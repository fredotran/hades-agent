"""High-level Devin delegation tools.

Wraps the raw MCP tools exposed by the oh-my-opendevin Devin MCP server into
agent-friendly operations with:
  - Automatic session lifecycle management (start -> wait -> result)
  - Model fallback on quota exhaustion
  - Incremental output polling
  - Clean result parsing
  - Exponential-backoff polling
  - Config-driven defaults
  - Process-exit cleanup

These tools assume the oh-my-opendevin Devin MCP server is already connected
(via auto-discovery in tools/mcp_tool.py or manual config).
"""

import atexit
import json
import logging
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set

from tools.registry import registry

logger = logging.getLogger(__name__)

# Devin model fallback chain (same as oh-my-opendevin tiers.ts)
_DEVIN_FALLBACK_CHAIN = ["opus", "sonnet", "kimi-k2.6", "swe"]
_KNOWN_DEVIN_MODELS: Set[str] = set(_DEVIN_FALLBACK_CHAIN)

# Max total wait time for devin_delegate (2 hours default)
_DEFAULT_MAX_WAIT_SECONDS = 7200
# Base poll interval; actual interval grows exponentially up to _MAX_POLL_INTERVAL
_BASE_POLL_INTERVAL_SECONDS = 2
_MAX_POLL_INTERVAL_SECONDS = 60
# Bindings older than this are auto-purged by the monitor
_BINDING_TTL_SECONDS = 86400  # 24 hours


def _find_devin_mcp_tool(base_name: str) -> Optional[str]:
    """Find the registered MCP tool name for a Devin tool (e.g. 'devin_start').

    Searches the registry for any MCP-registered tool whose name ends with
    the base name (e.g. ``mcp_opendevin_devin_devin_start``).
    """
    for entry_name in registry.get_all_tool_names():
        if entry_name.endswith(f"_{base_name}"):
            entry = registry.get_entry(entry_name)
            if entry and entry.toolset.startswith("mcp-"):
                return entry_name
    return None


def _devin_mcp_available() -> bool:
    """Return True when at least the core Devin MCP tools are registered."""
    return _find_devin_mcp_tool("devin_start") is not None


def _call_devin_mcp(tool_base_name: str, args: dict) -> dict:
    """Call a Devin MCP tool and return the result as a parsed dict.

    The raw MCP response is a JSON string with either:
      {"result": "<text from MCP server>"}
      {"error": "<error message>"}
    """
    tool_name = _find_devin_mcp_tool(tool_base_name)
    if not tool_name:
        return {"error": f"Devin MCP tool '{tool_base_name}' not found. "
                          f"Is the oh-my-opendevin MCP server connected?"}

    raw = registry.dispatch(tool_name, args)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # Some tools return plain text wrapped in a result string
        parsed = {"result": raw}
    return parsed


def _extract_text_from_mcp_result(result: dict) -> str:
    """Extract the text payload from an MCP result dict."""
    if "error" in result:
        return result["error"]
    if "result" in result:
        return str(result["result"])
    return str(result)


def _parse_snapshot(text: str) -> Dict[str, str]:
    """Parse the key:value lines from a Devin snapshot text block."""
    out: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Handle "status: running (exit 0)" -> key=status, value=running (exit 0)
        if ":" in line:
            key, _, val = line.partition(":")
            out[key.strip()] = val.strip()
    return out


def _parse_output_from_snapshot(text: str) -> str:
    """Extract the output section after '--- output (tail) ---' or '--- new output ---'."""
    for marker in ("--- new output ---", "--- output (tail) ---"):
        idx = text.find(marker)
        if idx != -1:
            return text[idx + len(marker):].lstrip("\n")
    return text


def _get_next_fallback_model(current: str) -> Optional[str]:
    """Return the next model in the Devin fallback chain."""
    try:
        idx = _DEVIN_FALLBACK_CHAIN.index(current)
    except ValueError:
        # If current is not in chain, start from the beginning
        return _DEVIN_FALLBACK_CHAIN[0] if _DEVIN_FALLBACK_CHAIN else None
    if idx + 1 < len(_DEVIN_FALLBACK_CHAIN):
        return _DEVIN_FALLBACK_CHAIN[idx + 1]
    return None


def _validate_devin_model(model: Optional[str]) -> Optional[str]:
    """Validate and normalise a Devin model name.

    Returns the validated model, or None if the input was empty.
    Warns and returns None for unknown models so the caller can fall
    back to the config-driven default.
    """
    if not model:
        return None
    m = model.strip().lower()
    if m in _KNOWN_DEVIN_MODELS:
        return m
    # Accept fully-qualified IDs like "swe-1-6" by prefix match
    for known in _KNOWN_DEVIN_MODELS:
        if m.startswith(known):
            return known
    logger.warning(
        "Unknown Devin model %r; expected one of %s. "
        "Falling back to default.",
        model, list(_KNOWN_DEVIN_MODELS),
    )
    return None


def _get_config() -> Dict[str, Any]:
    """Load Hermes config.yaml (cached per-process)."""
    try:
        from hermes_cli.config import get_config_path
        cfg_path = get_config_path()
        if cfg_path.exists():
            import yaml
            with open(cfg_path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    except Exception as exc:
        logger.debug("Could not load Hermes config: %s", exc)
    return {}


# Process-level cache for config reads
_config_cache: Optional[Dict[str, Any]] = None
_config_cache_time: float = 0.0
_CONFIG_CACHE_TTL: float = 5.0  # seconds


def _get_cached_config() -> Dict[str, Any]:
    """Return config, refreshing the cache if older than TTL."""
    global _config_cache, _config_cache_time
    now = time.monotonic()
    if _config_cache is None or (now - _config_cache_time) > _CONFIG_CACHE_TTL:
        _config_cache = _get_config()
        _config_cache_time = now
    return _config_cache


def _get_default_model() -> str:
    """Return the default Devin model from config, or 'kimi-k2.6'."""
    cfg = _get_cached_config()
    # Support both delegation.devin_model and top-level devin.model
    for path in ("delegation.devin_model", "devin.model"):
        keys = path.split(".")
        node = cfg
        for k in keys:
            if isinstance(node, dict):
                node = node.get(k)
            else:
                node = None
                break
        if isinstance(node, str) and node:
            validated = _validate_devin_model(node)
            if validated:
                return validated
    return "kimi-k2.6"


def _compute_poll_interval(iteration: int) -> float:
    """Return the poll sleep duration for the *iteration*th poll loop.

    Exponential backoff capped at _MAX_POLL_INTERVAL_SECONDS.
    """
    return min(_BASE_POLL_INTERVAL_SECONDS * (2 ** iteration), _MAX_POLL_INTERVAL_SECONDS)


# ---------------------------------------------------------------------------
# Process-exit cleanup: track Devin sessions started by this process
# ---------------------------------------------------------------------------
_active_devin_sessions: Set[str] = set()
_sessions_lock = threading.Lock()


def _track_session(session_id: str) -> None:
    """Register a session ID for atexit cancellation."""
    if not session_id:
        return
    with _sessions_lock:
        _active_devin_sessions.add(session_id)


def _untrack_session(session_id: str) -> None:
    """Remove a session ID from the atexit watchlist."""
    with _sessions_lock:
        _active_devin_sessions.discard(session_id)


def _cancel_tracked_sessions() -> None:
    """Cancel all Devin sessions started by this process on exit.

    Registered with atexit so SIGTERM / normal exit cleans up gracefully.
    """
    with _sessions_lock:
        sessions = list(_active_devin_sessions)
        _active_devin_sessions.clear()
    for sid in sessions:
        try:
            logger.info("Cancelling Devin session %s at process exit", sid)
            _call_devin_mcp("devin_cancel", {"session_id": sid})
        except Exception as exc:
            logger.debug("Failed to cancel Devin session %s at exit: %s", sid, exc)


atexit.register(_cancel_tracked_sessions)


def _start_devin_session(
    prompt: str,
    model: Optional[str] = None,
    cwd: Optional[str] = None,
    permission_mode: Optional[str] = None,
    resume: Optional[str] = None,
    max_duration_ms: Optional[int] = None,
    auto_fallback: bool = True,
) -> dict:
    """Start a Devin session, with optional manual fallback on quota errors."""
    # Validate / normalise model, then fall back to config default
    validated = _validate_devin_model(model)
    resolved_model = validated or _get_default_model()

    args: dict = {"prompt": prompt, "model": resolved_model}
    if cwd:
        args["cwd"] = cwd
    if permission_mode:
        args["permission_mode"] = permission_mode
    if resume:
        args["resume"] = resume
    if max_duration_ms is not None:
        args["max_duration_ms"] = max_duration_ms
    args["auto_fallback"] = auto_fallback

    result = _call_devin_mcp("devin_start", args)
    text = _extract_text_from_mcp_result(result)

    # Check for quota errors even when auto_fallback was passed
    # (older MCP servers might not support it)
    if "QUOTA_EXCEEDED" in text and not auto_fallback:
        return {"error": text, "quota_exceeded": True, "model": resolved_model}

    if "error" in result or "FAILED" in text:
        # Check if it's a quota error that we should retry manually
        if "QUOTA_EXCEEDED" in text or "quota exceeded" in text.lower():
            return {"error": text, "quota_exceeded": True, "model": resolved_model}
        return {"error": text}

    # Parse session_id from the response text
    snap = _parse_snapshot(text)
    session_id = snap.get("session_id", "")

    # Track for atexit cleanup
    _track_session(session_id)

    return {
        "session_id": session_id,
        "snapshot": snap,
        "raw": text,
        "model": resolved_model,
    }


def _wait_devin_session(
    session_id: str,
    timeout_ms: int = 30000,
    tail_bytes: int = 8192,
) -> dict:
    """Call devin_wait and parse the result."""
    result = _call_devin_mcp("devin_wait", {
        "session_id": session_id,
        "timeout_ms": timeout_ms,
        "tail_bytes": tail_bytes,
    })
    text = _extract_text_from_mcp_result(result)

    if "error" in result:
        return {"error": text}

    snap = _parse_snapshot(text)
    status = snap.get("status", "").lower()

    # "Session {id} exited." means it finished
    exited = "exited" in text.lower() or status in ("completed", "error", "cancelled")

    return {
        "exited": exited,
        "status": status,
        "snapshot": snap,
        "output": _parse_output_from_snapshot(text),
        "raw": text,
    }


def _poll_devin_status(
    session_id: str,
    since_bytes: int = 0,
) -> dict:
    """Call devin_status with since_bytes and parse the result."""
    result = _call_devin_mcp("devin_status", {
        "session_id": session_id,
        "since_bytes": since_bytes,
    })
    text = _extract_text_from_mcp_result(result)

    if "error" in result:
        return {"error": text}

    snap = _parse_snapshot(text)
    status = snap.get("status", "").lower()

    # Extract output_bytes for next poll
    output_bytes_str = snap.get("output_bytes", "0")
    try:
        output_bytes = int(output_bytes_str)
    except (ValueError, TypeError):
        output_bytes = since_bytes

    return {
        "status": status,
        "snapshot": snap,
        "output": _parse_output_from_snapshot(text),
        "output_bytes": output_bytes,
        "raw": text,
    }


def _extract_error_tag(text: str) -> Optional[str]:
    """Extract structured error tags from MCP server responses.

    Known tags: RATE_LIMIT, QUOTA_EXCEEDED, CONTEXT_LIMIT, UNKNOWN.
    """
    for tag in ("RATE_LIMIT", "QUOTA_EXCEEDED", "CONTEXT_LIMIT", "UNKNOWN"):
        if tag in text:
            return tag
    return None


def devin_delegate(
    prompt: str,
    model: Optional[str] = None,
    cwd: Optional[str] = None,
    permission_mode: Optional[str] = None,
    resume: Optional[str] = None,
    max_duration_ms: Optional[int] = None,
    wait: bool = True,
    auto_fallback: bool = True,
    task_id: Optional[str] = None,
    platform: Optional[str] = None,
    chat_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    stream_callback: Optional[Callable[[str], None]] = None,
) -> str:
    """Start a Devin session and optionally block until it completes.

    Parameters:
      prompt (str): The task prompt for Devin.
      model (str, optional): Devin model keyword (e.g. "opus", "sonnet", "kimi-k2.6", "swe").
      cwd (str, optional): Working directory for the session.
      permission_mode (str, optional): "auto" or "dangerous".
      resume (str, optional): Resume a previous session by ID.
      max_duration_ms (int, optional): Max duration before auto-cancel (default 2h).
      wait (bool): If True, block until the session exits or max wait time.
      auto_fallback (bool): If True, retry with next model on quota errors.
      platform (str, optional): Gateway platform (for bidirectional notifications).
      chat_id (str, optional): Gateway chat ID (for bidirectional notifications).
      thread_id (str, optional): Gateway thread ID (for bidirectional notifications).
      stream_callback (callable, optional): Called with each incremental output
        chunk during the wait loop. Useful for streaming to the parent agent UI.

    Returns JSON with:
      - session_id
      - status (completed / error / cancelled / running / etc.)
      - summary (the session output)
      - duration_seconds
      - model (resolved model)
      - error_tag (RATE_LIMIT, QUOTA_EXCEEDED, CONTEXT_LIMIT, UNKNOWN)
    """
    start_time = time.monotonic()

    # Try starting with the requested model, fallback on quota error
    current_model = model
    attempts = 0
    max_attempts = len(_DEVIN_FALLBACK_CHAIN) + 1

    while attempts < max_attempts:
        attempts += 1
        start_result = _start_devin_session(
            prompt=prompt,
            model=current_model,
            cwd=cwd,
            permission_mode=permission_mode,
            resume=resume,
            max_duration_ms=max_duration_ms,
            auto_fallback=auto_fallback,
        )

        if "error" not in start_result:
            break  # Success

        # If quota exceeded and we can fallback, retry
        if start_result.get("quota_exceeded") and auto_fallback:
            next_model = _get_next_fallback_model(current_model or "")
            if next_model:
                logger.warning(
                    "Devin model %s quota exceeded, falling back to %s (attempt %d/%d)",
                    current_model, next_model, attempts, max_attempts,
                )
                current_model = next_model
                continue

        # Non-quota error or out of fallback options
        return json.dumps({
            "error": start_result["error"],
            "model": current_model,
            "attempts": attempts,
            "error_tag": _extract_error_tag(start_result["error"]),
        }, ensure_ascii=False)

    session_id = start_result.get("session_id", "")
    if not session_id:
        return json.dumps({
            "error": "Devin session started but no session_id was returned.",
            "raw": start_result.get("raw", ""),
        }, ensure_ascii=False)

    resolved_model = start_result.get("model", current_model or _get_default_model())

    if not wait:
        # Fire-and-forget: bind for async completion notification
        _bind_session_to_conversation(
            session_id, task_id=task_id, platform=platform, chat_id=chat_id, thread_id=thread_id
        )
        return json.dumps({
            "session_id": session_id,
            "status": "running",
            "summary": f"Devin session {session_id} started (model: {resolved_model}).",
            "model": resolved_model,
            "duration_seconds": round(time.monotonic() - start_time, 2),
        }, ensure_ascii=False)

    # Wait loop with exponential-backoff polling + optional streaming
    total_wait_limit = _DEFAULT_MAX_WAIT_SECONDS
    deadline = start_time + total_wait_limit
    last_output_bytes = 0
    poll_iteration = 0

    try:
        while time.monotonic() < deadline:
            wait_result = _wait_devin_session(session_id, timeout_ms=30000)

            if "error" in wait_result:
                return json.dumps({
                    "session_id": session_id,
                    "status": "error",
                    "summary": wait_result["error"],
                    "model": resolved_model,
                    "duration_seconds": round(time.monotonic() - start_time, 2),
                    "error_tag": _extract_error_tag(wait_result["error"]),
                }, ensure_ascii=False)

            if wait_result.get("exited"):
                status = wait_result.get("status", "unknown")
                output = wait_result.get("output", "")
                return json.dumps({
                    "session_id": session_id,
                    "status": status,
                    "summary": output,
                    "model": resolved_model,
                    "duration_seconds": round(time.monotonic() - start_time, 2),
                }, ensure_ascii=False)

            # Still running — poll incrementally for progress
            poll_result = _poll_devin_status(session_id, since_bytes=last_output_bytes)
            if "error" not in poll_result:
                new_bytes = poll_result.get("output_bytes", last_output_bytes)
                if stream_callback and new_bytes > last_output_bytes:
                    chunk = poll_result.get("output", "")
                    if chunk:
                        try:
                            stream_callback(chunk)
                        except Exception:
                            pass
                last_output_bytes = new_bytes

            # Exponential-backoff sleep capped at _MAX_POLL_INTERVAL_SECONDS
            poll_iteration += 1
            sleep_seconds = _compute_poll_interval(poll_iteration)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(sleep_seconds, remaining))

        # Max wait exceeded
        return json.dumps({
            "session_id": session_id,
            "status": "timeout",
            "summary": f"Devin session {session_id} did not complete within {total_wait_limit}s.",
            "model": resolved_model,
            "duration_seconds": round(time.monotonic() - start_time, 2),
        }, ensure_ascii=False)
    finally:
        # Stop tracking for atexit cleanup once we leave the wait loop
        _untrack_session(session_id)


def devin_status_check(
    session_id: str,
    since_bytes: int = 0,
    task_id: Optional[str] = None,
) -> str:
    """Check the status of a running Devin session.

    Parameters:
      session_id (str): The session ID returned by devin_delegate.
      since_bytes (int): Return only new output after this byte offset.
                         Use 0 for full snapshot. Use output_bytes from the
                         previous call for incremental reads.

    Returns JSON with status, output, and output_bytes for the next poll.
    """
    result = _poll_devin_status(session_id, since_bytes=since_bytes)
    return json.dumps(result, ensure_ascii=False)


def devin_cancel(session_id: str, task_id: Optional[str] = None) -> str:
    """Cancel a running Devin session.

    Parameters:
      session_id (str): The session ID to cancel.

    Returns JSON with cancellation status.
    """
    result = _call_devin_mcp("devin_cancel", {"session_id": session_id})
    text = _extract_text_from_mcp_result(result)

    if "error" in result:
        return json.dumps({"error": text}, ensure_ascii=False)

    _untrack_session(session_id)
    unbind_session(session_id)

    return json.dumps({
        "session_id": session_id,
        "cancelled": True,
        "raw": text,
    }, ensure_ascii=False)


def devin_health() -> str:
    """Check the health of the Devin MCP server.

    Returns JSON with binary availability, disk usage, slot usage,
    and orphaned session count.
    """
    result = _call_devin_mcp("devin_health", {})
    text = _extract_text_from_mcp_result(result)

    if "error" in result:
        return json.dumps({"error": text}, ensure_ascii=False)

    # Parse key:value health snapshot
    snap = _parse_snapshot(text)
    return json.dumps({
        "healthy": "error" not in text.lower(),
        "snapshot": snap,
        "raw": text,
    }, ensure_ascii=False)


def devin_resumable(limit: Optional[int] = None, task_id: Optional[str] = None) -> str:
    """List Devin sessions eligible for resumption.

    Parameters:
      limit (int, optional): Maximum number of sessions to return.

    Returns JSON with a list of resumable sessions.
    """
    args: dict = {}
    if limit is not None:
        args["limit"] = limit
    result = _call_devin_mcp("devin_resumable", args)
    text = _extract_text_from_mcp_result(result)

    if "error" in result:
        return json.dumps({"error": text}, ensure_ascii=False)

    sessions: List[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line == "(no sessions)":
            continue
        if line.startswith("- "):
            sessions.append({"line": line})

    return json.dumps({
        "sessions": sessions,
        "count": len(sessions),
        "raw": text,
    }, ensure_ascii=False)


def devin_list_managed_sessions(
    filter_status: Optional[str] = None,
    include_output: bool = False,
    task_id: Optional[str] = None,
) -> str:
    """List Devin sessions managed by the MCP server.

    Parameters:
      filter_status (str, optional): Filter by status (running, completed, error, etc.)
      include_output (bool): Include a tail of each session's output.

    Returns JSON with a list of sessions.
    """
    result = _call_devin_mcp("devin_list", {"include_output": include_output})
    text = _extract_text_from_mcp_result(result)

    if "error" in result:
        return json.dumps({"error": text}, ensure_ascii=False)

    # Parse the text list into structured entries
    sessions: List[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line == "(no sessions)":
            continue
        # Format: "- {id}  [{status}]  model={model}  duration={dur}ms  prompt={prompt}"
        if line.startswith("- "):
            sessions.append({"line": line})
        elif line.startswith("  tail: "):
            if sessions:
                sessions[-1]["tail"] = line[7:]

    if filter_status:
        sessions = [s for s in sessions if filter_status.lower() in s.get("line", "").lower()]

    return json.dumps({
        "sessions": sessions,
        "count": len(sessions),
        "raw": text,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Conversation binding for bidirectional notifications
# ---------------------------------------------------------------------------

# Module-level registry: session_id -> conversation metadata dict.
# Populated by devin_delegate and consumed by the gateway monitor.
_session_bindings: Dict[str, dict] = {}
_bindings_lock = threading.Lock()


def _bind_session_to_conversation(
    session_id: str,
    task_id: Optional[str] = None,
    platform: Optional[str] = None,
    chat_id: Optional[str] = None,
    thread_id: Optional[str] = None,
) -> None:
    """Store a mapping from Devin session to Hermes conversation context.

    The gateway monitor uses this to route completion notifications back
    to the originating conversation.
    """
    if not session_id:
        return
    with _bindings_lock:
        _session_bindings[session_id] = {
            "task_id": task_id,
            "platform": platform,
            "chat_id": chat_id,
            "thread_id": thread_id,
            "bound_at": time.time(),
        }
    _ensure_monitor()


def get_session_bindings() -> Dict[str, dict]:
    """Return a snapshot of active session->conversation bindings."""
    with _bindings_lock:
        return dict(_session_bindings)


def unbind_session(session_id: str) -> None:
    """Remove a session binding (called after notification is sent)."""
    with _bindings_lock:
        _session_bindings.pop(session_id, None)


# ---------------------------------------------------------------------------
# Background monitor for async Devin session completion notifications
# ---------------------------------------------------------------------------

_monitor_thread: Optional[threading.Thread] = None
_monitor_lock = threading.Lock()
_MONITOR_INTERVAL_SECONDS = 30


def _ensure_monitor() -> None:
    """Start the background Devin session monitor if not already running."""
    global _monitor_thread
    with _monitor_lock:
        if _monitor_thread is not None and _monitor_thread.is_alive():
            return
        _monitor_thread = threading.Thread(
            target=_devin_monitor_loop, daemon=True, name="devin-monitor"
        )
        _monitor_thread.start()
        logger.info("Started Devin session monitor thread")


def _devin_monitor_loop() -> None:
    """Daemon thread that polls active Devin sessions and notifies on completion."""
    while True:
        time.sleep(_MONITOR_INTERVAL_SECONDS)
        try:
            _check_pending_sessions()
        except Exception as exc:
            logger.debug("Devin monitor cycle error: %s", exc)


def _check_pending_sessions() -> None:
    """Poll all bound Devin sessions; notify and unbind those that have completed.

    Also purges bindings older than _BINDING_TTL_SECONDS to prevent
    unbounded memory growth when the MCP server restarts or sessions
    are lost.
    """
    bindings = get_session_bindings()
    if not bindings:
        return

    now = time.time()
    for session_id, meta in list(bindings.items()):
        # TTL purge: silently drop ancient bindings
        bound_at = meta.get("bound_at", 0)
        if now - bound_at > _BINDING_TTL_SECONDS:
            logger.debug(
                "Purging stale Devin binding %s (bound %.0fh ago)",
                session_id, (now - bound_at) / 3600,
            )
            unbind_session(session_id)
            _untrack_session(session_id)
            continue

        try:
            result = _poll_devin_status(session_id, since_bytes=0)
        except Exception as exc:
            logger.debug("Devin monitor poll error for %s: %s", session_id, exc)
            continue

        status = result.get("status", "").lower()
        if status in ("completed", "error", "cancelled"):
            _notify_completion(session_id, meta, result)
            unbind_session(session_id)
            _untrack_session(session_id)


# Optional fallback callback for notifications when the gateway is unavailable.
# Signature: callback(session_id: str, meta: dict, result: dict) -> None
_notification_fallback: Optional[Callable[[str, dict, dict], Any]] = None


def register_notification_fallback(cb: Callable[[str, dict, dict], Any]) -> None:
    """Register a callback to receive Devin completion notifications.

    Called when the gateway runner is unavailable. Useful for plugins or
    custom notification sinks (e.g. webhook, Slack bot, etc.).
    """
    global _notification_fallback
    _notification_fallback = cb


def _get_gateway_adapter(platform: str):
    """Look up the gateway runner and return the adapter for *platform*.

    Returns (adapter, event_loop) or (None, None) on any failure.
    """
    try:
        from gateway.run import _gateway_runner_ref
        runner = _gateway_runner_ref()
    except Exception:
        return None, None

    if runner is None:
        return None, None
    if not hasattr(runner, "adapters"):
        return None, None

    adapter = runner.adapters.get(platform)
    if adapter is None:
        return None, None
    if not hasattr(runner, "_gateway_loop"):
        return None, None

    loop = runner._gateway_loop
    if loop is None or loop.is_closed():
        return None, None

    return adapter, loop


def _notify_completion(session_id: str, meta: dict, result: dict) -> None:
    """Send a completion notification for a Devin session.

    Tries the gateway runner first (for messaging platforms), then a
    registered fallback callback, then falls back to logging.
    Fire-and-forget: exceptions are swallowed so the monitor stays healthy.
    """
    platform = meta.get("platform")
    chat_id = meta.get("chat_id")
    thread_id = meta.get("thread_id")

    status = result.get("status", "unknown")
    summary = result.get("output", "")[:800]
    icon = "✅" if status == "completed" else "❌"
    message = (
        f"{icon} **Devin session** `{session_id}` **finished** (status: {status})\n\n"
        f"{summary}"
    )

    if not platform or not chat_id:
        logger.info("Devin session %s completed (no platform/chat_id for push)", session_id)
        return

    # 1. Try gateway runner notification
    adapter, loop = _get_gateway_adapter(platform)
    if adapter and loop:
        try:
            import asyncio
            metadata = {"thread_id": thread_id} if thread_id else None
            asyncio.run_coroutine_threadsafe(
                adapter.send(chat_id, message, metadata=metadata),
                loop,
            )
            logger.info(
                "Notified %s/%s about Devin session %s completion",
                platform, chat_id, session_id,
            )
            return
        except Exception as exc:
            logger.debug("Gateway adapter.send failed for %s: %s", session_id, exc)
    else:
        logger.debug(
            "Gateway not available for %s/%s (Devin session %s)",
            platform, chat_id, session_id,
        )

    # 2. Try registered fallback callback
    if _notification_fallback is not None:
        try:
            _notification_fallback(session_id, meta, result)
            logger.info("Devin session %s completion handled by fallback callback", session_id)
            return
        except Exception as exc:
            logger.debug("Notification fallback failed for %s: %s", session_id, exc)

    # 3. Log-only fallback
    logger.info(
        "Devin session %s completed on %s/%s (notification not sent: no adapter/loop)",
        session_id, platform, chat_id,
    )


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def check_devin_delegate_requirements() -> bool:
    """Available when the Devin MCP server is connected."""
    return _devin_mcp_available()


registry.register(
    name="devin_delegate",
    toolset="devin",
    schema={
        "name": "devin_delegate",
        "description": (
            "Delegate a task to a Devin agent running via oh-my-opendevin. "
            "Starts a background Devin CLI session with the given prompt, "
            "optionally waits for completion, and returns the result. "
            "Supports automatic model fallback on quota exhaustion.\n\n"
            "Use this for: long-running tasks (>5 min), complex multi-file "
            "refactors, tasks requiring Devin's reliability pack, or when "
            "you want to offload work to a separate agent instance.\n\n"
            "When wait=false, the session_id is returned for later polling "
            "with devin_status_check."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The task prompt to send to Devin.",
                },
                "model": {
                    "type": "string",
                    "description": (
                        "Devin model keyword: 'opus', 'sonnet', 'kimi-k2.6', 'swe', "
                        "'codex'. Defaults to kimi-k2.6."
                    ),
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory for the Devin session.",
                },
                "permission_mode": {
                    "type": "string",
                    "enum": ["auto", "dangerous"],
                    "description": "Devin permission mode. Default: dangerous (auto-approves).",
                },
                "resume": {
                    "type": "string",
                    "description": "Resume a previous Devin session by ID.",
                },
                "max_duration_ms": {
                    "type": "integer",
                    "description": "Max session duration in ms before auto-cancel. Default: 2h.",
                },
                "wait": {
                    "type": "boolean",
                    "description": "If true, block until the session completes. Default: true.",
                },
                "auto_fallback": {
                    "type": "boolean",
                    "description": (
                        "If true, automatically retry with the next model in the fallback chain "
                        "on quota errors. Default: true."
                    ),
                },
            },
            "required": ["prompt"],
        },
    },
    handler=lambda args, **kw: devin_delegate(
        prompt=args["prompt"],
        model=args.get("model"),
        cwd=args.get("cwd"),
        permission_mode=args.get("permission_mode"),
        resume=args.get("resume"),
        max_duration_ms=args.get("max_duration_ms"),
        wait=args.get("wait", True),
        auto_fallback=args.get("auto_fallback", True),
        task_id=kw.get("task_id"),
    ),
    check_fn=check_devin_delegate_requirements,
    requires_env=[],
    is_async=False,
    description="Delegate a task to Devin and optionally wait for the result.",
    emoji="🤖",
)

registry.register(
    name="devin_status_check",
    toolset="devin",
    schema={
        "name": "devin_status_check",
        "description": (
            "Check the status and incremental output of a Devin session. "
            "After the first call, always pass since_bytes (from the previous "
            "output_bytes field) to avoid redundant data transfer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID returned by devin_delegate.",
                },
                "since_bytes": {
                    "type": "integer",
                    "description": (
                        "Return only new output after this byte offset. "
                        "Use the output_bytes value from the previous devin_status_check response."
                    ),
                    "default": 0,
                },
            },
            "required": ["session_id"],
        },
    },
    handler=lambda args, **kw: devin_status_check(
        session_id=args["session_id"],
        since_bytes=args.get("since_bytes", 0),
        task_id=kw.get("task_id"),
    ),
    check_fn=check_devin_delegate_requirements,
    requires_env=[],
    is_async=False,
    description="Poll a Devin session for status and incremental output.",
    emoji="📊",
)

registry.register(
    name="devin_list_sessions",
    toolset="devin",
    schema={
        "name": "devin_list_sessions",
        "description": "List all Devin sessions managed by the MCP server.",
        "parameters": {
            "type": "object",
            "properties": {
                "filter_status": {
                    "type": "string",
                    "description": "Optional status filter (running, completed, error, etc.)",
                },
                "include_output": {
                    "type": "boolean",
                    "description": "Include a tail of each session's output.",
                    "default": False,
                },
            },
        },
    },
    handler=lambda args, **kw: devin_list_managed_sessions(
        filter_status=args.get("filter_status"),
        include_output=args.get("include_output", False),
        task_id=kw.get("task_id"),
    ),
    check_fn=check_devin_delegate_requirements,
    requires_env=[],
    is_async=False,
    description="List active and recent Devin sessions.",
    emoji="📋",
)

registry.register(
    name="devin_cancel",
    toolset="devin",
    schema={
        "name": "devin_cancel",
        "description": (
            "Cancel a running Devin session. Also removes it from the "
            "async notification monitor if it was bound."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID to cancel.",
                },
            },
            "required": ["session_id"],
        },
    },
    handler=lambda args, **kw: devin_cancel(
        session_id=args["session_id"],
        task_id=kw.get("task_id"),
    ),
    check_fn=check_devin_delegate_requirements,
    requires_env=[],
    is_async=False,
    description="Cancel a running Devin session.",
    emoji="🛑",
)

registry.register(
    name="devin_health",
    toolset="devin",
    schema={
        "name": "devin_health",
        "description": (
            "Check Devin MCP server health: binary availability, disk usage, "
            "slot usage, and orphaned session count."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    handler=lambda args, **kw: devin_health(),
    check_fn=check_devin_delegate_requirements,
    requires_env=[],
    is_async=False,
    description="Check Devin MCP server health.",
    emoji="🏥",
)

registry.register(
    name="devin_resumable",
    toolset="devin",
    schema={
        "name": "devin_resumable",
        "description": (
            "List Devin sessions that completed or errored and are eligible "
            "for resumption. Pass a session_id as the resume parameter to "
            "devin_delegate to continue work."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of sessions to return.",
                },
            },
        },
    },
    handler=lambda args, **kw: devin_resumable(
        limit=args.get("limit"),
        task_id=kw.get("task_id"),
    ),
    check_fn=check_devin_delegate_requirements,
    requires_env=[],
    is_async=False,
    description="List Devin sessions eligible for resumption.",
    emoji="🔁",
)
