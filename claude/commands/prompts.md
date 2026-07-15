---
description: Browse, use, save and edit your personal prompt library
argument-hint: [save <text> | get <id> | edit <id> | rm <id> | <free-form request>]
allowed-tools: Bash(prompts:*), Read, Edit, Write
---

You manage the user's personal **prompt library** through the `prompts` CLI.
Prompts are markdown files under `~/.claude/prompts/` (a private git repo); the
CLI auto-commits every change. Always go through the CLI rather than editing the
raw files, so commits and slug/title handling stay consistent.

Current library:

!`prompts ls`

The user's request (may be empty): **$ARGUMENTS**

Decide what they want and act:

- **Empty / "list" / "ls"** — Show the library above, grouped or summarized if
  long. Briefly remind them they can `get`, `save`, `edit`, or `rm`, and that
  Ctrl+Shift+L opens the popup. Don't dump full bodies unless asked.

- **"get <id>" / "show <id>" / "use <id>"** — Run `prompts get <id>` and present
  the body. If they want it applied to the current task, use it directly.

- **"save …" / "add …" / "remember this prompt …"** — Save a new prompt with
  `prompts add "<concise Title>" --tags <comma,tags> --body "<full prompt>"`.
  Derive a short Title and 1–3 useful tags yourself. If they're saving the *last
  prompt they sent you* or text from this conversation, use that exact text as
  the body. Confirm with the new id.

- **"edit <id> …"** — For a targeted change, read it with `prompts get <id>`,
  then rewrite via the file: `prompts path <id>` gives the path — edit the body
  with the Edit tool, OR re-save. Simplest reliable path: read current body,
  apply the change, and `prompts add`/overwrite. If just opening for the user,
  tell them to run `prompts edit <id>` in a terminal ($EDITOR).
  To overwrite in place programmatically, write the file at `prompts path <id>`
  keeping its frontmatter, then run `prompts git add -A && prompts git commit`.

- **"rm <id>" / "delete <id>"** — Run `prompts rm <id> -f` (confirm first if
  ambiguous).

- **Anything else** — Treat `$ARGUMENTS` as a description; search with
  `prompts search <terms>` and offer the best matches, or offer to save it.

`<id>` accepts a full slug, a unique prefix, or a unique word from the title.
Keep responses tight — this is a quick utility, not an essay.
