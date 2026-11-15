"""One place that builds the Anthropic client, so every call sends the same headers."""
import os

import anthropic

# New style keys (personal keys, 'sk-ant-usr-...') are used with the current API version.
API_VERSION = os.getenv("ANTHROPIC_API_VERSION", "2026-10-21")


def make_client(key):
    headers = {"anthropic-version": API_VERSION}
    ws = (os.getenv("ANTHROPIC_WORKSPACE_ID") or "").strip().strip("\"'")
    if ws:  # needed when the key is not tied to one workspace
        headers["anthropic-workspace-id"] = ws
    return anthropic.Anthropic(api_key=key, default_headers=headers)
