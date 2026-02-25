# Seekarr

![Seekarr banner](./social-preview-1280x640.png)

Seekarr is a lightweight Sonarr/Radarr automation worker focused on two jobs:

1. **Find missing media** and trigger searches for missing episodes/movies.
2. **Upgrade existing media to quality cutoff** (when enabled) by searching items below cutoff.

## What Seekarr does

- **Missing media recovery**
  - Search missing episodes in Sonarr
  - Search missing movies in Radarr
- **Quality upgrades to cutoff**
  - Find items below cutoff and trigger upgrade searches (when enabled)
- **Safe automation controls**
  - Queue-aware safety caps
  - Config/env-driven runtime (one-shot or cron mode in Docker)

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
- `SEEKARR_STARTUP_STRICT=true|false` (default `true`)

## Startup checks

On container boot, Seekarr now validates:
- config file exists/loads (or builds config from env if file is missing)
- if file is missing, Seekarr writes a generated `/config/config.json` from env values
- Sonarr API connectivity (`/system/status`)
- Radarr API connectivity (`/system/status`)

If checks fail and `SEEKARR_STARTUP_STRICT=true`, container exits instead of silently running broken.

## Boot/ready visibility

Seekarr now prints a startup banner and an explicit ready line:
- `READY: cron scheduler active ...` in `docker logs`
- same ready line is appended to `/logs/seekarr.log`

### Secrets / API keys and endpoints

Do **not** commit real API keys.

You can set values in `config.json` (local only, gitignored) or prefer env vars:

- `SEEKARR_SONARR_BASE_URL`
- `SEEKARR_RADARR_BASE_URL`
- `SEEKARR_SONARR_API_KEY`
- `SEEKARR_RADARR_API_KEY`
- `SEEKARR_UPGRADES_ENABLED=true|false`

`config.example.json` includes `*_env` fields so users can override both API keys and base URLs via env vars.

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
      # Optional: keep this mount if you want a persistent editable config file.
      # If missing, Seekarr auto-generates /config/config.json from env vars at boot.
      - ./config.json:/config/config.json
      - ./logs:/logs
    environment:
      - SEEKARR_CONFIG=/config/config.json
      - SEEKARR_RUN_AS_CRON=true
      - SEEKARR_CRON_SCHEDULE=0 */12 * * *
      - SEEKARR_DRY_RUN=false
      - SEEKARR_UPGRADES_ENABLED=true
      - SEEKARR_STARTUP_STRICT=true
      - SEEKARR_SONARR_BASE_URL=http://sonarr:8989/api/v3
      - SEEKARR_RADARR_BASE_URL=http://radarr:7878/api/v3
      - SEEKARR_SONARR_API_KEY=your_key_here
      - SEEKARR_RADARR_API_KEY=your_key_here
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
