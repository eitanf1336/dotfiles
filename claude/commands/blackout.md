---
description: Black out every screen and freeze everything on the laptop except this chat and what it runs, with progress and notes on the main screen and a button to get the laptop back
argument-hint: [label] [--keep <unit or pattern> ...]   e.g. "Minecraft run" --keep minecraft-arena
allowed-tools: Bash(takeover:*), Bash(systemctl:*), Bash(ls:*), Bash(cat:*)
---

Hand this laptop to the work of THIS chat. Everything else is frozen in place with the
systemd freezer (nothing is closed, nothing loses state), every monitor goes black, and the
main screen shows a progress bar, a time estimate and a notes area in white text. The
screen's button "Stop and give the laptop back" and Ctrl+Alt+P (pause) belong to him.

What to do, in order:

1. Decide what this chat's work needs alive besides its own terminal: the units it starts
   or talks to (a bot service, a testbed server, a bridge). Standing exclusions already
   live in `~/.config/takeover/keep-units` and `~/.config/takeover/keep-chats` (the German
   deed chat and its monitor are there); do not remove those. Check the plan first:

   !`takeover plan`

2. Start the blackout with a label he will recognise and the extra units to keep:

       takeover hold -l "<label>" --keep <unit-or-regex> [--keep ...]

   `hold` freezes and shows the screen, then returns; this chat keeps working underneath.

3. While working, keep the screen honest:
   - `takeover progress <done> <total> "<what>"` whenever the count changes
     (for a render: frames; for a Minecraft run: episodes or minutes; for a batch: items).
   - `takeover note "<one line>"` for anything he would want to read on the screen:
     a stage finished, a result, a problem. Last 10 lines are shown.

4. When the work is done, or if it fails: `takeover finish`. That thaws everything,
   restores the power profile, closes the screen and sends a desktop notification.
   Never leave a blackout running after the work ends.

If a blackout is already running (`takeover status` says so), do not start another;
report it and ask whether to take it over.

Arguments given: $ARGUMENTS
