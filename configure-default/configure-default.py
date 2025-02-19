import os
import stat
import tempfile
import textwrap
from pathlib import Path

import gdb
from src.udbpy import cfg, locations, report, ui
from src.udbpy.gdb_extensions import command, udb_base


@command.register(
    gdb.COMMAND_STATUS,
)
def configure_default(udb: udb_base.Udb) -> None:
    """
    [Not really to be a command, just a handy wrapper for now]
    """

    if not ui.get_user_confirmation(
        "Would you like to make all the Undo tools available on your path?",
        default=False,
    ):
        return

    version = cfg.get().build_id_version
    fragment = textwrap.dedent(
        f"""
        #--- Added by Undo {version}
        export PATH={locations.top_level_install_dir.resolve()}:$PATH
        #---
    """
    )

    profile = Path.home() / ".profile"

    if not Path.home().stat().st_mode & stat.S_IWUSR:
        report.user("Home directory is not writable.")
        return

    if not profile.exists():
        profile.write_text(fragment)
        report.user(f'Created {profile}. Delete the "Added by Undo" section to revert.')
        return

    mode = profile.stat().st_mode
    if not mode & stat.S_IWUSR:
        report.user(f"{profile} is not writable.")
        return

    profile_content = profile.read_text()

    if "Added by Undo" in profile_content:
        # TODO try harder to handle this case?
        report.user(f"{profile} already contains code to set the path.")
        return

    with tempfile.NamedTemporaryFile("w+", dir=Path.home(), delete=False) as new_profile:
        new_name = new_profile.name
        os.chmod(new_name, mode)
        new_profile.write(profile_content)
        new_profile.write(fragment)

    os.replace(new_name, profile)
    report.user(f'Modified {profile}. Delete the "Added by Undo" section to revert.')


@command.register(
    gdb.COMMAND_STATUS,
)
def configure_gdb(udb: udb_base.Udb) -> None:
    """
    [Not really to be a command, just a handy wrapper for now]
    """

    if not ui.get_user_confirmation(
        "Would you like to launch UDB when you type 'gdb'?", default=False
    ):
        return

    local_bin = Path.home() / ".local" / "bin"
    if local_bin not in (Path(p).resolve() for p in os.get_exec_path()):
        report.user(f"{local_bin} is not on your path.")

    gdb_springboard = local_bin / "gdb"
    if gdb_springboard.exists():
        report.user(f"{gdb_springboard} already exists.")
        return

    version = cfg.get().build_id_version
    gdb_springboard_content = textwrap.dedent(
        f"""
        #! /bin/bash
        # Created by Undo {version}
        {locations.udb_executable.resolve()}
        """
    ).lstrip()
    gdb_springboard.write_text(gdb_springboard_content)
    gdb_springboard.chmod(0o755)
    report.user(f"Created {gdb_springboard}.")
