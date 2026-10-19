"""Whether a session runs inside an autonomous autorun run, found through the autorun skill installed beside guard."""
import os
import sys


def autorun_scripts():
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (here, os.path.dirname(os.path.realpath(__file__))):
        scripts = os.path.normpath(os.path.join(base, "..", "..", "..", "autorun", "scripts"))
        if os.path.isfile(os.path.join(scripts, "autorun_lib", "store.py")):
            return scripts
    return None


def ask_command(agent, session):
    """The `autorun.py ask` prefix when this session belongs to an active run, else None."""
    scripts = autorun_scripts()
    if not scripts:
        return None
    sys.path.insert(0, scripts)
    from autorun_lib import store

    run, _ = store.lookup(agent, session)
    explicit = os.environ.get("AUTORUN_RUN")
    if not run and explicit and store.Run(explicit).active:
        run = store.Run(explicit)
    return f"python3 {os.path.join(scripts, 'autorun.py')} ask --run {run.id}" if run else None
