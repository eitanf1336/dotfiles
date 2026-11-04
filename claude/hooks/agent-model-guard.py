#!/usr/bin/env python3
"""agent-model-guard: PreToolUse hook on the Agent tool.

Background agents run for hours and re-read their whole context on every step,
so an Opus or Fable agent is the most expensive thing on this machine. On
1 Nov 2026 one chat's Opus agents (plus the Minecraft bots) ate ~95% of the
weekly quota. This hook rewrites every Agent call to Sonnet.

Escape hatch: `touch ~/.claude/allow-big-agents` lets opus/fable agents through
(delete the file to arm the guard again). Haiku and Sonnet always pass as asked.
"""
import json, os, sys

ALLOW = os.path.expanduser("~/.claude/allow-big-agents")
CHEAP = ("sonnet", "haiku")


def main():
    try:
        inp = json.load(sys.stdin)
    except ValueError:
        return 0
    if inp.get("tool_name") not in ("Agent", "Task"):
        return 0
    ti = dict(inp.get("tool_input") or {})
    if ti.get("subagent_type") == "fork":
        return 0          # a fork always runs on the parent's model; nothing to rewrite
    model = str(ti.get("model") or "").lower()
    if any(c in model for c in CHEAP) or os.path.exists(ALLOW):
        return 0
    ti["model"] = "sonnet"
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "permissionDecisionReason": "agent-model-guard: agents run on Sonnet",
        "updatedInput": ti,
        "additionalContext": (
            f"agent-model-guard: this agent was asked for '{model or 'the parent model'}' "
            "and now runs on Sonnet (Eitan's rule since 4 Nov 2026: Opus/Fable agents "
            "burned the weekly quota). Do not try to get around it; if a job truly "
            "needs Opus, do it in this chat or ask Eitan to `touch ~/.claude/allow-big-agents`."),
    }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
