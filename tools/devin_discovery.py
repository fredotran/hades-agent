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
import shutil
from pathlib import Path
from typing import Dict, Optional

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

    return {
        "opendevin_devin": {
            "command": "bash",
            "args": [str(launcher)],
            "env": {},
            "connect_timeout": 30,
            "timeout": 120,
        }
    }
