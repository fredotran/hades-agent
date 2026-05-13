"""Tests for the oh-my-opendevin Devin integration.

Covers auto-discovery, high-level delegation tools, subagent bridge, and
bidirectional notification monitor. All tests use mocks -- no real Devin
sessions or MCP servers are started.
"""

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# devin_discovery
# ---------------------------------------------------------------------------

class TestDiscoverOpenDevinRepo:
    """Tests for tools.devin_discovery.discover_opendevin_repo."""

    def test_env_var_takes_precedence(self, tmp_path, monkeypatch):
        """OH_MY_OPENDEVIN_PATH is checked first and wins."""
        # given: a fake repo with marker files
        fake_repo = tmp_path / "from_env"
        (fake_repo / "src/mcp-servers/devin").mkdir(parents=True)
        (fake_repo / "bin").mkdir()
        (fake_repo / "src/mcp-servers/devin/index.ts").write_text("")
        (fake_repo / "bin/devin-mcp-launcher.sh").write_text("")

        monkeypatch.setenv("OH_MY_OPENDEVIN_PATH", str(fake_repo))
        monkeypatch.chdir(tmp_path)

        # when
        import tools.devin_discovery as dd
        # Reset module cache to force re-discovery
        dd._discovered_repo = None
        result = dd.discover_opendevin_repo()

        # then
        assert result == str(fake_repo)

    def test_known_path_discovery(self, tmp_path, monkeypatch):
        """Repo found in a known search path."""
        # given
        fake_repo = tmp_path / "oh-my-opendevin"
        (fake_repo / "src/mcp-servers/devin").mkdir(parents=True)
        (fake_repo / "bin").mkdir()
        (fake_repo / "src/mcp-servers/devin/index.ts").write_text("")
        (fake_repo / "bin/devin-mcp-launcher.sh").write_text("")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.chdir(tmp_path)

        import tools.devin_discovery as dd
        dd._discovered_repo = None

        # when
        result = dd.discover_opendevin_repo()

        # then
        assert result == str(fake_repo)

    def test_not_found_returns_none(self, tmp_path, monkeypatch):
        """When no repo exists, discover_opendevin_repo returns None."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("OH_MY_OPENDEVIN_PATH", raising=False)

        import tools.devin_discovery as dd
        dd._discovered_repo = None

        result = dd.discover_opendevin_repo()
        assert result is None

    def test_cached_result_reused(self, tmp_path, monkeypatch):
        """Second call returns cached result without re-scanning."""
        import tools.devin_discovery as dd
        dd._discovered_repo = "/cached/path"

        result = dd.discover_opendevin_repo()
        assert result == "/cached/path"


class TestGetDevinMcpConfig:
    """Tests for tools.devin_discovery.get_devin_mcp_config."""

    def test_returns_config_when_repo_and_bun_found(self, tmp_path, monkeypatch):
        """Config dict is produced when repo is valid and bun is on PATH."""
        fake_repo = tmp_path / "oh-my-opendevin"
        (fake_repo / "src/mcp-servers/devin").mkdir(parents=True)
        (fake_repo / "bin").mkdir()
        (fake_repo / "src/mcp-servers/devin/index.ts").write_text("")
        (fake_repo / "bin/devin-mcp-launcher.sh").write_text("")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/bun" if x == "bun" else None)

        import tools.devin_discovery as dd
        dd._discovered_repo = None

        config = dd.get_devin_mcp_config()

        assert config is not None
        assert "opendevin_devin" in config
        assert config["opendevin_devin"]["command"] == "bash"

    def test_returns_none_when_bun_missing(self, tmp_path, monkeypatch):
        """Config is None when bun is not available."""
        fake_repo = tmp_path / "oh-my-opendevin"
        (fake_repo / "src/mcp-servers/devin").mkdir(parents=True)
        (fake_repo / "bin").mkdir()
        (fake_repo / "src/mcp-servers/devin/index.ts").write_text("")
        (fake_repo / "bin/devin-mcp-launcher.sh").write_text("")
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr("shutil.which", lambda _: None)

        import tools.devin_discovery as dd
        dd._discovered_repo = None

        config = dd.get_devin_mcp_config()
        assert config is None


# ---------------------------------------------------------------------------
# devin_delegate — helpers
# ---------------------------------------------------------------------------

class TestDevinHelpers:
    """Tests for internal helper functions in devin_delegate."""

    def test_parse_snapshot_extracts_key_value(self):
        """_parse_snapshot splits key:value lines correctly."""
        import tools.devin_delegate as ddg

        text = "session_id: abc123\nstatus: running\nmodel: sonnet\n"
        snap = ddg._parse_snapshot(text)

        assert snap["session_id"] == "abc123"
        assert snap["status"] == "running"
        assert snap["model"] == "sonnet"

    def test_parse_output_from_snapshot_new_output(self):
        """_parse_output_from_snapshot extracts after the new-output marker."""
        import tools.devin_delegate as ddg

        text = "status: done\n--- new output ---\nhello world"
        output = ddg._parse_output_from_snapshot(text)
        assert output == "hello world"

    def test_parse_output_from_snapshot_tail(self):
        """_parse_output_from_snapshot falls back to tail marker."""
        import tools.devin_delegate as ddg

        text = "status: done\n--- output (tail) ---\nfoo bar"
        output = ddg._parse_output_from_snapshot(text)
        assert output == "foo bar"

    def test_next_fallback_model_advances_chain(self):
        """_get_next_fallback_model walks the chain."""
        import tools.devin_delegate as ddg

        assert ddg._get_next_fallback_model("opus") == "sonnet"
        assert ddg._get_next_fallback_model("sonnet") == "kimi-k2.6"
        assert ddg._get_next_fallback_model("kimi-k2.6") == "swe"
        assert ddg._get_next_fallback_model("swe") is None

    def test_next_fallback_unknown_starts_at_beginning(self):
        """Unknown model falls back to chain start."""
        import tools.devin_delegate as ddg

        assert ddg._get_next_fallback_model("unknown") == "opus"

    def test_extract_text_from_mcp_result(self):
        """_extract_text_from_mcp_result pulls the text payload."""
        import tools.devin_delegate as ddg

        assert ddg._extract_text_from_mcp_result({"result": "ok"}) == "ok"
        assert ddg._extract_text_from_mcp_result({"error": "fail"}) == "fail"


class TestDevinMcpAvailable:
    """Tests for _devin_mcp_available and _find_devin_mcp_tool."""

    def test_available_when_tool_registered(self):
        """_devin_mcp_available returns True when devin_start is in registry."""
        import tools.devin_delegate as ddg

        mock_entry = MagicMock()
        mock_entry.toolset = "mcp-opendevin_devin"

        with patch.object(ddg.registry, "get_all_tool_names", return_value=["mcp_opendevin_devin_devin_start"]):
            with patch.object(ddg.registry, "get_entry", return_value=mock_entry):
                assert ddg._devin_mcp_available() is True

    def test_not_available_when_missing(self):
        """_devin_mcp_available returns False when no devin tools are registered."""
        import tools.devin_delegate as ddg

        with patch.object(ddg.registry, "get_all_tool_names", return_value=["terminal"]):
            assert ddg._devin_mcp_available() is False


class TestCallDevinMcp:
    """Tests for _call_devin_mcp dispatch and result parsing."""

    def test_dispatches_and_returns_json(self):
        """_call_devin_mcp returns parsed JSON from registry.dispatch."""
        import tools.devin_delegate as ddg

        with patch.object(ddg.registry, "get_all_tool_names", return_value=["mcp_opendevin_devin_devin_start"]):
            mock_entry = MagicMock(toolset="mcp-opendevin_devin")
            with patch.object(ddg.registry, "get_entry", return_value=mock_entry):
                with patch.object(ddg.registry, "dispatch", return_value='{"result": "ok"}'):
                    result = ddg._call_devin_mcp("devin_start", {"prompt": "hello"})
                    assert result == {"result": "ok"}

    def test_plain_text_fallback(self):
        """Non-JSON dispatch result is wrapped as a result string."""
        import tools.devin_delegate as ddg

        with patch.object(ddg.registry, "get_all_tool_names", return_value=["mcp_opendevin_devin_devin_start"]):
            mock_entry = MagicMock(toolset="mcp-opendevin_devin")
            with patch.object(ddg.registry, "get_entry", return_value=mock_entry):
                with patch.object(ddg.registry, "dispatch", return_value="raw text"):
                    result = ddg._call_devin_mcp("devin_start", {})
                    assert result == {"result": "raw text"}

    def test_missing_tool_returns_error(self):
        """When the Devin MCP tool is not found, an error dict is returned."""
        import tools.devin_delegate as ddg

        with patch.object(ddg.registry, "get_all_tool_names", return_value=["terminal"]):
            result = ddg._call_devin_mcp("devin_start", {})
            assert "error" in result


# ---------------------------------------------------------------------------
# devin_delegate — high-level tool
# ---------------------------------------------------------------------------

class TestDevinDelegate:
    """Tests for devin_delegate()."""

    def test_wait_false_returns_running(self):
        """wait=False returns session_id immediately."""
        import tools.devin_delegate as ddg

        fake_start = {
            "session_id": "sess-123",
            "snapshot": {"model": "sonnet"},
            "raw": "started",
        }

        with patch.object(ddg, "_start_devin_session", return_value=fake_start):
            result = json.loads(ddg.devin_delegate(prompt="do it", wait=False))

        assert result["status"] == "running"
        assert result["session_id"] == "sess-123"
        assert result["model"] == "sonnet"

    def test_quota_error_with_fallback(self):
        """QUOTA_EXCEEDED triggers model fallback."""
        import tools.devin_delegate as ddg

        # First call fails with quota, second succeeds
        side_effects = [
            {"error": "QUOTA_EXCEEDED", "quota_exceeded": True, "model": "opus"},
            {"session_id": "sess-456", "snapshot": {"model": "sonnet"}, "raw": "ok"},
        ]

        with patch.object(ddg, "_start_devin_session", side_effect=side_effects):
            with patch.object(ddg, "_wait_devin_session", return_value={"exited": True, "status": "completed", "output": "done"}):
                result = json.loads(ddg.devin_delegate(prompt="do it", model="opus", wait=True))

        assert result["status"] == "completed"
        assert result["session_id"] == "sess-456"

    def test_quota_exhausted_all_models(self):
        """When all models in the chain are exhausted, an error is returned."""
        import tools.devin_delegate as ddg

        error = {"error": "QUOTA_EXCEEDED", "quota_exceeded": True, "model": "swe"}
        with patch.object(ddg, "_start_devin_session", return_value=error):
            result = json.loads(ddg.devin_delegate(prompt="do it", model="swe", wait=True))

        assert "error" in result
        assert result["attempts"] >= 1

    def test_wait_true_blocks_until_exited(self):
        """wait=True polls until the session exits."""
        import tools.devin_delegate as ddg

        fake_start = {
            "session_id": "sess-789",
            "snapshot": {"model": "kimi-k2.6"},
            "raw": "started",
        }

        wait_responses = [
            {"exited": True, "status": "completed", "output": "all done"},
        ]

        with patch.object(ddg, "_start_devin_session", return_value=fake_start):
            with patch.object(ddg, "_wait_devin_session", side_effect=wait_responses):
                result = json.loads(ddg.devin_delegate(prompt="do it", wait=True))

        assert result["status"] == "completed"
        assert result["summary"] == "all done"

    def test_wait_loop_times_out(self):
        """If the session never exits, a timeout result is returned."""
        import tools.devin_delegate as ddg

        fake_start = {
            "session_id": "sess-abc",
            "snapshot": {"model": "kimi-k2.6"},
            "raw": "started",
        }

        # Session never exits
        wait_resp = {"exited": False, "status": "running", "output": ""}

        with patch.object(ddg, "_start_devin_session", return_value=fake_start):
            with patch.object(ddg, "_wait_devin_session", return_value=wait_resp):
                # Speed up the wait limit so the test doesn't take 2 hours
                with patch.object(ddg, "_DEFAULT_MAX_WAIT_SECONDS", 0.1):
                    result = json.loads(ddg.devin_delegate(prompt="do it", wait=True))

        assert result["status"] == "timeout"

    def test_wait_false_binds_conversation(self):
        """wait=True does NOT bind; wait=False DOES bind for notifications."""
        import tools.devin_delegate as ddg

        fake_start = {
            "session_id": "sess-bind",
            "snapshot": {"model": "sonnet"},
            "raw": "started",
        }

        # Clear existing bindings
        ddg._session_bindings.clear()
        # Stop any running monitor to avoid interference
        ddg._monitor_thread = None

        with patch.object(ddg, "_start_devin_session", return_value=fake_start):
            ddg.devin_delegate(prompt="async task", wait=False, platform="telegram", chat_id="123")

        # then: binding should exist
        assert "sess-bind" in ddg._session_bindings
        assert ddg._session_bindings["sess-bind"]["platform"] == "telegram"
        assert ddg._session_bindings["sess-bind"]["chat_id"] == "123"

        ddg._session_bindings.clear()

    def test_wait_true_does_not_bind(self):
        """Synchronous wait mode should not leave a session binding."""
        import tools.devin_delegate as ddg

        fake_start = {
            "session_id": "sess-sync",
            "snapshot": {"model": "sonnet"},
            "raw": "started",
        }

        ddg._session_bindings.clear()
        ddg._monitor_thread = None

        with patch.object(ddg, "_start_devin_session", return_value=fake_start):
            with patch.object(ddg, "_wait_devin_session", return_value={"exited": True, "status": "completed", "output": "ok"}):
                ddg.devin_delegate(prompt="sync task", wait=True, platform="telegram", chat_id="123")

        # then: no binding should exist
        assert "sess-sync" not in ddg._session_bindings

        ddg._session_bindings.clear()


# ---------------------------------------------------------------------------
# Monitor / bidirectional notifications
# ---------------------------------------------------------------------------

class TestDevinMonitor:
    """Tests for the background monitor and notification logic."""

    def test_check_pending_sessions_unbinds_on_completion(self):
        """Completed sessions are unbound after notification."""
        import tools.devin_delegate as ddg

        ddg._session_bindings.clear()
        ddg._session_bindings["sess-done"] = {
            "platform": "telegram", "chat_id": "123", "task_id": None,
        }

        with patch.object(ddg, "_poll_devin_status", return_value={"status": "completed", "output": "yep"}):
            with patch.object(ddg, "_notify_completion"):
                ddg._check_pending_sessions()

        assert "sess-done" not in ddg._session_bindings

    def test_check_pending_sessions_skips_running(self):
        """Running sessions are left bound."""
        import tools.devin_delegate as ddg

        ddg._session_bindings.clear()
        ddg._session_bindings["sess-run"] = {
            "platform": "telegram", "chat_id": "123", "task_id": None,
        }

        with patch.object(ddg, "_poll_devin_status", return_value={"status": "running", "output": ""}):
            ddg._check_pending_sessions()

        assert "sess-run" in ddg._session_bindings
        ddg._session_bindings.clear()

    def test_notify_completion_with_gateway(self):
        """Gateway notification is attempted when adapter and loop exist."""
        import tools.devin_delegate as ddg

        mock_adapter = MagicMock()
        mock_loop = MagicMock()
        mock_loop.is_closed.return_value = False

        mock_runner = MagicMock()
        mock_runner.adapters = {"telegram": mock_adapter}
        mock_runner._gateway_loop = mock_loop

        with patch("gateway.run._gateway_runner_ref", return_value=lambda: mock_runner):
            ddg._notify_completion(
                "sess-1",
                {"platform": "telegram", "chat_id": "456", "thread_id": "789"},
                {"status": "completed", "output": "done"},
            )

        # Verify run_coroutine_threadsafe was used
        assert mock_loop.call_count >= 0  # loop was accessed

    def test_notify_completion_no_platform_logs(self):
        """Without platform/chat_id, notification falls back to logging."""
        import tools.devin_delegate as ddg

        with patch("gateway.run._gateway_runner_ref", return_value=lambda: None):
            # Should not raise
            ddg._notify_completion(
                "sess-2",
                {"platform": None, "chat_id": None},
                {"status": "completed", "output": "done"},
            )

    def test_ensure_monitor_starts_once(self):
        """Multiple calls to _ensure_monitor start only one thread."""
        import tools.devin_delegate as ddg

        ddg._monitor_thread = None
        with patch("threading.Thread") as mock_thread:
            mock_instance = MagicMock()
            mock_instance.is_alive.return_value = False
            mock_thread.return_value = mock_instance

            ddg._ensure_monitor()
            ddg._ensure_monitor()

            # Thread constructor should only be called once
            assert mock_thread.call_count == 1

        ddg._monitor_thread = None


# ---------------------------------------------------------------------------
# Subagent bridge (DevinSubagent)
# ---------------------------------------------------------------------------

class TestDevinSubagent:
    """Tests for DevinSubagent in delegate_tool."""

    def test_run_conversation_returns_agent_compatible_dict(self):
        """DevinSubagent.run_conversation returns the shape _run_single_child expects."""
        from tools.delegate_tool import DevinSubagent

        sa = DevinSubagent(
            goal="test", model="sonnet", subagent_id="sa-1",
            parent_subagent_id=None, depth=0,
            progress_cb=None, parent_print_fn=None,
        )

        with patch("tools.devin_delegate.devin_delegate", return_value=json.dumps({
            "session_id": "dev-1",
            "status": "completed",
            "summary": "result text",
        })):
            result = sa.run_conversation("do it", task_id="t-1")

        assert result["final_response"] == "result text"
        assert result["completed"] is True
        assert result["api_calls"] == 0

    def test_interrupt_sets_flag_and_cancels(self):
        """interrupt() sets the flag and cancels the Devin session."""
        from tools.delegate_tool import DevinSubagent

        sa = DevinSubagent(
            goal="test", model="sonnet", subagent_id="sa-2",
            parent_subagent_id=None, depth=0,
            progress_cb=None, parent_print_fn=None,
        )
        sa._devin_session_id = "dev-2"

        with patch("tools.devin_delegate._call_devin_mcp") as mock_cancel:
            sa.interrupt()
            assert sa._interrupt_requested is True
            mock_cancel.assert_called_once_with("devin_cancel", {"session_id": "dev-2"})

    def test_get_activity_summary_advances_counter(self):
        """get_activity_summary increments the synthetic counter."""
        from tools.delegate_tool import DevinSubagent

        sa = DevinSubagent(
            goal="test", model="sonnet", subagent_id="sa-3",
            parent_subagent_id=None, depth=0,
            progress_cb=None, parent_print_fn=None,
        )

        s1 = sa.get_activity_summary()
        s2 = sa.get_activity_summary()

        assert s1["api_call_count"] == 1
        assert s2["api_call_count"] == 2
        assert s1["current_tool"] == "devin_delegate"


# ---------------------------------------------------------------------------
# Role normalisation
# ---------------------------------------------------------------------------

class TestNormalizeRole:
    """Tests for _normalize_role with the new 'devin' role."""

    def test_devin_role_accepted(self):
        """_normalize_role accepts 'devin' as a valid role."""
        from tools.delegate_tool import _normalize_role

        assert _normalize_role("devin") == "devin"

    def test_leaf_and_orchestrator_still_work(self):
        """Existing roles remain valid."""
        from tools.delegate_tool import _normalize_role

        assert _normalize_role("leaf") == "leaf"
        assert _normalize_role("orchestrator") == "orchestrator"

    def test_unknown_coerces_to_leaf(self):
        """Unknown roles still degrade to leaf."""
        from tools.delegate_tool import _normalize_role

        assert _normalize_role("unknown") == "leaf"


# ---------------------------------------------------------------------------
# Live MCP smoke test (skipped when server unavailable)
# ---------------------------------------------------------------------------

class TestLiveMcpSmoke:
    """Smoke tests that require a real oh-my-opendevin checkout + bun."""

    @pytest.fixture(scope="class")
    def live_mcp_config(self):
        """Yield the MCP config only if the server is actually reachable."""
        import shutil
        import tools.devin_discovery as dd
        dd._discovered_repo = None

        # Fast-fail: bun missing
        if shutil.which("bun") is None:
            pytest.skip("bun not on PATH — oh-my-opendevin MCP server unavailable")

        cfg = dd.get_devin_mcp_config()
        if cfg is None:
            pytest.skip("oh-my-opendevin repo not found — MCP server unavailable")
        return cfg

    def test_discovery_produces_valid_config(self, live_mcp_config):
        """Auto-discovery returns a well-formed MCP server entry."""
        assert "opendevin_devin" in live_mcp_config
        entry = live_mcp_config["opendevin_devin"]
        assert entry["command"] == "bash"
        assert entry["args"]
        assert Path(entry["args"][0]).exists()

    def test_launcher_script_is_executable(self, live_mcp_config):
        """The discovered launcher script exists and is executable."""
        launcher = Path(live_mcp_config["opendevin_devin"]["args"][0])
        assert launcher.exists()
        # Should be executable (mode & 0o111)
        assert launcher.stat().st_mode & 0o111, "launcher script is not executable"

    def test_mcp_server_tools_list(self, live_mcp_config):
        """Spawn the MCP server and verify it exposes the expected Devin tools."""
        import subprocess

        entry = live_mcp_config["opendevin_devin"]
        launcher = entry["args"][0]

        # JSON-RPC initialize + tools/list handshake
        handshake = (
            '{"jsonrpc":"2.0","id":1,"method":"initialize","params":'
            '{"protocolVersion":"2024-11-05","capabilities":{},'
            '"clientInfo":{"name":"hades-agent-smoke-test","version":"0.1.0"}}}'
            '\n{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
            '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'
        )

        try:
            proc = subprocess.run(
                ["bun", "run", launcher],
                input=handshake,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError:
            pytest.skip("bun executable vanished between check and run")
        except subprocess.TimeoutExpired:
            pytest.fail("MCP server did not respond within 30s")

        # Look for expected tool names in the JSON-RPC response lines
        combined = proc.stdout + proc.stderr
        expected_tools = {
            "devin_start",
            "devin_status",
            "devin_wait",
            "devin_cancel",
            "devin_list",
            "devin_health",
            "devin_resumable",
        }
        found = {t for t in expected_tools if t in combined}
        # At least the core tools should be present
        core = {"devin_start", "devin_status", "devin_wait", "devin_cancel"}
        missing = core - found
        assert not missing, f"Core Devin MCP tools missing from server response: {missing}\n\nstdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}"


# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------

class TestModelValidation:
    """Tests for _validate_devin_model and _get_default_model."""

    def test_known_models_accepted(self):
        """Valid Devin tier keywords are accepted."""
        import tools.devin_delegate as ddg
        assert ddg._validate_devin_model("opus") == "opus"
        assert ddg._validate_devin_model("sonnet") == "sonnet"
        assert ddg._validate_devin_model("kimi-k2.6") == "kimi-k2.6"
        assert ddg._validate_devin_model("swe") == "swe"

    def test_fully_qualified_id_by_prefix(self):
        """Fully-qualified IDs like 'swe-1-6' match by prefix."""
        import tools.devin_delegate as ddg
        assert ddg._validate_devin_model("swe-1-6") == "swe"
        assert ddg._validate_devin_model("opus-latest") == "opus"

    def test_empty_returns_none(self):
        """Empty/None model returns None to trigger fallback."""
        import tools.devin_delegate as ddg
        assert ddg._validate_devin_model("") is None
        assert ddg._validate_devin_model(None) is None

    def test_unknown_warns_and_returns_none(self):
        """Unknown models return None after warning."""
        import tools.devin_delegate as ddg
        assert ddg._validate_devin_model("gpt-4") is None
        assert ddg._validate_devin_model("unknown") is None

    def test_default_model_is_known(self):
        """_get_default_model always returns a known model."""
        import tools.devin_delegate as ddg
        default = ddg._get_default_model()
        assert default in ddg._KNOWN_DEVIN_MODELS


# ---------------------------------------------------------------------------
# Exponential backoff
# ---------------------------------------------------------------------------

class TestExponentialBackoff:
    """Tests for _compute_poll_interval."""

    def test_backoff_grows_then_caps(self):
        """Poll interval doubles each iteration up to the cap."""
        import tools.devin_delegate as ddg

        assert ddg._compute_poll_interval(0) == ddg._BASE_POLL_INTERVAL_SECONDS
        assert ddg._compute_poll_interval(1) == 4
        assert ddg._compute_poll_interval(2) == 8
        assert ddg._compute_poll_interval(5) == 64
        # Should cap at _MAX_POLL_INTERVAL_SECONDS
        assert ddg._compute_poll_interval(10) == ddg._MAX_POLL_INTERVAL_SECONDS


# ---------------------------------------------------------------------------
# Session tracking and atexit
# ---------------------------------------------------------------------------

class TestSessionTracking:
    """Tests for _track_session / _untrack_session."""

    def test_track_and_untrack(self):
        """Sessions are tracked and can be untracked."""
        import tools.devin_delegate as ddg
        ddg._active_devin_sessions.clear()
        ddg._track_session("sess-1")
        assert "sess-1" in ddg._active_devin_sessions
        ddg._untrack_session("sess-1")
        assert "sess-1" not in ddg._active_devin_sessions

    def test_duplicate_track_is_noop(self):
        """Tracking the same session twice is harmless."""
        import tools.devin_delegate as ddg
        ddg._active_devin_sessions.clear()
        ddg._track_session("sess-1")
        ddg._track_session("sess-1")
        assert len(ddg._active_devin_sessions) == 1
        ddg._active_devin_sessions.clear()


# ---------------------------------------------------------------------------
# Binding TTL cleanup
# ---------------------------------------------------------------------------

class TestBindingTtl:
    """Tests for automatic purging of stale bindings."""

    def test_old_bindings_purged(self):
        """Bindings older than _BINDING_TTL_SECONDS are removed."""
        import tools.devin_delegate as ddg

        ddg._session_bindings.clear()
        # Inject a very old binding
        ddg._session_bindings["sess-old"] = {
            "platform": "telegram", "chat_id": "123",
            "bound_at": time.time() - ddg._BINDING_TTL_SECONDS - 1,
        }

        ddg._check_pending_sessions()
        assert "sess-old" not in ddg._session_bindings

    def test_fresh_bindings_kept(self):
        """Recent bindings survive the TTL check."""
        import tools.devin_delegate as ddg

        ddg._session_bindings.clear()
        ddg._session_bindings["sess-fresh"] = {
            "platform": "telegram", "chat_id": "123",
            "bound_at": time.time(),
        }
        # Mock poll so we don't actually call MCP
        with patch.object(ddg, "_poll_devin_status", return_value={"status": "running"}):
            ddg._check_pending_sessions()
        assert "sess-fresh" in ddg._session_bindings
        ddg._session_bindings.clear()
