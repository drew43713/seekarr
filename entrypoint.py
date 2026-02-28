#!/usr/bin/env python3
import json
import os
import shlex
import subprocess
import sys
import time
from urllib import request


# Ensure startup messages appear immediately in container logs
from functools import partial
print = partial(print, flush=True)

CONFIG = os.environ.get("SEEKARR_CONFIG", "/config/config.json")


def load_cfg(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    # Build minimal config from environment when config file is absent
    print(f"[startup] config not found at {path}; building config from environment")
    cfg = {
        "sonarr": {
            "base_url": os.environ.get("SEEKARR_SONARR_BASE_URL", ""),
            "base_url_env": "SEEKARR_SONARR_BASE_URL",
            "api_key": os.environ.get("SEEKARR_SONARR_API_KEY", ""),
            "api_key_env": "SEEKARR_SONARR_API_KEY",
            "enabled": _env_bool("SEEKARR_SONARR_ENABLED", True),
        },
        "radarr": {
            "base_url": os.environ.get("SEEKARR_RADARR_BASE_URL", ""),
            "base_url_env": "SEEKARR_RADARR_BASE_URL",
            "api_key": os.environ.get("SEEKARR_RADARR_API_KEY", ""),
            "api_key_env": "SEEKARR_RADARR_API_KEY",
            "enabled": _env_bool("SEEKARR_RADARR_ENABLED", True),
        },
        "limits": {
            "max_series_searches_per_run": int(os.environ.get("SEEKARR_MAX_SERIES_SEARCHES", "25")),
            "max_movie_searches_per_run": int(os.environ.get("SEEKARR_MAX_MOVIE_SEARCHES", "25")),
            "max_upgrade_episode_searches_per_run": int(os.environ.get("SEEKARR_MAX_UPGRADE_EPISODES", "200")),
            "max_upgrade_movie_searches_per_run": int(os.environ.get("SEEKARR_MAX_UPGRADE_MOVIES", "50")),
            "skip_if_queue_over": int(os.environ.get("SEEKARR_SKIP_IF_QUEUE_OVER", "200")),
        },
        "upgrades": {
            "enabled": _env_bool("SEEKARR_UPGRADES_ENABLED", True),
        },
        "runtime": {
            "run_as_cron": _env_bool("SEEKARR_RUN_AS_CRON", True),
            "cron_schedule": os.environ.get("SEEKARR_CRON_SCHEDULE", "0 */12 * * *"),
            "dry_run": _env_bool("SEEKARR_DRY_RUN", False),
            "timezone": os.environ.get("SEEKARR_TIMEZONE", "UTC"),
        },
    }

    # Persist generated config so manual runs with --config path also work
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
            f.write("\n")
        print(f"[startup] wrote generated config to {path}")
    except Exception as e:
        print(f"[startup] warning: could not write generated config to {path}: {e}")

    return cfg


def _env_bool(name, default):
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _check_api(base_url, api_key, label, retries=6, delay=5):
    url = f"{base_url.rstrip('/')}/system/status"
    for i in range(1, retries + 1):
        try:
            req = request.Request(url, headers={"X-Api-Key": api_key})
            with request.urlopen(req, timeout=10) as r:
                if r.status == 200:
                    print(f"[startup] {label} API OK ({url})")
                    return True
        except Exception as e:
            print(f"[startup] {label} API check failed attempt {i}/{retries}: {e}")
            time.sleep(delay)
    return False


def _boot_banner():
    from seekarr import __version__
    print("[seekarr] ========================================")
    print(f"[seekarr] Booting Seekarr v{__version__}")
    print("[seekarr] Scanning for missing + cutoff candidates")
    print("[seekarr] ========================================")


def startup_checks(cfg):
    strict = _env_bool("SEEKARR_STARTUP_STRICT", True)

    if os.path.exists(CONFIG):
        print(f"[startup] config loaded: {CONFIG}")
    else:
        print(f"[startup] using environment-derived config (no file at {CONFIG})")

    ok = True
    sonarr = cfg.get("sonarr", {})
    radarr = cfg.get("radarr", {})

    if sonarr.get("enabled"):
        s_key = os.environ.get(sonarr.get("api_key_env", "SEEKARR_SONARR_API_KEY"), sonarr.get("api_key", ""))
        s_url = os.environ.get(sonarr.get("base_url_env", "SEEKARR_SONARR_BASE_URL"), sonarr.get("base_url", ""))
        if not s_key:
            print("[startup] Sonarr enabled but API key missing")
            ok = False
        elif not s_url:
            print("[startup] Sonarr enabled but base_url missing")
            ok = False
        else:
            ok = _check_api(s_url, s_key, "sonarr") and ok

    if radarr.get("enabled"):
        r_key = os.environ.get(radarr.get("api_key_env", "SEEKARR_RADARR_API_KEY"), radarr.get("api_key", ""))
        r_url = os.environ.get(radarr.get("base_url_env", "SEEKARR_RADARR_BASE_URL"), radarr.get("base_url", ""))
        if not r_key:
            print("[startup] Radarr enabled but API key missing")
            ok = False
        elif not r_url:
            print("[startup] Radarr enabled but base_url missing")
            ok = False
        else:
            ok = _check_api(r_url, r_key, "radarr") and ok

    if not ok and strict:
        print("[startup] strict mode enabled; refusing to continue")
        return False

    if not ok:
        print("[startup] checks failed, continuing because SEEKARR_STARTUP_STRICT=false")
    else:
        print("[startup] all checks passed")
    return True


def main():
    _boot_banner()
    cfg = load_cfg(CONFIG)
    runtime = cfg.get("runtime", {})

    run_as_cron = _env_bool("SEEKARR_RUN_AS_CRON", bool(runtime.get("run_as_cron", False)))
    cron_schedule = os.environ.get("SEEKARR_CRON_SCHEDULE", runtime.get("cron_schedule", "0 */12 * * *"))
    dry_run = _env_bool("SEEKARR_DRY_RUN", bool(runtime.get("dry_run", False)))
    timezone = os.environ.get("SEEKARR_TIMEZONE", runtime.get("timezone", "UTC"))

    # Apply container/process timezone for cron scheduling and log timestamps where supported
    if timezone:
        os.environ["TZ"] = timezone
        try:
            time.tzset()
        except Exception:
            pass

    if not startup_checks(cfg):
        sys.exit(1)

    cmd_parts = ["python", "/app/seekarr.py", "--config", CONFIG]
    if dry_run:
        cmd_parts.append("--dry-run")
    cmd = " ".join(shlex.quote(p) for p in cmd_parts)

    if run_as_cron:
        # Route cron output to container stdout/stderr; seekarr.py handles persistent file logging itself.
        line = f"{cron_schedule} {cmd} >> /proc/1/fd/1 2>> /proc/1/fd/2"
        os.makedirs("/etc/crontabs", exist_ok=True)
        os.makedirs("/logs", exist_ok=True)
        with open("/etc/crontabs/root", "w", encoding="utf-8") as f:
            if timezone:
                f.write(f"CRON_TZ={timezone}\n")
                f.write(f"TZ={timezone}\n")
            f.write(line + "\n")

        ready_msg = (
            f"[seekarr] READY: cron scheduler active | schedule='{cron_schedule}' "
            f"| tz='{timezone}' | dry_run={str(dry_run).lower()}"
        )
        print(ready_msg)
        with open("/logs/seekarr.log", "a", encoding="utf-8") as f:
            f.write(ready_msg + "\n")

        os.execvp("crond", ["crond", "-f", "-l", "8"])
    else:
        print(f"[seekarr] READY: once mode | cmd={cmd}")
        rc = subprocess.call(cmd_parts)
        sys.exit(rc)


if __name__ == "__main__":
    main()
