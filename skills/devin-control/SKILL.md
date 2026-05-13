---
name: devin-control
description: "Delegate tasks to Devin agent via oh-my-opendevin with automatic discovery, fallback, and bidirectional notifications."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Devin, Agents, Delegation, MCP]
    related_skills: [native-mcp]
---

# Devin Control

This skill enables Hermes Agent to delegate tasks to a Devin CLI agent running
through the oh-my-opendevin repository. It provides high-level tools that wrap
the oh-my-opendevin Devin MCP server with agent-friendly semantics.

## When to Use

Use `devin_delegate` when:
- The task is expected to take longer than 5 minutes
- You need complex multi-file refactoring that benefits from Devin's UI
- You want to offload work to a separate agent instance while continuing your
  own conversation
- The task requires Devin's reliability pack (auto-retry, context preservation)

Do NOT use `devin_delegate` when:
- The task is a quick file read, single edit, or one-line fix
- The repository is small and local tools are faster
- You need immediate synchronous results (unless you pass `wait: true`)

## Prerequisites

1. **oh-my-opendevin repository** cloned locally. Hermes will auto-discover it
   from common paths (`~/Code/oh-my-opendevin`, etc.) or the
   `OH_MY_OPENDEVIN_PATH` environment variable.
2. **Bun** installed and on PATH (required by oh-my-opendevin's MCP server).
3. **Devin CLI** installed and authenticated.

## Tools

### devin_delegate

Start a Devin session and optionally wait for completion.

```json
{
  "prompt": "Implement a REST API endpoint for user authentication",
  "model": "sonnet",
  "wait": true,
  "auto_fallback": true
}
```

- `model`: One of `opus`, `sonnet`, `kimi-k2.6`, `swe`, `codex`. Defaults to
  the value in `~/.hermes/config.yaml` (`devin.model` or `delegation.devin_model`),
  falling back to `kimi-k2.6`.
- `wait`: If `true`, blocks until the session exits (up to 2 hours). If `false`,
  returns immediately with a `session_id`.
- `auto_fallback`: If `true`, automatically retries with the next model in the
  fallback chain (`opus -> sonnet -> kimi-k2.6 -> swe`) on quota exhaustion.

Returns:
```json
{
  "session_id": "abc123",
  "status": "completed",
  "summary": "...session output...",
  "duration_seconds": 420,
  "model": "sonnet"
}
```

On errors the response includes an `error_tag` field:
`RATE_LIMIT`, `QUOTA_EXCEEDED`, `CONTEXT_LIMIT`, or `UNKNOWN`.

### devin_status_check

Poll an active Devin session for incremental output.

```json
{
  "session_id": "abc123",
  "since_bytes": 0
}
```

Always use `since_bytes` after the first call. The response includes
`output_bytes` — pass this value as `since_bytes` on the next poll.

### devin_list_sessions

List all Devin sessions managed by the MCP server.

```json
{
  "filter_status": "running",
  "include_output": false
}
```

### devin_cancel

Cancel a running Devin session and remove it from the async monitor.

```json
{
  "session_id": "abc123"
}
```

### devin_health

Check the Devin MCP server health (binary availability, disk usage, slot usage,
orphaned session count).

```json
{}
```

### devin_resumable

List completed/errored sessions eligible for resumption.

```json
{
  "limit": 10
}
```

Use the returned `session_id` as the `resume` parameter in `devin_delegate`.

## Subagent Integration

You can also delegate to Devin via the standard `delegate_task` tool by setting
`role: "devin"`:

```json
{
  "goal": "Refactor the authentication module to use JWT tokens",
  "role": "devin",
  "model": "sonnet"
}
```

This treats Devin as a first-class subagent with the same lifecycle management
as local subagents (progress callbacks, heartbeat, timeout handling).

## Bidirectional Notifications

When `devin_delegate` is called with `wait: false` in gateway mode (Telegram,
Discord, Slack, etc.), a background monitor watches the session. On completion,
Hermes automatically sends a message to the originating conversation with the
result summary.

No additional configuration is required for notifications.

## Configuration

The toolset is gated by the availability of the oh-my-opendevin Devin MCP server.
Hermes auto-discovers the repo; if discovery fails, you can set:

```bash
export OH_MY_OPENDEVIN_PATH=/path/to/your/oh-my-opendevin
```

Or manually add the MCP server to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  opendevin_devin:
    command: "bash"
    args: ["/path/to/oh-my-opendevin/bin/devin-mcp-launcher.sh"]
```

Enable the toolset:

```yaml
enabled_toolsets:
  - devin
```

Or via CLI:

```bash
hermes tools enable devin
```

## Fallback Behavior

When a model quota is exceeded, the fallback chain is:

1. `opus` (Deep) → `sonnet` (Balanced) → `kimi-k2.6` (Standard) → `swe` (Fast/Cheap)

Both the MCP server and the high-level tool implement this chain, so fallback
works even if the MCP server is an older version.
