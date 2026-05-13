# Devin Integration (oh-my-opendevin)

Hermes can delegate tasks to a Devin CLI agent via the [oh-my-opendevin](https://github.com/NousResearch/oh-my-opendevin) repository. This document describes the complete integration architecture, configuration, and verification procedures.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Auto-Discovery](#auto-discovery)
4. [High-Level Tools](#high-level-tools)
5. [Subagent Bridge](#subagent-bridge)
6. [Bidirectional Notifications](#bidirectional-notifications)
7. [Configuration](#configuration)
8. [Production Hardening](#production-hardening)
9. [Verification](#verification)
10. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

The integration is layered:

```
┌─────────────────────────────────────────────────────────────┐
│  Hermes Agent                                               │
│  ├── tools/devin_discovery.py   (auto-discovery)           │
│  ├── tools/devin_delegate.py    (high-level tools)        │
│  ├── tools/delegate_tool.py      (subagent bridge)        │
│  └── tools/mcp_tool.py           (MCP server wiring)        │
└──────────────────┬──────────────────────────────────────────┘
                   │ stdio JSON-RPC
┌──────────────────▼──────────────────────────────────────────┐
│  oh-my-opendevin Devin MCP Server                           │
│  └── src/mcp-servers/devin/index.ts                        │
└──────────────────┬──────────────────────────────────────────┘
                   │ spawns background process
┌──────────────────▼──────────────────────────────────────────┐
│  Devin CLI (devin -p <prompt>)                              │
└─────────────────────────────────────────────────────────────┘
```

**Phase 1 — MCP wiring:** On startup, `discover_mcp_tools()` auto-finds the oh-my-opendevin checkout and registers its stdio MCP server as `opendevin_devin`.

**Phase 2 — High-level tools:** `devin_delegate`, `devin_status_check`, `devin_list_sessions`, `devin_cancel`, `devin_health`, `devin_resumable` wrap the raw MCP tools with agent-friendly semantics.

**Phase 3 — Subagent bridge:** `role="devin"` in `delegate_task` routes to a `DevinSubagent` proxy instead of spawning a local `AIAgent`.

**Phase 4 — Bidirectional notifications:** When `wait=False`, the session is bound to the current conversation context. A background daemon thread polls active sessions every 30s and pushes completion messages back through the gateway.

---

## Prerequisites

1. **oh-my-opendevin repository** cloned locally. Hermes will auto-discover it from 18 common paths (see [Auto-Discovery](#auto-discovery)).
2. **Bun** installed and on PATH (required by oh-my-opendevin's MCP server).
   ```bash
   curl -fsSL https://bun.sh/install | bash
   ```
3. **Devin CLI** installed and authenticated.
   ```bash
   npm install -g devin
   devin login
   ```

---

## Auto-Discovery

`tools/devin_discovery.py` searches for the oh-my-opendevin repository in this order:

1. **`OH_MY_OPENDEVIN_PATH`** environment variable
2. **Known paths** (18 locations checked):
   - `~/Code/oh-my-opendevin`
   - `~/oh-my-opendevin`
   - `~/repos/oh-my-opendevin`
   - `~/src/oh-my-opendevin`
   - `~/projects/oh-my-opendevin`
   - `~/workspace/oh-my-opendevin`
   - `~/dev/oh-my-opendevin`
   - `~/Development/oh-my-opendevin`
   - `~/devin/oh-my-opendevin`
   - `~/work/oh-my-opendevin`
   - `~/Documents/oh-my-opendevin`
   - `~/Dropbox/oh-my-opendevin`
   - `~/github/oh-my-opendevin`
   - `~/git/oh-my-opendevin`
   - `~/gitlab/oh-my-opendevin`
   - `~/bitbucket/oh-my-opendevin`
   - `~/tools/oh-my-opendevin`
   - `~/opt/oh-my-opendevin`
3. **Walk up from cwd** — checks `[cwd, cwd/.., cwd/../.., ...]` for `oh-my-opendevin/`

Validation requires both `src/mcp-servers/devin/index.ts` and `bin/devin-mcp-launcher.sh`.

Results are cached per-process for performance.

---

## High-Level Tools

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

**Parameters:**
| Name | Type | Default | Description |
|------|------|---------|-------------|
| `prompt` | string | required | Task prompt for Devin |
| `model` | string | config-driven | `opus`, `sonnet`, `kimi-k2.6`, `swe`, or fully-qualified IDs like `swe-1-6` |
| `cwd` | string | — | Working directory for the session |
| `permission_mode` | string | — | `"auto"` or `"dangerous"` |
| `resume` | string | — | Resume a previous session by ID |
| `max_duration_ms` | int | 2h | Max duration before auto-cancel |
| `wait` | bool | `true` | Block until completion if `true` |
| `auto_fallback` | bool | `true` | Retry next model on quota errors |

**Returns:**
```json
{
  "session_id": "abc123",
  "status": "completed",
  "summary": "...session output...",
  "duration_seconds": 420,
  "model": "sonnet",
  "error_tag": null
}
```

On errors, `error_tag` contains one of: `RATE_LIMIT`, `QUOTA_EXCEEDED`, `CONTEXT_LIMIT`, `UNKNOWN`.

When `wait=false`, the session is bound for async completion notification.

### devin_status_check

Poll an active session for incremental output.

```json
{"session_id": "abc123", "since_bytes": 0}
```

Always use `since_bytes` after the first call. The response includes `output_bytes` — pass this as `since_bytes` on the next poll.

### devin_list_sessions

List all sessions managed by the MCP server.

```json
{"filter_status": "running", "include_output": false}
```

### devin_cancel

Cancel a running session and remove it from the async monitor.

```json
{"session_id": "abc123"}
```

### devin_health

Check MCP server health: binary availability, disk usage, slot usage, orphaned sessions.

```json
{}
```

### devin_resumable

List completed/errored sessions eligible for resumption.

```json
{"limit": 10}
```

Use the returned `session_id` as the `resume` parameter in `devin_delegate`.

---

## Subagent Bridge

You can delegate to Devin via the standard `delegate_task` tool by setting `role: "devin"`:

```json
{
  "goal": "Refactor the authentication module to use JWT tokens",
  "role": "devin",
  "model": "sonnet"
}
```

This treats Devin as a first-class subagent with the same lifecycle management as local subagents:
- Progress callbacks
- Heartbeat (synthetic counter prevents stale detection)
- Timeout handling
- Incremental output streaming via `_print_fn`

---

## Bidirectional Notifications

When `devin_delegate` is called with `wait: false` in gateway mode (Telegram, Discord, Slack, etc.), a background monitor watches the session:

1. Session is bound to `(platform, chat_id, thread_id)` in `_session_bindings`
2. Daemon thread `devin-monitor` polls every 30s
3. On completion/error/cancellation:
   - Looks up the gateway adapter for the platform
   - Sends a message via `asyncio.run_coroutine_threadsafe(adapter.send(...), loop)`
   - Unbinds the session

**Fallback chain for notifications:**
1. Gateway adapter → platform message
2. Registered callback (`register_notification_fallback()`)
3. Log-only

**Auto-cleanup:** Bindings older than 24h are silently purged to prevent unbounded memory growth.

---

## Configuration

Enable the toolset:

```yaml
# ~/.hermes/config.yaml
enabled_toolsets:
  - devin
```

Or via CLI:
```bash
hermes tools enable devin
```

### Default Model

Set your preferred default Devin model:

```yaml
# Option A: under delegation section
devin:
  model: "sonnet"

# Option B: under delegation section
delegation:
  devin_model: "sonnet"
```

Valid values: `opus`, `sonnet`, `kimi-k2.6`, `swe`. The config is read with a 5-second cache.

### Manual MCP Server

If auto-discovery fails, add the MCP server manually:

```yaml
mcp_servers:
  opendevin_devin:
    command: "bash"
    args: ["/path/to/oh-my-opendevin/bin/devin-mcp-launcher.sh"]
```

---

## Production Hardening

| Feature | Implementation | Benefit |
|---------|----------------|---------|
| **Exponential-backoff polling** | Base 2s, doubles each iteration, caps at 60s | Reduces MCP server load for long-running tasks |
| **Model validation** | Accepts known tiers + prefix match (e.g. `swe-1-6`) | Prevents invalid model strings from reaching the server |
| **Config-driven defaults** | Reads `devin.model` or `delegation.devin_model` from `config.yaml` | User preference without code changes |
| **Process-exit cleanup** | `atexit` handler cancels all tracked sessions | No orphaned Devin processes when Hermes exits |
| **Binding TTL** | 24h auto-purge of stale `_session_bindings` | Prevents memory leaks across MCP server restarts |
| **Thread-safe bindings** | `threading.Lock` around all `_session_bindings` access | Safe concurrent bind/get/unbind |
| **Structured error tags** | `RATE_LIMIT`, `QUOTA_EXCEEDED`, `CONTEXT_LIMIT`, `UNKNOWN` | Programmatic error handling |
| **Incremental streaming** | Optional `stream_callback` during wait loop | Live UI output for long sessions |
| **Gateway fallback** | `_get_gateway_adapter()` + `register_notification_fallback()` | Notifications survive gateway restarts |
| **JSON parse recovery** | Regex-extracts `session_id` from malformed JSON | Graceful degradation on MCP format drift |

---

## Verification

Run the comprehensive verification script:

```bash
# Safe mode (no API quota used)
python3 tests/tools/verify_devin_integration.py

# Quiet mode (only failures)
python3 tests/tools/verify_devin_integration.py --quiet

# Live mode (starts a real Devin session — consumes API quota!)
python3 tests/tools/verify_devin_integration.py --live
```

The script checks:
1. Auto-discovery (env var, known paths, bun check, config production)
2. MCP server handshake (JSON-RPC initialize + tools/list)
3. Tool registry (all 6 tools registered, toolsets.py wiring)
4. Model validation & config defaults
5. Session lifecycle (wait loop, fire-and-forget, quota fallback, timeout, streaming)
6. Thread safety & cleanup (bindings lock, session tracking, TTL purge, backoff)
7. Subagent bridge (normal result, malformed JSON, interrupt, heartbeat)
8. Role normalisation
9. Live session (optional)

---

## Troubleshooting

### "Devin MCP tool not found"

The MCP server is not connected. Check:
```bash
# Is the repo discoverable?
python3 -c "from tools.devin_discovery import discover_opendevin_repo; print(discover_opendevin_repo())"

# Is bun available?
which bun

# Is the MCP server built?
ls ~/Code/oh-my-opendevin/dist/mcp-servers/devin/index.js
```

### "oh-my-opendevin repo not found"

Set the environment variable:
```bash
export OH_MY_OPENDEVIN_PATH=/path/to/oh-my-opendevin
```

Or clone to a known path:
```bash
git clone https://github.com/NousResearch/oh-my-opendevin ~/Code/oh-my-opendevin
cd ~/Code/oh-my-opendevin && bun install && bun run build
```

### "bun not on PATH"

```bash
curl -fsSL https://bun.sh/install | bash
# Add ~/.bun/bin to PATH in your shell profile
```

### "Gateway notification not sent"

The gateway runner must be active. In CLI mode (no gateway), notifications fall back to logging. You can register a custom fallback:

```python
from tools.devin_delegate import register_notification_fallback

def my_notifier(session_id, meta, result):
    print(f"Session {session_id} finished: {result['status']}")

register_notification_fallback(my_notifier)
```

### Model fallback not working

Ensure the model name is valid:
```python
from tools.devin_delegate import _validate_devin_model
print(_validate_devin_model("your-model"))  # None = invalid
```

---

## File Reference

| File | Purpose |
|------|---------|
| `tools/devin_discovery.py` | Auto-discovery of oh-my-opendevin repo |
| `tools/devin_delegate.py` | High-level tools, monitor thread, lifecycle |
| `tools/delegate_tool.py` | `DevinSubagent` class for subagent bridge |
| `tools/mcp_tool.py` | MCP server auto-injection |
| `toolsets.py` | Toolset registration |
| `skills/devin-control/SKILL.md` | Skill documentation |
| `tests/tools/verify_devin_integration.py` | Comprehensive verification script |
| `tests/tools/test_devin_integration.py` | Pytest unit test suite |

---

*Generated with [Devin](https://cli.devin.ai/docs)*
