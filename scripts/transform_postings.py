"""Flatten Mongo job snapshots to curated PostgreSQL tables, preserving original JSON in Mongo.
Usage: python scripts/transform_postings.py [--batch-id YYYYMMDDTHHMMSSZ]
Optional metro mapping: config/metro_crosswalk.csv (location_regex,bls_area,notes)
"""
import argparse
import os
import re
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from pymongo import MongoClient
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
US_STATES = dict(item.split(':') for item in (
    'Alabama:AL,Alaska:AK,Arizona:AZ,Arkansas:AR,California:CA,Colorado:CO,Connecticut:CT,'
    'Delaware:DE,Florida:FL,Georgia:GA,Hawaii:HI,Idaho:ID,Illinois:IL,Indiana:IN,Iowa:IA,'
    'Kansas:KS,Kentucky:KY,Louisiana:LA,Maine:ME,Maryland:MD,Massachusetts:MA,Michigan:MI,'
    'Minnesota:MN,Mississippi:MS,Missouri:MO,Montana:MT,Nebraska:NE,Nevada:NV,'
    'New Hampshire:NH,New Jersey:NJ,New Mexico:NM,New York:NY,North Carolina:NC,'
    'North Dakota:ND,Ohio:OH,Oklahoma:OK,Oregon:OR,Pennsylvania:PA,Rhode Island:RI,'
    'South Carolina:SC,South Dakota:SD,Tennessee:TN,Texas:TX,Utah:UT,Vermont:VT,'
    'Virginia:VA,Washington:WA,West Virginia:WV,Wisconsin:WI,Wyoming:WY,'
    'District of Columbia:DC').split(','))
load_dotenv(ROOT / '.env')
ROLE_MAPPINGS = {
    'data scientist': ('15-2051', '15-2051.00', 'direct'),
    'ml / ai engineer': ('15-2051', '15-2051.00', 'proxy'),
    'data / bi analyst': ('15-2051', '15-2051.01', 'proxy'),
    'data engineer': ('15-1243', '15-1243.01', 'proxy'),
    'ai research scientist': ('15-1221', '15-1221.00', 'proxy'),
    'ai product manager': ('11-3021', '11-3021.00', 'proxy'),
}
SKILLS = {
    'python': r'\bpython\b', 'sql': r'\bsql\b', 'aws': r'\baws\b|amazon web services',
    'azure': r'\bazure\b', 'gcp': r'\bgcp\b|google cloud',
    'pytorch': r'\bpytorch\b', 'tensorflow': r'\btensorflow\b',
    'docker': r'\bdocker\b', 'kubernetes': r'\bkubernetes\b|\bk8s\b',
    'apache airflow': r'\bairflow\b', 'spark': r'\bspark\b|\bpyspark\b',
    'kafka': r'\bkafka\b', 'databricks': r'\bdatabricks\b',
    'snowflake': r'\bsnowflake\b', 'tableau': r'\btableau\b',
    'power bi': r'\bpower\s*bi\b', 'llm': r'\bllms?\b|large language models?',
    'generative ai': r'\bgenerative ai\b|\bgenai\b|\bgen ai\b',
    'rag': r'\brag\b|retrieval.augmented generation', 'mlops': r'\bmlops\b',
    'langchain': r'\blangchain\b',
}


def classify(title, desc):
    t = title.lower()
    d = desc.lower()
    if re.search(r'\bai\b|artificial intelligence|machine learning', t) and 'product manager' in t:
        return 'ai product manager'
    if 'research scientist' in t and re.search(r'\bai\b|artificial intelligence|machine learning|\bllm\b|large language model', t + ' ' + d):
        return 'ai research scientist'
    if 'data engineer' in t:
        return 'data engineer'
    if re.search(r'\b(machine learning|ml|ai|artificial intelligence)\s+engineer\b', t):
        return 'ml / ai engineer'
    if 'data scientist' in t:
        return 'data scientist'
    if any(x in t for x in ('data analyst', 'business intelligence analyst', 'bi analyst')):
        return 'data / bi analyst'
    return None


def number(v):
    try:
        return float(v) if v is not None and str(v).strip() else None
    except (ValueError, TypeError):
        return None


def prediction(v):
    if v is None:
        return None
    if v in (True, 1, '1', 'true', 'True'):
        return True
    if v in (False, 0, '0', 'false', 'False'):
        return False
    return None


def extract_state(location_obj):
    # Prefer explicit U.S. two-letter abbreviations or state names in Adzuna location fields.
    texts = [location_obj.get('display_name') or ''] + list(location_obj.get('area') or [])
    for item in texts:
        match = re.search(r',\s*([A-Z]{2})(?:\b|$)', str(item))
        if match and match.group(1) in US_STATES.values():
            return match.group(1)
    for item in texts:
        for full_name, abbrev in US_STATES.items():
            if re.search(r'(?<!\w)' + re.escape(full_name) + r'(?!\w)', str(item), re.I):
                return abbrev
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch-id', default=None)
    args = parser.parse_args()
    client = MongoClient(os.environ['MONGODB_URI'])
    db = client[os.environ.get('MONGODB_DB', 'ai_jobs_m2')]
    if args.batch_id is None:
        # Most recent batch by id; ingestion IDs are UTC ISO-like and lexicographically ordered.
        rec = db.job_snapshots.find_one(sort=[('batch_id', -1)])
        if not rec:
            raise RuntimeError('No Mongo snapshots found. Run ingest_adzuna.py first.')
        args.batch_id = rec['batch_id']
    crosswalk_path = ROOT / 'config' / 'metro_crosswalk.csv'
    cw = pd.read_csv(crosswalk_path, dtype=str).fillna('').to_dict('records')
    postings, skills, rejected = [], [], []
    for rec in db.job_snapshots.find({'batch_id': args.batch_id}):
        job = rec['source']
        title = ' '.join(str(job.get('title') or '').split())
        desc = ' '.join(str(job.get('description') or '').split())
        role = classify(title, desc)
        if role is None:
            rejected.append((rec['job_id'], 'out_of_scope_title'))
            continue
        bls_soc, onet_soc, confidence = ROLE_MAPPINGS[role]
        location_obj = job.get('location') or {}
        location = location_obj.get('display_name') or ''
        us_state = extract_state(location_obj)
        metro = next((row['bls_area'].strip() for row in cw
                      if row.get('location_regex') and re.search(row['location_regex'], location, re.I)), None)
        sal_lo, sal_hi = number(job.get('salary_min')), number(job.get('salary_max'))
        sal_pred = prediction(job.get('salary_is_predicted'))
        good_range = (sal_lo is not None and sal_hi is not None and 0 < sal_lo <= sal_hi)
        outlier = bool(good_range and (sal_lo < 15_000 or sal_hi > 1_000_000))
        eligible = bool(good_range and not outlier and sal_pred is False)
        postings.append({
            'batch_id': args.batch_id, 'job_id': rec['job_id'],
            'created_utc': pd.to_datetime(job.get('created'), utc=True, errors='coerce'),
            'title': title, 'company': (job.get('company') or {}).get('display_name'),
            'role': role, 'bls_soc': bls_soc, 'onet_soc': onet_soc,
            'occupation_mapping': confidence, 'location_raw': location,
            'state_us': us_state, 'remote_location_flag': bool(re.search(r'\bremote\b', location, re.I)),
            'bls_area': metro, 'latitude': number(job.get('latitude')),
            'longitude': number(job.get('longitude')), 'salary_min': sal_lo,
            'salary_max': sal_hi, 'salary_midpoint': (sal_lo + sal_hi) / 2 if good_range else None,
            'salary_is_predicted': sal_pred, 'salary_valid_range': good_range,
            'salary_outlier_review': outlier, 'salary_eligible': eligible,
            'description_snippet': desc, 'redirect_url': job.get('redirect_url'),
            'matched_queries': ', '.join(rec.get('matched_queries', [])),
        })
        for skill, pattern in SKILLS.items():
            if re.search(pattern, title + ' ' + desc, flags=re.I):
                skills.append({'batch_id': args.batch_id, 'job_id': rec['job_id'], 'skill': skill})
    if not postings:
        raise ValueError('No matching postings after filtering; inspect Adzuna source and query parameters.')
    engine = create_engine(os.environ['DATABASE_URL'])
    with engine.begin() as conn:
        conn.execute(text('CREATE SCHEMA IF NOT EXISTS clean'))
        conn.execute(text('CREATE SCHEMA IF NOT EXISTS serving'))
    pd.DataFrame(postings).to_sql('postings', engine, schema='clean', if_exists='replace', index=False, chunksize=1000)
    pd.DataFrame(skills, columns=['batch_id','job_id','skill']).drop_duplicates().to_sql(
        'posting_skills', engine, schema='clean', if_exists='replace', index=False)
    pd.DataFrame(rejected, columns=['job_id', 'reason']).to_sql(
        'excluded_postings', engine, schema='clean', if_exists='replace', index=False)
    print('Batch:', args.batch_id)
    print('Retained postings:', len(postings), 'Out-of-scope posts (available in raw Mongo):', len(rejected))
    print('Matched metro:', sum(x['bls_area'] is not None for x in postings), '/', len(postings))
    print('Salary eligible:', sum(x['salary_eligible'] for x in postings), '/', len(postings))
    print('Skill mentions:', len(skills))


if __name__ == '__main__':
    raise SystemExit('Archived Adzuna transformer. Use scripts/transform_headcount.py for the current dataset.')
