"""Safely collect Headcount Labs US job searches into original JSON pages.

Install: pip install requests python-dotenv
Configure: HEADCOUNT_API_KEY=... in .env (do not commit the file)
Run: python collect_headcount_capped.py --max-total 9000 --max-per-query 1000

The local cap is cumulative for this output directory. This script does not
activate or disable paid overage; keep paid usage disabled in account billing.
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

API = "https://api.headcountlabs.com/v1/jobs"
QUERIES = [
    "data scientist",
    "machine learning engineer",
    "AI engineer",
    "data analyst",
    "business intelligence analyst",
    "data engineer",
    "AI research scientist",
    "machine learning research scientist",
    "AI product manager",
]


def slugify(value):
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def atomic_json_write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(obj, file, indent=2, ensure_ascii=False)
    temporary.replace(path)


def allowance_remaining(response):
    raw = response.headers.get("X-Data-Records-Remaining")
    if raw is None:
        raise RuntimeError(
            "The provider returned no X-Data-Records-Remaining header; "
            "stopping rather than guessing the remaining free allowance."
        )
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Unexpected allowance header: {raw!r}") from exc


def get_checked(session, url, params):
    # Deliberately do not automatically retry: a timeout can occur after a
    # response was charged, so automatic repetition could consume allowance.
    response = session.get(url, params=params, timeout=(10, 90))
    if not response.ok:
        raise RuntimeError(
            f"API returned HTTP {response.status_code}: "
            f"{response.text[:600]} (URL: {response.url})"
        )
    return response


def build_manifest(root, state, remaining):
    unique_ids = set()
    no_id = 0
    for title in QUERIES:
        folder = root / slugify(title)
        for page in sorted(folder.glob("page_*.json")):
            with page.open("r", encoding="utf-8") as file:
                wrapper = json.load(file)
            for job in wrapper.get("response", {}).get("data", []):
                job_id = job.get("job_id")
                if job_id:
                    unique_ids.add(str(job_id))
                else:
                    no_id += 1

    manifest = {
        "generated_at_utc": now_utc(),
        "source": API,
        "filters": {"country": "US", "currentness": "current"},
        "api_records_returned_this_collection": state["total_returned"],
        "unique_job_ids_in_saved_pages": len(unique_ids),
        "records_missing_job_id": no_id,
        "last_observed_provider_records_remaining": remaining,
        "per_search": {
            title: {
                "returned": state["queries"][title]["returned"],
                "pages": state["queries"][title]["pages"],
                "exhausted": state["queries"][title]["exhausted"],
            }
            for title in QUERIES
        },
        "notes": "Returned records consume allowance even when the same job_id repeats.",
    }
    atomic_json_write(root / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-total", type=int, default=9000,
                        help="Maximum records returned in this local collection")
    parser.add_argument("--max-per-query", type=int, default=1000,
                        help="Maximum records returned per title")
    parser.add_argument("--page-size", type=int, default=100,
                        help="1–250; keep unchanged when resuming")
    parser.add_argument("--reserve", type=int, default=1000,
                        help="Provider records to leave unused, beyond local cap")
    parser.add_argument("--out", default="data/raw/headcount",
                        help="Location of raw pages and checkpoint")
    args = parser.parse_args()

    if not (1 <= args.page_size <= 250):
        parser.error("--page-size must be between 1 and 250")
    if args.max_total < 1 or args.max_per_query < 1 or args.reserve < 0:
        parser.error("Caps must be positive, reserve must be nonnegative")

    load_dotenv()
    key = os.getenv("HEADCOUNT_API_KEY")
    if not key:
        sys.exit("Missing HEADCOUNT_API_KEY. Put it in .env in the working directory.")

    root = Path(args.out)
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / "checkpoint.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("page_size") != args.page_size or state.get("query_names") != QUERIES:
            sys.exit("Saved cursor depends on page size/search list. Use the same settings ")
    else:
        state = {
            "created_at_utc": now_utc(),
            "page_size": args.page_size,
            "query_names": QUERIES,
            "total_returned": 0,
            "queries": {
                title: {"cursor": None, "pages": 0, "returned": 0,
                        "exhausted": False} for title in QUERIES
            },
        }
        atomic_json_write(state_path, state)

    if state["total_returned"] >= args.max_total:
        print(f"Already at local cap ({state['total_returned']} >= {args.max_total}).")
        return

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {key}", "Accept": "application/json"})

    # Counts consume no job-record allowance. The response also supplies
    # the provider's current allowance headers before the first paid record.
    preflight = get_checked(session, API + "/count", {
        "country": "US", "currentness": "current", "title": QUERIES[0]
    })
    remaining = allowance_remaining(preflight)
    print(f"Provider reports {remaining:,} records remaining this month.")
    print(f"Local collection so far: {state['total_returned']:,} records.")
    print(f"Collection max: {args.max_total:,}; per-title max: {args.max_per_query:,}.")
    if remaining <= args.reserve:
        sys.exit("Stopping: remaining monthly allowance is at/below your reserve.")
    time.sleep(1.1)

    # Round-robin pages keep coverage balanced when a global cap is reached.
    while state["total_returned"] < args.max_total and remaining > args.reserve:
        progressed = False
        for title in QUERIES:
            entry = state["queries"][title]
            if entry["exhausted"] or entry["returned"] >= args.max_per_query:
                continue
            page_limit = min(
                args.page_size,
                args.max_total - state["total_returned"],
                args.max_per_query - entry["returned"],
                remaining - args.reserve,
            )
            if page_limit <= 0:
                break
            params = {
                "country": "US", "currentness": "current",
                "title": title, "limit": page_limit,
            }
            if entry["cursor"]:
                params["cursor"] = entry["cursor"]
            response = get_checked(session, API, params)
            payload = response.json()
            jobs = payload.get("data")
            if not isinstance(jobs, list):
                raise RuntimeError(f"Unexpected response data for {title}: {str(payload)[:400]}")
            if len(jobs) > page_limit:
                raise RuntimeError(f"API returned {len(jobs)} records for a limit of {page_limit}")

            # Persist the original response and metadata, then checkpoint.
            folder = root / slugify(title)
            page_number = entry["pages"] + 1
            file_path = folder / f"page_{page_number:04d}.json"
            if file_path.exists():
                raise RuntimeError(f"Refusing to overwrite {file_path}. Inspect checkpoint.")
            atomic_json_write(file_path, {
                "retrieved_at_utc": now_utc(),
                "search_title": title,
                "request_parameters": params,
                "response": payload,
                "response_usage": {
                    "records_charged": response.headers.get("X-Data-Records-Charged"),
                    "records_remaining": response.headers.get("X-Data-Records-Remaining"),
                },
            })
            entry["pages"] = page_number
            entry["returned"] += len(jobs)
            state["total_returned"] += len(jobs)
            entry["cursor"] = payload.get("next_cursor")
            entry["exhausted"] = not jobs or not entry["cursor"]
            atomic_json_write(state_path, state)
            progressed = True
            print(f"{title:32} +{len(jobs):3} | total {state['total_returned']:6,} ", end="")
            remaining = allowance_remaining(response)
            print(f"| provider remaining {remaining:,}")
            time.sleep(1.1)
            if state["total_returned"] >= args.max_total or remaining <= args.reserve:
                break
        if not progressed:
            break

    manifest = build_manifest(root, state, remaining)
    print("\nCollection complete or safely paused.")
    print(f"Returned records: {manifest['api_records_returned_this_collection']:,}")
    print(f"Unique job IDs:    {manifest['unique_job_ids_in_saved_pages']:,}")
    print(f"Files:             {root.resolve()}")
    print("Raw JSON pages, checkpoint.json, and manifest.json are available.")
    print("Important: Paid usage settings are controlled on the provider Billing page.")


if __name__ == "__main__":
    main()
