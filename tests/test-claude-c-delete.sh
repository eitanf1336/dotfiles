#!/usr/bin/env bash
# Tests claude-c-delete in a throwaway HOME: nothing real is touched, no ssh.
set -u
TOOL="$(cd "$(dirname "$0")/.." && pwd)/bin/claude-c-delete"
T="$(mktemp -d)"; export HOME="$T"; unset CLAUDE_CONFIG_DIR CLAUDE_CODE_SESSION_ID
SID=aaaaaaaa-1111-2222-3333-444444444444; OLD=bbbbbbbb-1111-2222-3333-444444444444; OTHER=cccccccc-1111-2222-3333-444444444444
C="$T/.claude"; fail=0
ok() { echo "ok   $1"; }; bad() { echo "FAIL $1"; fail=1; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
build() {
  mkdir -p "$C/projects/-x/$SID/subagents" "$C/jobs/abcd1234/tmp" "$C/state/ctx" "$C/chats" "$C/remote/server/projects/-x" "$C/sessions"
  echo '{"type":"user","message":{"content":"hello test chat"}}' > "$C/projects/-x/$SID.jsonl"
  echo sub > "$C/projects/-x/$SID/subagents/a.jsonl"
  echo '{"type":"user","message":{"content":"older copy"}}' > "$C/projects/-x/$OLD.jsonl"
  echo '{"type":"user","message":{"content":"other chat"}}' > "$C/projects/-x/$OTHER.jsonl"
  echo "{\"sessionId\":\"$SID\"}" > "$C/jobs/abcd1234/state.json"
  echo '{}' > "$C/state/ctx/$SID.json"
  echo mirror > "$C/remote/server/projects/-x/$SID.jsonl"
  printf '%s\n' "{\"display\":\"keep1\",\"sessionId\":\"$OTHER\"}" "{\"display\":\"mine\",\"sessionId\":\"$SID\"}" "{\"display\":\"keep2\",\"sessionId\":\"$OTHER\"}" > "$C/history.jsonl"
  echo "{\"$SID\":\"Done\",\"$OTHER\":\"Later\"}" > "$C/chats/categories.json"
  echo "{\"$SID\":\"My test chat\"}" > "$C/chats/names.json"
  echo "{\"$OLD\":\"$SID\"}" > "$C/chats/superseded.json"
  mkdir -p "/tmp/claude-$(id -u)/-ccdel-test/$SID"; echo out > "/tmp/claude-$(id -u)/-ccdel-test/$SID/t.output"
}
snap() { (cd "$C" && find projects jobs state -type f | sort | xargs sha256sum;
          python3 -c 'import json,sys,glob; [print(f, json.dumps(json.load(open(f)), sort_keys=True)) for f in sorted(glob.glob("chats/*.json"))]'); }

build; before="$(snap)"
out="$("$TOOL" --session "$SID" --peer-call)"; rc=$?
check "delete exits 0" "[ $rc = 0 ]"
check "transcript gone"        "[ ! -e '$C/projects/-x/$SID.jsonl' ]"
check "sidecar folder gone"    "[ ! -e '$C/projects/-x/$SID' ]"
check "older copy gone"        "[ ! -e '$C/projects/-x/$OLD.jsonl' ]"
check "other chat untouched"   "[ -e '$C/projects/-x/$OTHER.jsonl' ]"
check "job folder gone"        "[ ! -e '$C/jobs/abcd1234' ]"
check "ctx state gone"         "[ ! -e '$C/state/ctx/$SID.json' ]"
check "mirror copy gone"       "[ ! -e '$C/remote/server/projects/-x/$SID.jsonl' ]"
check "tmp output gone"        "[ ! -e '/tmp/claude-$(id -u)/-ccdel-test/$SID' ]"
check "history: mine removed"  "! grep -q $SID '$C/history.jsonl'"
check "history: others kept"   "[ \$(wc -l < '$C/history.jsonl') = 2 ]"
check "board: category gone"   "! grep -q $SID '$C/chats/categories.json' && grep -q $OTHER '$C/chats/categories.json'"
check "board: name gone"       "! grep -q $SID '$C/chats/names.json'"
check "board: link gone"       "! grep -q $SID '$C/chats/superseded.json'"
check "trash is private"       "[ \"\$(stat -c %a '$C/chat-trash')\" = 700 ] && [ -f '$C/chat-trash/README.txt' ]"
check "list shows it"          "'$TOOL' list --peer-call | grep -q 'aaaaaaaa.*29d left.*My test chat'"
"$TOOL" restore aaaaaaaa --peer-call >/dev/null; rc=$?
check "restore exits 0" "[ $rc = 0 ]"
after="$(snap)"
check "restore brings files and board entries back exactly" "[ \"\$before\" = \"\$after\" ]"
check "history line back"      "grep -q $SID '$C/history.jsonl' && [ \$(wc -l < '$C/history.jsonl') = 3 ]"
check "tmp output back"        "[ -e '/tmp/claude-$(id -u)/-ccdel-test/$SID/t.output' ]"
check "trash empty after restore" "[ -z \"\$(ls '$C/chat-trash' | grep -v README)\" ]"

# 30-day purge
"$TOOL" --session "$SID" --peer-call >/dev/null
b="$(ls -d "$C"/chat-trash/2*)"
"$TOOL" purge >/dev/null 2>&1; check "fresh copy survives purge" "[ -d '$b' ]"
python3 - "$b/manifest.json" <<'P'
import json,sys,time
m=json.load(open(sys.argv[1])); m["expires_at"]=time.time()-5; json.dump(m,open(sys.argv[1],"w"))
P
"$TOOL" purge >/dev/null 2>&1; check "expired copy is purged" "[ ! -e '$b' ]"

# backups: the chat leaves every snapshot of this machine's restic repository
if command -v restic >/dev/null && command -v home-backup >/dev/null; then
  rm -rf "$C"; build
  case "$(hostname)" in *-server) P=server;; *) P=laptop;; esac
  mkdir -p "$T/.config/restic"; echo pw > "$T/.config/restic/$P.pass"
  printf 'RESTIC_REPOSITORY=%s\nRESTIC_PASSWORD_FILE=%s\nRESTIC_CACHE_DIR=%s\n' "$T/repo" "$T/.config/restic/$P.pass" "$T/cache" > "$T/.config/restic/$P.env"
  hb() { home-backup restic "$@"; }
  hb init -q >/dev/null 2>&1; hb backup -q "$C" >/dev/null 2>&1; echo x >> "$C/projects/-x/$OTHER.jsonl"; hb backup -q "$C" >/dev/null 2>&1
  lsall() { for s in $(hb snapshots --json | python3 -c 'import json,sys;print(" ".join(x["short_id"] for x in json.load(sys.stdin)))'); do hb ls "$s"; done; }
  all="$(lsall)"
  check "backup: chat is in the snapshots before" "echo \"\$all\" | grep -c $SID >/dev/null"
  "$TOOL" --session "$SID" --peer-call >/dev/null
  for i in $(seq 1 30); do systemctl --user list-units --all --no-legend 'claude-c-delete-scrub-*' | grep -q . || break; sleep 1; done
  CLAUDE_C_DELETE_PRUNE_NOW=1 "$TOOL" scrub; rc=$?
  check "backup: scrub finishes and empties its queue" "[ $rc = 0 ] && [ ! -e '$C/chat-trash/pending-scrub.json' ]"
  all="$(lsall)"
  check "backup: chat, older copy, job folder, old prompt history gone from every snapshot" "! echo \"\$all\" | grep -qE '$SID|$OLD|jobs/abcd1234|history.jsonl'"
  check "backup: other chat still in both snapshots" "[ \$(echo \"\$all\" | grep -c '$OTHER.jsonl') = 2 ]"
  check "backup: repository still healthy" "hb check >/dev/null 2>&1"
  "$TOOL" restore aaaaaaaa --peer-call >/dev/null
else echo "skip backup tests (no restic/home-backup here)"; fi

# unknown chat, bad id
"$TOOL" --session dddddddd-1111-2222-3333-444444444444 --peer-call >/dev/null; check "unknown chat: exit 1, no bundle" "[ $? = 1 ] && [ -z \"\$(ls '$C/chat-trash' | grep -v 'README\|pending')\" ]"
"$TOOL" --session nope --peer-call >/dev/null; check "bad id refused" "[ $? = 2 ]"

# live chat: a stand-in process registered as the session; deletion is handed
# to a detached unit, which ends it and then moves the files
rm -rf "$C"; build
sleep 600 & SP=$!
echo "{\"pid\":$SP,\"sessionId\":\"$SID\"}" > "$C/sessions/$SP.json"
out="$("$TOOL" --session "$SID" --peer-call)"
check "live: says it will delete" "echo '$out' | grep -q 'Deleting this chat'"
check "live: nothing moved yet"   "[ -e '$C/projects/-x/$SID.jsonl' ]"
for i in $(seq 1 60); do [ -e "$C/projects/-x/$SID.jsonl" ] || break; sleep 1; done
check "live: transcript moved by the detached unit" "[ ! -e '$C/projects/-x/$SID.jsonl' ]"
check "live: session process ended" "! kill -0 $SP 2>/dev/null"
echo late >> "$C/projects/-x/$SID.jsonl"     # a dying session's last write
for i in $(seq 1 20); do [ -e "$C/projects/-x/$SID.jsonl" ] || break; sleep 1; done
check "live: late write swept too" "[ ! -e '$C/projects/-x/$SID.jsonl' ] && grep -q late '$C'/chat-trash/2*/files/projects/-x/$SID.jsonl"
kill $SP 2>/dev/null
rm -rf "/tmp/claude-$(id -u)/-ccdel-test"
[ $fail = 0 ] && echo "ALL PASSED" || echo "SOME FAILED (left in $T)"
[ $fail = 0 ] && rm -rf "$T"   # I-CHECKED-DRY-RUN (mktemp dir of this test)
exit $fail
