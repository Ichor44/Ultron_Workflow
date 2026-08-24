# Ultron Workflow

A modular AI agent platform combining an LLM-powered agent core, a parallel web-scraping sub-bot swarm, and a pantheon of specialized sub-agents — deployable via Docker with a built-in self-update system.

## Repository layout

```
Ultron_Workflow/
├── ultron-deploy/       Main application (deploy this)
│   ├── agent.py         CLI entry point
│   ├── web.py           Web UI server (Flask/WebSocket)
│   ├── core/            Engine: LLM routing, memory, plugins,
│   │                    skills loader, sandbox, voice, self-updater
│   ├── skills/          Built-in skills (Protein Lab, DNA Lab, Boltz-2,
│   │                    TTS/ASR, web crawler, Obsidian memory, ...)
│   ├── recipes/         Multi-step workflow recipes
│   ├── webui/           Browser interface
│   └── Dockerfile       Single-container deployment
├── ultron_sub_bots/     Sub-Bot Manager package
│   └── ...              Parallel scraping/crawling/search workers
│                        built on Firecrawl (see its README for API docs)
├── sub_agents/          Sub-agent definitions + collaboration contract
├── docs/                Full documentation
│   ├── ULTRON_COMPLETE_DOCUMENTATION.md
│   ├── SUBAGENTS_GUIDE.md
│   └── OPTIMIZATION_SUMMARY.md
└── requirements.txt     Python dependencies
```

## Quick start (Docker)

Requirements: [Docker Desktop](https://www.docker.com/products/docker-desktop/) and Git.

```bash
git clone https://github.com/Ichor44/Ultron_Workflow.git ultron
cd ultron/ultron-deploy

cp .env.example .env        # Windows: copy .env.example .env
```

Edit `.env` and add your own API keys (OpenRouter / OpenAI / Anthropic, etc.).
No keys are bundled — everyone brings their own. Keys can also be entered later
via the UI settings; they are saved to `.env` automatically.

```bash
docker compose up -d --build
```

Open **http://localhost:5000**

### Self-update system

Each running instance checks the cloud repo on page load. When a new version is
pushed, the **UPDATE** button in the header lights up — click it and Ultron pulls
the new code, reinstalls dependencies if needed, restarts itself, and reloads.
User data (`data/`, `output/`, `logs/`) and `.env` keys are never touched by updates.

See [`ultron-deploy/README.md`](ultron-deploy/README.md) for the full deployment
and maintainer guide.

## Quick start (local, no Docker)

```bash
cd ultron-deploy
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt

copy .env.example .env          # add your API keys
python web.py                   # open http://localhost:5000
```

## Sub-bots

`ultron_sub_bots` is the parallel execution layer: specialized worker bots
(ScrapeBot, CrawlBot, SearchBot, MapBot, InteractBot, MonitorBot, DownloadBot)
that run concurrently through a thread pool and chain into multi-step workflows
(e.g. search → scrape → extract). It requires the Firecrawl CLI:

```bash
npm install -g firecrawl
```

Usage example:

```python
from ultron_sub_bots import SubBotManager, quick_scrape

print(quick_scrape("https://example.com"))

with SubBotManager(max_workers=4) as manager:
    task = manager.create_crawl_task("https://docs.python.org/3/", max_depth=2, limit=50)
    results = manager.run(task)
```

Full API reference: [`ultron_sub_bots/README.md`](ultron_sub_bots/README.md)
and [`ultron_sub_bots/ULTRON_DOCUMENTATION.md`](ultron_sub_bots/ULTRON_DOCUMENTATION.md).

## Sub-agents

The `sub_agents/` folder defines the agent roster — each `.md` file is a
specialized persona (research, planning, engineering, testing, biology,
design, orchestration, ...) that can be dispatched by the core agent.
Collaboration rules and reporting requirements live in
[`sub_agents/SUBAGENT_CONTRACT.md`](sub_agents/SUBAGENT_CONTRACT.md);
usage patterns in [`docs/SUBAGENTS_GUIDE.md`](docs/SUBAGENTS_GUIDE.md).

## Configuration

All configuration is environment-based (`.env`). Key variables:

| Variable | Purpose |
|---|---|
| `OPENROUTER_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | LLM providers (at least one required) |
| `FIRECRAWL_API_KEY` | Web scraping / sub-bots |
| `NVIDIA_API_KEY` | Boltz-2 protein structure prediction & Evo-2 genomics |
| `TELEGRAM_BOT_TOKEN` | Telegram bridge (optional) |
| `ULTRON_REPO_URL` | Git URL used by the self-update system |

See `ultron-deploy/.env.example` for the complete list with comments.

## Documentation

- [`docs/ULTRON_COMPLETE_DOCUMENTATION.md`](docs/ULTRON_COMPLETE_DOCUMENTATION.md) — full system documentation
- [`docs/OPTIMIZATION_SUMMARY.md`](docs/OPTIMIZATION_SUMMARY.md) — performance notes
- [`ultron-deploy/README.md`](ultron-deploy/README.md) — deployment details & troubleshooting

## License

MIT — see [LICENSE](LICENSE).
