import json
from collections import Counter

d = json.load(open('data.json'))
nodes_by_id = {n['id']: n for n in d['nodes']}

print("edge kinds:", Counter(e['kind'] for e in d['edges']).most_common())

action_kinds = {'task', 'deliverable', 'action'}
result_edges = [e for e in d['edges'] if e['kind'] == 'result']
print(f"\ntotal result edges: {len(result_edges)}")

action_to_action = [
    e for e in result_edges
    if nodes_by_id.get(e['from'], {}).get('kind') in action_kinds
    and nodes_by_id.get(e['to'], {}).get('kind') in action_kinds
]
print(f"action->action result edges: {len(action_to_action)}")

sample_kinds = Counter()
for e in result_edges[:200]:
    f_kind = nodes_by_id.get(e['from'], {}).get('kind', '?')
    t_kind = nodes_by_id.get(e['to'], {}).get('kind', '?')
    sample_kinds[(f_kind, t_kind)] += 1

print("\n(from_kind, to_kind) distribution among result edges:")
for k, n in sample_kinds.most_common():
    print(f"  {k}: {n}")

# Also peek at what the node kinds in this graph actually are,
# so we can confirm whether 'task'/'deliverable'/'action' even appear.
print("\nall node kinds in graph:",
      Counter(n.get('kind', '?') for n in d['nodes']).most_common())
