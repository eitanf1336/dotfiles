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
# projcolor.py sits beside chats.py (it imports it by path) and is also called
# by the status line, so both ends get the same per-project colors.
ln -sf "$REPO/python/projcolor.py" "$HOME/.claude/chats/projcolor.py"
ln -sf "$REPO/python/claude-ask" "$BIN/claude-ask"
ln -sf "$BIN/claude-custom" "$BIN/claude-c"
ln -sf "$BIN/claude-desktop" "$BIN/claude-d"

echo "==> Claude Code status line -> ~/.claude/statusline.sh"
# Same care as chats.py: a locally-edited real file is never clobbered.
LIVE_SL="$HOME/.claude/statusline.sh"
if [ -f "$LIVE_SL" ] && [ ! -L "$LIVE_SL" ] \
   && ! cmp -s "$LIVE_SL" "$REPO/claude/statusline.sh"; then
    echo "    SKIP statusline.sh: $LIVE_SL differs from the repo copy; adopt it with"
    echo "           cp $LIVE_SL $REPO/claude/statusline.sh && git -C $REPO diff"
else
    ln -sf "$REPO/claude/statusline.sh" "$LIVE_SL"
fi

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
systemctl --user enable --now power-menu-rescue.service 2>/dev/null || true
systemctl --user enable --now power-profile-auto.service 2>/dev/null || true

# power-menu-rescue is useless without its polkit rule (see polkit/README.md):
# without it `systemctl reboot -i` asks for a password the service cannot type,
# and the power menu silently keeps doing nothing. Same for await-claude-shut's
# `systemctl suspend -i`. Install it once, via pkexec so this script can stay
# unprivileged. The check probes the newest action in the rule, so a box with an
# older copy installed still gets the update.
echo "==> polkit rule for power-menu-rescue / await-claude-shut"
if pkcheck --action-id org.freedesktop.login1.suspend-ignore-inhibit --process $$ >/dev/null 2>&1; then
    echo "    already authorized"
elif pkexec install -m 0644 -o root -g root \
        "$REPO/polkit/etc/polkit-1/rules.d/49-force-shutdown-ignore-inhibit.rules" \
        /etc/polkit-1/rules.d/49-force-shutdown-ignore-inhibit.rules; then
    echo "    installed 49-force-shutdown-ignore-inhibit.rules"
else
    echo "    NOT installed — 'Restart Anyway' will keep doing nothing."
    echo "    Run it by hand: sudo install -m 0644 -o root -g root \\"
    echo "      $REPO/polkit/etc/polkit-1/rules.d/49-force-shutdown-ignore-inhibit.rules /etc/polkit-1/rules.d/"
fi

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

echo "==> app icons -> ~/.local/share/icons/hicolor"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$ICONS"
for f in "$REPO"/icons/hicolor/scalable/apps/*; do
    [ -e "$f" ] || continue
    ln -sf "$f" "$ICONS/$(basename "$f")"
done
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true

echo "==> wireplumber drop-ins -> ~/.config/wireplumber/wireplumber.conf.d"
WPCONF="$HOME/.config/wireplumber/wireplumber.conf.d"
mkdir -p "$WPCONF"
for f in "$REPO"/wireplumber/*.conf; do
    ln -sf "$f" "$WPCONF/$(basename "$f")"
done

echo "==> keybindings"
bash "$REPO/keybindings/restore-keybindings.sh" || true

cat <<'EOF'

Done. Next steps:
  - Log out/in (Wayland) or restart GNOME Shell to load the extensions, then:
      gnome-extensions enable displaylink-nightlight@eitan.local
      gnome-extensions enable terminal-tiler@eitan.local
  - Ensure ~/.local/bin is on your PATH.
  - Install the polkit rule that lets "Restart Anyway" actually restart
    (see polkit/README.md).
EOF
