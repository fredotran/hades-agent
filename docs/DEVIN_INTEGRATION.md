# Devin Integration (oh-my-opendevin)

Hermes can delegate tasks to a Devin CLI agent via the [oh-my-opendevin](https://github.com/NousResearch/oh-my-opendevin) repository. This document describes the complete integration architecture, configuration, and verification procedures.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Quick Setup](#quick-setup)
3. [Prerequisites](#prerequisites)
4. [Auto-Discovery](#auto-discovery)
5. [High-Level Tools](#high-level-tools)
6. [Subagent Bridge](#subagent-bridge)
7. [Bidirectional Notifications](#bidirectional-notifications)
8. [Configuration](#configuration)
9. [Production Hardening](#production-hardening)
10. [Verification](#verification)
11. [Troubleshooting](#troubleshooting)

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

## Quick Setup

Configure Hermes as an MCP server for devin-cli with one command:

### One-Line Installer

**Linux / macOS / WSL2:**
```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/setup-devin-mcp.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/setup-devin-mcp.ps1 | iex
```

### What the Installer Does

1. Detects devin-cli and Hermes installations
2. Creates `~/.devin/config.json` (or `%USERPROFILE%\.devin\config.json` on Windows)
3. Adds the Hermes MCP server configuration
4. Verifies the configuration is valid
5. Backs up existing config before modifying

### Advanced Options

**Force overwrite existing configuration:**
```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/setup-devin-mcp.sh | bash -s -- --force
```

**Use custom Hermes path:**
```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/setup-devin-mcp.sh | bash -s -- --hermes-path /usr/local/bin/hermes
```

**Use custom devin config location:**
```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/setup-devin-mcp.sh | bash -s -- --devin-config /path/to/config.json
```

**Verify existing configuration without modifying:**
```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/setup-devin-mcp.sh | bash -s -- --verify-only
```

### Expected Output

```
⚕ Hermes Agent — Devin MCP Setup

→ Checking devin-cli...
✓ devin-cli found: /home/user/.local/bin/devin
✓ Hermes found on PATH: /home/user/.local/bin/hermes
✓ jq found — using for JSON manipulation
→ Verifying Hermes binary...
✓ Hermes binary is functional
→ Creating minimal devin config: /home/user/.devin/config.json
✓ Created minimal devin config
→ Adding Hermes MCP server configuration...
✓ Hermes MCP configuration updated

→ Verifying configuration...
✓ Configuration verified

Hermes MCP Configuration:
{
  "command": "/home/user/.local/bin/hermes",
  "args": ["mcp", "serve"],
  "env": {
    "HERMES_HOME": "/home/user/.hermes"
  }
}

✓ Setup complete!
```

### Next Steps

After running the installer:
1. Restart devin-cli if it's currently running
2. Run `devin mcp list` — you should see "hermes" listed
3. Test with: `devin mcp call hermes mcp_hermes_conversations_list`

See the [dedicated setup guide](../getting-started/devin-mcp-setup.md) for manual setup, troubleshooting, and advanced configuration.

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

## Sample Workflows

### Workflow 1: Quick Task Delegation

**Scenario:** You need to quickly refactor a Python function.

```bash
# In Hermes CLI
> Refactor this function to use type hints and add docstring
> [Hermes automatically uses devin_delegate with role="devin"]
```

**Expected Output:**
```json
{
  "session_id": "abc123",
  "status": "completed",
  "summary": "Function refactored with type hints and comprehensive docstring...",
  "duration_seconds": 45.2,
  "model": "sonnet"
}
```

### Workflow 2: Background Task with Notification

**Scenario:** Start a long-running task in the background and get notified when it completes.

```bash
# In Hermes CLI (gateway mode)
> /background Implement a REST API for user authentication using FastAPI
> [Session starts in background]
```

**Expected Output (immediate):**
```json
{
  "session_id": "xyz789",
  "status": "running",
  "summary": "Devin session xyz789 started (model: sonnet).",
  "model": "sonnet",
  "duration_seconds": 0.5
}
```

**Expected Output (when complete, via gateway notification):**
```
🤖 Devin session xyz789 completed!
Status: completed
Duration: 8m 32s
Summary: REST API implemented with FastAPI, including user registration, login, JWT authentication...
```

### Workflow 3: Parallel Task Execution

**Scenario:** Run multiple independent tasks concurrently.

```bash
# In Hermes CLI
> Implement unit tests for the auth module
> [Starts session A]
> Write API documentation for the auth endpoints
> [Starts session B]
> Create a Dockerfile for the auth service
> [Starts session C]
```

**Check Status:**
```bash
# Use the new /devin command to check all sessions
> /devin
```

**Expected Output:**
```
🤖 Devin Integration Status
==================================================
✅ oh-my-opendevin repo: /home/user/Code/oh-my-opendevin
✅ MCP server config: available
✅ MCP tools: registered
✅ devin CLI: installed
✅ devin CLI: authenticated

📋 Active Devin Sessions:
--------------------------------------------------
Session: abc123 (running, age: 2m 15s) - Unit tests
Session: def456 (running, age: 1m 45s) - API docs
Session: ghi789 (running, age: 1m 30s) - Dockerfile
```

### Workflow 4: Error Recovery with Guidance

**Scenario:** Task fails due to quota exhaustion.

```bash
# In Hermes CLI
> Implement a complex machine learning pipeline
```

**Expected Output (with error guidance):**
```json
{
  "error": "QUOTA_EXCEEDED: Model opus quota exhausted",
  "model": "opus",
  "attempts": 1,
  "error_tag": "QUOTA_EXCEEDED",
  "guidance": "All Devin models in the fallback chain are quota-exceeded.\nTo fix this:\n1. Check your Devin account quota at https://cli.devin.ai\n2. Upgrade your plan if needed\n3. Try again later when quota resets"
}
```

**Recovery Action:**
```bash
# Check quota and retry with a different model
> Retry the task using the kimi-k2.6 model instead
```

### Workflow 5: Session Resume

**Scenario:** Resume a previously interrupted session.

```bash
# List resumable sessions
> Use devin_resumable to find sessions I can resume
```

**Expected Output:**
```json
{
  "resumable_sessions": [
    {
      "session_id": "prev123",
      "status": "error",
      "summary": "Partial implementation of ML pipeline",
      "timestamp": "2026-05-17T10:30:00Z"
    }
  ]
}
```

**Resume Session:**
```bash
> Resume session prev123 and complete the ML pipeline
> [Uses resume parameter in devin_delegate]
```

### Workflow 6: Metrics and Telemetry

**Scenario:** Monitor Devin usage patterns over time.

**Enable Metrics:**
```yaml
# ~/.hermes/config.yaml
devin:
  enable_metrics: true
```

**Check Metrics:**
```python
# In Python or via a custom tool
from tools.devin_delegate import get_devin_metrics
metrics = json.loads(get_devin_metrics())
print(f"Success rate: {metrics['success_rate']}%")
print(f"Average duration: {metrics['average_duration_seconds']}s")
print(f"Model usage: {metrics['model_usage']}")
```

**Expected Output:**
```json
{
  "total_sessions": 42,
  "successful_sessions": 38,
  "failed_sessions": 3,
  "cancelled_sessions": 1,
  "success_rate": 90.48,
  "average_duration_seconds": 125.5,
  "model_usage": {
    "sonnet": 25,
    "kimi-k2.6": 12,
    "opus": 5
  },
  "error_counts": {
    "QUOTA_EXCEEDED": 2,
    "CONTEXT_LIMIT": 1
  },
  "session_history": [...]
}
```

### Workflow 7: Installation and Setup

**Scenario:** Fresh installation with --with-devin flag.

```bash
# Run installer with Devin integration
./scripts/install.sh --with-devin
```

**Expected Output:**
```
Setting up Devin CLI integration...

✅ devin-cli installed
✅ bun installed
✅ oh-my-opendevin cloned to ~/oh-my-opendevin
✅ OH_MY_OPENDEVIN_PATH=~/oh-my-opendevin
✅ 'devin' toolset added to Hermes config
✅ Devin config updated with Hermes MCP server

Performing comprehensive Devin integration health check...
✅ devin CLI found in PATH
✅ oh-my-opendevin repo structure validated
✅ bun runtime found (required for oh-my-opendevin MCP server)
✅ Python verification script passed
ℹ️  Devin CLI not authenticated or MCP connection not configured
   Run 'devin login' to authenticate
   Run 'devin mcp list' to verify MCP connection after authentication

✅ Devin integration setup complete!

Environment variables:
   OH_MY_OPENDEVIN_PATH=~/oh-my-opendevin
   Add this to your ~/.bashrc or ~/.zshrc:
   export OH_MY_OPENDEVIN_PATH=~/oh-my-opendevin

Next steps:
   devin login          Authenticate with Devin
   devin mcp list       Verify Hermes MCP server is connected
   hermes mcp serve     Start Hermes MCP server (for testing)
```

### Workflow 8: Orphaned Session Recovery

**Scenario:** Clean up sessions left over from a previous Hermes crash.

```python
from tools.devin_delegate import recover_orphaned_sessions
result = json.loads(recover_orphaned_sessions())
print(f"Recovered {result['recovered_bindings']} stale bindings")
print(f"Cancelled {result['cancelled_stuck_sessions']} stuck sessions")
```

**Expected Output:**
```json
{
  "recovered_bindings": 3,
  "cancelled_stuck_sessions": 1,
  "errors": []
}
```

---

## Expected Tool Responses

### devin_delegate (successful completion)
```json
{
  "session_id": "sess-abc123",
  "status": "completed",
  "summary": "Task completed successfully. Implemented feature X with tests...",
  "duration_seconds": 123.45,
  "model": "sonnet",
  "error_tag": null
}
```

### devin_delegate (with quota fallback)
```json
{
  "session_id": "sess-def456",
  "status": "completed",
  "summary": "Task completed after model fallback from opus to sonnet...",
  "duration_seconds": 234.56,
  "model": "sonnet",
  "error_tag": null
}
```

### devin_status_check (incremental)
```json
{
  "status": "running",
  "output": "Currently working on step 3 of 5...",
  "output_bytes": 2048,
  "snapshot": {
    "session_id": "sess-xyz789",
    "model": "kimi-k2.6",
    "status": "running"
  }
}
```

### devin_list_sessions
```json
{
  "sessions": [
    {
      "session_id": "sess-1",
      "status": "running",
      "model": "sonnet",
      "prompt": "Implement feature X"
    },
    {
      "session_id": "sess-2",
      "status": "completed",
      "model": "kimi-k2.6",
      "prompt": "Fix bug Y"
    }
  ]
}
```

### devin_health
```json
{
  "healthy": true,
  "snapshot": {
    "bun_available": true,
    "disk_usage": "45%",
    "slot_usage": "2/10",
    "orphaned_sessions": 0
  }
}
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
