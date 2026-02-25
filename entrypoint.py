#!/usr/bin/env python3
import json
import os
import subprocess
import sys

CONFIG = os.environ.get("SEEKARR_CONFIG", "/config/config.json")


def load_cfg(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _env_bool(name, default):
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def main():
    cfg = load_cfg(CONFIG)
    runtime = cfg.get("runtime", {})

    run_as_cron = _env_bool("SEEKARR_RUN_AS_CRON", bool(runtime.get("run_as_cron", False)))
    cron_schedule = os.environ.get("SEEKARR_CRON_SCHEDULE", runtime.get("cron_schedule", "0 */12 * * *"))
    dry_run = _env_bool("SEEKARR_DRY_RUN", bool(runtime.get("dry_run", False)))

    cmd = f"python /app/seekarr.py --config {CONFIG}"
    if dry_run:
        cmd += " --dry-run"

    if run_as_cron:
        line = f"{cron_schedule} {cmd} >> /logs/seekarr.log 2>&1"
        os.makedirs("/etc/crontabs", exist_ok=True)
        with open("/etc/crontabs/root", "w", encoding="utf-8") as f:
            f.write(line + "\n")
        print(f"[seekarr] cron mode enabled: {line}")
        os.execvp("crond", ["crond", "-f", "-l", "8"])
    else:
        print(f"[seekarr] once mode: {cmd}")
        rc = subprocess.call(cmd, shell=True)
        sys.exit(rc)


if __name__ == "__main__":
    main()
