"""Group repeated provider records only when shared source identity supports it."""
from collections import defaultdict

from posting_rules import plain


def entity_links(jobs, sources):
    """Keep conflicts separate; identical descriptions alone never cause a merge."""
    parents = {j['job_id']: j['job_id'] for j in jobs}
    by_id = {j['job_id']: j for j in jobs}
    by_source = defaultdict(set)
    for source in sources:
        if source.get('posting_id'):
            by_source[source['posting_id']].add(source['job_id'])

    def find(jid):
        while parents[jid] != jid:
            parents[jid] = parents[parents[jid]]
            jid = parents[jid]
        return jid

    def identity(jid):
        j = by_id[jid]
        return (plain(j.get('company')).casefold(), plain(j.get('title')).casefold().replace('_', ' '), j.get('role', ''))

    conflicts, shared = set(), set()
    for members in by_source.values():
        if len(members) <= 1:
            continue
        shared.update(members)
        partitions = defaultdict(list)
        for jid in sorted(members):
            partitions[identity(jid)].append(jid)
        if len(partitions)>1:
            conflicts.update(members)
        for key, group in partitions.items():
            if not all(key):
                continue  # Missing identity evidence is not enough to merge.
            for jid in group[1:]:
                left,right = find(group[0]),find(jid)
                parents[max(left,right)] = min(left,right)
    groups = defaultdict(list)
    for jid in parents:
        groups[find(jid)].append(jid)
    result = []
    for root, members in sorted(groups.items()):
        # Consistent with selected job-version ranking, ISO timestamps here are already source UTC strings.
        representative = max(members, key=lambda j:(by_id[j].get('updated_utc') or '', j))
        for jid in sorted(members):
            result.append(dict(batch_id=by_id[jid]['batch_id'], job_id=jid,
                entity_id='ad_'+root, representative_job_id=representative,
                group_size=str(len(members)), shared_source_id=str(jid in shared).lower(),
                identity_conflict=str(jid in conflicts).lower()))
    return result
