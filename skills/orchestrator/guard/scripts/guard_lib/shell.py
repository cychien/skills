"""What a shell line runs: the argv of each simple command, split the way a shell splits it.

Quotes and comments are respected, heredoc bodies are dropped, a reserved word such as `if` or `while` introduces the
command after it, and command substitutions and the program a shell runs with -c, or eval runs, count as commands too,
so a wrapper such as `bash -lc '...'` or `if ...; then` hides nothing while quoted text passed to any other program stays
an argument.
"""
import os
import re
import shlex

HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1([^\n]*)\n.*?\n\s*\2\b", re.S)
SEPARATORS = set(";&|\n()")
KEYWORDS = {"if", "then", "elif", "else", "while", "until", "do", "!", "{", "}", "coproc"}
REDIRECT = re.compile(r"^(?:\d+|&)?(?:<<<|>>|>&|>\||<>|<&|>|<)(.*)$")
PREFIXES = {"nohup", "exec", "command", "caffeinate", "sudo", "builtin"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
SHELL_VALUED = {"-o", "+o", "-O", "+O"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
DEPTH = 4
OPENERS = {"do", "then", "else", "elif", "{", "!"}
EXITS = {"break", "exit", "return"}
BODY_WORDS = OPENERS | {"if", "fi", "done"}
CHAINS = {"&&", "||", "|", "(", ")"}
LEADING_CD = re.compile(r"\s*cd\s+((?:'[^']*'|\"(?:[^\"\\]|\\.)*\"|\\.|[^\s;&|'\"\\])+)\s*(?:&&|;)")
LEADING_CD_WORD = re.compile(r"\s*cd(?:\s|;|&|$)")
UNKNOWN_TARGET = re.compile(r"[$`*?\[]")
UNQUOTED_TILDE = re.compile(r"^~[\w.-]*(?:/|$)")


def substitution(text, i):
    """(its body, the index just past it) for the command substitution that opens at text[i], a backtick or the $ of $(;
    an unclosed one runs to the end of the text."""
    if text[i] == "`":
        j = i + 1
        while j < len(text) and text[j] != "`":
            j += 2 if text[j] == "\\" else 1
        return text[i + 1:j], min(j + 1, len(text))
    depth, quote, j = 0, None, i + 1
    while j < len(text):
        c = text[j]
        if quote:
            if c == quote:
                quote = None
            elif c == "\\" and quote == '"':
                j += 1
        elif c == "\\":
            j += 1
        elif c in "'\"":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if not depth:
                return text[i + 2:j], j + 1
        j += 1
    return text[i + 2:], len(text)


def segments(line):
    """The text of each simple command in a shell line: split at ; & | newlines and parentheses outside quotes, with
    comments and heredoc bodies dropped, and the commands of each backtick or double-quoted $( ) substitution added."""
    found = []
    for text, _, substitutions in pieces(line):
        for body in substitutions:
            found += segments(body)
        found.append(text)
    return [s for s in found if s.strip()]


def pieces(line):
    """(text, the operator after it, the substitution bodies inside it) for each simple command of a shell line, in order;
    the operator is ;, &, &&, |, ||, a newline, a parenthesis, or '' at the end."""
    text = HEREDOC.sub(lambda m: m.group(3), line or "")
    found, current, inner, quote, i = [], [], [], None, 0

    def close(op):
        nonlocal current, inner
        piece = "".join(current)
        if piece.strip() or inner:
            found.append([piece, op, inner])
        elif found and found[-1][1] in "()":
            found[-1][1] = op
        current, inner = [], []

    while i < len(text):
        c = text[i]
        if quote != "'" and (c == "`" or (quote == '"' and text.startswith("$(", i) and not text.startswith("$((", i))):
            body, end = substitution(text, i)
            inner.append(body)
            current.append(text[i:end])
            i = end
            continue
        if quote:
            current.append(c)
            if c == quote:
                quote = None
            elif c == "\\" and quote == '"' and i + 1 < len(text):
                current.append(text[i + 1])
                i += 1
        elif c == "\\" and i + 1 < len(text):
            current += [c, text[i + 1]]
            i += 1
        elif c in "'\"":
            quote = c
            current.append(c)
        elif c == "#" and (not current or current[-1].isspace()):
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
            continue
        elif c == "&" and ((current and current[-1] in "<>") or text[i + 1:i + 2] == ">"):
            current.append(c)
        elif c in SEPARATORS:
            op = text[i:i + 2] if text[i:i + 2] in ("&&", "||") else c
            close(op)
            i += len(op)
            continue
        else:
            current.append(c)
        i += 1
    close("")
    return [tuple(piece) for piece in found]


def argv(segment):
    """The argv a simple command runs, past reserved words, assignments, redirections and wrappers such as env, nohup, time
    and timeout; [] when the segment does not parse."""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return []
    while tokens:
        first = tokens[0]
        if first in KEYWORDS or first in PREFIXES or ASSIGNMENT.match(first):
            tokens = tokens[1:]
        elif first == "env":
            tokens = tokens[1:]
            while tokens and (tokens[0].startswith("-") or ASSIGNMENT.match(tokens[0])):
                tokens = tokens[2:] if tokens[0] in ("-u", "-C", "-S") else tokens[1:]
        elif first == "time":
            tokens = tokens[1:]
            while tokens and tokens[0].startswith("-"):
                tokens = tokens[1:]
        elif first == "function":
            tokens = tokens[2:]
        elif redirect := REDIRECT.match(first):
            tokens = tokens[1:] if redirect.group(1) else tokens[2:]
        elif first == "timeout":
            tokens = tokens[1:]
            while tokens and tokens[0].startswith("-"):
                tokens = tokens[2:] if tokens[0] in ("-s", "-k") else tokens[1:]
            tokens = tokens[1:]
        else:
            break
    return tokens


def program(tokens):
    """The shell text this command hands to a nested shell: a shell's -c program, or eval's arguments; else None."""
    if not tokens:
        return None
    if tokens[0] == "eval":
        return " ".join(tokens[1:]) or None
    if os.path.basename(tokens[0]) not in SHELLS:
        return None
    rest, runs_c = tokens[1:], False
    while rest and rest[0][:1] in "-+" and rest[0] not in ("-", "--"):
        option = rest.pop(0)
        if option in SHELL_VALUED:
            rest = rest[1:]
        elif not option.startswith("--") and "c" in option[1:]:
            runs_c = True
    return rest[0] if runs_c and rest else None


def commands(line, depth=0):
    """The argv of every simple command a shell line runs, nested shell programs included."""
    found = []
    for segment in segments(line):
        tokens = argv(segment)
        if not tokens:
            continue
        found.append(tokens)
        nested = program(tokens)
        if nested and depth < DEPTH:
            found += commands(nested, depth + 1)
    return found


def script(tokens):
    """(the script a command runs, its arguments): argv[0], or the first argument of a python interpreter."""
    first = os.path.basename(tokens[0])
    if re.fullmatch(r"python[\d.]*", first):
        args = tokens[1:]
        while args and args[0].startswith("-") and args[0] not in ("-c", "-m"):
            args = args[1:]
        if args and args[0] not in ("-c", "-m"):
            return os.path.basename(args[0]), args[1:]
    return first, tokens[1:]


def invocations(line, name):
    """The arguments of each command in a shell line that runs the script name."""
    return [rest for found, rest in map(script, commands(line)) if found == name]


def workdir(line, cwd):
    """The directory a shell line's commands run in: cwd moved by each leading `cd <dir> &&` or `cd <dir>;`, or None when
    a leading cd goes where only the shell can know (`cd -`, a variable, a substitution, a glob, an option)."""
    directory, at, line = cwd, 0, line or ""
    while LEADING_CD_WORD.match(line, at):
        found = LEADING_CD.match(line, at)
        if not found or UNKNOWN_TARGET.search(found.group(1)):
            return None
        try:
            target = shlex.split(found.group(1))[0]
        except (ValueError, IndexError):
            return None
        if target.startswith("-"):
            return None
        if UNQUOTED_TILDE.match(found.group(1)):
            target = os.path.expanduser(target)
        directory = os.path.normpath(os.path.join(directory or ".", target))
        at = found.end()
    return directory


class Loop:
    """A while or until loop of a shell line: the argv of each command in its condition and in its body, and of each body
    command whose status decides whether the loop ends: one chained to a break or an exit, or the test of an if that
    breaks."""

    def __init__(self, keyword):
        self.keyword, self.condition, self.body, self.exits = keyword, [], [], []
        self.in_body, self.chain, self.ifs = False, [], []

    def add(self, found, op):
        """The commands of one piece of the line, and the operator after it."""
        if not self.in_body:
            self.condition += found
            return
        self.body += found
        if self.ifs and self.ifs[-1]["testing"]:
            self.ifs[-1]["test"] += found
        if any(tokens[0] in EXITS for tokens in found):
            self.exits += [tokens for tokens in self.chain + found if tokens[0] not in EXITS]
            if self.ifs:
                self.ifs[-1]["breaks"] = True
        self.chain = self.chain + found if op in CHAINS else []

    def reserved(self, word):
        """Follow the if, then, elif and fi words of the body, so an if's test decides the exit when a branch breaks."""
        if not self.in_body:
            return
        if word == "if":
            self.ifs.append({"testing": True, "test": [], "breaks": False})
        elif word == "elif" and self.ifs:
            self.ifs[-1]["testing"] = True
        elif word in ("then", "else") and self.ifs:
            self.ifs[-1]["testing"] = False
        elif word == "fi" and self.ifs:
            closed = self.ifs.pop()
            if closed["breaks"]:
                self.exits += closed["test"]
                if self.ifs:
                    self.ifs[-1]["breaks"] = True
        self.chain = []

    def deciding(self):
        """The commands whose status decides whether the loop ends."""
        return self.condition + self.exits


def loops(line, depth=0):
    """Each while or until loop a shell line runs, nested loops and those in nested shell programs included."""
    found, open_loops = [], []
    for text, op, substitutions in pieces(line):
        try:
            words = shlex.split(text)
        except ValueError:
            words = []
        while words[:1] and words[0] in BODY_WORDS and open_loops:
            if words[0] == "do":
                open_loops[-1].in_body = True
            elif words[0] == "done":
                closed = open_loops.pop()
                found += [closed] if closed.keyword in ("while", "until") else []
            else:
                open_loops[-1].reserved(words[0])
            words = words[1:]
        while words[:1] and words[0] in BODY_WORDS:
            words = words[1:]
        if words[:1] in (["while"], ["until"], ["for"], ["select"]):
            if open_loops:
                open_loops[-1].chain = []
            open_loops.append(Loop(words[0]))
        here = [t for t in [argv(text), *(c for body in substitutions for c in commands(body, depth + 1))] if t and t[0] not in BODY_WORDS]
        for loop in open_loops[:-1]:
            loop.body += here if loop.in_body else []
        if open_loops and here:
            open_loops[-1].add(here, op)
        nested = program(argv(text))
        if nested and depth < DEPTH:
            found += loops(nested, depth + 1)
    return found + [loop for loop in open_loops if loop.keyword in ("while", "until")]


def line(words):
    """The shell line an argv list runs: a shell's -c program itself, else the words quoted back into one line."""
    words = [str(w) for w in words]
    return program(words) or shlex.join(words)
