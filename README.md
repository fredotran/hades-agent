# hades-agent

This is a personal fork of hermes-agent, customized for private use and integrated with oh-my-opendevin for advanced Devin CLI delegation.

## Features
- Hermes-Agent with oh-my-opendevin integration
- One-way delegation: Hermes delegates tasks to Devin CLI (no two-way orchestration)
- Automated setup and health checks
- Parallel and background task support

## Quick Setup

```bash
# Clone this fork
git clone https://github.com/fredotran/hades-agent.git
cd hades-agent

# Run the installer with Devin integration
bash scripts/install.sh --with-devin

# Or configure Hermes as MCP server for devin-cli (one-line installer)
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/setup-devin-mcp.sh | bash
```

## Usage
- Delegate tasks to Devin CLI using the "devin" toolset
- Monitor background sessions and status
- See docs/DEVIN_INTEGRATION.md for advanced workflows

## License
MIT
