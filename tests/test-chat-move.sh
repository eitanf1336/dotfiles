#!/usr/bin/env bash
# Tests for chat-move (~/code/linux-setup/bin/chat-move). Run on the SERVER (needs ssh laptop).
# Uses only throwaway trees under /tmp/cmtest on both machines.
set -u
CM=${CM:-$HOME/bin/chat-move}            # the copy on the server
LCM=${LCM:-/home/eitan/bin/chat-move}    # the copy on the laptop
T=/tmp/cmtest
export CHAT_MOVE_STATE=$T/state
pass=0; fail=0
ok()  { echo "PASS $*"; pass=$((pass+1)); }
bad() { echo "FAIL $*"; fail=$((fail+1)); }
L() { ssh -o BatchMode=yes laptop "$@"; }
snap() { L "cd $1 && find . -type f -printf '%p %s %T@\n' | sort | md5sum"; }

rm -rf "$T"; L "rm -rf $T"
# Receiver (laptop): the "full" project with 5 folders, one file newer and different.
L "mkdir -p $T/proj/{a,b,c,d,e} && for d in a b c d e; do echo full-\$d > $T/proj/\$d/keep.txt; done && echo laptop-version-newer > $T/proj/a/x.txt"
# Sender (server): a trimmed copy with only a and b, and a different a/x.txt.
mkdir -p $T/proj/{a,b}; echo srv-a > $T/proj/a/keep.txt; echo srv-b > $T/proj/b/keep.txt; echo server-version > $T/proj/a/x.txt; touch -d "2 hours ago" $T/proj/a/x.txt; echo new > $T/proj/b/new.txt

# 1. non-git dir without --cwd is refused
(cd $T/proj && bash $CM laptop --files-only >/tmp/cm1.out 2>&1); rc=$?
[ $rc = 3 ] && grep -q 'not inside a git repo' /tmp/cm1.out && ok "1 non-git root refused without --cwd" || { bad "1 rc=$rc"; cat /tmp/cm1.out; }

# 2. the accident: partial sender, explicit --cwd, no --force -> abort, receiver untouched
before=$(snap $T/proj)
bash $CM laptop --cwd $T/proj --files-only >/tmp/cm2.out 2>&1; rc=$?
after=$(snap $T/proj)
[ $rc = 4 ] && [ "$before" = "$after" ] && grep -q '3 top-level entries' /tmp/cm2.out && ok "2 partial sender aborts, laptop tree unchanged" || { bad "2 rc=$rc"; cat /tmp/cm2.out; }

# 3. --dry-run prints the summary and copies nothing
bash $CM laptop --cwd $T/proj --files-only --dry-run >/tmp/cm3.out 2>&1; rc=$?
[ $rc = 0 ] && [ "$(snap $T/proj)" = "$before" ] && grep -q "1 files to add.*3 files to OVERWRITE on laptop (1 of them newer there)" /tmp/cm3.out && ok "3 dry run summary (1 add, 3 overwrite), nothing copied" || { bad "3 rc=$rc"; cat /tmp/cm3.out; }

# 4. overwrite threshold
mkdir -p $T/proj/c $T/proj/d $T/proj/e   # make the top level match so only the threshold trips
CHAT_MOVE_MAX_OVERWRITE=1 bash $CM laptop --cwd $T/proj --files-only >/tmp/cm4.out 2>&1; rc=$?
[ $rc = 4 ] && [ "$(snap $T/proj)" = "$before" ] && grep -q 'more than the limit of 1' /tmp/cm4.out && ok "4 overwrite count over limit aborts" || { bad "4 rc=$rc"; cat /tmp/cm4.out; }
rmdir $T/proj/c $T/proj/d $T/proj/e

# 5. --force: copies, receiver-only files survive, overwritten versions kept in the backup dir
bash $CM laptop --cwd $T/proj --files-only --force >/tmp/cm5.out 2>&1; rc=$?
surv=$(L "cat $T/proj/c/keep.txt $T/proj/d/keep.txt $T/proj/e/keep.txt" | tr '\n' ' ')
kept=$(L "cat $T/state/backups/*$T/proj/a/x.txt" 2>/dev/null)
newx=$(L "cat $T/proj/a/x.txt; cat $T/proj/b/new.txt" | tr '\n' ' ')
[ $rc = 0 ] && [ "$surv" = "full-c full-d full-e " ] && [ "$kept" = laptop-version-newer ] && [ "$newx" = "server-version new " ] \
  && ok "5 --force: c,d,e survive on laptop; old a/x.txt kept in backup dir; new files arrived" || { bad "5 rc=$rc surv=[$surv] kept=[$kept] newx=[$newx]"; cat /tmp/cm5.out; }

# 6. no --delete anywhere in the real transfer
! grep -n -- '--delete' $CM | grep -v '^[0-9]*: *#' | grep -q . && ok "6 no --delete in chat-move code" || { bad "6 found --delete"; grep -n -- '--delete' $CM; }

# 7. parent of several repos refused even with --cwd
mkdir -p $T/parent/r1 $T/parent/r2; git -C $T/parent/r1 init -q; git -C $T/parent/r2 init -q
bash $CM laptop --cwd $T/parent --files-only >/tmp/cm7.out 2>&1; rc=$?
[ $rc = 3 ] && grep -q 'parent of several projects' /tmp/cm7.out && ok "7 non-git parent of repos refused" || { bad "7 rc=$rc"; cat /tmp/cm7.out; }

# 8. symmetric excludes: laptop -> server with --exclude BIG (laptop only), then server -> laptop with no excludes
SID=00000000-test-cm00-0000-000000000000
L "mkdir -p $T/repo/src $T/repo/BIG && cd $T/repo && git init -q && echo v1 > src/m.py && echo huge > BIG/data.bin"
L "cd $T/repo && CHAT_MOVE_STATE=$T/state bash $LCM server $SID --files-only --exclude BIG" >/tmp/cm8a.out 2>&1; rc1=$?
[ ! -e $T/repo/BIG ] && [ -f $T/repo/src/m.py ] && [ -f $T/state/$SID.excludes ] || { bad "8a rc=$rc1 BIG copied or memo missing"; cat /tmp/cm8a.out; }
echo v2 > $T/repo/src/m.py
(cd $T/repo && bash $CM laptop $SID --files-only) >/tmp/cm8b.out 2>&1; rc2=$?
back=$(L "cat $T/repo/src/m.py; ls $T/repo/BIG" | tr '\n' ' ')
[ $rc1 = 0 ] && [ $rc2 = 0 ] && grep -q 'remembered excludes for this chat: BIG' /tmp/cm8b.out && [ "$back" = "v2 data.bin " ] \
  && ok "8 excludes remembered: move back reuses BIG, no false partial-copy alarm, laptop BIG intact" || { bad "8 rc1=$rc1 rc2=$rc2 back=[$back]"; cat /tmp/cm8a.out /tmp/cm8b.out; }

# 9. too-broad roots refused
bash $CM laptop --cwd "$HOME/code" --files-only --dry-run >/tmp/cm9.out 2>&1; rc=$?
[ $rc = 3 ] && ok "9 ~/code refused as a root" || { bad "9 rc=$rc"; cat /tmp/cm9.out; }

echo "== $pass passed, $fail failed"
rm -rf "$T"; L "rm -rf $T"
[ $fail = 0 ]
