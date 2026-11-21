# MongoDB status and teammate access

MongoDB has now been connected, inspected, populated and validated. The configured database is **`ai_job_market`** on **`aijobmarketcluster.7irkp1a.mongodb.net`**. Original data was preserved, and no PostgreSQL tables were removed.

| Collection | Verified contents for the current source/version |
|---|---|
| `raw_pages` | **251** original page wrappers under `payload`: **5,635** returned occurrences, **3,705** distinct provider IDs and **5** empty responses |
| `collection_manifests` | **2** documents preserving the original collection manifest and checkpoint |
| `clean_job_summaries` | **3,705** canonical job documents, created by MongoDB aggregation |
| `clean_pay_ranges` | **27,771** Decimal128-dollar source range documents with validity/eligibility flags |
| `ingestion_runs` | Completed source/version record, actual counts and verification results |

The initially empty `ai_job_market` collection was left untouched. It is not one of the ingested datasets. The planned optional `job_snapshots` collection was not needed: processed summaries already include original-page/array pointers.

MongoDB aggregation performs deterministic job-ID selection, whitespace/date cleaning, nested location reshaping and salary conversion/flags. Sorting source pointers before fetching text/arrays avoids the cluster's 32 MB sort limit. `$merge` writes only the two clean collections. Raw pages were read back and matched to their original files; a repeated import inserted **zero new raw pages** and left processed counts unchanged.

All **11 MongoDB/cross-store checks pass**, including source-file selection, missing-description labels, exact salary row keys/values/eligibility flags and retention of PostgreSQL provider records. The existing **19 PostgreSQL checks** also pass. Original source files remain unchanged.

## What teammates should do

1. Obtain authorized database credentials outside Git/chat screenshots. Use the actual `MONGODB_URI` in a local `.env` and set `MONGODB_DB=ai_job_market`.
2. Ensure the teammate's client IP is authorized in Atlas and the database user has the intended access. Access was verified from this machine; individual teammates' grants/network access were not tested. [Atlas connection prerequisites](https://www.mongodb.com/docs/atlas/connect-to-database-deployment/).
3. In Atlas/Compass, open `ai_job_market`, then the specific collection above. Filter raw documents by `source_snapshot`; filter processed documents by both `source_snapshot` and `clean_version`. Exact current values and PostgreSQL locators are in [the access guide](DATA_COLLECTION_AND_CLEANING_GUIDE.md) and [data_access.json](../reports/data_access.json).
4. Open the [executed notebook](../notebooks/Milestone2_Data_Walkthrough.ipynb) or [HTML copy](../reports/Milestone2_Data_Walkthrough.html) for progressive cleaning examples, diagrams and the recording route.
5. Establish the shared cloud backup location for the government ZIPs and remaining local originals. Headcount JSON is now cloud-stored in MongoDB, but this does not make the local government archives accessible to teammates automatically.

## Reproduce MongoDB processing

```powershell
.\.venv\Scripts\python.exe scripts/ingest_headcount_mongo.py
.\.venv\Scripts\python.exe scripts/audit_mongodb.py
```

These commands use saved source files; they do not call the jobs API. Preserve all originals and use the source/version filters from the current report when inspecting processed data. Keep the PostgreSQL derivatives: course requirements D17/D19 permit relational flattening and MongoDB processing together.
