# Milestone 2 schema and cleaning rules

`raw` preserves tabular source values. `staging` contains flattened, versioned Headcount snapshots and their provenance. `clean` applies types/flags and selects the active batch. Its `postings`, `posting_locations`, `source_postings` and `pay_ranges` relations are typed, indexed **materialized views** persisted for reliable query performance; other clean relations are views. `serving` contains initial integrations for checking that the sources can work together. `audit` records file and batch identities. These are data-preparation outputs, not final findings.

## Reference data

| Relation | Grain and identifiers | Main fields and rules |
|---|---|---|
| `raw.oews_metro` | One original BLS area/occupation/industry/ownership observation | All 32 source columns are text, plus `source_file`, `source_release`. Includes both metro and nonmetro workbooks and total/major/detailed groups. The historical table name is retained. No raw content constraints or dropped anomalies. |
| `raw.onet_occupation` | One source occupation row | Original O*NET code, title, description, file/release. |
| `raw.onet_software_skills` | One occupation/software-example/category row | Example name, element ID/name, Hot Technology and In Demand source flags; original source values retained. |
| `raw.onet_essential_skills` | One occupation/element/rating-scale observation | Importance (`IM`) and Level (`LV`) are different measures. Original ratings, sample sizes, uncertainty, suppression, date and domain fields retained. |
| `clean.bls_oews` | Same observation grain as raw | `bls_area`, `bls_soc`, typed numeric employment/wages and source metadata. Blank, `*`, `**`, `#` map to numeric NULL with status flags. `#` is top coding, never an exact salary. |
| `clean.bls_metro_benchmarks` | One BLS metro/SOC | `area_type='4'`, `o_group='detailed'`, `naics='000000'`, `own_code='1235'`. Duplicate keys cause a failure, rather than choosing an arbitrary wage. Nonmetro rows remain accessible separately. |
| `clean.onet_occupations` | One O*NET-SOC code | Trimmed codes/title, original description. Code uniqueness checked. |
| `clean.onet_skills` | Unique occupation/example/category/element/flags | Lowercase, trimmed technology examples; Y/N become nullable booleans. These are reference examples, not job-ad frequencies. |
| `clean.onet_essential_skills` | Original rating grain | Typed ratings/sample sizes and nullable suppression/relevance flags; source rating month retained as text. Interpret within scale; honor suppression before analysis. |

## Headcount staging and active clean views

Every staging table has `batch_id`. A new content/rule fingerprint appends a new batch; identical reruns verify counts and append nothing. Indexes enforce processed identifiers. Previous batches are retained; do not sum them as distinct jobs. Source JSON remains in `data/raw/headcount_10states` and is now preserved in MongoDB `ai_job_market.raw_pages`. See the [access guide](DATA_COLLECTION_AND_CLEANING_GUIDE.md) for exact hosts and source/version filters.

| Staging table | Grain / processed key | Content |
|---|---|---|
| `headcount_occurrences` | `(batch_id, source_file, record_index)` | Every returned occurrence, including repeated or missing IDs. Original file hash, title/state query and retrieval timestamp. Use this to trace selection and collection bias. |
| `headcount_jobs` | `(batch_id, job_id)` | Deterministically selected canonical job version, source-file/hash pointer, normalized title/description, role, employer, original field-state labels, currentness and source timestamps. |
| `headcount_locations` | `(batch_id, job_id, location_index)` | Every job-level location, source field state, city, country, ISO region, state, county FIPS, source CBSA code/title/type. Foreign and unresolved locations remain. |
| `headcount_source_postings` | `(batch_id, job_id, posting_index)` | Source posting ID/platform/status/URL, source publication date, source-specific city/state/country/remote flag and pay/location field states. |
| `headcount_pay_ranges` | `(batch_id, job_id, posting_index, money_index)` | Every `money[]` range with cents, currency, period, amount statuses and source path. If money is absent but `pay.value` exists, its ranges are flattened with `source_path='pay.value'`. |
| `headcount_skills` | `(batch_id, job_id, skill)` | Dictionary mentions in normalized title + available description, including jobs later excluded by scope. |
| `headcount_entities` | `(batch_id, job_id)` | Source-linked ad-group ID, member count, representative ID and shared-source/identity-review flags. Exact source-posting IDs connect records only within matching nonempty employer/title/role identities. Description equality alone never merges records. |
| `role_mappings` | `(batch_id, role)` | Versioned copy of `config/role_mappings.csv`, including BLS/O*NET codes, direct/proxy label and rationale. |
| `onet_skill_aliases` | `(batch_id, onet_soc, skill_example, skill)` conceptually | O*NET examples matched by the identical dictionary used for postings. `clean.onet_skill_aliases` removes exact duplicate links. |

The source wrappers distinguish missingness: `known` is usable source evidence; `derived` is provider interpretation; `source_omitted`, `source_unmapped`, `extraction_failed` and missing fields remain distinguishable. Null values are never converted to the literal text `None`. Original wrapper evidence and nested metadata remain in raw JSON, rather than being copied into every relational table.

| Clean relation | Grain | Rules |
|---|---|---|
| `clean.postings` | One accepted job in the active batch | Six-role title classifier, current/nonstale job, at least one explicitly U.S. job-level location. Missing employer/description/pay do not remove a job. Role mapping is joined by configuration. `created_utc` means provider first-seen time, not an employer posting date. |
| `clean.excluded_postings` | One excluded canonical job | Explicit reason: unmatched title, noncurrent/stale, or no explicit U.S. location. The selected staging row and original JSON remain intact. |
| `clean.posting_locations` | One location entry per selected job | Preserves all selected jobs' locations, including excluded jobs. Accepts a CBSA only for an explicitly U.S. metro and a code in BLS 2025. Flags no code, non-U.S./unknown country, unmatched code and title disagreement. State is assigned only from explicit source geography, never the query filter. |
| `clean.source_postings` | One linked source posting | Source date typed to UTC; invalid dates flagged. Source state normalized from USPS, `US-XX` or full state names only with explicit U.S. country. Remote is nullable; unknown is not false. |
| `clean.pay_ranges` | One source money range | Cents / 100 using decimal/numeric arithmetic. A comparison range needs positive, ordered min/max with `ok` statuses. Primary eligibility additionally needs known source pay, USD, explicit `year`, min ≥ 15,000 and max ≤ 1,000,000. No annualization or currency-rate guessing. |
| `clean.posting_skills` | One accepted job/skill | One link per dictionary skill per job, irrespective of repeated mentions or queries. Missing descriptions are reported separately. |
| `clean.job_entities` | One accepted job/ad-group membership | All provider IDs remain inspectable. Missing identity evidence and conflicting identity partitions are kept separate; conflict flags support sensitivity review. |
| `clean.source_posting_metros` | One job/source-posting index | An exact city + state match to job-level locations must identify a single validated metro. Missing/ambiguous locations yield NULL. This does not prove that separate tiers in a posted salary range correspond to that city. |

`source_salary_observed` means a linked known source-pay field has at least one positive extracted amount. It can be true for a partial range, hourly pay or unknown period. `salary_eligible` on a money row means the strict primary range rules pass. On a job it additionally means exactly one distinct eligible annual range across linked postings. None of these measures independently verifies salary disclosure compliance or the provider's extraction against an employer website.

## Initial serving relations

| View | Grain | Interpretation |
|---|---|---|
| `serving.postings_with_bls` | One accepted job | BLS benchmark attached only if all U.S. locations identify a single verified metro. Otherwise metro fields stay NULL. The row count must equal `clean.postings`. No skill explosion in this view. |
| `serving.analysis_jobs` | One source-linked ad group | Accepted representative chosen by latest update and deterministic ID tiebreaker, member count and identity-review flag. The child-based views below use all members' evidence rather than just the representative's location/text. |
| `serving.metro_sample_counts` | Metro/BLS SOC | Distinct sample ad-group associations, remote-ad count and sample associations per 1,000 BLS workers. Aggregates at SOC level before applying the employment denominator. Geography counts overlap; do not add them or label them market vacancy rates. |
| `serving.salary_range_benchmarks` | Distinct job/metro/range/remote evidence | Eligible annual ranges from listed source postings matched to metros. Multiple ranges remain visible for review. |
| `serving.salary_comparisons` | One unambiguous ad-group/metro salary | One unique range across group members per metro; positive BLS median; explicit remote evidence excluded. The midpoint minus BLS median is a descriptive gap, not a causal skill premium. Unknown remote status remains a limitation. |
| `serving.role_skill_comparison` | Role/dictionary skill | Distinct ad-group mentions across members, group denominator, description coverage and whether a matching O*NET software example exists. No zero-frequency skill rows are manufactured. Comparisons cover only the selected dictionary/file. |
| `serving.state_salary_field_coverage` | Sampled state/role | Distinct ad-group/state associations split into source salary observed, source omitted pay and unknown pay. Evidence must come from a currently listed source posting assigned to the same state. A group may count in several states. This is observed field coverage in the collected sample. |

## Audit records and reproducibility

MongoDB database **`ai_job_market`** has separate original and processed collections:

| Collection | Grain | Fields and processing |
|---|---|---|
| `raw_pages` | One original source page file/snapshot | Complete original JSON wrapper under `payload`, original file path/SHA-256, source snapshot and technical retry ID. Includes all five empty pages. Never a cleaning `$merge` target. |
| `collection_manifests` | One original manifest/checkpoint version | Original metadata content and file hash. Two documents for this source snapshot. |
| `clean_job_summaries` | One canonical provider job/source/clean-version | Source page/array pointer, deterministic selected version, query matches/occurrence counts, normalized whitespace, source field-state labels, BSON dates and normalized location arrays. 3,705 documents in the current version. |
| `clean_pay_ranges` | One provider-job/source-posting/money index/source/clean-version | Decimal128 dollars, source currency/period/status, validity and salary-eligibility flags; pointers back to the original page/job. 27,771 documents. |
| `ingestion_runs` | One registered completed source/clean-version | Actual counts, raw-payload verification and completion state. The current source snapshot and cleaning version are recorded in `reports/mongodb_ingestion.json`. |

`scripts/mongo_pipeline.py` defines server-side aggregation stages; `$merge` persists only processed outputs. MongoDB initial cleaning and PostgreSQL processing start from identical original files and are independently reconciled. MongoDB text normalization is whitespace-only; the Python/PostgreSQL text path additionally strips HTML/unescapes entities. Both agree on selected IDs/source files, missing-description labels and every money value/eligibility flag. These initial MongoDB summaries do not replace PostgreSQL entity resolution or BLS/O*NET integrations.

`audit.source_files` registers exact file SHA-256, bytes, table and ingested row count. Legacy starter loads are registered only after multiset reconciliation of every source column; source data is never replaced. A changed file at a registered path causes failure.

`audit.headcount_batches` records the page/rule fingerprint, occurrence and unique-job counts. `audit.active_batch` selects one successfully loaded batch. Transactional loads, an advisory ingestion lock and processed unique indexes prevent partial activation or concurrent duplicate loads. SQL validation failures roll back the load. Only activate a batch through `transform_headcount.py`: it rebuilds the derived materializations and dependent serving views within the same transaction. Raw tables, files and historical staging batches are retained.

`reports/raw_file_manifest.json` inventories every original raw/download file. `audit_data.py` checks those hashes, uses a read-only repeatable-read database transaction, asserts record reconciliation and exports exact metrics. `reports/headcount_ingestion.json` includes raw field-state counts and selected-version statistics. UTC timestamps in these reports are intentional; the snapshot was acquired on the evening of November 20, 2026 in America/New_York.
