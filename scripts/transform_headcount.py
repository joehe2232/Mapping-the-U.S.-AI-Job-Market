"""Flatten saved Headcount pages to PostgreSQL; no API calls and no MongoDB required.

Raw files are read-only. Append content-addressed batches, preserve occurrences,
and let SQL type and integrate the flattened data. Different rules create a new batch.
"""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation

import pandas as pd
from sqlalchemy import text

from pipeline_common import ROOT, append_text_frame, database_engine, initialize, sha256, write_json
from posting_rules import classify, extract_skills, plain, state_code
from posting_entities import entity_links

EMPTY_COLUMNS = {
    'headcount_locations': 'batch_id job_id location_index location_state city region state_us country county_fips cbsa_code cbsa_title cbsa_type',
    'headcount_source_postings': 'batch_id job_id posting_index posting_id source source_posting_id posting_status posting_url source_posted_at pay_state location_state remote city state_raw state_us country',
    'headcount_pay_ranges': 'batch_id job_id posting_index money_index kind min_cents max_cents amount_cents currency period min_status max_status amount_status source_path',
    'headcount_skills': 'batch_id job_id skill',
    'onet_skill_aliases': 'batch_id onet_soc skill_example skill',
}

def value(obj):
    return obj.get('value') if isinstance(obj, dict) and obj.get('state') in ('known', 'derived') else None


def cents(value):
    if value is None:
        return ''
    try:
        result = Decimal(str(value)) * 100
        return str(result) if result.is_finite() else ''
    except InvalidOperation:
        return ''


def flatten(folder):
    files = sorted(folder.glob('states/*/*/page_*.json'))
    if not files:
        raise FileNotFoundError(f'No state-partitioned Headcount pages under {folder}')
    inventory = [{'path': f.relative_to(ROOT).as_posix(), 'sha256': sha256(f), 'bytes': f.stat().st_size} for f in files]
    dependencies = ['scripts/transform_headcount.py', 'scripts/posting_rules.py', 'scripts/posting_entities.py', 'scripts/pipeline_common.py',
                    'config/role_mappings.csv', 'sql/clean_headcount.sql', 'sql/build_views.sql']
    onet = next((ROOT/'data/raw/onet_31_0_csv').rglob('software_skills.csv'))
    fingerprint = hashlib.sha256(json.dumps({'files': inventory, 'onet_software_sha256':sha256(onet),
        'rules': {p: sha256(ROOT/p) for p in dependencies}}, sort_keys=True).encode()).hexdigest()
    batch = 'hc_' + fingerprint[:20]
    selected, occurrences, variants = {}, [], defaultdict(set)
    for file, meta in zip(files, inventory):
        wrapper = json.loads(file.read_text(encoding='utf-8'))
        jobs = wrapper.get('response', {}).get('data')
        if not isinstance(jobs, list):
            raise ValueError(f'Malformed page: {file.name}')
        for index, job in enumerate(jobs):
            jid = str(job.get('job_id') or '')
            occurrence = dict(batch_id=batch, job_id=jid, source_file=meta['path'],
                              source_sha256=meta['sha256'], record_index=str(index),
                              query_state=wrapper.get('state_filter', ''),
                              query_title=wrapper.get('title_filter', ''),
                              retrieved_at=wrapper.get('retrieved_at_utc', ''))
            occurrences.append(occurrence)
            if not jid:
                continue  # Explicitly retained in occurrence ledger and QA.
            variants[jid].add(hashlib.sha256(json.dumps(job, sort_keys=True).encode()).hexdigest())
            # Timestamps are parsed, rather than comparing varying timezone strings.
            rank = tuple(pd.to_datetime(job.get(k) or wrapper.get('retrieved_at_utc'), utc=True, errors='raise')
                         for k in ('job_updated_at', 'curated_at')) + (meta['path'], index)
            if jid not in selected or rank > selected[jid][0]:
                selected[jid] = rank, job, occurrence
    manifest_file = folder/'manifest.json'
    if manifest_file.exists():
        manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
        if manifest['total_returned'] != len(occurrences) or manifest['unique_job_ids'] != len(selected):
            raise ValueError('Saved pages disagree with collection manifest; inspect checkpoint before loading')
    rows = defaultdict(list, {name: [] for name in EMPTY_COLUMNS})
    rows['headcount_occurrences'] = occurrences
    states = Counter()
    for jid, (_, job, occurrence) in sorted(selected.items()):
        title = plain(value(job.get('title')))
        description = plain(value(job.get('description')))
        role = classify(title, description)
        base = {'batch_id': batch, 'job_id': jid}
        record = dict(base, source_file=occurrence['source_file'], source_sha256=occurrence['source_sha256'],
                      title=title, description=description, role=role,
                      company=plain(value(job.get('employer_name'))), company_id=job.get('company_id'),
                      currentness=job.get('currentness'), stale=str(job.get('stale')).lower(),
                      work_arrangement=value(job.get('work_arrangement')),
                      created_utc=job.get('job_first_seen_at'), updated_utc=job.get('job_updated_at'),
                      retrieved_utc=occurrence['retrieved_at'])
        for key in ('title', 'description', 'employer_name', 'work_arrangement'):
            record[key+'_state'] = (job.get(key) or {}).get('state', 'missing_field')
            states[key+':'+record[key+'_state']] += 1
        rows['headcount_jobs'].append(record)
        for index, item in enumerate(job.get('locations') or []):
            location = value(item) or {}
            msa = location.get('msa') or {}
            rows['headcount_locations'].append(dict(base, location_index=str(index),
                location_state=item.get('state'), city=location.get('city'), region=location.get('region'),
                state_us=state_code(location.get('region')), country=location.get('country'),
                county_fips=location.get('county_fips'), cbsa_code=msa.get('cbsa_code'),
                cbsa_title=msa.get('cbsa_title'), cbsa_type=msa.get('type')))
        for index, posting in enumerate(job.get('postings') or []):
            location = value(posting.get('location')) or {}
            posting_base = dict(base, posting_index=str(index))
            rows['headcount_source_postings'].append(dict(posting_base,
                posting_id=posting.get('posting_id'), source=posting.get('source'),
                source_posting_id=posting.get('source_posting_id'), posting_status=posting.get('posting_status'),
                posting_url=value(posting.get('posting_url')), source_posted_at=posting.get('source_posted_at'),
                pay_state=(posting.get('pay') or {}).get('state', 'missing_field'),
                location_state=(posting.get('location') or {}).get('state', 'missing_field'),
                remote=str(location.get('remote')).lower(),
                city=location.get('city'), state_raw=location.get('state'),
                state_us=state_code(location.get('state')), country=location.get('country')))
            money = posting.get('money') or []
            # Older representations can provide pay.value but omit money[]. Keep its provenance.
            if not money and value(posting.get('pay')):
                pay = value(posting['pay'])
                money = [dict(kind='range', min_cents=cents(p.get('min')), max_cents=cents(p.get('max')),
                    currency=p.get('currency'), period=p.get('interval'), source_path='pay.value',
                    amount_status={'min': 'ok' if p.get('min') is not None else 'missing',
                                   'max': 'ok' if p.get('max') is not None else 'missing'})
                    for p in (pay.get('ranges') or [pay])]
            for mi, amount in enumerate(money):
                status = amount.get('amount_status') or {}
                rows['headcount_pay_ranges'].append(dict(posting_base, money_index=str(mi),
                    kind=amount.get('kind'), min_cents=amount.get('min_cents'), max_cents=amount.get('max_cents'),
                    amount_cents=amount.get('amount_cents'), currency=amount.get('currency'),
                    period=amount.get('period'), min_status=status.get('min'), max_status=status.get('max'),
                    amount_status=status.get('amount'), source_path=amount.get('source_path')))
        for skill in extract_skills(title+' '+description):
            rows['headcount_skills'].append(dict(base, skill=skill))
    onet = next((ROOT/'data/raw/onet_31_0_csv').rglob('software_skills.csv'))
    software = pd.read_csv(onet, dtype=str, keep_default_na=False)
    rows['onet_skill_aliases'] = [dict(batch_id=batch, onet_soc=r['O*NET-SOC Code'],
        skill_example=r['Workplace Example'].strip().lower(), skill=s)
        for r in software.to_dict('records') for s in extract_skills(r['Workplace Example'])]
    mapping = pd.read_csv(ROOT/'config/role_mappings.csv', dtype=str, keep_default_na=False)
    rows['role_mappings'] = [dict(batch_id=batch, **r) for r in mapping.to_dict('records')]
    rows['headcount_entities'] = entity_links(rows['headcount_jobs'], rows['headcount_source_postings'])
    stats = dict(batch_id=batch, manifest_sha256=fingerprint, page_count=len(files),
        occurrence_count=len(occurrences), unique_jobs=len(selected),
        missing_job_ids=sum(not x['job_id'] for x in occurrences),
        duplicate_occurrences=len(occurrences)-len(selected),
        jobs_with_conflicting_versions=sum(len(v)>1 for v in variants.values()), field_states=dict(states),
        source_linked_ad_groups=len({r['entity_id'] for r in rows['headcount_entities']}),
        jobs_with_shared_source_id=sum(r['shared_source_id']=='true' for r in rows['headcount_entities']),
        jobs_with_source_identity_conflict=sum(r['identity_conflict']=='true' for r in rows['headcount_entities']),
        title_classification_counts=dict(Counter(r['role'] or 'out_of_scope' for r in rows['headcount_jobs'])),
        files=inventory)
    return rows, stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', default='data/raw/headcount_10states')
    args = parser.parse_args()
    folder = (ROOT/args.input).resolve()
    rows, stats = flatten(folder)
    engine = database_engine()
    with engine.begin() as conn:
        initialize(conn)
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('ai_jobs_headcount_ingest'))"))
        exists = conn.execute(text('SELECT 1 FROM audit.headcount_batches WHERE batch_id=:b'), {'b':stats['batch_id']}).scalar()
        if not exists:
            for table, records in rows.items():
                if not records and table not in EMPTY_COLUMNS:
                    raise ValueError(f'Expected nonempty staging table: {table}')
                frame = pd.DataFrame(records) if records else pd.DataFrame(columns=EMPTY_COLUMNS[table].split())
                append_text_frame(frame, table, conn)
                print(f'staging.{table}: appended {len(records):,} rows', flush=True)
            conn.execute(text('''INSERT INTO audit.headcount_batches
                (batch_id,manifest_sha256,page_count,occurrence_count,unique_jobs)
                VALUES (:batch_id,:manifest_sha256,:page_count,:occurrence_count,:unique_jobs)'''), stats)
        else:
            for table, records in rows.items():
                count = conn.execute(text(f'SELECT count(*) FROM staging.{table} WHERE batch_id=:b'), {'b':stats['batch_id']}).scalar()
                if count != len(records):
                    raise ValueError(f'Saved staging count differs for {table}; refusing partial batch')
            print('Identical batch already loaded; verified counts, no rows appended.', flush=True)
        conn.execute(text('''INSERT INTO audit.active_batch(singleton,batch_id) VALUES(true,:b)
            ON CONFLICT(singleton) DO UPDATE SET batch_id=excluded.batch_id'''), {'b':stats['batch_id']})
        conn.exec_driver_sql('ANALYZE audit.active_batch')
        conn.exec_driver_sql('ANALYZE audit.headcount_batches')
        conn.exec_driver_sql((ROOT/'sql/clean_headcount.sql').read_text(encoding='utf-8'))
        conn.exec_driver_sql((ROOT/'sql/build_views.sql').read_text(encoding='utf-8'))
        for table in ('headcount_jobs','headcount_occurrences','headcount_locations','headcount_source_postings',
                      'headcount_pay_ranges','headcount_skills','role_mappings','onet_skill_aliases','headcount_entities'):
            conn.exec_driver_sql(f'CREATE INDEX IF NOT EXISTS ix_{table}_batch ON staging.{table}(batch_id)')
            conn.exec_driver_sql(f'ANALYZE staging.{table}')
    write_json(ROOT/'reports/headcount_ingestion.json', stats)
    print('Committed and activated batch', stats['batch_id'])


if __name__ == '__main__':
    main()
