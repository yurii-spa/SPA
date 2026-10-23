"""Проекция «снимок → витрина → страницы», проверяемая машинно (ADR-373 / ADR-357 п. 5 / ADR-580).

Три звена и три вопроса:

1. **снимок → витрина.** Откуда у числа витрины его значение? Ответ берётся не из текста
   ``source``, а из ПОВЕДЕНИЯ сборщика: каждый лист снимка по очереди подменяется уникальным
   значением, витрина пересобирается настоящим ``scripts/build_site_numbers.py::build`` — и
   там, где подмена всплыла, и есть путь, из которого число взято (``projection_map``). После
   этого ``source`` обязан с этим путём СОГЛАСОВАТЬСЯ, а значение опубликованной витрины —
   совпасть со значением снимка, по которому её собрали (``check_shelf_provenance``).
2. **витрина/переходник → страницы.** Что страница реально читает? Статический разбор
   страниц (``_site_js_reads``) и настоящий прогон модулей сайта в node под записывающими
   прокси (``run_harness``) дают перечень чтений; каждое обязано попасть в существующий путь
   выхода того модуля, который читается (``check_reads``).
3. **классификация.** Каждый путь снимка либо доходит до страницы (переходник; витрина + её
   читатель), либо объявлен С ДОКАЗАТЕЛЬСТВОМ: подмена его значения не меняет НИЧЕГО
   опубликованного, или меняет только витрину, которую никто не читает
   (``classify_snapshot_paths``). Непонятный путь — ошибка, общего освобождения нет.

Третий исход (инв. #17): нет ``node``, сборщик не загрузился, снимок, из которого собрана
опубликованная витрина, не найден — ``NotMeasured`` с названной причиной, а не зелёный.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from spa_core.tests import _site_js_reads as jr

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "landing" / "src"
SNAPSHOT = SRC / "data" / "track_snapshot.json"
SHELF = SRC / "data" / "site_numbers.json"
CONSTITUTION = SRC / "lib" / "constitution.json"
VIEW_MODULE = SRC / "lib" / "snapshot_view.js"
TARGET_MODULES = ("lib/snapshot_view.js", "lib/site_numbers.js", "lib/realized_rate.js", "lib/book_exposure.js")
VIEW_CTX = "import:" + str(VIEW_MODULE.resolve())


class NotMeasured(RuntimeError):
    """Замер не состоялся; причина названа."""


# ── shapes ────────────────────────────────────────────────────────────────────────────────────────

def shape(doc, prefix=()) -> dict:
    """{path tuple: "dict"|"list"|"scalar"}; list elements are ``*``."""
    out = {prefix: _kind(doc)}
    if isinstance(doc, dict):
        for k, v in doc.items():
            out.update(shape(v, prefix + (str(k),)))
    elif isinstance(doc, list):
        for v in doc:
            for p, kd in shape(v, prefix + ("*",)).items():
                if out.get(p) in (None, "scalar"):
                    out[p] = kd
    return out


def _kind(v):
    return "dict" if isinstance(v, dict) else "list" if isinstance(v, list) else "scalar"


def union(*shapes) -> dict:
    out = {}
    for s in shapes:
        for p, k in s.items():
            if out.get(p) in (None, "scalar"):
                out[p] = k
    return out


def resolves(path, shp) -> "tuple | None":
    """A concrete path in ``shp`` matching ``path`` (``*`` on either side matches any key)."""
    path = tuple(str(x) for x in path)
    if path in shp:
        return path
    n = len(path)
    for p in shp:
        if len(p) == n and all(a == b or a == "*" or b == "*" for a, b in zip(path, p)):
            return p
    return None


def get_at(doc, path):
    cur = doc
    for k in path:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        elif isinstance(cur, list) and str(k).isdigit() and int(k) < len(cur):
            cur = cur[int(k)]
        else:
            raise KeyError(path)
    return cur


def instances(doc, path):
    """All concrete paths (and values) of a wildcard path in ``doc``."""
    out = [((), doc)]
    for k in path:
        nxt = []
        for p, v in out:
            if k == "*":
                if isinstance(v, dict):
                    nxt += [(p + (kk,), vv) for kk, vv in v.items()]
                elif isinstance(v, list):
                    nxt += [(p + (str(i),), vv) for i, vv in enumerate(v)]
            elif isinstance(v, dict) and k in v:
                nxt.append((p + (k,), v[k]))
            elif isinstance(v, list) and str(k).isdigit() and int(k) < len(v):
                nxt.append((p + (k,), v[int(k)]))
        out = nxt
    return out


def leaf_paths(doc, prefix=()) -> list:
    """Concrete paths of every scalar / empty container (list indices concrete)."""
    if isinstance(doc, dict) and doc:
        return [p for k, v in doc.items() for p in leaf_paths(v, prefix + (k,))]
    if isinstance(doc, list) and doc:
        return [p for i, v in enumerate(doc) for p in leaf_paths(v, prefix + (str(i),))]
    return [prefix]


def set_at(doc, path, value):
    cur = doc
    for k in path[:-1]:
        cur = cur[int(k)] if isinstance(cur, list) else cur[k]
    last = path[-1]
    if isinstance(cur, list):
        cur[int(last)] = value
    else:
        cur[last] = value


def snapshot_paths(obj, prefix: str = "") -> set:
    """The same path notion as ``test_site_snapshot_view_shape.paths`` (dicts only, lists are leaves)."""
    out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(f"{prefix}/{k}")
            if isinstance(v, dict):
                out |= snapshot_paths(v, f"{prefix}/{k}")
    return out


# ── the builder, loaded privately ─────────────────────────────────────────────────────────────────

def load_builder():
    spec = importlib.util.spec_from_file_location("_bsn_projection", ROOT / "scripts" / "build_site_numbers.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:  # noqa: BLE001
        raise NotMeasured(f"сборщик витрины не загрузился ({exc!r})") from exc
    return mod


def build_from(bsn, snap: dict, const: dict, published_at: str) -> dict:
    """The REAL ``build()`` over in-memory inputs (the module's own copy; the repository is untouched)."""
    real_load, real_sha = bsn._load, bsn._sha256

    def _load(path):
        if Path(path) == bsn.SNAPSHOT:
            return copy.deepcopy(snap)
        if Path(path) == bsn.CONSTITUTION:
            return copy.deepcopy(const)
        return real_load(path)

    def _sha(path):
        doc = snap if Path(path) == bsn.SNAPSHOT else const
        return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()

    bsn._load, bsn._sha256 = _load, _sha
    try:
        return bsn.build(published_at=published_at)
    finally:
        bsn._load, bsn._sha256 = real_load, real_sha


def _diff(a, b, prefix=()) -> list:
    if type(a) is not type(b):
        return [prefix]
    if isinstance(a, dict):
        out = []
        for k in set(a) | set(b):
            if k not in a or k not in b:
                out.append(prefix + (k,))
            else:
                out += _diff(a[k], b[k], prefix + (k,))
        return out
    if isinstance(a, list):
        if len(a) != len(b):
            return [prefix]
        return [p for i, (x, y) in enumerate(zip(a, b)) for p in _diff(x, y, prefix + (str(i),))]
    return [] if a == b else [prefix]


_IGNORED = (("_provenance", "source_hashes"),)


def _sentinel(base, k: int):
    """A unique stand-in of the SAME type, so the builder takes the same branch it takes for real."""
    if isinstance(base, bool):
        return not base
    if isinstance(base, int):
        return 900_000 + k
    if isinstance(base, float):
        return 900_000 + k + 0.25
    if isinstance(base, str):
        if len(base) >= 10 and base[4:5] == "-" and base[7:8] == "-" and base[:4].isdigit():
            d = (date(2031, 1, 1) + timedelta(days=k)).isoformat()
            return d + base[10:] if len(base) > 10 else d
        return f"SENTINEL-{k}"
    if isinstance(base, list):
        return [f"SENTINEL-{k}"]
    if isinstance(base, dict):
        return {"sentinel": f"SENTINEL-{k}"}
    return f"SENTINEL-{k}"            # None: an observation appears where there was none


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _same(shelf_val, snap_val) -> bool:
    if shelf_val == snap_val and type(shelf_val) is type(snap_val):
        return True
    a, b = _num(shelf_val), _num(snap_val)
    return a is not None and b is not None and a == b and not isinstance(shelf_val, str)


@dataclass
class Projection:
    """Where a snapshot (or constitution) leaf goes in the shelf, measured by perturbation."""
    origin: str                     # "snapshot" | "constitution"
    leaf: tuple
    identity: list = field(default_factory=list)   # shelf paths that now carry the sentinel
    mirror: list = field(default_factory=list)     # shelf paths equal to the leaf in base and changed
    touched: list = field(default_factory=list)    # every shelf path that changed


def unlocked(snap: dict) -> dict:
    """The same snapshot with every maturity verdict opened — so a gated rate shows its origin."""
    s = copy.deepcopy(snap)
    for b in (s.get("paper_tracks") or {}).values():
        if isinstance(b, dict) and b.get("reportable") is False:
            b["reportable"] = True
    return s


def projection_map(bsn, snap: dict, const: dict, published_at: str, skip=(("bars",),)) -> dict:
    """{(origin, leaf): Projection} — every leaf perturbed ALONE and the real builder rerun.

    Two scenes: the snapshot as it is, and the same snapshot with maturity verdicts opened (a rate
    published as null below 30 days shows its origin only there). ``bars`` is the daily chart series —
    the view passes it through whole, the shelf never carries it (snapshot_view.js header)."""
    out = {}
    k = 0
    for unlock in (False, True):
        s0 = unlocked(snap) if unlock else snap
        base = build_from(bsn, s0, const, published_at)
        for origin, src in (("snapshot", s0), ("constitution", const)):
            if origin == "constitution" and unlock:
                continue
            for leaf in leaf_paths(src):
                if any(leaf[:len(sk)] == sk for sk in skip):
                    continue
                cur = get_at(src, leaf)
                pr = out.setdefault((origin, leaf), Projection(origin, leaf))
                # an unobserved value (null) is a number or a text once observed — try both forms
                for sent in ((900_000 + k + 0.25, f"SENTINEL-{k}") if cur is None else (_sentinel(cur, k),)):
                    k += 1
                    _perturb(bsn, origin, src, s0, const, published_at, leaf, cur, sent, base, pr)
    return out


def _perturb(bsn, origin, src, s0, const, published_at, leaf, cur, sent, base, pr):
                pert = copy.deepcopy(src)
                set_at(pert, leaf, sent)
                try:
                    shelf = (build_from(bsn, pert, const, published_at) if origin == "snapshot"
                             else build_from(bsn, s0, pert, published_at))
                except Exception as exc:  # noqa: BLE001 — a sentinel the builder refuses IS a dependency
                    pr.touched.append(("<build refused>", repr(exc)[:120]))
                    return
                for pth in _diff(base, shelf):
                    if any(pth[:len(i)] == i for i in _IGNORED):
                        continue
                    if pth not in pr.touched:
                        pr.touched.append(pth)
                    try:
                        new, old = get_at(shelf, pth), get_at(base, pth)
                    except KeyError:
                        continue
                    if _same(new, sent):
                        if pth not in pr.identity:
                            pr.identity.append(pth)
                    elif _same(old, cur) and pth not in pr.mirror:
                        pr.mirror.append(pth)


def figures(shelf: dict, prefix=()) -> list:
    """Every published number: a dict with value/unit/kind/source."""
    out = []
    if isinstance(shelf, dict):
        if {"value", "unit", "kind", "source"} <= set(shelf):
            return [prefix]
        for k, v in shelf.items():
            out += figures(v, prefix + (k,))
    elif isinstance(shelf, list):
        for i, v in enumerate(shelf):
            out += figures(v, prefix + (str(i),))
    return out


def figure_origins(pmap: dict) -> dict:
    """{shelf figure path: [(origin, leaf)]} — the leaves whose sentinel lands in ``<figure>/value``."""
    inv = {}
    for (origin, leaf), pr in pmap.items():
        for p in pr.identity:
            if p and p[-1] == "value":
                inv.setdefault(p[:-1], [])
                if (origin, leaf) not in inv[p[:-1]]:
                    inv[p[:-1]].append((origin, leaf))
    return inv


# ── the inputs a published shelf was built from ──────────────────────────────────────────────────

def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def input_by_hash(rel: str, sha: str, current: Path) -> "tuple[dict, str]":
    """The exact input bytes a shelf declares (``_provenance.source_hashes``): the current file, the
    content-addressed store (ADR-630), or the file's git history. Not found ⇒ NotMeasured."""
    if current.is_file() and _sha256_bytes(current.read_bytes()) == sha:
        return json.loads(current.read_text(encoding="utf-8")), f"{rel} (рабочее дерево)"
    store = ROOT / "data" / "publication_inputs" / f"{sha}.json"
    if store.is_file() and _sha256_bytes(store.read_bytes()) == sha:
        return json.loads(store.read_text(encoding="utf-8")), f"data/publication_inputs/{sha}.json"
    git = shutil.which("git")
    if git:
        try:
            revs = subprocess.run([git, "-C", str(ROOT), "log", "--format=%H", "-n", "400", "--", rel],
                                  capture_output=True, text=True, timeout=60).stdout.split()
        except Exception:  # noqa: BLE001
            revs = []
        for r in revs:
            try:
                blob = subprocess.run([git, "-C", str(ROOT), "show", f"{r}:{rel}"],
                                      capture_output=True, timeout=60).stdout
            except Exception:  # noqa: BLE001
                continue
            if _sha256_bytes(blob) == sha:
                return json.loads(blob.decode("utf-8")), f"{rel} @ {r[:10]}"
    raise NotMeasured(f"вход витрины {rel} с sha256 {sha[:12]}… не найден ни в дереве, ни в хранилище "
                      f"входов, ни в истории git — сверять опубликованную витрину не с чем")


# ── provenance of the published shelf ────────────────────────────────────────────────────────────

def _source_key(source: str) -> "str | None":
    """The key a ``source`` names after «→» (first identifier), or None when it names only the file."""
    if "→" not in source:
        return None
    rest = source.split("→", 1)[1].strip()
    key = ""
    for ch in rest:
        if ch.isalnum() or ch == "_":
            key += ch
        else:
            break
    return key or None


def _equality_claims(source: str) -> list:
    """``(= a.b.c, …)`` inside a source: the figure claims to equal the snapshot value at a/b/c."""
    out = []
    if "(=" in source:
        tail = source.split("(=", 1)[1]
        ref = ""
        for ch in tail.strip():
            if ch.isalnum() or ch in "_.":
                ref += ch
            else:
                break
        if ref:
            out.append(tuple(ref.split(".")))
    return out


def _decimals(v: float) -> int:
    s = repr(float(v))
    return len(s.split(".")[1]) if "." in s and "e" not in s else 6


def check_shelf_provenance(shelf: dict, snap: dict, const: dict, origins: dict, rebuilt: dict) -> list:
    """Every published figure: origin measured · source agrees · value equals the input at the origin.
    ``snap``/``const`` are the inputs THIS shelf was built from (matched by hash); ``rebuilt`` is the
    real builder over those inputs."""
    problems = []
    for fp in figures(shelf):
        fig = get_at(shelf, fp)
        where = "/".join(fp)
        src = str(fig.get("source") or "")
        org = origins.get(fp)
        if not org:
            problems.append(f"{where}: у числа нет измеренного происхождения — подмена ни одного листа "
                            f"снимка/конституции не всплывает в {where}/value")
            continue
        if len(org) > 1:
            problems.append(f"{where}: происхождение неоднозначно — {org}")
            continue
        origin, leaf = org[0]
        leaf_s = "/".join(leaf)
        names_snapshot = "track_snapshot.json" in src
        names_const = "constitution.json" in src
        if origin == "snapshot" and not (names_snapshot and not names_const):
            problems.append(f"{where}: source {src!r} не называет снимок, а число взято из снимка ({leaf_s})")
        if origin == "constitution" and not (names_const and not names_snapshot):
            problems.append(f"{where}: source {src!r} не называет конституцию, а число взято из неё ({leaf_s})")
        key = _source_key(src)
        if key is not None and key != leaf[0]:
            problems.append(f"{where}: source называет «{key}», а число взято из «{leaf_s}» — путь не тот")
        base = snap if origin == "snapshot" else const
        try:
            raw = get_at(base, leaf)
        except KeyError:
            problems.append(f"{where}: пути {leaf_s} нет во входе, из которого собрана витрина")
            continue
        expect = _num(raw)
        if fig.get("reportable") is False:
            expect = None              # ADR-580 C2: an immature rate is published as null
        got = fig.get("value")
        if not ((got is None and expect is None) or (got is not None and expect is not None and float(got) == expect)):
            problems.append(f"{where}: значение витрины {got!r} ≠ значению снимка {raw!r} по пути {leaf_s} "
                            f"(с учётом объявленного преобразования: число, null при reportable=false)")
        for claim in _equality_claims(src):
            try:
                cv = _num(get_at(snap, claim))
            except KeyError:
                problems.append(f"{where}: source утверждает равенство с {'.'.join(claim)}, а такого пути нет")
                continue
            if got is not None and cv is not None and round(cv, _decimals(got)) != float(got):
                problems.append(f"{where}: source утверждает «= {'.'.join(claim)}», но {got} ≠ {cv}")
        kind = fig.get("kind")
        if origin == "constitution" and kind != "решение":
            problems.append(f"{where}: число из конституции несёт род {kind!r}, а не «решение»")
        if origin == "snapshot" and leaf[0] == "packages" and kind != "backtest":
            problems.append(f"{where}: пакеты снимка — бэктест (ADR-580 C2), а род {kind!r}")
        if origin == "snapshot" and leaf[0] != "packages" and kind == "backtest":
            problems.append(f"{where}: число живого трека ({leaf_s}) помечено «backtest»")
    for p in _diff(rebuilt, shelf):
        if not any(p[:len(i)] == i for i in _IGNORED):
            problems.append(f"/{'/'.join(p)}: опубликованная витрина расходится со сборкой из её же входов")
    return problems


# ── node harness: the site's modules executed under recording proxies ──────────────────────────────

_HOOKS = r"""
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
let OV = {}, ROOTS = {};
export async function initialize(data) { OV = data.overrides || {}; ROOTS = data.roots || {}; }
export async function load(url, context, nextLoad) {
  if (url.startsWith('file://')) {
    const p = fileURLToPath(url);
    if (ROOTS[p]) return { format: 'module', shortCircuit: true,
      source: `export default globalThis.__SPA_ROOT__(${JSON.stringify(ROOTS[p])});` };
    if (Object.prototype.hasOwnProperty.call(OV, p)) return { format: 'module', shortCircuit: true, source: OV[p] };
    if (p.endsWith('.json')) return { format: 'module', shortCircuit: true,
      source: 'export default ' + readFileSync(p, 'utf8') + ';' };
  }
  return nextLoad(url, context);
}
"""

_HARNESS = r"""
import { register } from 'node:module';
import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const cfg = JSON.parse(readFileSync(process.argv[2], 'utf8'));
register(pathToFileURL(cfg.hooks).href, { data: { overrides: cfg.overrides, roots: cfg.roots } });
const DATA = { SHELF: cfg.shelf, SNAP: cfg.snap };
const READS = new Map();
let CTX = 'init';
const META = new WeakMap(), TARGET = new WeakMap(), CACHE = new WeakMap();
const own = (t, k) => Object.prototype.hasOwnProperty.call(t, k);
const norm = (t, k) => (Array.isArray(t) && /^\d+$/.test(k)) ? '*' : k;
function rec(root, path, present) {
  const key = JSON.stringify([CTX, root, path]);
  READS.set(key, READS.get(key) === true ? true : present);
}
function wrap(root, t, path) {
  if (t === null || typeof t !== 'object') return t;
  const key = root + '\u0000' + JSON.stringify(path);
  let m = CACHE.get(t); if (!m) { m = new Map(); CACHE.set(t, m); }
  if (m.has(key)) return m.get(key);
  const p = new Proxy(t, {
    get(tt, k, r) {
      if (typeof k === 'symbol') return Reflect.get(tt, k, r);
      if (Array.isArray(tt) && k === 'length') return tt.length;
      if (!own(tt, k) && (k in tt)) return Reflect.get(tt, k, r);
      const np = path.concat([norm(tt, k)]);
      rec(root, np, own(tt, k));
      return own(tt, k) ? wrap(root, tt[k], np) : undefined;
    },
    has(tt, k) {
      if (typeof k !== 'symbol') rec(root, path.concat([norm(tt, k)]), own(tt, k));
      return Reflect.has(tt, k);
    },
  });
  m.set(key, p); META.set(p, { root, path }); TARGET.set(p, t);
  return p;
}
function plain(v, depth = 0) {
  if (v === null || typeof v !== 'object' || depth > 40) return v;
  const t = TARGET.get(v) || v;
  if (Array.isArray(t)) return t.map((x) => plain(x, depth + 1));
  const o = {};
  for (const k of Object.keys(t)) o[k] = plain(t[k], depth + 1);
  return o;
}
function describe(v, path = [], out = { paths: [], refs: [] }, depth = 0) {
  if (v === null || typeof v !== 'object' || depth > 12) return out;
  if (META.has(v)) { out.refs.push({ at: path, ...META.get(v) }); return out; }
  if (Array.isArray(v)) { out.paths.push(path.concat(['*'])); v.forEach((x) => describe(x, path.concat(['*']), out, depth + 1)); return out; }
  for (const k of Object.keys(v)) { out.paths.push(path.concat([k])); describe(v[k], path.concat([k]), out, depth + 1); }
  return out;
}
globalThis.__SPA_ROOT__ = (root) => wrap(root, DATA[root], []);
const out = { reads: [], specs: {}, errors: [], view: null };
const mods = {};
async function load(m) {
  if (mods[m] !== undefined) return mods[m];
  const prev = CTX; CTX = 'import:' + m;
  try { mods[m] = await import(pathToFileURL(m).href); }
  catch (e) { mods[m] = null; out.errors.push({ where: 'import ' + m, error: String(e && e.stack || e).slice(0, 400) }); }
  CTX = prev;
  return mods[m];
}
const vm = await load(cfg.view_module);
out.view = vm ? plain(vm.default) : null;
DATA.VIEW = out.view;
for (const m of cfg.modules) await load(m);
const DOMAIN = ['conservative', 'balanced', 'aggressive', true, false, undefined];
const RAW = {};
function concrete(root, path) {
  let cur = [[[], DATA[root]]];
  for (const k of path) {
    const nxt = [];
    for (const [p, v] of cur) {
      if (v === null || typeof v !== 'object') continue;
      if (k === '*') for (const kk of Object.keys(v)) nxt.push([p.concat([Array.isArray(v) ? '*' : kk]), v[kk]]);
      else if (own(v, k)) nxt.push([p.concat([k]), v[k]]);
    }
    cur = nxt;
  }
  return cur.map(([p, v]) => wrap(root, v, p));
}
for (const s of cfg.specs) {
  const mod = await load(s.module);
  const res = { ok: 0, results: [], errors: [], explored: false, module: s.module, name: s.name };
  out.specs[s.id] = res;
  if (!mod) { res.errors.push('module did not import'); continue; }
  const fn = s.name === 'default' ? mod.default : mod[s.name];
  if (s.args === null) {
    CTX = 'call:' + s.id; res.ok = 1; res.results.push(describe(fn)); RAW[s.id] = [fn]; continue;
  }
  if (typeof fn !== 'function') { res.errors.push('export is not a function: ' + s.name); continue; }
  let specs = s.args === 'auto' ? Array.from({ length: fn.length }, () => ['unknown']) : s.args;
  let variants = [[]];
  for (const a of specs) {
    let vals;
    if (a[0] === 'lit') vals = [a[1] === '__undefined__' ? undefined : a[1]];
    else if (a[0] === 'ref') vals = (cfg.roots_ok[a[1]] ? concrete(a[1], a[2]) : []);
    else if (a[0] === 'spec') vals = (RAW[a[1]] || []).slice(0, 4);
    else if (a[0] === 'now') vals = [Date.now()];
    else if (a[0] === 'fn') { const mm = await load(a[1]); vals = mm ? [mm[a[2]]] : [undefined]; }
    else { vals = DOMAIN; res.explored = true; }
    if (vals.length === 0) vals = [undefined];
    const nv = [];
    for (const v of variants) for (const x of vals) if (nv.length < 60) nv.push(v.concat([x]));
    variants = nv;
  }
  RAW[s.id] = [];
  for (const args of variants) {
    CTX = (res.explored ? 'explore:' : 'call:') + s.id;
    try { const r = fn(...args); RAW[s.id].push(r); res.results.push(describe(r)); res.ok += 1; }
    catch (e) { res.errors.push(String(e && e.message || e).slice(0, 200)); }
  }
}
for (const [k, present] of READS) { const [ctx, root, path] = JSON.parse(k); out.reads.push({ ctx, root, path, present }); }
writeFileSync(cfg.out, JSON.stringify(out));
"""


def run_harness(shelf: dict, snap: dict, specs: list, modules: list, overrides: "dict | None" = None) -> dict:
    node = shutil.which("node")
    if node is None:
        raise NotMeasured("`node` не найден — модули сайта нечем исполнить")
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "hooks.mjs").write_text(_HOOKS, encoding="utf-8")
        (t / "harness.mjs").write_text(_HARNESS, encoding="utf-8")
        cfg = {
            "hooks": str(t / "hooks.mjs"),
            "out": str(t / "out.json"),
            "view_module": str(VIEW_MODULE.resolve()),
            "modules": modules,
            "shelf": shelf,
            "snap": snap,
            "roots": {str(SHELF.resolve()): "SHELF", str(SNAPSHOT.resolve()): "SNAP"},
            "roots_ok": {"SHELF": True, "SNAP": True, "VIEW": True},
            "overrides": overrides or {},
            "specs": [{"id": s.id, "module": s.module, "name": s.name, "args": s.args} for s in specs],
        }
        (t / "cfg.json").write_text(json.dumps(cfg), encoding="utf-8")
        try:
            r = subprocess.run([node, str(t / "harness.mjs"), str(t / "cfg.json")],
                               capture_output=True, text=True, timeout=180)
        except Exception as exc:  # noqa: BLE001
            raise NotMeasured(f"node не запустился ({exc})") from exc
        if r.returncode != 0 or not (t / "out.json").is_file():
            raise NotMeasured(f"модули сайта не исполнились: {r.stderr.strip()[-400:]}")
        out = json.loads((t / "out.json").read_text(encoding="utf-8"))
    if out.get("view") is None:
        raise NotMeasured(f"переходник не загрузился: {out.get('errors')}")
    return out


# ── scenes ────────────────────────────────────────────────────────────────────────────────────────

def degraded_snapshot(snap: dict) -> dict:
    """The other branch of every «measured?» question: period and exposure unmeasured, figures null."""
    s = copy.deepcopy(snap)
    s["track_period"] = {"state": "UNMEASURED", "reason": "scene: period not measured"}
    s["book_exposure"] = {"state": "UNMEASURED", "reason": "scene: exposure not measured"}
    for k in ("paper_apy_pct", "max_drawdown_pct", "nav_usd", "end_equity", "anchor_equity",
              "track_return_pct", "total_return_pct", "gates_passed", "gates_total"):
        if k in s:
            s[k] = None
    for b in (s.get("paper_tracks") or {}).values():
        if isinstance(b, dict):
            for k in ("apy_pct", "dd_pct", "nav_usd", "days_with_positions", "positions_count",
                      "observed_accrual_since"):
                if k in b:
                    b[k] = None
    for p in (s.get("packages") or {}).values():
        if isinstance(p, dict):
            for k in list(p):
                if isinstance(p[k], (int, float)) and not isinstance(p[k], bool):
                    p[k] = None
    return s


@dataclass
class Scene:
    name: str
    shelf: dict
    snap: dict
    out: dict


def scenes(specs, modules, shelf: dict, snap: dict, const: dict, bsn, overrides=None,
           shelf_mutator=None) -> list:
    """The published shelf + today's snapshot, and the degraded branch built by the REAL builder."""
    deg_snap = degraded_snapshot(snap)
    deg_shelf = build_from(bsn, deg_snap, const, shelf.get("published_at") or "2026-01-01")
    pairs = [("published", shelf, snap), ("degraded", deg_shelf, deg_snap)]
    out = []
    for name, sh, sn in pairs:
        sh = copy.deepcopy(sh)
        if shelf_mutator:
            shelf_mutator(sh)
        out.append(Scene(name, sh, sn, run_harness(sh, sn, specs, modules, overrides)))
    return out


# ── reads ─────────────────────────────────────────────────────────────────────────────────────────

def _is_target(module: str) -> bool:
    return any(str(module).endswith(t) for t in TARGET_MODULES)


@dataclass
class ReadCheck:
    problems: list
    unanalyzed: list
    shapes: dict
    shelf_reads: set          # shelf paths read by any consumer other than the view's own construction
    snap_reads: set           # snapshot paths read directly (not via the shelf)
    view_reads: set


def check_reads(an: "jr.Analysis", scs: list) -> ReadCheck:
    shp = {
        "VIEW": union(*(shape(s.out["view"]) for s in scs)),
        "SHELF": union(*(shape(s.shelf) for s in scs)),
        "SNAP": union(*(shape(s.snap) for s in scs)),
    }
    problems, unanalyzed = [], []
    domain_keys = {"conservative", "balanced", "aggressive", "true", "false", "undefined"}
    spec_by_id = {s.id: s for s in an.specs}
    for sc in scs:
        for s in an.specs:
            got = sc.out["specs"].get(str(s.id))
            if got is None or got.get("module") != s.module or got.get("name") != s.name:
                raise NotMeasured(f"сцена «{sc.name}» исполнена для ДРУГОГО набора вызовов (вызов {s.id} "
                                  f"{Path(s.module).name}::{s.name}) — сверять чтения не с чем")

    def spec_resolves(sid, sub):
        found_any = False
        for sc in scs:
            res = sc.out["specs"].get(str(sid)) or sc.out["specs"].get(sid)
            if not res:
                continue
            for d in res["results"]:
                found_any = True
                if not sub:
                    return True
                if resolves(sub, {tuple(map(str, p)): "x" for p in d["paths"]}):
                    return True
                for r in d["refs"]:
                    at = tuple(map(str, r["at"]))
                    if sub[:len(at)] == at and resolves(tuple(r["path"]) + sub[len(at):], shp[r["root"]]):
                        return True
        return None if not found_any else False

    for rd in an.reads:
        where = f"{Path(rd.file).relative_to(SRC) if str(rd.file).startswith(str(SRC)) else rd.file}:{rd.line}"
        if isinstance(rd.root, tuple):
            spec = spec_by_id[rd.root[1]]
            if not _is_target(spec.module):
                continue
            ok = spec_resolves(rd.root[1], tuple(map(str, rd.path)))
            if ok is None:
                problems.append(f"{where}: вызов {Path(spec.module).name}::{spec.name} не исполнился ни в одной "
                                f"сцене — чтение «.{'.'.join(map(str, rd.path))}» НЕ ИЗМЕРЕНО")
            elif not ok and rd.kind != "maybe_builtin":
                problems.append(f"{where}: читает «{Path(spec.module).name}::{spec.name}(…)."
                                f"{'.'.join(map(str, rd.path))}», а в выходе функции такого поля нет")
            continue
        if resolves(rd.path, shp[rd.root]):
            continue
        if rd.kind == "maybe_builtin" and resolves(rd.path[:-1], shp[rd.root]):
            continue
        problems.append(f"{where}: читает {rd.root}:/{'/'.join(map(str, rd.path))}, а такого пути в выходе "
                        f"модуля нет — страница напечатает «undefined»")

    for sc in scs:
        for r in sc.out["reads"]:
            if r["present"] or r["root"] not in shp:
                continue
            path = tuple(map(str, r["path"]))
            if resolves(path, shp[r["root"]]) or resolves(_generic(path), shp[r["root"]]):
                continue
            if r["ctx"].startswith("explore:") and path and path[-1] in domain_keys:
                continue
            ctx = r["ctx"]
            if ctx.startswith(("call:", "explore:")):
                sid = int(ctx.split(":", 1)[1])
                ctx = f"{Path(spec_by_id[sid].module).name}::{spec_by_id[sid].name} (зов из {spec_by_id[sid].site})"
            problems.append(f"[{sc.name}] {ctx}: читает {r['root']}:/{'/'.join(path)}, а такого пути нет "
                            f"ни в одной сцене")
        for e in sc.out["errors"]:
            problems.append(f"[{sc.name}] модуль не исполнился: {e}")

    for es in an.escapes:
        ref = es.ref
        if isinstance(ref.root, tuple):
            if not _is_target(spec_by_id[ref.root[1]].module):
                continue
            continue          # call results of the four modules are plain values: escape is a copy
        hit = resolves(ref.path, shp[ref.root])
        if hit is None or shp[ref.root].get(hit) == "scalar":
            continue
        if ref.root == "VIEW" and _pass_through(ref.path, scs):
            continue
        unanalyzed.append(f"{es.file}:{es.line}: {ref.root}:/{'/'.join(map(str, ref.path))} — {es.why}")

    shelf_reads, snap_reads, view_reads = set(), set(), set()
    by_root = {"SHELF": shelf_reads, "SNAP": snap_reads, "VIEW": view_reads}
    for rd in an.reads:
        if isinstance(rd.root, tuple):
            # a read on what a function handed out: when it handed out a piece of the data, the read
            # lands on the data (``(book(k) || {}).evidence_split.observed_since`` reads the shelf)
            sub = tuple(map(str, rd.path))
            for sc in scs:
                res = sc.out["specs"].get(str(rd.root[1])) or {}
                for d in res.get("results", []):
                    for r in d["refs"]:
                        at = tuple(map(str, r["at"]))
                        if sub[:len(at)] == at and r["root"] in by_root:
                            by_root[r["root"]].add(tuple(map(str, r["path"])) + sub[len(at):])
        elif rd.root == "SHELF":
            shelf_reads.add(tuple(map(str, rd.path)))
        elif rd.root == "SNAP":
            snap_reads.add(tuple(map(str, rd.path)))
        elif rd.root == "VIEW":
            view_reads.add(tuple(map(str, rd.path)))
    for sc in scs:
        for r in sc.out["reads"]:
            p = tuple(map(str, r["path"]))
            if r["root"] == "SHELF" and r["ctx"] != VIEW_CTX:
                shelf_reads.add(p)
            elif r["root"] == "SNAP":
                snap_reads.add(p)
            elif r["root"] == "VIEW":
                view_reads.add(p)
    return ReadCheck(problems, unanalyzed, shp, shelf_reads, snap_reads, view_reads)


PACKAGE_IDS = ("conservative", "balanced", "aggressive")


def _generic(path):
    """Entries of a map keyed by package id share one schema: a field optional in one book is
    resolved against its siblings (``composition.tiers_held.unresolved`` exists only where there is
    something unresolved)."""
    return tuple("*" if k in PACKAGE_IDS else k for k in path)


def _pass_through(path, scs) -> bool:
    """A view subtree that IS the snapshot subtree (deep-equal in every scene and instance)."""
    for sc in scs:
        vi = instances(sc.out["view"], path)
        if not vi:
            return False
        for p, v in vi:
            try:
                if get_at(sc.snap, p) != v:
                    return False
            except KeyError:
                return False
    return True


# ── classification of the snapshot's paths ───────────────────────────────────────────────────────

VIEW_C = "переходник"
SHELF_READ_C = "витрина → читатель"
SHELF_ONLY_C = "только витрина, не читается (объявлено, доказано)"
UNPUBLISHED_C = "не публикуется (объявлено, доказано)"
DUPLICATE_C = "дубль пути, доходящего до страницы (объявлено, доказано)"
CONTAINER_C = "контейнер"


def _matches(read, target) -> bool:
    return len(read) >= len(target) and all(a == b or a == "*" or b == "*" for a, b in zip(read, target))


def classify_snapshot_paths(snap: dict, view: dict, pmap: dict, rc: ReadCheck, not_in_view: dict,
                            shelf_only: dict, unpublished: dict, duplicate_of: dict) -> "tuple[dict, list]":
    """{snapshot path: (class, proof)} and the problems. Nothing is exempt by default:

    * ``переходник`` — the path is in the view's output (node);
    * ``витрина → читатель`` — perturbing it surfaces in the shelf AND a consumer reads that shelf path
      (static page reads + reads recorded while the site's modules ran), the view's own construction
      excluded — so a field the view drops is never «covered» by the view having read it;
    * declared paths are accepted only with their proof, and a declaration a measurement makes
      unnecessary is itself a problem (the bases may only shrink):
        ``NOT_IN_VIEW`` / ``UNPUBLISHED`` — perturbation changes nothing published and no consumer reads
        the snapshot path directly; ``NOT_IN_VIEW`` / ``SHELF_ONLY`` — perturbation surfaces in the shelf
        and nobody reads it there; ``DUPLICATE_OF`` — equal (at the stated rounding) to a path that does
        reach a page, and itself read by nobody.
    """
    vpaths = snapshot_paths(view)
    leaves_of = {}
    for (origin, leaf), pr in pmap.items():
        if origin == "snapshot":
            for n in range(1, len(leaf) + 1):
                leaves_of.setdefault("/" + "/".join(leaf[:n]), []).append(pr)

    def targets(prs):
        return sorted({"/" + "/".join(t) for pr in prs for t in pr.identity + pr.mirror})

    def touched(prs):
        return [t for pr in prs for t in pr.touched]

    def direct_snap_read(p):
        tp = tuple(p.strip("/").split("/"))
        return any(_matches(r, tp) or _matches(tp, r) for r in rc.snap_reads)

    def read_targets(prs):
        return sorted({"/" + "/".join(t) for pr in prs for t in pr.identity + pr.mirror
                       if any(_matches(r, t) for r in rc.shelf_reads)})

    def declared(table, p):
        anc = p
        while True:
            if anc in table:
                return anc
            if anc.count("/") <= 1:
                return None
            anc = anc.rsplit("/", 1)[0]

    def unpublished_proof(p, prs):
        if not prs:
            return "у пути нет листов, подменять нечего"
        if touched(prs):
            return f"подмена меняет витрину {sorted({'/' + '/'.join(map(str, t)) for t in touched(prs)})[:3]}"
        if direct_snap_read(p):
            return "его читают из снимка напрямую"
        return None

    def shelf_only_proof(p, prs):
        if not prs or not all(pr.identity or pr.mirror for pr in prs):
            return "подмена не всплывает в витрине целиком"
        rt = read_targets(prs)
        if rt:
            return f"витрину по этому пути ЧИТАЮТ ({rt[:3]})"
        if direct_snap_read(p):
            return "его читают из снимка напрямую"
        return None

    out, problems = {}, {}
    all_paths = sorted(snapshot_paths(snap))
    for p in all_paths:
        prs = leaves_of.get(p, [])
        tp = tuple(p.strip("/").split("/"))
        is_dict = isinstance(get_at(snap, tp), dict)
        if p in vpaths:
            out[p] = (VIEW_C, "путь есть в выходе переходника (node)")
        elif not is_dict and prs and all((pr.identity or pr.mirror) and read_targets([pr]) for pr in prs):
            out[p] = (SHELF_READ_C, f"→ {read_targets(prs)[:3]}")
        else:
            out[p] = None
    measured = {p: c for p, c in out.items() if c is not None}

    def need(table_name, d, p):
        if p in measured:
            problems[p] = (f"{p}: объявлен в {table_name} ({d}), но замер и так доводит его до страницы "
                           f"({measured[p][0]}) — объявление лишнее, снять (база только уменьшается)")
            return False
        return True

    used = set()
    for p in all_paths:
        prs = leaves_of.get(p, [])
        for table_name, table in (("NOT_IN_VIEW", not_in_view), ("SHELF_ONLY", shelf_only),
                                  ("UNPUBLISHED", unpublished), ("DUPLICATE_OF", duplicate_of)):
            # NOT_IN_VIEW lists every path itself (as it always did); the new tables may declare a
            # whole subtree, and every leaf below still has to carry the proof
            d = (p if p in table else None) if table_name == "NOT_IN_VIEW" else declared(table, p)
            if d is None:
                continue
            used.add((table_name, d))
            if d == p and not need(table_name, d, p):
                break
            if out[p] is not None and d != p:
                break           # an ancestor declaration does not override a measured class
            if table_name == "DUPLICATE_OF":
                other, digits = table[d] if d == p else (None, None)
                if other is None:
                    problems[p] = f"{p}: DUPLICATE_OF объявляется только для листа, не для контейнера ({d})"
                    break
                try:
                    a = get_at(snap, tuple(p.strip('/').split('/')))
                    b = get_at(snap, tuple(other.strip('/').split('/')))
                except KeyError:
                    problems[p] = f"{p}: объявлен дублем {other}, а такого пути в снимке нет"
                    break
                eq = (a == b) if digits is None else (_num(a) is not None and _num(b) is not None
                                                     and round(_num(b), digits) == round(_num(a), digits))
                oc = measured.get(other)
                if not eq:
                    problems[p] = f"{p}: объявлен дублем {other}, но {a!r} ≠ {b!r}" + (
                        f" (округление {digits} зн.)" if digits is not None else "")
                elif oc is None:
                    problems[p] = f"{p}: объявлен дублем {other}, но {other} сам до страницы не доходит"
                elif read_targets(prs) or direct_snap_read(p):
                    problems[p] = f"{p}: объявлен дублем, но его самого читают — снять объявление"
                else:
                    out[p] = (DUPLICATE_C, f"= {other} ({oc[0]})" + (f", округление {digits} зн." if digits is not None else ""))
                break
            proofs = {"SHELF_ONLY": [shelf_only_proof], "UNPUBLISHED": [unpublished_proof],
                      "NOT_IN_VIEW": [unpublished_proof, shelf_only_proof]}[table_name]
            fails = [f(p, prs) for f in proofs]
            if any(x is None for x in fails):
                which = (UNPUBLISHED_C if proofs[[x is None for x in fails].index(True)] is unpublished_proof
                         else SHELF_ONLY_C)
                tg = targets(prs)
                out[p] = (which, f"{table_name}: {table[d]}" + (f" · витрина: {tg[:2]}{' …' if len(tg) > 2 else ''}"
                                                                   if which == SHELF_ONLY_C else ""))
            else:
                problems[p] = f"{p}: объявлен в {table_name} ({d}), но доказательство не сходится: {'; '.join(fails)}"
            break
    for p in sorted(out, key=lambda x: -x.count("/")):
        if out[p] is None and p not in problems:
            kids = [q for q in out if q.startswith(p + "/") and q.count("/") == p.count("/") + 1]
            if kids and all(out[q] is not None for q in kids):
                out[p] = (CONTAINER_C, f"все {len(kids)} дочерних путей классифицированы")
    for p, c in sorted(out.items()):
        if c is None and p not in problems:
            prs = leaves_of.get(p, [])
            tg = targets(prs)
            problems[p] = (f"{p}: не классифицирован — нет в переходнике; "
                           + (f"витрина несёт его ({tg[:3]}), но ни одна страница этого не читает"
                              if tg else "в витрину не попадает")
                           + "; объявить с доказательством или вернуть в переходник")
    for table_name, table in (("NOT_IN_VIEW", not_in_view), ("SHELF_ONLY", shelf_only),
                              ("UNPUBLISHED", unpublished), ("DUPLICATE_OF", duplicate_of)):
        for d in table:
            if (table_name, d) not in used:
                problems[d] = problems.get(d) or (f"{d}: запись {table_name} ничего не классифицирует "
                                                  f"(пути нет в снимке) — мусор, снять")
    return out, [problems[p] for p in sorted(problems)]


# ── one measurement for every test of the chain ──────────────────────────────────────────────────

@dataclass
class Measurement:
    analysis: object
    scenes: list
    reads: ReadCheck
    pmap: dict
    origins: dict
    shelf: dict
    snap: dict
    const: dict
    bsn: object
    shelf_inputs: str          # where the inputs of the published shelf were found


def page_files():
    """Pages, components and layouts that read the view / shelf / realized_rate / book_exposure.
    The site's own modules (``lib/``) are not read statically: they are EXECUTED (``run_harness``),
    which sees the branch they really take instead of guessing at both."""
    return [f for f in jr.reader_files(SRC.resolve()) if (SRC.resolve() / "lib") not in f.parents]


_CACHE: dict = {}


def measure() -> Measurement:
    if "m" in _CACHE:
        return _CACHE["m"]
    for p in (SNAPSHOT, SHELF, CONSTITUTION, VIEW_MODULE):
        if not p.is_file():
            raise NotMeasured(f"{p.relative_to(ROOT)} нет в этом дереве")
    an = jr.analyze(SRC.resolve(), files=page_files())
    shelf = json.loads(SHELF.read_text(encoding="utf-8"))
    snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    const = json.loads(CONSTITUTION.read_text(encoding="utf-8"))
    bsn = load_builder()
    scs = scenes(an.specs, sorted(an.closure), shelf, snap, const, bsn)
    rc = check_reads(an, scs)
    pmap = projection_map(bsn, snap, const, shelf.get("published_at") or "2026-01-01")
    origins = figure_origins(pmap)
    hashes = (shelf.get("_provenance") or {}).get("source_hashes") or {}
    rel_s, rel_c = "landing/src/data/track_snapshot.json", "landing/src/lib/constitution.json"
    if rel_s not in hashes or rel_c not in hashes:
        raise NotMeasured("витрина не объявляет хэши своих входов (_provenance.source_hashes)")
    in_snap, where_s = input_by_hash(rel_s, hashes[rel_s], SNAPSHOT)
    in_const, where_c = input_by_hash(rel_c, hashes[rel_c], CONSTITUTION)
    m = Measurement(an, scs, rc, pmap, origins, shelf, in_snap, in_const, bsn, f"{where_s}; {where_c}")
    m.today_snap = snap
    _CACHE["m"] = m
    return m
