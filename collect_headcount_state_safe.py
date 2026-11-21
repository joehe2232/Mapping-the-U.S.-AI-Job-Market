"""Headcount Labs state-partitioned JSON collector with local record cap.

Requirements: pip install requests python-dotenv
.env: HEADCOUNT_API_KEY=...

Smoke:
    python collect_headcount_state_safe.py --states PA --max-total 5 --max-per-title 5 --page-size 5 --out data/raw/headcount_smoke_pa

Main (a ten-state sample, not a complete national census):
    python collect_headcount_state_safe.py --states PA,NY,CA,TX,WA,MA,IL,VA,GA,NC --max-total 9000 --max-per-title 1000 --page-size 25 --out data/raw/headcount_10states

Safety notes:
 - Requests are NOT automatically retried after network timeouts (provider may have charged records).
 - Check provider remaining quota and leave a reserve; local cap only applies to this output folder.
 - Resume with the exact same --states, --posted-since, --page-size and --out settings.
 - Job listing cursor is tied to exact page size. This script never changes it while paging.
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE = "https://api.headcountlabs.com/v1/jobs"
TITLES = [
    "data scientist", "machine learning engineer", "AI engineer",
    "data analyst", "business intelligence analyst", "data engineer",
    "AI research scientist", "machine learning research scientist", "AI product manager"
]
US_STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())


def stamp():
    return datetime.now(timezone.utc).isoformat()


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def atomic_write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def checked(session, url, params, timeout=95):
    try:
        r = session.get(url, params=params, timeout=(10, timeout))
    except requests.exceptions.ReadTimeout as exc:
        raise RuntimeError(
            f"Timed out waiting for the jobs API (read timeout {timeout}s). "
            "Do not blindly retry the same request: check allowance and narrow filters "
            "to a state/city or shorter posting-date window first."
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Request did not complete: {exc}") from exc
    if not r.ok:
        try:
            obj = r.json().get("error", {})
        except ValueError:
            obj = {}
        raise RuntimeError(
            f"HTTP {r.status_code}: {obj.get('code','unknown')} — "
            f"{obj.get('message', r.text[:250])}; request id: "
            f"{obj.get('request_id', r.headers.get('X-Request-Id','unavailable'))}"
        )
    return r


def remaining_count(r):
    hdr = r.headers.get("X-Data-Records-Remaining")
    if hdr is None or not hdr.isdigit():
        raise RuntimeError(f"Cannot verify remaining allowance (header={hdr!r}); stopping.")
    return int(hdr)


def build_manifest(root, state, remaining):
    ids, missing = set(), 0
    for pg in root.glob("states/*/*/page_*.json"):
        wrapper = json.loads(pg.read_text(encoding="utf-8"))
        for job in wrapper.get("response", {}).get("data", []):
            jid = job.get("job_id")
            if jid is None:
                missing += 1
            else:
                ids.add(str(jid))
    result = {
        "created_at_utc": stamp(),
        "source": BASE,
        "sample_states": state["settings"]["states"],
        "posted_since": state["settings"]["posted_since"],
        "total_returned": state["total_returned"],
        "unique_job_ids": len(ids),
        "records_without_job_id": missing,
        "remaining_provider_allowance": remaining,
        "records_by_title": state["title_counts"],
        "records_by_state": {s: sum(v["returned"] for k, v in state["segments"].items() if k.startswith(s + "|")) for s in state["settings"]["states"]},
        "note": "Sample of API search results, NOT a representative count of U.S. vacancies. Duplicate jobs in multiple searches consume allowance again."
    }
    atomic_write(root / "manifest.json", result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--states", default="PA", help="Comma-separated USPS states, e.g. PA,NY,CA,TX")
    p.add_argument("--posted-since", default="", help="Optional source posting date: YYYY-MM-DD")
    p.add_argument("--max-total", type=int, default=9000)
    p.add_argument("--max-per-title", type=int, default=1000)
    p.add_argument("--page-size", type=int, default=25)
    p.add_argument("--reserve", type=int, default=1000)
    p.add_argument("--out", default="data/raw/headcount_by_state")
    args = p.parse_args()
    states = [x.strip().upper() for x in args.states.split(",") if x.strip()]
    if not states or len(set(states)) != len(states) or not set(states) <= US_STATES:
        p.error("--states must contain distinct valid two-letter US state codes or DC")
    if args.posted_since:
        try:
            datetime.strptime(args.posted_since, "%Y-%m-%d")
        except ValueError:
            p.error("--posted-since must be YYYY-MM-DD")
    if not 1 <= args.page_size <= 250:
        p.error("--page-size must be 1–250")
    if args.max_total < 1 or args.max_per_title < 1 or args.reserve < 0:
        p.error("Caps must be positive and reserve nonnegative")

    load_dotenv()
    api_key = os.getenv("HEADCOUNT_API_KEY")
    if not api_key:
        sys.exit("HEADCOUNT_API_KEY not set. Put it in .env.")

    root = Path(args.out)
    state_file = root / "checkpoint.json"
    settings = {"states": states, "titles": TITLES, "posted_since": args.posted_since,
                "page_size": args.page_size, "sort": "updated"}
    if state_file.exists():
        state = json.loads(state_file.read_text(encoding="utf-8"))
        if state["settings"] != settings:
            sys.exit("Checkpoint settings changed. Resume with same --states, --posted-since and --page-size, or choose a NEW --out folder.")
    else:
        state = {"created_at_utc": stamp(), "settings": settings, "total_returned": 0,
                 "title_counts": {t: 0 for t in TITLES},
                 "segments": {f"{s}|{t}": {"returned": 0, "pages": 0, "cursor": None,
                                             "exhausted": False, "page_limit": None}
                              for s in states for t in TITLES}}
        atomic_write(state_file, state)

    if state["total_returned"] >= args.max_total:
        print(f"Local collection already at cap: {state['total_returned']} >= {args.max_total}.")
        return

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {api_key}", "Accept": "application/json"})
    preflight = {"country": "US", "currentness": "current", "title": TITLES[0], "state": states[0]}
    if args.posted_since:
        preflight["posted_since"] = args.posted_since
    print("Checking provider quota using count endpoint (does not return job records)...", flush=True)
    allowance_response = checked(session, BASE + "/count", preflight, timeout=15)
    remaining = remaining_count(allowance_response)
    print(f"Provider remaining: {remaining:,}; locally saved {state['total_returned']:,}; cap {args.max_total:,}; reserve {args.reserve:,}.", flush=True)
    if remaining <= args.reserve:
        sys.exit("No allowance above reserve; stopping without retrieving jobs.")

    while state["total_returned"] < args.max_total and remaining > args.reserve:
        progressed = False
        for s in states:
            for title in TITLES:
                entry = state["segments"][f"{s}|{title}"]
                if entry["exhausted"] or state["title_counts"][title] >= args.max_per_title:
                    continue
                room = min(args.max_total - state["total_returned"],
                           args.max_per_title - state["title_counts"][title],
                           remaining - args.reserve)
                if room <= 0:
                    break
                if entry["page_limit"] is None:
                    limit = min(args.page_size, room)
                else:
                    limit = entry["page_limit"]
                    if room < limit:
                        # Pagination cursor is tied to original page size; never change it.
                        continue

                params = {"country": "US", "currentness": "current", "state": s,
                          "title": title, "sort": "updated", "limit": limit}
                if args.posted_since:
                    params["posted_since"] = args.posted_since
                if entry["cursor"]:
                    params["cursor"] = entry["cursor"]

                print(f"Fetching state={s}, title={title!r}, page={entry['pages']+1}, limit={limit}", flush=True)
                try:
                    response = checked(session, BASE, params)
                except Exception:
                    print("Stopped WITHOUT auto-retry. Check your provider allowance and request scope before rerunning.", file=sys.stderr)
                    raise
                payload = response.json()
                jobs = payload.get("data")
                if not isinstance(jobs, list) or len(jobs) > limit:
                    raise RuntimeError(f"Unexpected API response for {s}/{title}: {str(payload)[:300]}")
                page = entry["pages"] + 1
                file_path = root / "states" / s / slug(title) / f"page_{page:04d}.json"
                if file_path.exists():
                    raise RuntimeError(f"Refusing to overwrite previously saved {file_path}. Inspect checkpoint.")
                atomic_write(file_path, {
                    "retrieved_at_utc": stamp(), "state_filter": s, "title_filter": title,
                    "request_parameters": params, "response": payload,
                    "response_usage": {
                        "charged": response.headers.get("X-Data-Records-Charged"),
                        "remaining": response.headers.get("X-Data-Records-Remaining"),
                        "request_id": response.headers.get("X-Request-Id")}
                })
                entry["pages"] += 1
                entry["returned"] += len(jobs)
                entry["page_limit"] = limit
                entry["cursor"] = payload.get("next_cursor")
                entry["exhausted"] = not jobs or not entry["cursor"]
                state["total_returned"] += len(jobs)
                state["title_counts"][title] += len(jobs)
                atomic_write(state_file, state)
                remaining = remaining_count(response)
                print(f"  Saved {len(jobs)} jobs; total {state['total_returned']:,}; allowance left {remaining:,}", flush=True)
                progressed = True
                if state["total_returned"] >= args.max_total or remaining <= args.reserve:
                    break
                time.sleep(1.1)
            if state["total_returned"] >= args.max_total or remaining <= args.reserve:
                break
        if not progressed:
            print("No further pages fit the configured limits or all segments are exhausted.")
            break
    summary = build_manifest(root, state, remaining)
    print(f"Done. Records saved: {summary['total_returned']}; unique job IDs: {summary['unique_job_ids']}.")
    print(f"Raw pages: {root / 'states'}")
    print(f"Summary: {root / 'manifest.json'}")


if __name__ == "__main__":
    main()
