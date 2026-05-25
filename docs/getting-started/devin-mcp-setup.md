# Devin MCP Setup Guide

Complete guide for configuring Hermes Agent as an MCP server for devin-cli.

---

## Quick Start

### One-Line Installer (Recommended)

**Linux / macOS / WSL2:**
```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/setup-devin-mcp.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/setup-devin-mcp.ps1 | iex
```

---

## Prerequisites

Before running the installer, ensure you have:

1. **Hermes Agent** installed and working
   ```bash
   hermes --version
   ```

2. **devin-cli** installed and authenticated
   ```bash
   devin --version
   devin login
   ```

3. **jq** (optional but recommended) for reliable JSON manipulation
   ```bash
   jq --version
   ```
   If jq is not available, the installer falls back to Python.

---

## Manual Setup

If you prefer manual configuration or the installer doesn't work for your environment:

### 1. Locate the Devin Config File

```bash
# Default location
~/.devin/config.json

# On Windows
%USERPROFILE%\.devin\config.json
```

### 2. Create the Config Directory

```bash
mkdir -p ~/.devin
```

### 3. Create or Edit config.json

```json
{
  "mcpServers": {
    "hermes": {
      "command": "hermes",
      "args": ["mcp", "serve"],
      "env": {
        "HERMES_HOME": "~/.hermes"
      }
    }
  }
}
```

### 4. Customize the Configuration

**Custom Hermes path:**
```json
{
  "mcpServers": {
    "hermes": {
      "command": "/path/to/hermes",
      "args": ["mcp", "serve"],
      "env": {
        "HERMES_HOME": "~/.hermes"
      }
    }
  }
}
```

**Custom HERMES_HOME:**
```json
{
  "mcpServers": {
    "hermes": {
      "command": "hermes",
      "args": ["mcp", "serve"],
      "env": {
        "HERMES_HOME": "/custom/path/to/hermes/data"
      }
    }
  }
}
```

**Multiple environment variables:**
```json
{
  "mcpServers": {
    "hermes": {
      "command": "hermes",
      "args": ["mcp", "serve"],
      "env": {
        "HERMES_HOME": "~/.hermes",
        "HERMES_PROFILE": "default",
        "LOG_LEVEL": "debug"
      }
    }
  }
}
```

### 5. Verify Configuration

```bash
# Validate JSON syntax
jq empty ~/.devin/config.json

# Check Hermes MCP section exists
jq '.mcpServers.hermes' ~/.devin/config.json

# Restart devin-cli and list MCP servers
devin mcp list
```

---

## Available MCP Tools

Once configured, devin-cli can call these Hermes MCP tools:

| Tool | Description |
|------|-------------|
| `mcp_hermes_conversations_list` | List active sessions across platforms |
| `mcp_hermes_conversation_get` | Get detailed conversation info |
| `mcp_hermes_messages_send` | Send messages through any platform |
| `mcp_hermes_messages_read` | Read message history |
| `mcp_hermes_events_poll` | Poll for new events since cursor |
| `mcp_hermes_events_wait` | Long-poll for real-time events |
| `mcp_hermes_attachments_fetch` | Extract non-text attachments |
| `mcp_hermes_permissions_list_open` | List pending approval requests |
| `mcp_hermes_permissions_respond` | Allow/deny approval requests |
| `mcp_hermes_channels_list` | List available messaging targets |

---

## Example Usage in Devin

```bash
# In devin-cli, ask Devin to use Hermes
devin: "Send a Telegram message to the team that deployment is done"

# Devin will call:
devin mcp call hermes mcp_hermes_messages_send '{
  "target": "telegram:me",
  "message": "Deployment complete!"
}'
```

---

## Verification

### Using the Installer's Verify Mode

```bash
# Linux/macOS
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/setup-devin-mcp.sh | bash -s -- --verify-only

# Windows
irm https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/setup-devin-mcp.ps1 | iex -Args -VerifyOnly
```

### Manual Verification Steps

1. **Check config file exists:**
   ```bash
   cat ~/.devin/config.json
   ```

2. **Validate JSON:**
   ```bash
   jq empty ~/.devin/config.json
   ```

3. **Check Hermes MCP section:**
   ```bash
   jq '.mcpServers.hermes' ~/.devin/config.json
   ```

4. **Test devin integration:**
   ```bash
   devin mcp list
   # Should show "hermes" in the list
   ```

5. **Test a basic MCP call:**
   ```bash
   devin mcp call hermes mcp_hermes_conversations_list
   ```

---

## Troubleshooting

### Issue: "Hermes command not found"

**Cause:** Hermes is not in your PATH.

**Solution:**
```bash
# Find Hermes installation
which hermes
# or
find ~ -name hermes -type f 2>/dev/null

# Use the full path
setup-devin-mcp.sh --hermes-path /path/to/hermes
```

### Issue: "devin-cli not found"

**Cause:** devin-cli is not installed or not in PATH.

**Solution:**
```bash
# Install devin-cli
npm install -g devin

# Verify installation
devin --version
```

### Issue: "Config file contains invalid JSON"

**Cause:** Existing config file has syntax errors.

**Solution:**
```bash
# Check syntax with jq
jq empty ~/.devin/config.json

# Or use Python
python3 -c "import json; json.load(open('~/.devin/config.json'))"

# Fix syntax errors manually, or delete and re-run the installer
rm ~/.devin/config.json
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/setup-devin-mcp.sh | bash
```

### Issue: "Hermes MCP not found in devin mcp list"

**Cause:** devin-cli hasn't reloaded its configuration.

**Solution:**
```bash
# Restart devin-cli
# Or reload MCP servers
devin mcp refresh
# Or
devin mcp reload
```

### Issue: "jq failed to update config"

**Cause:** jq is installed but failed to process the JSON.

**Solution:**
```bash
# The installer automatically falls back to Python
# Ensure Python is available:
python3 --version
# or
python --version
```

### Issue: "Permission denied" when modifying config

**Cause:** Config file or directory has incorrect permissions.

**Solution:**
```bash
# Fix permissions
chmod 755 ~/.devin
chmod 644 ~/.devin/config.json

# Or run with appropriate permissions
```

### Issue: "hermes mcp serve command not found"

**Cause:** Your Hermes version doesn't support MCP server mode.

**Solution:**
```bash
# Update Hermes to the latest version
cd ~/.hermes/hermes-agent
git pull
source ~/.venv/bin/activate  # or equivalent
pip install -e .
```

---

## Advanced Configuration

### Environment Variables

The installer respects these environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `HERMES_HOME` | Hermes data directory | `~/.hermes` |
| `DEVIN_CONFIG_DIR` | Devin config directory | `~/.devin` |
| `DEVIN_CONFIG` | Full path to devin config | `~/.devin/config.json` |

### HTTP Transport (Future)

While the current implementation uses stdio transport, you can manually configure HTTP transport:

```json
{
  "mcpServers": {
    "hermes": {
      "url": "http://localhost:8000/mcp",
      "transport": "http",
      "headers": {
        "Authorization": "Bearer your-token"
      }
    }
  }
}
```

---

## Next Steps

After successful setup:

1. **Configure messaging platforms** (if not already done):
   ```bash
   hermes gateway setup
   ```

2. **Start the Hermes gateway** (optional, for messaging features):
   ```bash
   hermes gateway start
   ```

3. **Test the integration**:
   ```bash
   # In devin-cli
devin: "Use Hermes to list my active conversations"
   ```

4. **Explore available tools**:
   ```bash
   devin mcp list
   devin mcp tools hermes
   ```

---

## See Also

- [Devin Integration Overview](../DEVIN_INTEGRATION.md) — Complete integration documentation
- [Hermes Installation Guide](./installation.md) — Install Hermes Agent
- [Hermes Configuration](../user-guide/configuration.md) — Configure Hermes settings
