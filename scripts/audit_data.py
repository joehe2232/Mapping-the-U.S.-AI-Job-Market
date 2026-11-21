"""Read-only PostgreSQL QA plus SHA-256 verification of every acquired source file."""
import json
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text

from pipeline_common import ROOT, database_engine, sha256, write_json

QUERIES = {
 'table_counts': '''SELECT 'raw.oews_metro' AS table_name,count(*) AS rows FROM raw.oews_metro
 UNION ALL SELECT 'raw.onet_occupation',count(*) FROM raw.onet_occupation
 UNION ALL SELECT 'raw.onet_software_skills',count(*) FROM raw.onet_software_skills
 UNION ALL SELECT 'raw.onet_essential_skills',count(*) FROM raw.onet_essential_skills
 UNION ALL SELECT 'clean.postings',count(*) FROM clean.postings
 UNION ALL SELECT 'clean.excluded_postings',count(*) FROM clean.excluded_postings
 UNION ALL SELECT 'clean.posting_locations',count(*) FROM clean.posting_locations
 UNION ALL SELECT 'clean.source_postings',count(*) FROM clean.source_postings
 UNION ALL SELECT 'clean.pay_ranges',count(*) FROM clean.pay_ranges
 UNION ALL SELECT 'clean.posting_skills',count(*) FROM clean.posting_skills
 UNION ALL SELECT 'serving.postings_with_bls',count(*) FROM serving.postings_with_bls
 UNION ALL SELECT 'serving.analysis_jobs',count(*) FROM serving.analysis_jobs
 UNION ALL SELECT 'serving.salary_comparisons',count(*) FROM serving.salary_comparisons''',
 'role_quality': '''SELECT role,count(*) AS jobs,
 count(*) FILTER(WHERE description_state<>'known' OR description='') AS missing_descriptions,
 count(*) FILTER(WHERE company IS NULL) AS missing_employers,
 count(*) FILTER(WHERE source_salary_observed) AS jobs_with_observed_salary,
 count(*) FILTER(WHERE salary_eligible) AS jobs_with_one_annual_range,
 count(*) FILTER(WHERE occupation_mapping='proxy') AS proxy_mapped_jobs,
 count(*) FILTER(WHERE EXISTS(SELECT 1 FROM clean.posting_skills s WHERE s.job_id=p.job_id)) AS jobs_with_dictionary_skills
 FROM clean.postings p GROUP BY role ORDER BY role''',
 'excluded_titles': '''SELECT reason,title,count(*) AS jobs FROM clean.excluded_postings
 GROUP BY reason,title ORDER BY jobs DESC,title''',
 'salary_quality': '''SELECT salary_quality,currency,period,count(*) AS ranges,
 count(DISTINCT job_id) AS jobs FROM clean.pay_ranges GROUP BY 1,2,3 ORDER BY ranges DESC''',
 'metro_quality': '''SELECT metro_match_status,count(*) AS location_records,
 count(DISTINCT job_id) AS jobs,count(*) FILTER(WHERE metro_name_differs) AS name_differences
 FROM clean.posting_locations GROUP BY 1 ORDER BY 1''',
 'bls_quality': '''SELECT area_type,o_group,employment_status,wage_status,count(*) AS rows
 FROM clean.bls_oews GROUP BY 1,2,3,4 ORDER BY 1,2,3,4''',
 'onet_quality': '''SELECT recommend_suppress,not_relevant,count(*) AS essential_skill_rows,
 count(*) FILTER(WHERE data_value IS NULL) AS missing_rating
 FROM clean.onet_essential_skills GROUP BY 1,2''',
 'state_salary_coverage': 'SELECT * FROM serving.state_salary_field_coverage ORDER BY state_us,role',
 'role_skill_comparison': 'SELECT * FROM serving.role_skill_comparison ORDER BY role,skill',
 'source_coverage': '''SELECT source,count(*) AS source_postings,count(DISTINCT job_id) AS jobs
 FROM clean.source_postings GROUP BY source ORDER BY jobs DESC''',
 'employer_coverage': '''SELECT company,count(*) AS jobs FROM clean.postings
 GROUP BY company ORDER BY jobs DESC NULLS LAST LIMIT 20''',
 'query_coverage': '''SELECT query_state,query_title,count(*) AS occurrences,count(DISTINCT job_id) AS jobs
 FROM staging.headcount_occurrences JOIN audit.active_batch USING(batch_id)
 GROUP BY 1,2 ORDER BY 1,2''',
 'unmatched_metro_codes': '''SELECT source_cbsa,source_cbsa_title,metro_match_status,count(*) AS locations
 FROM clean.posting_locations WHERE source_cbsa IS NOT NULL AND bls_area IS NULL
 GROUP BY 1,2,3 ORDER BY locations DESC''',
 'job_geography': '''WITH g AS (
 SELECT p.job_id,count(*) AS location_entries,
 count(DISTINCT l.state_us) AS states,count(DISTINCT l.bls_area) AS metros
 FROM clean.postings p JOIN clean.posting_locations l USING(job_id) GROUP BY p.job_id)
 SELECT count(*) AS jobs,count(*) FILTER(WHERE location_entries>1) AS multiple_location_jobs,
 count(*) FILTER(WHERE states>1) AS multiple_state_jobs,
 count(*) FILTER(WHERE metros>1) AS multiple_verified_metro_jobs FROM g''',
 'duplicate_content_candidates': '''SELECT company,title,md5(description) AS description_hash,count(*) AS job_ids
 FROM clean.postings WHERE description<>'' GROUP BY company,title,md5(description)
 HAVING count(*)>1 ORDER BY job_ids DESC,company,title''',
 'source_status': '''SELECT posting_status,pay_state,count(*) AS source_postings,
 count(*) FILTER(WHERE invalid_posted_at) AS invalid_posted_dates
 FROM clean.source_postings GROUP BY posting_status,pay_state ORDER BY 1,2''',
 'classification_review': '''WITH sampled AS (
 SELECT role,title,company,occupation_mapping,job_id,source_file,
 row_number() OVER(PARTITION BY role ORDER BY md5(job_id)) AS review_row FROM clean.postings)
 SELECT * FROM sampled WHERE review_row<=6 ORDER BY role,review_row''',
 'entity_quality': '''SELECT group_size,identity_conflict,count(*) AS job_records,count(DISTINCT entity_id) AS ad_groups
 FROM clean.job_entities GROUP BY 1,2 ORDER BY 1,2''',
 'analysis_role_quality': '''SELECT p.role,count(DISTINCT e.entity_id) AS ad_groups,
 count(DISTINCT e.entity_id) FILTER(WHERE p.source_salary_observed) AS groups_with_observed_salary,
 count(DISTINCT e.entity_id) FILTER(WHERE p.description_state='known' AND p.description<>'') AS groups_with_description,
 count(DISTINCT e.entity_id) FILTER(WHERE EXISTS(SELECT 1 FROM clean.posting_skills s WHERE s.job_id=p.job_id)) AS groups_with_dictionary_skills
 FROM clean.postings p JOIN clean.job_entities e USING(batch_id,job_id) GROUP BY p.role ORDER BY p.role''',
 'shared_source_ids': '''SELECT s.posting_id,count(DISTINCT s.job_id) AS provider_job_ids,
 count(DISTINCT e.entity_id) AS analysis_ad_groups
 FROM clean.source_postings s JOIN clean.job_entities e USING(batch_id,job_id)
 WHERE s.posting_id<>'' GROUP BY s.posting_id HAVING count(DISTINCT s.job_id)>1
 ORDER BY provider_job_ids DESC,s.posting_id''',
}

ASSERTIONS = {
 'one_row_per_clean_job': 'SELECT count(*)=count(DISTINCT job_id) FROM clean.postings',
 'serving_join_preserves_jobs': '''SELECT (SELECT count(*) FROM clean.postings)=
     (SELECT count(*) FROM serving.postings_with_bls)''',
 'accepted_plus_excluded_equals_unique_raw': '''SELECT
 (SELECT count(*) FROM clean.postings)+(SELECT count(*) FROM clean.excluded_postings)=
 (SELECT unique_jobs FROM audit.headcount_batches JOIN audit.active_batch USING(batch_id))''',
 'occurrences_reconcile': '''SELECT (SELECT count(*) FROM staging.headcount_occurrences JOIN audit.active_batch USING(batch_id))=
 (SELECT occurrence_count FROM audit.headcount_batches JOIN audit.active_batch USING(batch_id))''',
 'no_bls_join_duplicates': '''SELECT NOT EXISTS(SELECT 1 FROM clean.bls_metro_benchmarks
 GROUP BY bls_area,bls_soc HAVING count(*)>1)''',
 'both_bls_geographies_loaded': "SELECT count(DISTINCT area_type)=2 FROM clean.bls_oews WHERE area_type IN ('4','6')",
 'skills_have_parent_job': '''SELECT NOT EXISTS(SELECT 1 FROM clean.posting_skills s
 LEFT JOIN clean.postings p USING(job_id) WHERE p.job_id IS NULL)''',
 'source_postings_have_parent_job': '''SELECT NOT EXISTS(SELECT 1 FROM clean.source_postings s
 LEFT JOIN staging.headcount_jobs j ON j.batch_id=s.batch_id AND j.job_id=s.job_id WHERE j.job_id IS NULL)''',
 'money_has_parent_posting': '''SELECT NOT EXISTS(SELECT 1 FROM clean.pay_ranges m
 LEFT JOIN clean.source_postings s USING(batch_id,job_id,posting_index) WHERE s.job_id IS NULL)''',
 'locations_have_parent_job': '''SELECT NOT EXISTS(SELECT 1 FROM clean.posting_locations l
 LEFT JOIN staging.headcount_jobs j ON j.batch_id=l.batch_id AND j.job_id=l.job_id WHERE j.job_id IS NULL)''',
 'all_six_roles_have_reference_codes': '''SELECT count(*)=6 FROM clean.role_mappings r
 JOIN clean.onet_occupations o USING(onet_soc)
 WHERE EXISTS(SELECT 1 FROM clean.bls_metro_benchmarks b WHERE b.bls_soc=r.bls_soc)''',
 'salary_eligibility_respects_rules': '''SELECT NOT EXISTS(SELECT 1 FROM clean.pay_ranges WHERE salary_eligible AND
 (currency<>'USD' OR period<>'year' OR NOT valid_range OR outlier_review OR pay_state<>'known'))''',
 'suppression_is_not_zero': "SELECT clean.number('*') IS NULL AND clean.number('**') IS NULL AND clean.number('#') IS NULL AND clean.number('') IS NULL",
 'bad_timestamp_returns_null': "SELECT clean.timestamp_utc('bad-date') IS NULL AND clean.timestamp_utc('2026-02-30') IS NULL",
 'state_pay_counts_partition_denominator': '''SELECT bool_and(sampled_ad_state_associations=
 ads_with_state_source_salary+ads_source_omitted_pay+ads_unknown_pay) FROM serving.state_salary_field_coverage''',
 'every_accepted_job_has_one_entity': '''SELECT (SELECT count(*) FROM clean.job_entities)=
 (SELECT count(*) FROM clean.postings) AND (SELECT count(*)=count(DISTINCT job_id) FROM clean.job_entities)''',
 'merged_ad_groups_have_consistent_identity': '''SELECT NOT EXISTS(
 SELECT entity_id FROM clean.postings p JOIN clean.job_entities e USING(batch_id,job_id)
 GROUP BY entity_id HAVING count(DISTINCT (coalesce(lower(company),''),lower(replace(title,'_',' ')),role))>1)''',
 'one_analysis_row_per_entity': '''SELECT count(*)=count(DISTINCT entity_id) AND count(*)=
 (SELECT count(DISTINCT entity_id) FROM clean.job_entities) FROM serving.analysis_jobs''',
}


def main():
    output = ROOT/'reports'
    output.mkdir(exist_ok=True)
    baseline = json.loads((output/'raw_file_manifest.json').read_text(encoding='utf-8'))['files']
    changed = [r['path'] for r in baseline if not (ROOT/r['path']).exists() or sha256(ROOT/r['path'])!=r['sha256']]
    if changed:
        raise ValueError(f'Raw preservation failed for {len(changed)} files: {changed[:5]}')
    checks = {'all_original_files_unchanged': True}
    print(f'Raw preservation: verified {len(baseline)} original files', flush=True)
    engine = database_engine()
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as conn:
        conn.execute(text('SET TRANSACTION READ ONLY'))
        batch = dict(conn.execute(text('SELECT b.* FROM audit.headcount_batches b JOIN audit.active_batch a USING(batch_id)')).mappings().one())
        results = {}
        for name, query in QUERIES.items():
            frame = pd.read_sql(text(query), conn)
            frame.to_csv(output/(name+'.csv'), index=False)
            results[name] = json.loads(frame.to_json(orient='records'))
            print(f'QA {name}: {len(frame)} result rows', flush=True)
        for name, query in ASSERTIONS.items():
            checks[name] = bool(conn.execute(text(query)).scalar())
        summary = dict(conn.execute(text('''SELECT count(*) AS accepted_jobs,
            count(*) FILTER(WHERE source_salary_observed) AS jobs_with_observed_salary,
            count(*) FILTER(WHERE salary_eligible) AS jobs_with_one_annual_range,
            count(*) FILTER(WHERE description_state<>'known' OR description='') AS missing_descriptions,
            count(*) FILTER(WHERE occupation_mapping='proxy') AS proxy_mapped_jobs,
            count(*) FILTER(WHERE EXISTS(SELECT 1 FROM clean.posting_skills s WHERE s.job_id=p.job_id)) AS jobs_with_skills,
            count(*) FILTER(WHERE EXISTS(SELECT 1 FROM clean.posting_locations l WHERE l.job_id=p.job_id AND l.bls_area IS NOT NULL)) AS jobs_with_any_verified_metro
            FROM clean.postings p''')).mappings().one())
        summary.update(dict(conn.execute(text('''SELECT
            count(*) FILTER(WHERE bls_area IS NOT NULL) AS jobs_with_one_unambiguous_metro,
            count(*) FILTER(WHERE bls_annual_median_wage IS NOT NULL) AS jobs_with_single_metro_wage_benchmark
            FROM serving.postings_with_bls''')).mappings().one()))
        summary.update(dict(conn.execute(text('''SELECT count(*) AS source_linked_ad_groups,
            count(*) FILTER(WHERE source_job_record_count>1) AS groups_with_multiple_provider_jobs
            FROM serving.analysis_jobs''')).mappings().one()))
    report = dict(generated_at_utc=datetime.now(timezone.utc).isoformat(), batch=batch,
                  preserved_files=len(baseline), preserved_bytes=sum(r['bytes'] for r in baseline),
                  checks=checks, summary=summary, results=results)
    write_json(output/'data_quality.json', report)
    failed = [k for k,v in checks.items() if not v]
    if failed:
        raise RuntimeError('Quality assertions failed: '+', '.join(failed))
    print(json.dumps(summary, indent=2))
    print(f'All {len(checks)} checks passed; {len(baseline)} original files unchanged.')


if __name__ == '__main__':
    main()
