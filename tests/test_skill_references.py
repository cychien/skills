"""Every verify.py and guard.py command a skill text names is one the real CLI accepts, read from the CLI's own help."""
import functools
import pathlib
import re
import shlex
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = {"verify.py": ROOT / "skills" / "eng" / "verify" / "scripts" / "verify.py",
           "guard.py": ROOT / "skills" / "orchestrator" / "guard" / "scripts" / "guard.py"}
SPAN = re.compile(r"`([^`\n]+)`")
FENCE = re.compile(r"^\s*```")
SCRIPT_REF = re.compile(r"(<[^<>]*>/)?((?:[\w.-]+/)*)(verify\.py|guard\.py)(?: path>)?")
ALIAS = re.compile(r"^\s*([A-Za-z_]\w*)\s*\(\)\s*\{[^}]*\bguard\.py\b")
GUARD_WORDS = ("todo", "quota")
CHOICES = re.compile(r"^\s+\{([\w,-]+)\}\s*$", re.M)
OPTION = re.compile(r"^\s+(?:-\w, )?(--[\w-]+)", re.M)
FLAG = re.compile(r"^\[?(--[A-Za-z][\w-]*)")
SYNOPSIS = re.compile(r"^\s*(?:usage: )?verify\.py (\S+)(.*)$", re.M)
STOP = {"&&", "||", "|", ";", ">", "<", "2>&1"}


def documents():
    return sorted({*ROOT.glob("skills/**/SKILL.md"), *ROOT.glob("skills/**/references/*.md"), ROOT / "README.md"})


@functools.cache
def help_text(script, *path):
    out = subprocess.run([sys.executable, str(SCRIPTS[script]), *path, "--help"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout


def cli(script, *path):
    """(subcommand choices or None, options) of `<script> <path...>`, from its --help."""
    text = help_text(script, *path)
    choices = CHOICES.search(text.partition("positional arguments:")[2].partition("options:")[0])
    return (set(choices.group(1).split(",")) if choices else None), set(OPTION.findall(text))


@functools.cache
def verify_synopsis():
    """Flags each verify.py command's help synopsis lists; `<command>` holds the ones every command takes."""
    text = help_text("verify.py")
    usage = text[text.index("usage: verify.py"):].partition("\n\n")[0]
    synopsis = {}
    for command, rest in SYNOPSIS.findall(usage):
        synopsis.setdefault(command, set()).update(re.findall(r"--[\w-]+", rest))
    return synopsis


def owner(doc):
    """The skill folder a document belongs to."""
    path = doc.parent
    while path != ROOT and not (path / "SKILL.md").is_file():
        path = path.parent
    return path


def resolve(doc, placeholder, directory, script):
    """The CLI a script reference means: the named skill's own, else the document's skill's own, else the shared one.
    None when it names some other skill's script of the same name."""
    named = [p for p in directory.split("/") if p and p not in (".", "..", "scripts")]
    if named and not placeholder:
        skill = next(iter(ROOT.glob(f"skills/*/{named[-1]}")), None)
        if skill is not None:
            return script if (skill / "scripts" / script) == SCRIPTS[script] else None
    return None if (owner(doc) / "scripts" / script).is_file() and (owner(doc) / "scripts" / script) != SCRIPTS[script] else script


def tokens(text):
    try:
        words = shlex.split(text)
    except ValueError:
        words = [w.strip("\"'") for w in text.split()]
    out = []
    for word in words:
        if word in STOP:
            break
        out.append(word.rstrip(",.)\"'"))
    return out


def commands(doc):
    """(line number, script, words after the script) for every command the document names in backticks or code blocks."""
    aliases, fenced = set(), False
    for number, line in enumerate(doc.read_text().splitlines(), 1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced and (alias := ALIAS.match(line)):
            aliases.add(alias.group(1))
            continue
        candidates = [line.strip()] if fenced and "`" not in line else SPAN.findall(line)
        for text in candidates:
            refs = list(SCRIPT_REF.finditer(text))
            for ref in refs:
                if script := resolve(doc, *ref.groups()):
                    yield number, script, tokens(text[ref.end():])
            if refs:
                continue
            words = tokens(text)
            if words and words[0] in aliases:
                words = words[1:]
            if len(words) > 1 and words[0] in GUARD_WORDS:
                yield number, "guard.py", words


def placeholder(word):
    return word.startswith(("<", "[", "{", "$")) or word in ("...", "…")


def problems(script, words):
    """What the CLI would not accept in `<script> <words>`."""
    flags = [m.group(1) for w in words if (m := FLAG.match(w))]
    positional = [w for w in words if not w.startswith(("-", "[-"))]
    if script == "verify.py":
        choices, options = cli("verify.py")
        if not positional or placeholder(positional[0]):
            return []
        command = positional[0]
        if command not in choices:
            return [f"verify.py has no command {command!r}"]
        allowed = verify_synopsis().get(command, set()) | verify_synopsis().get("<command>", set())
        return [f"verify.py {command} takes no {flag}" for flag in flags if flag not in options or flag not in allowed]
    path = []
    for word in positional:
        choices, _ = cli("guard.py", *path)
        if choices is None or placeholder(word):
            break
        if word not in choices:
            return [f"{' '.join(['guard.py', *path])} has no command {word!r}"]
        path.append(word)
    choices, options = cli("guard.py", *path)
    if choices is not None:
        return []
    return [f"{' '.join(['guard.py', *path])} takes no {flag}" for flag in flags if flag not in options]


class SkillReferences(unittest.TestCase):
    def test_every_command_a_skill_names_is_one_the_cli_accepts(self):
        seen, wrong = 0, []
        for doc in documents():
            for number, script, words in commands(doc):
                seen += 1
                wrong += [f"{doc.relative_to(ROOT)}:{number}: {p}" for p in problems(script, words)]
        self.assertGreater(seen, 100)
        self.assertEqual(wrong, [])

    def test_the_verify_synopsis_names_only_real_commands_and_flags(self):
        choices, options = cli("verify.py")
        for command, flags in verify_synopsis().items():
            self.assertTrue(command == "<command>" or command in choices, command)
            self.assertLessEqual(flags, options, command)

    def test_a_wrong_command_or_flag_is_caught(self):
        self.assertEqual(problems("verify.py", ["report", "--write", "--author", "<a>"]), [])
        self.assertEqual(problems("verify.py", ["dryrun", "--base", "<w>", "--dir", "<d>"]), [])
        self.assertTrue(problems("verify.py", ["affected"]))
        self.assertTrue(problems("verify.py", ["report", "--kill"]))
        self.assertTrue(problems("verify.py", ["rerun", "--explain"]))
        self.assertEqual(problems("guard.py", ["todo", "done", "<n>", "--token", "<t>"]), [])
        self.assertEqual(problems("guard.py", ["quota", "pick", "--role", "executor", "[--avoid", "<a>]"]), [])
        self.assertTrue(problems("guard.py", ["todo", "done", "1", "--not-run", "x"]))
        self.assertTrue(problems("guard.py", ["todo", "finish", "1"]))
        self.assertTrue(problems("guard.py", ["quota", "pick", "--agent", "x"]))


if __name__ == "__main__":
    unittest.main()
