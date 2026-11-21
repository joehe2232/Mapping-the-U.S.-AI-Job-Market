"""Build, execute and export the team's progressive cleaning walkthrough."""
import json
import os
from pathlib import Path
import sys
import textwrap

import nbformat as nbf
from nbclient import NotebookClient
from nbconvert import HTMLExporter

from pipeline_common import ROOT


def build():
    cells=[]
    def md(value):
        cells.append(nbf.v4.new_markdown_cell(textwrap.dedent(value).strip()))
    def code(value):
        cells.append(nbf.v4.new_code_cell(textwrap.dedent(value).strip()))

    md('''
    # Milestone 2: from original sources to explainable analysis data
    **Mapping the U.S. AI Job Market · SecB2 Group 07**

    This notebook is the report/video walkthrough. Saved outputs show an executed run against our real MongoDB and PostgreSQL databases. Open the accompanying HTML export to read without installing Python or entering credentials.

    **Run All reads both databases and saves local figures; it does not rebuild or delete database data.** Production ingestion commands are at the end. Select the repository's `.venv` interpreter to rerun.

    We retain three complementary datasets: BLS OEWS (employment/wages), O*NET (occupation/skill references), and Headcount (nested job JSON). Adzuna was replaced by Headcount after Milestone 1. Our ten-state title-capped sample supports descriptive comparisons, not representative national vacancy estimates.
    ''')
    md('''
    ## 1. Why use both databases?
    Course requirements C10–13 preserve raw data and require structured data in PostgreSQL. D17 permits flattening semi-structured data; D19 explicitly permits MongoDB queries for JSON. They do **not** require deleting relational derivatives when the raw source is JSON.

    We therefore keep original Headcount pages in MongoDB, perform initial cleaning with aggregation pipelines, and retain PostgreSQL derivatives for SOC/metro/skill integration. The two processing paths start from identical original files and are reconciled. The existing SQL pipeline is not claimed to have been loaded from the new MongoDB summaries.
    ''')
    code('''
    from pathlib import Path
    import json, sys
    ROOT = next(p for p in [Path.cwd(), *Path.cwd().parents] if (p/'scripts/pipeline_common.py').exists())
    sys.path.insert(0, str(ROOT/'scripts'))
    import pandas as pd
    import matplotlib.pyplot as plt
    from IPython.display import display, JSON, Markdown
    from sqlalchemy import text
    from ingest_headcount_mongo import mongo_database
    from mongo_pipeline import occurrence_stages, selection_stages, merge_stage
    from pipeline_common import database_engine
    from demo_visuals import architecture, relational_schema, cleaning_counts
    pd.set_option('display.max_colwidth', 85)
    pd.set_option('display.max_columns', 15)
    plt.rcParams.update({'font.size':11, 'figure.dpi':110})
    engine = database_engine()
    mongo_client, db = mongo_database()
    mongo_run = json.loads((ROOT/'reports/mongodb_ingestion.json').read_text(encoding='utf-8'))
    mongo_qa = json.loads((ROOT/'reports/mongodb_quality.json').read_text(encoding='utf-8'))
    pg_qa = json.loads((ROOT/'reports/data_quality.json').read_text(encoding='utf-8'))
    access = json.loads((ROOT/'reports/data_access.json').read_text(encoding='utf-8'))
    snapshot, clean_version = mongo_run['source_snapshot'], mongo_run['clean_version']
    scope = {'source_snapshot':snapshot, 'clean_version':clean_version}
    FIGURES = ROOT/'docs/figures'
    def sql(query, params=None):
        with engine.connect() as connection:
            connection.execute(text('SET TRANSACTION READ ONLY'))
            return pd.read_sql(text(query), connection, params=params)
    assert all(mongo_qa['checks'].values()), 'Resolve MongoDB audit failures first.'
    assert all(pg_qa['checks'].values()), 'Resolve PostgreSQL audit failures first.'
    assert sql('SELECT batch_id FROM audit.active_batch').iloc[0,0] == mongo_qa['postgres_batch_id']
    print('Connected without displaying credentials.')
    print('MongoDB database:', db.name, '| PostgreSQL database:', engine.url.database)
    print('Source snapshot:', snapshot, '| Mongo cleaning version:', clean_version)
    ''')
    code('''
    display(pd.DataFrame([
        {'system':'Local original files','location':'data/downloads/ + data/raw/','purpose':'Original ZIP/XLSX/CSV/JSON and checkpoints'},
        {'system':'MongoDB','location':db.name+'.raw_pages','purpose':'Original nested JSON page payloads'},
        {'system':'MongoDB','location':db.name+'.clean_job_summaries','purpose':'Canonical job selection and initial document cleaning'},
        {'system':'MongoDB','location':db.name+'.clean_pay_ranges','purpose':'Typed salary ranges and eligibility flags'},
        {'system':'PostgreSQL','location':'ai_job_market.raw.*','purpose':'Government source cells as TEXT'},
        {'system':'PostgreSQL','location':'ai_job_market.staging.*','purpose':'Versioned flattened Headcount snapshots'},
        {'system':'PostgreSQL','location':'ai_job_market.clean.* + serving.*','purpose':'Typed data, entity resolution and integration'},
    ]))
    display(architecture(FIGURES))
    plt.close('all')
    ''')
    md('''
    ## 2. Inspect the original semi-structured data
    **Before cleaning:** a page contains query metadata, a `response.data` array, field-state wrappers, and nested location/source-posting/money arrays. JSON remains semi-structured after we create relational copies. This preview uses one real job and shortens its description only for display.
    ''')
    code('''
    original_page = db.raw_pages.find_one({'source_snapshot':snapshot, 'payload.response.data.0':{'$exists':True}},
        {'source_file':1, 'source_sha256':1, 'payload.response.data':{'$slice':1}})
    original_job = original_page['payload']['response']['data'][0]
    print('Original file:', original_page['source_file'])
    print('File SHA-256:', original_page['source_sha256'])
    preview = {k:original_job.get(k) for k in ['job_id','title','employer_name','work_arrangement']}
    preview['description'] = {'state':original_job['description'].get('state'),
                              'value_preview':(original_job['description'].get('value') or '')[:240]}
    preview['first_location'] = (original_job.get('locations') or [None])[0]
    preview['first_source_money'] = (original_job.get('postings') or [{}])[0].get('money',[])[:1]
    display(JSON(preview))
    ''')
    md('''
    ## 3. MongoDB: expand pages and count repeated queries
    `$unwind` exposes each returned occurrence. The same job can be found by several state/title queries, so an occurrence is not a unique job. Empty responses must also stay in raw storage.
    ''')
    code('''
    page_counts = list(db.raw_pages.aggregate([
        {'$match':{'source_snapshot':snapshot}},
        {'$project':{'returned':{'$size':'$payload.response.data'}}},
        {'$group':{'_id':None,'page_files':{'$sum':1},'returned_occurrences':{'$sum':'$returned'},
                    'empty_pages':{'$sum':{'$cond':[{'$eq':['$returned',0]},1,0]}}}}
    ]))[0]
    display(pd.DataFrame([{k:v for k,v in page_counts.items() if k!='_id'}]))
    repeated = list(db.raw_pages.aggregate(occurrence_stages(snapshot) + [
        {'$group':{'_id':'$job.job_id','returned_occurrences':{'$sum':1}}},
        {'$match':{'returned_occurrences':{'$gt':1}}},
        {'$sort':{'returned_occurrences':-1,'_id':1}}, {'$limit':5}
    ], allowDiskUse=False))
    display(pd.DataFrame(repeated).rename(columns={'_id':'job_id'}))
    ''')
    md('''
    ## 4. MongoDB: select a deterministic job version
    Sort by source update time, curation time, source-file path and array index; then take the first record per job ID. Query matches and occurrence counts remain attached. We sort lightweight pointers before fetching text/arrays because this Atlas tier has a 32 MB in-memory sort limit. The raw pages are unchanged.
    ''')
    code('''
    selection_pipeline = selection_stages(snapshot)
    display(JSON([stage for stage in selection_pipeline if '$sort' in stage or '$group' in stage]))
    selected = list(db.raw_pages.aggregate(selection_pipeline + [
        {'$project':{'_id':0,'job_id':1,'source_file':1,'record_index':1,'updated_utc':1,'occurrence_count':1}},
        {'$limit':5}
    ], allowDiskUse=False))
    display(pd.DataFrame(selected))
    print('Persisted canonical job documents:', db.clean_job_summaries.count_documents(scope))
    ''')
    md('''
    ## 5. MongoDB: normalize text, types and missingness
    **After initial document cleaning:** titles/text have normalized whitespace, observation dates are BSON dates, and locations remain a structured array. `source_omitted` and `extraction_failed` remain distinct; missing descriptions are NULL, not fabricated text or evidence of absent skills. PostgreSQL's text path additionally strips HTML/unescapes entities using the shared Python rules.
    ''')
    code('''
    normalized_job = db.clean_job_summaries.find_one(dict(scope, job_id=original_job['job_id']))
    display(pd.DataFrame([
        {'field':'title','before':original_job['title'],'after':normalized_job['title']},
        {'field':'first_seen','before':original_job['job_first_seen_at'],'after':normalized_job['first_seen_utc']},
        {'field':'description state','before':original_job['description'].get('state'),'after':normalized_job['description_state']},
        {'field':'location shape','before':'Nested field-state array','after':str(len(normalized_job['locations']))+' normalized entries'},
    ]))
    missingness = list(db.clean_job_summaries.aggregate([
        {'$match':scope}, {'$group':{'_id':'$description_state','provider_records':{'$sum':1}}},
        {'$sort':{'provider_records':-1}}
    ]))
    display(pd.DataFrame(missingness).rename(columns={'_id':'description_state'}))
    missing_example = db.clean_job_summaries.find_one(dict(scope,description_state='extraction_failed'),
        {'_id':0,'job_id':1,'description_state':1,'description':1})
    display(missing_example)
    ''')
    md('''
    ## 6. MongoDB: source money to exact dollar ranges
    The production aggregation unwinds source postings and money arrays, uses `$convert` to Decimal128, divides cents by 100, and applies explicit validity/currency/period/source-status rules. Annual USD ranges outside the review bounds, incomplete ranges and unknown periods stay stored with flags. They are not silently repaired.
    ''')
    code('''
    example_range = (db.clean_pay_ranges.find_one(dict(scope,job_id=original_job['job_id'],salary_eligible=True))
                     or db.clean_pay_ranges.find_one(dict(scope,salary_eligible=True)))
    page = db.raw_pages.find_one({'_id':example_range['raw_page_id']},{'payload.response.data':1})
    job = page['payload']['response']['data'][example_range['record_index']]
    posting = job['postings'][example_range['posting_index']]
    raw_money = posting.get('money',[])[example_range['money_index']]
    display(pd.DataFrame([
        {'field':'minimum','before':raw_money.get('min_cents'),'before_type':'integer cents',
         'after':str(example_range['salary_min']),'after_type':'Decimal128 dollars'},
        {'field':'maximum','before':raw_money.get('max_cents'),'before_type':'integer cents',
         'after':str(example_range['salary_max']),'after_type':'Decimal128 dollars'},
        {'field':'period','before':raw_money.get('period'),'before_type':'source evidence',
         'after':example_range['period'],'after_type':'retained; never guessed'},
        {'field':'primary comparison eligible','before':'Not yet evaluated','before_type':'',
         'after':str(example_range['salary_eligible']),'after_type':'boolean'},
    ]))
    # An actual, read-only MongoDB conversion preview for this original page/job.
    cents_preview = list(db.raw_pages.aggregate([
        {'$match':{'_id':example_range['raw_page_id']}}, {'$unwind':'$payload.response.data'},
        {'$match':{'payload.response.data.job_id':example_range['job_id']}},
        {'$unwind':'$payload.response.data.postings'},
        {'$unwind':'$payload.response.data.postings.money'},
        {'$project':{'_id':0,'min_cents':'$payload.response.data.postings.money.min_cents',
            'min_dollars':{'$divide':[{'$convert':{'input':'$payload.response.data.postings.money.min_cents',
                'to':'decimal','onError':None,'onNull':None}},100]},
            'period':'$payload.response.data.postings.money.period'}}, {'$limit':3}
    ]))
    display(pd.DataFrame(cents_preview))
    ''')
    code('''
    salary_before_after = sql("""
        SELECT DISTINCT ON (p.salary_quality) p.salary_quality,
          m.min_cents AS source_min_cents, m.max_cents AS source_max_cents,
          p.salary_min AS cleaned_min_dollars, p.salary_max AS cleaned_max_dollars,
          p.currency, p.period, p.valid_range, p.salary_eligible
        FROM staging.headcount_pay_ranges m JOIN clean.pay_ranges p
          ON m.batch_id=p.batch_id AND m.job_id=p.job_id
          AND m.posting_index::integer=p.posting_index AND m.money_index::integer=p.money_index
        ORDER BY p.salary_quality,p.job_id,p.posting_index,p.money_index
    """)
    display(salary_before_after)
    print('PostgreSQL and MongoDB agree on every salary row key, value and eligibility flag:',
          mongo_qa['checks']['salary_values_and_flags_equal'])
    ''')
    md('''
    ## 7. MongoDB arrays to relational child tables
    A provider job is not a single location or a single salary range. `$unwind` produces entries; foreign/unknown locations remain inspectable. A state query is collection metadata, not permission to assign every result to that state. MongoDB retains source CBSA codes; PostgreSQL verifies them against the pinned BLS metro vintage.
    ''')
    code('''
    locations = list(db.clean_job_summaries.aggregate([
        {'$match':dict(scope,job_id=original_job['job_id'])}, {'$unwind':'$locations'},
        {'$project':{'_id':0,'job_id':1,'city':'$locations.city','source_region':'$locations.region',
          'country':'$locations.country','state_us':'$locations.state_us','source_cbsa':'$locations.source_cbsa'}},
        {'$limit':6}
    ]))
    display(pd.DataFrame(locations))
    display(sql('SELECT metro_match_status,count(*) AS location_entries FROM clean.posting_locations GROUP BY 1 ORDER BY 1'))
    display(relational_schema(FIGURES))
    plt.close('all')
    ''')
    md('''
    ## 8. SQL: preserve BLS source symbols, then type valid numbers
    Before cleaning, even valid numbers are TEXT in `raw.*`. Symbols and blanks are source evidence. The inline CASE below illustrates the same strict numeric rule used by `clean.number`; suppression/top coding become numeric NULL with a separate status, never zero. Both metro and nonmetro workbooks remain stored; only detailed metro observations form the primary benchmark.
    ''')
    code(r'''
    bls_before_after = sql("""
        WITH examples AS (
            SELECT DISTINCT ON (a_median) area,occ_code,tot_emp,a_median
            FROM raw.oews_metro WHERE a_median IN ('*','**','#','')
            UNION ALL
            SELECT area,occ_code,tot_emp,a_median FROM raw.oews_metro
            WHERE area='41860' AND occ_code='15-2051'
        )
        SELECT area,occ_code,tot_emp AS raw_employment,a_median AS raw_median,
          pg_typeof(a_median)::text AS raw_type,
          CASE WHEN btrim(replace(replace(a_median,',',''),'$','')) ~ '^[+-]?[0-9]+([.][0-9]+)?$'
               THEN btrim(replace(replace(a_median,',',''),'$',''))::numeric END AS typed_median,
          CASE WHEN a_median='#' THEN 'top_coded'
               WHEN a_median IN ('*','**') THEN 'suppressed_or_unavailable'
               WHEN a_median='' THEN 'missing' ELSE 'numeric' END AS reason
        FROM examples ORDER BY reason,area
    """)
    display(bls_before_after)
    display(sql("SELECT area_type,o_group,count(*) AS source_rows FROM clean.bls_oews GROUP BY 1,2 ORDER BY 1,2"))
    ''')
    md('''
    ## 9. SQL: normalize O*NET examples and join occupation codes
    Codes remain text so punctuation and leading zeros are preserved. Technology examples become lowercase/trimmed strings; Y/N flags become nullable booleans. O*NET's `.01` extension maps to the corresponding six-digit BLS SOC. Five role mappings are proxies and remain labelled; generic analyst and AI-product-manager benchmarks are especially approximate.
    ''')
    code('''
    display(sql("""
        SELECT r.o_net_soc_code,r.workplace_example AS original_example,
               lower(btrim(r.workplace_example)) AS cleaned_example,
               r.in_demand AS original_flag,
               CASE btrim(r.in_demand) WHEN 'Y' THEN true WHEN 'N' THEN false END AS cleaned_flag
        FROM raw.onet_software_skills r
        WHERE r.o_net_soc_code='15-2051.00' AND lower(r.workplace_example) LIKE '%python%'
        LIMIT 5
    """))
    display(sql("""
        SELECT r.role,r.bls_soc,r.onet_soc,o.occupation,r.occupation_mapping,r.notes
        FROM clean.role_mappings r JOIN clean.onet_occupations o USING(onet_soc) ORDER BY r.role
    """))
    ''')
    md('''
    ## 10. Beyond job IDs: resolve supported source-linked duplicates
    Different provider IDs sometimes contain the same source-posting IDs. We link them only when employer, title and role also agree. Missing/conflicting identity evidence stays separate and flagged. Identical description text alone never causes a merge. All provider records and every group membership remain available.
    ''')
    code('''
    display(sql("""
        WITH example AS (SELECT entity_id FROM clean.job_entities GROUP BY entity_id
          ORDER BY count(*) DESC,entity_id LIMIT 1)
        SELECT p.job_id,p.title,p.company,e.entity_id,e.group_size,e.identity_conflict
        FROM clean.postings p JOIN clean.job_entities e USING(batch_id,job_id)
        JOIN example x USING(entity_id) ORDER BY p.job_id LIMIT 6
    """))
    counts = mongo_qa['counts']
    display(cleaning_counts(FIGURES,counts['occurrences'],counts['clean_job_summaries'],counts['postgres_analysis_ad_groups']))
    plt.close('all')
    ''')
    md('''
    ## 11. SQL integration: demonstrate usable analysis rows
    A salary comparison requires a listed source, valid annual USD range, a supported city/state-to-metro match, a positive BLS median and one unambiguous range per ad group/metro. Explicitly remote evidence is excluded. A 2026 posting range versus May 2025 worker wages is descriptive, not a causal pay premium. Multi-metro rows are non-additive.
    ''')
    code('''
    display(sql("""
        SELECT entity_id,role,occupation_mapping,metro_name,salary_min,salary_max,
               salary_midpoint,bls_annual_median_wage,salary_midpoint_minus_bls
        FROM serving.salary_comparisons ORDER BY entity_id,bls_area LIMIT 6
    """))
    display(sql("""
        SELECT role,skill,ads_mentioning_skill,ads_in_role,mention_fraction,
               matched_in_onet_software_examples
        FROM serving.role_skill_comparison
        WHERE skill IN ('llm','generative ai','mlops') ORDER BY role,skill LIMIT 12
    """))
    ''')
    md('''
    ## 12. Before/after summary and validation
    Missingness and uncertain records are preserved, not claimed to be solved by deleting them. These are actual captured results; the database retains the original evidence behind each decision.
    ''')
    code('''
    display(pd.DataFrame([
        {'step':'Repeated searches','before':f"{counts['occurrences']:,} occurrences",'after':f"{counts['clean_job_summaries']:,} canonical provider records",'retained_evidence':'raw_pages + query occurrence ledger'},
        {'step':'Cross-ID repeats','before':f"{counts['clean_job_summaries']:,} provider records",'after':f"{counts['postgres_analysis_ad_groups']:,} analysis groups",'retained_evidence':'clean.job_entities membership + conflict flags'},
        {'step':'Money','before':'Nested cents; mixed periods/currencies','after':f"{counts['clean_pay_ranges']:,} typed source ranges; {counts['eligible_salary_ranges']:,} annual USD eligible",'retained_evidence':'Original money + range/status flags'},
        {'step':'Government types','before':'TEXT numbers and suppression symbols','after':'Numeric values or NULL + explicit reason','retained_evidence':'raw.oews_metro + original workbooks'},
        {'step':'Geography','before':'Nested locations, including foreign/unknown','after':'Location rows + verified/unknown metro status','retained_evidence':'Original arrays; no guessed metro'},
    ]))
    checks = pd.DataFrame([
        {'validation':'PostgreSQL','check':k,'passed':v} for k,v in pg_qa['checks'].items()
    ] + [
        {'validation':'MongoDB / cross-store','check':k,'passed':v} for k,v in mongo_qa['checks'].items()
    ])
    display(checks)
    assert checks['passed'].all()
    assert db.raw_pages.count_documents({'source_snapshot':snapshot}) == counts['pages']
    assert db.clean_job_summaries.count_documents(scope) == counts['clean_job_summaries']
    assert db.clean_pay_ranges.count_documents(scope) == counts['clean_pay_ranges']
    print('All displayed checks pass; raw pages and PostgreSQL derivatives remain stored.')
    ''')
    md('''
    ## 13. Exact access points and five-minute video path
    The following locators intentionally omit credentials. Keep them in your local `.env`. Access from this machine is verified; teammates still need their own authorized network/database access.

    Suggested recording: **0:00–0:35** section 1 storage diagram; **0:35–1:10** original JSON and collection counts; **1:10–2:10** sections 4–6 MongoDB cleaning and cents example; **2:10–3:00** BLS/O*NET before/after; **3:00–4:05** duplicate grouping and schema; **4:05–5:00** integrated rows, QA and sampling limits.
    ''')
    code('''
    display(pd.DataFrame([
        {'system':'PostgreSQL','host':access['postgresql']['host'],'port':access['postgresql']['port'],'database':access['postgresql']['database']},
        {'system':'MongoDB Atlas','host':access['mongodb']['host'],'port':'Atlas SRV driver discovery','database':access['mongodb']['database']}
    ]))
    display(pd.DataFrame([{'MongoDB collection':name,'purpose':purpose} for purpose,name in access['mongodb']['collections'].items()]))
    print('Current Mongo filters:',scope)
    print('Current PostgreSQL batch:',mongo_qa['postgres_batch_id'])
    print('Connection credentials: local .env only.')
    mongo_client.close()
    engine.dispose()
    ''')
    md('''
    ## Rebuild stored data only when needed
    Notebook preview cells show progressive transformations directly. Production scripts/SQL remain the versioned implementation so a recording notebook cannot accidentally replace raw data or drift from the pipeline. No separate SQL-editor execution is needed to read this walkthrough.

    From the repository root:
    ```powershell
    .\\.venv\\Scripts\\python.exe -m pip install -r requirements-notebook.txt
    .\\.venv\\Scripts\\python.exe scripts/ingest_reference.py
    .\\.venv\\Scripts\\python.exe scripts/transform_headcount.py
    .\\.venv\\Scripts\\python.exe scripts/ingest_headcount_mongo.py
    .\\.venv\\Scripts\\python.exe scripts/audit_data.py
    .\\.venv\\Scripts\\python.exe scripts/audit_mongodb.py
    .\\.venv\\Scripts\\python.exe scripts/build_walkthrough.py
    ```

    The MongoDB production pipelines end in `$merge` to **clean_job_summaries** and **clean_pay_ranges**, never `raw_pages`. [MongoDB aggregation documentation](https://www.mongodb.com/docs/manual/core/aggregation-pipeline/) explains that ordinary aggregation previews do not modify collections; `$merge` explicitly persists derived output.

    Full collection/cleaning rationale and access instructions: `docs/DATA_COLLECTION_AND_CLEANING_GUIDE.md`. Detailed limitations: `docs/MILESTONE2_DATA_AUDIT.md`. Schema/grains: `docs/DATA_DICTIONARY.md`. Raw file checksums: `reports/raw_file_manifest.json`.
    ''')

    notebook=nbf.v4.new_notebook(cells=cells,metadata={
        'kernelspec':{'display_name':'Python (.venv)','language':'python','name':'python3'},
        'language_info':{'name':'python','version':'.'.join(map(str,sys.version_info[:3]))}})
    target=ROOT/'notebooks/Milestone2_Data_Walkthrough.ipynb'
    target.parent.mkdir(exist_ok=True)
    # Use a kernel inside this environment, rather than the Windows Store python alias.
    kernel=Path(sys.prefix)/'share/jupyter/kernels/ai_jobs_m2'
    kernel.mkdir(parents=True,exist_ok=True)
    (kernel/'kernel.json').write_text(json.dumps({'argv':[sys.executable,'-m','ipykernel_launcher','-f','{connection_file}'],
        'display_name':'AI Jobs Milestone 2 (.venv)','language':'python'}),encoding='utf-8')
    def progress(cell,cell_index,**kwargs):
        if cell['cell_type']=='code':print(f'Executed cell {cell_index+1}/{len(cells)}',flush=True)
    os.environ['PYTHONIOENCODING']='utf-8'
    client=NotebookClient(notebook,timeout=240,kernel_name='ai_jobs_m2',
        resources={'metadata':{'path':str(ROOT)}},on_cell_executed=progress,store_widget_state=False)
    client.execute()
    nbf.validate(notebook)
    nbf.write(notebook,target)
    exporter=HTMLExporter(template_name='lab')
    body,_=exporter.from_notebook_node(notebook)
    html=ROOT/'reports/Milestone2_Data_Walkthrough.html'
    html.write_text(body,encoding='utf-8')
    print('Saved executed notebook:',target.name)
    print('Saved browser-readable report:',html.name)


if __name__=='__main__':
    build()
