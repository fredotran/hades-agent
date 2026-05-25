# ============================================================================
# Hermes Agent — Devin MCP Server Setup (Windows)
# ============================================================================
# One-line installer that configures Hermes Agent as an MCP server in
# devin-cli.
#
# Usage:
#   irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/setup-devin-mcp.ps1 | iex
#
# Or download and run with options:
#   .\setup-devin-mcp.ps1 -HermesPath "C:\Tools\hermes.exe" -Force
#
# ============================================================================

param(
    [string]$HermesPath = "",
    [string]$DevinConfigPath = "",
    [switch]$Force,
    [switch]$VerifyOnly,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
$HermesHome = $env:HERMES_HOME
if (-not $HermesHome) {
    $HermesHome = "$env:USERPROFILE\.hermes"
}

if (-not $DevinConfigPath) {
    # Try common devin config locations (platformdirs -> LocalAppData on Windows)
    $candidates = @(
        "$env:LOCALAPPDATA\devin\config.json",
        "$env:USERPROFILE\.devin\config.json"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) {
            $DevinConfigPath = $c
            break
        }
    }
    if (-not $DevinConfigPath) {
        $DevinConfigPath = "$env:LOCALAPPDATA\devin\config.json"
    }
}

$script:HermesCmd = $HermesPath

# ---------------------------------------------------------------------------
# Helper functions — colored output
# ---------------------------------------------------------------------------
function Write-Info {
    param([string]$Message)
    Write-Host "-> $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[!] $Message" -ForegroundColor Yellow
}

function Write-Err {
    param([string]$Message)
    Write-Host "[X] $Message" -ForegroundColor Red
}

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
function Show-Help {
    @"
Hermes Agent -- Devin MCP Server Setup

Usage: setup-devin-mcp.ps1 [OPTIONS]

Options:
  -HermesPath PATH      Custom path to Hermes binary
  -DevinConfigPath PATH Custom path to devin config.json
                        (default: $DevinConfigPath)
  -Force                Overwrite existing Hermes MCP configuration
  -VerifyOnly           Only verify existing configuration
  -Help                 Show this help

Examples:
  .\setup-devin-mcp.ps1                           # Basic setup
  .\setup-devin-mcp.ps1 -Force                    # Overwrite existing config
  .\setup-devin-mcp.ps1 -VerifyOnly               # Verify without modifying
  .\setup-devin-mcp.ps1 -HermesPath C:\hermes\bin\hermes.exe
"@ | Write-Host
}

# ---------------------------------------------------------------------------
# Resolve Hermes binary path
# ---------------------------------------------------------------------------
function Resolve-Hermes {
    if ($script:HermesCmd) {
        if (Test-Path $script:HermesCmd) {
            Write-Success "Using Hermes binary: $script:HermesCmd"
            return
        } else {
            Write-Err "Hermes binary not found: $script:HermesCmd"
            exit 1
        }
    }

    if (Get-Command hermes -ErrorAction SilentlyContinue) {
        $script:HermesCmd = (Get-Command hermes).Source
        Write-Success "Hermes found on PATH: $script:HermesCmd"
        return
    }

    # Check common install locations
    $candidates = @(
        "$env:LOCALAPPDATA\hermes\hermes-agent\.venv\Scripts\hermes.exe",
        "$env:LOCALAPPDATA\hermes\hermes-agent\venv\Scripts\hermes.exe",
        "$env:USERPROFILE\.local\bin\hermes.exe",
        "$HermesHome\hermes-agent\.venv\Scripts\hermes.exe",
        "$HermesHome\hermes-agent\venv\Scripts\hermes.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) {
            $script:HermesCmd = $c
            Write-Success "Hermes found: $c"
            return
        }
    }

    Write-Err "Hermes not found. Please install Hermes or specify -HermesPath"
    exit 1
}

# ---------------------------------------------------------------------------
# Check if devin-cli is installed
# ---------------------------------------------------------------------------
function Test-DevinCli {
    Write-Info "Checking devin-cli..."

    if (Get-Command devin -ErrorAction SilentlyContinue) {
        Write-Success "devin-cli found: $((Get-Command devin).Source)"
        return
    }

    if (Get-Command devin-cli -ErrorAction SilentlyContinue) {
        Write-Success "devin-cli found: $((Get-Command devin-cli).Source)"
        return
    }

    # Also check via pip
    try {
        $pipList = & python -m pip list 2>$null | Out-String
        if ($pipList -match "devin-cli") {
            Write-Success "devin-cli installed (found via pip)"
            return
        }
    } catch { }

    Write-Warn "devin-cli not found on PATH"
    Write-Info "  You can install it with: pip install devin-cli"
    Write-Info "  Continuing anyway -- configuration will be written for when devin-cli is installed"
}

# ---------------------------------------------------------------------------
# Create devin config directory if needed
# ---------------------------------------------------------------------------
function Ensure-DevinDir {
    $configDir = Split-Path -Parent $DevinConfigPath
    if (-not (Test-Path $configDir)) {
        Write-Info "Creating devin config directory: $configDir"
        New-Item -ItemType Directory -Path $configDir -Force | Out-Null
        Write-Success "Created $configDir"
    }
}

# ---------------------------------------------------------------------------
# Create minimal devin config if it doesn't exist
# ---------------------------------------------------------------------------
function New-MinimalConfig {
    if (Test-Path $DevinConfigPath) {
        Write-Info "Devin config exists: $DevinConfigPath"
        return
    }

    Write-Info "Creating minimal devin config: $DevinConfigPath"
    $minimal = @{ mcpServers = @{} } | ConvertTo-Json -Depth 10
    Set-Content -Path $DevinConfigPath -Value $minimal -Encoding UTF8
    Write-Success "Created minimal devin config"
}

# ---------------------------------------------------------------------------
# Check if Hermes MCP configuration already exists
# ---------------------------------------------------------------------------
function Test-HermesMcpConfig {
    if (-not (Test-Path $DevinConfigPath)) {
        return $false
    }
    try {
        $config = Get-Content $DevinConfigPath -Raw | ConvertFrom-Json
        if ($config.mcpServers -and $config.mcpServers.hermes) {
            return $true
        }
    } catch { }
    return $false
}

# ---------------------------------------------------------------------------
# Backup existing config before modification
# ---------------------------------------------------------------------------
function Backup-Config {
    if (Test-Path $DevinConfigPath) {
        $backup = "$DevinConfigPath.bak.$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())"
        Copy-Item $DevinConfigPath $backup
        Write-Info "Backup created: $backup"
    }
}

# ---------------------------------------------------------------------------
# Add or update Hermes MCP server configuration
# ---------------------------------------------------------------------------
function Update-McpConfig {
    param([string]$HermesBinary)

    Write-Info "Adding Hermes MCP server configuration..."
    Backup-Config

    $config = @{}
    if (Test-Path $DevinConfigPath) {
        try {
            $config = Get-Content $DevinConfigPath -Raw | ConvertFrom-Json -AsHashtable
        } catch {
            Write-Err "Failed to parse existing config JSON: $_"
            exit 1
        }
    }

    if (-not $config) { $config = @{} }
    if (-not $config["mcpServers"]) { $config["mcpServers"] = @{} }

    $config["mcpServers"]["hermes"] = @{
        command = $HermesBinary
        args    = @("mcp", "serve")
        env     = @{
            HERMES_HOME = $HermesHome
        }
    }

    try {
        $json = $config | ConvertTo-Json -Depth 10
        Set-Content -Path $DevinConfigPath -Value $json -Encoding UTF8
    } catch {
        Write-Err "Failed to write devin config: $_"
        exit 1
    }

    Write-Success "Hermes MCP configuration updated"
}

# ---------------------------------------------------------------------------
# Verify the configuration
# ---------------------------------------------------------------------------
function Confirm-Config {
    Write-Info "Verifying configuration..."

    if (-not (Test-Path $DevinConfigPath)) {
        Write-Err "Config file not found: $DevinConfigPath"
        exit 1
    }

    # Check JSON validity
    try {
        $config = Get-Content $DevinConfigPath -Raw | ConvertFrom-Json
    } catch {
        Write-Err "Config file contains invalid JSON: $_"
        exit 1
    }

    # Check Hermes MCP section exists
    if (-not ($config.mcpServers -and $config.mcpServers.hermes)) {
        Write-Err "Hermes MCP configuration not found in $DevinConfigPath"
        exit 1
    }

    $hermesConfig = $config.mcpServers.hermes
    if (-not $hermesConfig) {
        Write-Err "Hermes MCP configuration is empty"
        exit 1
    }

    Write-Success "Configuration verified"
    Write-Host ""
    Write-Host "Hermes MCP Configuration:" -ForegroundColor White
    $hermesConfig | ConvertTo-Json -Depth 10 | Write-Host
}

# ---------------------------------------------------------------------------
# Verify Hermes binary works
# ---------------------------------------------------------------------------
function Confirm-HermesBinary {
    param([string]$HermesBinary)

    Write-Info "Verifying Hermes binary..."

    if (-not (Test-Path $HermesBinary)) {
        Write-Warn "Cannot find Hermes binary: $HermesBinary"
        return
    }

    try {
        $null = & $HermesBinary --version 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Hermes binary is functional"
            return
        }
    } catch { }

    try {
        $null = & $HermesBinary -h 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Success "Hermes binary is functional"
            return
        }
    } catch { }

    Write-Warn "Hermes binary may not be fully functional yet (this is OK for fresh installs)"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
function Main {
    if ($Help) {
        Show-Help
        exit 0
    }

    Write-Host ""
    Write-Host "Hermes Agent -- Devin MCP Setup" -ForegroundColor Cyan
    Write-Host ""

    # --verify-only mode
    if ($VerifyOnly) {
        Write-Info "Running in verify-only mode"
        Confirm-Config
        Write-Host ""
        Write-Success "Verification complete -- Hermes MCP is configured"
        exit 0
    }

    # Step 1: Check dependencies
    Test-DevinCli
    Resolve-Hermes

    # Step 2: Verify Hermes binary
    Confirm-HermesBinary -HermesBinary $script:HermesCmd

    # Step 3: Ensure devin config directory and file exist
    Ensure-DevinDir

    # Step 4: Check for existing config
    if (Test-Path $DevinConfigPath) {
        if (Test-HermesMcpConfig) {
            if ($Force) {
                Write-Info "Overwriting existing Hermes MCP configuration (-Force)"
            } else {
                Write-Warn "Hermes MCP configuration already exists"
                Write-Info "Use -Force to overwrite, or -VerifyOnly to check"
                Write-Host ""
                Confirm-Config
                exit 0
            }
        }
    } else {
        New-MinimalConfig
    }

    # Step 5: Update MCP configuration
    Update-McpConfig -HermesBinary $script:HermesCmd

    # Step 6: Verify
    Write-Host ""
    Confirm-Config

    # Step 7: Summary
    Write-Host ""
    Write-Host "Setup complete!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Config file: $DevinConfigPath"
    Write-Host "  Hermes home: $HermesHome"
    Write-Host ""
    Write-Host "Hermes is now configured as an MCP server in devin-cli."
    Write-Host "Restart devin-cli or run 'devin mcp refresh' to load the new server."
    Write-Host ""
}

Main
