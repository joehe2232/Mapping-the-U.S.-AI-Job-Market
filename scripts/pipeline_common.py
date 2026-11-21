"""Shared I/O. Credentials are read locally and never written to audit output."""
import hashlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import Text, create_engine, text

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def database_engine():
    load_dotenv(ROOT / '.env')
    url = os.environ['DATABASE_URL']
    if url.startswith(('postgres://', 'postgresql://')):
        url = 'postgresql+psycopg://' + url.split('://', 1)[1]
    return create_engine(url, connect_args={'connect_timeout': 15,
        'options': '-c jit=off -c statement_timeout=120000', 'application_name':'ai_jobs_m2'}, hide_parameters=True)


def initialize(conn):
    for name in ('raw', 'staging', 'clean', 'serving', 'audit'):
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS {name}'))
    conn.execute(text('''CREATE TABLE IF NOT EXISTS audit.source_files (
        table_name text NOT NULL, source_file text NOT NULL, sha256 text NOT NULL,
        size_bytes bigint NOT NULL, row_count bigint NOT NULL,
        registered_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (table_name, source_file, sha256))'''))
    conn.execute(text('''CREATE TABLE IF NOT EXISTS audit.headcount_batches (
        batch_id text PRIMARY KEY, manifest_sha256 text NOT NULL,
        page_count integer NOT NULL, occurrence_count integer NOT NULL,
        unique_jobs integer NOT NULL, created_at timestamptz NOT NULL DEFAULT now())'''))
    conn.execute(text('''CREATE TABLE IF NOT EXISTS audit.active_batch (
        singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
        batch_id text NOT NULL REFERENCES audit.headcount_batches(batch_id))'''))


def append_text_frame(frame, table, conn, schema='staging'):
    frame = frame.astype('string').fillna('')
    frame.to_sql(table, conn, schema=schema, if_exists='append', index=False,
                 dtype={c: Text() for c in frame.columns}, chunksize=1000)


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
    temp.replace(path)
