---
description: Read my previous reply aloud via the Read-Aloud TTS server (like selecting it + Ctrl+Shift+L)
allowed-tools: Bash(speak-text:*), Bash(/home/eitan/.local/bin/speak-text:*)
---
Read your **previous** assistant message aloud through the local Read-Aloud
text-to-speech server — exactly what selecting that message and pressing
Ctrl+Shift+L would do.

Do this now, in one step, with no preamble:

1. Take the full, verbatim prose of your previous reply to me (the last
   message you showed before this `/speak` command). Include only the visible
   text you actually displayed — **exclude** any thinking, tool calls, tool
   output, and this command itself. Do not summarize, translate, or shorten it;
   send it exactly as written.
2. Pipe that exact text into the helper via stdin using a heredoc:

   ```
   speak-text <<'SPEAK_EOF'
   <the exact text of your previous reply>
   SPEAK_EOF
   ```

The helper starts the TTS server if needed and opens the player popup, so the
text is spoken aloud. After it runs, reply with just a one-line confirmation
(e.g. "🔊 Reading last reply aloud.") — nothing else.
