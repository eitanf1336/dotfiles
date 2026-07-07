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
gsettings set "$k" binding '<Control><Shift>l'
gsettings set "$k" command '/home/eitan/.local/bin/prompts gui'

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

# Repurpose plain PrtScr: free it from GNOME's built-in screenshot UI and
# point it at screenshot-claude so Print copies the saved path to the clipboard.
gsettings set org.gnome.shell.keybindings show-screenshot-ui "[]"
paths+=("/screenshot-claude-print/")
k="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/screenshot-claude-print/"
gsettings set "$k" name 'Screenshot → copy path for Claude (PrtScr)'
gsettings set "$k" binding 'Print'
gsettings set "$k" command '/home/eitan/bin/screenshot-claude'

# register the list of paths
arr="["
for p in "${paths[@]}"; do arr="$arr'$p', "; done
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
