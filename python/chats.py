#!/usr/bin/env python3
"""
chats — an interactive board for organizing your Claude Code chats into categories.

Self-contained, standard-library only (uses curses). It only READS your chat files
under ~/.claude/projects and stores your category tags in its own file
(~/.claude/chats/categories.json). Deleting ~/.claude/chats removes the tool with
zero effect on your actual chats.

Keys:
  ↑/↓ or k/j   move selection
  Enter        open the chat — attaches if it's a live agent (Ctrl+Z to detach,
               keeps running), otherwise resumes a finished chat. On a section
               header, Enter (or Space) collapses/expands that section.
  Space        collapse/expand the section header your cursor is on
  n            start a new chat as a background agent — leave with Ctrl+Z and
               it keeps running (just like attaching to an existing agent)
  r            rename the selected chat
  f            fork a copy of the selected chat
  x            stop the selected live agent
  1..5         file the selected chat into a category
  P            projects panel — switch active project, add a folder, rename,
               remove. The active project filters the board and is where new
               chats start.
  d            delete the selected chat permanently (asks to confirm)
  Ctrl+R       reload this script (pick up edits without restarting)
  q            quit
"""

import curses
import fcntl
import json
import locale
import os
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import time
import tty
from pathlib import Path

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

locale.setlocale(locale.LC_ALL, "")

HOME = Path.home()
PROJECTS_DIR = HOME / ".claude" / "projects"
STORE = HOME / ".claude" / "chats" / "categories.json"

# Category order shown on the board. "Uncategorized" is the landing bucket for
# any chat you haven't filed yet; the 5 real categories map to number keys 1-5.
UNCATEGORIZED = "Uncategorized"
CATEGORIES = [
    "In Progress",
    "Later",
    "Failed",
    "Done — Not Committed",
    "Done",
]
DISPLAY_ORDER = [UNCATEGORIZED] + CATEGORIES

# color pair index per category (filled in setup_colors)
CAT_COLOR = {
    UNCATEGORIZED: 1,
    "In Progress": 9,  # blue
    "Later": 3,
    "Failed": 4,
    "Done — Not Committed": 5,
    "Done": 6,
}


def _load_json(path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}
    return {}


def _atomic_write_json(path, data):
    """Write JSON atomically (temp file + rename) so a concurrent reader never
    sees a partial file and a crash can't corrupt it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def _json_set(path, key, value):
    """Locked read-modify-write of one key in a JSON dict file, so multiple
    `claude-c` instances can't lose each other's edits. value=None deletes the
    key. Returns the merged dict."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(f"{path.name}.lock")
    with open(lock, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            d = _load_json(path)
            if value is None:
                d.pop(key, None)
            else:
                d[key] = value
            _atomic_write_json(path, d)
            return d
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def _json_update(path, fn):
    """Locked read-modify-write of a whole JSON dict (fn mutates it in place)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(f"{path.name}.lock")
    with open(lock, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            d = _load_json(path)
            fn(d)
            _atomic_write_json(path, d)
            return d
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def load_store():
    return _load_json(STORE)


PROJECTS_STORE = HOME / ".claude" / "chats" / "projects.json"
COLLAPSE_STORE = HOME / ".claude" / "chats" / "collapsed.json"


def _text_from_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for x in content:
            if isinstance(x, dict) and x.get("type") == "text":
                parts.append(x.get("text", ""))
            elif isinstance(x, dict) and "text" in x:
                parts.append(x.get("text", ""))
        return " ".join(parts)
    return ""


def _is_noise(text):
    t = text.strip()
    if not t:
        return True
    noise_prefixes = ("<command", "<system-reminder", "Caveat:", "<local-command",
                      "[Request interrupted", "<bash-")
    return t.startswith(noise_prefixes)


def parse_chat(path):
    """Return dict(id, cwd, title, ai_title, mtime) or None if unreadable/empty."""
    session_id = path.stem
    cwd = None
    title = None
    ai_title = None
    try:
        with path.open() as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if not isinstance(d, dict):
                    continue
                if cwd is None and d.get("cwd"):
                    cwd = d["cwd"]
                # Claude's own generated session name lives on an "ai-title" line.
                if ai_title is None and d.get("type") == "ai-title" and d.get("aiTitle"):
                    ai_title = " ".join(str(d["aiTitle"]).split())[:90]
                if title is None and d.get("type") == "user":
                    txt = _text_from_content(d.get("message", {}).get("content"))
                    if not _is_noise(txt):
                        title = " ".join(txt.split())[:90]
                if cwd is not None and title is not None and ai_title is not None:
                    break
    except Exception:
        return None
    if title is None:
        title = "(no readable messages)"
    return {
        "id": session_id,
        "cwd": cwd or "(unknown)",
        "title": title,
        "ai_title": ai_title,
        "mtime": path.stat().st_mtime,
        "path": path,
    }


def scan_chats():
    chats = []
    if not PROJECTS_DIR.exists():
        return chats
    for proj in PROJECTS_DIR.iterdir():
        if not proj.is_dir():
            continue
        for f in proj.glob("*.jsonl"):
            c = parse_chat(f)
            if c:
                chats.append(c)
    chats.sort(key=lambda c: c["mtime"], reverse=True)
    return chats


JOBS_DIR = HOME / ".claude" / "jobs"
CLAUDE_JSON = HOME / ".claude.json"

# live Claude-side status -> (icon glyph, color pair)
STATUS_ICON = {
    "running":     ("●", 9),  # blue    — in progress / actively working
    "needs_input": ("◆", 2),  # yellow  — waiting on you
    "done":        ("✓", 6),  # green   — finished
    "failed":      ("✗", 4),  # red     — errored out
    "unknown":     ("·", 8),  # dim     — no signal / closed
}

# Running chats get a moving-dot animation; everything else is a static glyph.
# All cells are exactly 3 columns wide so titles stay aligned.
_RUN_FRAMES = ("●··", "·●·", "··●", "·●·")


def status_cell(status, frame):
    if status == "running":
        return _RUN_FRAMES[frame % len(_RUN_FRAMES)]
    return f"{STATUS_ICON.get(status, STATUS_ICON['unknown'])[0]}  "


def agents_active():
    """Authoritative set of currently-live background agents, straight from
    Claude itself. These are exactly the sessions `claude --resume` refuses
    (must fork/attach). Returns sessionId -> record. Empty on any failure."""
    try:
        out = subprocess.run(["claude", "agents", "--json"],
                             capture_output=True, text=True, timeout=8)
        if out.returncode != 0:
            return {}
        data = json.loads(out.stdout or "[]")
    except Exception:
        return {}
    return {x["sessionId"]: x for x in data
            if isinstance(x, dict) and x.get("sessionId")}


def job_tempo_map():
    """sessionId -> (state, tempo) from job state files, for richer status
    (the 'blocked' tempo is how we detect 'needs input')."""
    m = {}
    if JOBS_DIR.exists():
        for d in JOBS_DIR.iterdir():
            sf = d / "state.json"
            if not sf.exists():
                continue
            try:
                s = json.loads(sf.read_text())
            except Exception:
                continue
            sid = s.get("sessionId")
            if sid:
                m[sid] = (s.get("state"), s.get("tempo"))
    return m


def resolve_status(sid, active, jobs):
    """Status icon for a chat. running/needs_input only count if the session is
    genuinely a live agent (in `active`); otherwise it's closed -> done/failed."""
    if sid in active:
        state, tempo = jobs.get(sid, (None, None))
        if tempo == "blocked":
            return "needs_input"
        if tempo == "active":
            return "running"
        a = active[sid]
        if a.get("status") == "busy":
            return "running"
        if a.get("state") == "failed" or state == "failed":
            return "failed"
        return "done"  # live agent, just idle
    state, _ = jobs.get(sid, (None, None))
    if state == "failed":
        return "failed"
    return "done"


def short_id(full_id, active):
    """The 8-char id `claude attach`/`claude stop` expect (not the full UUID)."""
    rec = active.get(full_id)
    if rec and rec.get("id"):
        return rec["id"]
    return full_id.split("-")[0]


def stop_agent(short):
    """Stop a background agent via Claude's own command. Returns True on success
    (or if it was already gone)."""
    try:
        out = subprocess.run(["claude", "stop", short],
                             capture_output=True, text=True, timeout=20)
    except Exception:
        return False
    txt = (out.stdout + out.stderr).lower()
    return out.returncode == 0 or "stopped" in txt or "no job matching" in txt


def ensure_trusted(cwd):
    """Mark a directory as trusted in ~/.claude.json so Claude doesn't show the
    'do you trust this folder?' dialog on every launch. Locked + atomic so
    parallel `claude-c` launches (and Claude itself) don't corrupt the file."""
    if not cwd or not os.path.isdir(cwd) or not CLAUDE_JSON.exists():
        return
    # Fast path: already trusted -> no write, no lock.
    try:
        d = json.loads(CLAUDE_JSON.read_text())
        if d.get("projects", {}).get(cwd, {}).get("hasTrustDialogAccepted") is True:
            return
    except Exception:
        return
    lock = CLAUDE_JSON.with_name(f"{CLAUDE_JSON.name}.lock")
    try:
        with open(lock, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                d = json.loads(CLAUDE_JSON.read_text())  # re-read under lock
                entry = d.setdefault("projects", {}).setdefault(cwd, {})
                if entry.get("hasTrustDialogAccepted") is True:
                    return
                entry["hasTrustDialogAccepted"] = True
                _atomic_write_json(CLAUDE_JSON, d)
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)
    except Exception:
        pass


NAMES_STORE = HOME / ".claude" / "chats" / "names.json"


def load_names():
    return _load_json(NAMES_STORE)


def claude_names():
    """sessionId -> Claude's own auto-generated session name (from job files)."""
    m = {}
    if JOBS_DIR.exists():
        for d in JOBS_DIR.iterdir():
            sf = d / "state.json"
            if not sf.exists():
                continue
            try:
                s = json.loads(sf.read_text())
            except Exception:
                continue
            sid, name = s.get("sessionId"), s.get("name")
            if sid and name:
                m[sid] = name
    return m


def setup_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, -1)    # Uncategorized
    curses.init_pair(2, curses.COLOR_YELLOW, -1)   # In Progress
    curses.init_pair(3, curses.COLOR_CYAN, -1)     # Later
    curses.init_pair(4, curses.COLOR_RED, -1)      # Failed
    curses.init_pair(5, curses.COLOR_MAGENTA, -1)  # Done — Not Committed
    curses.init_pair(6, curses.COLOR_GREEN, -1)    # Done
    curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_WHITE)  # selection
    curses.init_pair(8, curses.COLOR_WHITE, -1)    # dim/help
    curses.init_pair(9, curses.COLOR_BLUE, -1)     # In Progress / running


class App:
    def __init__(self, stdscr, select_id=None):
        self.stdscr = stdscr
        self.store = load_store()
        self.names = load_names()  # sessionId -> user's custom name
        self._chat_cache = {}   # path -> parsed chat dict (title/cwd are stable)
        self.all_chats = []
        self.rescan()           # populate self.all_chats from disk
        self.live = {}          # sessionId -> status icon key
        self.live_ids = set()   # sessions Claude treats as live agents
        self.cnames = {}        # sessionId -> Claude's auto name
        self._agents = {}       # cached agents_active() result
        self._agents_ts = 0.0
        self.anim = 0           # animation frame counter (running-dot spinner)
        self._live_ts = 0.0     # last status-data refresh time
        self._scan_ts = 0.0     # last chat-file rescan time
        self._reselect_id = None  # keep cursor on this chat after a rescan
        self.refresh_live(force=True)
        pj = _load_json(PROJECTS_STORE)
        self.projects_added = pj.get("list", {})   # path -> custom display name
        if "active" not in pj:                      # first run -> default to home
            self.active_project = str(HOME)
        else:                                       # "__all__" means user chose All
            a = pj["active"]
            self.active_project = None if a in (None, "__all__") else a
        self.collapsed = set(_load_json(COLLAPSE_STORE).get("collapsed", []))
        self.start_cwd = os.environ.get("CHATS_LAUNCH_CWD") or os.getcwd()
        self.sel = 0           # index into self.flat (chat rows only)
        self.scroll = 0
        self.message = ""
        self.resume_target = None  # set on Enter -> handled after curses ends
        self.resume_action = "resume"  # 'resume' | 'fork' | 'attach'
        self.new_chat = False  # set on 'n' -> start a fresh session
        self.reload = False  # set on 'r' -> re-exec the script to pick up edits
        self._want_select = select_id  # reposition cursor here on first draw
        self._positioned = False

    def _blocking_getch(self):
        self.stdscr.timeout(-1)
        try:
            return self.stdscr.getch()
        finally:
            self.stdscr.timeout(350)

    def display_title(self, chat):
        """What to show for a chat: your custom name > Claude's auto name >
        first user message (fallback). Claude uses the short id as a placeholder
        name until it auto-names a fresh chat, so we skip id-like names."""
        sid = chat["id"]
        if self.names.get(sid):
            return self.names[sid]

        def _real(name):
            if not name:
                return None
            if name == sid or name == sid.split("-")[0]:
                return None
            if re.fullmatch(r"[0-9a-f]{8}", name):  # bare hex placeholder
                return None
            return name

        rec = self._agents.get(sid)
        return (_real(rec.get("name") if rec else None)
                or _real(self.cnames.get(sid))
                or _real(chat.get("ai_title"))
                or chat["title"])

    def _read_line(self, prompt, initial=""):
        """Bottom-bar text input with cursor movement. Returns the string on
        Enter, or None on Esc. Supports ←/→, Home/End, Backspace, Delete."""
        curses.curs_set(1)
        self.stdscr.timeout(-1)
        buf = list(initial)
        pos = len(buf)  # cursor index within buf
        try:
            while True:
                h, w = self.stdscr.getmaxyx()
                s = (prompt + "".join(buf))[: w - 1]
                self.stdscr.move(h - 1, 0)
                self.stdscr.clrtoeol()
                self.stdscr.addstr(h - 1, 0, s, curses.A_BOLD)
                self.stdscr.move(h - 1, min(len(prompt) + pos, w - 1))
                self.stdscr.refresh()
                k = self.stdscr.getch()
                if k == 27:  # Esc alone -> cancel; or start of an arrow sequence
                    self.stdscr.nodelay(True)
                    seq = []
                    while len(seq) < 3:
                        nx = self.stdscr.getch()
                        if nx == -1:
                            break
                        seq.append(nx)
                        if seq[-1] in (ord("D"), ord("C"), ord("H"), ord("F")):
                            break
                    self.stdscr.nodelay(False)
                    if not seq:
                        return None  # real Esc -> cancel
                    code = seq[-1]
                    if code == ord("D"):      # left
                        pos = max(0, pos - 1)
                    elif code == ord("C"):    # right
                        pos = min(len(buf), pos + 1)
                    elif code == ord("H"):    # home
                        pos = 0
                    elif code == ord("F"):    # end
                        pos = len(buf)
                    continue
                if k in (curses.KEY_ENTER, 10, 13):
                    return "".join(buf).strip()
                if k in (curses.KEY_BACKSPACE, 127, 8):
                    if pos > 0:
                        buf.pop(pos - 1)
                        pos -= 1
                elif k == curses.KEY_DC:  # Delete
                    if pos < len(buf):
                        buf.pop(pos)
                elif k == curses.KEY_LEFT:
                    pos = max(0, pos - 1)
                elif k == curses.KEY_RIGHT:
                    pos = min(len(buf), pos + 1)
                elif k == curses.KEY_HOME:
                    pos = 0
                elif k == curses.KEY_END:
                    pos = len(buf)
                elif 32 <= k <= 126:
                    buf.insert(pos, chr(k))
                    pos += 1
        finally:
            curses.curs_set(0)
            self.stdscr.timeout(350)

    def _draw_indicator(self, y, status, sel):
        """Draw the 5-col status indicator at the left of a row. 'running' is a
        smooth pulse: three fixed dots with the lit one gliding across them."""
        try:
            if status == "running":
                active = self.anim % 3
                for i in range(3):
                    if sel:
                        attr = curses.color_pair(7) | (curses.A_BOLD if i == active else 0)
                    else:
                        attr = curses.color_pair(9) | (
                            curses.A_BOLD if i == active else curses.A_DIM)
                    self.stdscr.addstr(y, 1 + i, "•", attr)
            else:
                glyph, pair = STATUS_ICON.get(status, STATUS_ICON["unknown"])
                attr = (curses.color_pair(7) if sel
                        else curses.color_pair(pair)) | curses.A_BOLD
                self.stdscr.addstr(y, 1, glyph, attr)
        except curses.error:
            pass

    def refresh_live(self, force=False):
        """Recompute per-chat status + the live-agent set. The agents query is
        throttled (it spawns `claude`); job tempo files are cheap, read each time."""
        now = time.time()
        if force or now - self._agents_ts > 2.5:
            self._agents = agents_active()
            self._agents_ts = now
        jobs = job_tempo_map()
        active = self._agents
        self.cnames = claude_names()
        self.live = {c["id"]: resolve_status(c["id"], active, jobs)
                     for c in self.all_chats}
        # EVERY active background agent refuses a plain `--resume` (verified),
        # whether busy, blocked, or idle/done. So all of them are "live" and need
        # stop / fork / attach. Only truly-closed sessions resume directly.
        self.live_ids = set(active.keys())

    def rescan(self):
        """Re-scan ~/.claude/projects for chat files and refresh self.all_chats.
        Incremental: a chat's title/cwd never change once written, so we only
        parse files that are new or whose mtime moved, and reuse cached parses
        otherwise. This is what lets one claude-c instance pick up chats created
        by ANOTHER instance (or by `n` here) without a manual reload. Returns the
        set of session ids that newly appeared since the last scan."""
        cache = self._chat_cache
        seen = set()
        new_ids = set()
        if PROJECTS_DIR.exists():
            for proj in PROJECTS_DIR.iterdir():
                if not proj.is_dir():
                    continue
                for f in proj.glob("*.jsonl"):
                    p = str(f)
                    seen.add(p)
                    try:
                        mtime = f.stat().st_mtime
                    except OSError:
                        continue
                    cached = cache.get(p)
                    if cached is not None:
                        cached["mtime"] = mtime  # touch; title/cwd are stable
                        continue
                    c = parse_chat(f)
                    if c:
                        cache[p] = c
                        new_ids.add(c["id"])
        for p in list(cache):  # drop files that were deleted on disk
            if p not in seen:
                del cache[p]
        self.all_chats = sorted(cache.values(),
                                key=lambda c: c["mtime"], reverse=True)
        return new_ids

    def category_of(self, chat_id):
        return self.store.get(chat_id, UNCATEGORIZED)

    def project_name(self, path):
        if not path:
            return "all projects"
        return (self.projects_added.get(path)
                or os.path.basename(path.rstrip("/")) or path)

    def project_list(self):
        """[(None, 'All'), (path, name), ...] — union of added projects and any
        directory that already has chats."""
        paths = set(p for p in self.projects_added)
        for c in self.all_chats:
            cw = c.get("cwd")
            if cw and cw != "(unknown)":
                paths.add(cw)
        ordered = sorted(paths, key=lambda p: self.project_name(p).lower())
        return [(None, "All projects (no filter)")] + [(p, self.project_name(p))
                                                       for p in ordered]

    def _save_projects(self):
        def fn(d):
            d["active"] = self.active_project or "__all__"  # None = explicit "All"
            d["list"] = self.projects_added
        _json_update(PROJECTS_STORE, fn)

    def _add_project(self):
        raw = self._read_line("Add project folder (path): ", "")
        if not raw:
            return
        path = os.path.abspath(os.path.expanduser(raw))
        if not os.path.isdir(path):
            try:
                os.makedirs(path, exist_ok=True)
                self.message = f"Created {path}"
            except Exception as e:
                self.message = f"Couldn't create: {e}"
                return
        else:
            self.message = f"Added {path}"
        self.projects_added.setdefault(path, "")
        self.active_project = path
        self._save_projects()

    def _draw_projects(self, items, sel):
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()
        self.stdscr.addstr(0, 0, " Projects "[: w - 1], curses.A_BOLD)
        help_ = ("↑/↓ move   Enter switch-to   n new folder   r rename   "
                 "d remove   Esc/q back")
        self.stdscr.addstr(1, 0, help_[: w - 1], curses.color_pair(8) | curses.A_DIM)
        top = 3
        view_h = max(1, h - top - 1)
        start = sel - view_h + 1 if sel >= view_h else 0
        y = top
        for i in range(start, min(len(items), start + view_h)):
            path, name = items[i]
            is_sel = (i == sel)
            active = (path == self.active_project) if path else (not self.active_project)
            mark = "● " if active else "  "
            if path is None:
                detail = "show every chat"
            else:
                cnt = sum(1 for c in self.all_chats if c["cwd"] == path)
                detail = f"{path}   ({cnt})"
            line = f"{mark}{name:<26.26}  {detail}"
            if is_sel:
                attr = curses.color_pair(7)
            elif active:
                attr = curses.color_pair(9) | curses.A_BOLD
            else:
                attr = curses.A_NORMAL
            self.stdscr.addstr(y, 0, line[: w - 1], attr)
            y += 1
        if self.message:
            self.stdscr.addstr(h - 1, 0, self.message[: w - 1], curses.A_BOLD)
        self.stdscr.refresh()

    def projects_panel(self):
        """Modal projects view: switch active project, add a folder, rename,
        remove. Active project filters the board and is the cwd for new chats."""
        sel = 0
        try:
            while True:
                self.stdscr.timeout(-1)
                items = self.project_list()
                sel = max(0, min(sel, len(items) - 1))
                self._draw_projects(items, sel)
                k = self.stdscr.getch()
                if k in (ord("q"),):
                    return
                if k == 27:  # Esc alone -> back; or an arrow escape sequence
                    self.stdscr.nodelay(True)
                    seq = []
                    while len(seq) < 3:
                        nx = self.stdscr.getch()
                        if nx == -1:
                            break
                        seq.append(nx)
                        if seq[-1] in (ord("A"), ord("B")):
                            break
                    self.stdscr.nodelay(False)
                    if not seq:
                        return
                    if seq[-1] == ord("A"):
                        sel -= 1
                    elif seq[-1] == ord("B"):
                        sel += 1
                    continue
                if k in (curses.KEY_UP, ord("k")):
                    sel -= 1
                elif k in (curses.KEY_DOWN, ord("j")):
                    sel += 1
                elif k in (curses.KEY_ENTER, 10, 13):
                    self.active_project = items[sel][0]
                    self._save_projects()
                    self.sel = 0
                    return
                elif k in (ord("n"), ord("N")):
                    self._add_project()
                elif k in (ord("r"), ord("R")):
                    path = items[sel][0]
                    if not path:
                        self.message = "Can't rename 'All projects'"
                    else:
                        new = self._read_line("Rename project to: ",
                                              self.project_name(path))
                        if new is not None:
                            self.projects_added[path] = new  # '' -> basename
                            self._save_projects()
                            self.message = "Project renamed"
                elif k in (ord("d"), ord("D")):
                    path = items[sel][0]
                    if path and path in self.projects_added:
                        del self.projects_added[path]
                        if self.active_project == path:
                            self.active_project = None
                        self._save_projects()
                        self.message = "Removed from project list"
                    elif path:
                        self.message = "Has chats (auto-listed) — can't remove"
                    else:
                        self.message = "Can't remove 'All projects'"
        finally:
            self.stdscr.timeout(350)

    def visible_chats(self):
        cs = self.all_chats
        if self.active_project:
            cs = [c for c in cs if c["cwd"] == self.active_project]
        return cs

    def grouped(self):
        groups = {cat: [] for cat in DISPLAY_ORDER}
        for c in self.visible_chats():
            groups[self.category_of(c["id"])].append(c)
        return groups

    def build_rows(self):
        """Flat list of display rows. Each row is (kind, payload). The second
        return value `nav` lists the indices of selectable rows — both headers
        (so you can collapse/expand) and chats. Collapsed categories hide their
        chats but keep the header."""
        rows = []
        nav = []  # indices into rows that the cursor can land on
        groups = self.grouped()
        for cat in DISPLAY_ORDER:
            members = groups[cat]
            if cat == UNCATEGORIZED and not members:
                continue  # hide empty landing bucket
            nav.append(len(rows))
            rows.append(("header", cat))
            if cat in self.collapsed:
                continue  # collapsed -> hide members
            if not members:
                rows.append(("empty", cat))
            for c in members:
                nav.append(len(rows))
                rows.append(("chat", c))
        return rows, nav

    def run(self):
        curses.curs_set(0)
        setup_colors()
        self.stdscr.timeout(350)  # wake often so the running-dot animates smoothly
        curses.flushinp()  # drop any keys buffered before the board opened
        while True:
            rows, nav = self.build_rows()
            if not self._positioned and self._want_select:
                for i, ri in enumerate(nav):
                    if rows[ri][0] == "chat" and rows[ri][1]["id"] == self._want_select:
                        self.sel = i
                        break
                self._positioned = True
            if self._reselect_id is not None:
                for i, ri in enumerate(nav):
                    if rows[ri][0] == "chat" and rows[ri][1]["id"] == self._reselect_id:
                        self.sel = i
                        break
                self._reselect_id = None
            if self.sel >= len(nav):
                self.sel = max(0, len(nav) - 1)
            self.draw(rows, nav)
            ch = self.stdscr.getch()
            if not self.handle_key(ch, nav):
                return

    def _selected_row(self, nav):
        if not nav:
            return (None, None)
        rows, _ = self.build_rows()
        return rows[nav[self.sel]]

    def selected_chat(self, nav):
        kind, payload = self._selected_row(nav)
        return payload if kind == "chat" else None

    def selected_header(self, nav):
        kind, payload = self._selected_row(nav)
        return payload if kind == "header" else None

    def toggle_collapse(self, cat):
        if cat in self.collapsed:
            self.collapsed.discard(cat)
        else:
            self.collapsed.add(cat)
        _json_update(COLLAPSE_STORE,
                     lambda d: d.__setitem__("collapsed", sorted(self.collapsed)))

    def handle_key(self, ch, nav):
        if ch == -1:  # timeout tick — advance animation; refresh data ~1/sec
            self.anim += 1
            now = time.time()
            if now - self._scan_ts > 2.0:
                # Pick up chats / category / name edits made by another claude-c
                # instance (or by `n` here) without a manual reload.
                self._scan_ts = now
                sel_chat = self.selected_chat(nav)
                self.store = load_store()
                self.names = load_names()
                new_ids = self.rescan()
                if sel_chat:  # keep the cursor on the same chat as rows shift
                    self._reselect_id = sel_chat["id"]
                if new_ids:
                    self.refresh_live(force=True)
                    self._live_ts = now
            if now - self._live_ts > 1.0:
                self.refresh_live()
                self._live_ts = now
            return True
        self.message = ""
        if ch in (ord("q"),):
            return False
        elif ch in (curses.KEY_DOWN, ord("j")):
            if nav:
                self.sel = min(self.sel + 1, len(nav) - 1)
        elif ch in (curses.KEY_UP, ord("k")):
            self.sel = max(self.sel - 1, 0)
        elif ch in (ord(" "),):  # Space — collapse/expand the section header
            cat = self.selected_header(nav)
            if cat:
                self.toggle_collapse(cat)
        elif ch in (ord("1"), ord("2"), ord("3"), ord("4"), ord("5")):
            c = self.selected_chat(nav)
            if c:
                cat = CATEGORIES[ch - ord("1")]
                self.store = _json_set(STORE, c["id"], cat)
                self.message = f"Moved to “{cat}”"
        elif ch in (ord("p"), ord("P")):
            self.projects_panel()
            self.message = (f"Project: {self.project_name(self.active_project)}"
                            if self.active_project else "Showing all projects")
            self.sel = 0
        elif ch == 18:  # Ctrl+R — reload the script (re-exec; picks up code edits)
            self.reload = True
            return False
        elif ch in (ord("r"),):
            c = self.selected_chat(nav)
            if c:
                new = self._read_line("Rename to: ", self.display_title(c))
                if new is not None:
                    if new == "":
                        self.names = _json_set(NAMES_STORE, c["id"], None)
                        self.message = "Name reset to default"
                    else:
                        self.names = _json_set(NAMES_STORE, c["id"], new)
                        self.message = "Renamed"
        elif ch in (ord("d"),):
            c = self.selected_chat(nav)
            if c:
                self.confirm_delete(c)
        elif ch in (ord("n"), ord("N")):
            self.new_chat = True  # start a fresh chat (handled after curses ends)
            return False
        elif ch in (ord("f"), ord("F")):
            c = self.selected_chat(nav)
            if c:
                self.resume_target, self.resume_action = c, "fork"
                return False
        elif ch in (ord("x"), ord("X")):
            c = self.selected_chat(nav)
            if c and c["id"] in self.live_ids:
                self.confirm_stop(c)
                if self.resume_target:
                    return False
            elif c:
                self.message = "Not a live agent — nothing to stop"
        elif ch in (curses.KEY_ENTER, 10, 13):
            c = self.selected_chat(nav)
            if c:
                # Live agent -> attach (non-destructive; detach with Ctrl+Z keeps
                # it running). Closed chat -> normal resume.
                self.resume_target = c
                self.resume_action = "attach" if c["id"] in self.live_ids else "resume"
                return False
            cat = self.selected_header(nav)
            if cat:  # Enter on a section header -> collapse/expand it
                self.toggle_collapse(cat)
        return True

    def confirm_stop(self, chat):
        h, w = self.stdscr.getmaxyx()
        prompt = (f"Stop this live agent? It stops running (conversation kept).  "
                  f"(y/N)  {chat['title'][:35]}")
        self.stdscr.addstr(h - 1, 0, prompt[: w - 1], curses.color_pair(4) | curses.A_BOLD)
        self.stdscr.clrtoeol()
        self.stdscr.refresh()
        if self._blocking_getch() in (ord("y"), ord("Y")):
            self.resume_target, self.resume_action = chat, "stop"
        else:
            self.message = "Stop cancelled"

    def confirm_delete(self, chat):
        h, w = self.stdscr.getmaxyx()
        live = "  (NOTE: this chat is running live)" if chat["id"] in self.live_ids else ""
        prompt = f"Delete this chat permanently? (y/N)  {chat['title'][:40]}{live}"
        self.stdscr.addstr(h - 1, 0, prompt[: w - 1], curses.color_pair(4))
        self.stdscr.clrtoeol()
        self.stdscr.refresh()
        if self._blocking_getch() in (ord("y"), ord("Y")):
            try:
                chat["path"].unlink()
                self.store = _json_set(STORE, chat["id"], None)
                self.rescan()
                self.message = "Chat deleted"
            except Exception as e:
                self.message = f"Delete failed: {e}"
        else:
            self.message = "Delete cancelled"

    def draw(self, rows, nav):
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()
        title = " Claude Chats "
        scope = self.project_name(self.active_project) if self.active_project else "all projects"
        header = f"{title}— {len(self.visible_chats())} chats ({scope})"
        self.stdscr.addstr(0, 0, header[: w - 1], curses.A_BOLD)
        help1 = ("Enter open   Space fold   n new   r rename   f fork   x stop   "
                 "1-5 file   d delete   P projects   ^R reload   q quit")
        self.stdscr.addstr(1, 0, help1[: w - 1], curses.color_pair(8) | curses.A_DIM)
        legend = "  ".join(f"{i+1}:{CATEGORIES[i]}" for i in range(5))
        self.stdscr.addstr(2, 0, legend[: w - 1], curses.A_DIM)
        status_legend = "status:  ● running   ◆ needs input   ✓ done   ✗ failed"
        self.stdscr.addstr(3, 0, status_legend[: w - 1], curses.A_DIM)

        top = 5
        view_h = h - top - 1
        sel_row = nav[self.sel] if nav else 0
        if sel_row < self.scroll:
            self.scroll = sel_row
        elif sel_row >= self.scroll + view_h:
            self.scroll = sel_row - view_h + 1

        y = top
        for idx in range(self.scroll, min(len(rows), self.scroll + view_h)):
            kind, payload = rows[idx]
            line_y = y
            y += 1
            if kind == "header":
                cnt = sum(1 for c in self.visible_chats()
                          if self.category_of(c["id"]) == payload)
                arrow = "▸" if payload in self.collapsed else "▾"
                is_sel = nav and idx == nav[self.sel]
                text = f"{arrow} {payload}  ({cnt})"
                if is_sel:
                    text = text.ljust(w - 1)
                    attr = curses.color_pair(7) | curses.A_BOLD
                else:
                    attr = curses.color_pair(CAT_COLOR[payload]) | curses.A_BOLD
                self.stdscr.addstr(line_y, 0, text[: w - 1], attr)
            elif kind == "empty":
                self.stdscr.addstr(line_y, 2, "(empty)"[: w - 3],
                                   curses.A_DIM)
            elif kind == "chat":
                c = payload
                is_sel = nav and idx == nav[self.sel]
                proj = os.path.basename(c["cwd"].rstrip("/")) or c["cwd"]
                status = self.live.get(c["id"], "unknown")
                gcolor = STATUS_ICON.get(status, STATUS_ICON["unknown"])[1]
                prefix = "     "  # 5 cols reserved for the status indicator
                tail = f"  [{proj}]"
                avail = w - 1 - len(tail) - len(prefix)
                t = self.display_title(c)
                if len(t) > avail:
                    t = t[: avail - 1] + "…"
                body = t + " " * max(0, avail - len(t)) + tail
                if is_sel:
                    self.stdscr.addstr(line_y, 0, (prefix + body)[: w - 1],
                                       curses.color_pair(7))
                    self._draw_indicator(line_y, status, sel=True)
                else:
                    self.stdscr.addstr(line_y, len(prefix),
                                       body[: w - 1 - len(prefix)], curses.A_NORMAL)
                    self._draw_indicator(line_y, status, sel=False)

        if self.message:
            self.stdscr.addstr(h - 1, 0, self.message[: w - 1], curses.A_BOLD)
        self.stdscr.refresh()


def create_bg_agent(cwd=None):
    """Create a new idle background agent and return its short id (or None).
    The agent keeps running in Claude's daemon; we then attach to it so the
    user can leave with Ctrl+Z and it stays alive."""
    try:
        out = subprocess.run(["claude", "--bg"], cwd=cwd,
                             capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    txt = _ANSI_RE.sub("", out.stdout + out.stderr)
    mt = re.search(r"backgrounded\W+([0-9a-f]{8})", txt)
    return mt.group(1) if mt else None


def run_child(cmd, cwd=None):
    """Run an interactive child (claude) and wait for it to truly exit. If a
    stray Ctrl+Z ever suspends it (some claude modes re-enable job control), we
    immediately resume it — so the board can NEVER hang on a stopped child.
    `claude attach` is unaffected: it reads Ctrl+Z as a keystroke and exits.

    start_new_session=True is critical: `claude --resume`/`--fork-session`
    (unlike attach) treat Ctrl+Z as a real job-control SUSPEND and raise
    SIGTSTP on their process group. Without a separate session the child shares
    the board's group, so that SIGTSTP propagates up and tears down the whole
    terminal (and stops the agent) instead of doing nothing. Giving the child
    its own session contains the signal — the board and terminal always survive.
    Verified: attach still detaches cleanly (agent keeps running) and resume
    stays fully interactive."""
    p = subprocess.Popen(cmd, cwd=cwd, start_new_session=True)
    while True:
        try:
            _, status = os.waitpid(p.pid, os.WUNTRACED)
        except ChildProcessError:
            return
        if os.WIFSTOPPED(status):
            try:
                os.kill(p.pid, signal.SIGCONT)  # un-suspend and keep going
            except Exception:
                pass
            continue
        return  # exited or killed


def run_child_relay(cmd, cwd=None):
    """Like run_child, but for `claude --resume`/`--fork-session` (CLOSED chats).

    Those put the terminal in RAW mode, so Ctrl+Z is delivered to claude as a
    plain byte (0x1A) — never a signal — and claude ignores it. So there is no
    job-control signal to catch (verified): the only way to make Ctrl+Z mean
    "come back to the board" is to sit between the terminal and claude in a pty
    and intercept the byte ourselves (how tmux/script work). On Ctrl+Z we tear
    the child down and return; Ctrl-D//quit still work (claude exits → pty EOF).

    Falls back to a plain run_child if stdin isn't a real tty."""
    stdin_fd = sys.stdin.fileno()
    stdout_fd = sys.stdout.fileno()
    try:
        old_attr = termios.tcgetattr(stdin_fd)
    except Exception:
        return run_child(cmd, cwd=cwd)  # not a tty — nothing to relay

    master, slave = os.openpty()
    try:
        sz = fcntl.ioctl(stdin_fd, termios.TIOCGWINSZ, b"\x00" * 8)
    except Exception:
        sz = struct.pack("HHHH", 40, 120, 0, 0)
    try:
        fcntl.ioctl(slave, termios.TIOCSWINSZ, sz)
    except Exception:
        pass

    def _pre():
        os.setsid()
        try:
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)  # pty becomes claude's own ctty
        except Exception:
            pass

    p = subprocess.Popen(cmd, cwd=cwd, stdin=slave, stdout=slave, stderr=slave,
                         preexec_fn=_pre, close_fds=True)
    os.close(slave)

    def _winch(signum, frame):
        try:
            s = fcntl.ioctl(stdin_fd, termios.TIOCGWINSZ, b"\x00" * 8)
            fcntl.ioctl(master, termios.TIOCSWINSZ, s)
            os.killpg(os.getpgid(p.pid), signal.SIGWINCH)
        except Exception:
            pass

    old_winch = signal.getsignal(signal.SIGWINCH)
    try:
        signal.signal(signal.SIGWINCH, _winch)
    except Exception:
        pass

    try:
        tty.setraw(stdin_fd)
        while True:
            try:
                rs, _, _ = select.select([stdin_fd, master], [], [], 0.2)
            except (OSError, select.error):
                continue
            if stdin_fd in rs:
                try:
                    data = os.read(stdin_fd, 65536)
                except OSError:
                    data = b""
                if data:
                    if b"\x1a" in data:                  # Ctrl+Z → back to board
                        pre = data.split(b"\x1a", 1)[0]
                        if pre:
                            os.write(master, pre)
                        break
                    os.write(master, data)
            if master in rs:
                try:
                    data = os.read(master, 65536)
                except OSError:
                    data = b""
                if not data:
                    break                                # claude closed the pty
                os.write(stdout_fd, data)
            if p.poll() is not None:
                try:                                     # drain anything left
                    while True:
                        d = os.read(master, 65536)
                        if not d:
                            break
                        os.write(stdout_fd, d)
                except OSError:
                    pass
                break
    finally:
        try:
            termios.tcsetattr(stdin_fd, termios.TCSADRAIN, old_attr)
        except Exception:
            pass
        try:
            signal.signal(signal.SIGWINCH, old_winch)
        except Exception:
            pass
        if p.poll() is None:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except Exception:
                try:
                    p.terminate()
                except Exception:
                    pass
            try:
                p.wait(timeout=3)
            except Exception:
                try:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                except Exception:
                    pass
        try:
            os.close(master)
        except Exception:
            pass


def main():
    # Make the board immune to Ctrl+Z (SIGTSTP) so it can never be suspended —
    # e.g. an extra Ctrl+Z after detaching from an agent. Children reset this
    # via _child_preexec so `claude attach` keeps Ctrl+Z for detaching.
    try:
        signal.signal(signal.SIGTSTP, signal.SIG_IGN)
    except Exception:
        pass

    if not PROJECTS_DIR.exists():
        print("No Claude projects directory found at", PROJECTS_DIR)
        return

    last_id = None
    while True:
        holder = {}

        def _run(stdscr):
            app = App(stdscr, select_id=last_id)
            app.run()
            holder["app"] = app

        curses.wrapper(_run)
        app = holder.get("app")
        if not app:
            return

        # Ctrl+R — reload the script itself by re-executing (picks up code edits).
        if getattr(app, "reload", False):
            os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)])

        # 'n' — start a new chat as a BACKGROUND AGENT, then attach. This way the
        # user can leave with Ctrl+Z and the agent keeps running (just like the
        # existing live agents), instead of Ctrl-D stopping the work.
        if getattr(app, "new_chat", False):
            new_cwd = app.active_project or app.start_cwd
            run_cwd = new_cwd if (new_cwd and os.path.isdir(new_cwd)) else None
            ensure_trusted(run_cwd)
            print(f"\n▶ Creating a new background chat"
                  f"{f' in {run_cwd}' if run_cwd else ''} …")
            short = create_bg_agent(run_cwd)
            if not short:
                print("  Couldn't create the chat (is `claude` on PATH?).")
                input("  Press Enter to return to the menu …")
                continue
            full = next((s for s, r in agents_active().items()
                         if r.get("id") == short), None)
            if full:
                _json_set(STORE, full, "In Progress")
            print("  Attaching — press Ctrl+Z to leave it running and come back.\n")
            try:
                run_child(["claude", "attach", short], run_cwd)
            except FileNotFoundError:
                print("Could not find `claude` on PATH.")
                input("Press Enter to return to the menu …")
            continue

        if not app.resume_target:
            return  # user pressed q — leave the board

        # Run the chosen chat as a sub-process so we return here when it exits.
        c = app.resume_target
        action = getattr(app, "resume_action", "resume")
        last_id = c["id"]
        cwd = c["cwd"]
        run_cwd = cwd if (cwd and cwd != "(unknown)" and os.path.isdir(cwd)) else None
        short = short_id(c["id"], app._agents)

        # 'stop' just ends a live agent, then returns to the board.
        if action == "stop":
            print(f"\n■ Stopping background agent: {c['title'][:55]} …")
            ok = stop_agent(short)
            print("  stopped." if ok else "  couldn't confirm it stopped.")
            time.sleep(0.7)
            continue

        # Trust the folder once so Claude doesn't re-ask "trust this folder?".
        ensure_trusted(run_cwd)

        title = app.display_title(c)
        if action == "attach":
            # Direct attach to the LIVE agent. It keeps running; detach with
            # Ctrl+Z (claude attach handles the keystroke itself) to come back.
            cmd = ["claude", "attach", short]
            runner = run_child
            print(f"\n▶ Attaching to live agent: {title[:60]}")
            print("  (press Ctrl+Z to detach and come back — the agent KEEPS RUNNING)\n")
        elif action == "fork":
            # Closed-chat path: claude runs the terminal in raw mode and ignores
            # Ctrl+Z, so we relay through a pty and catch it ourselves.
            cmd = ["claude", "--resume", c["id"], "--fork-session"]
            runner = run_child_relay
            print(f"\n▶ Forking a copy of: {title[:60]}")
            print("  (press Ctrl+Z, Ctrl-D, or /quit to come back here)\n")
        else:  # resume a closed/finished chat
            cmd = ["claude", "--resume", c["id"]]
            runner = run_child_relay
            print(f"\n▶ Resuming: {title[:60]}")
            print("  (press Ctrl+Z, Ctrl-D, or /quit to come back here)\n")

        try:
            runner(cmd, run_cwd)
        except FileNotFoundError:
            print("Could not find the `claude` command on PATH.")
            print(f"Run manually:  cd {cwd} && {' '.join(cmd)}")
            input("Press Enter to return to the menu …")
        # loop returns to the board automatically; flushinp() in run() drops
        # any keys buffered while the sub-process was up so we never auto-loop.


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
