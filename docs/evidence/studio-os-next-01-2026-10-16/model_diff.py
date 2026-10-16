import json, sys
a, b = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
leaf = []
def walk(x, y, p=""):
    if isinstance(x, dict) and isinstance(y, dict):
        for k in sorted(set(x) | set(y)): walk(x.get(k, "<absent>"), y.get(k, "<absent>"), p + "." + k)
    elif isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
        for i, (u, v) in enumerate(zip(x, y)): walk(u, v, f"{p}[{i}]")
    elif x != y: leaf.append((p, str(x)[:120], str(y)[:120]))
walk(a, b)
print("differing leaves:", len(leaf))
for l in leaf[:40]: print(*l, sep=" | ")
