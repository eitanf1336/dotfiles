---
description: Read a past reply aloud via Read-Aloud TTS. /speak (or /speak 0) = last reply; /speak -1 = one back; /speak -2 = two back; etc.
argument-hint: "[-N]  (0 = last reply, -1 = one back, -2 = two back, ...)"
allowed-tools: Bash(speak-msg:*), Bash(/home/eitan/.local/bin/speak-msg:*)
model: haiku
---
Read one of my recent replies aloud through the local Read-Aloud text-to-speech
server — the same one bound to Ctrl+Shift+L — choosing which reply by argument:

- no argument or `0` → my most recent substantive reply
- `-1` → one reply further back, `-2` → two back, and so on

Do this in one step: run exactly the following via the Bash tool, substituting
the user's argument (use `0` if none was given):

    speak-msg $ARGUMENTS

`speak-msg` reads the session transcript, picks the right reply (skipping
thinking, tool output, and speak confirmations), starts the TTS server if
needed, and opens the player popup so it is spoken aloud. It handles
everything — do NOT reproduce, retype, or summarize the message yourself.
After it runs, reply with only a one-line confirmation (e.g. "🔊 Reading last
reply aloud." / "🔊 Reading 2 replies back aloud.") — nothing else.
