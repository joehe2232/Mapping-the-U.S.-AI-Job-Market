-- Run by transform_headcount.py, after reference SQL cleaning.
-- One source-linked ad group, with an accepted representative and complete membership ledger.
CREATE OR REPLACE VIEW serving.analysis_jobs AS
SELECT DISTINCT ON (e.entity_id) p.*,e.entity_id,
 count(*) OVER(PARTITION BY e.entity_id) AS source_job_record_count,
 bool_or(e.identity_conflict) OVER(PARTITION BY e.entity_id) AS source_identity_review
FROM clean.postings p JOIN clean.job_entities e USING(batch_id,job_id)
ORDER BY e.entity_id,p.updated_utc DESC NULLS LAST,p.job_id;

-- One row per job. Multi-location jobs retain child records and are not assigned arbitrarily.
CREATE OR REPLACE VIEW serving.postings_with_bls AS
WITH geography AS (
 SELECT job_id,
  CASE WHEN count(DISTINCT bls_area)=1 AND bool_and(bls_area IS NOT NULL)
       THEN min(bls_area) END AS bls_area,
  CASE WHEN count(DISTINCT state_us)=1 AND bool_and(state_us IS NOT NULL)
       THEN min(state_us) END AS state_us,
  count(DISTINCT bls_area) AS matched_metro_count
 FROM clean.posting_locations WHERE country='US' GROUP BY job_id
)
SELECT p.*,g.bls_area,g.state_us,g.matched_metro_count,b.metro_name AS bls_metro_name,
 b.employment AS bls_occupation_employment,b.annual_median_wage AS bls_annual_median_wage
FROM clean.postings p LEFT JOIN geography g USING(job_id)
LEFT JOIN clean.bls_metro_benchmarks b ON b.bls_area=g.bls_area AND b.bls_soc=p.bls_soc;

-- Distinct job/metro associations are non-additive across metros.
CREATE OR REPLACE VIEW serving.metro_sample_counts AS
WITH grouped AS (
 SELECT l.bls_area,p.bls_soc,count(DISTINCT e.entity_id) AS sampled_ad_metro_associations,
  count(DISTINCT e.entity_id) FILTER(WHERE p.work_arrangement='remote') AS remote_ads
 FROM clean.postings p JOIN clean.posting_locations l USING(batch_id,job_id)
 JOIN clean.job_entities e USING(batch_id,job_id)
 WHERE l.bls_area IS NOT NULL GROUP BY l.bls_area,p.bls_soc
)
SELECT g.*,b.metro_name,b.employment,
 CASE WHEN b.employment>0 THEN 1000.0*g.sampled_ad_metro_associations/b.employment END
 AS sampled_associations_per_1000_workers
FROM grouped g LEFT JOIN clean.bls_metro_benchmarks b USING(bls_area,bls_soc);

-- Associate pay only with an exact city+state match to one validated job-level metro.
CREATE OR REPLACE VIEW clean.source_posting_metros AS
SELECT s.job_id,s.posting_index,
 CASE WHEN count(DISTINCT l.bls_area)=1 THEN min(l.bls_area) END AS bls_area
FROM clean.source_postings s LEFT JOIN clean.posting_locations l ON l.job_id=s.job_id
 AND l.state_us=s.state_us AND lower(btrim(l.city))=lower(btrim(s.city))
 AND l.country='US' AND s.country IN ('US','USA','United States')
GROUP BY s.job_id,s.posting_index;

CREATE OR REPLACE VIEW serving.salary_range_benchmarks AS
WITH jobs AS MATERIALIZED (
 SELECT p.batch_id,p.job_id,p.role,p.bls_soc,p.occupation_mapping,p.work_arrangement,e.entity_id
 FROM clean.postings p JOIN clean.job_entities e USING(batch_id,job_id)
), money AS MATERIALIZED (
 SELECT batch_id,job_id,posting_index,salary_min,salary_max,salary_midpoint
 FROM clean.pay_ranges WHERE salary_eligible
), sources AS MATERIALIZED (
 SELECT batch_id,job_id,posting_index,remote FROM clean.source_postings WHERE posting_status='listed'
), geographies AS MATERIALIZED (
 SELECT * FROM clean.source_posting_metros WHERE bls_area IS NOT NULL
), benchmarks AS MATERIALIZED (
 SELECT bls_area,bls_soc,metro_name,annual_median_wage FROM clean.bls_metro_benchmarks
)
SELECT DISTINCT p.batch_id,p.job_id,p.entity_id,p.role,p.bls_soc,p.occupation_mapping,g.bls_area,
 m.salary_min,m.salary_max,m.salary_midpoint,b.metro_name,b.annual_median_wage,
 s.remote,p.work_arrangement
FROM jobs p JOIN money m USING(batch_id,job_id)
JOIN sources s USING(batch_id,job_id,posting_index)
JOIN geographies g USING(job_id,posting_index)
JOIN benchmarks b ON b.bls_area=g.bls_area AND b.bls_soc=p.bls_soc;

-- Primary Q2 comparison: one unambiguous annual USD range per job/metro;
-- exclude explicitly remote postings. Unknown work arrangements remain labelled.
CREATE OR REPLACE VIEW serving.salary_comparisons AS
SELECT batch_id,entity_id,role,bls_soc,occupation_mapping,bls_area,min(metro_name) AS metro_name,
 min(salary_min) AS salary_min,min(salary_max) AS salary_max,min(salary_midpoint) AS salary_midpoint,
 min(annual_median_wage) AS bls_annual_median_wage,
 min(salary_midpoint)-min(annual_median_wage) AS salary_midpoint_minus_bls
FROM serving.salary_range_benchmarks
WHERE remote IS DISTINCT FROM true AND work_arrangement IS DISTINCT FROM 'remote'
GROUP BY batch_id,entity_id,role,bls_soc,occupation_mapping,bls_area
HAVING count(DISTINCT (salary_min,salary_max))=1 AND min(annual_median_wage)>0;

CREATE OR REPLACE VIEW serving.role_skill_comparison AS
WITH frequencies AS (
 SELECT p.role,p.onet_soc,s.skill,count(DISTINCT e.entity_id) AS ads_mentioning_skill
 FROM clean.postings p JOIN clean.posting_skills s USING(batch_id,job_id)
 JOIN clean.job_entities e USING(batch_id,job_id)
 GROUP BY p.role,p.onet_soc,s.skill
), denominators AS (
 SELECT p.role,count(DISTINCT e.entity_id) AS ads_in_role,
 count(DISTINCT e.entity_id) FILTER(WHERE p.description_state='known' AND p.description<>'') AS ads_with_description
 FROM clean.postings p JOIN clean.job_entities e USING(batch_id,job_id) GROUP BY p.role
)
SELECT f.*,d.ads_in_role,d.ads_with_description,
 1.0*f.ads_mentioning_skill/d.ads_in_role AS mention_fraction,
 EXISTS(SELECT 1 FROM clean.onet_skill_aliases o WHERE o.onet_soc=f.onet_soc AND o.skill=f.skill)
 AS matched_in_onet_software_examples
FROM frequencies f JOIN denominators d USING(role);

-- Q4 observes source salary fields; extraction failure remains unknown.
-- Restrict to the sampled query states. A job can belong to several states.
CREATE OR REPLACE VIEW serving.state_salary_field_coverage AS
WITH evidence AS (
 SELECT s.job_id,s.state_us,bool_or(m.source_salary_observed) AS salary_observed,
 bool_and(s.pay_state='source_omitted') AS all_sources_omit_pay
 FROM clean.source_postings s LEFT JOIN clean.pay_ranges m USING(batch_id,job_id,posting_index)
 WHERE s.state_us IS NOT NULL AND s.posting_status='listed' GROUP BY s.job_id,s.state_us
), job_states AS (
 SELECT DISTINCT p.job_id,e.entity_id,p.role,l.state_us FROM clean.postings p
 JOIN clean.posting_locations l USING(batch_id,job_id)
 JOIN clean.job_entities e USING(batch_id,job_id)
 WHERE l.state_us IN (SELECT DISTINCT query_state FROM staging.headcount_occurrences o
                      JOIN audit.active_batch a USING(batch_id))
), ad_states AS (
 SELECT j.entity_id,j.state_us,j.role,bool_or(coalesce(e.salary_observed,false)) AS salary_observed,
 bool_and(coalesce(e.all_sources_omit_pay,false)) AS all_sources_omit_pay
 FROM job_states j LEFT JOIN evidence e USING(job_id,state_us) GROUP BY j.entity_id,j.state_us,j.role
)
SELECT state_us,role,count(*) AS sampled_ad_state_associations,
 count(*) FILTER(WHERE salary_observed) AS ads_with_state_source_salary,
 count(*) FILTER(WHERE all_sources_omit_pay AND NOT salary_observed) AS ads_source_omitted_pay,
 count(*) FILTER(WHERE NOT salary_observed AND NOT all_sources_omit_pay) AS ads_unknown_pay,
 1.0*count(*) FILTER(WHERE salary_observed)/count(*) AS observed_salary_field_fraction
FROM ad_states GROUP BY state_us,role;
