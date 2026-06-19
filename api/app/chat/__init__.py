"""Chat-side helpers that sit above the gateway client.

PR5b-ii: the governed chat tool-loop (``tool_loop``) — assembles the per-turn
tool allowlist, runs the read-only execute-and-loop over the gateway, and
surfaces a confirmation signal for human-gated tools.
"""
