# Seekarr

![Seekarr banner](./assets/social-preview-1280x640.png)

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
  - Rotating search windows for missing **and cutoff-upgrade** items (prevents re-searching only the first N each run)
  - Persistent state file (`/config/seekarr_state.json` by default)
  - Per-run formatted logs with selected title lists and command counts
  - Run-window change reporting (grab/import counts + imported titles)
  - Log retention guard keeps only the most recent 4 run blocks in `/logs/seekarr.log`
  - Config/env-driven runtime (one-shot or cron mode in Docker)

### Rotation behavior

Seekarr uses persistent offsets to rotate each category independently:
- Sonarr missing series
- Radarr missing movies
- Sonarr cutoff-upgrade episodes
- Radarr cutoff-upgrade movies

On each run, Seekarr:
1. takes the next batch up to your per-run limits,
2. advances offsets,
3. wraps to the beginning when reaching the end.

This means repeated runs **cycle across the full eligible library over time** rather than repeatedly searching only the first N items.

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
      # Optional but recommended: mount config.json if you want a persistent editable file.
      # Behavior:
      # - If /config/config.json exists, Seekarr loads it first.
      # - Then env overrides are applied (env values take precedence).
      # - If /config/config.json is missing, Seekarr auto-builds it from env values at startup.
      - ./config.json:/config/config.json
      - ./logs:/logs
    environment:
      - SEEKARR_CONFIG=/config/config.json
      - SEEKARR_RUN_AS_CRON=true
      - SEEKARR_CRON_SCHEDULE=0 */12 * * *
      - SEEKARR_DRY_RUN=false
      - SEEKARR_TIMEZONE=America/New_York
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

This reads local `config.json` (if mounted), applies env overrides, and writes logs to `./logs/seekarr.log`.

Config precedence summary:
1. Built-in defaults
2. `config.json` values
3. Environment variables (highest priority)

## Files

- `seekarr.py` — main runner
- `config.example.json` — config template
- `Dockerfile` — container image
- `entrypoint.py` — runtime launcher (once/cron mode)
- `docker-compose.example.yml` — local container example

## Config options

- `upgrades.enabled`: enable cutoff upgrade searches
- `runtime.run_as_cron`: if `true`, container starts `crond`
- `runtime.cron_schedule`: cron expression (default `0 */12 * * *`, twice daily)
- `runtime.timezone`: timezone used for cron schedule interpretation (default `UTC`, e.g. `America/New_York`)
  - Example: `"timezone": "America/New_York"`
- `runtime.dry_run`: if `true`, cron jobs run in dry-run mode
- `state.path`: state file for rotation offsets (default `/config/seekarr_state.json`)

Environment overrides for runtime:
- `SEEKARR_RUN_AS_CRON=true|false`
- `SEEKARR_CRON_SCHEDULE="0 */12 * * *"`
- `SEEKARR_DRY_RUN=true|false`
- `SEEKARR_TIMEZONE=UTC|America/New_York|...` (overrides `runtime.timezone`)
- `SEEKARR_UPGRADES_ENABLED=true|false`
- `SEEKARR_STARTUP_STRICT=true|false` (default `true`)

## Startup checks

On container boot, Seekarr validates:
- config file exists/loads (or builds config from env if file is missing)
- if file is missing, Seekarr writes a generated `/config/config.json` from env values
- Sonarr API connectivity (`/system/status`)
- Radarr API connectivity (`/system/status`)

If checks fail and `SEEKARR_STARTUP_STRICT=true`, container exits instead of silently running broken.

## Boot/ready visibility

Seekarr prints a startup banner and an explicit ready line:
- `READY: cron scheduler active ...` in `docker logs`
- same ready line is appended to `/logs/seekarr.log`
- cron run output is mirrored to both `docker logs` and `/logs/seekarr.log`
