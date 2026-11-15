#!/usr/bin/env python3
"""PreToolUse guard (Bash): stops commands that can delete a lot of data in one go.

Written after 15 Nov 2026, when `rsync --delete` from a partial copy wiped 6 of 8 research folders.
Blocks, unless the command contains the literal marker  # I-CHECKED-DRY-RUN :
  - rsync with any --delete* / --del flag (a dry run with -n / --dry-run passes)
  - rclone sync / bisync / purge (a --dry-run passes)
  - git clean with -f together with -d or -x (wipes untracked data; -n passes)
  - rm -r / -rf aimed at a whole project root: ~, ~/code, ~/code/*, ~/code/*/* (also / and /home)
Tests: test-delete-guard.sh next to this file in ~/code/linux-setup/claude/hooks/.
"""
import json, os, re, sys

MARKER = "# I-CHECKED-DRY-RUN"
HOME = os.path.expanduser("~")
TEXT_TOOLS = {"grep", "egrep", "fgrep", "rg", "ag", "ack", "echo", "printf", "cat", "less", "head", "tail",
              "sed", "awk", "man", "which", "type", "file", "wc", "jq", "diff"}
RUNNERS = {"ssh", "bash", "sh", "zsh", "dash", "eval"}
QUOTED = re.compile(r"'([^']*)'|\"((?:[^\"\\]|\\.)*)\"")

def split_top(cmd):
    """Split a shell command on ; && || | newline ( ) ` $( , but never inside quotes."""
    segs, cur, q, i = [], [], None, 0
    while i < len(cmd):
        c = cmd[i]
        if q:
            cur.append(c)
            if c == "\\" and q == '"' and i + 1 < len(cmd): cur.append(cmd[i + 1]); i += 1
            elif c == q: q = None
        elif c in "'\"": q = c; cur.append(c)
        elif cmd.startswith(("&&", "||", "$("), i): segs.append("".join(cur)); cur = []; i += 2; continue
        elif c in ";|\n()`": segs.append("".join(cur)); cur = []
        else: cur.append(c)
        i += 1
    segs.append("".join(cur))
    return segs

def block(what):
    sys.stderr.write(
        f"DELETE GUARD: blocked {what}.\n"
        "This can remove many files at once (an rsync --delete wiped 6 of 8 research folders on 15 Nov 2026).\n"
        "Do this instead: 1) run the same command as a dry run first (rsync -n --itemize-changes, "
        "rclone --dry-run, git clean -n, or `du -sh`/`find | wc -l` of what rm would remove); "
        "2) show Eitan the exact delete count and paths; 3) get his explicit yes. "
        f"Only then rerun it with the marker `{MARKER}` at the end of the command. Never add the marker without his yes.\n")
    sys.exit(2)

def is_dry(seg):
    return bool(re.search(r"--dry-run\b|(^|\s)-[a-zA-Z]*n[a-zA-Z]*(\s|$)", seg))

def protected(path):
    p = os.path.normpath(path)
    while True:   # rm -rf dir/* or dir/. wipes dir itself for our purposes
        q = re.sub(r"/(\.\*|\*|\.)$", "", p)
        if q == p: break
        p = q or "/"
    if p in ("/", "/home", HOME, HOME + "/code"):
        return True
    if p.startswith(HOME + "/code/"):
        return len(p[len(HOME) + 6:].split("/")) <= 2
    return False

def check(cmd, cwd, depth=0):
    for seg in split_top(cmd):
        s = seg.replace("'", " ").replace('"', " ").strip()
        if not s: continue
        toks = s.split()
        if os.path.basename(toks[0]) in RUNNERS and depth < 3:
            # ssh host 'cmd', bash -c "cmd": the quoted part is a command of its own; judge it as one
            for a, b in QUOTED.findall(seg):
                check(a or b, HOME if os.path.basename(toks[0]) == "ssh" else cwd, depth + 1)
            s = QUOTED.sub(" ", seg).strip()
            toks = s.split()
            if not toks: continue
        if toks[0] == "cd" and len(toks) > 1:
            t = toks[1].replace("$HOME", HOME).replace("${HOME}", HOME)
            cwd = os.path.join(cwd, os.path.expanduser(t)); continue
        if os.path.basename(toks[0]) in TEXT_TOOLS:
            continue   # searching for or printing these words is not running them
        m = re.search(r"\bgit\b.*\bclean\b(.*)", s)
        if m:
            fl = "".join(re.findall(r"(?:^|\s)-([a-zA-Z]+)", m.group(1)))
            if "f" in fl and ("d" in fl or "x" in fl or "X" in fl) and "n" not in fl and "--dry-run" not in m.group(1):
                block("git clean -f with -d/-x (removes untracked files)")
        if toks[0] == "git":
            continue   # other git commands (commit messages etc.) only carry text
        m = re.search(r"\brsync\b(.*)", s)
        rs_args = m.group(1) if m else (s if toks[0].startswith("$") and re.search(r"\brsync\b", cmd) else "")
        if re.search(r"--del(ete[\w-]*)?\b", rs_args) and not is_dry(rs_args):
            block("an rsync with a --delete flag")
        if re.search(r"\brclone\b.*\b(sync|bisync|purge)\b", s) and not re.search(r"--dry-run\b", s):
            block("rclone sync/bisync/purge")
        for i, t in enumerate(toks):
            if t not in ("rm", "/bin/rm", "/usr/bin/rm"): continue
            args = toks[i + 1:]
            rec, targets, opts = False, [], True
            for a in args:
                if a in (">", ">>", "2>", "&>") or a.startswith(("2>", ">")): break
                if opts and a == "--": opts = False; continue
                if opts and a.startswith("--"):
                    rec |= a == "--recursive"; continue
                if opts and a.startswith("-") and len(a) > 1:
                    rec |= "r" in a or "R" in a; continue
                targets.append(a)
            if not rec: continue
            for t in targets:
                t = t.replace("${HOME}", HOME).replace("$HOME", HOME)
                if "$" in t: continue   # unresolvable variable: not judged here
                t = os.path.expanduser(t)
                if not t.startswith("/"): t = os.path.join(cwd, t)
                if protected(t):
                    block(f"rm -r of a whole project root or above ({os.path.normpath(t)})")

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if data.get("tool_name") != "Bash":
    sys.exit(0)
cmd = (data.get("tool_input") or {}).get("command") or ""
if MARKER in cmd or not re.search(r"\b(rsync|rclone|rm|clean)\b|--del", cmd):
    sys.exit(0)
check(cmd, data.get("cwd") or os.getcwd())
sys.exit(0)
