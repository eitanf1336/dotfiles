#!/usr/bin/env bash
# deed-rollback.sh - bring the deed job back from the server to this laptop.
# Undoes deed-cutover.sh from any point after step e (for failures before e,
# the cutover script already put the laptop back by itself).  Prepared by agent D.
#
#   deed-rollback.sh          show what it would do (read-only)
#   deed-rollback.sh --go     do it
#
# The login is MOVED back, never copied: the server's copy is the newest (it may
# have refreshed), so it comes back here and is then parked on the server where
# nothing refreshes it. Old parked laptop copies are stale once the server has
# refreshed, so they are only a last resort.
set -uo pipefail
cd "$HOME" || exit 1

SID=1c976435-dfde-4deb-90a9-6e02954c14e6
SHORT=${SID:0:8}
DEED_EMAIL=betscar.office@proton.me
DEED=$HOME/.claude-deed
REPO=$HOME/code/MyLittleProjects/DeedPortal
PROJ=$HOME/.claude/projects/-home-eitan
SERVER=${DEED_SERVER:-server}
STAMP=$(date +%Y%m%d-%H%M%S)
LOGDIR=$HOME/fleet-staging/logs; mkdir -p "$LOGDIR"
LOG=$LOGDIR/deed-rollback-$STAMP.log
LAPTOP_UNITS=(claude-deed-watch.service deed-watch-canary.timer deed-push-limits.timer)
SERVER_UNITS=(claude-deed-watch.service deed-watch-canary.timer deed-push-limits.timer claude-creds-guard.timer)
say()  { printf '%s  %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG"; }
die()  { say "STOP: $*"; exit 1; }
S()    { ssh -o BatchMode=yes -o ConnectTimeout=15 "$SERVER" "$@"; }
deedc() { CLAUDE_CONFIG_DIR=$DEED "$@"; }
FLAGS=(--effort xhigh --model opus)   # the laptop roster's respawnFlags for this chat

MODE=${1:-plan}
S true || die "cannot ssh to $SERVER"
srv_login=$(S 'test -s ~/.claude-deed/.credentials.json && echo yes || echo no')
lap_login=$([ -s "$DEED/.credentials.json" ] && echo yes || echo no)
say "deed rollback ($MODE): server login=$srv_login laptop login=$lap_login"
if [ "$MODE" != --go ]; then
  say "would: stop server units + deed agent, rsync repo/transcript back (no delete),"
  say "       move the login back (server copy wins), restore launchers, unmask + start laptop units, resume the chat here"
  exit 0
fi

say "1. stopping the server side"
S "systemctl --user disable --now ${SERVER_UNITS[*]}" >>"$LOG" 2>&1
S "CLAUDE_CONFIG_DIR=~/.claude-deed timeout 60 claude stop $SHORT" >>"$LOG" 2>&1
S 'CLAUDE_CONFIG_DIR=~/.claude-deed timeout 60 claude daemon stop --any' >>"$LOG" 2>&1
PAT="${SID%?}[${SID: -1}]"   # bracket: grep must not match its own command line
for i in $(seq 1 30); do S "grep -lqs '$PAT' /proc/[0-9]*/cmdline" || break; sleep 2; done
S "grep -lqs '$PAT' /proc/[0-9]*/cmdline" && die "the deed chat is still running on the server; stop it by hand (ssh server claude stop $SHORT)"
say "   server deed chat and units stopped"

say "2. bringing the work back (no deletes on the laptop)"
rsync -aH --exclude=/pipeline/venv/ --exclude=__pycache__/ "$SERVER:code/MyLittleProjects/DeedPortal/" "$REPO/" >>"$LOG" 2>&1 || die "repo rsync back failed"
rsync -aH "$SERVER:.claude/projects/-home-eitan/$SID.jsonl" "$SERVER:.claude/projects/-home-eitan/$SID" "$PROJ/" >>"$LOG" 2>&1 || die "transcript rsync back failed"
rsync -a "$SERVER:.claude-deed/.claude.json" "$DEED/.claude.json" >>"$LOG" 2>&1
rsync -a "$SERVER:.claude-deed/jobs/" "$DEED/jobs/" >>"$LOG" 2>&1
say "   repo and transcript are back"

say "3. moving the login back"
umask 077
if [ "$srv_login" = yes ]; then
  scp -q -p "$SERVER:.claude-deed/.credentials.json" "$DEED/.credentials.json.incoming" || die "could not copy the login back"
  chmod 600 "$DEED/.credentials.json.incoming"; mv "$DEED/.credentials.json.incoming" "$DEED/.credentials.json"
  S "mkdir -p ~/.claude/accounts/.deed-moved-to-laptop/$STAMP && mv ~/.claude-deed/.credentials.json ~/.claude-deed/.active-account ~/.claude/accounts/.deed-moved-to-laptop/$STAMP/ 2>/dev/null; [ -d ~/.claude/accounts/deed ] && mv ~/.claude/accounts/deed ~/.claude/accounts/.deed-moved-to-laptop/$STAMP/slot-deed; true"
  say "   server copy moved here; server copies parked in ~/.claude/accounts/.deed-moved-to-laptop/$STAMP on the server"
elif [ "$lap_login" = no ]; then
  last=$(ls -1d "$HOME"/.claude/accounts/.deed-moved-to-server/*/ 2>/dev/null | tail -1)
  [ -n "$last" ] && [ -f "$last/.credentials.json" ] || die "no deed login anywhere: Eitan must /login in claude-deed"
  cp -p "$last/.credentials.json" "$DEED/.credentials.json"
  say "   WARNING: used the parked laptop copy from $last; if the server ever refreshed it, it is dead and Eitan must /login"
fi
echo deed > "$DEED/.active-account"
rm -f "$DEED/.moved-to-server"
auth=$(deedc timeout 60 claude auth status 2>&1)
case "$auth" in *'"loggedIn": true'*"$DEED_EMAIL"*|*"$DEED_EMAIL"*'"loggedIn": true'*) say "   laptop auth ok ($DEED_EMAIL)" ;;
  *) say "   WARNING: laptop auth status did not confirm $DEED_EMAIL: check 'claude-account-deed list'" ;; esac
claude-account-deed save deed >>"$LOG" 2>&1 && say "   laptop slot 'deed' re-parked from the live login"

say "4. launchers back"
for n in claude-c-deed claude-deed; do
  [ -f "$HOME/bin/$n.local" ] && mv -f "$HOME/bin/$n.local" "$HOME/bin/$n"
done
# the patched creds-guard stays: with the marker gone it guards ~/.claude-deed again.
# (the pre-move copy is ~/bin/claude-creds-guard.pre-deed-move if wanted)

say "5. laptop units back on, chat resumed here"
systemctl --user unmask "${LAPTOP_UNITS[@]}" >>"$LOG" 2>&1
systemctl --user enable --now "${LAPTOP_UNITS[@]}" >>"$LOG" 2>&1
(cd "$HOME" && deedc claude --bg --resume "$SID" "${FLAGS[@]}" >>"$LOG" 2>&1) || say "   could not resume the chat: run claude-deed"
echo "$SID" > "$REPO/work/session-id"
sleep 5
deedc claude agents --json 2>/dev/null | jq -r --arg s "$SID" '.[] | select(.sessionId == $s) | "   laptop agent pid=\(.pid) status=\(.status)"' | tee -a "$LOG"
cat >> "$HOME/fleet-staging/PROGRESS.md" <<EOF

### D: deed ROLLED BACK to the laptop $(date '+%F %H:%M')
- chat, watcher, canary, push-limits and the deed login are on the laptop again. Log: $LOG
EOF
say "DONE: deed job is back on the laptop"
