#!/usr/bin/env python3
import json
import os
import subprocess
import sys

CONFIG = os.environ.get("SEEKARR_CONFIG", "/config/config.json")


def load_cfg(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    cfg = load_cfg(CONFIG)
    runtime = cfg.get("runtime", {})
    run_as_cron = bool(runtime.get("run_as_cron", False))
    cron_schedule = runtime.get("cron_schedule", "*/30 * * * *")
    dry_run = bool(runtime.get("dry_run", False))

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
