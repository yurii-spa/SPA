"""Retrieval index — SQLite FTS5 (BM25) over the allow-listed sources. DISPOSABLE by design.

Losing data/memory/index.db loses nothing: `build()` recreates it from the sources in seconds and the
build manifest records exactly which files (and their hashes) went in.

Russian/English robustness without a model: every chunk is indexed twice — the original words and a
light-stemmed form (Russian and English suffix stripping) — and queries are expanded through a small
bilingual glossary (агент↔agent, решение↔decision/ADR, владелец↔owner …). Ranking = BM25, then a
boost for authority and a demotion for SUPERSEDED/REJECTED (still returned, flagged).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from . import sources as src
from . import truth as tr

REPO = Path(__file__).resolve().parents[3]
MAX_CHUNK = 1800

_WORD = re.compile(r"[0-9A-Za-zА-Яа-яЁё_.\-]+")
_RU_SUFFIX = sorted("""ировать ировали ировал ирует уется ениями ениям ения ение ений ениях ностью ность ности
 ового ового ыми ими ого его ому ему ая яя ое ее ые ие ый ий ой ем ом ам ям ах ях ами ями ов ев ей ую юю
 ешь ет ют ут ит ат ят ал ала али ило или ть ться тся сь ся а я о е ы и у ю ь""".split(), key=len, reverse=True)
_EN_SUFFIX = ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "ied", "ers", "er", "ed", "es", "s")

#: Bilingual glossary — each group is one concept. Query terms are OR-expanded within their group.
GLOSSARY = [
    {"агент", "агента", "агенты", "agent", "agents", "сервис", "service", "служба"},
    {"ресерч", "ресёрч", "ресерча", "ресёрча", "research", "исследование", "исследования"},
    {"решение", "решения", "решил", "decision", "decisions", "adr", "постановил"},
    {"владелец", "владельца", "owner", "юрий", "юрия"},
    {"пауза", "приостановлен", "выключен", "paused", "disabled", "disable", "bootout", "остановлен"},
    {"почему", "зачем", "why", "причина", "reason", "purpose", "цель"},
    {"телеграм", "telegram", "бот", "bot"},
    {"финансовое", "financial", "деньги", "money", "капитал", "capital"},
    {"состояние", "state", "состоянием"},
    {"дорожная", "roadmap", "план", "plan", "следующий", "next", "эпик", "epic"},
    {"реализовано", "implemented", "сделано", "построено", "built", "done", "delivered"},
    {"предложено", "proposed", "идея", "idea", "черновик", "draft"},
    {"заменён", "superseded", "supersedes", "устарел", "заменяет"},
    {"релиз", "release", "выпуск", "approved"},
    {"инцидент", "incident", "авария", "recovery", "восстановление"},
    {"торговый", "торговое", "trading", "трейдинг", "стратегии", "strategies"},
    {"одобрение", "approval", "разрешение", "permission", "gate", "гейт"},
    # site vocabulary (ADR-537): the redesign specs that explain WHY a site feature exists are English;
    # an owner asks in Russian. Measured 2026-10-02: «калькулятор доходности» found no spec at all.
    {"калькулятор", "калькулятора", "calculator", "calc"},
    # NOT «главная → homepage»: «главная находка» (main finding) is far more frequent in the canon (measured)
    {"сайт", "сайта", "сайте", "site", "website"},
    {"пакет", "пакеты", "пакетов", "package", "packages", "тир", "тиры", "tier", "tiers"},
]
_GLOSS_INDEX: Dict[str, set] = {}
for _g in GLOSSARY:
    for _w in _g:
        _GLOSS_INDEX[_w] = _g


def alias_groups() -> List[Dict]:
    """ADR-591 §A5 — `architecture/memory_aliases.json`: RU/EN/superseded names for the SAME
    entity (Oracle/Оракул/Штирлиц, Sherlock/Шерлок, Bridge/Мост…), expanded at query time exactly
    like `GLOSSARY` above. Not cached process-wide: tests point `SPA_MEMORY_ROOT_SPA` at a
    different tmp corpus per test, and this file is small (a few KB) to re-read. A group marked
    `ambiguous` (e.g. "Core": tier name / package / colloquial "core engine") is loaded but never
    expanded — expanding an ambiguous word would trade one false negative for several false
    positives. Missing or malformed file ⇒ no aliases, never an exception (same fail-soft contract
    as `GLOSSARY`, which is static and can't fail)."""
    try:
        p = src.roots()["spa"] / "architecture" / "memory_aliases.json"
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [g for g in data.get("groups", []) if not g.get("ambiguous")]


def _alias_group_for(w: str) -> Optional[set]:
    """Name-set of the alias group word `w` belongs to, or None. Kept separate from the
    superseded-name NOTE below: `concepts()` dedupes by group (one «Oracle»-sized concept per
    query, same as GLOSSARY), so a query using BOTH the current and the superseded name in the
    same sentence («…Оракулом… Штирлицем…», N04) would silently drop the second occurrence's note
    if the note lived on the per-concept dict. `alias_notes_in()` below scans every word
    independently of that dedup for exactly this reason."""
    for grp in alias_groups():
        lower = {str(n["name"] if isinstance(n, dict) else n).lower() for n in grp.get("names", [])}
        if w in lower or stem(w) in {stem(x) for x in lower}:
            return lower
    return None


def alias_notes_in(q: str) -> List[Dict]:
    """ADR-591 §A5/§A6-lite: every superseded alias NAME used in the query, independent of
    `concepts()`'s per-group dedup (see `_alias_group_for`'s docstring for why that matters).
    «Штирлиц until 2026-10-04» is the seed case: a question can legitimately use both the current
    and the retired name in one sentence (N04) and both deserve a note."""
    out, seen = [], set()
    for w in _words(q):
        for grp in alias_groups():
            names = [n if isinstance(n, dict) else {"name": n} for n in grp.get("names", [])]
            sup = next((n for n in names if n.get("valid_to")
                       and (str(n["name"]).lower() == w or stem(str(n["name"]).lower()) == stem(w))), None)
            if sup and sup["name"] not in seen:
                seen.add(sup["name"])
                out.append({"canonical": grp.get("canonical"), "superseded_name": sup["name"],
                            "valid_to": sup["valid_to"]})
    return out

STOP = {"и", "в", "во", "на", "с", "со", "что", "как", "а", "по", "к", "у", "о", "об", "за", "из", "это", "ли",
        "не", "the", "a", "an", "of", "to", "is", "in", "and", "for", "what", "does", "do", "who", "which",
        "сейчас", "уже", "был", "была", "было", "были", "есть", "мне", "между", "чем", "кто", "какой",
        "какая", "какие", "какое", "каких", "скажи", "пожалуйста", "он", "она", "оно", "они", "его", "её", "ее",
        "их", "им", "неё", "нее",
        "каким", "какого", "какую", "каком", "it", "its", "they", "them",
        # conversational fillers of spoken / dictated Russian — carry no topic
        "слушай", "вообще", "этот", "эта", "это", "тот", "та", "те", "штука", "реально", "вот", "ну", "там",
        "нас", "наш", "наша", "наши", "мы", "ты", "вы", "мой", "моё", "мое", "моя", "можешь", "расскажи",
        # ADR-591 §Wave2 — English function words with ZERO topic content. Measured 2026-10-06: the
        # Russian list above already strips auxiliaries/pronouns, but the English list stopped at a
        # handful of articles/wh-words, so an EN phrasing of the SAME question carried several extra
        # weight=1.0 concepts its RU twin never had ("did","was","from","come","called","before" in
        # "Where did the Oracle CIO come from and what was it called before?"). Each of those matches
        # almost every chunk in the corpus (auxiliary verbs, prepositions), diluting the one real
        # concept (the alias group) relative to noise — this, not a broken alias expansion, is why
        # RU/EN top-5 disagreed on all 9 paired questions (0/9).
        "was", "were", "did", "will", "would", "can", "could", "should", "shall", "be", "been", "being",
        "have", "has", "had", "this", "that", "these", "those", "then", "than", "with", "on", "at", "by",
        "as", "about", "into", "out", "up", "down", "over", "under", "such", "any", "all", "some", "more",
        "most", "other", "now", "also", "just", "i", "you", "he", "she", "we", "our", "your", "his", "her",
        "if", "or", "but", "not", "no", "so", "there", "here", "both", "each", "own", "same", "too"}


def stem(w: str) -> str:
    w = w.lower().replace("ё", "е")
    if re.match(r"^[а-я]+$", w) and len(w) > 4:
        for s in _RU_SUFFIX:
            if w.endswith(s) and len(w) - len(s) >= 3:
                return w[: -len(s)]
    if re.match(r"^[a-z]+$", w) and len(w) > 4:
        for s in _EN_SUFFIX:
            if w.endswith(s) and len(w) - len(s) >= 3:
                return w[: -len(s)]
    return w


def stems(text: str) -> str:
    return " ".join(stem(w) for w in _WORD.findall(text))


_REF = re.compile(r"\bADR-B?\d[\w.]*|\bb19\.\d+\.\d+\b|\bcom\.(?:spa|studiobridge|earn-defi)\.[\w.-]+|\b(?:inbox|own|owner-decision|agent)-[a-z0-9-]{6,}")


def refs(text: str) -> List[str]:
    return sorted({m.group(0).rstrip(".").replace("ADR-B", "ADR-B") for m in _REF.finditer(text)})[:40]


def _chunks(text: str) -> List[tuple]:
    """(heading, body) chunks: split on markdown headings, then cap size (sentence-aware)."""
    parts, head, buf = [], "", []
    for line in text.splitlines():
        if re.match(r"^#{1,4}\s", line):
            if buf:
                parts.append((head, "\n".join(buf)))
            head, buf = line.lstrip("# ").strip(), []
        else:
            buf.append(line)
    if buf:
        parts.append((head, "\n".join(buf)))
    out = []
    for h, body in parts:
        body = body.strip()
        while len(body) > MAX_CHUNK:
            cut = max(body.rfind(". ", 0, MAX_CHUNK), body.rfind("\n", 0, MAX_CHUNK))
            cut = cut if cut > MAX_CHUNK // 3 else MAX_CHUNK
            out.append((h, body[:cut + 1]))
            body = body[cut + 1:].lstrip()
        if body:
            out.append((h, body))
    return out


def _agent_docs(text: str) -> List[tuple]:
    """architecture/manifest.json → one chunk per agent (its passport is the semantic record)."""
    try:
        m = json.loads(text)
    except ValueError:
        return []
    out = []
    for a in m.get("agents", []):
        p = a.get("passport") or {}
        body = "\n".join(f"{k}: {v}" for k, v in [("label", a["label"]), ("role", a.get("role")),
                         ("intent", a.get("intent")), ("schedule", a.get("schedule")),
                         ("program", a.get("program")), ("notes", a.get("notes"))] + sorted(p.items()) if v)
        out.append((a["label"], body))
    return out


def _provenance_docs(text: str) -> List[tuple]:
    """architecture/provenance.json → one chunk per artifact (ADR-551): purpose, task, decision,
    producer, reviewer, owner, status — the record a fresh session needs before changing it."""
    try:
        m = json.loads(text)
    except ValueError:
        return []
    out = []
    for a in m.get("artifacts", []):
        keys = ("purpose", "purpose_source", "source_task", "source_decision", "producer_role", "producer_run",
                "reviewer", "owner_role", "status", "supersedes", "consumers", "notes")
        body = "\n".join(f"{k}: {a[k]}" for k in keys if a.get(k)) + f"\nanchors: {', '.join(a.get('anchors', []))}"
        out.append((f"ARTIFACT {a['id']} [{a.get('status')}] {' '.join(a.get('anchors', []))}", body))
    return out


def _roles_docs(text: str) -> List[tuple]:
    """architecture/roles.json → one chunk per role (ADR-591 §A4): role_id, display_name (Oracle,
    Sherlock, Шурик), domain, authority and may/may_not. Measured 2026-10-05: without this, "who is
    Oracle / what may Sherlock not do" had zero canonical evidence (oracle_origin 0.458)."""
    try:
        m = json.loads(text)
    except ValueError:
        return []
    out = []
    for r in m.get("roles", []):
        keys = ("title", "display_name", "domain", "domain_excludes", "implemented", "reserved",
                "adr", "authority", "authority_over_capital", "may", "may_not")
        body = "\n".join(f"{k}: {r[k]}" for k in keys if r.get(k) not in (None, [], ""))
        out.append((f"ROLE {r['role_id']} [{r.get('display_name')}]", body))
    return out


_ADR_B_NUM = re.compile(r"ADR[_-](\d{2,4})(?!\d)", re.I)


def _adr_b_docs(text: str, rel: str) -> List[tuple]:
    """docs/adr/*.md → chunks tagged ADR-B<n> (ADR-591 §A4): a SECOND ADR registry that collides on
    number with docs/decisions/ (CLAUDE.md: 5 cross-registry collisions; measured 2026-10-05: 10
    including intra-registry dupes 002/021). The "ADR-B" prefix is the convention already reserved
    in the `_ADR`/`_REF` regexes below and in passports.py/truth.py — this is its first producer."""
    m = _ADR_B_NUM.search(Path(rel).name)
    tag = f"ADR-B{m.group(1)}" if m else None
    out = []
    for heading, body in _chunks(text):
        out.append((f"{tag} · {heading}" if tag else heading, body))
    return out


def _truth_docs(text: str) -> List[tuple]:
    """architecture/memory_truth.json → one chunk per fact/override (semantic memory with evidence)."""
    try:
        m = json.loads(text)
    except ValueError:
        return []
    out = []
    for f in m.get("facts", []):
        out.append((f"FACT {f['subject']} [{f['status']}] {f.get('aliases', '')}",
                    f"{f['fact']}\nevidence: {'; '.join(f.get('evidence', []))}"
                    + (f"\nUNKNOWN: {f['unknown']}" if f.get("unknown") else "")))
    for o in m.get("overrides", []):
        out.append((f"STATUS {o['path']} = {o['status']}",
                    f"{o['path']} is {o['status']}" + (f", superseded by {o['superseded_by']}" if o.get("superseded_by") else "")
                    + f". {o.get('reason', '')}"))
    return out


SCHEMA = """
CREATE TABLE chunks (id INTEGER PRIMARY KEY, repo TEXT, path TEXT, layer TEXT, kind TEXT, authority INTEGER,
  status TEXT, status_basis TEXT, superseded_by TEXT, title TEXT, heading TEXT, body TEXT, refs TEXT,
  mtime INTEGER);
CREATE VIRTUAL TABLE fts USING fts5(title, heading, body, stemmed, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE manifest (key TEXT PRIMARY KEY, value TEXT);
"""


def default_path() -> Path:
    env = os.environ.get("SPA_MEMORY_INDEX")
    if env:
        return Path(env)
    from spa_core.utils.live_paths import live_data_dir
    return live_data_dir(REPO) / "memory" / "index.db"


#: an abandoned ``.building.*`` tmp file older than this is swept at the start of the NEXT
#: `build()` — younger than this, it is left alone on the chance it belongs to a build genuinely
#: in progress right now (a real `build()` call measures 6–30 s; 10 min is a wide margin either way).
_ABANDONED_TMP_MIN_AGE_S = 600


def build(path: Optional[Path] = None) -> Dict:
    """Rebuild from scratch (atomic: build in a PROCESS-UNIQUE tmp file, then ``os.replace``).

    Round-2 review fix, 2026-10-06: the tmp path used to be the single FIXED name
    ``<path>.building``, shared by every caller of this function. The scheduled ensure-fresh
    step (``scripts/agent_system_briefing.sh``) and an interactive ``assembler.assemble()``
    auto-rebuild (``ensure_fresh(rebuild=True)``) can both decide the index is stale and call
    `build()` around the same time; sharing one tmp name let one connection's half-written
    sqlite file be clobbered — or renamed out from under the other — by the sibling. The tmp
    name now embeds the pid and a random suffix, so two concurrent builders never write to the
    same file; only the final ``os.replace`` onto the shared ``path`` is common, and that
    rename is already atomic at the filesystem level (one caller's complete index wins, never a
    half-written one).
    """
    path = Path(path or default_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f"{path.name}.building.{os.getpid()}.{uuid.uuid4().hex[:8]}"
    # A process that died mid-build leaves ITS OWN uniquely-named tmp file behind forever —
    # nothing will ever claim that exact name again. Sweep genuinely old leftovers so they do
    # not accumulate, but never a fresh one: it may belong to a sibling build in progress right
    # now, and deleting it out from under that sibling would be the very race this fix closes.
    now = time.time()
    for stale in path.parent.glob(f"{path.name}.building.*"):
        try:
            if stale != tmp and (now - stale.stat().st_mtime) > _ABANDONED_TMP_MIN_AGE_S:
                stale.unlink()
        except OSError:
            pass
    conn = sqlite3.connect(str(tmp))
    try:
        man = _build_into(conn)
    except Exception:
        conn.close()
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    os.replace(tmp, path)
    return man


def _build_into(conn: sqlite3.Connection) -> Dict:
    """Fills ``conn`` (open on ``tmp``) with the whole index and commits+closes it. Split out of
    `build()` only so the tmp-file lifecycle (create unique name → fill → atomically publish or
    discard on error) reads as one thing in `build()` itself."""
    conn.executescript(SCHEMA)
    files = list(src.iter_files())
    texts = []
    for rule, p, rel in files:
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        texts.append((rule, p, rel, raw))
    reg_path = src.roots()["spa"] / "architecture" / "memory_truth.json"
    truth = tr.Truth(tr.load_registry(reg_path),
                     [(f"{r.root}:{rel}", r.layer, r.kind, raw) for r, p, rel, raw in texts])
    n_chunks, dropped, digest = 0, 0, hashlib.sha256()
    for rule, p, rel, raw in texts:
        clean, d = src.sanitize(raw)
        dropped += d
        key = f"{rule.root}:{rel}"
        digest.update(key.encode()); digest.update(hashlib.sha256(clean.encode()).digest())
        st = truth.resolve(key, rule.layer, clean)
        title = _title(clean, rel)
        pieces = (_agent_docs(clean) if rule.kind == "agents" else _truth_docs(clean) if rule.kind == "truth"
                  else _provenance_docs(clean) if rule.kind == "provenance"
                  else _roles_docs(clean) if rule.kind == "roles"
                  else _adr_b_docs(clean, rel) if rule.kind == "adr_b" else _chunks(clean))
        for heading, body in pieces:
            if not body.strip():
                continue
            cur = conn.execute(
                "INSERT INTO chunks (repo,path,layer,kind,authority,status,status_basis,superseded_by,title,heading,"
                "body,refs,mtime) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rule.root, rel, rule.layer, rule.kind, rule.authority, st["status"], st["basis"],
                 st.get("superseded_by"), title, heading, body, json.dumps(refs(heading + " " + body)),
                 int(p.stat().st_mtime)))
            conn.execute("INSERT INTO fts (rowid,title,heading,body,stemmed) VALUES (?,?,?,?,?)",
                         (cur.lastrowid, title, heading, body, stems(title + " " + heading + " " + body)))
            n_chunks += 1
    man = {"built_at": int(time.time()), "files": len(texts), "chunks": n_chunks, "secret_lines_dropped": dropped,
           "roots": {k: str(v) for k, v in src.roots().items()}, "present_roots": src.present_roots(),
           "sources_digest": digest.hexdigest()[:16],
           # ADR-591 §A1: the CHEAP (stat-only) staleness signal `ensure_fresh()` compares against
           # on every call. `sources_digest` above stays content-hashed (ADR-527 §A8 recovery proof).
           "mtime_fingerprint": src.fingerprint(),
           "schema": "studio-os/memory-index/1"}
    for k, v in man.items():
        conn.execute("INSERT INTO manifest VALUES (?,?)", (k, json.dumps(v)))
    conn.commit()
    conn.close()
    return man


def _title(text: str, rel: str) -> str:
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return (m.group(1).strip() if m else rel)[:200]


def manifest(path: Optional[Path] = None) -> Optional[Dict]:
    p = Path(path or default_path())
    if not p.exists():
        return None
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        return {k: json.loads(v) for k, v in c.execute("SELECT key, value FROM manifest")}
    finally:
        c.close()


def freshness(path: Optional[Path] = None) -> Dict:
    """ADR-591 §A1 — does the on-disk index match the CURRENT sources, right now? Stat-only
    (`src.fingerprint()`): never reads file content, so this is cheap enough to call on every
    `assembler.assemble()`, not just the scheduled step. Measured 2026-10-05 (pre-fix): the live
    prod index was 44 h stale and nothing ever compared it against anything — `search()` has no
    concept of "old"."""
    p = Path(path or default_path())
    fp = src.fingerprint()
    man = manifest(p)
    if man is None:
        return {"stale": True, "reason": "no-index", "fingerprint": fp, "built_at": None, "age_s": None}
    stale = man.get("mtime_fingerprint") != fp
    built_at = man.get("built_at")
    age_s = (int(time.time()) - built_at) if built_at else None
    return {"stale": stale, "reason": "sources-changed" if stale else None, "fingerprint": fp,
            "built_at": built_at, "age_s": age_s}


def ensure_fresh(path: Optional[Path] = None, *, rebuild: bool = True) -> Dict:
    """ADR-591 §A1 entry point for a scheduled step (wired into `scripts/agent_system_briefing.sh`,
    the existing 30-min mirror-sync tick — no new launchd agent) AND for `assembler.assemble()`
    itself. `rebuild=True` (the default used by `assemble()`): a stale index is rebuilt in place
    (≈6-30 s measured, cheap enough for an interactive call) so a query never silently answers from
    a stale snapshot. `rebuild=False`: never writes, only reports — the caller decides what STALE
    means for it (`assemble()` uses it to cap the verdict at PARTIAL, never SUFFICIENT)."""
    f = freshness(path)
    if f["stale"] and rebuild:
        build(path)
        f2 = freshness(path)
        f2["rebuilt"] = True
        return f2
    f["rebuilt"] = False
    return f


#: Question/intent words: they shape the query but must not dominate the ranking.
WEAK = {"почему", "зачем", "why", "причина", "reason", "purpose", "цель", "разница", "difference", "отличие",
        "чем", "отличается", "откуда", "where", "what", "кто", "who", "существует", "exists", "exist",
        # ADR-591 §Wave2 — EN origin/naming intent words, same low-weight class as откуда/почему above:
        # "come"/"from" = откуда ("Where did Oracle come FROM"), "called"/"before" = раньше назывался
        # ("what was it CALLED BEFORE"). Kept weighted (not dropped to STOP) because they still carry a
        # little of the question's intent, but at откуда's weight — not a full content word.
        "come", "from", "called", "before", "after", "раньше", "назывался", "ранее", "взялся", "взялась"}
_IDENT = re.compile(r"^(adr-b?\d[\w.]*|b19\.\d+\.\d+|com\.[\w.-]+|[a-z]+_[a-z_]+|[a-z]+-[a-z0-9-]+)$")


def _words(q: str) -> List[str]:
    """Words of a query; a hyphenated compound («трейдинг-ресёрча») also yields its parts."""
    out = []
    for w in _WORD.findall(q.lower().replace("ё", "е")):
        w = w.strip(".-")
        out.append(w)
        if "-" in w and not _IDENT.match(w):
            out += [x for x in w.split("-") if x]
    return out


def concepts(q: str) -> List[Dict]:
    """Query → concepts: each a set of alternative surface words + stems, a weight, identifier flag.
    ADR-591 §A5: a word not in the static GLOSSARY is also checked against the alias file — this is
    how «Оракул» and «Oracle» end up as the SAME concept group without a model."""
    out, seen = [], set()
    for w in _words(q):
        if w in STOP or len(w) < 2:
            continue
        group = _GLOSS_INDEX.get(w) or _GLOSS_INDEX.get(stem(w)) or _alias_group_for(w) or {w}
        key = tuple(sorted(group))
        if key in seen:
            continue
        seen.add(key)
        alts = sorted(set(group) | {w})
        ident = bool(_IDENT.match(w))
        out.append({"alts": alts, "stems": sorted({stem(x) for x in alts}), "ident": ident, "term": w,
                    "weight": 0.3 if w in WEAK else (3.0 if ident else 1.0)})
    return out


def _query(q: str) -> str:
    terms = []
    for c in concepts(q):
        exprs = [f'"{x}"' for x in c["alts"]] + \
                [f'stemmed:"{s}"*' if len(s) >= 4 else f'stemmed:"{s}"' for s in c["stems"]]
        terms.append("(" + " OR ".join(exprs) + ")")
    return " OR ".join(terms)


def _coverage(cs: List[Dict], hay: str, hay_stems: str) -> float:
    got = tot = 0.0
    for c in cs:
        tot += c["weight"]
        if any(a in hay for a in c["alts"]) or any(f" {s}" in hay_stems for s in c["stems"]):
            got += c["weight"]
    return got / tot if tot else 0.0


def _role_canonicals() -> set:
    """role_id of every role in `architecture/roles.json` (ADR-591 §A4) — used only to tell a role
    alias group apart from the other alias groups (tiers, bots, Bridge…) in `memory_aliases.json`."""
    try:
        p = src.roots()["spa"] / "architecture" / "roles.json"
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {r.get("role_id") for r in data.get("roles", []) if r.get("role_id")}


def _role_alias_words() -> set:
    """Every surface word (any language, current or `valid_to`) that names a ROLE specifically —
    not a tier, a bot or any other alias group. ADR-591 §Wave2 (point 3): the roles.json ranking
    boost in `search()` used to be unconditional for `kind=="roles"`, so Sherlock's passport (which
    legitimately says "may not change Oracle policy") could outrank the actually-relevant decision
    on a question that only MENTIONS a role name in passing. The boost should fire only when the
    QUESTION itself is about a role."""
    roles = _role_canonicals()
    if not roles:
        return set()
    words = set()
    for g in alias_groups():
        if g.get("canonical") in roles:
            for n in g.get("names", []):
                words.add(str(n["name"] if isinstance(n, dict) else n).lower())
    return words


def _query_names_role(query: str) -> bool:
    words = _role_alias_words()
    if not words:
        return False
    stemmed = {stem(w) for w in words}
    return any(w in words or stem(w) in stemmed for w in _words(query))


def search(query: str, *, k: int = 8, path: Optional[Path] = None, layers: Optional[Iterable[str]] = None,
           include_superseded: bool = True) -> List[Dict]:
    p = Path(path or default_path())
    fq = _query(query)
    if not fq or not p.exists():
        return []
    c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        rows = c.execute(
            "SELECT c.id, c.repo, c.path, c.layer, c.kind, c.authority, c.status, c.superseded_by, c.title, c.heading,"
            " c.body, c.refs, bm25(fts, 4.0, 3.0, 1.0, 1.5) AS s FROM fts JOIN chunks c ON c.id = fts.rowid"
            " WHERE fts MATCH ? ORDER BY s LIMIT 1500", (fq,)).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        c.close()
    want = set(layers) if layers else None
    cs = concepts(query)
    idents = [c["term"] for c in cs if c["ident"]]
    names_role = _query_names_role(query)
    out = []
    for (cid, repo, path_, layer, kind, auth, status, sup, title, heading, body, rf, s) in rows:
        if want and layer not in want:
            continue
        if not include_superseded and status in ("SUPERSEDED", "REJECTED"):
            continue
        hay = (path_ + " " + title + " " + heading + " " + body).lower()
        cov = _coverage(cs, hay, " " + stems(hay))
        ident_hit = sum(1 for t in idents if t in hay)
        head_hit = sum(1 for c in cs if c["weight"] >= 1 and any(a in (title + " " + heading).lower() for a in c["alts"]))
        score = (cov ** 2) * (1 + 0.6 * auth) * (1 + 1.5 * ident_hit + 0.4 * head_hit) * (1 + min(-s, 60) / 60)
        if kind == "card":
            score *= 0.5                    # one card is one task's prose — weak evidence for system questions
        if layer == "SEMANTIC":
            score *= 1.3
        if kind in ("agents", "provenance"):
            # ADR-591 §A4: one chunk = one entity's whole passport (agent/artifact). A generic
            # decision that mentions the SAME name in passing (there can be dozens) should not
            # outrank the one record that actually answers "who/what is this, who may it not do,
            # which ADR made it".
            score *= 2.4
        if kind == "roles":
            # ADR-591 §Wave2: the boost above is GLOBAL for agents/provenance (a label or artifact id
            # is specific enough that "mentioned at all" already means "about it"). A role's display
            # name (Oracle, Sherlock…) is not — those names show up inside OTHER roles' `may_not`
            # lines too (see docstring above `_role_alias_words`). So the big (3.6x) boost is
            # conditional on the QUESTION naming a role/alias; otherwise the role passport still gets
            # the plain SEMANTIC-sized bump (1.3x, same as any other well-authored canonical record)
            # rather than winning by default.
            score *= 3.6 if names_role else 1.3
        if status in ("SUPERSEDED", "REJECTED"):
            score *= 0.35
        ev = re.findall(r"\b(?:spa|bridge|earndefi|company|claude|shadow):[\w./-]+\.(?:md|json)", body) if kind == "truth" else []
        out.append({"id": cid, "repo": repo, "path": path_, "layer": layer, "kind": kind, "authority": auth, "evidence": ev,
                    "status": status, "superseded_by": sup, "title": title, "heading": heading,
                    "text": body, "refs": json.loads(rf), "score": round(score, 4)})
    out.sort(key=lambda r: -r["score"])
    # one chunk per document in the top-k (diversity), the best one
    seen, top = set(), []
    for r in out:
        key = (r["repo"], r["path"], r["heading"] if r["kind"] == "truth" else "")
        if key in seen:
            continue
        seen.add(key)
        top.append(r)
        if len(top) >= k:
            break
    return top
