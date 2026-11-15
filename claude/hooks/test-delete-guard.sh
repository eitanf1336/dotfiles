#!/usr/bin/env bash
# Feeds sample PreToolUse JSON to delete-guard.py. Usage: test-delete-guard.sh [path-to-guard]
G=${1:-$(dirname "$0")/delete-guard.py}
pass=0; fail=0
run() { # expect(0|2) cwd command
  local want=$1 cwd=$2 cmd=$3 got
  python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","cwd":sys.argv[1],"tool_input":{"command":sys.argv[2]}}))' "$cwd" "$cmd" \
    | python3 "$G" 2>/dev/null; got=$?
  if [ "$got" = "$want" ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL want=$want got=$got cwd=$cwd :: $cmd"; fi
}
H=$HOME; P=$H/code/MyProjects/App
# must BLOCK (2)
run 2 $H 'rsync -a --delete src/ laptop:src/'
run 2 $H 'rsync -av --delete-after a/ b/'
run 2 $H 'cd x && rsync -a --del a/ b/'
run 2 $H 'R="rsync -a"; $R --delete ~/.claude/skills server:.claude/'
run 2 $H "ssh server 'rsync -a --delete-excluded a/ b/'"
run 2 $H 'rclone sync ~/x gdrive:x'
run 2 $H '~/bin/rclone purge gdrive:Old'
run 2 $H 'rm -rf ~/code'
run 2 $H 'rm -rf ~/code/'
run 2 $H 'rm -rf ~/code/MyProjects'
run 2 $H 'rm -rf ~/code/MyProjects/App'
run 2 $H 'rm -r "$HOME/code/Technion/Research"'
run 2 $H 'rm -rf /home/eitan/code/Technion/Research/*'
run 2 $H 'rm -rf ~'
run 2 $H 'rm -rf ~/*'
run 2 $H 'rm -fr $HOME/'
run 2 $H 'rm --recursive --force ~/code/linux-setup'
run 2 $P 'rm -rf .'
run 2 $P 'rm -rf *'
run 2 $H 'cd ~/code/Technion && rm -rf Research'
run 2 $H "ssh laptop 'rm -rf ~/code/Technion/Research'"
run 2 $P 'git clean -fdx'
run 2 $P 'git clean -f -d'
# must PASS (0)
run 0 $H 'ls -la ~/code'
run 0 $H 'rsync -a src/ laptop:src/'
run 0 $H 'rsync -an --delete --itemize-changes src/ laptop:src/'
run 0 $H 'rsync -a --dry-run --delete src/ dst/'
run 0 $H 'rsync -a --delete src/ dst/   # I-CHECKED-DRY-RUN'
run 0 $H 'rclone sync --dry-run ~/x gdrive:x'
run 0 $H '~/bin/rclone copyto a.txt gdrive:F/a.txt'
run 0 $H '~/bin/rclone deletefile gdrive:F/a.txt'
run 0 $H 'rm -rf ~/code/MyProjects/App/node_modules'
run 0 $P 'rm -rf build dist .cache'
run 0 $H 'rm -rf /tmp/x'
run 0 $H 'rm ~/code/MyProjects/App'
run 0 $H 'rm -f ~/code/notes.txt.bak'
run 0 $H 'rm -rf "$tmp"'
run 0 $H 'rm -rf ~/code/MyProjects   # I-CHECKED-DRY-RUN'
run 0 $P 'git clean -n -dx'
run 0 $P 'git status && git log --oneline -3'
run 0 $H 'grep -rn "delete" ~/bin | head'
run 0 $H 'git push origin --delete old-branch'
run 0 $H 'python3 -c "print(1)"'
run 0 $H 'grep -rnE -- "--delete|rclone sync" ~/bin ~/code/linux-setup | grep -v RSYNC_REPO'
run 0 $H 'git commit -m "chat-move: never rsync --delete, back up overwrites"'
run 0 $H 'echo rm -rf ~/code'
run 2 $H 'sudo rm -rf ~/code/MyProjects'
run 2 $H 'cd /tmp && rsync -a --delete-excluded a/ b/'
run 2 /tmp "ssh laptop 'cd ~/code/MyProjects && rm -rf *'"
run 0 /tmp "ssh laptop 'cd ~/code/MyProjects/App/sub && rm -rf build'"
run 2 $H 'bash -c "echo hi; rsync -a --delete a/ b/"'
run 0 $H 'ssh server "grep -c rclone\ sync ~/bin/* ; ls"'
# non-Bash tool and broken input pass
echo '{"tool_name":"Read","tool_input":{"file_path":"/x"}}' | python3 "$G" && pass=$((pass+1)) || { fail=$((fail+1)); echo "FAIL non-bash"; }
echo 'not json' | python3 "$G" && pass=$((pass+1)) || { fail=$((fail+1)); echo "FAIL bad json"; }
# speed
t0=$(date +%s%N); for i in 1 2 3 4 5 6 7 8 9 10; do echo '{"tool_name":"Bash","tool_input":{"command":"ls -la"}}' | python3 "$G"; done; t1=$(date +%s%N)
echo "avg $(( (t1-t0)/10000000 )) ms per call"
echo "== $pass passed, $fail failed"
[ $fail = 0 ]
