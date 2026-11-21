"""MongoDB aggregation stages for the preserved Headcount JSON.

Only $merge targets are processed collections. raw_pages is never updated by cleaning.
"""
from pathlib import Path

from posting_rules import US_STATES
from pipeline_common import sha256


def version():
    return 'mc_' + sha256(Path(__file__))[:20]


def convert(value, target):
    return {'$convert': {'input': value, 'to': target, 'onError': None, 'onNull': None}}


def whitespace(value):
    return {'$reduce': {
        'input': {'$regexFindAll': {'input': {'$ifNull': [value, '']}, 'regex': r'\S+'}},
        'initialValue': '', 'in': {'$concat': ['$$value',
            {'$cond': [{'$eq': ['$$value', '']}, '', ' ']}, '$$this.match']}}}


def usable(field):
    return {'$in': [field+'.state', ['known', 'derived']]}


def occurrence_stages(snapshot):
    return [
        {'$match': {'source_snapshot': snapshot}},
        {'$unwind': {'path': '$payload.response.data', 'includeArrayIndex': 'record_index'}},
        {'$project': {
            '_id': 0, 'raw_page_id': '$_id', 'source_snapshot': 1, 'source_file': 1,
            'source_sha256': 1, 'record_index': 1,
            'retrieved_at': '$payload.retrieved_at_utc',
            'query_state': '$payload.state_filter', 'query_title': '$payload.title_filter',
            'job': '$payload.response.data'}}]


def selection_stages(snapshot):
    # Sort only pointers/IDs/dates; the small Atlas tier limits sorts to 32 MB.
    return occurrence_stages(snapshot) + [
        {'$match': {'job.job_id': {'$type': 'string', '$ne': ''}}},
        {'$project': {
            'raw_page_id': 1, 'source_snapshot': 1, 'source_file': 1, 'source_sha256': 1,
            'record_index': 1, 'query_state': 1, 'query_title': 1,
            'retrieved_utc': convert('$retrieved_at', 'date'),
            'job_id': '$job.job_id',
            'updated_utc': convert({'$ifNull': ['$job.job_updated_at', '$retrieved_at']}, 'date'),
            'curated_utc': convert({'$ifNull': ['$job.curated_at', '$retrieved_at']}, 'date'),
            'first_seen_utc': convert('$job.job_first_seen_at', 'date')}},
        {'$sort': {'job_id': 1, 'updated_utc': -1, 'curated_utc': -1,
                   'source_file': -1, 'record_index': -1}},
        {'$group': {'_id': '$job_id', 'selected': {'$first': '$$ROOT'},
                    'occurrence_count': {'$sum': 1},
                    'matched_queries': {'$addToSet': {'state': '$query_state', 'title': '$query_title'}}}},
        {'$replaceWith': {'$mergeObjects': ['$selected',
             {'occurrence_count': '$occurrence_count', 'matched_queries': '$matched_queries'}]}}]


def job_stages(snapshot, cleaning_version=None):
    cleaning_version = cleaning_version or version()
    stages = selection_stages(snapshot)
    stages += [
        {'$lookup': {'from': 'raw_pages', 'let': {'page': '$raw_page_id', 'idx': '$record_index'},
            'pipeline': [{'$match': {'$expr': {'$eq': ['$_id', '$$page']}}},
                {'$project': {'_id': 0, 'job': {'$arrayElemAt': ['$payload.response.data', '$$idx']}}},
                {'$project': {'_id': 0, 'title_field': '$job.title', 'company_field': '$job.employer_name',
                    'description_field': '$job.description', 'work_arrangement_field': '$job.work_arrangement',
                    'currentness': '$job.currentness', 'stale': '$job.stale', 'locations_raw': '$job.locations',
                    'source_posting_count': {'$size': {'$ifNull': ['$job.postings', []]}}}}], 'as': 'selected_fields'}},
        {'$replaceWith': {'$mergeObjects': ['$$ROOT', {'$arrayElemAt': ['$selected_fields', 0]}]}},
        {'$unset': 'selected_fields'}]
    fields = {'title': 'title_field', 'company': 'company_field',
              'description': 'description_field', 'work_arrangement': 'work_arrangement_field'}
    normalized = {}
    for target, source in fields.items():
        normalized[target] = {'$cond': [usable('$'+source), whitespace('$'+source+'.value'), None]}
        normalized[target+'_state'] = {'$ifNull': ['$'+source+'.state', 'missing_field']}
    stages += [{'$set': normalized}, {'$set': {
        '_id': {'$concat': [cleaning_version+'|'+snapshot+'|', '$job_id']},
        'clean_version': cleaning_version,
        'description_available': {'$and': [usable('$description_field'), {'$ne': ['$description', '']}]},
        'locations': {'$map': {'input': {'$ifNull': ['$locations_raw', []]}, 'as': 'loc',
            'in': {'source_state': '$$loc.state', 'city': '$$loc.value.city',
                'region': '$$loc.value.region', 'country': '$$loc.value.country',
                'state_us': {'$cond': [{'$and': [
                    {'$eq': ['$$loc.value.country', 'US']},
                    {'$eq': [{'$substrCP': [{'$ifNull': ['$$loc.value.region', '']}, 0, 3]}, 'US-']},
                    {'$in': [{'$substrCP': [{'$ifNull': ['$$loc.value.region', '']}, 3, 2]}, sorted(US_STATES)]}]},
                    {'$substrCP': ['$$loc.value.region', 3, 2]}, None]},
                'source_cbsa': '$$loc.value.msa.cbsa_code', 'cbsa_type': '$$loc.value.msa.type'}}}}},
        {'$unset': ['title_field', 'company_field', 'description_field', 'work_arrangement_field', 'locations_raw']}]
    return stages


def fallback_money():
    # Match the relational loader's fallback when pay.value exists but money[] is absent.
    return {'$map': {'input': {'$cond': [
        {'$gt': [{'$size': {'$ifNull': ['$posting.pay.value.ranges', []]}}, 0]},
        '$posting.pay.value.ranges', ['$posting.pay.value']]}, 'as': 'r', 'in': {
            'kind': 'range', 'currency': '$$r.currency', 'period': '$$r.interval',
            'min_cents': {'$multiply': [convert('$$r.min', 'decimal'), 100]},
            'max_cents': {'$multiply': [convert('$$r.max', 'decimal'), 100]},
            'source_path': 'pay.value', 'amount_status': {
                'min': {'$cond': [{'$ne': [{'$ifNull': ['$$r.min', None]}, None]}, 'ok', 'missing']},
                'max': {'$cond': [{'$ne': [{'$ifNull': ['$$r.max', None]}, None]}, 'ok', 'missing']}}}}}


def pay_stages(snapshot, cleaning_version=None):
    cleaning_version = cleaning_version or version()
    return [
        {'$match': {'source_snapshot': snapshot, 'clean_version': cleaning_version}},
        {'$project': {'_id': 0, 'job_id': 1, 'source_snapshot': 1, 'clean_version': 1,
                       'raw_page_id': 1, 'record_index': 1, 'source_file': 1}},
        {'$lookup': {'from': 'raw_pages', 'let': {'page': '$raw_page_id', 'idx': '$record_index'},
            'pipeline': [{'$match': {'$expr': {'$eq': ['$_id', '$$page']}}},
                {'$project': {'_id': 0, 'job': {'$arrayElemAt': ['$payload.response.data', '$$idx']}}}],
            'as': 'original'}},
        {'$set': {'postings': {'$ifNull': [{'$arrayElemAt': ['$original.job.postings', 0]}, []]}}},
        {'$unset': 'original'},
        {'$unwind': {'path': '$postings', 'includeArrayIndex': 'posting_index'}},
        {'$set': {'posting': '$postings'}}, {'$unset': 'postings'},
        {'$set': {'money': {'$cond': [
            {'$gt': [{'$size': {'$ifNull': ['$posting.money', []]}}, 0]}, '$posting.money',
            {'$cond': [{'$and': [usable('$posting.pay'),
                {'$ne': [{'$ifNull': ['$posting.pay.value', None]}, None]},
                {'$ne': ['$posting.pay.value', {}]}]}, fallback_money(), []]}]}}},
        {'$unwind': {'path': '$money', 'includeArrayIndex': 'money_index'}},
        {'$project': {
            '_id': {'$concat': [cleaning_version+'|'+snapshot+'|', '$job_id', '|',
                {'$toString': '$posting_index'}, '|', {'$toString': '$money_index'}]},
            'job_id': 1, 'source_snapshot': 1, 'clean_version': 1, 'raw_page_id': 1,
            'record_index': 1, 'source_file': 1, 'posting_index': 1, 'money_index': 1,
            'posting_id': '$posting.posting_id', 'posting_status': '$posting.posting_status',
            'pay_state': '$posting.pay.state', 'currency': '$money.currency', 'period': '$money.period',
            'source_path': '$money.source_path', 'min_status': '$money.amount_status.min',
            'max_status': '$money.amount_status.max',
            'salary_min': {'$divide': [convert('$money.min_cents', 'decimal'), 100]},
            'salary_max': {'$divide': [convert('$money.max_cents', 'decimal'), 100]},
            'salary_amount': {'$divide': [convert('$money.amount_cents', 'decimal'), 100]}}},
        {'$set': {'valid_range': {'$and': [
            {'$ne': ['$salary_min', None]}, {'$ne': ['$salary_max', None]},
            {'$gt': ['$salary_min', 0]}, {'$gte': ['$salary_max', '$salary_min']},
            {'$eq': ['$min_status', 'ok']}, {'$eq': ['$max_status', 'ok']}]}}},
        {'$set': {'salary_eligible': {'$and': ['$valid_range', {'$eq': ['$currency', 'USD']},
            {'$eq': ['$period', 'year']}, {'$eq': ['$pay_state', 'known']},
            {'$gte': ['$salary_min', 15000]}, {'$lte': ['$salary_max', 1000000]}]},
            'salary_midpoint': {'$cond': ['$valid_range',
                {'$divide': [{'$add': ['$salary_min', '$salary_max']}, 2]}, None]}}}]


def merge_stage(collection):
    return {'$merge': {'into': collection, 'on': '_id', 'whenMatched': 'keepExisting', 'whenNotMatched': 'insert'}}
