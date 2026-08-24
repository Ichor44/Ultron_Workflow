# Ultron — Complete System Documentation

> **A self-improving AI agent with persistent memory, skill learning, web UI, voice, and parallel web scraping. Think of it as your personal Jarvis — but with more sarcasm and the ability to write its own tools.**

---

## 📖 Table of Contents

1. [What is Ultron?](#what-is-ultron)
2. [Architecture Overview](#architecture-overview)
3. [Core Capabilities](#core-capabilities)
4. [Getting Started](#getting-started)
5. [Command Reference (All Commands)](#command-reference-all-commands)
6. [Web UI](#web-ui)
7. [Memory & Persistence](#memory--persistence)
8. [Skills System](#skills-system)
9. [Recipes (Markdown Workflows)](#recipes-markdown-workflows)
9. [Voice & TTS](#voice--tts)
10. [Model Configuration](#model-configuration)
11. [Obsidian Vault Integration](#obsidian-vault-integration)
12. [Ultron Sub-Bots (Parallel Web Scraping)](#ultron-sub-bots-parallel-web-scraping)
13. [Proposals & Code Changes](#proposals--code-changes)
14. [MCP Server Integration](#mcp-server-integration)
15. [Protein Lab](#protein-lab)
16. [Caching & Performance](#caching--performance)
17. [Troubleshooting](#troubleshooting)
18. [File Structure](#file-structure)

---

## What is Ultron?

**In plain English:** Ultron is an AI agent that runs on your computer. You talk to it, give it goals, and it figures out how to accomplish them. It remembers things about you, learns new skills, can speak aloud, has a web interface, and can even browse the web and scrape sites in parallel.

**Technically:** A Python-based autonomous agent with:
- **LLM integration** (OpenRouter, OpenAI, Anthropic, local models via Ollama/LM Studio)
- **Persistent memory** (facts, notes, reminders with background save thread)
- **Skill system** (auto-discovered Python modules with trigger matching)
- **Recipe system** (Markdown workflows you teach it)
- **Proposal system** (human-in-the-loop for new skills/code changes)
- **Web UI** (Flask + cached responses, WebSocket-free polling)
- **Voice/TTS** (Edge TTS + Windows SAPI fallback)
- **Obsidian vault** integration (read/write/search notes)
- **Ultron Sub-Bots** (parallel Firecrawl-based web scraping)
- **MCP support** (dynamic Model Context Protocol servers)
- **Protein Lab** (bioinformatics/structure prediction tools)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        ULTRON SYSTEM                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │  CLI Entry   │    │   Web UI     │    │  Background      │  │
│  │  (agent.py)  │    │   (web.py)   │    │  Services        │  │
│  └──────┬───────┘    └──────┬───────┘    │  • Reminder      │  │
│         │                   │            │    Service       │  │
│         ▼                   ▼            │  • MCP Servers   │  │
│  ┌─────────────────────────────────┐    │  • Cache Warmup  │  │
│  │         CORE ENGINE             │    └──────────────────┘  │
│  │  (core/engine.py - Agent)       │                          │
│  │  • LLM Client (core/llm.py)     │    ┌──────────────────┐  │
│  │  • Tool Dispatcher              │    │   DATA LAYER     │  │
│  │  • Auto-Skill Matching          │    │  • Memory        │  │
│  │  • Proposal Approval            │    │    (data/store.json)│  │
│  └──────────────┬──────────────────┘    │  • Skills        │  │
│                 │                       │    (skills/*.py) │  │
│         ┌───────┼───────┐               │  • Recipes       │  │
│         ▼       ▼       ▼               │    (recipes/*.md)│  │
│  ┌────────┐ ┌───────┐ ┌────────┐        │  • Proposals     │  │
│  │Memory  │ │Skills │ │Recipes │        │    (proposals/)  │  │
│  └────────┘ └───────┘ └────────┘        │  • Output Files  │  │
│         │       │       │               │    (output/)     │  │
│         ▼       ▼       ▼               │  • Config (.env) │  │
│  ┌─────────────────────────────────┐    └──────────────────┘  │
│  │         EXTERNAL TOOLS          │                          │
│  │  • Web Search (DuckDuckGo)      │    ┌──────────────────┐  │
│  │  • Vault (Obsidian)             │    │  ULTRON SUB-BOTS │  │
│  │  • Firecrawl (Sub-Bots)         │    │  (ultron_sub_bots/)  │
│  │  • TTS (Edge/SAPI)              │    │  • ScrapeBot     │  │
│  │  • MCP Servers                  │    │  • CrawlBot      │  │
│  │  • Protein Lab (Boltz/ESM)      │    │  • SearchBot     │  │
│  └─────────────────────────────────┘    │  • MapBot        │  │
│                                         │  • InteractBot   │  │
│                                         │  • MonitorBot    │  │
│                                         │  • DownloadBot   │  │
│                                         └──────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Core Capabilities

| Capability | Description | How to Use |
|------------|-------------|------------|
| **Chat / Goal Execution** | Conversational or single-goal mode | `python agent.py chat` or `python agent.py chat "goal"` |
| **Web UI** | Browser-based chat with approvals | `python agent.py ui` → http://localhost:5000 |
| **Persistent Memory** | Facts, notes, reminders across sessions | Automatic; use `brief` command to view |
| **Skill Learning** | Auto-discovers Python skills in `skills/` | `list-skills`, `run-skill NAME` |
| **Vault Skill Catalog** | 900+ pre-built skills across 11 categories | `search_vault_skills` tool |
| **Recipes** | Markdown workflows you teach it | `list-recipes`, `use_recipe` tool |
| **Proposals** | Human approval for new skills/code | `review` command |
| **Voice/TTS** | Speaks responses aloud | `--speak` flag or Web UI voice settings |
| **Model Config** | Multiple providers, custom models | `set-model`, `add-model`, `list-models` |
| **Obsidian Vault** | Read/write/search notes | `vault_read`, `vault_write`, `vault_search` tools |
| **Parallel Scraping** | Firecrawl-based sub-bots | `ultron_sub_bots` package / `ultron` CLI |
| **MCP Servers** | Dynamic Model Context Protocol | Web UI MCP panel |
| **Protein Lab** | Bioinformatics/structure prediction | Web UI Protein Lab panel |
| **Output Files** | Generate any file type | `write_output_file` tool |

---

## Getting Started

### Prerequisites

1. **Python 3.10+** (3.13 recommended)
2. **Node.js + npm** (for Firecrawl CLI)
3. **Firecrawl CLI**: `npm install -g firecrawl`
4. **API Keys** (at least one):
   - OpenRouter (recommended): `OPENROUTER_API_KEY`
   - OpenAI: `OPENAI_API_KEY`
   - Anthropic: `ANTHROPIC_API_KEY`
   - Or local: Ollama/LM Studio (no key needed)

### Installation

```bash
# Clone / navigate to project
cd A.G.E.N.T

# Install Python dependencies
pip install -r requirements.txt

# Install Firecrawl for web scraping
npm install -g firecrawl

# Set API key (PowerShell)
$env:OPENROUTER_API_KEY = "your-key"

# Or create .env file from example
copy .env.example .env
# Edit .env with your keys
```

### First Run

```bash
# Quick test (offline mock mode)
python agent.py chat --mock "Hello Ultron"

# Interactive chat
python agent.py chat

# Web UI
python agent.py ui
# Opens http://127.0.0.1:5000

# Set up a real model
python agent.py set-model openrouter openai/gpt-4o-mini --key YOUR_KEY
```

---

## Command Reference (All Commands)

### 🎯 Primary Commands

| Command | Syntax | Description | Use Case |
|---------|--------|-------------|----------|
| **chat** | `python agent.py chat [goal]` | Interactive chat or single goal | Main interaction mode |
| **ui** | `python agent.py ui` | Launch web UI | Browser-based chat, approvals, voice |
| **serve** | `python agent.py serve [--interval N]` | Background reminder service | Proactive notifications |

### 💬 Chat Flags

| Flag | Description | Example |
|------|-------------|---------|
| `--mock` | Use offline mock LLM (no API key) | `python agent.py chat --mock "test"` |
| `--auto` | Auto-approve proposals (skip review) | `python agent.py chat --auto "make skill"` |
| `--speak` | Enable Windows TTS for this session | `python agent.py chat --speak` |

### 🧠 Memory & Status

| Command | Syntax | Description | Use Case |
|---------|--------|-------------|----------|
| **brief** | `python agent.py brief` | Full status briefing | Check skills, reminders, facts, notes |
| **notify** | `python agent.py notify` | Show due reminder toasts | Manual reminder check |

### 🔧 Skill Management

| Command | Syntax | Description | Use Case |
|---------|--------|-------------|----------|
| **list-skills** | `python agent.py list-skills` | List all learned skills | See what Ultron can do |
| **run-skill** | `python agent.py run-skill NAME [args-json]` | Execute a skill directly | Test skills, automation |
| **list-recipes** | `python agent.py list-recipes` | List Markdown recipes | See taught workflows |

### ⚙️ Model Configuration

| Command | Syntax | Description | Use Case |
|---------|--------|-------------|----------|
| **set-model** | `python agent.py set-model [provider] [model] [--key KEY]` | Configure LLM provider/model | Switch models, first-time setup |
| **add-model** | `python agent.py add-model --name NAME --url URL --key KEY --model MODEL` | Add custom OpenAI-compatible model | Ollama, LM Studio, vLLM, Together.ai |
| **list-models** | `python agent.py list-models` | Show all configured models | See available models |
| **show-config** | `python agent.py show-config` | Display config (keys masked) | Debug configuration |

### 🔄 Proposals & Review

| Command | Syntax | Description | Use Case |
|---------|--------|-------------|----------|
| **review** | `python agent.py review` | Review pending proposals | Approve/reject skill/code changes |

### 🌙 Fun / Experimental

| Command | Syntax | Description | Use Case |
|---------|--------|-------------|----------|
| **dream** | `python agent.py dream` | Connect memories via web search | Serendipitous connections |

---

## Web UI

Launch with:
```bash
python agent.py ui
# Opens http://127.0.0.1:5000
```

### Features

| Feature | Description |
|---------|-------------|
| **Chat Interface** | Real-time polling (no WebSockets needed) |
| **Proposal Approvals** | In-browser diff view, approve/reject/edit |
| **Voice Settings** | Enable/disable TTS, select engine/voice/rate/volume |
| **Model Selector** | Switch providers/models from UI |
| **Skills Browser** | Search and execute skills |
| **Recipes Manager** | View, create, delete Markdown recipes |
| **Metrics Dashboard** | CPU, memory, disk, network, uptime |
| **MCP Panel** | Connect/disconnect/toggle MCP servers |
| **Protein Lab** | Run bioinformatics actions |
| **Output Files** | List and download generated files |
| **Cache Stats** | Hit/miss rates, clear cache |

### Web UI API Endpoints (for integration)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/state` | GET | Current agent state, messages, proposal |
| `/api/chat` | POST | Send message (`{"message": "..."}`) |
| `/api/review/<pid>` | POST | Approve/reject/edit proposal |
| `/api/models` | GET/POST | List/add/activate models |
| `/api/voice` | GET/POST | Voice settings |
| `/api/voice/voices` | GET | List available TTS voices |
| `/api/voice/speak` | POST | Generate speech audio |
| `/api/skills` | GET | List skills |
| `/api/skills/search` | GET | Search skills (`?q=query`) |
| `/api/skills/<name>/execute` | POST | Execute skill |
| `/api/recipes` | GET | List recipes |
| `/api/recipe/<name>` | GET/DELETE | Read or delete recipe |
| `/api/recipe` | POST | Create/update recipe |
| `/api/metrics` | GET | System metrics |
| `/api/mcp/status` | GET | MCP connection status |
| `/api/mcp/servers` | GET | List MCP servers |
| `/api/mcp/toggle` | POST | Toggle MCP server |
| `/api/protein-lab/run` | POST | Run Protein Lab action |
| `/api/output` | GET | List output files |
| `/api/output/<filename>` | GET | Download output file |
| `/api/cache/stats` | GET | Cache statistics |
| `/api/cache/clear` | POST | Clear all caches |
| `/api/launch-terminal` | POST | Launch terminal agent in new window |

---

## Memory & Persistence

### What's Remembered (Across Sessions)

| Type | Description | Commands/Tools |
|------|-------------|----------------|
| **Facts** | Key-value pairs about user | `remember_fact`, `recall_fact` |
| **Notes** | Free-form text notes | `save_note`, `recall_note` |
| **Reminders** | Time-based alerts | `set_reminder`, `list_reminders` |

### Storage

- **File**: `data/store.json`
- **Cache**: In-memory with background write-behind (2s interval)
- **Thread-safe**: `RLock` for concurrent access

### Example Usage

```python
# In chat or skill:
remember_fact("user_name", "Tony")
remember_fact("preferred_language", "Python")
save_note("project_ideas", "Build a sarcastic AI butler")
set_reminder("Check on the drone fleet", 60)  # 60 minutes

# Recall:
recall_fact("user_name")  # "Tony"
recall_fact()  # All facts as JSON
list_reminders()  # Pending reminders
```

### Background Reminder Service

```bash
# Runs every 5 minutes (300s default)
python agent.py serve

# Custom interval
python agent.py serve --interval 60  # Every minute
```

---

## Skills System

### How It Works

1. **Auto-discovery**: Scans `skills/*.py` on startup
2. **Metadata**: Each skill defines `NAME`, `DESCRIPTION`, `TRIGGERS`
3. **Inverted Index**: Fast trigger matching (word → skill mapping)
4. **Auto-match**: Before LLM runs, checks if query matches a skill trigger
5. **Execution**: `execute_skill(name, args)` runs the skill's `run(**kwargs)`

### Skill Structure

```python
# skills/my_skill.py
NAME = "My Skill"
DESCRIPTION = "Does something useful"
TRIGGERS = ["do something", "help with task", "run analysis"]

def run(param1: str, param2: int = 10) -> str:
    """Main entry point - args come from LLM tool call"""
    return f"Result: {param1} x {param2}"
```

### Commands

```bash
# List all skills
python agent.py list-skills

# Run a skill directly (JSON args)
python agent.py run-skill my_skill '{"param1": "hello", "param2": 5}'

# In chat - auto-matched by triggers
# You: "help me do something"
# Ultron: [runs my_skill automatically]
```

### Vault Skill Catalog (900+ Skills)

Pre-built skills across 11 categories:
- **Thinking** - reasoning, planning, analysis
- **Scientific** - research, data analysis, biology
- **Writing** - content generation, editing
- **Analysis** - data processing, statistics
- **Code** - generation, review, refactoring
- **Research** - web search, synthesis
- **Productivity** - task management, automation
- **Creative** - brainstorming, design
- **Communication** - emails, presentations
- **...and more**

**Tools available to LLM:**
- `search_vault_skills(query, top_k)` — Find relevant skills
- `list_vault_skills(category)` — Browse by category
- `read_vault_skill(name)` — Read skill source
- `propose_new_skill` — Compile vault skill to local

---

## Recipes (Markdown Workflows)

### What Are Recipes?

Markdown files in `recipes/` that teach Ultron workflows. Like skills but written in plain text.

### Structure

```markdown
---
name: "Research Topic"
description: "Deep research on any topic"
triggers: "research, deep dive, investigate"
---

# Research Topic Recipe

## Steps

1. Search web for "{{topic}}"
2. Scrape top 5 results
3. Extract key findings
4. Synthesize report
5. Save as markdown file
```

### Commands

```bash
# List recipes
python agent.py list-recipes

# In chat - LLM uses use_recipe tool
# You: "research quantum computing"
# Ultron: [follows recipe steps]
```

### Compile to Skill

```python
# In chat or skill:
compile_recipe("Research Topic")
# Returns recipe + instructions to propose_new_skill
```

---

## Voice & TTS

### Engines Supported

| Engine | Platform | Notes |
|--------|----------|-------|
| **Edge TTS** | Cross-platform | High quality, many voices, async |
| **Windows SAPI** | Windows only | Built-in, no dependencies |

### Configuration

**Web UI:** Settings panel → Voice
- Enable/disable
- Engine: `edge` or `sapi`
- Voice: Select from dropdown (Edge) or system voices (SAPI)
- Rate: -100% to +100%
- Volume: 0-100%

**CLI Flag:**
```bash
python agent.py chat --speak  # Enable for session
```

**Environment (persistent):**
```bash
# .env
VOICE_ENABLED=true
VOICE_ENGINE=edge
VOICE_NAME=en-US-AndrewNeural
VOICE_RATE=0
VOICE_VOLUME=100
```

### Programmatic

```python
from core import voice

# Speak text
voice.speak("Hello sir", engine="edge", voice="en-US-AndrewNeural")

# List voices
voices = voice.list_voices(engine="edge")

# Save settings
voice.save_voice_settings(enabled=True, engine="edge", name="en-US-AndrewNeural")
```

---

## Model Configuration

### Supported Providers

| Provider | Env Var | Model Env | Base URL Env |
|----------|---------|-----------|--------------|
| OpenRouter | `OPENROUTER_API_KEY` | `OPENROUTER_MODEL` | `OPENROUTER_BASE_URL` |
| OpenAI | `OPENAI_API_KEY` | `OPENAI_MODEL` | `OPENAI_BASE_URL` |
| Anthropic | `ANTHROPIC_API_KEY` | `ANTHROPIC_MODEL` | (fixed) |
| Custom | `CUSTOM_API_KEY` | `CUSTOM_MODEL` | `CUSTOM_BASE_URL` |

### Commands

```bash
# First-time setup (saves key)
python agent.py set-model openrouter openai/gpt-4o-mini --key sk-or-xxx

# Switch model (key preserved)
python agent.py set-model openrouter anthropic/claude-3.5-sonnet

# Add custom model (Ollama, LM Studio, vLLM, etc.)
python agent.py add-model --name Ollama --url http://localhost:11434/v1 --key no-key --model llama3

# List all
python agent.py list-models

# Show config (keys masked)
python agent.py show-config
```

### Custom Models (Local/Compatible)

```bash
# Ollama (local)
python agent.py add-model --name Ollama --url http://localhost:11434/v1 --key no-key --model llama3

# LM Studio (local)
python agent.py add-model --name LMStudio --url http://localhost:1234/v1 --key no-key --model local-model

# vLLM
python agent.py add-model --name vLLM --url http://localhost:8000/v1 --key token-abc --model meta-llama/Llama-3-8B

# Together.ai
python agent.py add-model --name Together --url https://api.together.xyz/v1 --key YOUR_KEY --model meta-llama/Llama-3-70B-chat-hf
```

---

## Obsidian Vault Integration

### Setup

1. Set vault path in `.env`:
   ```
   OBSIDIAN_VAULT_PATH=C:/Users/You/Documents/Ultron_brain
   ```

2. Vault tools available to LLM:
   - `vault_read(name)` — Read note
   - `vault_write(name, content)` — Write/update note
   - `vault_search(query)` — Search all notes
   - `vault_list()` — List all notes
   - `vault_remember(content)` — Save fact to vault
   - `vault_recall(query)` — Recall memories

### Example

```python
# In chat:
vault_write("project/alpha", "# Project Alpha\n\nStatus: Active\nPriority: High")
vault_read("project/alpha")
vault_search("priority high")
```

---

## Ultron Sub-Bots (Parallel Web Scraping)

### What Is It?

A separate package (`ultron_sub_bots/`) for parallel Firecrawl-based scraping with 7 specialized sub-bots.

### Installation

```bash
cd ultron_sub_bots
pip install -e .
# Requires: npm install -g firecrawl + FIRECRAWL_API_KEY
```

### Quick Start

```python
from ultron_sub_bots import quick_scrape, quick_crawl, quick_search

# One-liners
quick_scrape("https://example.com")
quick_crawl("https://docs.python.org/3/", max_depth=2, limit=20)
quick_search("AI news 2024", num_results=10)
```

### CLI (installed as `ultron` command)

```bash
ultron scrape https://example.com
ultron crawl https://docs.example.com -d 2 -l 50
ultron search "machine learning" -r 20 -t deep
ultron batch tasks.json
```

### 7 Sub-Bot Types

| Bot | Purpose | Best For |
|-----|---------|----------|
| **ScrapeBot** | Individual URLs | Known pages, extraction |
| **CrawlBot** | Entire sites/sections | Docs, blogs, catalogs |
| **SearchBot** | Web search + content | Research, current events |
| **MapBot** | Discover all URLs | Site audits, SEO |
| **InteractBot** | Browser automation | SPAs, login, clicks |
| **MonitorBot** | Change detection | Price tracking, alerts |
| **DownloadBot** | Offline archives | Docs backup, offline reading |

### Parallel Execution

```python
from ultron_sub_bots import SubBotManager, TaskBatch

with SubBotManager(max_workers=8) as manager:
    # Maximum parallelism - one task per URL
    tasks = TaskBatch.scrape_multiple(urls=["a.com", "b.com", "c.com"])
    manager_tasks = [t.to_task(manager) for t in tasks]
    results = manager.run(manager_tasks)
```

### Workflows

```python
from ultron_sub_bots import create_competitive_analysis_workflow, create_market_research_workflow

# Pre-built
wf = create_competitive_analysis_workflow(["comp1.com", "comp2.com"])
wf = create_market_research_workflow("EV market", num_sources=10)

# Custom
wf = Workflow("my_flow")
wf.add_step("search", lambda prev: [SearchTask(query="AI news")])
wf.add_step("scrape", lambda prev: [ScrapeTask(urls=[...])], depends_on=["search"])
results = wf.execute(manager)
```

### Event Callbacks

```python
manager.on_task_started(lambda t: print(f"🚀 {t.name}"))
manager.on_task_completed(lambda t, r: print(f"✅ {t.name}: {r.urls_processed} URLs"))
manager.on_task_failed(lambda t, r: print(f"❌ {t.name}: {r.error}"))
manager.on_all_completed(lambda results: print(f"🏁 All done: {len(results)} tasks"))
```

---

## Proposals & Code Changes

### How It Works

1. **LLM proposes** new skill or code change via `propose_new_skill` / `propose_edit_skill` / `propose_code_change`
2. **Proposal saved** to `proposals/queue.json` with diff
3. **Human reviews** via `review` command or Web UI
4. **On approve**: File written, skill index rebuilt, cache invalidated

### Commands

```bash
# Review all pending
python agent.py review

# Web UI: /api/review/<pid> POST with {"decision": "approve|reject|edit"}
```

### Proposal Types

| Type | Tool | Use Case |
|------|------|----------|
| New Skill | `propose_new_skill` | Add capability |
| Edit Skill | `propose_edit_skill` | Fix/improve skill |
| Code Change | `propose_code_change` | Modify core files |

---

## MCP Server Integration

### What Is MCP?

Model Context Protocol — standardized way for LLMs to use external tools/services.

### Web UI Management

- **Panel**: MCP Servers in web UI
- **Actions**: Connect, Disconnect, Toggle
- **Status**: Real-time connection state, heartbeats

### API

```bash
# Status
curl http://localhost:5000/api/mcp/status

# List servers
curl http://localhost:5000/api/mcp/servers

# Toggle
curl -X POST http://localhost:5000/api/mcp/toggle -H "Content-Type: application/json" -d '{"server_id": "github"}'
```

### Configuration

MCP servers defined in config (or dynamically added). Each runs as subprocess with stdio transport.

---

## Protein Lab

### What Is It?

Bioinformatics toolkit integrated into Ultron for protein structure prediction and analysis.

### Actions Available

| Action | Description |
|--------|-------------|
| `analyze` | Analyze protein sequence |
| `predict_structure` | Predict 3D structure (Boltz/ESM) |
| `fold` | Run folding simulation |
| `dock` | Protein-ligand docking |
| `help` | List all actions |

### Web UI

- **Panel**: Protein Lab in web UI
- **Run actions** with parameters
- **View results** (structures, metrics, visualizations)

### API

```bash
# Run action
curl -X POST http://localhost:5000/api/protein-lab/run \
  -H "Content-Type: application/json" \
  -d '{"action": "predict_structure", "sequence": "MKL..."}'

# List actions
curl http://localhost:5000/api/protein-lab/actions
```

---

## Caching & Performance

### Cache Layers

| Layer | Backend | TTL | Scope |
|-------|---------|-----|-------|
| **Flask-Caching** | Redis or Memory | 300s | HTTP responses |
| **Core Cache** | Memory (LRU) | Config | Skills, recipes, config, memory |
| **Memory Module** | Write-behind | 2s | Facts, notes, reminders |

### Cache Invalidation

- **Auto**: On skill/recipe/config/voice change
- **Manual**: `/api/cache/clear` POST or Web UI button

### Stats

```bash
# Web UI
curl http://localhost:5000/api/cache/stats

# Output
{
  "flask_cache": {"hits": 150, "misses": 20, "hit_rate_pct": 88.2, "backend": "redis"},
  "core_cache": {"skills": {...}, "recipes": {...}, "memory": {...}}
}
```

### Performance Tips

| Goal | Recommendation |
|------|----------------|
| Faster skill matching | Index auto-built on first use |
| Reduce LLM calls | Auto-skill match runs before LLM |
| Parallel scraping | Use `TaskBatch.scrape_multiple()` |
| Lower latency | Enable Redis for Flask-Caching |
| Memory efficiency | Background save thread batches writes |

---

## Troubleshooting

### Common Issues

| Problem | Solution |
|---------|----------|
| **"No LLM provider configured"** | Run `python agent.py set-model openrouter MODEL --key KEY` or use `--mock` |
| **"Firecrawl CLI not found"** | `npm install -g firecrawl` and ensure `%APPDATA%\npm` in PATH |
| **"API Key not set"** | Check `.env` or `setx VAR_NAME VALUE` |
| **"Skill not found"** | Run `python agent.py list-skills` to see available |
| **"Proposal pending"** | Run `python agent.py review` or check Web UI |
| **Voice not working** | Install `edge-tts`: `pip install edge-tts` |
| **Web UI won't start** | Check port 5000 free: `netstat -an | findstr 5000` |
| **MCP server fails** | Check server command in config, view logs in Web UI |
| **Unicode errors (Windows)** | Code handles UTF-8; set `PYTHONIOENCODING=utf-8` |

### Debug Commands

```bash
# Show config (keys masked)
python agent.py show-config

# List all models
python agent.py list-models

# Test mock mode
python agent.py chat --mock "test"

# Check skills
python agent.py list-skills

# Clear all caches
curl -X POST http://localhost:5000/api/cache/clear
```

### Logs

- **Agent**: Console output (spinner, errors)
- **Web UI**: Console + Flask logs
- **Cache**: `/api/cache/stats`
- **MCP**: Web UI MCP panel shows connection logs

---

## File Structure

```
A.G.E.N.T/
├── agent.py              # CLI entry point, commands, chat loop
├── web.py                # Flask web UI, API endpoints, caching
├── config.py             # Config loading, .env management, model registry
├── requirements.txt      # Python dependencies
├── .env                  # API keys, settings (not committed)
├── .env.example          # Template for .env
├── conv.bat              # Windows batch helper
├── opencode.json         # OpenCode configuration
├── CONVERSATION_SYSTEM.md# Conversation system docs
├── OPTIMIZATION_SUMMARY.md# Performance optimizations
│
├── core/                 # Core engine modules
│   ├── __init__.py
│   ├── engine.py         # Agent class, tool dispatch, LLM loop
│   ├── engine_mcp.py     # MCP integration for agent
│   ├── llm.py            # LLM client (OpenRouter, OpenAI, Anthropic, custom)
│   ├── cache.py          # LRU cache, decorators, monitoring
│   ├── memory.py         # Facts, notes, reminders (cached, write-behind)
│   ├── skills.py         # Skill loading, index, execution
│   ├── skills_db.py      # Vault skill catalog (900+ skills)
│   ├── skills_sh.py      # Skill shell utilities
│   ├── proposals.py      # Proposal system, diff, approval
│   ├── recipes.py        # Markdown recipe management
│   ├── review.py         # Human approval prompts
│   ├── file_output.py    # Output file generation
│   ├── mcp_dynamic.py    # Dynamic MCP server management
│   ├── notify.py         # Windows toast notifications
│   └── voice.py          # TTS (Edge + SAPI)
│
├── skills/               # Learned skills (auto-discovered)
│   ├── hello.py
│   ├── file_find.py
│   ├── sys_info.py
│   ├── web_crawler.py
│   ├── asr_whisper.py
│   ├── tts_speak.py
│   ├── procgen_3d.py
│   ├── bgpt_paper_search.py
│   ├── boltz_2.py
│   ├── protein_lab.py
│   ├── obsidian_memory.py
│   ├── vault_skill_catalog.py
│   └── skill_make_a_new_skill_to_crawl.py
│
├── ultron_sub_bots/      # Parallel web scraping package
│   ├── __init__.py
│   ├── core.py           # UltronCore, task management, parallel exec
│   ├── bots.py           # 7 SubBot implementations
│   ├── manager.py        # SubBotManager, task creators, quick funcs
│   ├── tasks.py          # Task helpers, TaskBatch, Workflow
│   ├── cli.py            # `ultron` CLI command
│   ├── examples.py       # Usage examples
│   ├── pyproject.toml    # Package config
│   └── README.md         # Sub-bots documentation
│
├── webui/                # Web UI static files
│   ├── index.html
│   ├── app.js
│   └── style.css
│
├── data/                 # Persistent data
│   └── store.json        # Memory (facts, notes, reminders)
│
├── proposals/            # Proposal queue
│   └── queue.json        # Pending proposals
│
├── recipes/              # Markdown recipes
│   └── *.md
│
├── output/               # Generated files
│   └── *.csv, *.stl, *.html, etc.
│
├── A.G.E.N.T_brain/      # Obsidian vault (optional)
│   └── *.md
│
└── skills/ (external)    # Additional skill repos (git submodules)
    ├── agent-skills-main/
    ├── awesome-ai-for-science-master/
    └── ... (20+ repos)
```

---

## Quick Reference Card

### Most Used Commands

```bash
# Start chatting
python agent.py chat

# Web UI
python agent.py ui

# Quick goal
python agent.py chat "research quantum computing"

# With voice
python agent.py chat --speak "read me the news"

# Offline test
python agent.py chat --mock "hello"

# Check status
python agent.py brief

# Manage skills
python agent.py list-skills
python agent.py run-skill web_crawler '{"url": "https://example.com"}'

# Configure model
python agent.py set-model openrouter openai/gpt-4o-mini --key YOUR_KEY
python agent.py add-model --name Ollama --url http://localhost:11434/v1 --key no-key --model llama3

# Review proposals
python agent.py review

# Background reminders
python agent.py serve

# Parallel scraping (separate package)
cd ultron_sub_bots && pip install -e .
ultron scrape https://example.com
ultron crawl https://docs.site.com -d 2 -l 50
```

### Key Files to Know

| File | Purpose |
|------|---------|
| `.env` | Your API keys and settings |
| `data/store.json` | Your memories |
| `skills/*.py` | Your custom skills |
| `recipes/*.md` | Your taught workflows |
| `proposals/queue.json` | Pending changes |
| `output/` | Generated files |

---

*Ultron v2.0.0 — "Another crisis averted. You're welcome."*