#!/usr/bin/env bash
# Install/restore all customizations in this repo. Idempotent — re-run anytime.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BIN="$HOME/.local/bin"
EXT="$HOME/.local/share/gnome-shell/extensions"
SYSD="$HOME/.config/systemd/user"
AUTOSTART="$HOME/.config/autostart"
mkdir -p "$BIN" "$EXT" "$SYSD" "$AUTOSTART"

echo "==> bin/ scripts -> $BIN"
for f in "$REPO"/bin/*; do
    ln -sf "$f" "$BIN/$(basename "$f")"
done

echo "==> python tools"
# chats.py lives under ~/.claude/chats (its state files are written alongside it)
mkdir -p "$HOME/.claude/chats"
# Sessions sometimes replace that symlink with a real file and then edit it in
# place, so the live file can hold work the repo copy has never seen. A plain
# `ln -sf` here silently destroyed ~13KB of such work once. Never clobber it.
LIVE_CHATS="$HOME/.claude/chats/chats.py"
if [ -f "$LIVE_CHATS" ] && [ ! -L "$LIVE_CHATS" ] \
   && ! cmp -s "$LIVE_CHATS" "$REPO/python/chats.py"; then
    echo "    SKIP chats.py: $LIVE_CHATS is a local file that differs from the"
    echo "         repo copy, so it is left alone. To adopt it into the repo:"
    echo "           cp $LIVE_CHATS $REPO/python/chats.py && git -C $REPO diff"
else
    ln -sf "$REPO/python/chats.py" "$LIVE_CHATS"
fi
ln -sf "$REPO/python/claude-ask" "$BIN/claude-ask"
ln -sf "$BIN/claude-custom" "$BIN/claude-c"
ln -sf "$BIN/claude-desktop" "$BIN/claude-d"

echo "==> Claude Code slash commands -> ~/.claude/commands"
mkdir -p "$HOME/.claude/commands"
for f in "$REPO"/claude/commands/*.md; do
    ln -sf "$f" "$HOME/.claude/commands/$(basename "$f")"
done

echo "==> GNOME extensions -> $EXT"
for d in "$REPO"/gnome-extensions/*/; do
    name="$(basename "$d")"
    rm -rf "$EXT/$name"
    cp -r "$d" "$EXT/$name"
    if [ -d "$EXT/$name/schemas" ]; then
        glib-compile-schemas "$EXT/$name/schemas" 2>/dev/null || true
    fi
    echo "    installed $name"
done

echo "==> Sunrise Alarm app -> ~/.local/share/sunrise-alarm"
APPDIR="$HOME/.local/share/sunrise-alarm"
mkdir -p "$APPDIR"
cp "$REPO"/sunrise-alarm/* "$APPDIR"/
chmod +x "$APPDIR"/*.py "$APPDIR"/*.sh
echo "    installed sunrise-alarm (config lives in ~/.config/sunrise-alarm)"

echo "==> systemd user units"
cp "$REPO"/systemd/*.service "$REPO"/systemd/*.timer "$SYSD/" 2>/dev/null || true
systemctl --user daemon-reload 2>/dev/null || true
for t in "$REPO"/systemd/*.timer; do
    systemctl --user enable --now "$(basename "$t")" 2>/dev/null || true
done
# Units that are not timer-driven still need enabling explicitly.
systemctl --user enable --now media-keep-awake.service 2>/dev/null || true

echo "==> autostart entries -> $AUTOSTART"
for f in "$REPO"/autostart/*.desktop; do
    ln -sf "$f" "$AUTOSTART/$(basename "$f")"
done

echo "==> desktop launchers -> ~/.local/share/applications"
APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"
for f in "$REPO"/applications/*.desktop; do
    ln -sf "$f" "$APPS/$(basename "$f")"
done

echo "==> keybindings"
bash "$REPO/keybindings/restore-keybindings.sh" || true

cat <<'EOF'

Done. Next steps:
  - Log out/in (Wayland) or restart GNOME Shell to load the extensions, then:
      gnome-extensions enable displaylink-nightlight@eitan.local
      gnome-extensions enable terminal-tiler@eitan.local
  - Ensure ~/.local/bin is on your PATH.
EOF
