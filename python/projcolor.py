#!/usr/bin/env python3
"""projcolor — one stable, good-looking color per Claude project.

Every project (a folder-based one like ~/code/MyProjects/SurfStatus, or a
virtual one like "HW") gets a color the first time it's seen. The pick looks
random but is deterministic: it starts from a hash of the project key and then
walks the palette until it finds a shade nobody else has taken, so two projects
never end up wearing the same color while free colors remain. Once assigned it
is written to project_colors.json and never changes on its own.

That color is then used in two places, so you always know which project the
terminal in front of you belongs to:
  * the chats board (claude-c) — header chip, the [tag] on every row, the rules
    above and below the list, and swatches in the P panel
  * inside a chat — the project chip at the left of the status line, plus the
    text cursor, which the board tints on the way in and resets on the way out

Used as a library by chats.py and as a CLI by ~/.claude/statusline.sh:
    projcolor.py --resolve [--session ID] [--cwd DIR]   -> "#RRGGBB\\tName"
    projcolor.py --list                                 -> every assignment
    projcolor.py --reroll KEY                           -> give KEY a new color
"""

import fcntl
import functools
import hashlib
import json
import os
import sys
from pathlib import Path

HOME = Path.home()
CHATS_DIR = HOME / ".claude" / "chats"
COLORS_STORE = CHATS_DIR / "project_colors.json"
PROJECTS_STORE = CHATS_DIR / "projects.json"
PROJECT_TAGS_STORE = CHATS_DIR / "chat_projects.json"

# Hand-picked palette: saturated but not neon, all legible on a dark terminal
# and distinct enough from each other that two projects never read as "the same
# blue". Order matters only as a walk order — the starting point is hashed.
PALETTE = [
    "#22D3EE",  # cyan
    "#FB923C",  # orange
    "#A78BFA",  # violet
    "#34D399",  # emerald
    "#F472B6",  # pink
    "#FBBF24",  # amber
    "#60A5FA",  # blue
    "#A3E635",  # lime
    "#FB7185",  # rose
    "#2DD4BF",  # teal
    "#E879F9",  # fuchsia
    "#F9E2AF",  # sunflower
    "#818CF8",  # indigo
    "#6EE7B7",  # mint
    "#FF8A65",  # coral
    "#38BDF8",  # sky
    "#C4B5FD",  # lavender
    "#B5E853",  # chartreuse
    "#FF79C6",  # magenta
    "#40E0D0",  # turquoise
    "#FFB86C",  # peach
    "#9EB8FF",  # periwinkle
    "#8AE9C1",  # seafoam
    "#E5C07B",  # gold
    "#BD93F9",  # iris
    "#F38BA8",  # flamingo
    "#7FDBFF",  # aqua
    "#FF9E9E",  # salmon
]

DEFAULT_OPTIONS = {
    # Tint the terminal's text cursor with the project color while you're in one
    # of its chats. Cheap, works everywhere, resets on the way out.
    "cursor": True,
    # Also tint the terminal BACKGROUND a few percent toward the project color
    # (OSC 11). Off by default: it does nothing in terminals that paint a
    # background image (Terminator with a wallpaper), and it's a bigger change
    # than "subtle" implies for everyone else. Turn it on by setting this true.
    "background": False,
    # How far toward the project color the background moves, 0.0–1.0.
    "background_strength": 0.10,
}


# --- store -----------------------------------------------------------------

def _load_json(path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


# The board asks for a color once per visible row per repaint (a few times a
# second), so the store is cached in memory and only re-read when the file's
# mtime changes. That keeps a redraw at one stat() instead of dozens of parses,
# while a color rerolled in another `claude-c` window still shows up here.
_CACHE = {"stamp": None, "colors": {}, "options": dict(DEFAULT_OPTIONS)}


def _read():
    try:
        st = COLORS_STORE.stat()
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        stamp = None
    if stamp != _CACHE["stamp"]:
        d = _load_json(COLORS_STORE)
        colors = d.get("colors")
        opts = dict(DEFAULT_OPTIONS)
        if isinstance(d.get("options"), dict):
            opts.update(d["options"])
        _CACHE.update(stamp=stamp,
                      colors=colors if isinstance(colors, dict) else {},
                      options=opts)
    return _CACHE["colors"], _CACHE["options"]


def _write_locked(fn):
    """Locked read-modify-write of the color store, so two boards (or a board
    and a status line) assigning colors at the same moment can't clobber each
    other. fn(colors_dict) mutates in place and may return a value to pass on."""
    CHATS_DIR.mkdir(parents=True, exist_ok=True)
    lock = COLORS_STORE.with_name(COLORS_STORE.name + ".lock")
    with open(lock, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            d = _load_json(COLORS_STORE)
            if not isinstance(d.get("colors"), dict):
                d["colors"] = {}
            if not isinstance(d.get("options"), dict):
                d["options"] = dict(DEFAULT_OPTIONS)
            out = fn(d["colors"])
            tmp = COLORS_STORE.with_name(f"{COLORS_STORE.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False))
            os.replace(tmp, COLORS_STORE)
            return out
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def option(name):
    return _read()[1].get(name, DEFAULT_OPTIONS.get(name))


# --- assignment ------------------------------------------------------------

def _hash_index(key):
    h = hashlib.md5(key.encode("utf-8", "replace")).hexdigest()
    return int(h[:8], 16) % len(PALETTE)


def _pick(key, taken):
    """A color for `key`: start where its hash lands and take the first shade
    nobody else is using. Once the palette is exhausted, fall back to the hashed
    slot itself (so it stays stable) and accept the repeat."""
    start = _hash_index(key)
    for step in range(len(PALETTE)):
        cand = PALETTE[(start + step) % len(PALETTE)]
        if cand not in taken:
            return cand
    return PALETTE[start]


def color_for(key, assign=True):
    """The project's color as '#RRGGBB'. Assigns and persists one on first sight
    unless assign=False (then an unknown project just gets its hashed shade
    without touching the store — used by read-only callers)."""
    if not key:
        return None
    colors, _ = _read()
    cur = colors.get(key)
    if isinstance(cur, str) and cur.startswith("#") and len(cur) == 7:
        return cur
    if not assign:
        return PALETTE[_hash_index(key)]

    def fn(c):
        have = c.get(key)
        if isinstance(have, str) and have.startswith("#"):
            return have
        picked = _pick(key, set(c.values()))
        c[key] = picked
        return picked
    return _write_locked(fn)


def reroll(key):
    """Give a project the next free color after its current one — the 'I don't
    like this one' button. Returns the new color."""
    def fn(c):
        taken = {v for k, v in c.items() if k != key}
        cur = c.get(key)
        start = (PALETTE.index(cur) + 1) if cur in PALETTE else _hash_index(key)
        for step in range(len(PALETTE)):
            cand = PALETTE[(start + step) % len(PALETTE)]
            if cand not in taken:
                c[key] = cand
                return cand
        c[key] = PALETTE[start % len(PALETTE)]
        return c[key]
    return _write_locked(fn)


def set_color(key, hexcolor):
    def fn(c):
        if hexcolor:
            c[key] = hexcolor
        else:
            c.pop(key, None)
        return hexcolor
    return _write_locked(fn)


def all_colors():
    return _read()[0]


# --- color math ------------------------------------------------------------

def rgb(hexcolor):
    h = (hexcolor or "").lstrip("#")
    if len(h) != 6:
        return (200, 200, 200)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(hexcolor, other, t):
    """Blend `hexcolor` toward `other` by t (0 = unchanged, 1 = fully other)."""
    a, b = rgb(hexcolor), rgb(other)
    return "#%02X%02X%02X" % tuple(
        max(0, min(255, round(a[i] + (b[i] - a[i]) * t))) for i in range(3))


@functools.lru_cache(maxsize=256)
def xterm256(hexcolor):
    """Nearest xterm-256 palette index — what curses needs, since it addresses
    colors by index, not by hex."""
    r, g, b = rgb(hexcolor)
    best, best_d = 15, None
    for idx in range(16, 256):
        if idx < 232:                       # 6x6x6 color cube
            n = idx - 16
            cr, cg, cb = (n // 36) % 6, (n // 6) % 6, n % 6
            cr, cg, cb = [0 if v == 0 else 55 + 40 * v for v in (cr, cg, cb)]
        else:                               # 24-step grayscale ramp
            cr = cg = cb = 8 + (idx - 232) * 10
        d = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if best_d is None or d < best_d:
            best, best_d = idx, d
    return best


def ansi_fg(hexcolor, truecolor=True):
    r, g, b = rgb(hexcolor)
    if truecolor:
        return f"\033[38;2;{r};{g};{b}m"
    return f"\033[38;5;{xterm256(hexcolor)}m"


# --- project resolution ----------------------------------------------------

def project_name(key):
    """Display name for a project key: the custom name you gave it in the P
    panel, else the folder's basename, else the key itself (virtual projects)."""
    if not key:
        return ""
    listed = _load_json(PROJECTS_STORE).get("list")
    if isinstance(listed, dict):
        nm = listed.get(key)
        if nm:
            return nm
    if os.path.isabs(key):
        return os.path.basename(key.rstrip("/")) or key
    return key


def resolve(session_id=None, cwd=None):
    """(key, name, color) for the project a chat belongs to. A per-chat project
    tag (set with 'm' on the board) wins over the folder, exactly like the board
    does it, so a chat you filed under 'HW' shows HW's color, not its folder's."""
    key = None
    if session_id:
        tags = _load_json(PROJECT_TAGS_STORE)
        if isinstance(tags, dict):
            key = tags.get(session_id) or None
    if not key and cwd:
        key = os.path.abspath(os.path.expanduser(cwd))
    if not key:
        return (None, "", None)
    return (key, project_name(key), color_for(key))


# --- CLI (used by the status line) -----------------------------------------

def _main(argv):
    if "--list" in argv:
        colors = all_colors()
        for k in sorted(colors, key=lambda k: project_name(k).lower()):
            print(f"{colors[k]}\t{project_name(k)}\t{k}")
        return 0
    if "--reroll" in argv:
        key = argv[argv.index("--reroll") + 1]
        print(reroll(key))
        return 0

    def opt(name):
        return argv[argv.index(name) + 1] if name in argv else None

    key, name, color = resolve(opt("--session"), opt("--cwd"))
    if not color:
        return 1
    print(f"{color}\t{name}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(_main(sys.argv[1:]))
    except (IndexError, KeyboardInterrupt, BrokenPipeError):
        sys.exit(1)
