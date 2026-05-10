# ModWatch

Self-hosted Vintage Story mod update tracker. Add mod pages from [mods.vintagestory.at](https://mods.vintagestory.at), get notified when they update, and filter by target VS version to see compatibility at a glance.

## Quick Start

```bash
git clone https://github.com/LoneAngelFayt/vs-modwatch
cd vs-modwatch
docker compose up -d
```

Open `http://localhost:8000`.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:////app/data/mods.db` | SQLAlchemy connection string |
| `DISCORD_WEBHOOK_URL` | — | Discord webhook for update notifications |
| `APPRISE_URL` | — | Apprise notification URL |
| `SCRAPE_INTERVAL_HOURS` | `6` | How often to check all mods |

> **Note:** Changes to `SCRAPE_INTERVAL_HOURS` via the Settings UI take effect after restarting the container. All other settings (webhook URLs) take effect immediately.

Set these in `docker-compose.yml` under `environment:` or as host env vars.

## Storage

**Bind mount (default):** SQLite file is stored at `./data/mods.db` on the host.

```yaml
volumes:
  - ./data:/app/data
```

**Named volume:** Edit `docker-compose.yml` to use Docker-managed storage instead:

```yaml
volumes:
  - modwatch_data:/app/data

volumes:
  modwatch_data:
```

## PostgreSQL

Set `DATABASE_URL` to a Postgres connection string — no code changes required:

```
DATABASE_URL=postgresql://user:password@db-host:5432/modwatch
```

Add `psycopg2-binary` to `requirements.txt` when using a non-Postgres-enabled image.

## Development

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
pytest -v
```

## Roadmap

- Comment parsing for community patches and unofficial compatibility fixes
- One-click download for the latest mod version compatible with the selected target VS version
