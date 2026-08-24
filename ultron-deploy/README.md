# Ultron — Docker Pilot Deployment

Single-container deployment of the Ultron web UI with a built-in one-click
self-update system. Each pilot user runs Ultron on their own machine and can
update it from the cloud by clicking **UPDATE** in the header.

## Requirements

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/macOS/Linux)
- Git (for cloning the repo)

## First-time setup

```bash
git clone <REPO_URL> ultron
cd ultron

cp .env.example .env        # Windows: copy .env.example .env
```

Edit `.env` and add **your own** API keys (OpenRouter / OpenAI / Anthropic, etc.).
No keys are bundled — everyone brings their own. You can also enter keys later
via the UI settings; they are saved to `.env` automatically.

Then start:

```bash
docker compose up -d --build
```

Open **http://localhost:5000**

## Updating to the latest version

1. When a new version is pushed to the cloud repo, the **UPDATE** button in the
   header lights up (checked automatically on page load).
2. Click it, confirm, and Ultron pulls the new code from the cloud, reinstalls
   dependencies if they changed, restarts itself, and reloads the page.
3. Your data (`data/`, `output/`, `logs/`) and API keys (`.env`) are never touched
   by updates.

Manual alternative:

```bash
docker compose pull   # not needed for this setup
docker compose up -d --build
```

## For the maintainer: publishing an update

From your dev copy of the repo:

```bash
# 1. bump the version
echo "0.1.1" > VERSION

# 2. commit + push
git add -A
git commit -m "v0.1.1"
git push origin main
```

All running pilot instances pick it up on their next UPDATE click / page load.

## Configuration reference

| Variable | Purpose |
|---|---|
| `ULTRON_REPO_URL` | Git URL updates are pulled from (set in `.env` or compose) |
| `ULTRON_UPDATE_BRANCH` | Branch to track (default `main`) |
| `AGENT_HOST` | Bind address inside container (compose sets `0.0.0.0`) |
| `AGENT_PORT` | Port (default `5000`) |

## Troubleshooting

- **UPDATE button says "not configured"**: `ULTRON_REPO_URL` is empty. Set it in `.env`
  and `docker compose up -d` again.
- **Private repo auth errors**: embed a read-only token in `ULTRON_REPO_URL`
  (`https://<token>@github.com/<user>/<repo>.git`). GitHub fine-grained token with
  *Contents: Read* is enough.
- **Port already in use**: change `"5000:5000"` in `docker-compose.yml` to e.g. `"8080:5000"`.
