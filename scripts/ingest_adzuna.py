"""Retrieve real U.S. job results from Adzuna; save raw JSON pages + source jobs to MongoDB.
Usage: python scripts/ingest_adzuna.py --pages 3 --days 30
Requires user's own Adzuna app ID/key. Preserves query provenance and page responses.
"""
import argparse
import os
import time
from datetime import datetime, timezone
from pathlib import Path
import requests
from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
QUERIES = {
    'data scientist': {'title_only': 'data scientist'},
    'machine learning engineer': {'title_only': 'machine learning engineer'},
    'ai engineer': {'title_only': 'ai engineer'},
    'data analyst': {'title_only': 'data analyst'},
    'business intelligence analyst': {'title_only': 'business intelligence analyst'},
    'data engineer': {'title_only': 'data engineer'},
    'ai research scientist': {'title_only': 'research scientist', 'what_or': 'AI machine learning'},
    'ai product manager': {'title_only': 'AI product manager'},
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pages', type=int, default=3)
    parser.add_argument('--days', type=int, default=30)
    parser.add_argument('--batch-id', default=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    args = parser.parse_args()
    if args.pages < 1 or args.days < 1:
        parser.error('--pages and --days must be positive')
    for secret in ('ADZUNA_APP_ID', 'ADZUNA_APP_KEY', 'MONGODB_URI'):
        if not os.environ.get(secret):
            raise EnvironmentError(f'Set {secret} in .env')
    mongo = MongoClient(os.environ['MONGODB_URI'], serverSelectionTimeoutMS=15000)
    db = mongo[os.environ.get('MONGODB_DB', 'ai_jobs_m2')]
    db.raw_pages.create_index([('batch_id', 1), ('query', 1), ('page', 1)], unique=True)
    db.job_snapshots.create_index([('batch_id', 1), ('job_id', 1)], unique=True)
    session = requests.Session()
    for name, query in QUERIES.items():
        for page in range(1, args.pages + 1):
            params = {
                'app_id': os.environ['ADZUNA_APP_ID'],
                'app_key': os.environ['ADZUNA_APP_KEY'],
                'results_per_page': 50,
                'content-type': 'application/json',
                'max_days_old': args.days,
                'sort_by': 'date',
                **query,
            }
            url = f'https://api.adzuna.com/v1/api/jobs/us/search/{page}'
            response = None
            for attempt in range(4):
                try:
                    response = session.get(url, params=params, timeout=35)
                    if response.status_code in (429, 500, 502, 503, 504):
                        time.sleep(2 ** (attempt + 1))
                        continue
                    response.raise_for_status()
                    break
                except requests.RequestException:
                    if attempt == 3:
                        raise
                    time.sleep(2 ** (attempt + 1))
            if response is None or not response.ok:
                raise RuntimeError(f'Adzuna request failed: {name} page {page}, status {getattr(response,"status_code",None)}')
            data = response.json()
            if not isinstance(data.get('results'), list):
                raise ValueError(f'Unexpected Adzuna response for {name}, page {page}')
            now = datetime.now(timezone.utc)
            db.raw_pages.replace_one(
                {'batch_id': args.batch_id, 'query': name, 'page': page},
                {'batch_id': args.batch_id, 'query': name, 'page': page, 'fetched_at': now,
                 'params_without_secrets': {k:v for k,v in params.items() if not k.startswith('app_')},
                 'api_response': data},
                upsert=True,
            )
            ops = []
            for job in data['results']:
                job_id = str(job.get('id', '')).strip()
                if not job_id:
                    continue  # preserved in raw_pages and counted in QA, not eligible for dedup
                ops.append(UpdateOne(
                    {'batch_id': args.batch_id, 'job_id': job_id},
                    {'$setOnInsert': {'source': job, 'fetched_at': now}, '$addToSet': {'matched_queries': name}},
                    upsert=True,
                ))
            if ops:
                db.job_snapshots.bulk_write(ops, ordered=False)
            print(f'{name}: page={page} returned={len(data["results"])} total_matches={data.get("count", "unknown")}')
            if len(data['results']) == 0:
                break
            time.sleep(1.5)  # conservative request pacing; honor provider quotas
    print('Batch:', args.batch_id)
    print('Raw pages:', db.raw_pages.count_documents({'batch_id': args.batch_id}))
    print('Unique job snapshots:', db.job_snapshots.count_documents({'batch_id': args.batch_id}))


if __name__ == '__main__':
    raise SystemExit('Archived Adzuna collector. Current source: collect_headcount_state_safe.py; see README.md.')
