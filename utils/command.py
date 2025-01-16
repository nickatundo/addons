import pathlib
import sys

import gdb

def locate_api() -> None:
    udb_api_paths = [p for p in sys.path if p.endswith("src/udbpy/public_api")]
    if not udb_api_paths:
        # Not running under UDB
        raise ImportError

    # Some evil to allow this script to call internal udbpy stuff
    public_api_path = udb_api_paths[0]
    path = pathlib.Path(public_api_path).parent.parent.parent
    sys.path.append(str(path))

locate_api()
from src.udbpy.gdb_extensions import command, command_args, udb_base
from undo.debugger_extensions import udb
the_udb = udb._wrapped_udb

class AddonCommand:

    @staticmethod
    def invoke(self, *args, **kwargs) -> None:
        assert False, "Should be overridden"

    def __init__(self, name: str, command_class: int, 
                completer_class: int = gdb.COMPLETE_NONE, prefix=False) -> None:

        def wrap(udb: udb_base.Udb, args: str, *, 
                    original_command_name: str, from_tty: bool) -> None:
    
            self.__class__.invoke(args, from_tty)

        wrap.__name__ = name
        wrap.__doc__ = self.__doc__
        command.register(command_class,
                        arg_parser=command_args.Untokenized(),
                        completer=completer_class)(wrap)

