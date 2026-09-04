#!/usr/bin/env bash
# Recreate all custom GNOME media-key shortcuts. Idempotent.
set -e
BASE=org.gnome.settings-daemon.plugins.media-keys
PREFIX=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings
paths=()

paths+=("/rotate-bg/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/rotate-bg/"
gsettings set "$k" name 'Rotate wallpaper + terminal'
gsettings set "$k" binding '<Control><Shift>s'
gsettings set "$k" command '/home/eitan/.local/bin/rotate-bg.sh next'

paths+=("/claude-ask/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/claude-ask/"
gsettings set "$k" name 'Ask Claude (popup)'
gsettings set "$k" binding '<Control><Alt>a'
gsettings set "$k" command '/home/eitan/.local/bin/claude-ask'

paths+=("/prompts/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/prompts/"
gsettings set "$k" name 'Prompts library (popup)'
gsettings set "$k" binding '<Control><Shift>p'
gsettings set "$k" command '/home/eitan/.local/bin/prompts gui'

paths+=("/fix-screen/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/fix-screen/"
gsettings set "$k" name 'Fix screen (soft, keeps audio)'
gsettings set "$k" binding '<Super>F5'
gsettings set "$k" command '/home/eitan/bin/fix-screen-soft'

# The wholesale version: bounces the VT, which rebuilds every GPU surface. It
# always clears the corruption but stops Spotify, so it is the fallback key.
paths+=("/fix-screen-hard/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/fix-screen-hard/"
gsettings set "$k" name 'Fix screen (hard VT bounce)'
gsettings set "$k" binding '<Super><Shift>F5'
gsettings set "$k" command '/home/eitan/bin/fix-screen'

paths+=("/keys-cheatsheet/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/keys-cheatsheet/"
gsettings set "$k" name 'Keyboard shortcuts overlay'
gsettings set "$k" binding '<Super>k'
gsettings set "$k" command '/home/eitan/bin/keys-cheatsheet'

paths+=("/dlnl-bright-up/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/dlnl-bright-up/"
gsettings set "$k" name 'DLNL Brightness Up'
gsettings set "$k" binding '<Super>equal'
gsettings set "$k" command '/home/eitan/.local/bin/brightness up'

paths+=("/dlnl-bright-up-kp/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/dlnl-bright-up-kp/"
gsettings set "$k" name 'DLNL Brightness Up'
gsettings set "$k" binding '<Super>KP_Add'
gsettings set "$k" command '/home/eitan/.local/bin/brightness up'

paths+=("/dlnl-bright-down/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/dlnl-bright-down/"
gsettings set "$k" name 'DLNL Brightness Down'
gsettings set "$k" binding '<Super>minus'
gsettings set "$k" command '/home/eitan/.local/bin/brightness down'

paths+=("/dlnl-bright-down-kp/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/dlnl-bright-down-kp/"
gsettings set "$k" name 'DLNL Brightness Down'
gsettings set "$k" binding '<Super>KP_Subtract'
gsettings set "$k" command '/home/eitan/.local/bin/brightness down'

paths+=("/dlnl-night-up/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/dlnl-night-up/"
gsettings set "$k" name 'DLNL Night Light Up'
gsettings set "$k" binding '<Super><Shift>equal'
gsettings set "$k" command '/home/eitan/.local/bin/nightlight up'

paths+=("/dlnl-night-up-kp/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/dlnl-night-up-kp/"
gsettings set "$k" name 'DLNL Night Light Up'
gsettings set "$k" binding '<Super><Shift>KP_Add'
gsettings set "$k" command '/home/eitan/.local/bin/nightlight up'

paths+=("/dlnl-night-down/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/dlnl-night-down/"
gsettings set "$k" name 'DLNL Night Light Down'
gsettings set "$k" binding '<Super><Shift>minus'
gsettings set "$k" command '/home/eitan/.local/bin/nightlight down'

paths+=("/dlnl-night-down-kp/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/dlnl-night-down-kp/"
gsettings set "$k" name 'DLNL Night Light Down'
gsettings set "$k" binding '<Super><Shift>KP_Subtract'
gsettings set "$k" command '/home/eitan/.local/bin/nightlight down'

paths+=("/dlnl-present/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/dlnl-present/"
gsettings set "$k" name 'DLNL Clean/Capture Mode'
gsettings set "$k" binding '<Super><Shift>0'
gsettings set "$k" command '/home/eitan/.local/bin/present toggle'

paths+=("/run-once/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/run-once/"
gsettings set "$k" name 'Run one command'
gsettings set "$k" binding '<Control><Alt>r'
gsettings set "$k" command '/home/eitan/bin/run-once-term'

paths+=("/screenshot-claude/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/screenshot-claude/"
gsettings set "$k" name 'Screenshot → copy path for Claude'
gsettings set "$k" binding '<Control><Alt>s'
gsettings set "$k" command '/home/eitan/bin/screenshot-claude'

# Plain PrtScr stays GNOME's own screenshot UI, because that overlay is the only
# one with the record-video toggle; the portal screenshot screenshot-claude uses
# hides it. Shift+PrtScr gets screenshot-claude instead, taking over the built-in
# instant-fullscreen shot (which the UI already covers).
gsettings set org.gnome.shell.keybindings show-screenshot-ui "['Print']"
gsettings set org.gnome.shell.keybindings screenshot "[]"
paths+=("/screenshot-claude-print/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/screenshot-claude-print/"
gsettings set "$k" name 'Screenshot → copy path for Claude (Shift+PrtScr)'
gsettings set "$k" binding '<Shift>Print'
gsettings set "$k" command '/home/eitan/bin/screenshot-claude'

paths+=("/sunrise-alarm/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/sunrise-alarm/"
gsettings set "$k" name 'Sunrise Alarm'
gsettings set "$k" binding '<Control><Shift>a'
gsettings set "$k" command '/home/eitan/.local/bin/sunrise-alarm'

paths+=("/portfolio/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/portfolio/"
gsettings set "$k" name 'Portfolio + surf desktop panels'
gsettings set "$k" binding '<Control><Shift>m'
gsettings set "$k" command '/home/eitan/.local/bin/panels'

paths+=("/read-aloud/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/read-aloud/"
gsettings set "$k" name 'Read Aloud selection'
gsettings set "$k" binding '<Control><Shift>l'
gsettings set "$k" command '/home/eitan/code/Technion/Research/read-aloud/speak-selection.sh'

paths+=("/calc/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/calc/"
gsettings set "$k" name 'Calculate selection (popup)'
gsettings set "$k" binding '<Control><Alt>c'
gsettings set "$k" command '/home/eitan/.local/bin/calc'

paths+=("/claude-new-chat/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/claude-new-chat/"
gsettings set "$k" name 'New Claude chat'
gsettings set "$k" binding '<Primary><Alt>y'
gsettings set "$k" command '/home/eitan/bin/claude-new-chat'

# Spotify transport on Ctrl+Super+arrows. These drive spotify-skip over MPRIS
# and are deliberately NOT the XF86Audio* media keys, which the laptop lacks.
paths+=("/spotify-next/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/spotify-next/"
gsettings set "$k" name 'Spotify Next Track'
gsettings set "$k" binding '<Control><Super>Right'
gsettings set "$k" command '/home/eitan/.local/bin/spotify-skip next'

paths+=("/spotify-prev/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/spotify-prev/"
gsettings set "$k" name 'Spotify Previous Track'
gsettings set "$k" binding '<Control><Super>Left'
gsettings set "$k" command '/home/eitan/.local/bin/spotify-skip prev'

paths+=("/spotify-play/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/spotify-play/"
gsettings set "$k" name 'Spotify Play'
gsettings set "$k" binding '<Control><Super>Up'
gsettings set "$k" command '/home/eitan/.local/bin/spotify-skip play'

paths+=("/spotify-pause/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/spotify-pause/"
gsettings set "$k" name 'Spotify Pause'
gsettings set "$k" binding '<Control><Super>Down'
gsettings set "$k" command '/home/eitan/.local/bin/spotify-skip pause'

# Register the list of paths. MERGE with whatever is already registered rather
# than replacing it: a plain overwrite silently orphans any shortcut added since
# this script was last edited (added via GNOME Settings, or by a tool that wrote
# its own dconf entry). An orphaned entry still exists in dconf and still shows
# in GNOME Settings, but gsd-media-keys never grabs it, so the key just dies --
# which is exactly how the Spotify/portfolio/surf binds were lost.
existing=$(gsettings get $BASE custom-keybindings)
while read -r p; do
    [ -n "$p" ] || continue
    for have in "${paths[@]}"; do [ "$have" = "$p" ] && continue 2; done
    paths+=("$p")
done < <(echo "$existing" | tr ',' '\n' | sed "s|.*/custom-keybindings||; s|[]['\" ]||g" | grep -v '^$')

# Then ADOPT orphans: entries that exist under the dconf directory but are
# absent from the registered list. Merging the list alone cannot recover these
# -- once a shortcut falls off the list it is invisible to every later run, so
# it stays dead forever (this is how Ctrl+Shift+L / Read Aloud was lost, and it
# survived several runs of this script afterwards). Deliberate removals delete
# the dconf entry itself, so nothing intentionally dropped comes back here.
if command -v dconf >/dev/null 2>&1; then
    while read -r child; do
        [ -n "$child" ] || continue
        p="/$child"                       # dconf list prints 'name/'
        for have in "${paths[@]}"; do [ "$have" = "$p" ] && continue 2; done
        paths+=("$p")
        echo "Adopted orphaned shortcut: $p"
    done < <(dconf list "$PREFIX/" 2>/dev/null | grep '/$')
fi

# Emit FULL dconf paths, the canonical form GNOME Settings itself writes.
# gsd-media-keys happens to tolerate the bare '/rotate-bg/' form this script
# used to write, but anything that addresses the per-binding schema as
# "<schema>.custom-keybinding:<path>" (GNOME Settings, keys-cheatsheet) can only
# resolve a full path, and silently sees no shortcuts at all with the bare form.
arr="["
for p in "${paths[@]}"; do arr="$arr'$PREFIX$p', "; done
arr="${arr%, }]"
gsettings set $BASE custom-keybindings "$arr"
echo "Restored ${#paths[@]} keybindings."

# --- De-conflict the terminal-tiler from Ubuntu's Tiling Assistant ----------
# The terminal-tiler extension owns <Super>Left / <Super>Right to reorder the
# focused terminal within its column group. Tiling Assistant ships with the
# SAME accelerators bound to tile-left-half / tile-right-half, and two grabbers
# on one key make Mutter fire them nondeterministically — so Super+Left/Right
# "sometimes" half-tiled the window instead of moving the terminal. Drop the
# arrows from Tiling Assistant (its keypad variants <Super>KP_4 / <Super>KP_6
# still half-tile any window), leaving the arrows solely to the tiler. This is
# the same treatment already applied to tile-maximize / restore-window, which
# were moved off <Super>Up/Down onto the keypad. Guarded so it is a no-op if
# Tiling Assistant is not installed.
TA=org.gnome.shell.extensions.tiling-assistant
if gsettings list-schemas 2>/dev/null | grep -qx "$TA"; then
    gsettings set "$TA" tile-left-half  "['<Super>KP_4']"
    gsettings set "$TA" tile-right-half "['<Super>KP_6']"
    echo "De-conflicted Tiling Assistant (freed <Super>Left/Right for terminal-tiler)."
fi

# Also free the arrows from Mutter's BUILT-IN edge-tiling. These default to
# <Super>Left/Right in Ubuntu and can reappear after a settings reset/update,
# re-introducing the same conflict with the terminal-tiler (symptom: one arrow
# moves terminals, the other snaps the window to a screen half). Clearing them
# leaves the arrows solely to the tiler; half-tiling stays on <Super>KP_4/KP_6.
gsettings set org.gnome.mutter.keybindings toggle-tiled-left  "@as []"
gsettings set org.gnome.mutter.keybindings toggle-tiled-right "@as []"
echo "Cleared Mutter edge-tiling off <Super>Left/Right."

# And free <Super><Alt>Left/Right, which the terminal-tiler now uses to walk
# keyboard focus between the terminals of a tiled group. GNOME ships them as
# duplicate accelerators for switch-to-workspace-left/right; drop just those
# two entries and workspace switching keeps <Super>Page_Up/Down, the keypad
# variants and <Control><Alt>Left/Right. (The tiler also falls back to a plain
# workspace switch when the focused window is not one of its terminals, so the
# old behaviour survives on that key for every other app.)
gsettings set org.gnome.desktop.wm.keybindings switch-to-workspace-left \
    "['<Super>Page_Up', '<Super>KP_Prior', '<Control><Alt>Left']"
gsettings set org.gnome.desktop.wm.keybindings switch-to-workspace-right \
    "['<Super>Page_Down', '<Super>KP_Next', '<Control><Alt>Right']"
echo "Freed <Super><Alt>Left/Right for terminal-tiler focus movement."
