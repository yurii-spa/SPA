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

STOP = {"и", "в", "во", "на", "с", "со", "что", "как", "а", "по", "к", "у", "о", "об", "за", "из", "это", "ли",
        "не", "the", "a", "an", "of", "to", "is", "in", "and", "for", "what", "does", "do", "who", "which",
        "сейчас", "уже", "был", "была", "было", "были", "есть", "мне", "между", "чем", "кто", "какой",
        "какая", "какие", "скажи", "пожалуйста", "он", "она", "оно", "они", "его", "её", "ее", "их", "им",
        "каким", "какого", "какую", "каком", "it", "its", "they", "them",
        # conversational fillers of spoken / dictated Russian — carry no topic
        "слушай", "вообще", "этот", "эта", "это", "тот", "та", "те", "штука", "реально", "вот", "ну", "там",
        "нас", "наш", "наша", "наши", "мы", "ты", "вы", "мой", "моё", "мое", "моя", "можешь", "расскажи"}


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


def build(path: Optional[Path] = None) -> Dict:
    """Rebuild from scratch (atomic: build in a tmp file, then os.replace)."""
    path = Path(path or default_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".building")
    if tmp.exists():
        tmp.unlink()
    conn = sqlite3.connect(str(tmp))
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
                  else _chunks(clean))
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
           "sources_digest": digest.hexdigest()[:16], "schema": "studio-os/memory-index/1"}
    for k, v in man.items():
        conn.execute("INSERT INTO manifest VALUES (?,?)", (k, json.dumps(v)))
    conn.commit()
    conn.close()
    os.replace(tmp, path)
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


#: Question/intent words: they shape the query but must not dominate the ranking.
WEAK = {"почему", "зачем", "why", "причина", "reason", "purpose", "цель", "разница", "difference", "отличие",
        "чем", "отличается", "откуда", "where", "what", "кто", "who", "существует", "exists", "exist"}
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
    """Query → concepts: each a set of alternative surface words + stems, a weight, identifier flag."""
    out, seen = [], set()
    for w in _words(q):
        if w in STOP or len(w) < 2:
            continue
        group = _GLOSS_INDEX.get(w) or _GLOSS_INDEX.get(stem(w)) or {w}
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
