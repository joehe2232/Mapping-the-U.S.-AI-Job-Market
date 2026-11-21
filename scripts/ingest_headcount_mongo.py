"""Preserve Headcount pages in MongoDB and persist initial aggregation cleaning.

Never calls the jobs API, deletes collections, updates raw payloads or removes SQL data.
"""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone

from bson import BSON
from dotenv import load_dotenv
from pymongo import MongoClient

from pipeline_common import ROOT, sha256, write_json
from mongo_pipeline import job_stages, pay_stages, merge_stage, version


def mongo_database():
    load_dotenv(ROOT/'.env')
    client = MongoClient(os.environ['MONGODB_URI'], serverSelectionTimeoutMS=15000,
                         connectTimeoutMS=15000, appname='ai_jobs_m2', tz_aware=True)
    client.admin.command('ping')
    return client, client[os.environ.get('MONGODB_DB', 'ai_job_market')]


def canonical_hash(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def ingest(folder):
    baseline = json.loads((ROOT/'reports/raw_file_manifest.json').read_text(encoding='utf-8'))['files']
    expected_files = {r['path']:r['sha256'] for r in baseline}
    pages = sorted(folder.glob('states/*/*/page_*.json'))
    inventory = [{'path':p.relative_to(ROOT).as_posix(), 'sha256':sha256(p), 'bytes':p.stat().st_size} for p in pages]
    if not pages:
        raise ValueError('No original Headcount pages found')
    for entry in inventory:
        if expected_files.get(entry['path']) != entry['sha256']:
            raise ValueError('Unregistered or changed raw file: '+entry['path'])
    snapshot = 'hc_source_'+canonical_hash(inventory)[:20]
    cleaning_version = version()
    client, db = mongo_database()
    print(f'Connected to MongoDB database {db.name}; {len(pages)} original pages.', flush=True)
    inserted, occurrences, empty_pages, ids = 0, 0, 0, set()
    before_raw = db.raw_pages.count_documents({'source_snapshot':snapshot})
    for number, (file,meta) in enumerate(zip(pages,inventory),1):
        payload = json.loads(file.read_text(encoding='utf-8'))
        records = payload.get('response',{}).get('data')
        if not isinstance(records,list):
            raise ValueError('Malformed response.data in '+meta['path'])
        occurrences += len(records)
        empty_pages += not records
        ids.update(str(j['job_id']) for j in records if j.get('job_id'))
        doc_id = canonical_hash([snapshot,meta['path'],meta['sha256']])
        doc = dict(_id=doc_id,source_snapshot=snapshot,source_file=meta['path'],
                   source_sha256=meta['sha256'],payload_sha256=canonical_hash(payload),
                   size_bytes=meta['bytes'],payload=payload,registered_at=datetime.now(timezone.utc))
        if len(BSON.encode(doc))>=16*1024*1024:
            raise ValueError('Original page exceeds BSON document limit: '+meta['path'])
        if not db.raw_pages.find_one({'_id':doc_id},{'_id':1}):
            result = db.raw_pages.update_one({'_id':doc_id},{'$setOnInsert':doc},upsert=True)
            inserted += result.upserted_id is not None
        if number%25==0 or number==len(pages):
            print(f'Raw import: {number}/{len(pages)} pages; {inserted} newly inserted.',flush=True)
    # Verify actual stored content, not only the hash field supplied on upload.
    actual_files = {}
    for doc in db.raw_pages.find({'source_snapshot':snapshot}).batch_size(3):
        if canonical_hash(doc['payload'])!=doc['payload_sha256']:
            raise ValueError('Mongo raw payload integrity check failed: '+doc['source_file'])
        original=json.loads((ROOT/doc['source_file']).read_text(encoding='utf-8'))
        if doc['payload']!=original or doc['source_sha256']!=expected_files[doc['source_file']]:
            raise ValueError('Mongo/raw-file mismatch: '+doc['source_file'])
        actual_files[doc['source_file']]=doc['source_sha256']
    if actual_files!={r['path']:r['sha256'] for r in inventory}:
        raise ValueError('Mongo page inventory does not match originals')
    for name in ('manifest.json','checkpoint.json'):
        file=folder/name
        payload=json.loads(file.read_text(encoding='utf-8'))
        doc=dict(_id=canonical_hash([snapshot,name,sha256(file)]),source_snapshot=snapshot,
                 source_file=file.relative_to(ROOT).as_posix(),source_sha256=sha256(file),payload=payload)
        db.collection_manifests.update_one({'_id':doc['_id']},{'$setOnInsert':doc},upsert=True)
        if db.collection_manifests.find_one({'_id':doc['_id']})['payload']!=payload:
            raise ValueError('Stored manifest differs from original')
    source_manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    if occurrences!=source_manifest['total_returned'] or len(ids)!=source_manifest['unique_job_ids']:
        raise ValueError('Mongo acquisition counts disagree with source manifest')
    db.raw_pages.create_index('source_snapshot')
    db.clean_job_summaries.create_index([('source_snapshot',1),('clean_version',1),('job_id',1)],unique=True)
    db.clean_pay_ranges.create_index([('source_snapshot',1),('clean_version',1),('job_id',1),('posting_index',1),('money_index',1)],unique=True)
    print('Running MongoDB aggregation: canonical job selection, field states, whitespace, dates and nested locations.',flush=True)
    list(db.raw_pages.aggregate(job_stages(snapshot,cleaning_version)+[merge_stage('clean_job_summaries')],
                                allowDiskUse=False,maxTimeMS=180000))
    print('Running MongoDB aggregation: source money arrays, exact cents conversion and eligibility flags.',flush=True)
    list(db.clean_job_summaries.aggregate(pay_stages(snapshot,cleaning_version)+[merge_stage('clean_pay_ranges')],
                                          allowDiskUse=False,maxTimeMS=180000))
    selection={'source_snapshot':snapshot,'clean_version':cleaning_version}
    job_count=db.clean_job_summaries.count_documents(selection)
    pay_count=db.clean_pay_ranges.count_documents(selection)
    if job_count!=len(ids):
        raise ValueError('Mongo cleaned job count does not equal distinct raw IDs')
    raw_after=db.raw_pages.count_documents({'source_snapshot':snapshot})
    if raw_after!=len(pages):
        raise ValueError('Raw page count changed during cleaning')
    stats=db.command('dbStats')
    report=dict(database=db.name,source_snapshot=snapshot,clean_version=cleaning_version,
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        raw_pages=raw_after,raw_pages_before_run=before_raw,new_raw_pages=inserted,
        empty_pages=empty_pages,returned_occurrences=occurrences,distinct_provider_jobs=len(ids),
        clean_job_summaries=job_count,clean_pay_ranges=pay_count,
        collections={'raw':'raw_pages','source_metadata':'collection_manifests',
                     'processed_jobs':'clean_job_summaries','processed_salary':'clean_pay_ranges'},
        checks={'stored_payloads_match_originals':True,'source_counts_match_manifest':True,
                'raw_pages_preserved_after_cleaning':True,'canonical_job_count_matches':True},
        storage={k:stats.get(k) for k in ['dataSize','storageSize','indexSize']})
    db.ingestion_runs.update_one({'_id':snapshot+'|'+cleaning_version},
        {'$set':dict(report,status='complete')},upsert=True)
    write_json(ROOT/'reports/mongodb_ingestion.json',report)
    client.close()
    print(json.dumps({k:report[k] for k in ['database','raw_pages','new_raw_pages','clean_job_summaries','clean_pay_ranges']},indent=2))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',default='data/raw/headcount_10states')
    args=parser.parse_args()
    ingest((ROOT/args.input).resolve())
