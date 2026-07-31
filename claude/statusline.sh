#!/usr/bin/env bash
# Claude Code status line: shows remaining usage limits (5h + weekly), model, context.
# Rate-limit fields are provided by Claude Code for Claude.ai Pro/Max subscribers
# and only appear after the first API response of a session.
#
# Layout: stays on one line when it fits; if the line would overflow the terminal
# width ($COLUMNS, set by Claude Code v2.1.153+), the weekly segment wraps to a
# second row.

input=$(cat)

WIDTH=${COLUMNS:-80}

RESET='\033[0m'
DIM='\033[2m'
SEP_C=" ${DIM}|${RESET} "   # colored separator
SEP_P=" | "                 # plain separator (for width measurement)

# Color a percentage REMAINING: green=plenty, yellow=getting low, red=almost out.
color_for_remaining() {
  local pct=$1
  if   (( pct >= 50 )); then printf '\033[32m'   # green
  elif (( pct >= 20 )); then printf '\033[33m'   # yellow
  else                      printf '\033[31m'    # red
  fi
}

# Turn a Unix epoch reset time into a short "resets in" string.
# >= 1 day away: "resets in 3d04h" (days + hours, no minutes).
# Otherwise:     "resets in 2h13m" or "resets in 5m".
resets_in() {
  local epoch=$1
  [ -z "$epoch" ] && return
  local now diff d h m
  now=$(date +%s)
  diff=$(( epoch - now ))
  (( diff < 0 )) && diff=0
  d=$(( diff / 86400 ))
  h=$(( (diff % 86400) / 3600 ))
  m=$(( (diff % 3600) / 60 ))
  if   (( d > 0 )); then printf 'resets in %dd%02dh' "$d" "$h"
  elif (( h > 0 )); then printf 'resets in %dh%02dm' "$h" "$m"
  else                   printf 'resets in %dm' "$m"
  fi
}

# Remaining percent (integer) from a used percent.
remaining_pct() {
  local used=$1
  printf '%.0f' "$(echo "100 - $used" | bc -l 2>/dev/null || echo "$((100 - ${used%.*}))")"
}

# --- project chip ----------------------------------------------------------
# Which project this chat belongs to, painted in that project's own color (the
# same color the claude-c board uses for it). Resolved by ~/.claude/chats/
# projcolor.py: a per-chat project tag wins, else the working directory.
PROJ_C=""; PROJ_P=""
PROJCOLOR="$HOME/.claude/chats/projcolor.py"
if [ -f "$PROJCOLOR" ]; then
  SID=$(echo "$input" | jq -r '.session_id // empty')
  PDIR=$(echo "$input" | jq -r '.workspace.project_dir // .workspace.current_dir // .cwd // empty')
  if PROJ=$(python3 "$PROJCOLOR" --resolve --session "$SID" --cwd "$PDIR" 2>/dev/null); then
    PHEX=${PROJ%%$'\t'*}
    PNAME=${PROJ#*$'\t'}
    if [ -n "$PNAME" ] && [[ "$PHEX" =~ ^#[0-9A-Fa-f]{6}$ ]]; then
      # #RRGGBB -> a 24-bit SGR color (every modern terminal here does truecolor)
      r=$((16#${PHEX:1:2})); g=$((16#${PHEX:3:2})); b=$((16#${PHEX:5:2}))
      PC="\033[38;2;${r};${g};${b}m"
      PROJ_C="${PC}▌${PNAME}${RESET}"
      PROJ_P="▌${PNAME}"
    fi
  fi
fi

# --- fields ----------------------------------------------------------------
MODEL=$(echo "$input" | jq -r '.model.display_name // "Claude"')
EFFORT=$(echo "$input" | jq -r '.effort.level // empty')
CTX_REMAIN=$(echo "$input" | jq -r '.context_window.remaining_percentage // empty')

FIVE_USED=$(echo "$input"  | jq -r '.rate_limits.five_hour.used_percentage // empty')
FIVE_RESET=$(echo "$input" | jq -r '.rate_limits.five_hour.resets_at // empty')
WEEK_USED=$(echo "$input"  | jq -r '.rate_limits.seven_day.used_percentage // empty')
WEEK_RESET=$(echo "$input" | jq -r '.rate_limits.seven_day.resets_at // empty')

# --- build segments (colored + plain in parallel) --------------------------
# model (with reasoning effort appended when the model supports it)
c_model="$MODEL"
p_model="$MODEL"
if [ -n "$EFFORT" ]; then
  c_model="$MODEL ${DIM}(${EFFORT})${RESET}"
  p_model="$MODEL (${EFFORT})"
fi

# 5h segment
if [ -n "$FIVE_USED" ]; then
  rem=$(remaining_pct "$FIVE_USED")
  c=$(color_for_remaining "$rem")
  ri=$(resets_in "$FIVE_RESET")
  c_5h="${c}5h: ${rem}% left${RESET}"
  p_5h="5h: ${rem}% left"
  if [ -n "$ri" ]; then c_5h="$c_5h ${DIM}($ri)${RESET}"; p_5h="$p_5h ($ri)"; fi
fi

# week segment
if [ -n "$WEEK_USED" ]; then
  rem=$(remaining_pct "$WEEK_USED")
  c=$(color_for_remaining "$rem")
  ri=$(resets_in "$WEEK_RESET")
  c_week="${c}week: ${rem}% left${RESET}"
  p_week="week: ${rem}% left"
  if [ -n "$ri" ]; then c_week="$c_week ${DIM}($ri)${RESET}"; p_week="$p_week ($ri)"; fi
fi

# ctx segment
if [ -n "$CTX_REMAIN" ]; then
  ctx=$(printf '%.0f' "$CTX_REMAIN")
  c_ctx="${DIM}ctx ${ctx}%${RESET}"
  p_ctx="ctx ${ctx}%"
fi

# No rate-limit data yet -> single hint line and exit.
if [ -z "$FIVE_USED" ] && [ -z "$WEEK_USED" ]; then
  hint="$c_model"
  [ -n "$PROJ_C" ] && hint="$PROJ_C$SEP_C$hint"
  [ -n "$c_ctx" ] && hint="$hint$SEP_C$c_ctx"
  printf '%b' "$hint$SEP_C${DIM}limits appear after first reply (run /usage)${RESET}"
  exit 0
fi

# --- assemble: pack segments onto line 1, wrapping any that overflow -------
# Segments are placed in order (model, 5h, ctx, week). Each one that would
# push the current line past $WIDTH starts a new continuation row prefixed
# with "└ " — so the 5h segment now wraps just like the weekly one.
# The project chip leads the line — it's the thing you glance at, so it should
# never be the segment that wraps off to a continuation row.
seg_c=(); seg_p=()
[ -n "$PROJ_C" ] && { seg_c+=("$PROJ_C"); seg_p+=("$PROJ_P"); }
seg_c+=("$c_model"); seg_p+=("$p_model")
[ -n "$c_5h" ]   && { seg_c+=("$c_5h");   seg_p+=("$p_5h");   }
[ -n "$c_ctx" ]  && { seg_c+=("$c_ctx");  seg_p+=("$p_ctx");  }
[ -n "$c_week" ] && { seg_c+=("$c_week"); seg_p+=("$p_week"); }

out=""            # accumulated colored output (real newlines between rows)
cur_c=""; cur_p=""
pushed=0          # how many rows already emitted

flush_line() {
  local pfx=""
  (( pushed > 0 )) && pfx="${DIM}└ ${RESET}"   # continuation rows get "└ "
  if [ -z "$out" ]; then out="${pfx}${cur_c}"; else out="$out"$'\n'"${pfx}${cur_c}"; fi
  pushed=$(( pushed + 1 )); cur_c=""; cur_p=""
}

for i in "${!seg_p[@]}"; do
  sc="${seg_c[$i]}"; sp="${seg_p[$i]}"
  if [ -z "$cur_p" ]; then
    cur_c="$sc"; cur_p="$sp"
  else
    avail=$WIDTH
    (( pushed > 0 )) && avail=$(( WIDTH - 2 ))   # account for "└ " prefix
    cand="${cur_p}${SEP_P}${sp}"
    if (( ${#cand} <= avail )); then
      cur_c="$cur_c$SEP_C$sc"; cur_p="$cand"     # fits on current row
    else
      flush_line                                  # overflow — wrap to next row
      cur_c="$sc"; cur_p="$sp"
    fi
  fi
done
[ -n "$cur_c" ] && flush_line

printf '%b' "$out"
