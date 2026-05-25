#!/usr/bin/env python3
"""
Comprehensive verification script for the oh-my-opendevin Devin integration.

Run this after any changes to the Devin integration to ensure everything works:

    cd /path/to/hades-agent
    python3 tests/tools/verify_devin_integration.py

The script has three modes:
  1. SAFE (default):   Runs unit tests with mocks + MCP server handshake (no API quota used)
  2. LIVE (--live):    Starts a real Devin session (consumes API quota)
  3. QUIET (--quiet):  Only prints failures

Exit codes:
  0 = all checks passed
  1 = one or more checks failed
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure the repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# Colours / formatting (no-ops when not a TTY so CI stays clean)
# ---------------------------------------------------------------------------
_IS_TTY = sys.stdout.isatty()
_BOLD = "\033[1m" if _IS_TTY else ""
_GREEN = "\033[32m" if _IS_TTY else ""
_RED = "\033[31m" if _IS_TTY else ""
_YELLOW = "\033[33m" if _IS_TTY else ""
_RESET = "\033[0m" if _IS_TTY else ""

_PASS = f"{_GREEN}PASS{_RESET}"
_FAIL = f"{_RED}FAIL{_RESET}"
_SKIP = f"{_YELLOW}SKIP{_RESET}"

_failures: list[str] = []
_passes: int = 0
_skips: int = 0


def _ok(msg: str) -> None:
    global _passes
    _passes += 1
    print(f"  {_PASS} {msg}")


def _ko(msg: str) -> None:
    global _failures
    _failures.append(msg)
    print(f"  {_FAIL} {msg}")


def _skip(msg: str) -> None:
    global _skips
    _skips += 1
    print(f"  {_SKIP} {msg}")


def _banner(title: str) -> None:
    print(f"\n{_BOLD}{title}{_RESET}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# 1. AUTO-DISCOVERY
# ---------------------------------------------------------------------------
def test_discovery() -> None:
    _banner("1. Auto-discovery")

    import tools.devin_discovery as dd
    dd._discovered_repo = None

    # 1a. Env var wins
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_repo = Path(tmpdir) / "from_env"
        (fake_repo / "src/mcp-servers/devin").mkdir(parents=True)
        (fake_repo / "bin").mkdir()
        (fake_repo / "src/mcp-servers/devin/index.ts").write_text("")
        (fake_repo / "bin/devin-mcp-launcher.sh").write_text("")

        old_env = os.environ.get("OH_MY_OPENDEVIN_PATH", "")
        os.environ["OH_MY_OPENDEVIN_PATH"] = str(fake_repo)
        try:
            result = dd.discover_opendevin_repo()
            if result == str(fake_repo):
                _ok("OH_MY_OPENDEVIN_PATH takes precedence")
            else:
                _ko(f"Env var precedence failed: {result}")
        finally:
            os.environ["OH_MY_OPENDEVIN_PATH"] = old_env
            dd._discovered_repo = None

    # 1b. Known path fallback
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_repo = Path(tmpdir) / "oh-my-opendevin"
        (fake_repo / "src/mcp-servers/devin").mkdir(parents=True)
        (fake_repo / "bin").mkdir()
        (fake_repo / "src/mcp-servers/devin/index.ts").write_text("")
        (fake_repo / "bin/devin-mcp-launcher.sh").write_text("")

        old_home = os.environ.get("HOME", "")
        os.environ["HOME"] = tmpdir
        dd._discovered_repo = None
        try:
            result = dd.discover_opendevin_repo()
            if result == str(fake_repo):
                _ok("Known path discovery works")
            else:
                _ko(f"Known path discovery failed: {result}")
        finally:
            os.environ["HOME"] = old_home
            dd._discovered_repo = None

    # 1c. Bun check
    import shutil
    has_bun = shutil.which("bun") is not None
    if has_bun:
        _ok("bun is on PATH")
    else:
        _skip("bun not on PATH")

    # 1d. Config production
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_repo = Path(tmpdir) / "oh-my-opendevin"
        (fake_repo / "src/mcp-servers/devin").mkdir(parents=True)
        (fake_repo / "bin").mkdir()
        (fake_repo / "src/mcp-servers/devin/index.ts").write_text("")
        (fake_repo / "bin/devin-mcp-launcher.sh").write_text("")

        old_home = os.environ.get("HOME", "")
        os.environ["HOME"] = tmpdir
        dd._discovered_repo = None
        try:
            cfg = dd.get_devin_mcp_config()
            if cfg and "opendevin_devin" in cfg:
                _ok("get_devin_mcp_config produces valid config")
            else:
                _ko("get_devin_mcp_config returned None")
        finally:
            os.environ["HOME"] = old_home
            dd._discovered_repo = None


# ---------------------------------------------------------------------------
# 2. MCP SERVER HANDSHAKE (live, but no API calls)
# ---------------------------------------------------------------------------
def test_mcp_handshake() -> None:
    _banner("2. MCP server handshake")

    import tools.devin_discovery as dd
    dd._discovered_repo = None
    cfg = dd.get_devin_mcp_config()
    if cfg is None:
        _skip("oh-my-opendevin not found — skipping handshake")
        return

    launcher = cfg["opendevin_devin"]["args"][0]
    mcp_server = Path(launcher).parent.parent / "dist/mcp-servers/devin/index.js"
    if not mcp_server.exists():
        _skip(f"MCP server not built at {mcp_server}")
        return

    handshake = (
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":'
        '{"protocolVersion":"2024-11-05","capabilities":{},'
        '"clientInfo":{"name":"verify","version":"0.1.0"}}}'
        '\n{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'
    )

    try:
        proc = subprocess.run(
            ["bun", "run", str(mcp_server)],
            input=handshake,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        _skip("bun executable not found")
        return
    except subprocess.TimeoutExpired:
        _ko("MCP server did not respond within 30s")
        return

    response_lines = [ln for ln in (proc.stdout + proc.stderr).splitlines()
                      if ln.strip().startswith('{"jsonrpc"') or ln.strip().startswith('{"result"')]

    found_tools = set()
    for line in response_lines:
        try:
            msg = json.loads(line)
            for t in msg.get("result", {}).get("tools", []):
                found_tools.add(t["name"])
        except (json.JSONDecodeError, KeyError):
            continue

    core = {"devin_start", "devin_status", "devin_wait", "devin_cancel",
            "devin_list", "devin_health", "devin_resumable"}
    missing = core - found_tools
    if not missing:
        _ok(f"All {len(core)} core MCP tools exposed")
    else:
        _ko(f"Missing MCP tools: {missing}")


# ---------------------------------------------------------------------------
# 3. HIGH-LEVEL TOOL REGISTRY
# ---------------------------------------------------------------------------
def test_tool_registry() -> None:
    _banner("3. High-level tool registry")

    # Force import so registry entries are populated
    import tools.devin_delegate as ddg  # noqa: F401
    from tools.registry import registry

    our_tools = ["devin_delegate", "devin_status_check", "devin_list_sessions",
                 "devin_cancel", "devin_health", "devin_resumable"]
    for t in our_tools:
        entry = registry.get_entry(t)
        if entry is not None:
            _ok(f"{t} registered (toolset={entry.toolset})")
        else:
            _ko(f"{t} NOT registered")

    # Check toolsets.py
    from toolsets import TOOLSETS
    devin_tools = set(TOOLSETS.get("devin", {}).get("tools", []))
    missing = set(our_tools) - devin_tools
    if not missing:
        _ok("All tools listed in toolsets.py['devin']")
    else:
        _ko(f"Missing from toolsets.py: {missing}")


# ---------------------------------------------------------------------------
# 4. MODEL VALIDATION & CONFIG DEFAULTS
# ---------------------------------------------------------------------------
def test_model_system() -> None:
    _banner("4. Model validation & config defaults")

    import tools.devin_delegate as ddg

    # Validation
    for m in ("opus", "sonnet", "kimi-k2.6", "swe"):
        if ddg._validate_devin_model(m) == m:
            _ok(f"_validate_devin_model('{m}')")
        else:
            _ko(f"_validate_devin_model('{m}') failed")

    if ddg._validate_devin_model("swe-1-6") == "swe":
        _ok("_validate_devin_model('swe-1-6') -> 'swe' (prefix)")
    else:
        _ko("Prefix match failed")

    if ddg._validate_devin_model("gpt-4") is None:
        _ok("_validate_devin_model('gpt-4') -> None (unknown)")
    else:
        _ko("Unknown model not rejected")

    # Default model
    ddg._config_cache = None
    default = ddg._get_default_model()
    if default in ddg._KNOWN_DEVIN_MODELS:
        _ok(f"_get_default_model() -> '{default}'")
    else:
        _ko(f"Unknown default model: {default}")


# ---------------------------------------------------------------------------
# 5. SESSION LIFECYCLE (mocked)
# ---------------------------------------------------------------------------
def test_session_lifecycle() -> None:
    _banner("5. Session lifecycle (mocked)")

    import tools.devin_delegate as ddg

    # 5a. Start + wait + success
    fake_start = {"session_id": "sess-ok", "snapshot": {"model": "sonnet"},
                  "raw": "started", "model": "sonnet"}
    fake_wait = {"exited": True, "status": "completed", "output": "done"}

    ddg._active_devin_sessions.clear()
    with patch.object(ddg, "_start_devin_session", return_value=fake_start):
        with patch.object(ddg, "_wait_devin_session", return_value=fake_wait):
            result = json.loads(ddg.devin_delegate(prompt="test", wait=True))

    if result.get("status") == "completed":
        _ok("wait=True returns completed result")
    else:
        _ko(f"Unexpected result: {result}")

    # 5b. Fire-and-forget binding
    ddg._session_bindings.clear()
    ddg._active_devin_sessions.clear()
    with patch.object(ddg, "_start_devin_session", return_value=fake_start):
        result = json.loads(ddg.devin_delegate(
            prompt="async", wait=False, platform="telegram", chat_id="123"
        ))
    if result.get("status") == "running" and "sess-ok" in ddg._session_bindings:
        _ok("wait=False binds session for async notification")
    else:
        _ko("Binding failed")
    ddg._session_bindings.clear()

    # 5c. Quota fallback
    error = {"error": "QUOTA_EXCEEDED", "quota_exceeded": True, "model": "opus"}
    success = {"session_id": "sess-fb", "snapshot": {"model": "sonnet"},
               "raw": "ok", "model": "sonnet"}
    ddg._active_devin_sessions.clear()
    with patch.object(ddg, "_start_devin_session", side_effect=[error, success]):
        with patch.object(ddg, "_wait_devin_session", return_value=fake_wait):
            result = json.loads(ddg.devin_delegate(prompt="test", model="opus", wait=True))
    if result.get("status") == "completed":
        _ok("Quota fallback works")
    else:
        _ko(f"Fallback failed: {result}")

    # 5d. Timeout
    ddg._active_devin_sessions.clear()
    fake_start2 = {"session_id": "sess-to", "snapshot": {"model": "kimi-k2.6"},
                   "raw": "started", "model": "kimi-k2.6"}
    running = {"exited": False, "status": "running", "output": ""}
    with patch.object(ddg, "_start_devin_session", return_value=fake_start2):
        with patch.object(ddg, "_wait_devin_session", return_value=running):
            with patch.object(ddg, "_DEFAULT_MAX_WAIT_SECONDS", 0.1):
                result = json.loads(ddg.devin_delegate(prompt="test", wait=True))
    if result.get("status") == "timeout":
        _ok("Timeout result returned")
    else:
        _ko(f"Expected timeout, got: {result}")

    # 5e. Error tag extraction
    if ddg._extract_error_tag("RATE_LIMIT hit") == "RATE_LIMIT":
        _ok("Error tag extraction")
    else:
        _ko("Error tag extraction failed")

    # 5f. Streaming callback
    streamed = []
    fake_start3 = {"session_id": "sess-str", "snapshot": {"model": "sonnet"},
                   "raw": "started", "model": "sonnet"}
    wait_resp = {"exited": False, "status": "running", "output": ""}
    wait_resp2 = {"exited": True, "status": "completed", "output": "final"}
    poll_resp = {"status": "running", "output": "chunk", "output_bytes": 5}
    ddg._active_devin_sessions.clear()
    with patch.object(ddg, "_start_devin_session", return_value=fake_start3):
        with patch.object(ddg, "_wait_devin_session", side_effect=[wait_resp, wait_resp2]):
            with patch.object(ddg, "_poll_devin_status", return_value=poll_resp):
                result = json.loads(ddg.devin_delegate(
                    prompt="test", wait=True, stream_callback=streamed.append,
                ))
    if "chunk" in streamed:
        _ok("stream_callback receives output chunks")
    else:
        _ko(f"Streaming failed: {streamed}")


# ---------------------------------------------------------------------------
# 6. THREAD SAFETY & CLEANUP
# ---------------------------------------------------------------------------
def test_threading_cleanup() -> None:
    _banner("6. Thread safety & cleanup")

    import tools.devin_delegate as ddg

    # 6a. Bindings lock
    ddg._session_bindings.clear()
    ddg._bind_session_to_conversation("sess-1", platform="telegram", chat_id="123")
    if "sess-1" in ddg.get_session_bindings():
        _ok("bind -> get roundtrip")
    else:
        _ko("Binding roundtrip failed")
    ddg.unbind_session("sess-1")
    if "sess-1" not in ddg.get_session_bindings():
        _ok("unbind works")
    else:
        _ko("Unbind failed")

    # 6b. Session tracking
    ddg._active_devin_sessions.clear()
    ddg._track_session("sess-t1")
    if "sess-t1" in ddg._active_devin_sessions:
        _ok("_track_session")
    else:
        _ko("Track failed")
    ddg._untrack_session("sess-t1")
    if "sess-t1" not in ddg._active_devin_sessions:
        _ok("_untrack_session")
    else:
        _ko("Untrack failed")

    # 6c. TTL purge
    ddg._session_bindings.clear()
    ddg._session_bindings["sess-old"] = {
        "platform": "telegram", "chat_id": "1",
        "bound_at": time.time() - ddg._BINDING_TTL_SECONDS - 1,
    }
    ddg._check_pending_sessions()
    if "sess-old" not in ddg._session_bindings:
        _ok("Stale binding TTL purged")
    else:
        _ko("TTL purge failed")

    # 6d. Exponential backoff
    if (ddg._compute_poll_interval(0) == ddg._BASE_POLL_INTERVAL_SECONDS and
        ddg._compute_poll_interval(5) == ddg._MAX_POLL_INTERVAL_SECONDS):
        _ok("Exponential backoff capped correctly")
    else:
        _ko("Backoff cap wrong")


# ---------------------------------------------------------------------------
# 7. SUBAGENT BRIDGE
# ---------------------------------------------------------------------------
def test_subagent_bridge() -> None:
    _banner("7. Subagent bridge")

    from tools.delegate_tool import DevinSubagent

    # 7a. Normal result
    sa = DevinSubagent(
        goal="test", model="sonnet", subagent_id="sa-1",
        parent_subagent_id=None, depth=0,
        progress_cb=None, parent_print_fn=None,
    )
    with patch("tools.devin_delegate.devin_delegate", return_value=json.dumps({
        "session_id": "dev-1", "status": "completed", "summary": "all done",
    })):
        result = sa.run_conversation("do it")
    if result.get("completed") is True and result["final_response"] == "all done":
        _ok("DevinSubagent returns agent-compatible dict")
    else:
        _ko(f"Subagent result wrong: {result}")

    # 7b. Malformed JSON fallback
    sa2 = DevinSubagent(
        goal="test", model="sonnet", subagent_id="sa-2",
        parent_subagent_id=None, depth=0,
        progress_cb=None, parent_print_fn=None,
    )
    malformed = '{"session_id": "dev-2", "status": "completed"'  # missing close
    with patch("tools.devin_delegate.devin_delegate", return_value=malformed):
        result2 = sa2.run_conversation("do it")
    if sa2._devin_session_id == "dev-2" and "JSON parse error" in result2.get("error", ""):
        _ok("Malformed JSON extracts session_id and surfaces error")
    else:
        _ko(f"Malformed JSON handling failed: {result2}")

    # 7c. Interrupt
    sa3 = DevinSubagent(
        goal="test", model="sonnet", subagent_id="sa-3",
        parent_subagent_id=None, depth=0,
        progress_cb=None, parent_print_fn=None,
    )
    sa3._devin_session_id = "dev-3"
    with patch("tools.devin_delegate._call_devin_mcp") as mock_cancel:
        sa3.interrupt()
        if sa3._interrupt_requested and mock_cancel.called:
            _ok("interrupt() sets flag and cancels session")
        else:
            _ko("Interrupt failed")

    # 7d. Heartbeat
    sa4 = DevinSubagent(
        goal="test", model="sonnet", subagent_id="sa-4",
        parent_subagent_id=None, depth=0,
        progress_cb=None, parent_print_fn=None,
    )
    s1 = sa4.get_activity_summary()
    s2 = sa4.get_activity_summary()
    if s1["api_call_count"] == 1 and s2["api_call_count"] == 2:
        _ok("Heartbeat counter advances")
    else:
        _ko("Heartbeat counter stuck")


# ---------------------------------------------------------------------------
# 8. ROLE NORMALISATION
# ---------------------------------------------------------------------------
def test_role_normalisation() -> None:
    _banner("8. Role normalisation")

    from tools.delegate_tool import _normalize_role

    for role, expected in [("devin", "devin"), ("leaf", "leaf"),
                           ("orchestrator", "orchestrator"), (None, "leaf"),
                           ("", "leaf"), ("unknown", "leaf")]:
        if _normalize_role(role) == expected:
            _ok(f"_normalize_role({role!r}) -> {expected!r}")
        else:
            _ko(f"_normalize_role({role!r}) wrong")


# ---------------------------------------------------------------------------
# 9. LIVE DEVIN SESSION (optional, consumes API quota)
# ---------------------------------------------------------------------------
def test_live_session(args: argparse.Namespace) -> None:
    _banner("9. Live Devin session")

    if not args.live:
        _skip("Pass --live to start a real Devin session (consumes API quota)")
        return

    import tools.devin_delegate as ddg

    print("\n  Starting a REAL Devin session — this will consume API quota.")
    print("  Prompt: 'Write a hello-world Python script'")
    print("  Press Ctrl-C within 3 seconds to abort...")
    try:
        time.sleep(3)
    except KeyboardInterrupt:
        print("\n  Aborted.")
        _skip("User aborted live test")
        return

    streamed: list[str] = []
    result_str = ddg.devin_delegate(
        prompt="Write a hello-world Python script and save it to /tmp/hello_devin.py",
        model="swe",
        wait=True,
        stream_callback=streamed.append,
    )
    result = json.loads(result_str)
    print(f"\n  Result: {json.dumps(result, indent=2, ensure_ascii=False)}")
    if result.get("status") == "completed":
        _ok("Live session completed successfully")
    else:
        _ko(f"Live session failed: {result.get('error', 'unknown')}")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Devin integration")
    parser.add_argument("--live", action="store_true",
                        help="Start a real billed Devin session (consumes quota)")
    parser.add_argument("--quiet", action="store_true",
                        help="Only print failures")
    args = parser.parse_args()

    if args.quiet:
        # Redirect stdout, keep stderr for failures
        class DevNull:
            def write(self, _: str) -> None: pass
            def flush(self) -> None: pass
        sys.stdout = DevNull()

    print(f"\n{_BOLD}Devin Integration Verification{_RESET}")
    print(f"Repo: {REPO_ROOT}")
    print(f"Live mode: {'YES (will use API quota!)' if args.live else 'NO'}")

    test_discovery()
    test_mcp_handshake()
    test_tool_registry()
    test_model_system()
    test_session_lifecycle()
    test_threading_cleanup()
    test_subagent_bridge()
    test_role_normalisation()
    test_live_session(args)

    # Summary
    print(f"\n{'=' * 60}")
    print(f"{_BOLD}Summary{_RESET}")
    print(f"  Passes:  {_passes}")
    print(f"  Skips:   {_skips}")
    print(f"  Failures: {len(_failures)}")

    if _failures:
        print(f"\n{_RED}Failed checks:{_RESET}")
        for f in _failures:
            print(f"  - {f}")
        return 1

    print(f"\n{_GREEN}ALL CHECKS PASSED{_RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
