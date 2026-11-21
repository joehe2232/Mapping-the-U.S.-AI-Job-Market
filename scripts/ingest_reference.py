"""Append all OEWS area workbooks and selected O*NET tables; never replace raw data.

Existing starter loads are adopted only after every source cell is reconciled.
Original files/ZIPs remain unchanged. Identical repeated loads are no-ops.
"""
import re

import pandas as pd
from sqlalchemy import inspect, text

from pipeline_common import ROOT, append_text_frame, database_engine, initialize, sha256


def snake(name):
    return re.sub(r'_+', '_', re.sub(r'[^a-z0-9]+', '_', str(name).strip().lower())).strip('_')


def normalized_columns(frame):
    columns = [snake(c) for c in frame.columns]
    if len(set(columns)) != len(columns) or not all(columns):
        raise ValueError('Ambiguous normalized source column names')
    frame.columns = columns
    return frame.astype('string').fillna('')


def frame_digest(frame):
    # Multiset equality includes duplicates and every cell, independent of SQL row order.
    return sorted(pd.util.hash_pandas_object(frame, index=False).tolist())


def load_raw(conn, frame, table, file, release):
    frame = normalized_columns(frame)
    file_key = file.relative_to(ROOT).as_posix()
    frame['source_file'] = file_key
    frame['source_release'] = release
    digest = sha256(file)
    registered = conn.execute(text('''SELECT sha256 FROM audit.source_files
        WHERE table_name=:table AND replace(source_file,chr(92),'/')=:file'''),
        {'table': table, 'file': file_key}).scalars().all()
    if registered and digest not in registered:
        raise ValueError(f'{file.name} changed. Preserve the old file and use a new release path.')
    previous = pd.DataFrame(columns=frame.columns)
    if inspect(conn).has_table(table, schema='raw'):
        previous = pd.read_sql(text(f"SELECT * FROM raw.{table} WHERE replace(source_file,chr(92),'/')=:file"), conn,
                               params={'file': file_key}).astype('string').fillna('')
    if len(previous):
        comparison = [c for c in frame.columns if c!='source_file']
        if set(previous.columns) != set(frame.columns) or frame_digest(previous[comparison]) != frame_digest(frame[comparison]):
            raise ValueError(f'Existing raw.{table} does not exactly match {file.name}; no data replaced.')
        action = 'verified existing'
    elif registered:
        raise ValueError(f'Registered raw rows are missing for {file.name}')
    else:
        append_text_frame(frame, table, conn, schema='raw')
        action = 'appended'
    if digest not in registered:
        conn.execute(text('''INSERT INTO audit.source_files(table_name,source_file,sha256,size_bytes,row_count)
            VALUES (:table,:file,:digest,:size,:rows) ON CONFLICT DO NOTHING'''),
            {'table': table, 'file': file_key, 'digest': digest,
             'size': file.stat().st_size, 'rows': len(frame)})
    print(f'raw.{table}: {action} {len(frame):,} rows from {file.name}', flush=True)


def main():
    engine = database_engine()
    with engine.begin() as conn:
        initialize(conn)
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('ai_jobs_reference_ingest'))"))
        # Explicit names avoid selecting only BOS or a file-description workbook.
        bls = ROOT / 'data/raw/bls_2025_metro'
        for name in ('BOS_M2025_dl.xlsx', 'MSA_M2025_dl.xlsx'):
            candidates = list(bls.rglob(name))
            if len(candidates) != 1:
                raise FileNotFoundError(f'Expected exactly one {name} under {bls}')
            file = candidates[0]
            frame = pd.read_excel(file, sheet_name=0, dtype=str, keep_default_na=False)
            if not {'AREA', 'OCC_CODE', 'AREA_TYPE', 'TOT_EMP', 'A_MEDIAN'} <= set(frame.columns):
                raise ValueError(f'Unexpected BLS schema: {name}')
            load_raw(conn, frame, 'oews_metro', file, 'May 2025')
        for name, table in [('occupation_data', 'onet_occupation'),
                            ('software_skills', 'onet_software_skills'),
                            ('essential_skills', 'onet_essential_skills')]:
            candidates = list((ROOT / 'data/raw/onet_31_0_csv').rglob(name + '.csv'))
            if len(candidates) != 1:
                raise FileNotFoundError(f'Expected exactly one {name}.csv')
            file = candidates[0]
            frame = pd.read_csv(file, dtype=str, keep_default_na=False, encoding='utf-8-sig')
            load_raw(conn, frame, table, file, 'O*NET 31.0')
        conn.exec_driver_sql((ROOT / 'sql/clean_reference.sql').read_text(encoding='utf-8'))
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_oews_clean_join ON raw.oews_metro(btrim(area),btrim(occ_code)) WHERE btrim(area_type)='4' AND btrim(o_group)='detailed'")
        conn.exec_driver_sql('ANALYZE raw.oews_metro')
    print('Reference ingestion and SQL cleaning committed; raw originals preserved.')


if __name__ == '__main__':
    main()
