# MOON-AI — AI-Enabled VS Code Setup

## AI Features Available

This project is configured for **AI-assisted development** using multiple AI tools integrated with VS Code:

| AI Tool | Status | Usage |
|---------|--------|-------|
| **GitHub Copilot** | ✅ Enabled | Inline code suggestions, chat |
| **hermes ACP** | ✅ Enabled | AI agent tasks, code generation |
| **Claude Code** | ✅ Installed | Advanced code analysis, debugging |

### Available AI Commands (via Tasks)

| Task | Description |
|------|-------------|
| `AI: Generate code with hermes` | Generate code for file patterns |
| `AI: Explain code` | Explain project architecture |
| `hermes: Run AI task` | Run a command through the hermes AI agent |
| `MCP: Start server` | Start hermes ACP server for VS Code MCP integration |

### AI Model Configuration

- **Primary model**: GPT-Image-2 (via Nous Research inference API)
- **Fallback model**: Solar Mini (via Upstage AI)
- **Provider**: inference-api.nousresearch.com

## Build Commands

```bash
make build      # Build the package
make run        # Run the agent in terminal mode
make serve      # Start the web UI terminal
make test       # Run tests
make verify     # Verify deployment
make clean      # Clean artifacts
```

## AI Feature Access

1. **GitHub Copilot Chat**: `Ctrl+Shift+I` or click the chat icon
2. **hermes Agent**: Use the `hermes: Run AI task` task to ask the AI anything
3. **MCP Integration**: Run `MCP: Start server` task to enable MCP server
4. **Agent Mode**: `hermes -q "task description" --oneshot` for one-shot AI tasks

## Project Structure

```
MOON-AI/
├── .vscode/          # VS Code configuration (AI features included)
├── main.py           # Main entry point
├── moon/             # Core MOON module
├── app/              # Application modules
├── tests/            # Unit tests
├── .venv/            # Virtual environment (gitignored)
└── README.md         # Project documentation
```

## Quick Start

```bash
# 1. Open this folder in VS Code
code /home/meow/Projects/MOON

# 2. Install recommended extensions (VS Code will prompt)

# 3. Build the project
#    Press Ctrl+Shift+P, type "Tasks: Run Task", select "MOON: Build"

# 4. Run the agent
#    "Tasks: Run Task" → "MOON: Run"

# 5. Use AI features:
#    - GitHub Copilot chat: Ctrl+Shift+I
#    - hermes AI tasks: "Tasks: Run Task" → "hermes: Run AI task"
