# ============================================================================
# Hermes Launcher for Windows — One-command install + run
# ============================================================================
# This script checks if Hermes is installed, installs it if missing,
# then launches the interactive CLI.
#
# Usage:
#   irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/hermes-launcher.ps1 | iex
#
# Or download and run with options:
#   .\hermes-launcher.ps1 -WithDevin
#
# ============================================================================

param(
    [switch]$WithDevin,
    [switch]$SkipInstall,
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"

$HermesHome = "$env:LOCALAPPDATA\hermes"
$InstallDir = "$HermesHome\hermes-agent"
$InstallScriptUrl = "https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.ps1"

function Write-Info { param([string]$Message) Write-Host "→ $Message" -ForegroundColor Cyan }
function Write-Success { param([string]$Message) Write-Host "✓ $Message" -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "⚠ $Message" -ForegroundColor Yellow }
function Write-Err { param([string]$Message) Write-Host "✗ $Message" -ForegroundColor Red }

function Test-HermesExists {
    $hermesCmd = Get-Command hermes -ErrorAction SilentlyContinue
    if ($hermesCmd) { return $true }

    $venvHermes = "$InstallDir\venv\Scripts\hermes.exe"
    if (Test-Path $venvHermes) { return $true }

    return $false
}

function Test-InstallationPresent {
    $venvDir = "$InstallDir\venv"
    if (Test-Path $venvDir) { return $true }
    return $false
}

function Install-Hermes {
    Write-Info "Hermes not found. Starting installation..."
    Write-Host ""

    $installArgs = @{ }
    if ($WithDevin) { $installArgs['WithDevin'] = $true }
    if ($Branch -ne "main") { $installArgs['Branch'] = $Branch }

    try {
        Write-Info "Downloading installer..."
        $script = Invoke-WebRequest -Uri $InstallScriptUrl -UseBasicParsing
        Invoke-Expression $script
    } catch {
        Write-Err "Installation failed: $_"
        Write-Host ""
        Write-Host "You can install manually:"
        Write-Host "  git clone https://github.com/NousResearch/hermes-agent.git $InstallDir"
        Write-Host "  cd $InstallDir"
        Write-Host "  .\setup-hermes.ps1"
        exit 1
    }

    Write-Success "Installation complete!"
    Write-Host ""
}

function Launch-Hermes {
    $venvDir = "$InstallDir\venv"
    $hermesBin = "$venvDir\Scripts\hermes.exe"

    if (-not (Test-Path $hermesBin)) {
        # Try PATH
        $hermesCmd = Get-Command hermes -ErrorAction SilentlyContinue
        if ($hermesCmd) {
            $hermesBin = $hermesCmd.Source
        } else {
            Write-Err "hermes command not found after installation."
            exit 1
        }
    }

    Write-Info "Launching Hermes..."
    Write-Host ""

    # Launch hermes
    & $hermesBin @args
}

# Main
Write-Host ""
Write-Host "⚕ Hermes Launcher" -ForegroundColor Cyan -Bold
Write-Host ""

if ($SkipInstall) {
    if (-not (Test-HermesExists) -and -not (Test-InstallationPresent)) {
        Write-Err "Hermes not found and -SkipInstall is set."
        exit 1
    }
    Write-Info "Skipping installation check (-SkipInstall)"
} else {
    if ((Test-HermesExists) -or (Test-InstallationPresent)) {
        Write-Info "Hermes already installed"
    } else {
        Install-Hermes
    }
}

Launch-Hermes
