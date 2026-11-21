"""Cross-check MongoDB processing against original files and PostgreSQL outputs."""
import json
from datetime import datetime, timezone

from bson.decimal128 import Decimal128
from sqlalchemy import text

from ingest_headcount_mongo import mongo_database
from pipeline_common import ROOT, database_engine, sha256, write_json


def number(value):
    return value.to_decimal() if isinstance(value,Decimal128) else value


def validate():
    report=json.loads((ROOT/'reports/mongodb_ingestion.json').read_text(encoding='utf-8'))
    scope={k:report[k] for k in ['source_snapshot','clean_version']}
    client,db=mongo_database()
    engine=database_engine()
    baseline=json.loads((ROOT/'reports/raw_file_manifest.json').read_text(encoding='utf-8'))['files']
    checks={'original_files_unchanged':all(sha256(ROOT/r['path'])==r['sha256'] for r in baseline)}
    raw_scope={'source_snapshot':scope['source_snapshot']}
    counts=list(db.raw_pages.aggregate([{'$match':raw_scope},
        {'$project':{'n':{'$size':'$payload.response.data'}}},
        {'$group':{'_id':None,'pages':{'$sum':1},'occurrences':{'$sum':'$n'},
                   'empty_pages':{'$sum':{'$cond':[{'$eq':['$n',0]},1,0]}}}}]))[0]
    checks['raw_counts_match_acquisition']=all(counts[k]==report[j] for k,j in
        [('pages','raw_pages'),('occurrences','returned_occurrences'),('empty_pages','empty_pages')])
    checks['completed_run_registered']=db.ingestion_runs.count_documents(dict(_id=report['source_snapshot']+'|'+report['clean_version'],status='complete'))==1
    mongo_jobs={r['job_id']:r for r in db.clean_job_summaries.find(scope,
        {'job_id':1,'source_file':1,'source_sha256':1,'occurrence_count':1,'description_state':1}).batch_size(500)}
    mongo_money={}
    for r in db.clean_pay_ranges.find(scope,{'job_id':1,'posting_index':1,'money_index':1,
        'salary_min':1,'salary_max':1,'valid_range':1,'salary_eligible':1}).batch_size(1000):
        key=(r['job_id'],int(r['posting_index']),int(r['money_index']))
        mongo_money[key]=(number(r.get('salary_min')),number(r.get('salary_max')),
                          r['valid_range'],r['salary_eligible'])
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
        conn.execute(text('SET TRANSACTION READ ONLY'))
        batch=conn.execute(text('SELECT batch_id FROM audit.active_batch')).scalar_one()
        sql_jobs={r['job_id']:dict(r) for r in conn.execute(text('''SELECT j.job_id,j.source_file,j.source_sha256,j.description_state
            FROM staging.headcount_jobs j JOIN audit.active_batch USING(batch_id)''')).mappings()}
        sql_occurrences=dict(conn.execute(text('''SELECT job_id,count(*) FROM staging.headcount_occurrences
            JOIN audit.active_batch USING(batch_id) GROUP BY job_id''')).all())
        sql_money={tuple(r[:3]):tuple(r[3:]) for r in conn.execute(text('''SELECT job_id,posting_index,money_index,
            salary_min,salary_max,valid_range,salary_eligible FROM clean.pay_ranges'''))}
        checks['provider_ids_equal_postgres_staging']=set(mongo_jobs)==set(sql_jobs)
        checks['same_selected_original_file']=all(
            mongo_jobs[j]['source_file']==r['source_file'] and mongo_jobs[j]['source_sha256']==r['source_sha256']
            for j,r in sql_jobs.items() if j in mongo_jobs)
        checks['query_occurrence_counts_equal']=all(mongo_jobs[j]['occurrence_count']==n
            for j,n in sql_occurrences.items() if j in mongo_jobs)
        checks['missing_description_states_equal']=all(mongo_jobs[j]['description_state']==r['description_state']
            for j,r in sql_jobs.items() if j in mongo_jobs)
        checks['salary_row_keys_equal']=set(mongo_money)==set(sql_money)
        differences=[k for k in set(mongo_money)&set(sql_money) if mongo_money[k]!=sql_money[k]]
        checks['salary_values_and_flags_equal']=not differences
        checks['postgres_provider_rows_retained']=conn.execute(text('select count(*) from clean.postings')).scalar()==len(sql_jobs)
        counts['postgres_analysis_ad_groups']=conn.execute(text('select count(*) from serving.analysis_jobs')).scalar()
    checks['raw_pages_still_preserved']=db.raw_pages.count_documents(raw_scope)==report['raw_pages']
    counts.update(clean_job_summaries=len(mongo_jobs),clean_pay_ranges=len(mongo_money),
        eligible_salary_ranges=sum(v[3] for v in mongo_money.values()))
    counts.pop('_id',None)
    result=dict(generated_at_utc=datetime.now(timezone.utc).isoformat(),database=db.name,
        postgres_batch_id=batch,**scope,counts=counts,checks=checks,
        salary_difference_examples=[list(k) for k in differences[:5]])
    write_json(ROOT/'reports/mongodb_quality.json',result)
    import os
    from urllib.parse import urlsplit
    mongo_host=urlsplit(os.environ['MONGODB_URI']).hostname
    access=dict(postgresql={'host':engine.url.host,'port':engine.url.port or 5432,'database':engine.url.database,
        'raw':['raw.oews_metro','raw.onet_occupation','raw.onet_software_skills','raw.onet_essential_skills'],
        'processed':['clean.postings','clean.posting_locations','clean.source_postings','clean.pay_ranges','clean.posting_skills','clean.job_entities'],
        'analysis':['serving.analysis_jobs','serving.postings_with_bls','serving.metro_sample_counts',
                    'serving.salary_comparisons','serving.role_skill_comparison','serving.state_salary_field_coverage']},
        mongodb={'host':mongo_host,'database':db.name,'collections':report['collections'],**scope},
        local_raw={'archives':'data/downloads/','government':'data/raw/bls_2025_metro/ and data/raw/onet_31_0_csv/',
            'headcount':'data/raw/headcount_10states/','checksums':'reports/raw_file_manifest.json'},
        credentials='Use local .env; credentials are not included in this inventory.')
    write_json(ROOT/'reports/data_access.json',access)
    client.close()
    failed=[k for k,v in checks.items() if not v]
    if failed:
        raise RuntimeError('Mongo/PostgreSQL validation failed: '+', '.join(failed))
    print(json.dumps(result,indent=2))
    return result


if __name__=='__main__':
    validate()
