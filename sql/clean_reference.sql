-- Source symbols and values remain unchanged in raw.*.
CREATE OR REPLACE FUNCTION clean.number(value text) RETURNS numeric
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE WHEN btrim(replace(replace(value, ',', ''), '$', '')) ~ '^[+-]?[0-9]+([.][0-9]+)?$'
 THEN btrim(replace(replace(value, ',', ''), '$', ''))::numeric END
$$;
CREATE OR REPLACE FUNCTION clean.timestamp_utc(value text) RETURNS timestamptz
LANGUAGE plpgsql STABLE AS $$
BEGIN RETURN nullif(btrim(value), '')::timestamptz;
EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow THEN RETURN NULL;
END $$;

CREATE OR REPLACE VIEW clean.bls_oews AS
SELECT btrim(area) AS bls_area, btrim(area_title) AS metro_name,
 btrim(occ_code) AS bls_soc, btrim(occ_title) AS occupational_title,
 btrim(area_type) AS area_type, btrim(o_group) AS o_group,
 btrim(naics) AS naics, btrim(own_code) AS own_code,
 clean.number(tot_emp) AS employment,
 clean.number(a_median) AS annual_median_wage, clean.number(a_mean) AS annual_mean_wage,
 CASE WHEN btrim(tot_emp)='' THEN 'missing'
      WHEN btrim(tot_emp) IN ('*','**') THEN 'suppressed_or_unavailable'
      WHEN clean.number(tot_emp) IS NULL THEN 'invalid' ELSE 'numeric' END AS employment_status,
 CASE WHEN btrim(a_median)='' THEN 'missing'
      WHEN btrim(a_median)='#' THEN 'top_coded'
      WHEN btrim(a_median) IN ('*','**') THEN 'suppressed_or_unavailable'
      WHEN clean.number(a_median) IS NULL THEN 'invalid' ELSE 'numeric' END AS wage_status,
 source_release, source_file
FROM raw.oews_metro;

DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM clean.bls_oews GROUP BY bls_area,bls_soc,naics,own_code HAVING count(*)>1)
 THEN RAISE EXCEPTION 'Duplicate BLS area/occupation/industry/ownership keys'; END IF;
 IF NOT EXISTS(SELECT 1 FROM clean.bls_oews WHERE area_type='4')
 THEN RAISE EXCEPTION 'BLS metropolitan observations missing'; END IF;
 IF EXISTS(SELECT 1 FROM raw.onet_occupation GROUP BY btrim(o_net_soc_code) HAVING count(*)>1)
 THEN RAISE EXCEPTION 'Duplicate O*NET occupation keys'; END IF;
END $$;

CREATE OR REPLACE VIEW clean.bls_metro_benchmarks AS
SELECT * FROM clean.bls_oews
WHERE area_type='4' AND o_group='detailed' AND naics='000000' AND own_code='1235';

CREATE OR REPLACE VIEW clean.onet_occupations AS
SELECT btrim(o_net_soc_code) AS onet_soc, btrim(title) AS occupation, description
FROM raw.onet_occupation WHERE btrim(o_net_soc_code)<>'';

CREATE OR REPLACE VIEW clean.onet_skills AS
SELECT DISTINCT btrim(o_net_soc_code) AS onet_soc, lower(btrim(workplace_example)) AS skill_example,
 btrim(element_name) AS skill_category, btrim(element_id) AS element_id,
 CASE btrim(in_demand) WHEN 'Y' THEN true WHEN 'N' THEN false END AS in_demand,
 CASE btrim(hot_technology) WHEN 'Y' THEN true WHEN 'N' THEN false END AS hot_technology
FROM raw.onet_software_skills WHERE btrim(o_net_soc_code)<>'' AND btrim(workplace_example)<>'';

CREATE OR REPLACE VIEW clean.onet_essential_skills AS
SELECT btrim(o_net_soc_code) AS onet_soc, btrim(element_id) AS element_id,
 btrim(element_name) AS skill, btrim(scale_id) AS scale_id,
 clean.number(data_value) AS data_value, clean.number(n) AS sample_n,
 clean.number(standard_error) AS standard_error,
 CASE btrim(recommend_suppress) WHEN 'Y' THEN true WHEN 'N' THEN false END AS recommend_suppress,
 CASE btrim(not_relevant) WHEN 'Y' THEN true WHEN 'N' THEN false END AS not_relevant,
 date AS source_date, domain_source, source_file
FROM raw.onet_essential_skills;
