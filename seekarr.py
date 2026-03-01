#!/usr/bin/env python3
__version__ = "1.1.0"

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict
from urllib import request, parse, error

TITLE_LOG_LIMIT = None
KEEP_LOG_RUNS = 4
LOG_FILE_PATH = "/logs/seekarr.log"


class _Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            s.write(data)
        return len(data)

    def flush(self):
        for s in self.streams:
            s.flush()


def _enable_dual_logging(path=LOG_FILE_PATH):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        f = open(path, "a", encoding="utf-8", buffering=1)
        sys.stdout = _Tee(sys.__stdout__, f)
        sys.stderr = _Tee(sys.__stderr__, f)
    except Exception as e:
        print(f"[log] warning: could not enable file logging to {path}: {e}")


def api_get(base_url, api_key, path, params=None):
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    if params:
        url += "?" + parse.urlencode(params)
    req = request.Request(url, headers={"X-Api-Key": api_key})
    with request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def api_post(base_url, api_key, path, payload):
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def get_queue_len(app_cfg):
    q = api_get(app_cfg["base_url"], app_cfg["api_key"], "/queue", {"page": 1, "pageSize": 1})
    return int(q.get("totalRecords", 0))


# Command completion waiting intentionally removed to keep runs fast and logs concise.


def _paginate_wanted(app_cfg, endpoint, page_size=1000):
    """Fetch all records from a paginated wanted endpoint."""
    all_recs = []
    page = 1
    while True:
        data = api_get(app_cfg["base_url"], app_cfg["api_key"], endpoint, {"page": page, "pageSize": page_size})
        recs = data.get("records", [])
        all_recs.extend(recs)
        total = int(data.get("totalRecords", 0))
        if len(all_recs) >= total or not recs:
            break
        page += 1
    return all_recs, total


def sonarr_missing_ids(app_cfg):
    recs, total = _paginate_wanted(app_cfg, "/wanted/missing")
    series_ids = sorted({r.get("seriesId") for r in recs if r.get("seriesId") is not None})
    return recs, series_ids


def radarr_missing_ids(app_cfg):
    recs, total = _paginate_wanted(app_cfg, "/wanted/missing")
    movie_ids = sorted(
        {
            r.get("movieId") if r.get("movieId") is not None else r.get("id")
            for r in recs
            if (r.get("movieId") is not None or r.get("id") is not None)
        }
    )
    return recs, movie_ids


def sonarr_cutoff_episode_ids(app_cfg):
    recs, total = _paginate_wanted(app_cfg, "/wanted/cutoff")
    episode_ids = sorted({r.get("id") for r in recs if r.get("id") is not None})
    return recs, episode_ids


def radarr_cutoff_movie_ids(app_cfg):
    recs, total = _paginate_wanted(app_cfg, "/wanted/cutoff")
    movie_ids = sorted({r.get("id") for r in recs if r.get("id") is not None})
    return recs, movie_ids


def _env_bool(name):
    v = os.environ.get(name)
    if v is None:
        return None
    return v.strip().lower() in {"1", "true", "yes", "on"}


def apply_env_overrides(cfg):
    # Allow secrets + endpoints via env vars so users don't hardcode local infra
    sonarr_api_env = cfg.get("sonarr", {}).get("api_key_env") or "SEEKARR_SONARR_API_KEY"
    radarr_api_env = cfg.get("radarr", {}).get("api_key_env") or "SEEKARR_RADARR_API_KEY"
    sonarr_url_env = cfg.get("sonarr", {}).get("base_url_env") or "SEEKARR_SONARR_BASE_URL"
    radarr_url_env = cfg.get("radarr", {}).get("base_url_env") or "SEEKARR_RADARR_BASE_URL"

    if cfg.get("sonarr", {}).get("enabled"):
        env_key = os.environ.get(sonarr_api_env)
        env_url = os.environ.get(sonarr_url_env)
        if env_key:
            cfg["sonarr"]["api_key"] = env_key
        if env_url:
            cfg["sonarr"]["base_url"] = env_url

    if cfg.get("radarr", {}).get("enabled"):
        env_key = os.environ.get(radarr_api_env)
        env_url = os.environ.get(radarr_url_env)
        if env_key:
            cfg["radarr"]["api_key"] = env_key
        if env_url:
            cfg["radarr"]["base_url"] = env_url

    # Feature flags
    upg_env = _env_bool("SEEKARR_UPGRADES_ENABLED")
    if upg_env is not None:
        cfg.setdefault("upgrades", {})["enabled"] = upg_env

    return cfg


def load_state(cfg):
    path = cfg.get("state", {}).get("path", "/config/seekarr_state.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return path, json.load(f)
    except Exception:
        return path, {
            "sonarr_missing_offset": 0,
            "radarr_missing_offset": 0,
            "sonarr_cutoff_offset": 0,
            "radarr_cutoff_offset": 0,
        }


def save_state(path, state):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
            f.write("\n")
    except Exception as e:
        print(f"[state] warning: could not save state to {path}: {e}")


def rotate_slice(items, offset, count):
    if not items:
        return [], 0
    n = len(items)
    offset = offset % n
    out = []
    i = offset
    for _ in range(min(count, n)):
        out.append(items[i])
        i = (i + 1) % n
    return out, i


def _parse_iso_utc(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _iso_utc(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _get_log_timezone(cfg):
    tz_name = (cfg.get("runtime", {}) or {}).get("timezone") or "UTC"
    try:
        return tz_name, ZoneInfo(tz_name)
    except Exception:
        print(f"[config] warning: invalid timezone '{tz_name}', falling back to UTC")
        return "UTC", timezone.utc


def _fmt_iso_in_tz(iso_utc, tzinfo):
    dt = _parse_iso_utc(iso_utc)
    if not dt:
        return iso_utc
    return dt.astimezone(tzinfo).isoformat()


def _limit_titles(items, limit=TITLE_LOG_LIMIT):
    return items[:limit]


def _series_title_map(app_cfg):
    try:
        rows = api_get(app_cfg["base_url"], app_cfg["api_key"], "/series")
        return {x.get("id"): x.get("title") for x in rows if x.get("id") is not None}
    except Exception:
        return {}


def _movie_title_map(app_cfg):
    try:
        rows = api_get(app_cfg["base_url"], app_cfg["api_key"], "/movie")
        return {x.get("id"): x.get("title") for x in rows if x.get("id") is not None}
    except Exception:
        return {}


def _trim_log_to_last_runs(path=LOG_FILE_PATH, keep_runs=KEEP_LOG_RUNS):
    try:
        if keep_runs < 1 or not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        marker = "===== SEEKARR RUN START ====="
        starts = []
        pos = 0
        while True:
            idx = content.find(marker, pos)
            if idx == -1:
                break
            starts.append(idx)
            pos = idx + len(marker)
        if len(starts) <= keep_runs:
            return
        keep_from = starts[-keep_runs]
        with open(path, "w", encoding="utf-8") as f:
            f.write(content[keep_from:])
    except Exception as e:
        print(f"[log] warning: could not trim log file: {e}")


def _print_run_report(summary):
    rid = summary.get("run_id")
    tz_name = summary.get("log_timezone", "UTC")
    print(f"[run:{rid}] ===== SEEKARR RUN START =====")
    print(f"[run:{rid}] Started ({tz_name}):  {summary.get('run_started_at_local')}")
    print(f"[run:{rid}] Finished ({tz_name}): {summary.get('run_finished_at_local')}")

    if summary.get("dry_run"):
        sm = summary.get('sonarr_missing_commands_planned', 0)
        su = summary.get('sonarr_upgrade_commands_planned', 0)
        rm = summary.get('radarr_missing_commands_planned', 0)
        ru = summary.get('radarr_upgrade_commands_planned', 0)
        mode_label = "Command counts (dry-run/planned)"
    else:
        sm = summary.get('sonarr_missing_commands', 0)
        su = summary.get('sonarr_upgrade_commands', 0)
        rm = summary.get('radarr_missing_commands', 0)
        ru = summary.get('radarr_upgrade_commands', 0)
        mode_label = "Command counts (live/sent)"

    print(f"[run:{rid}] {mode_label} -> Sonarr missing: {sm}, "
          f"Sonarr upgrades: {su}, "
          f"Radarr missing: {rm}, "
          f"Radarr upgrades: {ru}")

    def section(label, total, titles):
        print(f"[run:{rid}] {label}: total selected={total}, titles listed={len(titles)}")
        for t in titles:
            print(f"[run:{rid}]   - {t}")

    section("Sonarr missing series", summary.get("sonarr_missing_selected_total", 0), summary.get("sonarr_missing_titles", []))
    section("Sonarr upgrade series", summary.get("sonarr_upgrade_selected_total", 0), summary.get("sonarr_upgrade_series", []))
    section("Radarr missing movies", summary.get("radarr_missing_selected_total", 0), summary.get("radarr_missing_titles", []))
    section("Radarr upgrade movies", summary.get("radarr_upgrade_selected_total", 0), summary.get("radarr_upgrade_titles", []))

    print(f"[run:{rid}] ===== SEEKARR RUN END =====")


def run_once(cfg, dry_run=False):
    log_tz_name, log_tz = _get_log_timezone(cfg)
    run_started = datetime.now(timezone.utc)
    run_id = uuid.uuid4().hex[:10]

    limits = cfg.get("limits", {})
    max_series = int(limits.get("max_series_searches_per_run", 25))
    max_movies = int(limits.get("max_movie_searches_per_run", 25))
    max_upgrade_eps = int(limits.get("max_upgrade_episode_searches_per_run", 200))
    max_upgrade_movies = int(limits.get("max_upgrade_movie_searches_per_run", 50))
    queue_cap = int(limits.get("skip_if_queue_over", 200))

    upgrades_enabled = bool(cfg.get("upgrades", {}).get("enabled", False))
    summary = defaultdict(int)
    state_path, state = load_state(cfg)

    # Cache title maps to avoid redundant full-library API calls
    sonarr_titles = _series_title_map(cfg["sonarr"]) if cfg.get("sonarr", {}).get("enabled") else {}
    radarr_titles = _movie_title_map(cfg["radarr"]) if cfg.get("radarr", {}).get("enabled") else {}

    # We report what was submitted this run; no completion wait loop.

    # Sonarr missing
    if cfg.get("sonarr", {}).get("enabled"):
        s_cfg = cfg["sonarr"]
        sq = get_queue_len(s_cfg)
        print(f"[sonarr] queue={sq}")
        if sq <= queue_cap:
            recs, series_ids = sonarr_missing_ids(s_cfg)
            summary["sonarr_missing_episodes"] = len(recs)
            summary["sonarr_series_with_missing"] = len(series_ids)
            offset = int(state.get("sonarr_missing_offset", 0))
            batch, next_offset = rotate_slice(series_ids, offset, max_series)
            summary["sonarr_missing_offset_start"] = offset
            summary["sonarr_missing_offset_next"] = next_offset
            summary["sonarr_missing_selected_total"] = len(batch)
            summary["sonarr_missing_commands_planned"] = len(batch)
            summary["sonarr_missing_titles"] = _limit_titles([sonarr_titles.get(sid, f"series:{sid}") for sid in batch])
            for sid in batch:
                payload = {"name": "MissingEpisodeSearch", "seriesId": sid}
                if dry_run:
                    print(f"[dry-run][sonarr] would POST /command {payload}")
                else:
                    api_post(s_cfg["base_url"], s_cfg["api_key"], "/command", payload)
                    summary["sonarr_missing_commands"] += 1
            state["sonarr_missing_offset"] = next_offset
        else:
            print(f"[sonarr] skipped missing due queue cap ({sq}>{queue_cap})")

        # Sonarr upgrades (cutoff not met)
        if upgrades_enabled and sq <= queue_cap:
            recs, episode_ids = sonarr_cutoff_episode_ids(s_cfg)
            summary["sonarr_cutoff_not_met"] = len(recs)
            cutoff_offset = int(state.get("sonarr_cutoff_offset", 0))
            batch, next_cutoff_offset = rotate_slice(episode_ids, cutoff_offset, max_upgrade_eps)
            summary["sonarr_cutoff_offset_start"] = cutoff_offset
            summary["sonarr_cutoff_offset_next"] = next_cutoff_offset
            summary["sonarr_upgrade_selected_total"] = len(batch)
            summary["sonarr_upgrade_commands_planned"] = 1 if batch else 0
            ep_to_series = {r.get("id"): r.get("seriesId") for r in recs if r.get("id") is not None}
            series_names = []
            seen_series = set()
            for eid in batch:
                sid = ep_to_series.get(eid)
                name = sonarr_titles.get(sid, f"series:{sid}") if sid is not None else f"episode:{eid}"
                if name not in seen_series:
                    seen_series.add(name)
                    series_names.append(name)
            summary["sonarr_upgrade_series"] = _limit_titles(series_names)
            if batch:
                payload = {"name": "EpisodeSearch", "episodeIds": batch}
                if dry_run:
                    print(
                        f"[dry-run][sonarr] would POST /command EpisodeSearch "
                        f"count={len(batch)} offset={cutoff_offset}->{next_cutoff_offset}"
                    )
                else:
                    api_post(s_cfg["base_url"], s_cfg["api_key"], "/command", payload)
                    summary["sonarr_upgrade_commands"] += 1
            state["sonarr_cutoff_offset"] = next_cutoff_offset

    # Radarr missing
    if cfg.get("radarr", {}).get("enabled"):
        r_cfg = cfg["radarr"]
        rq = get_queue_len(r_cfg)
        print(f"[radarr] queue={rq}")
        if rq <= queue_cap:
            recs, movie_ids = radarr_missing_ids(r_cfg)
            summary["radarr_missing_movies"] = len(recs)
            summary["radarr_movies_missing"] = len(movie_ids)
            offset = int(state.get("radarr_missing_offset", 0))
            batch, next_offset = rotate_slice(movie_ids, offset, max_movies)
            summary["radarr_missing_offset_start"] = offset
            summary["radarr_missing_offset_next"] = next_offset
            summary["radarr_missing_selected_total"] = len(batch)
            summary["radarr_missing_commands_planned"] = len(batch)
            summary["radarr_missing_titles"] = _limit_titles([radarr_titles.get(mid, f"movie:{mid}") for mid in batch])
            for mid in batch:
                payload = {"name": "MoviesSearch", "movieIds": [mid]}
                if dry_run:
                    print(f"[dry-run][radarr] would POST /command {payload}")
                else:
                    api_post(r_cfg["base_url"], r_cfg["api_key"], "/command", payload)
                    summary["radarr_missing_commands"] += 1
            state["radarr_missing_offset"] = next_offset
        else:
            print(f"[radarr] skipped missing due queue cap ({rq}>{queue_cap})")

        # Radarr upgrades (cutoff not met)
        if upgrades_enabled and rq <= queue_cap:
            recs, movie_ids = radarr_cutoff_movie_ids(r_cfg)
            summary["radarr_cutoff_not_met"] = len(recs)
            cutoff_offset = int(state.get("radarr_cutoff_offset", 0))
            batch, next_cutoff_offset = rotate_slice(movie_ids, cutoff_offset, max_upgrade_movies)
            summary["radarr_cutoff_offset_start"] = cutoff_offset
            summary["radarr_cutoff_offset_next"] = next_cutoff_offset
            summary["radarr_upgrade_selected_total"] = len(batch)
            summary["radarr_upgrade_commands_planned"] = len(batch)
            summary["radarr_upgrade_titles"] = _limit_titles([radarr_titles.get(mid, f"movie:{mid}") for mid in batch])
            for mid in batch:
                payload = {"name": "MoviesSearch", "movieIds": [mid]}
                if dry_run:
                    print(f"[dry-run][radarr] would POST /command upgrade {payload}")
                else:
                    api_post(r_cfg["base_url"], r_cfg["api_key"], "/command", payload)
                    summary["radarr_upgrade_commands"] += 1
            state["radarr_cutoff_offset"] = next_cutoff_offset

    run_finished = datetime.now(timezone.utc)

    summary["run_id"] = run_id
    summary["dry_run"] = bool(dry_run)
    summary["log_timezone"] = log_tz_name
    summary["run_started_at"] = _iso_utc(run_started)
    summary["run_finished_at"] = _iso_utc(run_finished)
    summary["run_started_at_local"] = _fmt_iso_in_tz(summary["run_started_at"], log_tz)
    summary["run_finished_at_local"] = _fmt_iso_in_tz(summary["run_finished_at"], log_tz)

    save_state(state_path, state)
    summary_dict = dict(summary)
    _print_run_report(summary_dict)
    _trim_log_to_last_runs()
    return summary_dict


def main():
    _enable_dual_logging()

    p = argparse.ArgumentParser(description="Seekarr")
    p.add_argument("--config", default="config.json")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    cfg = apply_env_overrides(cfg)
    run_once(cfg, dry_run=args.dry_run)


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as e:
        print(f"Config missing: {e}")
        sys.exit(2)
    except error.HTTPError as e:
        print(f"HTTP error: {e.code} {e.reason}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
