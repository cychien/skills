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


def active_run(agent, session):
    """The active autorun run this session belongs to, else None."""
    scripts = autorun_scripts()
    if not scripts:
        return None
    sys.path.insert(0, scripts)
    from autorun_lib import store

    run, _ = store.lookup(agent, session)
    explicit = os.environ.get("AUTORUN_RUN")
    if not run and explicit and store.Run(explicit).active:
        run = store.Run(explicit)
    return run


def ask_command(run):
    return f"python3 {os.path.join(autorun_scripts(), 'autorun.py')} ask --run {run.id}"


def waiting_on_user(run):
    """Whether the run escalated a question to the user that is not answered yet."""
    return bool(run.gates("open", "asked"))
