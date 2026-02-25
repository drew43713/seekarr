#!/usr/bin/env python3
import argparse
import json
import os
import sys
from collections import defaultdict
from urllib import request, parse, error


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


def sonarr_missing_ids(app_cfg):
    missing = api_get(app_cfg["base_url"], app_cfg["api_key"], "/wanted/missing", {"page": 1, "pageSize": 1000})
    recs = missing.get("records", [])
    series_ids = sorted({r.get("seriesId") for r in recs if r.get("seriesId") is not None})
    return recs, series_ids


def radarr_missing_ids(app_cfg):
    missing = api_get(app_cfg["base_url"], app_cfg["api_key"], "/wanted/missing", {"page": 1, "pageSize": 1000})
    recs = missing.get("records", [])
    movie_ids = sorted(
        {
            r.get("movieId") if r.get("movieId") is not None else r.get("id")
            for r in recs
            if (r.get("movieId") is not None or r.get("id") is not None)
        }
    )
    return recs, movie_ids


def sonarr_cutoff_episode_ids(app_cfg):
    cutoff = api_get(app_cfg["base_url"], app_cfg["api_key"], "/wanted/cutoff", {"page": 1, "pageSize": 1000})
    recs = cutoff.get("records", [])
    episode_ids = sorted({r.get("id") for r in recs if r.get("id") is not None})
    return recs, episode_ids


def radarr_cutoff_movie_ids(app_cfg):
    cutoff = api_get(app_cfg["base_url"], app_cfg["api_key"], "/wanted/cutoff", {"page": 1, "pageSize": 1000})
    recs = cutoff.get("records", [])
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


def run_once(cfg, dry_run=False):
    limits = cfg.get("limits", {})
    max_series = int(limits.get("max_series_searches_per_run", 25))
    max_movies = int(limits.get("max_movie_searches_per_run", 25))
    max_upgrade_eps = int(limits.get("max_upgrade_episode_searches_per_run", 200))
    max_upgrade_movies = int(limits.get("max_upgrade_movie_searches_per_run", 50))
    queue_cap = int(limits.get("skip_if_queue_over", 200))

    upgrades_enabled = bool(cfg.get("upgrades", {}).get("enabled", False))
    summary = defaultdict(int)
    state_path, state = load_state(cfg)

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
            for mid in batch:
                payload = {"name": "MoviesSearch", "movieIds": [mid]}
                if dry_run:
                    print(f"[dry-run][radarr] would POST /command upgrade {payload}")
                else:
                    api_post(r_cfg["base_url"], r_cfg["api_key"], "/command", payload)
                    summary["radarr_upgrade_commands"] += 1
            state["radarr_cutoff_offset"] = next_cutoff_offset

    save_state(state_path, state)
    print("[summary]", dict(summary))
    return dict(summary)


def main():
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
