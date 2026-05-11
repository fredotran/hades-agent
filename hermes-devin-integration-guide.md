# Hermes Agent & Devin CLI Integration Guide

## Overview

This guide explains what Hermes Agent is, how it integrates with devin-cli, and practical workflows for combining both tools in your development process.

## What is Hermes Agent?

Hermes Agent is a **self-improving AI agent with a closed learning loop** built by Nous Research. It's designed to be a long-term AI companion that gets smarter with use, rather than a one-shot tool.

### Core Capabilities

#### 1. Conversational AI with Tool Calling
- Runs AI models (OpenAI, Anthropic, OpenRouter, Nous Portal, etc.)
- Automatic tool calling with 40+ built-in tools
- File operations, web browsing, code execution, and more

#### 2. Multi-Platform Messaging Hub
- **Platforms**: Telegram, Discord, Slack, WhatsApp, Signal, Email
- Unified conversation management across all platforms
- Voice memo transcription and cross-platform continuity
- Single gateway process for all messaging

#### 3. Self-Improving Learning System
- **Skill Creation**: Creates skills from experience after complex tasks
- **Skill Improvement**: Skills self-improve during use
- **Memory System**: Agent-curated memory with periodic nudges
- **Cross-Session Recall**: Searches its own past conversations
- **User Modeling**: Builds a deepening model of who you are across sessions

#### 4. Extensive Skill Library (24+ Categories)

**Software Development**
- Code review, testing, debugging
- Repository management
- CI/CD workflows

**Productivity**
- Google Workspace (Gmail, Calendar, Drive, Docs, Sheets)
- Notion, Linear, Airtable
- Time management, project planning

**Creative**
- Comic creation, infographics
- ASCII art, architecture diagrams
- Video processing

**DevOps & Infrastructure**
- Container management (Docker, Kubernetes)
- Deployment automation
- Server monitoring

**Research & Analysis**
- Paper analysis, literature reviews
- Data science, ML workflows
- Market research

**GitHub Integration**
- Repository management
- PR workflows and code review
- Issue tracking and triage

**Media & Content**
- YouTube content processing
- Image generation
- Video editing

#### 5. Scheduled Automations
- Built-in cron scheduler for unattended tasks
- Daily reports, nightly backups, weekly audits
- Natural language task scheduling
- Cross-platform delivery

#### 6. Parallel Processing
- Spawns isolated subagents for parallel workstreams
- Delegates complex tasks to specialized workers
- Multi-agent coordination via kanban boards

#### 7. Remote Execution
- **7 Terminal Backends**: Local, Docker, SSH, Modal, Daytona, Vercel Sandbox, Singularity
- Serverless persistence (hibernates when idle, wakes on demand)
- Cost-effective: Can run on $5 VPS or GPU clusters
- Not tied to your laptop

## Integration with Devin CLI

### Architecture

```
You (Developer)
    ↓
Devin CLI (Coding Specialist)
    ↓ MCP (Model Context Protocol)
Hermes Agent (Communication/Automation Specialist)
    ↓ Platform Adapters
Slack, Discord, Telegram, Email, etc.
```

### Integration Option: Hermes as MCP Server

Hermes Agent can run as an MCP server, exposing its messaging capabilities to devin-cli.

#### Available MCP Tools

**Conversation Management**
- `mcp_hermes_conversations_list` - List active sessions across platforms
- `mcp_hermes_conversation_get` - Get detailed conversation info

**Message Operations**
- `mcp_hermes_messages_read` - Read message history
- `mcp_hermes_messages_send` - Send messages through any platform

**Event Monitoring**
- `mcp_hermes_events_poll` - Poll for new events since cursor
- `mcp_hermes_events_wait` - Long-poll for real-time events

**File Attachments**
- `mcp_hermes_attachments_fetch` - Extract non-text attachments

**Approval Management**
- `mcp_hermes_permissions_list_open` - List pending approval requests
- `mcp_hermes_permissions_respond` - Allow/deny approval requests

**Channel Discovery**
- `mcp_hermes_channels_list` - List available messaging targets

### Setup Instructions

#### 1. Install Hermes Agent

```bash
# Linux, macOS, WSL2, Termux
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash

# Reload shell
source ~/.bashrc  # or source ~/.zshrc

# Verify installation
hermes --help
```

#### 2. Configure Hermes

```bash
# Run setup wizard
hermes setup

# Configure model provider
hermes model

# Configure tools
hermes tools
```

#### 3. Configure Devin CLI Integration

Add to `.devin/config.json`:

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

#### 4. Start Hermes Gateway

```bash
# Start the messaging gateway
hermes gateway start

# Or start Hermes MCP server directly
hermes mcp serve
```

#### 5. Verify Integration

```bash
# In devin-cli, test the connection
devin mcp list

# You should see "hermes" listed
```

## Practical Workflow Examples

### Scenario 1: Code Completion Notifications

```bash
# In devin-cli, working on a feature
devin: "Implement the user authentication module"

# When complete, notify via Hermes
devin: "Use Hermes to send me a Telegram message when auth module is done"
# Devin calls: mcp_hermes_messages_send(target="telegram:me", message="Auth module complete!")
```

### Scenario 2: Cross-Platform Project Updates

```bash
# Devin completes a deployment
devin: "Deploy the main branch to production"

# Broadcast to all platforms via Hermes
devin: "Use Hermes to announce the deployment to Slack, Discord, and Telegram"
# Devin calls:
# - mcp_hermes_channels_list() to get targets
# - mcp_hermes_messages_send() for each platform
```

### Scenario 3: Event-Driven Workflows

```bash
# Set up continuous monitoring
devin: "Monitor Hermes events for new messages containing 'urgent'"
# Devin calls: mcp_hermes_events_wait() in a loop

# When urgent message detected:
devin: "I see an urgent message from Hermes. Let me check the codebase for related issues"
```

### Scenario 4: Daily Development Workflow

```bash
# 1. Start your day with devin-cli
devin: "What are my priorities for today?"

# 2. Devin checks Hermes for context
devin: "Check Hermes conversations for any urgent requests"
# Devin: mcp_hermes_conversations_list(search="urgent")

# 3. Work on tasks with devin
devin: "Implement the API endpoint for user profiles"

# 4. When complete, notify via Hermes
devin: "Tell Hermes to notify the team on Slack that the API endpoint is done"
# Devin: mcp_hermes_messages_send(target="slack:#dev", message="API endpoint complete")
```

### Scenario 5: Incident Response

```bash
# 1. Hermes detects an issue (via monitoring)
# 2. Devin polls for events
devin: "Check Hermes for any critical events"
# Devin: mcp_hermes_events_poll()

# 3. Devin investigates and fixes
devin: "There's a critical event. Let me check the logs and fix the issue"

# 4. Update stakeholders via Hermes
devin: "Use Hermes to update the incident status on all platforms"
# Devin: mcp_hermes_messages_send() to multiple platforms
```

### Scenario 6: Scheduled Automations

```bash
# Set up recurring tasks via Hermes cron
devin: "Schedule a daily code quality report via Hermes"
# Devin calls Hermes to set up cron job that runs daily

# Hermes runs the report and sends results
# You get notified on your preferred platform
```

## Current Limitations and Solutions

### Limitation 1: Gateway Dependency
**Problem**: Requires Hermes gateway to be running with connected platforms

**Solutions**:
- Create standalone MCP mode that doesn't require full gateway
- Embed gateway functionality in MCP server process
- Use Hermes's internal messaging system directly

### Limitation 2: Stdio-Only Transport
**Problem**: MCP server runs in stdio mode only (not HTTP)

**Solution**: Add HTTP transport support
```python
# Enhanced MCP server with HTTP support
hermes mcp serve --http --port 8000

# Devin config
{
  "mcpServers": {
    "hermes": {
      "url": "http://localhost:8000/mcp",
      "transport": "http"
    }
  }
}
```

### Limitation 3: Manual Configuration
**Problem**: Devin needs manual MCP server configuration

**Solutions**:
- Auto-setup script: `scripts/setup-devin-integration.sh`
- Devin command extension for auto-configuration
- One-line installation command

### Limitation 4: Limited Feature Exposure
**Problem**: Many Hermes features (skills, memory, etc.) aren't exposed via MCP

**Solution**: Expand MCP tool surface

**Skills Integration**:
```python
@mcp.tool()
def skills_list() -> str:
    """List all available Hermes skills."""

@mcp.tool()
def skills_invoke(skill_name: str, prompt: str) -> str:
    """Invoke a Hermes skill and return result."""

@mcp.tool()
def skills_create(name: str, description: str, code: str) -> str:
    """Create a new skill from code."""
```

**Memory System Access**:
```python
@mcp.tool()
def memory_search(query: str, limit: int = 10) -> str:
    """Search Hermes memory for relevant information."""

@mcp.tool()
def memory_add(content: str, tags: list = None) -> str:
    """Add information to Hermes memory."""
```

**Tool and Toolset Access**:
```python
@mcp.tool()
def tools_list(toolset: str = None) -> str:
    """List available Hermes tools."""

@mcp.tool()
def toolsets_list() -> str:
    """List all available toolsets."""
```

**Configuration Access**:
```python
@mcp.tool()
def config_get(key: str) -> str:
    """Get a Hermes configuration value."""

@mcp.tool()
def config_set(key: str, value: str) -> str:
    """Set a Hermes configuration value."""
```

### Implementation Priority

**High Priority**:
- HTTP transport support (enables remote access)
- Skills integration (exposes core Hermes capability)
- Auto-configuration script (improves UX)

**Medium Priority**:
- Memory system access
- Enhanced event system
- Tool/toolset access

**Future Enhancement**:
- Standalone mode (requires significant refactoring)
- Embedded gateway (complex, may not be necessary)

## Key Benefits of Integration

### 1. Specialization
- **Devin**: Excels at coding, code analysis, and development tasks
- **Hermes**: Excels at communication, automation, and cross-platform coordination

### 2. Continuity
- Hermes maintains context across sessions and platforms
- Persistent memory and learning system
- Cross-session recall of past conversations

### 3. Scalability
- Hermes can run remotely while devin runs locally
- Serverless persistence (hibernates when idle)
- Cost-effective deployment options

### 4. Multi-Platform Reach
- Reach team members wherever they are
- Unified messaging across Slack, Discord, Telegram, etc.
- Cross-platform conversation continuity

### 5. Automation
- Schedule tasks that run even when you're not coding
- Built-in cron scheduler
- Natural language task scheduling

### 6. Shared Knowledge Base
- Memory system accessible from both tools
- Skills created in one context usable in another
- Learning system improves over time

## Advanced Integration Patterns

### Pattern 1: Skill-Based Task Delegation

```bash
# Devin encounters a task better suited for Hermes skills
devin: "I need to analyze these GitHub issues across multiple repos"
devin: "Use Hermes github-repo-management skill to clone and analyze repos"
# Devin calls Hermes skill through MCP
```

### Pattern 2: Memory and Context Sharing

```bash
# Devin learns something important
devin: "The deployment requires these specific environment variables"

# Store in Hermes memory for future reference
devin: "Save this deployment config to Hermes memory"
# Devin calls: mcp_hermes_memory_add()

# Later, retrieve the context
devin: "Check Hermes memory for deployment requirements"
# Devin calls: mcp_hermes_memory_search()
```

### Pattern 3: Parallel Processing

```bash
# Delegate parallel tasks to Hermes subagents
devin: "Analyze these 10 repositories in parallel"
# Devin calls Hermes to spawn subagents
# Each subagent handles one repo
# Results aggregated and returned
```

### Pattern 4: Research and Development

```bash
# Use Hermes for research tasks
devin: "Use Hermes to research the latest authentication protocols"

# Apply findings with devin
devin: "Based on the research, implement OAuth2 in our API"

# Document and share via Hermes
devin: "Send the implementation summary to the team via Hermes"
```

## Configuration Examples

### Basic MCP Configuration

```json
{
  "mcpServers": {
    "hermes": {
      "command": "hermes",
      "args": ["mcp", "serve"]
    }
  }
}
```

### Advanced Configuration with HTTP Transport

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

### Configuration with Environment Variables

```json
{
  "mcpServers": {
    "hermes": {
      "command": "hermes",
      "args": ["mcp", "serve", "--verbose"],
      "env": {
        "HERMES_HOME": "~/.hermes",
        "HERMES_PROFILE": "default",
        "LOG_LEVEL": "debug"
      }
    }
  }
}
```

## Troubleshooting

### Issue: Hermes MCP Server Not Starting

**Solution**:
```bash
# Check Hermes installation
hermes --version

# Verify MCP dependencies
pip install mcp

# Check logs
hermes logs --level debug
```

### Issue: Devin Cannot Connect to Hermes

**Solution**:
```bash
# Verify Hermes is running
hermes mcp serve --verbose

# Test MCP connection
devin mcp list

# Check Devin config
cat .devin/config.json
```

### Issue: Missing MCP Tools

**Solution**:
```bash
# Reload MCP configuration
hermes mcp reload

# Restart Hermes gateway
hermes gateway restart

# Check tool availability
devin: "List available MCP tools"
```

## Best Practices

### 1. Start Simple
- Begin with basic messaging integration
- Gradually add more advanced features
- Test each component before moving to the next

### 2. Use Appropriate Tools for Each Task
- Devin for coding, code analysis, and development
- Hermes for communication, automation, and coordination
- Don't force one tool to do everything

### 3. Leverage Hermes's Learning System
- Let Hermes create skills from complex tasks
- Use memory to store important context
- Take advantage of cross-session recall

### 4. Automate Repetitive Tasks
- Use Hermes cron for scheduled tasks
- Set up automatic notifications
- Create workflows that reduce manual intervention

### 5. Monitor and Iterate
- Check logs regularly
- Gather feedback from team members
- Continuously improve integration patterns

## Conclusion

The integration of Hermes Agent with devin-cli creates a powerful development workflow that combines:

- **Devin's** specialized coding capabilities
- **Hermes's** communication, automation, and learning features
- **MCP's** standardized protocol for tool integration

This combination gives you the best of both worlds: focused coding assistance when you need it, and intelligent automation and communication when you don't. The self-improving nature of Hermes means the integration gets better over time, learning from your workflows and adapting to your needs.

Start with the basic setup, experiment with the workflow examples, and gradually expand to more advanced patterns as you become comfortable with the integration.

## Additional Resources

- **Hermes Documentation**: https://hermes-agent.nousresearch.com/docs/
- **Hermes Discord**: https://discord.gg/NousResearch
- **Devin Documentation**: https://cli.devin.ai/docs/
- **MCP Specification**: https://modelcontextprotocol.io/

## License

MIT License - See respective project licenses for details.