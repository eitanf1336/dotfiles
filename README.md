# linux-setup

My personal Linux desktop customizations — custom **GNOME Shell extensions**, **display/audio control scripts**, and a couple of **Python tools** built around Claude Code. Running GNOME on Wayland with DisplayLink/EVDI monitors.

Everything here is hand-written. The repo doubles as a backup and a one-shot reinstall (`./install.sh`).

---

## 🧩 GNOME Shell extensions

Extensions written from scratch (`gnome-extensions/`):

### DisplayLink Night Light — `displaylink-nightlight@eitan.local`
A software warm-tint **and** brightness/dimming overlay for monitors that lack hardware gamma or brightness control (DisplayLink/EVDI, USB docks) — the screens GNOME's built-in Night Light can't reach. Ships its own GSettings schema (`intensity`, `brightness`, `active`) plus a preferences panel. The `brightness`, `nightlight`, and `present` scripts below drive it.

### Terminal Tiler — `terminal-tiler@eitan.local`
On-demand vertical tiling for terminals. **Super+Return** spawns a fullscreen terminal on the focused monitor; pressing again adds another and divides that monitor into equal vertical columns. Focusing a stray terminal and pressing the key absorbs it. Manually moving/resizing a tiled window ejects it and re-flows the rest. Per-monitor, Wayland-native.

### Claude Idle Shutdown (`claude-idle-shutdown@eitan.local`)
Adds two items to the top-right **Power Off** menu: **"Off when Claude's done"** and **"Suspend when Claude's done"**. Each one runs `bin/await-claude-shut` in a terminal, which polls `claude-status` and then powers off (or suspends) once no Claude agent or chat is actively working, after a cancellable countdown that aborts if work starts up again. The two items are driven by one `ACTIONS` array in `extension.js`, so they share the exact same waiter logic.

---

## 🐍 Python tools

In `python/`:

### `chats.py` (launched as `claude-c`)
A board/TUI for organizing Claude Code chats into categories (In Progress / Later / Done) with live status. State persists to JSON next to the script. Launched via `bin/claude-custom`.

### `claude-ask` (GTK3)
A quick-prompt bar that slides up from the bottom of the screen on **Ctrl+Alt+A**. Streams Claude's answer live; multiple bars re-tile side-by-side. From an answer you can follow up, start fresh, file the chat to the `claude-c` board, or hand the conversation off to a terminal. Accent color tracks the current wallpaper theme. Bound to a global shortcut (see keybindings).

---

## 🛠️ Scripts

In `bin/` (installed to `~/.local/bin`):

| Script | What it does |
|--------|--------------|
| `brightness` | Software dimming for all monitors via the Night Light overlay. `low\|med\|high\|full\|up\|down\|<10-100>\|status` |
| `nightlight` | Warm-tint control for the overlay. `low\|med\|high\|max\|up\|down\|off\|on\|toggle\|status` |
| `present` | "Clean/Capture" mode — instantly tint-off + 100% brightness, toggle again to restore exactly. |
| `volume` | PipeWire/WirePlumber volume, capped at 100% to avoid soft-clip distortion. `up\|down\|mute\|<0-100>\|status` |
| `rotate-bg.sh` | Rotates desktop wallpaper + matching Terminator terminal background through 7 themes; updates live in running terminals via remotinator. |
| `claude-custom` | Launcher for the `claude-c` chats board. |
| `claude-desktop` | Launches the community Claude Desktop AppImage fully detached from the terminal. |
| `await-claude-shut` | Waits until no Claude agent/chat is actively running, then `systemctl <poweroff\|suspend\|reboot\|halt>` after a cancellable grace countdown that re-checks and aborts if Claude starts working again. Backs the "…when Claude's done" power-menu items. |
| `sunrise-alarm` | Opens the Sunrise Alarm config panel (also on the app grid and **Ctrl+Shift+A**). Detaches via `setsid -f`. |
| `setup-rclone-gdrive` | One-shot: installs rclone and configures full read/write Google Drive access (remote `gdrive`). Run once, authorize in browser. No secrets stored in the repo — the token lives only in `~/.config/rclone/rclone.conf`. |

> Note: `rotate-bg.sh` expects wallpapers under `~/Pictures/Wallpapers/{desktop,terminal}/`, which are not included here.

---

## ⏱️ systemd (user)

`systemd/` — `rotate-bg.timer` + `rotate-bg.service` advance the wallpaper/terminal theme automatically every day at midnight.

## 🚀 Autostart

`autostart/` — XDG autostart entries dropped into `~/.config/autostart/` (honored by GNOME on Wayland, where the session manager no longer relaunches apps after logout).

### `google-chrome.desktop`
Relaunches Chrome on login with `--restore-last-session`, so the previous windows/tabs come back after a logout or reboot and the "didn't shut down correctly" bubble is suppressed. (Chrome must also have *On startup → Continue where you left off* set.)

## ⌨️ Keybindings

`keybindings/custom-keybindings.md` documents all custom GNOME shortcuts (theme rotation, Ask Claude popup, brightness/night-light, clean mode). `keybindings/restore-keybindings.sh` recreates them via `gsettings`.

---

## 📦 Install

```bash
./install.sh
```

This symlinks `bin/` scripts into `~/.local/bin`, the `python/` tools, the GNOME extensions into `~/.local/share/gnome-shell/extensions`, compiles their GSettings schemas, installs the systemd timer, links the autostart entries, and restores the keybindings. Re-run anytime; it's idempotent. Log out / back in (or restart GNOME Shell) to load the extensions.
