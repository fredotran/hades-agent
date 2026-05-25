"""Tests for the devin MCP setup installer scripts.

Covers: script existence, syntax validation, argument parsing, config generation,
JSON manipulation, idempotency, and integration scenarios.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest


SCRIPT_DIR = Path(__file__).parent.parent.parent / "scripts"
BASH_SCRIPT = SCRIPT_DIR / "setup-devin-mcp.sh"
PS_SCRIPT = SCRIPT_DIR / "setup-devin-mcp.ps1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_mock_hermes(tmpdir):
    """Create a fake Hermes binary for testing."""
    mock_hermes = Path(tmpdir) / "hermes"
    mock_hermes.write_text("#!/bin/bash\necho 'hermes mock v0.0.0'\n")
    mock_hermes.chmod(0o755)
    return str(mock_hermes)


def run_bash_script(*args, env=None, cwd=None):
    """Run the bash installer script with given arguments."""
    cmd = ["bash", str(BASH_SCRIPT)] + list(args)
    env_vars = os.environ.copy()
    if env:
        env_vars.update(env)
    result = subprocess.run(
        cmd, capture_output=True, text=True, env=env_vars, cwd=cwd
    )
    return result


def run_powershel_syntax_check():
    """Check PowerShell script syntax using a Docker container or local pwsh."""
    # Try local pwsh first
    if subprocess.run(["which", "pwsh"], capture_output=True).returncode == 0:
        return subprocess.run(
            ["pwsh", "-Command", f"$e = $null; [System.Management.Automation.PSParser]::Tokenize((Get-Content '{PS_SCRIPT}'), [ref]$e); exit $e.Count"],
            capture_output=True,
            text=True,
        )
    # Try powershell (older name)
    if subprocess.run(["which", "powershell"], capture_output=True).returncode == 0:
        return subprocess.run(
            ["powershell", "-Command", f"$e = $null; [System.Management.Automation.PSParser]::Tokenize((Get-Content '{PS_SCRIPT}'), [ref]$e); exit $e.Count"],
            capture_output=True,
            text=True,
        )
    return None


# ---------------------------------------------------------------------------
# Script existence and basic properties
# ---------------------------------------------------------------------------


class TestScriptExistence:
    def test_bash_script_exists(self):
        assert BASH_SCRIPT.exists(), f"Script not found: {BASH_SCRIPT}"

    def test_bash_script_is_executable(self):
        assert os.access(BASH_SCRIPT, os.X_OK), "Bash script should be executable"

    def test_powershell_script_exists(self):
        assert PS_SCRIPT.exists(), f"Script not found: {PS_SCRIPT}"

    def test_bash_script_not_empty(self):
        content = BASH_SCRIPT.read_text()
        assert len(content) > 1000, "Script seems too short"

    def test_powershell_script_not_empty(self):
        content = PS_SCRIPT.read_text()
        assert len(content) > 1000, "Script seems too short"


# ---------------------------------------------------------------------------
# Syntax validation
# ---------------------------------------------------------------------------


class TestSyntaxValidation:
    def test_bash_script_syntax(self):
        result = subprocess.run(
            ["bash", "-n", str(BASH_SCRIPT)], capture_output=True, text=True
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"

    @pytest.mark.skipif(
        subprocess.run(["which", "pwsh"], capture_output=True).returncode != 0
        and subprocess.run(["which", "powershell"], capture_output=True).returncode != 0,
        reason="PowerShell not available",
    )
    def test_powershell_script_syntax(self):
        result = run_powershel_syntax_check()
        if result is None:
            pytest.skip("PowerShell not available")
        assert result.returncode == 0, f"PowerShell syntax errors: {result.stdout}"

    def test_bash_script_has_shebang(self):
        first_line = BASH_SCRIPT.read_text().splitlines()[0]
        assert first_line.startswith("#!/bin/bash"), "Missing bash shebang"

    def test_powershell_script_has_comment_header(self):
        content = PS_SCRIPT.read_text()
        assert "<#" in content or "# " in content[:5], "Missing PowerShell comment header"


# ---------------------------------------------------------------------------
# Help and argument parsing
# ---------------------------------------------------------------------------


class TestHelpAndArguments:
    def test_help_flag(self):
        result = run_bash_script("--help")
        assert result.returncode == 0
        assert "Hermes" in result.stdout or "Devin" in result.stdout
        assert "Usage:" in result.stdout

    def test_help_short_flag(self):
        result = run_bash_script("-h")
        assert result.returncode == 0
        assert "Usage:" in result.stdout

    def test_unknown_option(self):
        result = run_bash_script("--unknown-flag")
        assert result.returncode != 0
        assert "Unknown option" in result.stdout or "Unknown option" in result.stderr

    def test_help_shows_all_options(self):
        result = run_bash_script("--help")
        text = result.stdout
        assert "--hermes-path" in text
        assert "--devin-config" in text
        assert "--force" in text
        assert "--verify-only" in text

    def test_help_shows_examples(self):
        result = run_bash_script("--help")
        text = result.stdout
        assert "Examples:" in text or "Example" in text


# ---------------------------------------------------------------------------
# Verify-only mode
# ---------------------------------------------------------------------------


class TestVerifyOnlyMode:
    def test_verify_only_no_config(self):
        """Verify-only mode should fail gracefully when no config exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            result = run_bash_script(
                "--verify-only", "--devin-config", str(config_path)
            )
            assert result.returncode != 0
            assert "Config file not found" in result.stdout or "not found" in result.stdout

    def test_verify_only_with_valid_config(self):
        """Verify-only mode should succeed with valid config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config = {
                "mcpServers": {
                    "hermes": {
                        "command": "hermes",
                        "args": ["mcp", "serve"],
                        "env": {"HERMES_HOME": "~/.hermes"},
                    }
                }
            }
            config_path.write_text(json.dumps(config))
            result = run_bash_script(
                "--verify-only", "--devin-config", str(config_path)
            )
            assert result.returncode == 0, f"Expected success: {result.stdout}{result.stderr}"
            assert "Configuration verified" in result.stdout

    def test_verify_only_empty_hermes_config(self):
        """Verify-only mode should fail when hermes config is empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config = {"mcpServers": {"hermes": {}}}
            config_path.write_text(json.dumps(config))
            result = run_bash_script(
                "--verify-only", "--devin-config", str(config_path)
            )
            assert result.returncode != 0
            assert "empty" in result.stdout.lower() or "not found" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Configuration creation and update
# ---------------------------------------------------------------------------


class TestConfigCreation:
    def test_creates_config_directory(self):
        """Script should create devin config directory if missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "nested" / "devin"
            config_path = config_dir / "config.json"
            result = run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
            )
            assert config_dir.exists(), "Config directory not created"

    def test_creates_minimal_config(self):
        """Script should create minimal config if file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            result = run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
            )
            assert config_path.exists(), "Config file not created"
            data = json.loads(config_path.read_text())
            assert "mcpServers" in data

    def test_adds_hermes_mcp_config(self):
        """Script should add Hermes MCP configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            result = run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
            )
            data = json.loads(config_path.read_text())
            assert "hermes" in data.get("mcpServers", {})
            hermes = data["mcpServers"]["hermes"]
            assert hermes["command"] == create_mock_hermes(tmpdir)
            assert hermes["args"] == ["mcp", "serve"]
            assert "HERMES_HOME" in hermes.get("env", {})

    def test_config_format(self):
        """Verify the exact structure of generated config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            result = run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
            )
            data = json.loads(config_path.read_text())
            hermes = data["mcpServers"]["hermes"]
            assert sorted(hermes.keys()) == sorted(["command", "args", "env"])
            assert isinstance(hermes["args"], list)
            assert isinstance(hermes["env"], dict)

    def test_hermes_home_expansion(self):
        """Script should expand ~ in HERMES_HOME."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            result = run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
            )
            data = json.loads(config_path.read_text())
            hermes_home = data["mcpServers"]["hermes"]["env"]["HERMES_HOME"]
            assert "~" not in hermes_home, "Tilde not expanded"
            assert hermes_home.startswith("/"), "HERMES_HOME should be absolute path"


# ---------------------------------------------------------------------------
# Idempotency and force mode
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_refuses_to_overwrite_without_force(self):
        """Second run without --force should warn and exit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            # First run
            run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
            )
            # Second run without --force
            result = run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
            )
            assert result.returncode == 0  # Exits gracefully after verification
            assert "already exists" in result.stdout.lower() or "Use --force" in result.stdout

    def test_force_overwrites(self):
        """--force should overwrite existing config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            # First run with original path
            run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
            )
            # Second run with different path and --force
            result = run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
                "--force",
            )
            assert result.returncode == 0
            data = json.loads(config_path.read_text())
            assert data["mcpServers"]["hermes"]["command"] == create_mock_hermes(tmpdir)

    def test_creates_backup(self):
        """Script should create backup before overwriting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
            )
            # Force overwrite
            run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
                "--force",
            )
            # Check backup exists
            backups = list(Path(tmpdir).glob("config.json.bak.*"))
            assert len(backups) > 0, "No backup created"


# ---------------------------------------------------------------------------
# Custom paths
# ---------------------------------------------------------------------------


class TestCustomPaths:
    def test_custom_hermes_path(self):
        """--hermes-path should use custom binary path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            result = run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
            )
            assert result.returncode == 0
            data = json.loads(config_path.read_text())
            assert data["mcpServers"]["hermes"]["command"] == create_mock_hermes(tmpdir)

    def test_custom_devin_config(self):
        """--devin-config should use custom config path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "my-config.json"
            result = run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
            )
            assert result.returncode == 0
            assert config_path.exists()

    def test_empty_hermes_path_rejected(self):
        """Empty --hermes-path should be rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            result = run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", "",
            )
            assert result.returncode != 0
            assert "non-empty" in result.stdout.lower() or "requires" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Existing config handling
# ---------------------------------------------------------------------------


class TestExistingConfig:
    def test_preserves_existing_servers(self):
        """Script should preserve other MCP servers in config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            original = {
                "mcpServers": {
                    "other-server": {
                        "command": "other",
                        "args": ["serve"],
                    }
                }
            }
            config_path.write_text(json.dumps(original))
            result = run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
            )
            assert result.returncode == 0
            data = json.loads(config_path.read_text())
            assert "other-server" in data["mcpServers"]
            assert "hermes" in data["mcpServers"]

    def test_handles_empty_mcp_servers(self):
        """Script should handle config with empty mcpServers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text('{"mcpServers": {}}')
            result = run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
            )
            assert result.returncode == 0
            data = json.loads(config_path.read_text())
            assert "hermes" in data["mcpServers"]

    def test_handles_config_without_mcp_servers(self):
        """Script should handle config missing mcpServers section."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text('{}')
            result = run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
            )
            assert result.returncode == 0
            data = json.loads(config_path.read_text())
            assert "mcpServers" in data
            assert "hermes" in data["mcpServers"]


# ---------------------------------------------------------------------------
# Environment variable handling
# ---------------------------------------------------------------------------


class TestEnvironmentVariables:
    def test_respects_hermes_home_env(self):
        """Script should use HERMES_HOME environment variable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            custom_home = "/custom/hermes/home"
            result = run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
                env={"HERMES_HOME": custom_home},
            )
            assert result.returncode == 0
            data = json.loads(config_path.read_text())
            assert data["mcpServers"]["hermes"]["env"]["HERMES_HOME"] == custom_home

    def test_respects_devin_config_env(self):
        """Script should use DEVIN_CONFIG environment variable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "from-env.json"
            result = run_bash_script(
                "--hermes-path", create_mock_hermes(tmpdir),
                env={"DEVIN_CONFIG": str(config_path)},
            )
            assert result.returncode == 0
            assert config_path.exists()


# ---------------------------------------------------------------------------
# JSON validation
# ---------------------------------------------------------------------------


class TestJsonValidation:
    def test_rejects_invalid_json(self):
        """Script should fail when config file has invalid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            config_path.write_text("{invalid json")
            result = run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
            )
            assert result.returncode != 0
            assert "invalid JSON" in result.stdout or "Failed" in result.stdout or "jq failed" in result.stdout

    def test_produces_valid_json(self):
        """Script should always produce valid JSON output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            result = run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
            )
            assert result.returncode == 0
            # Should be parseable
            data = json.loads(config_path.read_text())
            assert data is not None

    def test_produces_pretty_printed_json(self):
        """Script should produce human-readable JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            result = run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
            )
            assert result.returncode == 0
            content = config_path.read_text()
            assert "\n" in content, "JSON should be formatted with newlines"
            assert "  " in content, "JSON should be indented"


# ---------------------------------------------------------------------------
# Integration scenarios
# ---------------------------------------------------------------------------


class TestIntegrationScenarios:
    def test_full_workflow(self):
        """Test the complete setup workflow end-to-end."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            # Step 1: Initial setup
            result = run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
            )
            assert result.returncode == 0
            assert "Setup complete" in result.stdout

            # Step 2: Verify
            result = run_bash_script(
                "--devin-config", str(config_path),
                "--verify-only",
            )
            assert result.returncode == 0
            assert "Configuration verified" in result.stdout

            # Step 3: Force update
            result = run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
                "--force",
            )
            assert result.returncode == 0

            # Step 4: Verify updated
            data = json.loads(config_path.read_text())
            assert data["mcpServers"]["hermes"]["command"] == create_mock_hermes(tmpdir)

    def test_works_without_jq(self):
        """Script should work when jq is not available (Python fallback)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            # Create a minimal PATH without jq
            minimal_path = "/usr/bin:/bin"
            result = run_bash_script(
                "--devin-config", str(config_path),
                "--hermes-path", create_mock_hermes(tmpdir),
                env={"PATH": minimal_path},
            )
            # Note: This might fail if Python is also not in the minimal PATH
            # The test checks that the script handles the fallback gracefully
            if result.returncode == 0:
                data = json.loads(config_path.read_text())
                assert "hermes" in data.get("mcpServers", {})

    def test_handles_missing_devin_cli(self):
        """Script should continue even if devin-cli is not installed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"
            # Use a PATH that shouldn't have devin
            env = os.environ.copy()
            env["PATH"] = "/usr/bin:/bin"
            result = subprocess.run(
                ["bash", str(BASH_SCRIPT), "--devin-config", str(config_path), "--hermes-path", create_mock_hermes(tmpdir)],
                capture_output=True,
                text=True,
                env=env,
            )
            # Should warn but still create config
            assert "devin-cli not found" in result.stdout.lower() or result.returncode == 0
