#!/bin/bash
# ============================================================================
# Hermes Launcher — One-command install + run
# ============================================================================
# This script checks if Hermes is installed, installs it if missing,
# then launches the interactive CLI.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/hermes-launcher.sh | bash
#
# Or with Devin integration:
#   curl -fsSL ... | bash -s -- --with-devin
#
# Or download and run with options:
#   ./hermes-launcher.sh --with-devin
#
# ============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
INSTALL_DIR="$HERMES_HOME/hermes-agent"
REPO_URL="https://github.com/NousResearch/hermes-agent.git"
INSTALL_SCRIPT_URL="https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh"

# Options
WITH_DEVIN=false
SKIP_INSTALL=false
BRANCH="main"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --with-devin)
            WITH_DEVIN=true
            shift
            ;;
        --skip-install)
            SKIP_INSTALL=true
            shift
            ;;
        --branch)
            BRANCH="$2"
            shift 2
            ;;
        -h|--help)
            echo "Hermes Launcher — Install and run in one command"
            echo ""
            echo "Usage: hermes-launcher.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --with-devin   Install with Devin CLI bidirectional integration"
            echo "  --skip-install   Skip installation check (just launch if exists)"
            echo "  --branch NAME    Git branch to install (default: main)"
            echo "  -h, --help       Show this help"
            echo ""
            echo "Examples:"
            echo "  hermes-launcher.sh                          # Basic install + run"
            echo "  hermes-launcher.sh --with-devin             # With Devin integration"
            echo "  hermes-launcher.sh --skip-install           # Just launch if installed"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

log_info() { echo -e "${BLUE}→${NC} $1"; }
log_success() { echo -e "${GREEN}✓${NC} $1"; }
log_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
log_error() { echo -e "${RED}✗${NC} $1"; }

# Check if hermes is already installed and available
hermes_exists() {
    if command -v hermes &> /dev/null; then
        return 0
    fi
    # Check if entrypoint exists in expected location
    if [ -x "$INSTALL_DIR/.venv/bin/hermes" ] || [ -x "$INSTALL_DIR/venv/bin/hermes" ]; then
        return 0
    fi
    return 1
}

# Check if installation directory exists with venv
installation_present() {
    if [ -d "$INSTALL_DIR/.venv" ] || [ -d "$INSTALL_DIR/venv" ]; then
        return 0
    fi
    return 1
}

# Run the installer
run_installer() {
    log_info "Hermes not found. Starting installation..."
    echo ""

    # Build install arguments
    install_args=""
    if [ "$WITH_DEVIN" = true ]; then
        install_args="$install_args --with-devin"
    fi
    if [ "$BRANCH" != "main" ]; then
        install_args="$install_args --branch $BRANCH"
    fi

    # Download and run the official installer
    if command -v curl &> /dev/null; then
        log_info "Downloading installer..."
        # shellcheck disable=SC2086
        if ! curl -fsSL "$INSTALL_SCRIPT_URL" | bash -s -- $install_args; then
            log_error "Installation failed."
            echo ""
            echo "You can install manually:"
            echo "  git clone $REPO_URL $INSTALL_DIR"
            echo "  cd $INSTALL_DIR"
            echo "  ./setup-hermes.sh"
            exit 1
        fi
    else
        log_error "curl not found. Please install curl and retry."
        exit 1
    fi

    log_success "Installation complete!"
    echo ""
}

# Activate venv and launch hermes
launch_hermes() {
    # Find the correct venv
    VENV_DIR=""
    if [ -d "$INSTALL_DIR/.venv" ]; then
        VENV_DIR="$INSTALL_DIR/.venv"
    elif [ -d "$INSTALL_DIR/venv" ]; then
        VENV_DIR="$INSTALL_DIR/venv"
    fi

    if [ -z "$VENV_DIR" ]; then
        log_error "Could not find virtual environment in $INSTALL_DIR"
        exit 1
    fi

    # Check if hermes binary exists
    HERMES_BIN=""
    if [ -x "$VENV_DIR/bin/hermes" ]; then
        HERMES_BIN="$VENV_DIR/bin/hermes"
    elif command -v hermes &> /dev/null; then
        HERMES_BIN="$(command -v hermes)"
    fi

    if [ -z "$HERMES_BIN" ]; then
        log_error "hermes command not found after installation."
        exit 1
    fi

    log_info "Launching Hermes..."
    echo ""

    # Export venv python/pip paths for any subprocesses
    export PATH="$VENV_DIR/bin:$PATH"

    # Launch hermes. Use exec so this script is replaced by hermes,
    # ensuring signals (Ctrl+C) go directly to hermes.
    exec "$HERMES_BIN" "$@"
}

# Main
main() {
    echo ""
    echo -e "${CYAN}${BOLD}⚕ Hermes Launcher${NC}"
    echo ""

    if [ "$SKIP_INSTALL" = true ]; then
        if ! hermes_exists && ! installation_present; then
            log_error "Hermes not found and --skip-install is set."
            exit 1
        fi
        log_info "Skipping installation check (--skip-install)"
    else
        if hermes_exists || installation_present; then
            log_info "Hermes already installed"
        else
            run_installer
        fi
    fi

    # Source shell config if hermes still not on PATH (fresh install)
    if ! command -v hermes &> /dev/null && [ -f "$HOME/.bashrc" ]; then
        # shellcheck source=/dev/null
        source "$HOME/.bashrc" 2>/dev/null || true
    fi
    if ! command -v hermes &> /dev/null && [ -f "$HOME/.zshrc" ]; then
        # shellcheck source=/dev/null
        source "$HOME/.zshrc" 2>/dev/null || true
    fi

    launch_hermes "$@"
}

main "$@"
