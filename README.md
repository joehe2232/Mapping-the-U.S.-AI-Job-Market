# Mapping the U.S. AI Job Market

95-815 Data Engineering, Fall 2026, SecB2 Group 07. Data collection, PostgreSQL ingestion and initial cleaning for Milestone 2.

The project connects AI/data job postings with official occupational employment, wages and skill examples. The six role groups are data scientist, ML/AI engineer, data/BI analyst, data engineer, AI research scientist and AI product manager. Broad data roles are included as in the proposal; a data analyst posting does not necessarily involve AI.

## Scope and current status

Milestone 2 is due **November 23, 2026 at 11:59 p.m.** The assignment requires a **3–4 page PDF** carrying forward the proposal and adding actual sources, sizes, storage choices and initial quality/cleaning, plus a **5 minute demonstration video**. The data work here supports requirements A–D. The team still owns the submission PDF/video, shared meeting notes and final analysis/presentation. Final charts, conclusions, production scheduling and a complete serving design belong to Milestone 3.

**Completed:** acquisition of three complementary real datasets; PostgreSQL raw ingestion, flattening, SQL cleaning and integration; MongoDB original-page ingestion and aggregation cleaning; cross-store validation; and an executed notebook with schema visuals and before/after examples. **Pending:** individual teammate database/network access, a shared cloud backup of government archives/other local originals, and the team's PDF/video submission. Headcount's raw JSON is now stored in the shared MongoDB deployment; local files remain unchanged.

Start with the [executed notebook](notebooks/Milestone2_Data_Walkthrough.ipynb) or [browser-readable HTML](reports/Milestone2_Data_Walkthrough.html) for the report/video. The [collection, cleaning and access guide](docs/DATA_COLLECTION_AND_CLEANING_GUIDE.md) explains why/how decisions were made and exact database/collection/table/file locations. Read [the audit](docs/MILESTONE2_DATA_AUDIT.md) for suitability and limits, [the dictionary](docs/DATA_DICTIONARY.md) for grains and [the MongoDB handoff](docs/MONGODB_HANDOFF.md) for completed setup and remaining teammate access. Evidence is in [PostgreSQL QA](reports/data_quality.json), [MongoDB/cross-store QA](reports/mongodb_quality.json), and `reports/*.csv`.

## What changed since Milestone 1

| Proposal | Milestone 2 implementation | Reason and effect |
|---|---|---|
| Adzuna Jobs API | **Headcount Labs Jobs API**, collected by `collect_headcount_state_safe.py` | The team changed the job source after encountering subscription/access costs. We use the already acquired Headcount pages; no additional paid requests were made during this audit. Do not claim Adzuna was ingested or that its pricing policy was independently established here. |
| Adzuna title/snippet JSON schema | Headcount field-state wrappers, descriptions, multiple locations, source postings and money arrays | The old Adzuna transformer cannot parse this schema. New file-based transformation retains query provenance and normalizes child records. Descriptions can be substantially fuller, but extraction failures remain missing. |
| Broad U.S. live job coverage | **Ten-state, title-capped snapshot**: PA, NY, CA, TX, WA, MA, IL, VA, GA, NC | Updated-first queries and a 1,000-record cap per search title produce a purposive sample. They cannot establish national vacancy totals, representative metro rankings or population salary-disclosure rates. Jobs can list additional states/countries. |
| BLS OEWS | **Retained**, pinned to May 2025 area estimates | Both metro (`MSA`) and nonmetro (`BOS`) files are preserved. The original loader chose the first workbook and loaded only nonmetro data; it now explicitly ingests both. Only metro rows form the primary metro benchmarks. |
| O*NET | **Retained**, pinned to release 31.0 | Occupation Data, Software Skills and Essential Skills are loaded as separate tables from one dataset. The remaining downloaded O*NET files stay in the raw archive; they are not claimed as additional independent datasets. |
| MongoDB raw JSON + PostgreSQL tables | **Both implemented:** `ai_job_market.raw_pages` in MongoDB; government raw cells and Headcount derivatives in PostgreSQL | MongoDB now performs actual initial aggregation cleaning into separate job/salary collections. Relational derivatives are retained as allowed by D17/D19; the JSON source remains semi-structured. Government-archive shared backup and individual teammate access still need confirmation. |
| Title-to-SOC mapping assumed fairly direct | One direct title mapping and five **explicit proxy mappings** in `config/role_mappings.csv` | O*NET `15-2051.01` is a detailed extension of BLS `15-2051`, not an independent six-digit BLS occupation. AI product managers → IT managers is especially approximate. |
| Adzuna predicted-salary exclusion | Headcount source-pay evidence, currency/period/range checks | Headcount has no equivalent `salary_is_predicted` field in these files. Do not copy Adzuna's flag or infer missing salary means nondisclosure. Main pay comparisons use unambiguous, annual USD source ranges. |
| Scheduled pulls and final analytics | Manual, resumable snapshot acquisition and initial SQL previews | Scheduling, final sensitivity analysis and conclusions are deferred. This does not change the overarching context/problem. |

## Sources and storage

| Dataset | Original location | Raw PostgreSQL / document storage | Cleaned use |
|---|---|---|---|
| [BLS May 2025 OEWS](https://www.bls.gov/oes/tables.htm), [original ZIP](https://www.bls.gov/oes/special-requests/oesm25ma.zip) | `data/downloads/bls_2025_metro.zip`, `data/raw/bls_2025_metro/` | `raw.oews_metro`: **198,712 rows**, all 32 source columns as text plus file/release metadata | `clean.bls_oews`, `clean.bls_metro_benchmarks`: typed wages/employment, suppression flags, metro/SOC benchmarks |
| [O*NET 31.0](https://www.onetcenter.org/database.html), [original ZIP](https://www.onetcenter.org/dl_files/database/db_31_0_csv.zip) | `data/downloads/onet_31_0_csv.zip`, `data/raw/onet_31_0_csv/` | `raw.onet_occupation`: **1,016** rows; `raw.onet_software_skills`: **31,821**; `raw.onet_essential_skills`: **18,200** | Occupational descriptions, technology examples and contextual essential-skill ratings |
| [Headcount Labs Jobs API](https://headcountlabs.com/docs/) | `data/raw/headcount_10states/`: **251 page files, 5,635 occurrences, 3,705 distinct job IDs** | MongoDB database **`ai_job_market`**, collection **`raw_pages`**, holds original wrappers; `collection_manifests` holds source metadata. PostgreSQL `staging.*` holds versioned derivatives. | MongoDB `clean_job_summaries`: **3,705**; `clean_pay_ranges`: **27,771**. PostgreSQL retains **3,705** provider records / **2,815** source-linked analysis groups and reference joins. |

PostgreSQL suits typed tabular government data and SQL joins. Headcount's variable nested arrays, original field states and source-specific objects suit document storage. Flattened relational tables support analysis without repeatedly traversing those arrays. Original ZIPs, extracted files, checkpoint and API response wrappers are preserved independently of processed tables.

## Run the existing acquisition through cleaning

Use Python 3.11+ and a virtual environment. In this Windows workspace the runnable interpreter is `.venv\Scripts\python.exe`; the bare `python` command may resolve to the Windows Store alias.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# On a new machine, copy .env.example to .env and enter credentials locally.
# Never overwrite an existing .env or commit credentials.
.\.venv\Scripts\python.exe scripts/download_sources.py
.\.venv\Scripts\python.exe scripts/ingest_reference.py
.\.venv\Scripts\python.exe scripts/transform_headcount.py
.\.venv\Scripts\python.exe scripts/ingest_headcount_mongo.py
.\.venv\Scripts\python.exe scripts/audit_data.py
.\.venv\Scripts\python.exe scripts/audit_mongodb.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`DATABASE_URL` is needed for PostgreSQL processing; `MONGODB_URI`/`MONGODB_DB` are needed for MongoDB processing and the complete live notebook. `HEADCOUNT_API_KEY` is needed only for new acquisition. The existing PostgreSQL file-based path remains independently runnable. The downloader verifies existing extracted files against the retained ZIP and refuses to overwrite different files. BLS may block automated downloads; use the official page and preserve the resulting archive.

For the walkthrough, install `requirements-notebook.txt`, select the `.venv` kernel and open the executed notebook. `python scripts/build_walkthrough.py` reruns its read-only database previews and exports notebook outputs, HTML and report/video PNG/SVG diagrams. Ordinary Run All does not rebuild database tables or collections. Existing SQL files remain the production implementation; no separate SQL-editor execution is needed for the walkthrough.

`ingest_reference.py` reconciles existing rows with every source cell before registering legacy loads, appends missing files and records checksums in `audit.source_files`. It never replaces raw tables. All BLS rows, occupation groups, missing/suppressed symbols and source columns remain in raw storage. `source_file` uses the existing repository path convention, and filenames/releases are part of provenance.

`transform_headcount.py` reads saved pages without calling the API or MongoDB. It records every query occurrence, deduplicates by canonical `job_id`, and selects the newest version by parsed source timestamps with a deterministic file/index tiebreaker. It also groups different job IDs connected by an identical source-posting ID when employer, title and role agree; missing/conflicting identity evidence remains separate and flagged. The original pages keep every version and the membership ledger preserves every provider ID. Content/rule fingerprints identify batches; identical reruns append nothing. Changed transformation rules create a retained new batch, and `audit.active_batch` selects the current one. Unique keys and validation apply to processed snapshots, never to acquired raw records. The staging text is already flattened and title/description formatting has been normalized; it is **not** an original JSON archive.

SQL performs numeric/date conversion, null handling, suppression flags, salary validation, role/SOC and geographic joins, and initial aggregations. The four larger clean outputs are persisted as typed, indexed materialized views and rebuilt transactionally from retained staging data. Conservative title classification, source-identity grouping and matching the same skill aliases across both text sources happen in Python. [sql/quality_checks.sql](sql/quality_checks.sql) contains convenient read-only demonstration queries. Run `audit_data.py` to enforce assertions and export results.

MongoDB aggregation also performs canonical ID selection, whitespace normalization, date conversion, nested-location reshaping and Decimal128 salary conversion/flags. Its final `$merge` stages target `clean_job_summaries` and `clean_pay_ranges`; `raw_pages` stays untouched. The two processing paths start from the same files; MongoDB summaries are not claimed as the existing PostgreSQL pipeline's upstream input. **All 19 PostgreSQL checks and 11 MongoDB/cross-store checks pass**, including equality of every salary row/value/eligibility flag. Current source/version filters and credential-free host/database locators are in [reports/data_access.json](reports/data_access.json).

## Cleaning decisions that affect interpretation

- The raw occurrence ledger contains **1,930 repeated job-ID occurrences**. A second identity check consolidates **890 additional provider records** into shared-source ad groups. All **3,705 provider records** remain inspectable; `serving.analysis_jobs` contains **2,815 analysis groups**. **34 records** have conflicting identity evidence across a shared source ID and remain flagged for review. Identical description text alone never causes a merge. No missing-ID occurrences or conflicting versions of the same job ID occurred. Reviewing the classifier's four initial exclusions exposed underscore/punctuation boundaries; corrected rules retain all four, and no current records are excluded by scope.
- Keep `known`, `derived`, `source_omitted`, `source_unmapped` and `extraction_failed` distinct. Missing salary fields and failed extraction do not establish that an employer withheld pay.
- Convert money from **cents to dollars**. Primary comparisons require complete positive ranges, known source-pay status, USD, explicit annual period and bounds between $15,000 and $1,000,000. These bounds are review rules, not claims about true market limits. Hourly/monthly/unknown-period amounts stay available and are excluded from the primary comparison. Multiple distinct ranges are flagged rather than averaged silently.
- Validate Headcount's explicit CBSA code against the pinned BLS metro vintage. Preserve unknown, foreign, nonmetro and unmatched locations; do not guess codes from city names. Differences in metro titles are logged. Single-job previews only assign a metro when every U.S. location supports one identical verified metro.
- Main metro/state association counts and skill frequencies use distinct **source-linked ad groups** within each geography/role and are **not additive across geographies**. Source-posting salary comparisons require an exact normalized city/state match to a verified job-level metro, exclude explicitly remote postings and require one unique annual range per ad group/metro. They remain descriptive comparisons between a 2026 convenience snapshot and May 2025 wages. The one-row-per-provider-job view is retained for reconciliation, alongside the grouped analysis view; neither unit establishes true numbers of funded vacancies.
- O*NET Software Skills examples are matched with the same limited dictionary used for postings. `matched_in_onet_software_examples=false` means no matching alias in that role's selected file, not proof that O*NET omits the concept. Essential Skills ratings are contextual references with suppression/scale labels, not percentages of ads requiring a skill.

## Acquisition and teamwork

The current sample is nontrivial for Milestone 2; another API pull is not required to demonstrate ingestion/initial cleaning. More capped pages would not by themselves make the sample representative. Preserve existing collection directories and their exact resume settings. Any future collection should use a new output folder if states, titles, page size or time scope changes, and should check provider quota/billing first.

`collect_headcount_state_safe.py` is the adopted collector. `collect_headcount_capped.py` is the earlier national-title collector and is not the source of this ten-state snapshot. `scripts/ingest_adzuna.py` and `scripts/transform_postings.py` are retained as archived implementations; direct execution now stops with migration guidance. `config/metro_crosswalk.csv` is a legacy empty Adzuna file; Headcount's explicit metro codes replace that manual mapping step.

Share database access and a cloud copy of original source folders with teammates, using credentials outside Git. `data/` and `.env` are ignored. `reports/raw_file_manifest.json` is the checksum inventory used to verify preservation; keep it with the source backup and register new acquisition inventories deliberately. Quality report CSVs/JSON contain actual aggregate results and provenance, not credentials. Do not claim the entire Milestone 2 submission is finished until the team has completed shared raw storage, the PDF and the video.
