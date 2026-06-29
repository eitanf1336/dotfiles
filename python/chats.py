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
  m            move the selected chat to a project (independent of its folder)
  f            fork a copy of the selected chat
  x            stop the selected live agent
  1..6         file the selected chat into a category. A freshly-filed chat
               sorts to the TOP of its category, so an accidental move stays in
               plain sight instead of sinking into a big pile.
  u            undo the last category move (revert the chat to where it was)
  /            find a chat by name and jump to it, anywhere on the board — press
               / again to cycle to the next match. Reaches chats in collapsed
               sections (it expands the section it lands in).
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
import unicodedata
from pathlib import Path

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# --- bidi / display-width helpers ------------------------------------------
# Chat names can mix Hebrew (RTL) with English (LTR). A row whose first strong
# character is Hebrew makes the terminal flip the WHOLE line to RTL base
# direction, so the trailing "[project]" tag jumps to the left and the layout
# looks scrambled. Wrapping the name in directional isolates renders it
# correctly on its own while leaving the surrounding LTR layout untouched.
_FSI = "⁨"  # First Strong Isolate (auto-detects the run's direction)
_PDI = "⁩"  # Pop Directional Isolate


def _has_rtl(s):
    return any(unicodedata.bidirectional(c) in ("R", "AL") for c in s)


def _bidi(s):
    """Isolate a possibly-RTL string so it can't flip the surrounding layout."""
    return _FSI + s + _PDI if _has_rtl(s) else s


def _cwidth(ch):
    """Terminal columns a single character occupies (0 for zero-width marks)."""
    if unicodedata.combining(ch) or unicodedata.category(ch) == "Cf":
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _dwidth(s):
    return sum(_cwidth(c) for c in s)


def _clamp(s, cols):
    """Truncate s to at most `cols` display columns (counting zero-width as 0)."""
    if cols <= 0:
        return ""
    out, used = [], 0
    for ch in s:
        w = _cwidth(ch)
        if used + w > cols:
            break
        out.append(ch)
        used += w
    return "".join(out)


def _wrap(s, cols):
    """Split s into segments each <= `cols` display columns, breaking at spaces
    when possible so the full string can be shown across several lines."""
    if cols <= 0:
        return [s]
    out, cur = [], ""
    for word in s.split(" "):
        cand = (cur + " " + word) if cur else word
        if _dwidth(cand) <= cols:
            cur = cand
            continue
        if cur:
            out.append(cur)
            cur = ""
        # A single word wider than the line is hard-split by display width.
        while _dwidth(word) > cols:
            head = _clamp(word, cols)
            if not head:
                break
            out.append(head)
            word = word[len(head):]
        cur = word
    if cur or not out:
        out.append(cur)
    return out

locale.setlocale(locale.LC_ALL, "")

HOME = Path.home()
PROJECTS_DIR = HOME / ".claude" / "projects"
STORE = HOME / ".claude" / "chats" / "categories.json"

# Category order shown on the board. "Uncategorized" is the landing bucket for
# any chat you haven't filed yet; the 6 real categories map to number keys 1-6.
UNCATEGORIZED = "Uncategorized"
CATEGORIES = [
    "In Progress",
    "To Test",
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
    "To Test": 2,      # yellow
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


# When each chat was last (re)filed into a category, as unix timestamps keyed by
# session id. Used to float a freshly-moved chat to the top of its category, so an
# accidental move lands somewhere visible instead of sinking into a big pile.
MOVED_STORE = HOME / ".claude" / "chats" / "moved.json"


def load_moved():
    return _load_json(MOVED_STORE)


PROJECTS_STORE = HOME / ".claude" / "chats" / "projects.json"
COLLAPSE_STORE = HOME / ".claude" / "chats" / "collapsed.json"
PROJECT_TAGS_STORE = HOME / ".claude" / "chats" / "chat_projects.json"


def load_project_tags():
    """sessionId -> project key override. Lets a chat live in a project other
    than the one implied by its folder (e.g. grouping homework chats from several
    folders under one 'HW' project). Empty file = every chat just uses its
    folder, exactly like before this feature existed."""
    return _load_json(PROJECT_TAGS_STORE)


def project_key_for(chat, tags):
    """Effective project key for a chat: an explicit per-chat tag wins, else the
    chat's own working directory. The key is a real folder path for folder-based
    projects, or a free virtual name (like 'HW') for tagged ones."""
    return tags.get(chat["id"]) or chat.get("cwd") or "(unknown)"


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


# Sentinel for App(select_project=...). _KEEP_PROJECT means "this is a fresh
# launch — use whatever active project is persisted." Any other value (including
# None, which means the 'All projects' view) means "restore EXACTLY this project."
# Returning from a chat passes the board's own project so Ctrl+Z never moves you.
_KEEP_PROJECT = object()


class App:
    def __init__(self, stdscr, select_id=None, select_project=_KEEP_PROJECT):
        self.stdscr = stdscr
        self.store = load_store()
        self.names = load_names()  # sessionId -> user's custom name
        self.moved = load_moved()  # sessionId -> ts it was last (re)filed
        self._last_move = None     # (id, prev_cat, prev_ts) — for `u` undo
        self._search = ""          # last `/` query, so / repeats find the next hit
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
        self._resize_settle = 0.0  # >0 = a resize is in flight; clear+repaint when it lands
        self.refresh_live(force=True)
        pj = _load_json(PROJECTS_STORE)
        self.projects_added = pj.get("list", {})   # key -> custom display name
        self.project_cwds = pj.get("cwds", {})     # virtual project key -> default cwd
        self.tags = load_project_tags()            # sessionId -> project key override
        if "active" not in pj:                      # first run -> default to home
            self.active_project = str(HOME)
        else:                                       # "__all__" means user chose All
            a = pj["active"]
            self.active_project = None if a in (None, "__all__") else a
        # Returning from a chat (Ctrl+Z/detach/exit) restores the EXACT project
        # the board was showing when the chat was opened — NEVER the chat's own
        # project. (Snapping to the chat's project was jarring: Ctrl+Z from a
        # chat dumped you onto a different project screen than the one you left.)
        # _KEEP_PROJECT = a fresh launch, so use the persisted active set above;
        # any other value (including None for "All projects") = restore it verbatim.
        if select_project is not _KEEP_PROJECT:
            self.active_project = select_project
            self._save_projects()
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

    def project_name(self, key):
        if not key:
            return "all projects"
        name = self.projects_added.get(key)
        if name:
            return name
        if os.path.isabs(key):                       # a real folder -> basename
            return os.path.basename(key.rstrip("/")) or key
        return key                                   # virtual project: name is the key

    def project_cwd(self, key):
        """Default working directory for new chats started in a project. For a
        folder-based project that's the folder itself; for a virtual project
        it's an explicitly-stored cwd (if any)."""
        if not key:
            return None
        if os.path.isdir(key):
            return key
        return self.project_cwds.get(key)

    def project_list(self):
        """[(None, 'All'), (key, name), ...] — union of explicitly-added projects
        and the effective project of every chat (its tag override, or else its
        folder)."""
        keys = set(self.projects_added)
        for c in self.all_chats:
            k = project_key_for(c, self.tags)
            if k and k != "(unknown)":
                keys.add(k)
        ordered = sorted(keys, key=lambda k: self.project_name(k).lower())
        return [(None, "All projects (no filter)")] + [(k, self.project_name(k))
                                                       for k in ordered]

    def _save_projects(self):
        def fn(d):
            d["active"] = self.active_project or "__all__"  # None = explicit "All"
            d["list"] = self.projects_added
            d["cwds"] = self.project_cwds
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
                 "d remove   Esc/q/p back")
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
                cnt = sum(1 for c in self.all_chats
                          if project_key_for(c, self.tags) == path)
                if os.path.isabs(path):
                    detail = f"{path}   ({cnt})"
                else:
                    cw = self.project_cwds.get(path)
                    detail = (f"{cw}   " if cw else "") + f"(tagged · {cnt})"
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
                if k in (ord("q"), ord("p"), ord("P")):
                    # 'p' toggles the panel shut again — back to the project you
                    # had before opening it (selection here only commits on Enter).
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
                    if path is None:
                        self.message = "Can't remove 'All projects'"
                    else:
                        tagged = [sid for sid, kk in self.tags.items() if kk == path]
                        if tagged:  # un-tag its chats -> they fall back to folders
                            self.tags = _json_update(
                                PROJECT_TAGS_STORE,
                                lambda d: [d.pop(sid, None) for sid in tagged])
                        removed = False
                        if path in self.projects_added:
                            del self.projects_added[path]
                            self.project_cwds.pop(path, None)
                            self._save_projects()
                            removed = True
                        if self.active_project == path:
                            self.active_project = None
                        if removed or tagged:
                            self.message = "Project removed (chats back to folders)"
                        else:
                            self.message = "Has chats (auto-listed by folder) — can't remove"
        finally:
            self.stdscr.timeout(350)

    def move_chat(self, chat):
        """Assign a chat to a project, independent of its folder. Typing an
        existing project name files it there; a new name creates that project;
        a blank entry clears the tag so the chat goes back to its folder's
        project. Category (status) is untouched — it's stored separately."""
        new = self._read_line(
            "Move to project (name; blank = back to its folder): ", "")
        if new is None:
            return
        if new == "":
            self.tags = _json_set(PROJECT_TAGS_STORE, chat["id"], None)
            self.message = "Project tag cleared — back to its folder"
            return
        key = None
        for k, nm in self.project_list()[1:]:  # match an existing project by name
            if nm.lower() == new.lower():
                key = k
                break
        if key is None:                        # brand-new virtual project
            key = new
            self.projects_added.setdefault(key, new)
            self._save_projects()
        self.tags = _json_set(PROJECT_TAGS_STORE, chat["id"], key)
        self.message = f"Moved to project “{self.project_name(key)}”"

    def visible_chats(self):
        cs = self.all_chats
        if self.active_project:
            cs = [c for c in cs
                  if project_key_for(c, self.tags) == self.active_project]
        return cs

    def grouped(self):
        groups = {cat: [] for cat in DISPLAY_ORDER}
        for c in self.visible_chats():
            groups[self.category_of(c["id"])].append(c)
        # Order each category by recency = the MORE recent of the chat's own last
        # activity (file mtime) and when you last filed it here. So a chat you just
        # moved jumps to the top of its new category (an accidental move stays in
        # plain sight), while a chat you filed long ago but kept working in still
        # rises on real activity. Untouched-by-the-board chats fall back to mtime.
        for members in groups.values():
            members.sort(
                key=lambda c: max(c["mtime"], self.moved.get(c["id"], 0)),
                reverse=True)
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
            if ch == curses.KEY_RESIZE:
                self._on_resize()
                continue
            if not self.handle_key(ch, nav):
                return

    def _on_resize(self):
        """Terminator/VTE fires a burst of KEY_RESIZE events while the window is
        being dragged, and leaves stale/garbled cells behind when it reflows. ncurses
        already resized stdscr by the time we see the event, so the layout tracks the
        drag on its own — but a plain erase()+diff won't rewrite the cells VTE
        corrupted. So we just arm a short debounce here; once the events stop (~120ms,
        i.e. the drag is done) the timeout tick does ONE hard clear()+full repaint that
        wipes the garbage. Polling fast meanwhile makes us notice the gap promptly."""
        curses.update_lines_cols()  # keep curses.LINES/COLS in sync (draw() uses getmaxyx)
        self._resize_settle = time.time() + 0.12
        self.stdscr.timeout(50)

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

    def _record_move(self, chat_id, prev_cat):
        """Stamp a category move's time (drives the recency sort) and remember the
        prior state so `u` can revert the last move."""
        self._last_move = (chat_id, prev_cat, self.moved.get(chat_id))
        self.moved = _json_set(MOVED_STORE, chat_id, time.time())

    def _undo_move(self):
        """Revert the most recent category move — both the category and the
        recency stamp — so a stray 1-6 keypress is a one-key fix."""
        if not self._last_move:
            self.message = "Nothing to undo"
            return
        cid, prev_cat, prev_ts = self._last_move
        self._last_move = None
        # prev_cat == Uncategorized means it had no tag -> delete the key.
        self.store = _json_set(
            STORE, cid, None if prev_cat == UNCATEGORIZED else prev_cat)
        # prev_ts None -> it had never been filed before; delete the stamp.
        self.moved = _json_set(MOVED_STORE, cid, prev_ts)
        self._reselect_id = cid  # snap the cursor back to it
        self.message = f"Undone — back to “{prev_cat}”"

    def _search_jump(self, nav):
        """Find a chat by name anywhere on the board and jump the cursor to it, so
        even one buried deep in a big category is reachable. Pressing / again with
        the same query cycles to the next match (wrapping at the end)."""
        q = self._read_line("Find (name): ", self._search)
        if q is None:
            return
        q = q.strip().lower()
        self._search = q
        if not q:
            return
        groups = self.grouped()
        ordered = [c for cat in DISPLAY_ORDER for c in groups[cat]]  # board order
        matches = [c for c in ordered if q in self.display_title(c).lower()]
        if not matches:
            self.message = f"No match for “{q}”"
            return
        cur = self.selected_chat(nav)
        target = None
        if cur is not None:  # first match strictly after the cursor (cycle)
            ids = [c["id"] for c in ordered]
            try:
                start = ids.index(cur["id"]) + 1
            except ValueError:
                start = 0
            target = next((c for c in ordered[start:]
                           if q in self.display_title(c).lower()), None)
        if target is None:
            target = matches[0]
        cat = self.category_of(target["id"])
        if cat in self.collapsed:  # expand so the cursor can land on it
            self.toggle_collapse(cat)
        self._reselect_id = target["id"]
        n = len(matches)
        self.message = (f"Found: {self.display_title(target)}"
                        + (f"  ({n} matches — / for next)" if n > 1 else ""))

    def handle_key(self, ch, nav):
        if ch == -1:  # timeout tick — advance animation; refresh data ~1/sec
            if self._resize_settle and time.time() >= self._resize_settle:
                # The resize drag has stopped — force a full repaint to wipe the
                # garbage VTE left, then go back to the normal animation cadence.
                self._resize_settle = 0.0
                self.stdscr.timeout(350)
                self.stdscr.clear()  # clearok -> next draw()'s refresh fully repaints
            self.anim += 1
            now = time.time()
            if now - self._scan_ts > 2.0:
                # Pick up chats / category / name edits made by another claude-c
                # instance (or by `n` here) without a manual reload.
                self._scan_ts = now
                sel_chat = self.selected_chat(nav)
                self.store = load_store()
                self.names = load_names()
                self.moved = load_moved()
                self.tags = load_project_tags()
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
        elif ch in (ord("1"), ord("2"), ord("3"), ord("4"), ord("5"), ord("6")):
            c = self.selected_chat(nav)
            if c:
                cat = CATEGORIES[ch - ord("1")]
                cur = self.category_of(c["id"])
                # Going In Progress -> Done straight skips “Done — Not
                # Committed”, i.e. the work probably isn't committed yet. Ask.
                if (cat == "Done" and cur == "In Progress"
                        and not self.confirm_skip_commit(c)):
                    self.message = "Kept in “In Progress” — commit it first"
                elif cat == cur:
                    self.message = f"Already in “{cat}”"
                else:
                    self._record_move(c["id"], cur)
                    self.store = _json_set(STORE, c["id"], cat)
                    self.message = f"Moved to “{cat}”  —  u to undo"
        elif ch in (ord("u"), ord("U")):
            self._undo_move()
        elif ch in (ord("/"),):
            self._search_jump(nav)
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
        elif ch in (ord("m"), ord("M")):
            c = self.selected_chat(nav)
            if c:
                self.move_chat(c)
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

    def confirm_skip_commit(self, chat):
        """Warn when filing an In-Progress chat straight to Done — that skips
        the “Done — Not Committed” step, which usually means the work hasn't
        been committed yet. Returns True if the user wants to mark it Done anyway."""
        h, w = self.stdscr.getmaxyx()
        prompt = ("Mark Done without committing first? Skips “Done — Not "
                  f"Committed”.  (y/N)  {_bidi(chat['title'][:35])}")
        self.stdscr.addstr(h - 1, 0, _clamp(prompt, w - 1),
                           curses.color_pair(4) | curses.A_BOLD)
        self.stdscr.clrtoeol()
        self.stdscr.refresh()
        return self._blocking_getch() in (ord("y"), ord("Y"))

    def confirm_stop(self, chat):
        h, w = self.stdscr.getmaxyx()
        prompt = (f"Stop this live agent? It stops running (conversation kept).  "
                  f"(y/N)  {_bidi(chat['title'][:35])}")
        self.stdscr.addstr(h - 1, 0, _clamp(prompt, w - 1), curses.color_pair(4) | curses.A_BOLD)
        self.stdscr.clrtoeol()
        self.stdscr.refresh()
        if self._blocking_getch() in (ord("y"), ord("Y")):
            self.resume_target, self.resume_action = chat, "stop"
        else:
            self.message = "Stop cancelled"

    def confirm_delete(self, chat):
        h, w = self.stdscr.getmaxyx()
        live = "  (NOTE: this chat is running live)" if chat["id"] in self.live_ids else ""
        prompt = f"Delete this chat permanently? (y/N)  {_bidi(chat['title'][:40])}{live}"
        self.stdscr.addstr(h - 1, 0, _clamp(prompt, w - 1), curses.color_pair(4))
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
        # Header: plain "Claude Chats — N chats  " then the active project drawn
        # in a reverse-video chip so the current project is unmistakable.
        prefix = f"{title}— {len(self.visible_chats())} chats   "
        self.stdscr.addstr(0, 0, prefix[: w - 1], curses.A_BOLD)
        x = _dwidth(prefix)
        if x < w - 1:
            chip = _clamp(f" ▶ {_bidi(scope)} ", w - 1 - x)
            chip_attr = curses.color_pair(7) | curses.A_BOLD  # black-on-white bar
            try:
                self.stdscr.addstr(0, x, chip, chip_attr)
            except curses.error:
                pass
        help1 = ("Enter open   / find   Space fold   n new   r rename   m move   "
                 "f fork   x stop   1-6 file   u undo   d delete   P projects   "
                 "^R reload   q quit")
        self.stdscr.addstr(1, 0, help1[: w - 1], curses.color_pair(8) | curses.A_DIM)
        legend = "  ".join(f"{i+1}:{CATEGORIES[i]}" for i in range(6))
        self.stdscr.addstr(2, 0, legend[: w - 1], curses.A_DIM)
        status_legend = "status:  ● running   ◆ needs input   ✓ done   ✗ failed"
        self.stdscr.addstr(3, 0, status_legend[: w - 1], curses.A_DIM)

        top = 5
        # Footer block: the FULL title of the chat under the cursor, wrapped over
        # as many lines as it needs (capped) so even a name longer than the
        # terminal width is fully readable. The list view shrinks to make room,
        # so the footer never overlaps a chat row. A status message overrides it.
        FOOTER_MAX = 5
        footer = []
        if self.message:
            footer = [_clamp(self.message, w - 2)]
        elif nav:
            kind, payload = rows[nav[self.sel]]
            if kind == "chat":
                segs = _wrap(self.display_title(payload), w - 2) or [""]
                footer = [_bidi(s) for s in segs[:FOOTER_MAX]]
        footer_h = max(1, len(footer))
        # +1 for a faint separator rule between the list and the footer.
        view_h = h - top - footer_h - 1
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
                # The [tag] reflects the chat's EFFECTIVE project (its per-chat
                # override if any, else its folder) — not the raw cwd basename —
                # so a chat moved into HW shows [HW], not its old folder.
                proj = self.project_name(project_key_for(c, self.tags))
                status = self.live.get(c["id"], "unknown")
                gcolor = STATUS_ICON.get(status, STATUS_ICON["unknown"])[1]
                prefix = "     "  # 5 cols reserved for the status indicator
                tail = f"  [{proj}]"
                avail = w - 1 - _dwidth(tail) - len(prefix)
                t = self.display_title(c)
                if _dwidth(t) > avail:
                    t = _clamp(t, max(0, avail - 1)) + "…"
                # _bidi() keeps a Hebrew/RTL name from flipping the whole row;
                # pad/clamp by display width since it (and the name) may differ
                # from code-point count.
                pad = " " * max(0, avail - _dwidth(t))
                body = _bidi(t) + pad + tail
                if is_sel:
                    self.stdscr.addstr(line_y, 0, _clamp(prefix + body, w - 1),
                                       curses.color_pair(7))
                    self._draw_indicator(line_y, status, sel=True)
                else:
                    self.stdscr.addstr(line_y, len(prefix),
                                       _clamp(body, w - 1 - len(prefix)),
                                       curses.A_NORMAL)
                    self._draw_indicator(line_y, status, sel=False)

        sep_y = h - footer_h - 1
        try:
            self.stdscr.addstr(sep_y, 0, "─" * (w - 1), curses.A_DIM)
        except curses.error:
            pass
        attr = curses.A_BOLD if self.message else (curses.color_pair(8)
                                                   | curses.A_BOLD)
        base = h - len(footer)
        for i, fline in enumerate(footer):
            try:
                self.stdscr.addstr(base + i, 0, fline, attr)
            except curses.error:
                pass
        self.stdscr.refresh()


EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max", "ultracode"]


def prompt_effort(default="high"):
    """Ask which thinking (reasoning effort) level the new chat should use.
    Returns one of EFFORT_LEVELS. Pressing Enter (or typing anything invalid)
    picks the default, which is 'high'. Runs after curses has ended, so plain
    print/input is fine here."""
    print("\n  Thinking level for this chat:")
    for i, lv in enumerate(EFFORT_LEVELS, 1):
        mark = "   ← default" if lv == default else ""
        print(f"    {i}) {lv}{mark}")
    try:
        raw = input(f"  Choose 1-{len(EFFORT_LEVELS)} [Enter = {default}]: ").strip().lower()
    except EOFError:
        return default
    if not raw:
        return default
    if raw.isdigit() and 1 <= int(raw) <= len(EFFORT_LEVELS):
        return EFFORT_LEVELS[int(raw) - 1]
    if raw in EFFORT_LEVELS:
        return raw
    return default


def create_bg_agent(cwd=None, effort=None):
    """Create a new idle background agent and return its short id (or None).
    The agent keeps running in Claude's daemon; we then attach to it so the
    user can leave with Ctrl+Z and it stays alive. `effort`, if given, sets the
    session's thinking level via `claude --effort <level>`."""
    cmd = ["claude", "--bg"]
    if effort:
        cmd += ["--effort", effort]
    try:
        out = subprocess.run(cmd, cwd=cwd,
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
    # Project to restore when the board reopens after a chat. _KEEP_PROJECT on
    # the first launch (use whatever's persisted); after a chat it becomes the
    # project the board was showing, so Ctrl+Z always returns you to the SAME
    # project screen you left — never the chat's own project.
    last_project = _KEEP_PROJECT
    while True:
        holder = {}

        def _run(stdscr):
            app = App(stdscr, select_id=last_id, select_project=last_project)
            app.run()
            holder["app"] = app

        curses.wrapper(_run)
        app = holder.get("app")
        if not app:
            return
        # Remember the project the board was showing so EVERY path below
        # (resume/attach/fork/new/stop) returns you to that same project screen
        # — not the chat's own project. This is the whole Ctrl+Z fix.
        last_project = app.active_project

        # Ctrl+R — reload the script itself by re-executing (picks up code edits).
        if getattr(app, "reload", False):
            os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)])

        # 'n' — start a new chat as a BACKGROUND AGENT, then attach. This way the
        # user can leave with Ctrl+Z and the agent keeps running (just like the
        # existing live agents), instead of Ctrl-D stopping the work.
        if getattr(app, "new_chat", False):
            new_cwd = app.project_cwd(app.active_project) or app.start_cwd
            run_cwd = new_cwd if (new_cwd and os.path.isdir(new_cwd)) else None
            ensure_trusted(run_cwd)
            effort = prompt_effort()
            print(f"\n▶ Creating a new background chat"
                  f"{f' in {run_cwd}' if run_cwd else ''}"
                  f" (thinking: {effort}) …")
            short = create_bg_agent(run_cwd, effort)
            if not short:
                print("  Couldn't create the chat (is `claude` on PATH?).")
                input("  Press Enter to return to the menu …")
                continue
            full = next((s for s, r in agents_active().items()
                         if r.get("id") == short), None)
            if full:
                _json_set(STORE, full, "In Progress")
                if app.active_project:  # keep new chats inside the active project
                    _json_set(PROJECT_TAGS_STORE, full, app.active_project)
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

        # NOTE: we intentionally do NOT change last_project here. It already
        # holds the project the board was showing (captured above), so returning
        # from this chat lands back on that SAME project screen — never the
        # chat's own project, which used to throw you onto the wrong screen.

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
