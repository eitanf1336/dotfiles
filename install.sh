#!/usr/bin/env bash
# Install/restore all customizations in this repo. Idempotent — re-run anytime.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

BIN="$HOME/.local/bin"
EXT="$HOME/.local/share/gnome-shell/extensions"
SYSD="$HOME/.config/systemd/user"
mkdir -p "$BIN" "$EXT" "$SYSD"

echo "==> bin/ scripts -> $BIN"
for f in "$REPO"/bin/*; do
    ln -sf "$f" "$BIN/$(basename "$f")"
done

echo "==> python tools"
# chats.py lives under ~/.claude/chats (its state files are written alongside it)
mkdir -p "$HOME/.claude/chats"
ln -sf "$REPO/python/chats.py" "$HOME/.claude/chats/chats.py"
ln -sf "$REPO/python/claude-ask" "$BIN/claude-ask"
ln -sf "$BIN/claude-custom" "$BIN/claude-c"
ln -sf "$BIN/claude-desktop" "$BIN/claude-d"

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

echo "==> systemd user timer"
cp "$REPO"/systemd/rotate-bg.{service,timer} "$SYSD/"
systemctl --user daemon-reload 2>/dev/null || true
systemctl --user enable --now rotate-bg.timer 2>/dev/null || true

echo "==> keybindings"
bash "$REPO/keybindings/restore-keybindings.sh" || true

cat <<'EOF'

Done. Next steps:
  - Log out/in (Wayland) or restart GNOME Shell to load the extensions, then:
      gnome-extensions enable displaylink-nightlight@eitan.local
      gnome-extensions enable terminal-tiler@eitan.local
  - Ensure ~/.local/bin is on your PATH.
EOF
