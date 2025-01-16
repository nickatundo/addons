
import re
import gdb
from addons.utils import locate_api
locate_api()
from src.udbpy import report, termstyles
from src.udbpy.gdb_extensions import command, command_args, gdbio, gdbutils, udb_base
from undo.debugger_extensions import udb
udb = udb._wrapped_udb  # pylint: disable=protected-access,redefined-outer-name

def _get_block_vars(frame: gdb.Frame, block: gdb.Block) -> dict[str, gdb.Value]:
    """Fetch all variable values for the given block."""

    vals = {var.print_name: var.value(frame) for var in block}

    # Force values to be evaluated from debuggee before we move in time
    for val in vals.values():
        val.fetch_lazy()

    return vals


def _get_local_vars(frame: gdb.Frame = None) -> dict[str, gdb.Value]:
    """Fetch all local variables in the given (or current) scope."""

    if frame is None:
        frame = gdbutils.newest_frame()
    block = frame.block()
    vals: dict[str, gdb.Value] = {}

    # Iterate out from the current block until function scope is reached.
    # Variables from each scope level are collected; in the event of a name
    # clash, the inner scope is preferred.
    while True:
        vals = _get_block_vars(frame, block) | vals
        if block.function:
            break
        assert block.superblock is not None
        block = block.superblock

    # Force values to be evaluated from debuggee now
    for val in vals.values():
        val.fetch_lazy()

    return vals

def _print(text: str)-> None:
    """Print variable changes in a consistent style."""
    report.user(text, foreground=termstyles.Color.CYAN)

def _print_var_diffs(before_vals: dict[str, gdb.Value], after_vals: dict[str, gdb.Value],
                     reverse_op: bool = False) -> None:
    changed_vals = {
        var: val for var, val in after_vals.items() if (var, val) not in before_vals.items()
    }
    arrow = "<-" if reverse_op else "->"
    for var, val in changed_vals.items():
        prev_val = before_vals.get(var, "")
        _print(f"{var} {prev_val} {arrow} {val}")


@command.register(
    gdb.COMMAND_STATUS,
)
def auto_locals_next(udb: udb_base.Udb) -> None:
    """
    Report variable changes as a result of running the current line.
    """

    # TODO: consider allowing user to specify command name
    # TODO: consider how to hook onto other commands

    with (
        gdbutils.breakpoints_suspended(),
        udb.replay_standard_streams.temporary_set(False),
        gdbio.CollectOutput(),
        udb.time.auto_reverting(),
    ):
        before_vals = _get_local_vars()

        udb.execution.next()
        after_vals = _get_local_vars()

    if before_vals or after_vals:
        _print_var_diffs(before_vals, after_vals)
    else:
        _print("No changes.")

forward_ops = ["c", "continue",
       "fin", "finish",
       "n", "next",
       "ni", "nexti",
       "s", "step",
       "si", "stepi",
       "until",
]
reverse_ops = [
       "rc", "reverse-continue",
       "rfin", "reverse-finish",
       "rn", "reverse-next",
       "rni", "reverse-nexti",
       "rs", "reverse-step",
       "rsi", "reverse-stepi",
       "reverse-until",
]

def _execution_op_with_locals(cmd: str, quiet: bool=False) -> None:
    """
    Perform a (reverse) execution operation showing locals before and after.
    """

    before_vals = _get_local_vars()
    frame = gdbutils.newest_frame()
    gdb.execute(cmd, to_string=True)
    if gdbutils.newest_frame() != frame:
        return
    after_vals = _get_local_vars()

    if before_vals == after_vals:
        if not quiet:
            report.user("No changes.")
    else:
        _print_var_diffs(before_vals, after_vals, cmd in reverse_ops)

@command.register(
    gdb.COMMAND_STATUS, arg_parser=command_args.Choice(forward_ops+reverse_ops)
)
def auto_locals(udb: udb_base.Udb, cmd: str) -> None:
    """
    Perform a (reverse) execution operation showing locals before and after.
    """
    _execution_op_with_locals(cmd)


@command.register(
    gdb.COMMAND_STATUS,
)
def auto_locals_function(udb: udb_base.Udb) -> None:
    """
    Step through the current function line by line, reporting changes to locals.
    """

    with (
        udb.time.auto_reverting(),
        gdbutils.temporary_parameter("print frame-info", "source-line"),
    ):
        # Find start of function
        with (
            gdbutils.breakpoints_suspended(),
            udb.replay_standard_streams.temporary_set(False),
            gdbio.CollectOutput(),
        ):
            udb.execution.reverse_finish(cmd="auto-locals-function")
            udb.execution.step()

        # Step through function
        # TODO: How to print out source line contents but no other info (e.g. what to do
        # at "Switching to record mode")
        frame = gdbutils.newest_frame()
        report.user(f"        {frame.name()}(...)")
        report.user("        {")
        while True:
            gdb.execute("frame")
            _execution_op_with_locals("next", quiet=True)
            if gdbutils.newest_frame() != frame:
                break

        report.user("        }")

def _interpolate(udb: udb_base.Udb, references: bool = False) -> None:
    """
    Step through the current function line by line, reporting changes to locals.
    """

    with (
        udb.time.auto_reverting(),
        gdbutils.temporary_parameter("print frame-info", "source-line"),
    ):
        # Find start of function
        with (
            gdbutils.breakpoints_suspended(),
            udb.replay_standard_streams.temporary_set(False),
            gdbio.CollectOutput(),
        ):
            udb.execution.reverse_finish(cmd="auto-locals-function")
            udb.execution.step()

        # Step through function
        # TODO: How to print out source line contents but no other info (e.g. what to do
        # at "Switching to record mode")
        frame = gdbutils.newest_frame()
        report.user(f"        {frame.name()}(...)")
        report.user("        {")
        while True:
            code_line = gdbutils.execute_to_string("frame")
            code_line = termstyles.strip_ansi_escape_codes(code_line)
            before_vals = _get_local_vars()
            frame = gdbutils.newest_frame()
            gdb.execute("next", to_string=True)
            if gdbutils.newest_frame() != frame:
                break
            after_vals = _get_local_vars()

            for name, value in after_vals.items():
                #report.user(f"{name} {value}")
                annotation = f"«{value}»"
                annotation = termstyles.ansi_format(
                    annotation, intensity=termstyles.Intensity.DIM
                )
                if references:
                    annotate_re =  fr"(?<!\.|\>)(?P<orig>\s*{name})(?![a-zA-Z0-9_])"
                    annotate_lambda = lambda m: f"{m['orig']} {annotation} "
                else:
                    annotate_re =  fr"(?<!\.|\>)(?P<orig>\s*{name})\s*=(?!=)"
                    annotate_lambda = lambda m: f"{m['orig']} {annotation} ="
                # The RE aims to recognise "foo=", but not "bar->foo=" or "foo=="
                code_line = re.sub(annotate_re, annotate_lambda, code_line)
            report.user(code_line)

        report.user("        }")

@command.register(gdb.COMMAND_STATUS)
def auto_locals_interpolate(udb: udb_base.Udb) -> None:
    """blah"""
    _interpolate(udb, references=False)

@command.register(gdb.COMMAND_STATUS)
def auto_locals_interpolate_refs(udb: udb_base.Udb) -> None:
    """blah"""
    _interpolate(udb, references=True)
