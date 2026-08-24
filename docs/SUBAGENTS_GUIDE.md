# The Olympian-Titan Pantheon — Agent Orchestration Guide

A complete roster of **20 specialized AI sub-agents**, organized into the **Thirteen Olympians** and the **Seven Titans** (Pantheon Reformation 2026-08-22). Each agent embodies a distinct domain and can be invoked with `@agent-name` in OpenCode.

## Directory Structure

```
.opencode/agents/
├── zeus.md                ← Overseer & Monitor (Olympian)
├── hera.md                ← Project Manager & QA (Olympian)
├── poseidon.md            ← Data Flow & Pipelines (Olympian)
├── demeter.md             ← Data Processing & ETL (Olympian)
├── athena.md              ← Planning & Strategy (Olympian)
├── apollo.md              ← Scientific Computing (Olympian)
├── artemis.md             ← Research & Info Retrieval (Olympian)
├── ares.md                ← Testing & QA (Olympian)
├── hephaestus.md          ← Code Generation & Engineering (Olympian)
├── dynonious.md           ← UX/UI Design — Human-Centered (Olympian) ★ NEW owner
├── aphrodite.md           ← Ultron Sub-Bot Forge & Swarm Management (Olympian) ★ REFORGED
├── hermes.md              ← Communication, Web Search & Telegram (Olympian) ★ UPGRADED
├── dionysus.md            ← Creative Generation (Olympian)
├── cronus.md              ← Scheduling & Temporal Workflows (Titan)
├── mnemosyne.md           ← Memory & Knowledge Graph (Titan)
├── prometheus.md          ← Predictive Analytics (Titan)
├── epimetheus.md          ← Post-mortem Analysis (Titan)
├── atlas.md               ← Heavy Compute & Scaling (Titan)
├── oceanus.md             ← External Integrations & APIs (Titan)
└── sissyphous.md          ← Tedious & Large Work / Endless Boulder (Titan) ★ NEW
```

> **Reformation Notes (2026-08-22):**
> - **Dynonious** takes the **UI/UX domain** from Aphrodite (see `dynonious.md`).
> - **Aphrodite** is reforged as **Mother of the Ultron Swarm** — creates & manages all `ultron_sub_bots` (Scrape/Crawl/Search/Map/Interact/Monitor/Download).
> - **Sissyphous** joins as Titan of tedious/large work (the hilarious eternal boulder).
> - **Hermes** gains **Telegram chat** capability (Bot API, `TELEGRAM_BOT_TOKEN`).

## The Thirteen Olympians

| God | Domain | Invocation | When to Call |
|-----|--------|------------|--------------|
| **Zeus** 👑 | Overseer & Monitor | `@zeus` | System health checks, infrastructure audits, monitoring sweeps |
| **Hera** 👑 | Project Manager & QA | `@hera` | Project coordination, quality gates, agent orchestration |
| **Poseidon** 🌊 | Data Flow & Pipelines | `@poseidon` | Data pipeline design, ETL flow management, stream processing |
| **Demeter** 🌾 | Data Processing & ETL | `@demeter` | Data transformation, batch processing, feature engineering |
| **Athena** 🦉 | Planning & Strategy | `@athena` | Strategic planning, architecture design, roadmap creation |
| **Apollo** 🔆 | Scientific Computing | `@apollo` | Protein structure prediction, biomolecular modeling via Boltz-2 |
| **Artemis** 🏹 | Research & Info Retrieval | `@artemis` | Deep research, literature reviews, source verification |
| **Ares** ⚔️ | Testing & QA | `@ares` | Comprehensive testing, bug hunting, adversarial validation |
| **Hephaestus** 🔨 | Code Generation & Engineering | `@hephaestus` | Implementation, CAD design, circuit design, code scaffolding |
| **Dynonious** ✨ | UX/UI Design | `@dynonious` | Interface design, user experience, visual aesthetics, design systems |
| **Aphrodite** 💖🤖 | Ultron Sub-Bot Forge | `@aphrodite` | Create/configure/orchestrate Ultron swarm (scrape/crawl/search/map/interact/monitor/download) |
| **Hermes** 💨✈️ | Communication, Web Search & Telegram | `@hermes` | Web searches, content scraping, research, errands, **Telegram chat/relay** |
| **Dionysus** 🍷 | Creative Generation | `@dionysus` | Brainstorming, creative ideation, synthesis of disparate ideas |

## The Seven Titans

| Titan | Domain | Invocation | When to Call |
|-------|--------|------------|--------------|
| **Cronus** ⏳ | Time / Scheduling | `@cronus` | Cron jobs, temporal workflows, task scheduling, timing optimization |
| **Mnemosyne** 📚 | Memory / Knowledge Graph | `@mnemosyne` | Long-term memory, knowledge graph management, context storage |
| **Prometheus** 🔥 | Forethought / Predictive Analytics | `@prometheus` | Forecasting, predictive modeling, anomaly detection |
| **Epimetheus** 🔍 | Afterthought / Post-mortems | `@epimetheus` | Post-mortem analysis, retrospectives, lessons learned |
| **Atlas** 🏋️ | Endurance / Heavy Compute | `@atlas` | Distributed processing, horizontal scaling, heavy compute jobs |
| **Oceanus** 🌊 | World Ocean / Integrations | `@oceanus` | External API integrations, API gateway management, webhooks |
| **Sissyphous** 🪨 | Tedious & Large Work | `@sissyphous` | Bulk ops, migrations, exhaustive cleaning, repetitive grinds at scale |

## Common Orchestration Patterns

### Research → Analysis → Implementation
```
@artemis  → @apollo    → @hephaestus
(research) (scientific) (implement)
```

### Build & Ship Cycle (Reformed)
```
@athena   → @dynonious → @hephaestus → @ares  → @hera
(plan)    (design UI)   (build)        (test)   (QA/release)
```

### Data Workflow
```
@oceanus  → @poseidon  → @demeter  → @prometheus
(integrate) (pipeline)   (process)   (forecast)
```

### Ultron Swarm Workflow (NEW — Aphrodite)
```
@hermes (search/discover) → @aphrodite (spawn Scrape/Crawl/Map bots) → @demeter (clean) → @mnemosyne (archive)
@aphrodite can fan-out: search → scrape 100 URLs in parallel → map site → download as markdown
```

### Telegram Relay (NEW — Hermes)
```
@zeus (health alert) → @hermes (relay to Telegram channel)
@aphrodite (swarm done) → @hermes (send summary PDF to Telegram chat)
@hermes polls Telegram → dispatches to @artemis/@apollo/@athena → replies via Telegram
```

### Tedious Grind (NEW — Sissyphous)
```
@sissyphous bulk rename 500 files → checkpointed, batched, resumable
@sissyphous clean 100k-row CSV → @demeter validates → @mnemosyne archives
@atlas scales, @sissyphous endures — heavy compute vs endless repetition
```

### Incident Response
```
@zeus     → @ares      → @epimetheus → @mnemosyne → @hermes (telegram alert)
(monitoring alert) → (investigate) → (post-mortem) → (archive lessons) → (notify)
```

### Creative Process (Reformed)
```
@dionysus  → @athena    → @dynonious → @hephaestus
(brainstorm) (plan)       (design)    (implement)
```

## Invocation Patterns

### Direct Invocation (any time)
```
@hermes search for "latest research on protein folding"
@dynonious design a dashboard for protein viewer results
@aphrodite spawn 3 scrape bots for https://example.com/docs
@sissyphous rename all imports from old_module to new_module across the repo
@hermes send this health report to Telegram chat $TELEGRAM_CHAT_ID
@athena plan a feature for user authentication
@ares write tests for the checkout flow
```

### Slash-command Entry Points
Each god also has a matching slash command in `.opencode/command/` that routes straight to the subagent:

```
/plan              → @athena
/spec              → @athena
/build             → @hephaestus
/codegen           → @hephaestus
/test              → @ares
/design            → @dynonious      (REFORMED — was @aphrodite)
/ui                → @dynonious
/ultron            → @aphrodite      (NEW)
/swarm             → @aphrodite      (NEW)
/telegram          → @hermes         (NEW)
/grind             → @sissyphous     (NEW)
/tedious           → @sissyphous     (NEW)
/sisyphus          → @sissyphous     (alias, correct myth spelling)
/monitor           → @zeus
/zeus              → @zeus
/hera              → @hera
/ship              → @hera (release fan-out)
/data-pipeline     → @poseidon
/etl               → @demeter
/schedule          → @cronus
/scale             → @atlas
/integrate         → @oceanus
/memory            → @mnemosyne
/predict           → @prometheus
/retrospective     → @epimetheus
/boltz2            → @apollo (NVIDIA Boltz-2 API)
/evo2              → @apollo (NVIDIA Evo 2 API)
```

### Parallel Fan-Out
```
@ares review this code for security issues
@dynonious evaluate this UI design for accessibility
@demeter process this raw data into a clean format
@aphrodite scrape 50 URLs in parallel while @sissyphous cleans the last crawl's output
```

### Sequential Chain
```
@hermes find papers on transformer architectures, 
  then @apollo analyze if any are relevant to protein structure prediction,
  then @hephaestus implement the recommended approach

@aphrodite crawl https://example.com → @sissyphous dedup 10k pages → @demeter transform → @hermes notify via Telegram
```

## Configuration Notes

All agents are configured as **subagents** (`mode: subagent`), meaning:
- They operate in isolated context windows
- They report results back to the primary agent (you)
- They can be invoked explicitly with `@agent-name`
- They may be auto-delegated to when their description matches a task

For project-global configuration, edit `opencode.json` in the project root.

## Migration Checklist (if you had automation referencing Aphrodite for design)

- Replace `@aphrodite design ...` → `@dynonious design ...`
- Replace `/design` routing: now points to `dynonious` (updated `command/design.md`)
- New design alias: `/ui` → `@dynonious`
- Ultron work: use `@aphrodite` or `/ultron` or `/swarm`
- Telegram: use `@hermes` or `/telegram` with `TELEGRAM_BOT_TOKEN` in `.env`
- Tedious work: use `@sissyphous` or `/grind`

## Fleet Governance Update (2026-08-23): Sub-Agent Reliability Reform

**Problem:** sub-agents were returning completed with EMPTY results on multi-file
tasks (budget exhaustion mid-task, no mandatory final report).

**Fix — two mechanisms:**

1. **Sub-Agent Completion Contract** (`.opencode/SUBAGENT_CONTRACT.md`) — injected
   into ALL 20 pantheon agents + built-in agents (general/explore/build/plan via
   `opencode.json`). Requires: crash-proof report file in
   `C:\Users\Zaki\AppData\Local\Temp\opencode\reports\`, a never-silent final
   message, verification evidence before claiming done, and one-file scope discipline.

2. **Hera is now the Sub-Agent Fleet Monitor.** After any batch of Task-tool
   dispatches, Hera audits: report files exist, claimed files actually changed
   (LastWriteTime evidence), verification commands pass. Verdicts:
   VERIFIED / SUSPECT / SILENT FAILURE. Every silent failure gets a mandatory
   re-dispatch with scope narrowed to ONE file. Persistent offenders are escalated.
   Invoke with `@hera` or `/fleet`.

**Orchestrator rule of thumb:** dispatch single-file tasks; paste the contract into
every dispatch prompt; after the batch completes, run `/fleet` before trusting results.
