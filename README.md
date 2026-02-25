# Seekarr

![Seekarr banner](./social-preview-1280x640.png)

Seekarr is a lightweight automation worker for Sonarr/Radarr.

## v1 Scope

- Search missing episodes in Sonarr
- Search missing movies in Radarr
- Upgrade existing items below quality cutoff (when enabled)
- Queue-aware safety caps
- Config-driven runtime (one-shot or cron mode in Docker)

## Files

- `seekarr.py` — main runner
- `config.example.json` — config template
- `Dockerfile` — container image
- `entrypoint.py` — runtime launcher (once/cron mode)
- `docker-compose.example.yml` — local container example

## Quick Start (host)

```bash
cd /home/adaugherty/.openclaw/workspace/seekarr
cp config.example.json config.json
python3 seekarr.py --config config.json --dry-run
```

## Run live once

```bash
python3 seekarr.py --config config.json
```

## Config options (important)

- `upgrades.enabled`: enable cutoff upgrade searches
- `runtime.run_as_cron`: if `true`, container starts `crond`
- `runtime.cron_schedule`: cron expression (default `0 */12 * * *`, twice daily)
- `runtime.dry_run`: if `true`, cron jobs run in dry-run mode

Environment overrides for runtime:
- `SEEKARR_RUN_AS_CRON=true|false`
- `SEEKARR_CRON_SCHEDULE="0 */12 * * *"`
- `SEEKARR_DRY_RUN=true|false`

### Secrets / API keys

Do **not** commit real API keys.

You can either:
1. set keys in `config.json` (local only, file is gitignored), or
2. use environment variables (preferred):

- `SEEKARR_SONARR_API_KEY`
- `SEEKARR_RADARR_API_KEY`

`config.example.json` includes `api_key_env` fields so users can override keys via env vars.

## Docker Compose (recommended)

Use this as a starting `docker-compose.yml`:

```yaml
services:
  seekarr:
    build:
      context: https://github.com/drew43713/seekarr.git#main
      dockerfile: Dockerfile
    container_name: seekarr
    restart: unless-stopped
    volumes:
      - ./config.json:/config/config.json:ro
      - ./logs:/logs
    environment:
      - SEEKARR_CONFIG=/config/config.json
      - SEEKARR_RUN_AS_CRON=true
      - SEEKARR_CRON_SCHEDULE=0 */12 * * *
      - SEEKARR_DRY_RUN=false
      # - SEEKARR_SONARR_API_KEY=your_key_here
      # - SEEKARR_RADARR_API_KEY=your_key_here
```

Run it:

```bash
docker compose up -d --build
```

This reads local `config.json` and writes logs to `./logs/seekarr.log`.

## Notes

- Start in dry-run and verify output before enabling live mode.
- Sonarr upgrades use `/wanted/cutoff` + `EpisodeSearch`.
- Radarr upgrades use `/wanted/cutoff` + `MoviesSearch`.
