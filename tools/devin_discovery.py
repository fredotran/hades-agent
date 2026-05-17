"""Auto-discovery of oh-my-opendevin Devin MCP server.

Searches for the oh-my-opendevin repository in common locations, validates that
it contains a working Devin MCP server, and produces an MCP server config entry
that can be fed into register_mcp_servers().

Discovery order:
  1. OH_MY_OPENDEVIN_PATH environment variable
  2. Common known paths (~/Code/oh-my-opendevin, etc.)
  3. Walk up from the current working directory

Cached per-process so repeated calls are cheap.
"""

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Cache: None = not searched yet, "" = searched but not found
_discovered_repo: Optional[str] = None

# Directories to check as absolute/relative candidates.
_SEARCH_PATHS = [
    "~/Code/oh-my-opendevin",
    "~/oh-my-opendevin",
    "~/repos/oh-my-opendevin",
    "~/src/oh-my-opendevin",
    "~/projects/oh-my-opendevin",
    "~/workspace/oh-my-opendevin",
    "~/dev/oh-my-opendevin",
    "~/Development/oh-my-opendevin",
    "~/devin/oh-my-opendevin",
    "~/work/oh-my-opendevin",
    "~/Documents/oh-my-opendevin",
    "~/Dropbox/oh-my-opendevin",
    "~/github/oh-my-opendevin",
    "~/git/oh-my-opendevin",
    "~/gitlab/oh-my-opendevin",
    "~/bitbucket/oh-my-opendevin",
    "~/tools/oh-my-opendevin",
    "~/opt/oh-my-opendevin",
]

# Marker files that prove a checkout has the Devin MCP server
_REQUIRED_MARKER_FILES = [
    "src/mcp-servers/devin/index.ts",
    "bin/devin-mcp-launcher.sh",
]


def _is_valid_repo(path: Path) -> bool:
    """Return True when *path* looks like an oh-my-opendevin checkout with the
    Devin MCP server intact."""
    if not path.is_dir():
        return False
    return all((path / rel).exists() for rel in _REQUIRED_MARKER_FILES)


def discover_opendevin_repo() -> Optional[str]:
    """Find the oh-my-opendevin repository path, or None if not found.

    Results are cached for the lifetime of the process.
    """
    global _discovered_repo
    if _discovered_repo is not None:
        return _discovered_repo or None

    # 1. Environment variable
    env_path = os.environ.get("OH_MY_OPENDEVIN_PATH", "").strip()
    if env_path:
        candidate = Path(env_path).expanduser().resolve()
        if _is_valid_repo(candidate):
            _discovered_repo = str(candidate)
            logger.info("Discovered oh-my-opendevin via OH_MY_OPENDEVIN_PATH: %s", _discovered_repo)
            return _discovered_repo
        logger.warning(
            "OH_MY_OPENDEVIN_PATH=%s does not point to a valid oh-my-opendevin checkout", env_path
        )

    # 2. Known paths
    for sp in _SEARCH_PATHS:
        candidate = Path(sp).expanduser().resolve()
        if _is_valid_repo(candidate):
            _discovered_repo = str(candidate)
            logger.info("Discovered oh-my-opendevin at known path: %s", _discovered_repo)
            return _discovered_repo

    # 3. Walk up from cwd
    try:
        cwd = Path.cwd().resolve()
        for parent in [cwd, *list(cwd.parents)[:5]]:
            candidate = parent / "oh-my-opendevin"
            if _is_valid_repo(candidate):
                _discovered_repo = str(candidate)
                logger.info("Discovered oh-my-opendevin walking up from cwd: %s", _discovered_repo)
                return _discovered_repo
    except Exception as exc:
        logger.debug("Walking up from cwd failed: %s", exc)

    _discovered_repo = ""
    logger.debug("oh-my-opendevin repo not found")
    
    # Emit helpful warning if devin toolset is enabled but repo not found
    try:
        from hermes_cli.config import get_config_path
        cfg_path = get_config_path()
        if cfg_path.exists():
            import yaml
            with open(cfg_path, encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            enabled_toolsets = config.get("enabled_toolsets", [])
            if "devin" in enabled_toolsets:
                logger.warning(
                    "Devin toolset is enabled but oh-my-opendevin repo not found. "
                    "Set OH_MY_OPENDEVIN_PATH environment variable or clone to one of: %s",
                    ", ".join(_SEARCH_PATHS[:3])
                )
    except Exception as exc:
        logger.debug("Could not check if devin toolset is enabled: %s", exc)
    
    return None


def _check_bun_available() -> bool:
    """Return True when the ``bun`` binary is on PATH."""
    return shutil.which("bun") is not None


def get_devin_mcp_config() -> Optional[Dict[str, dict]]:
    """Return an MCP server config dict for the discovered Devin server.

    Format::

        {"opendevin_devin": {"command": "bash", "args": [...], ...}}

    Returns None when the repo is not found or ``bun`` is missing.
    """
    repo = discover_opendevin_repo()
    if not repo:
        return None

    launcher = Path(repo) / "bin" / "devin-mcp-launcher.sh"
    if not launcher.exists():
        logger.debug("devin-mcp-launcher.sh missing in %s", repo)
        return None

    if not _check_bun_available():
        logger.warning(
            "oh-my-opendevin found at %s but `bun` is not on PATH. "
            "Install Bun (https://bun.sh) to use the Devin MCP server.",
            repo,
        )
        return None

    # Check for version compatibility
    check_version_compatibility(repo)

    return {
        "opendevin_devin": {
            "command": "bash",
            "args": [str(launcher)],
            "env": {},
            "connect_timeout": 30,
            "timeout": 120,
        }
    }


def _get_hermes_version() -> Optional[str]:
    """Get the current Hermes version from git or package metadata."""
    try:
        # Try git first (development environment)
        result = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass
    
    try:
        # Try package metadata
        import importlib.metadata
        return importlib.metadata.version("hermes-agent")
    except Exception:
        pass
    
    return None


def _get_opendevin_version(repo_path: str) -> Optional[str]:
    """Get the oh-my-opendevin version from package.json or git."""
    repo = Path(repo_path)
    
    # Try package.json first
    package_json = repo / "package.json"
    if package_json.exists():
        try:
            import json
            with open(package_json, encoding="utf-8") as f:
                data = json.load(f)
            return data.get("version")
        except Exception:
            pass
    
    # Try git
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass
    
    return None


def check_version_compatibility(repo_path: str) -> None:
    """Check for version compatibility between Hermes and oh-my-opendevin.
    
    Emits a warning if versions appear to be significantly mismatched.
    This is a best-effort check - it won't prevent usage, just warn.
    """
    hermes_version = _get_hermes_version()
    opendevin_version = _get_opendevin_version(repo_path)
    
    if not hermes_version or not opendevin_version:
        # Can't check if we can't get versions
        return
    
    logger.info(
        "Version check: Hermes=%s, oh-my-opendevin=%s",
        hermes_version, opendevin_version
    )
    
    # Extract major/minor versions for comparison
    # Handle both semver (1.2.3) and git describe (v1.2.3-5-gabcdef)
    hermes_match = re.search(r'(\d+)\.(\d+)', hermes_version)
    opendevin_match = re.search(r'(\d+)\.(\d+)', opendevin_version)
    
    if not hermes_match or not opendevin_match:
        return
    
    hermes_major = int(hermes_match.group(1))
    hermes_minor = int(hermes_match.group(2))
    opendevin_major = int(opendevin_match.group(1))
    opendevin_minor = int(opendevin_match.group(2))
    
    # Warn if major versions differ significantly (more than 1 version apart)
    if abs(hermes_major - opendevin_major) > 1:
        logger.warning(
            "Potential version mismatch: Hermes major version %d vs oh-my-opendevin major version %d. "
            "This may cause compatibility issues. Consider updating to compatible versions.",
            hermes_major, opendevin_major
        )
    elif hermes_major != opendevin_major and abs(hermes_minor - opendevin_minor) > 5:
        # Different major versions or significantly different minor versions
        logger.warning(
            "Potential version mismatch: Hermes %s vs oh-my-opendevin %s. "
            "This may cause compatibility issues. Consider updating to compatible versions.",
            hermes_version, opendevin_version
        )
