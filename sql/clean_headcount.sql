-- All text staging snapshots are retained. These views select the activated batch.
-- Rebuild only derived, active-batch materializations inside the load transaction.
-- CASCADE removes dependent derived views; all are recreated below/build_views.sql.
DO $$ DECLARE target text; kind "char"; BEGIN
 FOREACH target IN ARRAY ARRAY['postings','pay_ranges','source_postings','posting_locations'] LOOP
  SELECT relkind INTO kind FROM pg_class WHERE oid=to_regclass('clean.'||target);
  IF kind='v' THEN EXECUTE 'DROP VIEW clean.'||quote_ident(target)||' CASCADE';
  ELSIF kind='m' THEN EXECUTE 'DROP MATERIALIZED VIEW clean.'||quote_ident(target)||' CASCADE';
  ELSIF kind IS NOT NULL THEN RAISE EXCEPTION USING MESSAGE='Unexpected existing relation clean.'||target;
  END IF;
 END LOOP;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_hc_jobs ON staging.headcount_jobs(batch_id,job_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_hc_occurrences ON staging.headcount_occurrences(batch_id,source_file,record_index);
CREATE UNIQUE INDEX IF NOT EXISTS uq_hc_locations ON staging.headcount_locations(batch_id,job_id,location_index);
CREATE UNIQUE INDEX IF NOT EXISTS uq_hc_sources ON staging.headcount_source_postings(batch_id,job_id,posting_index);
CREATE UNIQUE INDEX IF NOT EXISTS uq_hc_money ON staging.headcount_pay_ranges(batch_id,job_id,posting_index,money_index);
CREATE UNIQUE INDEX IF NOT EXISTS uq_hc_skills ON staging.headcount_skills(batch_id,job_id,skill);
CREATE UNIQUE INDEX IF NOT EXISTS uq_hc_roles ON staging.role_mappings(batch_id,role);
CREATE UNIQUE INDEX IF NOT EXISTS uq_hc_entities ON staging.headcount_entities(batch_id,job_id);

CREATE OR REPLACE VIEW clean.role_mappings AS
SELECT r.* FROM staging.role_mappings r JOIN audit.active_batch a USING(batch_id);

CREATE MATERIALIZED VIEW clean.posting_locations AS
SELECT l.batch_id,l.job_id,l.location_index::integer AS location_index,
 nullif(btrim(l.city),'') AS city, nullif(l.region,'') AS region,
 nullif(l.country,'') AS country,
 CASE WHEN l.country='US' THEN nullif(l.state_us,'') END AS state_us,
 nullif(l.county_fips,'') AS county_fips, nullif(l.cbsa_code,'') AS source_cbsa,
 nullif(l.cbsa_title,'') AS source_cbsa_title, l.cbsa_type,
 l.location_state,
 CASE WHEN l.country='US' AND l.cbsa_type='metro' THEN b.bls_area END AS bls_area,
 CASE WHEN l.country<>'US' THEN 'non_us_or_unknown_country'
      WHEN l.cbsa_type<>'metro' OR l.cbsa_code='' THEN 'no_metro_code'
      WHEN b.bls_area IS NULL THEN 'code_not_in_bls_vintage'
      ELSE 'verified_code' END AS metro_match_status,
 CASE WHEN b.bls_area IS NOT NULL THEN lower(btrim(l.cbsa_title))<>lower(btrim(b.metro_name)) END AS metro_name_differs
FROM staging.headcount_locations l JOIN audit.active_batch a USING(batch_id)
LEFT JOIN (SELECT DISTINCT bls_area,metro_name FROM clean.bls_metro_benchmarks) b ON b.bls_area=l.cbsa_code;
CREATE UNIQUE INDEX pk_clean_locations ON clean.posting_locations(batch_id,job_id,location_index);
CREATE INDEX ix_clean_locations_job ON clean.posting_locations(job_id,state_us,city);
ANALYZE clean.posting_locations;

CREATE MATERIALIZED VIEW clean.source_postings AS
SELECT p.batch_id,p.job_id,p.posting_index::integer AS posting_index,p.posting_id,p.source,
 p.source_posting_id,p.posting_status,nullif(p.posting_url,'') AS posting_url,
 clean.timestamp_utc(p.source_posted_at) AS source_posted_at,
 p.source_posted_at<>'' AND clean.timestamp_utc(p.source_posted_at) IS NULL AS invalid_posted_at,
 p.pay_state,p.location_state,nullif(btrim(p.city),'') AS city,p.state_raw,
 CASE WHEN p.country IN ('US','USA','United States') THEN nullif(p.state_us,'') END AS state_us,
 p.country, CASE p.remote WHEN 'true' THEN true WHEN 'false' THEN false END AS remote
FROM staging.headcount_source_postings p JOIN audit.active_batch a USING(batch_id);
CREATE UNIQUE INDEX pk_clean_sources ON clean.source_postings(batch_id,job_id,posting_index);
CREATE INDEX ix_clean_sources_job ON clean.source_postings(job_id,posting_index);
ANALYZE clean.source_postings;

CREATE MATERIALIZED VIEW clean.pay_ranges AS
WITH typed AS (
 SELECT m.batch_id,m.job_id,m.posting_index::integer AS posting_index,m.money_index::integer AS money_index,
  m.kind,m.currency,m.period,m.source_path,m.min_status,m.max_status,m.amount_status,
  clean.number(m.min_cents)/100 AS salary_min,
  clean.number(m.max_cents)/100 AS salary_max,
  clean.number(m.amount_cents)/100 AS salary_amount,p.pay_state
 FROM staging.headcount_pay_ranges m JOIN audit.active_batch a USING(batch_id)
 JOIN clean.source_postings p ON p.batch_id=m.batch_id AND p.job_id=m.job_id AND p.posting_index=m.posting_index::integer
), flags AS (
 SELECT *, coalesce(salary_min>0 AND salary_max>=salary_min AND min_status='ok' AND max_status='ok',false) AS valid_range,
  coalesce(salary_min>0 OR salary_max>0 OR salary_amount>0,false) AND pay_state='known' AS source_salary_observed
 FROM typed
)
SELECT *, valid_range AND period='year' AND (salary_min<15000 OR salary_max>1000000) AS outlier_review,
 valid_range AND currency='USD' AND period='year' AND pay_state='known'
 AND salary_min>=15000 AND salary_max<=1000000 AS salary_eligible,
 CASE WHEN valid_range THEN (salary_min+salary_max)/2 END AS salary_midpoint,
 CASE WHEN NOT valid_range THEN 'incomplete_or_invalid_range'
      WHEN pay_state<>'known' THEN 'unverified_pay_state'
      WHEN currency IS DISTINCT FROM 'USD' THEN 'non_usd_or_unknown_currency'
      WHEN period IS DISTINCT FROM 'year' THEN 'nonannual_or_unknown_period'
      WHEN salary_min<15000 OR salary_max>1000000 THEN 'outlier_review'
      ELSE 'annual_usd_valid' END AS salary_quality
FROM flags;
CREATE UNIQUE INDEX pk_clean_money ON clean.pay_ranges(batch_id,job_id,posting_index,money_index);
CREATE INDEX ix_clean_money_job ON clean.pay_ranges(job_id,posting_index);
ANALYZE clean.pay_ranges;

CREATE OR REPLACE VIEW clean.excluded_postings AS
SELECT j.batch_id,j.job_id,j.title,
 CASE WHEN j.role='' THEN 'out_of_scope_title'
      WHEN j.currentness<>'current' OR j.stale='true' THEN 'not_current_or_stale'
      ELSE 'no_explicit_us_location' END AS reason
FROM staging.headcount_jobs j JOIN audit.active_batch a USING(batch_id)
WHERE j.role='' OR j.currentness<>'current' OR j.stale='true'
 OR NOT EXISTS(SELECT 1 FROM staging.headcount_locations l
               WHERE l.batch_id=j.batch_id AND l.job_id=j.job_id AND l.country='US');

CREATE MATERIALIZED VIEW clean.postings AS
WITH salaries AS (
 SELECT job_id,bool_or(source_salary_observed) AS source_salary_observed,
  count(DISTINCT (salary_min,salary_max)) FILTER(WHERE salary_eligible) AS eligible_range_count,
  min(salary_midpoint) FILTER(WHERE salary_eligible) AS candidate_midpoint
 FROM clean.pay_ranges m JOIN clean.source_postings s USING(batch_id,job_id,posting_index)
 WHERE s.posting_status='listed' GROUP BY job_id
)
SELECT j.batch_id,j.job_id,j.title,nullif(j.company,'') AS company,nullif(j.company_id,'') AS company_id,
 j.role,r.bls_soc,r.onet_soc,r.occupation_mapping,j.description,
 j.description_state,j.employer_name_state,nullif(j.work_arrangement,'') AS work_arrangement,
 j.work_arrangement_state,clean.timestamp_utc(j.created_utc) AS created_utc,
 clean.timestamp_utc(j.updated_utc) AS updated_utc,clean.timestamp_utc(j.retrieved_utc) AS retrieved_utc,
 j.source_file,j.source_sha256,coalesce(s.source_salary_observed,false) AS source_salary_observed,
 coalesce(s.eligible_range_count,0) AS eligible_range_count,
 coalesce(s.eligible_range_count=1,false) AS salary_eligible,
 CASE WHEN s.eligible_range_count=1 THEN s.candidate_midpoint END AS salary_midpoint
FROM staging.headcount_jobs j JOIN audit.active_batch a USING(batch_id)
JOIN clean.role_mappings r ON j.role=r.role
LEFT JOIN salaries s USING(job_id)
WHERE j.role<>'' AND j.currentness='current' AND j.stale='false'
 AND EXISTS(SELECT 1 FROM staging.headcount_locations l
            WHERE l.batch_id=j.batch_id AND l.job_id=j.job_id AND l.country='US');
CREATE UNIQUE INDEX pk_clean_jobs ON clean.postings(batch_id,job_id);
CREATE UNIQUE INDEX uq_clean_jobs ON clean.postings(job_id);
ANALYZE clean.postings;

CREATE OR REPLACE VIEW clean.job_entities AS
SELECT e.batch_id,e.job_id,e.entity_id,e.representative_job_id,e.group_size::integer AS group_size,
 e.shared_source_id='true' AS shared_source_id,e.identity_conflict='true' AS identity_conflict
FROM staging.headcount_entities e JOIN clean.postings p USING(batch_id,job_id);

CREATE OR REPLACE VIEW clean.posting_skills AS
SELECT s.batch_id,s.job_id,s.skill FROM staging.headcount_skills s
JOIN clean.postings p ON s.batch_id=p.batch_id AND s.job_id=p.job_id;

CREATE OR REPLACE VIEW clean.onet_skill_aliases AS
SELECT DISTINCT s.onet_soc,s.skill_example,s.skill
FROM staging.onet_skill_aliases s JOIN audit.active_batch a USING(batch_id);

DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM clean.role_mappings r LEFT JOIN clean.onet_occupations o USING(onet_soc) WHERE o.onet_soc IS NULL)
 THEN RAISE EXCEPTION 'Role mapping points to nonexistent O*NET code'; END IF;
 IF EXISTS(SELECT 1 FROM clean.role_mappings r WHERE NOT EXISTS(SELECT 1 FROM clean.bls_metro_benchmarks b WHERE b.bls_soc=r.bls_soc))
 THEN RAISE EXCEPTION 'Role mapping points to nonexistent BLS code'; END IF;
 IF EXISTS(SELECT 1 FROM clean.source_postings GROUP BY job_id,posting_id HAVING count(*)>1)
 THEN RAISE EXCEPTION 'Duplicate source posting IDs within job'; END IF;
END $$;
