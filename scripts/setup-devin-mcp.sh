#!/bin/bash
# ============================================================================
# Hermes Agent — Devin MCP Server Setup
# ============================================================================
# One-line installer that configures Hermes Agent as an MCP server in
# devin-cli.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/setup-devin-mcp.sh | bash
#
# Or with options:
#   curl -fsSL ... | bash -s -- --hermes-path /usr/local/bin/hermes --force
#
# ============================================================================

set -euo pipefail

# Colors (only if stdout is a TTY)
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[0;33m'
    BLUE='\033[0;34m'
    CYAN='\033[0;36m'
    NC='\033[0m'
    BOLD='\033[1m'
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    CYAN=''
    NC=''
    BOLD=''
fi

# Defaults
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
DEVIN_CONFIG_DIR="${DEVIN_CONFIG_DIR:-$HOME/.devin}"
DEVIN_CONFIG="${DEVIN_CONFIG:-$DEVIN_CONFIG_DIR/config.json}"
HERMES_CMD=""
FORCE=false
VERIFY_ONLY=false

# Log functions
log_info() {
    echo -e "${CYAN}→${NC} $1"
}

log_success() {
    echo -e "${GREEN}✓${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

log_error() {
    echo -e "${RED}✗${NC} $1"
}

# Print help
print_help() {
    cat <<EOF
Hermes Agent — Devin MCP Server Setup

Usage: setup-devin-mcp.sh [OPTIONS]

Options:
  --hermes-path PATH   Custom path to Hermes binary
  --devin-config PATH  Custom path to devin config.json
                       (default: ~/.devin/config.json)
  --force              Overwrite existing Hermes MCP configuration
  --verify-only        Only verify existing configuration
  -h, --help           Show this help

Examples:
  setup-devin-mcp.sh                      # Basic setup
  setup-devin-mcp.sh --force              # Overwrite existing config
  setup-devin-mcp.sh --verify-only       # Verify without modifying
  setup-devin-mcp.sh --hermes-path /opt/hermes/bin/hermes
EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --hermes-path)
            HERMES_CMD="$2"
            if [ -z "$HERMES_CMD" ]; then
                log_error "--hermes-path requires a non-empty path"
                exit 1
            fi
            shift 2
            ;;
        --devin-config)
            DEVIN_CONFIG="$2"
            shift 2
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --verify-only)
            VERIFY_ONLY=true
            shift
            ;;
        -h|--help)
            print_help
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            print_help
            exit 1
            ;;
    esac
done

# Resolve Hermes binary path
resolve_hermes() {
    if [ -n "$HERMES_CMD" ]; then
        if [ -x "$HERMES_CMD" ]; then
            log_success "Using Hermes binary: $HERMES_CMD"
            return 0
        else
            log_error "Hermes binary not found or not executable: $HERMES_CMD"
            exit 1
        fi
    fi

    if command -v hermes &> /dev/null; then
        HERMES_CMD="$(command -v hermes)"
        log_success "Hermes found on PATH: $HERMES_CMD"
        return 0
    fi

    # Check common install locations
    for path in "$HOME/.local/bin/hermes" "/usr/local/bin/hermes" "$HERMES_HOME/hermes-agent/.venv/bin/hermes" "$HERMES_HOME/hermes-agent/venv/bin/hermes"; do
        if [ -x "$path" ]; then
            HERMES_CMD="$path"
            log_success "Hermes found: $HERMES_CMD"
            return 0
        fi
    done

    log_error "Hermes not found. Please install Hermes or specify --hermes-path"
    exit 1
}

# Check if devin-cli is installed
check_devin() {
    log_info "Checking devin-cli..."

    if command -v devin &> /dev/null; then
        log_success "devin-cli found: $(command -v devin)"
        return 0
    fi

    if command -v devin-cli &> /dev/null; then
        log_success "devin-cli found: $(command -v devin-cli)"
        return 0
    fi

    log_warn "devin-cli not found on PATH"
    log_info "  You can install it with: pip install devin-cli"
    log_info "  Continuing anyway — configuration will be written for when devin-cli is installed"
}

# Check for jq (optional but preferred)
check_jq() {
    if command -v jq &> /dev/null; then
        log_success "jq found — using for JSON manipulation"
        HAS_JQ=true
    else
        log_warn "jq not found — falling back to Python for JSON manipulation"
        HAS_JQ=false
        if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
            log_error "Neither jq nor python found. Install jq or Python to proceed."
            exit 1
        fi
    fi
}

# Determine Python command for JSON fallback
python_cmd() {
    if command -v python3 &> /dev/null; then
        echo "python3"
    else
        echo "python"
    fi
}

# Read a JSON value using jq or python fallback
json_read() {
    local file="$1"
    local key="$2"

    if [ "$HAS_JQ" = true ]; then
        jq -r "$key" "$file" 2>/dev/null || true
    else
        local py_cmd
        py_cmd="$(python_cmd)"
        # Pass variables via env to avoid shell injection
        PYTHON_JSON_FILE="$file" PYTHON_JSON_KEY="$key" "$py_cmd" -c '
import json, sys, os
try:
    file_path = os.environ["PYTHON_JSON_FILE"]
    key_path = os.environ["PYTHON_JSON_KEY"]
    with open(file_path) as f:
        data = json.load(f)
    keys = key_path.split(".")
    for k in keys:
        if k == "":
            break
        if isinstance(data, dict):
            data = data.get(k, None)
        else:
            data = None
        if data is None:
            break
    print(json.dumps(data) if data is not None else "null")
except Exception:
    print("null")
' 2>/dev/null || true
    fi
}

# Check if Hermes MCP configuration already exists
has_hermes_mcp() {
    local file="$1"
    if [ ! -f "$file" ]; then
        return 1
    fi

    if [ "$HAS_JQ" = true ]; then
        jq -e '.mcpServers.hermes' "$file" &>/dev/null
    else
        local py_cmd
        py_cmd="$(python_cmd)"
        PYTHON_JSON_FILE="$file" "$py_cmd" -c '
import json, sys, os
try:
    file_path = os.environ["PYTHON_JSON_FILE"]
    with open(file_path) as f:
        data = json.load(f)
    if data.get("mcpServers", {}).get("hermes"):
        sys.exit(0)
except Exception:
    pass
sys.exit(1)
' &>/dev/null
    fi
}

# Create devin config directory if needed
ensure_devin_dir() {
    local config_dir
    config_dir="$(dirname "$DEVIN_CONFIG")"

    if [ ! -d "$config_dir" ]; then
        log_info "Creating devin config directory: $config_dir"
        mkdir -p "$config_dir"
        log_success "Created $config_dir"
    fi
}

# Create minimal devin config if it doesn't exist
create_minimal_config() {
    if [ -f "$DEVIN_CONFIG" ]; then
        log_info "Devin config exists: $DEVIN_CONFIG"
        return 0
    fi

    log_info "Creating minimal devin config: $DEVIN_CONFIG"

    cat > "$DEVIN_CONFIG" <<'EOF'
{
  "mcpServers": {}
}
EOF

    log_success "Created minimal devin config"
}

# Expand tilde in path for the JSON value
expand_home() {
    local path="$1"
    if [[ "$path" == ~* ]]; then
        echo "$HOME${path:1}"
    else
        echo "$path"
    fi
}

# Backup existing config before modification
backup_config() {
    local file="$1"
    if [ -f "$file" ]; then
        local backup_file
        backup_file="${file}.bak.$(date +%s)"
        cp "$file" "$backup_file"
        log_info "Backup created: $backup_file"
    fi
}

# Add or update Hermes MCP server configuration
update_mcp_config() {
    local file="$1"
    local hermes_path="$2"

    # Expand ~ in HERMES_HOME for the config
    local expanded_home
    expanded_home="$(expand_home "$HERMES_HOME")"

    log_info "Adding Hermes MCP server configuration..."

    # Backup existing config
    backup_config "$file"

    if [ "$HAS_JQ" = true ]; then
        # Use jq to merge the hermes MCP config
        local tmp_file
        tmp_file="$(mktemp)"
        trap 'rm -f "$tmp_file"' EXIT

        # Build the mcpServers.hermes object
        if ! jq --arg cmd "$hermes_path" \
               --arg home "$expanded_home" \
               '.mcpServers.hermes = {
                   "command": $cmd,
                   "args": ["mcp", "serve"],
                   "env": {
                       "HERMES_HOME": $home
                   }
               }' "$file" > "$tmp_file"; then
            log_error "jq failed to update config"
            exit 1
        fi

        mv "$tmp_file" "$file"
        trap - EXIT
    else
        # Python fallback - pass variables via env to avoid shell injection
        local py_cmd
        py_cmd="$(python_cmd)"
        PYTHON_JSON_FILE="$file" PYTHON_JSON_CMD="$hermes_path" PYTHON_JSON_HOME="$expanded_home" "$py_cmd" -c '
import json, os, sys

try:
    file_path = os.environ["PYTHON_JSON_FILE"]
    cmd = os.environ["PYTHON_JSON_CMD"]
    home = os.environ["PYTHON_JSON_HOME"]

    with open(file_path) as f:
        data = json.load(f)

    data.setdefault("mcpServers", {})
    data["mcpServers"]["hermes"] = {
        "command": cmd,
        "args": ["mcp", "serve"],
        "env": {
            "HERMES_HOME": home
        }
    }

    with open(file_path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
' || {
            log_error "Failed to update devin config"
            exit 1
        }
    fi

    log_success "Hermes MCP configuration updated"
}

# Verify the configuration
verify_config() {
    local file="$1"

    log_info "Verifying configuration..."

    if [ ! -f "$file" ]; then
        log_error "Config file not found: $file"
        exit 1
    fi

    # Check JSON validity
    if [ "$HAS_JQ" = true ]; then
        if ! jq empty "$file" 2>/dev/null; then
            log_error "Config file contains invalid JSON"
            exit 1
        fi
    else
        local py_cmd
        py_cmd="$(python_cmd)"
        if ! PYTHON_JSON_FILE="$file" "$py_cmd" -c '
import json, os
try:
    file_path = os.environ["PYTHON_JSON_FILE"]
    with open(file_path) as f:
        json.load(f)
except Exception:
    exit(1)
' 2>/dev/null; then
            log_error "Config file contains invalid JSON"
            exit 1
        fi
    fi

    # Check Hermes MCP section exists
    if ! has_hermes_mcp "$file"; then
        log_error "Hermes MCP configuration not found in $file"
        exit 1
    fi

    # Extract and display the hermes config
    local hermes_config
    if [ "$HAS_JQ" = true ]; then
        hermes_config="$(jq -c '.mcpServers.hermes' "$file")"
    else
        local py_cmd
        py_cmd="$(python_cmd)"
        hermes_config="$(PYTHON_JSON_FILE="$file" "$py_cmd" -c '
import json, os
try:
    file_path = os.environ["PYTHON_JSON_FILE"]
    with open(file_path) as f:
        data = json.load(f)
    print(json.dumps(data.get("mcpServers", {}).get("hermes", {})))
except Exception:
    print("null")
' 2>/dev/null)"
    fi

    if [ -z "$hermes_config" ] || [ "$hermes_config" = "null" ] || [ "$hermes_config" = "{}" ]; then
        log_error "Hermes MCP configuration is empty"
        exit 1
    fi

    log_success "Configuration verified"
    echo ""
    echo -e "${BOLD}Hermes MCP Configuration:${NC}"
    if [ "$HAS_JQ" = true ]; then
        jq '.mcpServers.hermes' "$file"
    else
        local py_cmd
        py_cmd="$(python_cmd)"
        PYTHON_JSON_FILE="$file" "$py_cmd" -c '
import json, os, sys
try:
    file_path = os.environ["PYTHON_JSON_FILE"]
    with open(file_path) as f:
        data = json.load(f)
    hermes = data.get("mcpServers", {}).get("hermes", {})
    print(json.dumps(hermes, indent=2))
except Exception as e:
    print(f"Error reading config: {e}", file=sys.stderr)
' 2>/dev/null
    fi
}

# Verify Hermes binary works
verify_hermes_binary() {
    local hermes_path="$1"

    log_info "Verifying Hermes binary..."

    if [ ! -x "$hermes_path" ]; then
        log_warn "Cannot execute Hermes binary: $hermes_path"
        return 0
    fi

    # Quick smoke test — check if hermes responds to --version or help
    if "$hermes_path" --version &>/dev/null || "$hermes_path" -h &>/dev/null; then
        log_success "Hermes binary is functional"
    else
        log_warn "Hermes binary may not be fully functional yet (this is OK for fresh installs)"
    fi
}

# Main
main() {
    echo ""
    echo -e "${CYAN}${BOLD}⚕ Hermes Agent — Devin MCP Setup${NC}"
    echo ""

    # --verify-only mode
    if [ "$VERIFY_ONLY" = true ]; then
        log_info "Running in verify-only mode"
        check_jq
        verify_config "$DEVIN_CONFIG"
        echo ""
        log_success "Verification complete — Hermes MCP is configured"
        exit 0
    fi

    # Step 1: Check dependencies
    check_devin
    resolve_hermes
    check_jq

    # Step 2: Verify Hermes binary
    verify_hermes_binary "$HERMES_CMD"

    # Step 3: Ensure devin config directory and file exist
    ensure_devin_dir

    # Step 4: Check for existing config
    if [ -f "$DEVIN_CONFIG" ]; then
        if has_hermes_mcp "$DEVIN_CONFIG"; then
            if [ "$FORCE" = true ]; then
                log_info "Overwriting existing Hermes MCP configuration (--force)"
            else
                log_warn "Hermes MCP configuration already exists"
                log_info "Use --force to overwrite, or --verify-only to check"
                echo ""
                verify_config "$DEVIN_CONFIG"
                exit 0
            fi
        fi
    else
        create_minimal_config
    fi

    # Step 5: Update MCP configuration
    update_mcp_config "$DEVIN_CONFIG" "$HERMES_CMD"

    # Step 6: Verify
    echo ""
    verify_config "$DEVIN_CONFIG"

    # Step 7: Summary
    echo ""
    echo -e "${GREEN}${BOLD}✓ Setup complete!${NC}"
    echo ""
    echo -e "  Config file: ${BOLD}$DEVIN_CONFIG${NC}"
    echo -e "  Hermes home: ${BOLD}$HERMES_HOME${NC}"
    echo ""
    echo "Hermes is now configured as an MCP server in devin-cli."
    echo "Restart devin-cli or run 'devin mcp refresh' to load the new server."
    echo ""
}

main "$@"
