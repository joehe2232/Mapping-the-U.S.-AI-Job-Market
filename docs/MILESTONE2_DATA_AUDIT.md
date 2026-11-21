# Milestone 2 data audit and teammate handoff

Audit date: November 20, 2026, America/New_York. Team: SecB2 Group 07. Members: Jing Li, Joe He, Han Yang, Yichen Wang. Project manager: Yichen Wang.

This document records the data work requested by the user. The [course instructions](<../../95-815_Data_Engineering_Project_Instructions.pdf>) define evaluation requirements; the [Milestone 1 proposal](<../../Milestone 1_ Project proposal - SecB2 Group 07 .pdf>) supplies the team's context and preliminary plan. They are reference material, not authorization to complete every final-project task now.

## Assignment requirements and this milestone's boundary

| Requirement from the course PDF | Data work completed / handoff |
|---|---|
| A: meaningful problem and at least three questions | Retain the U.S. AI/data labor-market context, audience and motivation from Milestone 1. Refine claims to the observed sample as described below. |
| B: at least three complementary real datasets; at least one semi-structured | BLS OEWS, O*NET and Headcount Labs are three datasets from complementary providers. O*NET's component files are not counted as separate datasets. Headcount is genuinely nested JSON. No project evidence is fabricated. |
| C: structured data in PostgreSQL; preserve raw values; justify suitable JSON storage | Government source cells remain text in PostgreSQL `raw.*`; Headcount originals are now stored in MongoDB `ai_job_market.raw_pages`, with separate aggregation-cleaned collections. Relational derivatives are retained for integration. All original files remain unchanged. Individual teammate access and a government-archive shared backup still require team confirmation. |
| D: initial quality checks, types, missing values, duplicates, integration and useful SQL | Reproducible scripts, typed clean materializations, source-identity grouping, role/SOC and metro joins, flags and exported quality results are implemented. Critical provenance/schema/key failures stop the transaction. Recoverable source problems remain flagged and preserved. |
| Milestone 2 deliverables, items 27–28 | Team must prepare a 3–4 page PDF including the updated proposal, sources/storage/size and initial cleaning, plus a 5 minute video demonstrating actual ingestion and results. Due November 23 at 11:59 p.m. These deliverables are not produced by this data-only task. |
| E / Milestone 3 | Serving previews demonstrate compatibility; final analysis, charts, conclusions, scheduling, sensitivity decisions and presentation remain team work. Keep the shared running meeting-notes document and contribution records current. |

## Sources actually acquired

PostgreSQL and MongoDB connection settings were read locally from `.env`; both connections and ingestion were verified. Credentials were not copied into code, reports or this document. The MongoDB database is `ai_job_market`; its original and processed collections are documented in [the collection/cleaning/access guide](DATA_COLLECTION_AND_CLEANING_GUIDE.md).

| Source | Actual local volume | Information and contribution |
|---|---|---|
| [BLS May 2025 OEWS area estimates](https://www.bls.gov/oes/tables.htm) | ZIP: **39,932,338 bytes**. Three extracted workbooks: **40,532,148 bytes**. MSA: **150,023** rows; BOS: **48,689** rows; **32** source columns each. | Official employed-worker counts and wage distributions by geography/SOC. Provides Q1 employment denominators and Q2 pay benchmarks. These are employment stocks, not live vacancy counts. |
| [O*NET 31.0](https://www.onetcenter.org/database.html) | ZIP: **16,237,378 bytes**. Entire extraction: **46 files, 178,336,027 bytes**. Loaded Occupation Data: **1,016 × 3** source fields; Software Skills: **31,821 × 7**; Essential Skills: **18,200 × 15**. | Occupational definitions, software examples and skill ratings. Supplies role/SOC correspondence and Q3 reference information. Other downloaded files remain archived, not separately claimed as used data. |
| [Headcount Labs](https://headcountlabs.com/docs/) | **251 JSON pages**, plus checkpoint and manifest; **283,981,766 bytes** total. **5,635** query occurrences, **3,705** unique provider job IDs. | Titles, employer names, descriptions, field-state provenance, multiple locations, source-specific listings, pay ranges, currencies/periods and source/observation dates. Primary observed ads for all four questions. |

The complete original-file inventory contains **304 files, 559,019,657 bytes**. See [raw checksums](../reports/raw_file_manifest.json). It includes archives as well as extracted content; these byte totals do not represent independent analytical observations.

The JSON collection was made on the evening of November 20 local time (November 21 UTC). It requests current jobs, sorts by updated time, uses nine search titles over ten selected states and has no explicit `posted_since` window. Five common search titles reached their configured 1,000-return cap. All 90 state/title combinations have saved pages: 85 returned records and five returned empty pages. The occurrence-based query report contains the 85 nonempty segments. Coverage must be described from the checkpoint, saved empty responses and actual query ledger, not assumed balanced or exhaustive.

## What the audit changed

The full proposal-to-implementation change log is in [README.md](../README.md). Headcount replaces Adzuna after the team's subscription/access concerns. BLS and O*NET are retained, with pinned releases and updated parsing. The older README's statement that no data had been acquired was obsolete.

After MongoDB access was prepared, all 251 original Headcount pages were uploaded and read back for content verification. Server-side aggregation now persists **3,705 canonical job summaries** and **27,771 typed/flagged salary ranges** in separate clean collections. Raw pages remain unchanged. The original aggregation's full-text sort exceeded this cluster's **32 MB** limit; selection was changed to sort lightweight source pointers and retrieve selected text/arrays afterward. A repeated import added zero raw pages and left processed counts unchanged.

An executed **30-cell notebook** now demonstrates progressive MongoDB/SQL transformations, before/after tables, source/storage and relational-schema diagrams, duplicate handling, integrated samples and QA. A browser-readable HTML export and report/video PNG/SVG figures accompany it. The SQL files remain reusable production implementation; reading/running the notebook's previews does not require manual SQL-file execution. Both processing paths currently read identical original files, rather than claiming the new MongoDB summaries were the input of the previously built SQL pipeline.

The original government loader selected the first BLS workbook and had ingested only nonmetropolitan data into a table named `oews_metro`. The missing metro workbook was appended. The existing 48,689 rows were reconciled and preserved, and the reference loader was rerun successfully without adding duplicate rows. Its corrected total is **198,712**.

Deduplication required two levels. Removing repeated queries reduces 5,635 occurrences to 3,705 provider IDs. A deeper audit found **3,002 source-posting IDs shared across different provider job IDs**. For example, multiple Coinbase records shared the same job title and source listings. The analysis now groups source-linked records only where nonempty employer, title and role identities also match. This yields **2,815 ad groups**, consolidating **890** provider records while retaining all originals and membership links. **385** groups have multiple provider records. **34** records carry identity-conflict flags where a shared source identifier connects differing identities; those differing partitions stay separate for review. Neither provider IDs nor these ad groups establish numbers of funded vacancies.

An initial title-rule review found four false exclusions caused by underscores and punctuation, including `Engineer_Voice AI` and `AI, Engineer`. Boundary rules were corrected and regression fixtures added. All 3,705 records now match the defined role scope; no scope exclusions remain in this snapshot. This is title-based classification, with a 36-record review sample exported for teammates; job responsibilities and ambiguous manager/hybrid titles still merit review.

## Initial cleaning and measured quality

Raw files and source cells are preserved. Data corrections are confined to flattened/processed structures. Use [data_quality.json](../reports/data_quality.json) as the authoritative run record; CSVs beside it expose each query result. Provider-record metrics below use **3,705** as their denominator and must not be mixed with the **2,815** grouped-ad denominator used in primary serving summaries.

| Quality observation | Handling |
|---|---|
| 1,930 repeated query occurrences; no missing job IDs and no conflicting versions of the same job ID | Preserve every occurrence and query; select a deterministic version per ID. Apply the additional shared-source grouping described above. |
| 25 unavailable descriptions: 15 extraction failures, 10 source omissions | Retain missingness reasons; do not infer absence of skills from missing text. No description imputation. |
| 94 unavailable employer names | Retain provider field states. Missing employer identity is insufficient to merge source-linked records. |
| 2,594 provider records have observed salary amounts on currently listed source postings | This is observed source-field coverage, not independently verified employer disclosure or legal compliance. Missing/failed extraction remains unknown. |
| 27,771 source money entries; 23,388 pass annual-USD range rules across all selected source records | These are range entries, frequently repeated across listings; never report them as job counts. Convert cents to dollars exactly. Keep all ranges, periods, currencies and amount-status flags. |
| 1,172 provider records have exactly one distinct eligible annual range across listed sources | Job-level convenience fields remain conservative. Primary comparisons additionally use ad-group/metro evidence, exclude explicitly remote listings and require one unique range. |
| 3,169 otherwise-valid USD ranges have unknown period; valid hourly/monthly ranges also occur | Preserve but exclude from primary annual comparisons. Do not guess annual period or assume work hours. Incomplete ranges, unknown currency/status and the annual outlier remain flagged separately. |
| 21,335 job-level location entries, including foreign/unknown locations and multi-location jobs | Preserve all child entries; do not assign the state query filter as the job's state. Validate explicit metro codes against BLS 2025. |
| 18,696 location entries have a verified BLS metro code; 2,100 lack a usable metro code and 539 have non-U.S./unknown country | Keep unmatched records and exclusion reasons. Nonmetro and micro areas are not silently converted to metro areas. |
| 3,579 provider records have some verified metro; only 1,975 support one unambiguous metro across all U.S. locations | The one-job preview retains null metro for ambiguous jobs. Multi-geography summaries deduplicate ad groups within each geography and remain non-additive. |
| 1,965 provider records receive an available wage benchmark in the single-metro preview | Unmatched/suppressed occupation-geography wages stay null; serving joins must preserve the provider-record count. |
| 2,889 provider records use a proxy SOC mapping | Preserve direct/proxy flags and mapping notes. AI product manager → IT managers is particularly weak. Generic data/BI analyst titles are not all AI roles. |
| 3,358 provider records mention at least one dictionary skill | Use identical aliases for postings and O*NET Software Skills. Missing descriptions and a limited dictionary constrain recall; unmatched aliases do not prove official classifications omit a concept. |
| Hundreds of employer/title/description duplicate candidates remain | Text similarity alone cannot distinguish repeated ads from separate openings. Source-ID grouping handles supported matches; export remaining content candidates rather than automatically deleting legitimate openings. |

`reports/analysis_role_quality.csv` supplies the grouped-ad denominators and quality counts for final analysis. The **2,815** ad groups comprise **669** data-scientist, **666** ML/AI-engineer, **803** data/BI-analyst, **466** data-engineer, **101** AI-research-scientist and **110** AI-product-manager groups. Across members, **1,777 groups** have observed salary evidence, **2,801** have an available description and **2,503** have dictionary skill mentions. There are **1,072** eligible ad-group/metro salary comparison rows; these geography associations are non-additive and are not 1,072 independently verified vacancies.

`reports/entity_quality.csv` and `shared_source_ids.csv` document entity resolution. `reports/source_coverage.csv`, `employer_coverage.csv` and `query_coverage.csv` expose concentration and sampling. For example, Capital One contributes **575 provider records** and DirectEmployers appears on **1,390 provider records**; these provider-record counts are deliberately not described as independent vacancies.

## Can these data answer the proposal deeply and representatively?

They are complementary and substantial enough for a meaningful data-engineering project. They support **descriptive findings about the collected ads**. The Headcount sample is not a probability sample or complete census: ten selected states, title quotas, updated-first order, provider/ATS coverage, employer concentration, source-linked duplication, multi-location ads and missing fields all affect results. Expanding the same capped collection alone would not make national estimates defensible.

| Original question | Defensible analysis now | Limit / refinement to state explicitly |
|---|---|---|
| Which U.S. metros have the most AI/data postings, absolutely and relative to occupational employment? | Map source-linked ad associations and their ratio to matching BLS employment in observed metros. Aggregate by SOC before using the denominator. | Phrase as **where the collected sample is located**. Quotas mechanically shape counts; do not rank national demand or call the ratio a vacancy rate. Exclude or separately display remote and ambiguous geography. |
| Advertised vs. official pay | Compare unambiguous annual USD ranges to matched metro/SOC medians; report distinct group counts and uncertainty. | Posted ranges vs employed-worker wages, 2026 vs May 2025, seniority, employer mix and proxy occupations are different populations. Multiple pay tiers may lack geographic attribution. No causal premiums. |
| Skills in demand vs. O*NET | Within each role, count distinct ad groups mentioning the fixed dictionary; compare alias coverage to that role's O*NET software examples. | Describe mentions and unmatched examples. The dictionary is limited, missing text is not a negative, and O*NET contains broader categories beyond the selected software file. Essential Skill scales provide context rather than comparable posting frequencies. |
| Salary transparency by state/role | Split sampled ad/state associations into observed salary, source omission and unknown extraction evidence from listed sources in that state. | Call it **observed source salary-field coverage**, not population disclosure rates or evidence of legal compliance. Denominators overlap for multi-state ads. |

If the team insists on national demand ranking, it needs a defined, audited population frame and uncapped enumeration or a defensible sampling design with known inclusion probabilities, plus coverage validation. If the team keeps the current data, the sample-focused refinements above retain the original problem while matching available evidence, as the assignment permits.

## Evidence and remaining work

The scripts have been executed against the configured hosted PostgreSQL and MongoDB databases. The reference rerun reconciled all previously loaded source values. Identical Headcount reruns verified counts without adding records. **All 19 PostgreSQL quality assertions, 11 MongoDB/cross-store checks and six rule tests passed.** Cross-store validation compares every salary key/value/eligibility flag, the selected source files, IDs, occurrence counts and missing-description labels. All **304 original files** remain unchanged. Evidence is in [PostgreSQL QA](../reports/data_quality.json), [MongoDB ingestion](../reports/mongodb_ingestion.json) and [cross-store QA](../reports/mongodb_quality.json). Rule fixtures are separate unit-test inputs and never enter the project datasets.

For the video, show the official source pages and local original archives; query `audit.source_files`; show one raw Headcount page; inspect typed `clean.postings`, child tables and `clean.job_entities`; compare the 3,705 provider rows to 2,815 grouped ads; show actual missingness/range flags and QA results. Avoid credentials on screen.

MongoDB raw storage and initial aggregation cleaning are complete; [the handoff](MONGODB_HANDOFF.md) now records actual collections and teammate access steps. Use [the notebook](../notebooks/Milestone2_Data_Walkthrough.ipynb), [HTML copy](../reports/Milestone2_Data_Walkthrough.html) and [access guide](DATA_COLLECTION_AND_CLEANING_GUIDE.md) for report/video preparation. The team still needs to confirm each teammate's database/network access and shared government-file backup, carry forward the proposal's meeting-notes link and motivation, record source/question changes in meeting notes, and produce the submission PDF/video. Manual identity-conflict adjudication, broader extraction validation, sensitivity analysis and final conclusions remain next-stage work.
