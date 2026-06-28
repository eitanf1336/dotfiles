#!/usr/bin/env bash
# Rotate the desktop wallpaper + matching Terminator background through 7 themes.
#   rotate-bg.sh next      -> advance to the next theme  (default)
#   rotate-bg.sh current   -> (re)apply the current theme without advancing
#   rotate-bg.sh <color>   -> jump straight to a named theme
# Terminal backgrounds update LIVE in every running Terminator via remotinator;
# no restart is needed. The Terminator config is also rewritten so new windows
# launch with the same background.
set -uo pipefail
export PATH="/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin"

DESK_DIR="$HOME/Pictures/Wallpapers/desktop"
TERM_DIR="$HOME/Pictures/Wallpapers/terminal"
STATE_DIR="$HOME/.local/state/desktop-rotation"
STATE_FILE="$STATE_DIR/index"
TCONF="$HOME/.config/terminator/config"
LOG="$STATE_DIR/rotate.log"

# Ordered theme list. Terminal file is always <color>_terminal.png;
# desktop file is <color>_desktop.png except for wood (desktop_wood.png).
COLORS=(green blue purple red gold brown wood)

mkdir -p "$STATE_DIR"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

desk_file() { echo "$DESK_DIR/$1_desktop.png"; }
term_file() { echo "$TERM_DIR/$1_terminal.png"; }

n=${#COLORS[@]}

# read & sanitise current index
idx=0
[ -f "$STATE_FILE" ] && idx=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
[[ "$idx" =~ ^[0-9]+$ ]] || idx=0

MODE="${1:-next}"
case "$MODE" in
  next)    idx=$(( (idx + 1) % n )) ;;
  current) idx=$(( idx % n )) ;;
  *)
    # jump to a named color if it exists in the list
    found=-1
    for i in "${!COLORS[@]}"; do [ "${COLORS[$i]}" = "$MODE" ] && found=$i; done
    if [ "$found" -ge 0 ]; then idx=$found; else
      echo "$(ts) unknown theme '$MODE'" >> "$LOG"; exit 1
    fi ;;
esac

color="${COLORS[$idx]}"
dfile="$(desk_file "$color")"
tfile="$(term_file "$color")"

# --- desktop wallpaper (light + dark) ---
if [ -f "$dfile" ]; then
  gsettings set org.gnome.desktop.background picture-uri      "file://$dfile"
  gsettings set org.gnome.desktop.background picture-uri-dark "file://$dfile"
else
  echo "$(ts) MISSING desktop image: $dfile" >> "$LOG"
fi

# --- terminal background: live update for ALL running terminals ---
if [ -f "$tfile" ]; then
  # 1) write the new image into the config (so new windows match too)
  if [ -f "$TCONF" ]; then
    sed -i -E "s|^([[:space:]]*background_image[[:space:]]*=).*|\1 $tfile|" "$TCONF"
  fi
  # 2) reload: re-reads the config AND forces an immediate redraw of every
  #    terminal via reconfigure()/queue_draw() -- no click needed.
  #    Fall back to bg_img_all if reload isn't available.
  if ! terminator --reload >/dev/null 2>&1; then
    remotinator bg_img_all -f "$tfile" >/dev/null 2>&1 \
      || echo "$(ts) terminator reload + bg_img_all both failed (not running?)" >> "$LOG"
  fi
else
  echo "$(ts) MISSING terminal image: $tfile" >> "$LOG"
fi

echo "$idx" > "$STATE_FILE"
echo "$(ts) applied theme: $color (idx $idx)" >> "$LOG"
