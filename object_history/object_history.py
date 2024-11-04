import pathlib
import sys
import tempfile
import gdb
import re

# Some evil to allow this script to call internal udbpy stuff
public_api_path = [p for p in sys.path if p.endswith("src/udbpy/public_api")][0]
path = pathlib.Path(public_api_path).parent.parent.parent
sys.path.append(str(path))
from src.udbpy import report, timeline
from undo.debugger_extensions import udb
the_udb = udb._wrapped_udb



def get_methods(clz: str) -> list[str]:
    """Get list of class methods from GDB."""
    out = gdb.execute(f"ptype {clz}", to_string=True)
    if not out.startswith("type = class"):
        raise ValueError
    
    # TODO: virtual methods, templates, inheritance, concepts, mysteries

    methods = []
    for l in out.splitlines():
        if ';' not in l:
            continue

        # Distinguish a method from a data member by expecting an identifier followed
        # immediately by an argument list in parentheses. 
        m = re.search(r"[a-zA-Z0-9_~]+\(.*\)", l)
        if m:
            methods.append(f"{clz}::{m[0]}")

    return methods


def get_scope(variable: str) -> str:
    start = None
    for line in gdb.execute("info locals", to_string=True).splitlines():
        if line.startswith(f"{variable} = "):
            start = gdb.selected_frame().name()
    for line in gdb.execute("info args", to_string=True).splitlines():
        if line.startswith(f"{variable} = "):
            start = gdb.selected_frame().name()

    # Didn't match in locals, assume it's global
    # TODO worry about namespaces

    if not start:
        # FIXME need a probe syntax for "start of recording" cos this doesn't always work
        t = the_udb.time.get()
        gdb.execute("ugo start", to_string=True)
        gdb.execute("si", to_string=True)
        addr = gdb.execute("p/x $pc", to_string=True)
        m = re.search(r"0x[0-9a-f]+", addr)
        assert m
        start = f"*{m[0]}"
        the_udb.time.goto(t)

    return start

def type_code_name(type_code: int) -> str:
    for name, value in gdb.__dict__.items():
        if not name.startswith("TYPE_CODE_"):
            continue
        if type_code == value:
            return name
    return "UNKNOWN"

def show_current_call() -> None:
    """Show current call in a nicer way than GDB's frame command."""
    

def _make_probe(target: str) -> str:
    # Try to identify scope
    start = get_scope(target)

    value = gdb.selected_frame().read_var(target)
    if target == "this":
        # "this" is more usefully interpreted as the current object not the pointer
        value = value.dereference()
    t = value.type.strip_typedefs()

    print(f"type of {target=} is {type_code_name(t.code)}")

    match t.code:
        case gdb.TYPE_CODE_BOOL | gdb.TYPE_CODE_CHAR | gdb.TYPE_CODE_FLT | gdb.TYPE_CODE_INT:
            # Simple values
            probe = f"{start} => watch {target} => log {target}\n"
        case gdb.TYPE_CODE_PTR:
            # Pointers are also simple
            # TODO handle "*foo" syntax
            tt = t.target()
            probe = f"{start} => watch {target} => log {target}\n"
            pass
        case gdb.TYPE_CODE_ARRAY:
            probe = f"{start} => watch {target} => log {target}\n"
            pass
        case gdb.TYPE_CODE_STRUCT:
            # Struct includes objects
            ms = get_methods(t.name)
            ps = []
            for method in ms:
                instance_method = f'{target}.{method.split("::")[-1]}'
                ps.append(f'{method} if this == &({target}) => python gdb.execute("frame")\n')
            probe = "".join(ps)
            pass
        case gdb.TYPE_CODE_UNION:
            pass
        case gdb.TYPE_CODE_ENUM:
            pass
        case gdb.TYPE_CODE_FLAGS:
            pass
        case gdb.TYPE_CODE_FUNC:
            pass
        case gdb.TYPE_CODE_VOID:
            pass
        case gdb.TYPE_CODE_STRING:
            pass
        case gdb.TYPE_CODE_METHOD:
            pass
        case gdb.TYPE_CODE_METHODPTR:
            pass
        case gdb.TYPE_CODE_MEMBERPTR:
            pass
        case gdb.TYPE_CODE_REF:
            pass
        case gdb.TYPE_CODE_RVALUE_REF:
            pass
        case gdb.TYPE_CODE_COMPLEX:
            pass
        case gdb.TYPE_CODE_TYPEDEF:
            pass
        case gdb.TYPE_CODE_NAMESPACE:
            pass
        case _:
            # Unknown
            print(f"Don't know how to handle type {t.code}")

    return probe

def get_current_state(state: str) -> str:
    output = gdb.execute(f"show {state}", to_string = True)
    m = re.search(r'"(.*)"', output)
    assert m
    return m[1]

def history(*targets: str) -> None:

    # TODO cope with expressions, not just variable names
    # TODO offer formatting choices (hex etc)
    # TODO offer filtering of method names by regex
    # TODO faster search (tracepoints?)
    # TODO better viz of data series (charts etc)
    # TODO limit execution time by wallclock or bbcount range
    # TODO remove the unwanted chat (eg Current time) in 'it' output
    # TODO don't change user's position in history
    # TODO don't change user's config settings
    # TODO be able to create probes without going via a file
    # TODO render fn arguments without using `frame`
    # TODO support tracking multiple values at once

    with tempfile.NamedTemporaryFile(delete=False) as probe_file:
        for target in targets:
            probe = _make_probe(target)
            probe_file.write(probe.encode())
        probe_file.close()

    frame_state = get_current_state("print frame-info")
    gdb.execute("set print frame-info short-location")
    my_timeline(probe_file.name)
    gdb.execute(f"set print frame-info {frame_state}")

def my_timeline(probe_file: str):
    pfl_result = the_udb.pfl.get_pfl_items(probe_file)
    pfl_items = pfl_result.items
    tl = timeline.Timeline(
        extent=the_udb.get_event_log_extent(),
        bookmarks=the_udb.bookmarks.iter_bookmarks(),
        is_live=the_udb.get_execution_mode().has_live_process,
        extra_items=pfl_items,
    )
    formatter = timeline.TimelineTerminalFormatter(tl)
    report.user(formatter.format())
