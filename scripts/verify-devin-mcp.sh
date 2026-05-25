#!/bin/bash
# ============================================================================
# Devin MCP Integration Verification Script
# ============================================================================
# Verifies that Hermes MCP server is properly configured in devin-cli
#
# Usage:
#   bash scripts/verify-devin-mcp.sh
#   bash scripts/verify-devin-mcp.sh --json
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

# Options
JSON_OUTPUT=false
VERBOSE=false

# Results tracking
PASS=0
FAIL=0
WARN=0

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --json)
            JSON_OUTPUT=true
            shift
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        -h|--help)
            echo "Devin MCP Integration Verification"
            echo ""
            echo "Usage: verify-devin-mcp.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --json      Output results as JSON"
            echo "  --verbose   Show detailed output"
            echo "  -h, --help  Show this help"
            echo ""
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Logging functions
log_info() {
    if [ "$JSON_OUTPUT" = false ]; then
        echo -e "${CYAN}→${NC} $1"
    fi
}

log_success() {
    if [ "$JSON_OUTPUT" = false ]; then
        echo -e "${GREEN}✓${NC} $1"
    fi
    ((PASS++)) || true
}

log_warn() {
    if [ "$JSON_OUTPUT" = false ]; then
        echo -e "${YELLOW}⚠${NC} $1"
    fi
    ((WARN++)) || true
}

log_error() {
    if [ "$JSON_OUTPUT" = false ]; then
        echo -e "${RED}✗${NC} $1"
    fi
    ((FAIL++)) || true
}

# Check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check devin-cli installation
check_devin() {
    log_info "Checking devin-cli installation..."
    if command_exists devin; then
        local devin_path
        devin_path="$(command -v devin)"
        log_success "devin-cli found: $devin_path"
        if [ "$VERBOSE" = true ]; then
            devin --version 2>/dev/null || true
        fi
        return 0
    else
        log_error "devin-cli not found on PATH"
        return 1
    fi
}

# Check Hermes installation
check_hermes() {
    log_info "Checking Hermes installation..."
    if command_exists hermes; then
        local hermes_path
        hermes_path="$(command -v hermes)"
        log_success "Hermes found: $hermes_path"
        if [ "$VERBOSE" = true ]; then
            hermes --version 2>/dev/null || true
        fi
        return 0
    else
        log_error "Hermes not found on PATH"
        return 1
    fi
}

# Check Hermes MCP server support
check_hermes_mcp() {
    log_info "Checking Hermes MCP server support..."
    if command_exists hermes; then
        if hermes mcp serve --help >/dev/null 2>&1; then
            log_success "Hermes MCP server command works"
            return 0
        else
            log_warn "Hermes MCP server may not be supported"
            return 1
        fi
    else
        log_warn "Cannot check Hermes MCP (Hermes not installed)"
        return 1
    fi
}

# Check devin config file
check_devin_config() {
    log_info "Checking devin configuration..."
    local devin_config="${DEVIN_CONFIG:-$HOME/.devin/config.json}"

    if [ -f "$devin_config" ]; then
        log_success "Devin config found: $devin_config"
        return 0
    else
        log_error "Devin config not found: $devin_config"
        return 1
    fi
}

# Check JSON validity of devin config
check_json_validity() {
    log_info "Checking JSON validity..."
    local devin_config="${DEVIN_CONFIG:-$HOME/.devin/config.json}"

    if [ ! -f "$devin_config" ]; then
        log_warn "Cannot check JSON (config file not found)"
        return 1
    fi

    if command_exists jq; then
        if jq empty "$devin_config" 2>/dev/null; then
            log_success "Config file contains valid JSON"
            return 0
        else
            log_error "Config file contains invalid JSON"
            return 1
        fi
    else
        if python3 -c "import json; json.load(open('$devin_config'))" 2>/dev/null; then
            log_success "Config file contains valid JSON"
            return 0
        else
            log_error "Config file contains invalid JSON"
            return 1
        fi
    fi
}

# Check if Hermes MCP is configured
check_hermes_mcp_config() {
    log_info "Checking Hermes MCP configuration..."
    local devin_config="${DEVIN_CONFIG:-$HOME/.devin/config.json}"

    if [ ! -f "$devin_config" ]; then
        log_warn "Cannot check config (file not found)"
        return 1
    fi

    if command_exists jq; then
        if jq -e '.mcpServers.hermes' "$devin_config" >/dev/null 2>&1; then
            log_success "Hermes MCP configured in devin"
            if [ "$VERBOSE" = true ]; then
                echo ""
                jq '.mcpServers.hermes' "$devin_config"
                echo ""
            fi
            return 0
        else
            log_error "Hermes MCP not configured in devin"
            return 1
        fi
    else
        if python3 -c "import json; d=json.load(open('$devin_config')); exit(0 if d.get('mcpServers',{}).get('hermes') else 1)" 2>/dev/null; then
            log_success "Hermes MCP configured in devin"
            return 0
        else
            log_error "Hermes MCP not configured in devin"
            return 1
        fi
    fi
}

# Check if devin can list MCP servers
check_devin_mcp_list() {
    log_info "Checking devin mcp list..."
    if ! command_exists devin; then
        log_warn "Cannot test (devin-cli not installed)"
        return 1
    fi

    if devin mcp list >/dev/null 2>&1; then
        log_success "devin mcp list works"
        if [ "$VERBOSE" = true ]; then
            echo ""
            devin mcp list 2>/dev/null || true
            echo ""
        fi

        # Check if hermes is in the list
        if devin mcp list 2>/dev/null | grep -q "hermes"; then
            log_success "Hermes listed in devin MCP servers"
            return 0
        else
            log_warn "Hermes not found in devin MCP servers"
            return 1
        fi
    else
        log_warn "devin mcp list failed"
        return 1
    fi
}

# Check if Hermes binary path in config is valid
check_hermes_binary_path() {
    log_info "Checking Hermes binary path..."
    local devin_config="${DEVIN_CONFIG:-$HOME/.devin/config.json}"

    if [ ! -f "$devin_config" ]; then
        log_warn "Cannot check (config file not found)"
        return 1
    fi

    local hermes_cmd
    if command_exists jq; then
        hermes_cmd="$(jq -r '.mcpServers.hermes.command // empty' "$devin_config" 2>/dev/null)"
    else
        hermes_cmd="$(python3 -c "import json; d=json.load(open('$devin_config')); print(d.get('mcpServers',{}).get('hermes',{}).get('command',''))" 2>/dev/null)"
    fi

    if [ -z "$hermes_cmd" ]; then
        log_error "No command specified in Hermes MCP config"
        return 1
    fi

    if [ -x "$hermes_cmd" ]; then
        log_success "Hermes binary exists and is executable: $hermes_cmd"
        return 0
    else
        if command_exists hermes; then
            log_warn "Hermes binary in config not executable, but hermes is in PATH"
        else
            log_error "Hermes binary not found or not executable: $hermes_cmd"
        fi
        return 1
    fi
}

# Check HERMES_HOME env var in config
check_hermes_home_env() {
    log_info "Checking HERMES_HOME environment variable..."
    local devin_config="${DEVIN_CONFIG:-$HOME/.devin/config.json}"

    if [ ! -f "$devin_config" ]; then
        log_warn "Cannot check (config file not found)"
        return 1
    fi

    local hermes_home
    if command_exists jq; then
        hermes_home="$(jq -r '.mcpServers.hermes.env.HERMES_HOME // empty' "$devin_config" 2>/dev/null)"
    else
        hermes_home="$(python3 -c "import json; d=json.load(open('$devin_config')); print(d.get('mcpServers',{}).get('hermes',{}).get('env',{}).get('HERMES_HOME',''))" 2>/dev/null)"
    fi

    if [ -n "$hermes_home" ]; then
        log_success "HERMES_HOME set in config: $hermes_home"
        if [ -d "$hermes_home" ]; then
            log_success "HERMES_HOME directory exists"
        else
            log_warn "HERMES_HOME directory does not exist: $hermes_home"
        fi
        return 0
    else
        log_warn "HERMES_HOME not set in config"
        return 1
    fi
}

# Main verification flow
main() {
    if [ "$JSON_OUTPUT" = false ]; then
        echo ""
        echo -e "${CYAN}${BOLD}Devin MCP Integration Verification${NC}"
        echo "========================================"
        echo ""
    fi

    # Run all checks
    check_devin
    check_hermes
    check_hermes_mcp
    check_devin_config
    check_json_validity
    check_hermes_mcp_config
    check_hermes_binary_path
    check_hermes_home_env
    check_devin_mcp_list

    # Summary
    if [ "$JSON_OUTPUT" = true ]; then
        cat <<EOF
{
  "summary": {
    "passed": $PASS,
    "failed": $FAIL,
    "warnings": $WARN,
    "total": $((PASS + FAIL + WARN))
  },
  "status": "$([ $FAIL -eq 0 ] && echo "OK" || echo "FAIL")"
}
EOF
    else
        echo ""
        echo "========================================"
        echo -e "${BOLD}Summary:${NC}"
        echo -e "  ${GREEN}Passed:${NC}   $PASS"
        echo -e "  ${RED}Failed:${NC}   $FAIL"
        echo -e "  ${YELLOW}Warnings:${NC} $WARN"
        echo -e "  ${BOLD}Total:${NC}    $((PASS + FAIL + WARN))"
        echo ""

        if [ $FAIL -eq 0 ] && [ $WARN -eq 0 ]; then
            echo -e "${GREEN}${BOLD}✓ All checks passed!${NC}"
            echo ""
            echo "Hermes MCP server is properly configured."
            echo "Run 'devin mcp list' to verify."
        elif [ $FAIL -eq 0 ]; then
            echo -e "${YELLOW}${BOLD}⚠ Checks passed with warnings${NC}"
            echo ""
            echo "The integration should work, but some optional checks failed."
        else
            echo -e "${RED}${BOLD}✗ Some checks failed${NC}"
            echo ""
            echo "Please review the errors above and run the setup again:"
            echo "  curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/setup-devin-mcp.sh | bash"
        fi
        echo ""
    fi

    # Exit with appropriate code
    if [ $FAIL -gt 0 ]; then
        exit 1
    else
        exit 0
    fi
}

main "$@"
