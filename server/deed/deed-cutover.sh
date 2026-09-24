#!/usr/bin/env bash
# deed-cutover.sh - move the deed job (chat, watcher, canary, push-limits, deed
# login) from this laptop to eitan-vivobook-server.  Prepared by agent D.
#
#   deed-cutover.sh            READ-ONLY: pre-flight + "is the deed chat idle?"
#   deed-cutover.sh --go       do the cutover; refuses unless everything is idle
#
# Env knobs: QUIET_MIN (default 10) = minutes the transcript must have been still.
#
# Order of the --go run (each step logs to ~/fleet-staging/logs/deed-cutover-*.log):
#   a  idle check (agent status, transcript age, child procs, pipeline procs, portal inbox)
#   -  warm rsync of DeedPortal while things still run (shrinks the final delta)
#   b  stop claude-deed-watch + canary + push-limits timers on the laptop, re-check idle
#   c  claude stop the deed agent, stop the deed daemon, verify nothing holds the deed config
#   d  final rsync: DeedPortal (incl. work/), transcript file + dir, ~/.claude-deed state
#   e  MOVE the deed login: copy to server, verify `claude auth status` there, park the
#      laptop copy + laptop slot under ~/.claude/accounts/.deed-moved-to-server/<stamp>,
#      mark ~/.claude-deed/.moved-to-server, install the creds-guard that skips it
#   f  start the deed chat on the server (same session id, flags from the laptop roster),
#      record work/session-id, enable watch/canary/push-limits/creds-guard on the server,
#      disable + mask them on the laptop
#   g  laptop claude-c-deed / claude-deed become ssh -t wrappers (originals kept as *.local)
#
# Anything failing before step e puts the laptop back as it was (units restarted, and
# the chat resumed on the laptop if it had been stopped). From step e on, use
# ~/fleet-staging/deed-rollback.sh.
set -uo pipefail
cd "$HOME" || exit 1

SID=1c976435-dfde-4deb-90a9-6e02954c14e6
SHORT=${SID:0:8}
DEED_EMAIL=betscar.office@proton.me
DEED=$HOME/.claude-deed
REPO=$HOME/code/MyLittleProjects/DeedPortal
PROJ=$HOME/.claude/projects/-home-eitan
SERVER=${DEED_SERVER:-server}
QUIET_MIN=${QUIET_MIN:-10}
STAMP=$(date +%Y%m%d-%H%M%S)
PARK=$HOME/.claude/accounts/.deed-moved-to-server/$STAMP
STAGE=$HOME/fleet-staging/deed
LOGDIR=$HOME/fleet-staging/logs
LAPTOP_UNITS=(claude-deed-watch.service deed-watch-canary.timer deed-push-limits.timer)
SERVER_UNITS=(claude-creds-guard.timer claude-deed-watch.service deed-watch-canary.timer deed-push-limits.timer)
RSYNC_REPO=(-aH --delete --exclude=/pipeline/venv/ --exclude=__pycache__/)

mkdir -p "$LOGDIR"
LOG=$LOGDIR/deed-cutover-$STAMP.log
say()  { printf '%s  %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG"; }
warn() { say "WARN: $*"; }
die()  { say "STOP: $*"; exit 1; }
S()    { ssh -o BatchMode=yes -o ConnectTimeout=15 "$SERVER" "$@"; }
deedc() { CLAUDE_CONFIG_DIR=$DEED "$@"; }

# Launch flags: exactly what the laptop daemon used for this worker.
FLAGS=()
if [ -f "$DEED/daemon/roster.json" ]; then
  mapfile -t FLAGS < <(jq -r --arg s "$SHORT" '.workers[$s].dispatch.respawnFlags // empty | .[]' "$DEED/daemon/roster.json" 2>/dev/null)
fi
[ ${#FLAGS[@]} -gt 0 ] || FLAGS=(--effort xhigh --model opus)

# ---------------------------------------------------------------- idle check (a)
AGENT_PID=""
idle_check() {
  local bad=0 js row n status state age newest
  AGENT_PID=""
  # 1. the agent roster, as Claude itself reports it
  js=$(deedc timeout 45 claude agents --json 2>/dev/null) || { say "  claude agents --json failed"; return 1; }
  row=$(jq -c --arg s "$SID" '[.[] | select(.sessionId == $s)]' <<<"$js")
  n=$(jq length <<<"$row")
  if [ "$n" = 0 ]; then
    say "  agent:      not running on the laptop (nothing to stop)"
  else
    status=$(jq -r '.[0].status // "?"' <<<"$row"); state=$(jq -r '.[0].state // "-"' <<<"$row")
    AGENT_PID=$(jq -r '.[0].pid // empty' <<<"$row")
    say "  agent:      pid=$AGENT_PID kind=$(jq -r '.[0].kind' <<<"$row") status=$status state=$state"
    [ "$status" = idle ] || { say "  -> BUSY: status is '$status', not idle"; bad=1; }
    case "$state" in done|idle|-|null) ;; *) say "  -> BUSY: state is '$state'"; bad=1 ;; esac
    # 2. a tool call in flight shows up as a child process of the session
    if [ -n "$AGENT_PID" ] && pgrep -P "$AGENT_PID" >/dev/null 2>&1; then
      say "  -> BUSY: the session has child processes:"; pgrep -a -P "$AGENT_PID" | cut -c1-160 | sed 's/^/       /' | tee -a "$LOG"; bad=1
    fi
  fi
  # 2b. the job's own bookkeeping: tasks in flight or queued
  local js2="$DEED/jobs/$SHORT/state.json"
  if [ -f "$js2" ]; then
    local inf
    inf=$(jq -r '"\(.state // "?") tempo=\(.tempo // "?") tasks=\(.inFlight.tasks // 0) queued=\(.inFlight.queued // 0)"' "$js2")
    say "  job state:  $inf"
    jq -e '(.inFlight.tasks // 0) == 0 and (.inFlight.queued // 0) == 0' "$js2" >/dev/null || { say "  -> BUSY: tasks in flight or queued"; bad=1; }
  fi
  # 3. transcript and subagent transcripts must have been still for QUIET_MIN minutes
  if [ -f "$PROJ/$SID.jsonl" ]; then
    age=$(( ( $(date +%s) - $(stat -c %Y "$PROJ/$SID.jsonl") ) / 60 ))
    say "  transcript: last write ${age} min ago (need >= $QUIET_MIN)"
    [ "$age" -ge "$QUIET_MIN" ] || { say "  -> BUSY: transcript written ${age} min ago"; bad=1; }
  else
    say "  -> transcript $PROJ/$SID.jsonl missing"; bad=1
  fi
  newest=$(find "$PROJ/$SID" -type f -newermt "-$QUIET_MIN min" 2>/dev/null | head -3)
  if [ -n "$newest" ]; then say "  -> BUSY: subagent/tool files written in the last $QUIET_MIN min:"; echo "$newest" | sed 's/^/       /' | tee -a "$LOG"; bad=1; fi
  # 4. pipeline jobs: any process running from, or sitting in, the DeedPortal repo
  #    (the watcher itself, this script and its parents are expected)
  local skip=" $$ " p watchpid
  watchpid=$(systemctl --user show -p MainPID --value claude-deed-watch.service 2>/dev/null)
  skip+="$watchpid "
  p=$$; while [ "$p" -gt 1 ] 2>/dev/null; do skip+="$p "; p=$(awk '/^PPid:/{print $2}' /proc/$p/status 2>/dev/null || echo 1); done
  local found=0 pid cmd cwd
  for d in /proc/[0-9]*; do
    pid=${d#/proc/}
    case "$skip" in *" $pid "*) continue ;; esac
    [ "$(stat -c %u "$d" 2>/dev/null)" = "$(id -u)" ] || continue
    cmd=$(tr '\0' ' ' < "$d/cmdline" 2>/dev/null) || continue
    [ -n "$cmd" ] || continue
    cwd=$(readlink "$d/cwd" 2>/dev/null)
    if [[ "$cmd" == *DeedPortal* || "$cwd" == "$REPO"* ]]; then
      [ "$found" = 0 ] && say "  -> BUSY: processes working in DeedPortal:"
      found=1; say "       $pid ${cmd:0:150}"
    fi
  done
  [ "$found" = 0 ] && say "  pipeline:   no job processes in DeedPortal" || bad=1
  # 5. anything else holding the deed config (another deed chat, a board, a resume)
  local others=""
  for d in /proc/[0-9]*; do
    pid=${d#/proc/}
    [ "$(stat -c %u "$d" 2>/dev/null)" = "$(id -u)" ] || continue
    case "$(readlink "$d/exe" 2>/dev/null)" in */claude/versions/*) ;; *) continue ;; esac
    if tr '\0' '\n' < "$d/environ" 2>/dev/null | grep -qx "CLAUDE_CONFIG_DIR=$DEED/\?"; then
      cmd=$(tr '\0' ' ' < "$d/cmdline" 2>/dev/null)
      case "$cmd" in *"$SID"*|*"--bg-pty-host"*|*" daemon run"*|*"--bg-spare"*) continue ;; esac
      case "$cmd" in *"attach $SHORT"*) say "  note:       the chat is open in a terminal (pid $pid, claude attach): close that terminal before --go"; continue ;; esac
      others+="       $pid ${cmd:0:150}"$'\n'
    fi
  done
  if [ -n "$others" ]; then say "  -> BUSY: other Claude processes on the deed config:"; printf '%s' "$others" | tee -a "$LOG"; bad=1; fi
  # 6. the portal inbox, the same read the watcher does (GET only, changes nothing)
  local unread
  unread=$(cd "$REPO/pipeline" && set -a && . "$HOME/.config/deed-portal/credentials" && set +a &&
    timeout 90 ./venv/bin/python - 2>&1 <<'PY'
import portal
n = 0
for j in portal.api('/api/jobs', method='GET'):
    n += len(portal.api('/api/agent/inbox?job=' + j['id'], method='GET'))
print(n)
PY
  )
  if [[ "$unread" =~ ^[0-9]+$ ]]; then
    say "  portal:     $unread unread client message(s)"
    [ "$unread" = 0 ] || { say "  -> BUSY: the client is waiting on an answer"; bad=1; }
  else
    say "  -> could not read the portal inbox: ${unread:0:200}"; bad=1
  fi
  return $bad
}

# ---------------------------------------------------------------- pre-flight (server side, read-only)
preflight() {
  local bad=0 v1 v2
  say "pre-flight"
  S true || die "cannot ssh to $SERVER"
  v1=$(claude --version 2>/dev/null | awk '{print $1}'); v2=$(S 'claude --version' 2>/dev/null | awk '{print $1}')
  say "  claude:     laptop $v1, server $v2"; [ "$v1" = "$v2" ] || warn "Claude versions differ (the resume still works, but check)"
  S "test -d ~/code/MyLittleProjects/DeedPortal/work" || { say "  -> server has no DeedPortal/work (pre-seed missing)"; bad=1; }
  S "cd ~/code/MyLittleProjects/DeedPortal/pipeline && venv/bin/python -c 'import img2pdf,lxml,numpy,cv2,openpyxl,pikepdf,PIL,docx,websocket'" \
    && say "  server venv: imports ok" || { say "  -> server venv broken"; bad=1; }
  S 'command -v pdftoppm soffice jq >/dev/null && fc-match Calibri | grep -q Carlito && test -f /usr/share/fonts/truetype/msttcorefonts/Times_New_Roman.ttf' \
    && say "  server tools/fonts: ok" || { say "  -> server tools/fonts missing"; bad=1; }
  S 'test -L ~/.claude-deed/projects && test -f ~/.claude-deed/settings.json' && say "  server ~/.claude-deed: laid out" || { say "  -> server ~/.claude-deed not prepared"; bad=1; }
  if S 'test -e ~/.claude-deed/.credentials.json'; then say "  -> server ALREADY has a deed login: cutover done before? refusing"; bad=1; fi
  for u in "${SERVER_UNITS[@]}"; do S "test -f ~/.config/systemd/user/$u" || { say "  -> server unit $u missing"; bad=1; }; done
  for f in bin/deedwork bin/deed-push-limits bin/claude-deed bin/claude-c-deed bin/claude-account-deed bin/claude-creds-guard .local/bin/claude-limits .local/bin/claude-account .config/deed-portal/credentials; do
    S "test -e ~/$f" || { say "  -> server missing ~/$f"; bad=1; }
  done
  [ -f "$STAGE/claude-creds-guard.new" ] && [ -f "$STAGE/claude-c-deed.remote" ] && [ -f "$STAGE/claude-deed.remote" ] || { say "  -> staged files missing in $STAGE"; bad=1; }
  [ -f "$DEED/.credentials.json" ] || { say "  -> laptop has no deed login to move"; bad=1; }
  # things that degrade the job but do not block the move
  S 'curl -s -m 5 -o /dev/null http://127.0.0.1:8080/' && say "  whatsapp:   bridge answers on server :8080" || warn "no WhatsApp bridge on the server yet (agent C): watcher/canary escalations and notify_stage will fail until it is there"
  S 'test -f ~/.config/.wrangler/config/default.toml || test -n "${CLOUDFLARE_API_TOKEN:-}"' && say "  wrangler:   server has a login" || warn "server has no wrangler login: deploys and d1 execute from the deed chat will fail until one exists (see deed-prep notes)"
  S 'command -v send-gmail >/dev/null && test -f ~/.config/claude/gmail.json' && say "  send-gmail: present" || warn "no send-gmail on the server: notify_email (client stage e-mails) will fail; WhatsApp stage line unaffected"
  S 'command -v claude-c >/dev/null' && say "  claude-c:   present on server" || warn "no claude-c on the server yet: step g will copy a snapshot of chats.py so claude-c-deed works"
  local bytes
  bytes=$(rsync "${RSYNC_REPO[@]}" --dry-run --stats "$REPO/" "$SERVER:code/MyLittleProjects/DeedPortal/" 2>/dev/null | awk -F': ' '/Total transferred file size/{gsub(/[^0-9]/,"",$2); print $2}')
  say "  repo delta: $(numfmt --to=iec "${bytes:-0}" 2>/dev/null || echo "${bytes:-?}") still to send"
  return $bad
}

# ---------------------------------------------------------------- helpers for --go
laptop_units() { systemctl --user "$1" "${LAPTOP_UNITS[@]}" >>"$LOG" 2>&1; }
STOPPED_AGENT=0
undo_before_creds() {
  say "undoing: laptop keeps the job"
  if [ "$STOPPED_AGENT" = 1 ]; then
    (cd "$HOME" && deedc claude --bg --resume "$SID" "${FLAGS[@]}" >>"$LOG" 2>&1) && say "  resumed the deed chat on the laptop" || say "  COULD NOT resume the deed chat on the laptop: run claude-deed"
  fi
  systemctl --user unmask "${LAPTOP_UNITS[@]}" >>"$LOG" 2>&1
  laptop_units start && say "  laptop watcher/canary/push-limits running again"
}
wait_gone() {  # wait until no process carries the session id
  local i
  for i in $(seq 1 60); do
    # the bracket keeps grep from matching its own command line
    if ! grep -lqs "${SID%?}[${SID: -1}]" /proc/[0-9]*/cmdline 2>/dev/null; then return 0; fi
    sleep 1
  done
  return 1
}

# ---------------------------------------------------------------- main
MODE=${1:-check}
say "deed cutover ($MODE), log $LOG, flags: ${FLAGS[*]}"
if [ "$MODE" = check ]; then
  pf=0; preflight || pf=1
  say "idle check (read-only)"
  if idle_check; then say "RESULT: deed chat is IDLE"; else say "RESULT: deed chat is NOT idle"; fi
  [ "$pf" = 0 ] && say "pre-flight: OK" || say "pre-flight: PROBLEMS above"
  exit 0
fi
[ "$MODE" = --go ] || die "usage: $0 [--go]"

preflight || die "pre-flight failed"
say "a) idle check"
idle_check || die "not idle; nothing was changed"

say "warm rsync of DeedPortal (everything still running)"
rsync "${RSYNC_REPO[@]}" "$REPO/" "$SERVER:code/MyLittleProjects/DeedPortal/" >>"$LOG" 2>&1 || warn "warm rsync reported errors (final pass follows)"

say "b) stopping the laptop watcher, canary and push-limits"
laptop_units stop
say "   re-checking idle with the watcher stopped"
idle_check || { undo_before_creds; die "went busy during the switch; laptop restored, try again later"; }

say "c) stopping the deed agent on the laptop"
if [ -n "$AGENT_PID" ]; then
  deedc timeout 60 claude stop "$SHORT" >>"$LOG" 2>&1 || warn "claude stop returned non-zero"
  STOPPED_AGENT=1
fi
wait_gone || { undo_before_creds; die "the session is still running after claude stop"; }
deedc timeout 60 claude daemon stop --any >>"$LOG" 2>&1 || true
sleep 2
for d in /proc/[0-9]*; do
  case "$(readlink "$d/exe" 2>/dev/null)" in */claude/versions/*) ;; *) continue ;; esac
  if tr '\0' '\n' < "$d/environ" 2>/dev/null | grep -qx "CLAUDE_CONFIG_DIR=$DEED/\?"; then
    undo_before_creds; die "a Claude process still uses the deed config: ${d#/proc/} $(tr '\0' ' ' < "$d/cmdline" | cut -c1-120)"
  fi
done
say "   laptop deed agent and daemon are down"

say "d) final rsync"
rsync "${RSYNC_REPO[@]}" "$REPO/" "$SERVER:code/MyLittleProjects/DeedPortal/" >>"$LOG" 2>&1 || { undo_before_creds; die "repo rsync failed"; }
rsync -aH "$PROJ/$SID.jsonl" "$PROJ/$SID" "$SERVER:.claude/projects/-home-eitan/" >>"$LOG" 2>&1 || { undo_before_creds; die "transcript rsync failed"; }
rsync -a --exclude='.credentials.json*' --exclude='daemon/' --exclude='daemon*' --exclude='usage-cache/' \
  --exclude='cache/' --exclude='telemetry/' --exclude='state/' --exclude='backups/' --exclude='.claude.json.tmp.*' \
  --exclude='.claude.json.lock' --exclude='.last-*' --exclude='.active-account' \
  "$DEED/" "$SERVER:.claude-deed/" >>"$LOG" 2>&1 || { undo_before_creds; die "~/.claude-deed rsync failed"; }
rsync -a "$HOME/.claude/projects/-home-eitan/memory/" "$SERVER:.claude/projects/-home-eitan/memory/" >>"$LOG" 2>&1
rsync -a "$HOME/.claude/CLAUDE.md" "$HOME/.claude/statusline.sh" "$SERVER:.claude/" >>"$LOG" 2>&1
S "stat -c %s ~/.claude/projects/-home-eitan/$SID.jsonl" | grep -qx "$(stat -c %s "$PROJ/$SID.jsonl")" \
  || { undo_before_creds; die "transcript size differs on the server after rsync"; }
say "   repo, transcript and deed config state are on the server"

say "e) moving the deed login"
python3 - "$DEED/.credentials.json" <<'PY' || { undo_before_creds; die "the laptop deed login is blank: needs a browser /login by Eitan first"; }
import json, sys
d = json.load(open(sys.argv[1])); o = d.get("claudeAiOauth") or d
sys.exit(0 if (o.get("refreshToken") or o.get("accessToken")) else 1)
PY
S 'umask 077; mkdir -p ~/.claude-deed' && \
  scp -q -p "$DEED/.credentials.json" "$SERVER:.claude-deed/.credentials.json.incoming" && \
  S 'chmod 600 ~/.claude-deed/.credentials.json.incoming && mv ~/.claude-deed/.credentials.json.incoming ~/.claude-deed/.credentials.json && echo deed > ~/.claude-deed/.active-account' \
  || { undo_before_creds; die "copying the login to the server failed"; }
auth=$(S 'CLAUDE_CONFIG_DIR=~/.claude-deed timeout 60 claude auth status 2>&1' | python3 -c '
import json, sys, re
t = sys.stdin.read()
m = re.search(r"\{.*\}", t, re.S)
try:
    d = json.loads(m.group(0)) if m else {}
except Exception:
    d = {}
def find(o, keys):
    if isinstance(o, dict):
        for k, v in o.items():
            if k in keys and isinstance(v, (str, bool)): return v
            r = find(v, keys)
            if r is not None: return r
    return None
print(find(d, ("loggedIn",)), find(d, ("email", "emailAddress")))')
say "   server auth status: $auth"
if [ "$auth" != "True $DEED_EMAIL" ]; then
  S "mkdir -p ~/.claude/accounts/.deed-failed-move && mv ~/.claude-deed/.credentials.json ~/.claude/accounts/.deed-failed-move/credentials.$STAMP.json" >>"$LOG" 2>&1
  undo_before_creds; die "the server could not use the deed login ($auth); laptop keeps it"
fi
S 'claude-account-deed save deed' >>"$LOG" 2>&1 || warn "server claude-account-deed save failed"
S 'claude-account-deed list' 2>&1 | grep -q 'deed is using this' && say "   server slot 'deed' live (the watcher's account check will pass)" || warn "server claude-account-deed list does not show the deed slot live"
# park the laptop copies where no tool looks: not a slot, not in backups/ (claude-account
# restore takes the newest backups/ entry and would put the deed login into ~/.claude)
umask 077; mkdir -p "$PARK"
for f in .credentials.json .credentials.json.bak .active-account; do [ -e "$DEED/$f" ] && mv "$DEED/$f" "$PARK/"; done
[ -d "$HOME/.claude/accounts/deed" ] && mv "$HOME/.claude/accounts/deed" "$PARK/slot-deed"
printf 'deed login moved to %s at %s; parked copies in %s (stale once the server refreshes)\n' "$SERVER" "$(date -Is)" "$PARK" > "$DEED/.moved-to-server"
cp -p "$HOME/bin/claude-creds-guard" "$HOME/bin/claude-creds-guard.pre-deed-move"
install -m 755 "$STAGE/claude-creds-guard.new" "$HOME/bin/claude-creds-guard"
rsync -a "$STAGE/claude-creds-guard.new" "$SERVER:bin/claude-creds-guard"
say "   laptop copy parked in $PARK; laptop creds-guard now skips ~/.claude-deed"

say "f) starting the deed chat on the server (${FLAGS[*]})"
S "cd ~ && CLAUDE_CONFIG_DIR=~/.claude-deed claude --bg --resume $SID $(printf '%q ' "${FLAGS[@]}")" >>"$LOG" 2>&1 || warn "claude --bg returned non-zero"
newsid=""; spid=""
for i in $(seq 1 60); do
  row=$(S 'CLAUDE_CONFIG_DIR=~/.claude-deed claude agents --json' 2>/dev/null | jq -c --arg s "$SHORT" '[.[] | select((.sessionId // "") | startswith($s))][0] // empty')
  if [ -n "$row" ]; then newsid=$(jq -r .sessionId <<<"$row"); spid=$(jq -r .pid <<<"$row"); break; fi
  sleep 2
done
[ -n "$newsid" ] || die "the deed chat did not come up on the server: run ~/fleet-staging/deed-rollback.sh"
say "   server agent pid=$spid session=$newsid"
S "echo $newsid > ~/code/MyLittleProjects/DeedPortal/work/session-id"
for i in $(seq 1 30); do S "test -S /run/user/\$(id -u)/cc-socks/$spid.sock" && break; sleep 2; done
S "test -S /run/user/\$(id -u)/cc-socks/$spid.sock" && say "   wake socket present" || warn "no cc-socks socket for pid $spid yet (the watcher will fall back to --resume)"
S "systemctl --user daemon-reload && systemctl --user enable --now ${SERVER_UNITS[*]}" >>"$LOG" 2>&1 || warn "enabling server units reported errors"
systemctl --user disable "${LAPTOP_UNITS[@]}" >>"$LOG" 2>&1
systemctl --user mask "${LAPTOP_UNITS[@]}" >>"$LOG" 2>&1
say "   laptop watch/canary/push-limits disabled and masked"
S 'systemctl --user start deed-push-limits.service' >>"$LOG" 2>&1 && say "   push-limits ran on the server" || warn "push-limits failed on the server (journalctl --user -u deed-push-limits on the server)"
sleep 130
hb=$(S 'echo $(( $(date +%s) - $(stat -c %Y ~/code/MyLittleProjects/DeedPortal/work/watch-heartbeat) ))')
[ "${hb:-999}" -lt 150 ] && say "   server watcher heartbeat ${hb}s old: polling" || warn "server watcher heartbeat is ${hb}s old"
S 'tail -3 ~/code/MyLittleProjects/DeedPortal/work/client-activity.log' | sed 's/^/     /' | tee -a "$LOG"

say "g) laptop launchers now open the server"
for n in claude-c-deed claude-deed; do
  [ -e "$HOME/bin/$n.local" ] || mv "$HOME/bin/$n" "$HOME/bin/$n.local"
  install -m 755 "$STAGE/$n.remote" "$HOME/bin/$n"
done
if ! S 'command -v claude-c >/dev/null'; then
  S 'mkdir -p ~/.claude/chats ~/.local/bin'
  rsync -a "$HOME/.local/bin/claude-custom" "$SERVER:.local/bin/claude-custom"
  S 'ln -sfn ~/.local/bin/claude-custom ~/.local/bin/claude-c'
  rsync -a --exclude='__pycache__/' --exclude='*.bak*' --exclude='_backup-*/' --exclude='recovered/' "$HOME/.claude/chats/" "$SERVER:.claude/chats/"
  say "   copied a snapshot of claude-c (chats.py + board state) to the server"
else
  S "python3 - <<'PY'
import json, pathlib
p = pathlib.Path.home() / '.claude/chats/chat_projects.json'
try: d = json.loads(p.read_text())
except Exception: d = {}
if d.get('$SID') != 'Deed':
    d['$SID'] = 'Deed'; p.write_text(json.dumps(d, indent=2) + '\n')
PY"
  say "   server board already exists; tagged the deed chat 'Deed' there"
fi

cat >> "$HOME/fleet-staging/PROGRESS.md" <<EOF

### D: deed cutover ran $(date '+%F %H:%M')
- deed chat $SHORT now runs on the server (pid $spid), watcher/canary/push-limits/creds-guard enabled there.
- laptop units disabled+masked; laptop deed login parked in $PARK; claude-c-deed/claude-deed are ssh wrappers.
- rollback: ~/fleet-staging/deed-rollback.sh. Log: $LOG
EOF
say "DONE. Attach from the laptop with: claude-c-deed   (or: ssh -t $SERVER claude attach $SHORT)"
