-- Read-only demonstration queries. Run after ingest_reference.py and transform_headcount.py.
-- scripts/audit_data.py also runs assertions and saves exact results to reports/.
SELECT * FROM audit.headcount_batches ORDER BY created_at;
SELECT count(*) AS source_linked_ad_groups FROM serving.analysis_jobs;
SELECT group_size,identity_conflict,count(*) AS provider_job_records
FROM clean.job_entities GROUP BY 1,2 ORDER BY 1,2;
SELECT table_name,source_file,row_count,size_bytes,sha256 FROM audit.source_files ORDER BY table_name,source_file;
SELECT area_type,o_group,count(*) FROM clean.bls_oews GROUP BY 1,2 ORDER BY 1,2;
SELECT count(*) AS occurrences,count(DISTINCT job_id) AS unique_ids
FROM staging.headcount_occurrences JOIN audit.active_batch USING(batch_id);
SELECT reason,count(*) FROM clean.excluded_postings GROUP BY reason;
SELECT role,count(*),count(*) FILTER(WHERE description_state<>'known') AS missing_description,
 count(*) FILTER(WHERE source_salary_observed) AS observed_salary_fields,
 count(*) FILTER(WHERE occupation_mapping='proxy') AS soc_proxies
FROM clean.postings GROUP BY role ORDER BY role;
SELECT metro_match_status,count(*) FROM clean.posting_locations GROUP BY metro_match_status;
SELECT salary_quality,count(*) FROM clean.pay_ranges GROUP BY salary_quality;
SELECT (SELECT count(*) FROM clean.postings) AS cleaned_jobs,
 (SELECT count(*) FROM serving.postings_with_bls) AS serving_jobs,
 (SELECT count(*) FROM serving.salary_comparisons) AS unambiguous_ad_metro_salary_comparisons;
-- Both duplicate queries must return zero rows.
SELECT job_id,count(*) FROM clean.postings GROUP BY job_id HAVING count(*)>1;
SELECT bls_area,bls_soc,count(*) FROM clean.bls_metro_benchmarks GROUP BY 1,2 HAVING count(*)>1;
SELECT * FROM serving.state_salary_field_coverage ORDER BY state_us,role;
SELECT * FROM serving.role_skill_comparison WHERE skill IN ('llm','generative ai','mlops') ORDER BY role,skill;
