#!/usr/bin/env python3
# LLM_FORBIDDEN
"""OWNER-GATE guard — blocks autonomous auto-ship of OWNER-GATED site changes.

The site is push==live (Cloudflare Pages builds landing/ on every push to main).
The autonomous orchestrator may auto-ship SAFE site changes (layout/CSS, component
refactors, non-legal copy, SEO, bugfixes, DYNAMIC number reads), but a protected
set of change-classes must NEVER auto-ship — they route to an owner-decision card:

  A  solicitation language        (.claude/rules/site-copy.md, CLAUDE.md #8)
  B  displayed APY/yield NUMBERS  (owner-gated)
  C  tier NAMING + "SPA" brand expansion (owner-gated)
  D  legal / disclaimer copy      (owner-gated)
  E  APY-honesty tokens REMOVED   (evidence L0-L6, tail-always-visible)

Detection substrates
--------------------
  * Structured JSON (landing/src/lib/tier_bands.json, landing/src/data/track_snapshot.json):
    parse OLD vs NEW and field-diff — robust, no regex guessing.
  * Free copy (.astro/.jsx/.ts/.html): bilingual EN+RU regex on ADDED / REMOVED
    diff-hunk lines only.

Custodian exemption (not forgeable) — THREE outcomes, not two
-------------------------------------------------------------
  track_snapshot.json is legitimately auto-updated by deploy_site_snapshot.py. We do
  NOT trust the commit message. Instead: regenerate the snapshot from the committed
  data/ canon (scripts/generate_track_snapshot.py) and compare (ignoring the volatile
  generated_at). Byte-equivalent → deterministic custodian output → EXEMPT. A hand
  edited number will not match regeneration → GATED.

  The measurement is only POSSIBLE where the data/ canon is fresh enough to describe
  the snapshot being judged — i.e. the pre-push self-check on the owner's machine.
  In CI it is not: `data/equity_curve_daily.json` on origin is frozen far behind the
  live track (measured 2026-08-19: canon as_of 2026-07-04 vs snapshot as_of 2026-08-19),
  so regeneration reproduces an OLD snapshot and a mismatch proves nothing about who
  wrote the file. Until 2026-08-19 that third outcome had no name: `git-range` mode
  hardcoded `exempt=False` and every `except` returned `False`, so "I could not measure"
  was reported as "I proved a violation". Cost, re-measured 2026-08-19 over all 221 runs
  since 2026-07-15: 109 red, 106 of them (97.2 %) our own `chore(site-custodian)`
  auto-deploy — ~10 red runs a day. The 3 informative reds are indistinguishable from
  that noise.

  Now: True = proved custodian · False = proved NOT custodian · None = NOT MEASURABLE
  here, with the reason named. `None` grants NO exemption (fail-CLOSED, exit code
  unchanged) — it only stops a failed measurement from masquerading as a verdict.
  Whether an unmeasurable exemption may ship is an OWNER decision (ADR-078: site
  numbers stay with the owner) — see `_snapshot_self_consistency` for the measured
  alternative prepared for that decision.

Owner-approval bypass
---------------------
  A change touching a gated class ships only if the push carries a commit trailer
  `Owner-Approved: own-NN` AND that card exists with status: owner-done (owner-only —
  spa_core.owner_queue enforces it) AND its `approves:` scope covers the violations.

Design: pure stdlib, deterministic, no LLM (# LLM_FORBIDDEN). Reads read-only; writes
only data/owner_gate_check.json (gitignored) when --report.

Exit: 0 clean · 2 owner-gated violation(s) · 1 tool/IO error.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# 2026-08-08: логгер добавлен вместе с починкой обхода. До этого модуль не имел
# ни одной строки диагностики — поэтому «обход не сработал» и «обход упал»
# выглядели снаружи одинаково, и дефект прожил незамеченным с первого дня.
log = logging.getLogger("spa.owner_gate")

# ── which paths are in scope (the deploy surface) ───────────────────────────
_SITE_PREFIX = "landing/"
_TIER_BANDS = "landing/src/lib/tier_bands.json"
_TRACK_SNAPSHOT = "landing/src/data/track_snapshot.json"

# Legal pages — ANY diff touching these is Class D (path-based).
_LEGAL_PATHS = frozenset(
    {
        "landing/src/components/Disclaimer.astro",
        "landing/src/pages/disclaimer.astro",
        "landing/src/pages/risk-disclosure.astro",
    }
)

# tier_bands.json per-tier field taxonomy.
_TB_NUMBER_FIELDS = (  # Class B — displayed yield/drawdown numbers
    "band_en", "band_ru", "nav_band_en", "nav_band_ru",
    "dd_short_en", "dd_short_ru", "tail_en", "tail_ru",
)
_TB_IDENTITY_FIELDS = ("key", "en", "ru", "alt_en", "alt_ru")  # Class C — naming
_TB_EVIDENCE_FIELDS = ("evidence_en", "evidence_ru")  # Class E — honesty tokens

# track_snapshot.json numeric fields (Class B).
_TS_NUMBER_FIELDS = (
    "nav_usd", "end_equity", "paper_apy_pct", "max_drawdown_pct",
    "gates_passed", "gates_total", "real_track_days",
)

# ── Стоящее одобрение владельца (ADR-116, 2026-08-22, фаза стройки) ────────
# Классы, которые уезжают в live без карточки владельцу. РОВНО названные им:
# B — числа доходности, D — legal-файлы. Пустой frozenset() = одобрение отозвано.
_STANDING_APPROVED_KLASSES = frozenset({"B", "D"})
_STANDING_APPROVAL_ADR = "ADR-116"

# ── regexes (compiled once) ─────────────────────────────────────────────────
# Class A — solicitation (active-offer phrasing). EN + RU.
_RE_SOLICIT = re.compile(
    r"minimum\s+(?:investment|deposit|to\s+invest)"
    r"|withdrawals?\s+within\s+\d+\s+days?"
    r"|no\s+lock[-\s]?up"
    r"|fee\s+after\s+kyc"
    r"|guaranteed\s+returns?"
    r"|минимальн\w+\s+(?:сумма|вклад|инвест)"
    r"|вывод\w*\s+(?:в\s+течени[ие]|за)\s+\d+\s+дн"
    r"|без\s+блокировк"
    r"|комисси\w+\s+после\s+kyc"
    r"|гарантированн\w+\s+(?:доход|прибыл)",
    re.IGNORECASE,
)
# Class B — a percent literal next to a yield keyword (a BAKED number, not a read).
_RE_YIELD_NUMBER = re.compile(
    r"(?:up\s+to|net|apy|yield|годовых|доходност)\D{0,12}\d{1,3}(?:\.\d+)?\s*%"
    r"|\d{1,3}(?:\.\d+)?\s*%\s*(?:net\s+)?apy",
    re.IGNORECASE,
)
# A dynamic read (snap.paper_apy_pct, {apy}, toFixed) — NOT a baked literal. Suppresses B.
_RE_DYNAMIC = re.compile(
    r"snap\.|initialFacts|\{[^}]*(?:apy|pct|nav|equity|yield|days|gates)[^}]*\}"
    r"|\.toFixed\(|fmtPct|fmtUsd|f\.[a-z_]+|props\.",
    re.IGNORECASE,
)
# The dynamic-read exemption is applied per MATCH SPAN, not per whole line: only a
# dynamic token WITHIN this many chars of a baked percent suppresses it. A wider (line-
# level) suppressor let a hardcoded "30% net APY" ship whenever any unrelated dynamic
# token ({snap.x}, props.) sat elsewhere on the same line — a fail-OPEN. Kept small so an
# adjacent `{apy}%` / `.toFixed()%` read is still exempt but a distant literal still gates.
_DYNAMIC_WINDOW = 6
# Class C — a "SPA" brand expansion that differs from canon.
_CANON_SPA_EXPANSION = "smart passive aggregator"
_RE_SPA_EXPANSION = re.compile(
    r"\bSPA\b[^\n]{0,24}?\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\s+([A-Z][a-z]+)\b"
    r"|\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\s+([A-Z][a-z]+)\b[^\n]{0,8}?\(SPA\)",
)
# Class D legal copy is protected PATH-BASED (the legal files in _LEGAL_PATHS). We do
# NOT scan free text for legal phrases: "not investment advice" / "paper / research"
# appear in ordinary marketing prose, so a content detector over-gates every copy
# refactor into an owner card — noise that makes auto-ship useless. The disclaimer text
# itself lives in Disclaimer.astro / the legal pages, which the path rule already gates.
#
# Class E — honesty tokens. Narrow to the SPECIFIC evidence labels (level + refused-for-
# live). Tier drawdown/tail budgets live in tier_bands.json and are field-diffed (Class E
# there), so we do NOT gate on the generic word "drawdown/просадка" in free prose.
_RE_EVIDENCE_TOKEN = re.compile(
    r"\bL[0-6]\b\s*·"
    r"|refused\s+for\s+live|для\s+live\s+отказан",
    re.IGNORECASE,
)


# ── diff acquisition ────────────────────────────────────────────────────────
def _git(args: list[str], cwd: Path) -> str:
    out = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True
    )
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


def _changed_paths_and_hunks(
    diff_text: str,
) -> tuple[list[str], dict[str, list[tuple[str, int, str]]]]:
    """Parse `git diff --unified=0` → (changed paths, {path: [(sign,line,text)]}).

    sign is '+' or '-'. line is the NEW-file line for '+', OLD-file line for '-'.
    """
    paths: list[str] = []
    hunks: dict[str, list[tuple[str, int, str]]] = {}
    cur: str | None = None
    old_ln = new_ln = 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ b/"):
            cur = raw[6:].strip()
            if cur == "/dev/null":
                cur = None
            elif cur not in hunks:
                paths.append(cur)
                hunks[cur] = []
        elif raw.startswith("--- ") or raw.startswith("diff --git"):
            continue
        elif raw.startswith("@@"):
            m = re.search(r"-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?", raw)
            if m:
                old_ln = int(m.group(1))
                new_ln = int(m.group(2))
        elif cur is not None and raw.startswith("+") and not raw.startswith("+++"):
            hunks[cur].append(("+", new_ln, raw[1:]))
            new_ln += 1
        elif cur is not None and raw.startswith("-") and not raw.startswith("---"):
            hunks[cur].append(("-", old_ln, raw[1:]))
            old_ln += 1
        else:
            old_ln += 1
            new_ln += 1
    return paths, hunks


def _blob(ref: str, path: str, cwd: Path) -> str | None:
    """Content of `path` at git `ref` (or None if absent)."""
    out = subprocess.run(
        ["git", "show", f"{ref}:{path}"], cwd=str(cwd), capture_output=True, text=True
    )
    return out.stdout if out.returncode == 0 else None


def _acquire(
    mode: str, base: str | None, head: str | None, files: list[str] | None, repo: Path
):
    """Return (diff_text, old_ref) for the chosen mode. old_ref names the baseline
    used for JSON field-diff of structured files."""
    if mode == "git-range":
        b = base or "HEAD~1"
        h = head or "HEAD"
        return _git(["diff", "--unified=0", b, h], repo), b
    if mode == "worktree":
        return _git(["diff", "--unified=0", "origin/main", "--", "landing/"], repo), "origin/main"
    if mode == "files":
        # Compare each given local file against origin/main; synthesize a diff.
        parts: list[str] = []
        for f in files or []:
            rel = _rel(f, repo)
            old = _blob("origin/main", rel, repo)
            try:
                new = (repo / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                new = ""
            if old == new:
                continue
            parts.append(_unified(rel, old or "", new))
        return "\n".join(parts), "origin/main"
    raise ValueError(f"unknown diff-mode {mode}")


def _rel(f: str | os.PathLike, repo: Path) -> str:
    p = Path(f)
    try:
        return str(p.resolve().relative_to(repo))
    except ValueError:
        return str(f)


def _unified(rel: str, old: str, new: str) -> str:
    import difflib

    diff = difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"a/{rel}", tofile=f"b/{rel}", n=0,
    )
    return "".join(diff)


# ── JSON field-diff for the two structured sources ──────────────────────────
def _json_at(ref: str, path: str, repo: Path) -> dict[str, Any] | None:
    txt = _blob(ref, path, repo)
    if txt is None:
        return None
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return None


def _tier_bands_violations(old: Any, new: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(new, dict):
        return out
    old = old if isinstance(old, dict) else {}
    for tier in ("conservative", "balanced", "aggressive"):
        o = old.get(tier, {}) if isinstance(old.get(tier), dict) else {}
        n = new.get(tier, {}) if isinstance(new.get(tier), dict) else {}
        if not n:
            continue
        for fld in _TB_NUMBER_FIELDS:
            if o.get(fld) != n.get(fld):
                out.append(_v(_TIER_BANDS, 0, "B", "tier_bands.number",
                              f"{tier}.{fld}: {o.get(fld)!r} → {n.get(fld)!r}"))
        for fld in _TB_IDENTITY_FIELDS:
            if o.get(fld) != n.get(fld):
                out.append(_v(_TIER_BANDS, 0, "C", "tier_bands.naming",
                              f"{tier}.{fld}: {o.get(fld)!r} → {n.get(fld)!r}"))
        for fld in _TB_EVIDENCE_FIELDS:
            # gate if an evidence token disappears / changes
            if o.get(fld) and o.get(fld) != n.get(fld):
                out.append(_v(_TIER_BANDS, 0, "E", "tier_bands.evidence",
                              f"{tier}.{fld}: {o.get(fld)!r} → {n.get(fld)!r}"))
    return out


def _track_snapshot_violations(
    old: Any, new: Any, exempt: bool
) -> list[dict[str, Any]]:
    if exempt:
        return []
    out: list[dict[str, Any]] = []
    if not isinstance(new, dict):
        return out
    old = old if isinstance(old, dict) else {}

    def _walk(o, n, prefix=""):
        if isinstance(n, dict):
            for k, nv in n.items():
                ov = o.get(k) if isinstance(o, dict) else None
                key = f"{prefix}{k}"
                base = k
                if base in _TS_NUMBER_FIELDS or base.endswith(("_pct", "_usd")):
                    if ov != nv and not isinstance(nv, (dict, list)):
                        out.append(_v(_TRACK_SNAPSHOT, 0, "B", "snapshot.number",
                                      f"{key}: {ov!r} → {nv!r}"))
                if isinstance(nv, (dict, list)):
                    _walk(ov if isinstance(ov, (dict, list)) else {}, nv, key + ".")

    _walk(old, new)
    return out


_VOLATILE_SNAPSHOT_FIELDS = frozenset({"generated_at", "as_of_generated", "_generated"})


def _load_generator(repo: Path):
    """Import scripts/generate_track_snapshot.py as a module (import-safe: its writes
    live behind `if __name__ == '__main__'`). Raises on failure — the CALLER decides
    what a failure means, which is the whole point of the tri-state below."""
    import importlib.util

    gen = repo / "scripts" / "generate_track_snapshot.py"
    spec = importlib.util.spec_from_file_location("_gen_ts", gen)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"generator not importable at {gen}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _snapshot_custodian_equivalence(
    repo: Path, current: dict[str, Any] | None = None
) -> tuple[bool | None, str]:
    """Is this track_snapshot.json the deterministic output of the custodian generator?

    Returns (verdict, reason) where verdict is:
      True  — proved custodian output (regeneration from the data/ canon matches)
      False — proved NOT custodian output (regeneration ran, and differs)
      None  — NOT MEASURABLE here, reason named (no generator / no canon / the canon is
              older than the artifact being judged, so regeneration cannot reproduce it)

    `None` is NOT an exemption. It exists so that "I could not measure" stops being
    reported as "I proved a violation" — the distinction the guard lacked until
    2026-08-19 (see the module docstring).
    """
    try:
        mod = _load_generator(repo)
    except Exception as exc:
        return None, f"генератор не импортируется ({type(exc).__name__}) — освобождение нечем проверить"

    try:
        regenerated = mod.build_snapshot()
    except Exception as exc:
        return None, f"регенерация упала ({type(exc).__name__}) — освобождение нечем проверить"

    if current is None:
        try:
            current = json.loads((repo / _TRACK_SNAPSHOT).read_text(encoding="utf-8"))
        except Exception as exc:
            return None, f"снимок не прочитан ({type(exc).__name__}) — сравнивать не с чем"
    if not isinstance(regenerated, dict) or not isinstance(current, dict):
        return None, "снимок или регенерация — не объект JSON, сравнение не определено"

    # The canon must be able to DESCRIBE the artifact under judgement. `as_of` is the date
    # of the last evidenced bar, so a canon whose regeneration lands EARLIER than the
    # committed snapshot is behind the artifact: it reproduces an older track, and the
    # mismatch that follows says nothing about who wrote the file. This is the CI case —
    # data/equity_curve_daily.json on origin lags the live track by design.
    r_as_of, c_as_of = regenerated.get("as_of"), current.get("as_of")
    if isinstance(r_as_of, str) and isinstance(c_as_of, str) and r_as_of < c_as_of:
        return None, (
            f"канон data/ отстаёт от снимка (регенерация as_of={r_as_of}, "
            f"снимок as_of={c_as_of}) — воспроизвести этот снимок каноном НЕЛЬЗЯ"
        )

    a = {k: v for k, v in regenerated.items() if k not in _VOLATILE_SNAPSHOT_FIELDS}
    b = {k: v for k, v in current.items() if k not in _VOLATILE_SNAPSHOT_FIELDS}
    if a == b:
        return True, "регенерация из канона совпала — детерминированный вывод custodian"
    differing = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    return False, "регенерация из канона РАСХОДИТСЯ по полям: " + ", ".join(differing[:8])


def _snapshot_is_custodian_equivalent(repo: Path) -> bool:
    """Back-compat boolean view: EXEMPT or not. `None` (not measurable) grants no
    exemption — fail-CLOSED, exactly as before the tri-state existed."""
    verdict, _ = _snapshot_custodian_equivalence(repo)
    return verdict is True


def _snapshot_self_consistency(
    repo: Path, snap: Any
) -> tuple[bool | None, str, list[dict[str, Any]]]:
    """Do the DISPLAYED numbers agree with the snapshot's OWN `bars`?

    Measurable WITHOUT the data/ canon — i.e. exactly where `_snapshot_custodian_equivalence`
    cannot measure (CI). Recomputes with the generator's OWN arithmetic (imported, never a
    second copy) so there is one definition of each number:

        real_track_days   = number of evidenced bars
        as_of             = date of the last evidenced bar
        paper_apy_pct     = compound-annualized evidenced anchor → latest over real_track_days
        max_drawdown_pct  = generator's _max_drawdown_pct over the evidenced bars
        total_return_pct  = derived from end_equity
        nav_usd           = end_equity (PoR-NAV mirrors it)

    HONEST LIMIT, not hidden: `end_equity`/`nav_usd` come from paper_trading_status.json and
    `gates_passed`/`gates_total` from golive_status.json — neither is a function of `bars`, so
    forging THOSE is invisible to this check, as is forging the `bars` array itself. It covers
    the headline yield (`paper_apy_pct`), the tail (`max_drawdown_pct`) and the track length.

    Returns (verdict, reason, mismatches). None = not measurable, reason named.
    This is a MEASUREMENT ONLY — it does not gate anything (see the module docstring).
    """
    if not isinstance(snap, dict):
        return None, "снимок не прочитан — сверять нечего", []
    bars = snap.get("bars")
    if not isinstance(bars, list) or not bars:
        return None, "в снимке нет массива bars — числа не из чего пересчитать", []
    try:
        mod = _load_generator(repo)
    except Exception as exc:
        return None, f"генератор не импортируется ({type(exc).__name__}) — арифметику взять негде", []

    evidenced = [b for b in bars if isinstance(b, dict) and b.get("evidenced") is True]
    expected: dict[str, Any] = {}

    real_days = len(evidenced)
    if evidenced:
        expected["real_track_days"] = real_days
        expected["as_of"] = evidenced[-1].get("date")
        try:
            expected["max_drawdown_pct"] = mod._max_drawdown_pct(evidenced)
        except Exception:
            pass
        if len(evidenced) >= 2 and real_days > 0:
            try:
                anchor_eq = float(evidenced[0].get("equity") or 0)
                latest_eq = float(evidenced[-1].get("equity") or 0)
                if anchor_eq > 0 and latest_eq > 0:
                    apy = ((latest_eq / anchor_eq) ** (365.0 / real_days) - 1.0) * 100.0
                    expected["paper_apy_pct"] = round(apy, 4)
            except (TypeError, ValueError, ZeroDivisionError, OverflowError):
                pass

    end_equity = snap.get("end_equity")
    if isinstance(end_equity, (int, float)) and not isinstance(end_equity, bool):
        expected["nav_usd"] = round(float(end_equity), 2)
        expected["total_return_pct"] = round((float(end_equity) / 100000.0 - 1.0) * 100.0, 4)

    if not expected:
        return None, "ни одно поле не выводится из этого снимка — сверять нечего", []

    mismatches = [
        {"field": k, "declared": snap.get(k), "recomputed": v}
        for k, v in expected.items()
        if snap.get(k) != v
    ]
    checked = ", ".join(sorted(expected))
    if not mismatches:
        return True, f"числа согласны с собственными bars ({len(expected)}: {checked})", []
    named = ", ".join(
        f"{m['field']}: заявлено {m['declared']!r} против пересчитанного {m['recomputed']!r}"
        for m in mismatches
    )
    return False, f"числа РАСХОДЯТСЯ с собственными bars — {named}", mismatches


# ── free-text scan ──────────────────────────────────────────────────────────
def _v(file: str, line: int, klass: str, rule: str, matched: str,
       change: str = "") -> dict[str, Any]:
    return {"file": file, "line": line, "klass": klass, "rule": rule,
            "change": change, "matched_text": matched[:200]}


def _scan_free_text(
    path: str, hunk_lines: list[tuple[str, int, str]]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    is_legal_path = path in _LEGAL_PATHS
    for sign, line, text in hunk_lines:
        # Class D — path-based: any change to a legal file gates.
        if is_legal_path:
            out.append(_v(path, line, "D", "legal.path",
                          text.strip(), "added" if sign == "+" else "removed"))
            continue
        if sign == "+":
            if _RE_SOLICIT.search(text):
                out.append(_v(path, line, "A", "solicitation", text.strip(), "added"))
            for m in _RE_YIELD_NUMBER.finditer(text):
                window = text[max(0, m.start() - _DYNAMIC_WINDOW): m.end() + _DYNAMIC_WINDOW]
                if not _RE_DYNAMIC.search(window):
                    out.append(_v(path, line, "B", "yield.number.literal", text.strip(), "added"))
                    break
            m = _RE_SPA_EXPANSION.search(text)
            if m and " ".join(g for g in m.groups() if g).lower() != _CANON_SPA_EXPANSION:
                out.append(_v(path, line, "C", "spa.expansion", text.strip(), "added"))
        elif sign == "-":
            # Class E — removing a specific honesty/evidence token.
            if _RE_EVIDENCE_TOKEN.search(text):
                out.append(_v(path, line, "E", "honesty.token.removed", text.strip(), "removed"))
    return out


# ── owner-approval bypass ───────────────────────────────────────────────────
def _approved_scope(commit_message: str | None, repo: Path) -> dict[str, Any] | None:
    """If the commit message carries a valid `Owner-Approved: own-NN` trailer whose
    card is owner-done, return {card, approves:[...]}; else None. Never self-approvable
    by the orchestrator (owner-done is owner-only, enforced in spa_core.owner_queue)."""
    if not commit_message:
        return None
    # ЧЕТВЁРТАЯ поломка того же механизма (замер 2026-08-09, цикл #171): шаблон
    # принимал только `own-…` / `Q-OWN-…`, а карточки, которые заводит САМ гейт
    # (`safe_site_push._route_to_owner_card` → `create_card(tracker_type=
    # "owner-decision")`), называются `owner-decision-…`. На «own» шаблон требовал
    # сразу дефис, получал «e» — и ни одна машинная карточка не могла быть
    # предъявлена как одобрение. Производитель и потребитель идентификатора не
    # совпадали НИКОГДА. `owner-decision` стоит первым: иначе альтернатива `own`
    # съедает префикс и всё выражение снова не совпадает.
    m = re.search(r"Owner-Approved:\s*((?:owner-decision|own|Q-OWN)-\S+)",
                  commit_message, re.IGNORECASE)
    if not m:
        return None
    card_id = m.group(1).strip()
    try:
        from spa_core.owner_queue.queue import load_card, list_cards  # type: ignore
    except Exception as exc:  # noqa: BLE001
        log.warning("owner-gate bypass: очередь карточек недоступна (%s) — обхода нет", exc)
        return None
    card = None
    try:
        # 2026-08-08 (решение владельца, вариант А карточки
        # `owner-decision-zapasnoi-klyuch-k-zaschite-saita-ne-rabo`).
        # ЗДЕСЬ БЫЛА ОПЕЧАТКА: звали `card_type=`, а параметр называется
        # `tracker_type`. Вызов падал TypeError, TypeError молча проглатывался
        # соседним `except Exception`, и обход НЕ РАБОТАЛ НИКОГДА — с первого дня.
        # Опасного не произошло (замок был ЗАКРЫТ), но инструкция обещала
        # владельцу механизм, которого не существовало.
        for c in list_cards(tracker_type="owner-decision"):
            cid = str(getattr(c, "id", "") or getattr(c, "name", ""))
            if card_id.lower() in cid.lower() or cid.lower() in card_id.lower():
                card = c
                break
    except Exception as exc:  # noqa: BLE001
        # Молчаливое проглатывание убрано: сбой проверки обязан быть СЛЫШЕН.
        # Именно немота и позволила дефекту прожить незамеченным.
        log.warning("owner-gate bypass: поиск карточки %s упал (%s) — обхода нет",
                    card_id, exc)
        card = None
    if card is None:
        log.info("owner-gate bypass: карточка %s не найдена — обхода нет", card_id)
        return None
    status = str(getattr(card, "status", "") or "").lower()
    if status != "owner-done":
        log.info("owner-gate bypass: карточка %s в статусе %r, а не owner-done — обхода нет",
                 card_id, status)
        return None
    # ТРЕТЬЯ поломка того же механизма (замер 2026-08-09, цикл #171): читалось
    # несуществующее поле. `Card` (spa_core/owner_queue/queue.py) хранит прочие
    # ключи frontmatter в `fields`, атрибута `frontmatter` у него НЕТ — значит
    # `getattr(..., {})` возвращал пустой словарь ВСЕГДА, scope выходил пустым, и
    # ветка обхода не выполнялась ни разу. Снаружи это неотличимо от «владелец не
    # одобрял»: тот же класс fail-OPEN-по-форме, что две половины, починенные
    # 2026-08-08 по решению владельца (вариант А,
    # `owner-decision-zapasnoi-klyuch-k-zaschite-saita-ne-rabo`).
    fm = getattr(card, "fields", None) or getattr(card, "frontmatter", None) or {}
    approves = _parse_approves(fm.get("approves"))
    if not approves:
        # Молчать здесь нельзя: карточка ОДОБРЕНА владельцем, но не разрешает
        # ничего. Отказ верный (fail-CLOSED), а вот немота — нет: именно она
        # прятала все предыдущие поломки этого механизма.
        log.warning(
            "owner-gate bypass: карточка %s одобрена (owner-done), но поле `approves:` "
            "пусто или отсутствует — обход не открыт НИ НА ОДИН файл", card_id,
        )
    return {"card": card_id, "approves": approves}


def _parse_approves(raw) -> list[str]:
    """`approves:` из карточки → СПИСОК путей/классов.

    Вторая половина поломки 2026-08-08: список читался как одна сплошная строка.
    Починить только опечатку значило бы поменять «молча не работает» на «молча
    работает НЕ ТАК» — и второе хуже, потому что тогда обход открывался бы не на
    те файлы. Поэтому чинятся обе половины или ни одной.

    Принимаются обе формы записи: YAML-список и строка через запятую/перевод
    строки. Пустые куски отбрасываются — пустая строка не должна превращаться
    в разрешение на пустой путь.
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        items = [str(x) for x in raw]
    else:
        items = re.split(r"[,\n;]+", str(raw))
    return [s.strip().strip("'\"") for s in items if str(s).strip().strip("'\"")]


# ── main check ──────────────────────────────────────────────────────────────
def check_owner_gate(
    diff_mode: str = "worktree",
    base: str | None = None,
    head: str | None = None,
    files: Iterable[str] | None = None,
    commit_message: str | None = None,
    repo_root: str | os.PathLike | None = None,
) -> dict[str, Any]:
    repo = Path(repo_root) if repo_root is not None else _REPO_ROOT
    flist = [str(f) for f in files] if files else None

    diff_text, old_ref = _acquire(diff_mode, base, head, flist, repo)
    paths, hunks = _changed_paths_and_hunks(diff_text)
    site_paths = [p for p in paths if p.startswith(_SITE_PREFIX)]

    violations: list[dict[str, Any]] = []
    custodian_exemption: dict[str, Any] | None = None
    self_consistency: dict[str, Any] | None = None

    # Structured JSON field-diff.
    if _TIER_BANDS in site_paths:
        old = _json_at(old_ref, _TIER_BANDS, repo)
        new = _json_at("WORKTREE", _TIER_BANDS, repo) if diff_mode != "git-range" \
            else _json_at(head or "HEAD", _TIER_BANDS, repo)
        if new is None:
            try:
                new = json.loads((repo / _TIER_BANDS).read_text(encoding="utf-8"))
            except Exception:
                new = None
        violations.extend(_tier_bands_violations(old, new))

    if _TRACK_SNAPSHOT in site_paths:
        old = _json_at(old_ref, _TRACK_SNAPSHOT, repo)
        # `new` must mean the same thing as it does for tier_bands above: in git-range mode
        # the subject of judgement is the COMMITTED head, not whatever the working tree holds.
        if diff_mode == "git-range":
            new = _json_at(head or "HEAD", _TRACK_SNAPSHOT, repo)
        else:
            new = None
        if new is None:
            try:
                new = json.loads((repo / _TRACK_SNAPSHOT).read_text(encoding="utf-8"))
            except Exception:
                new = _json_at(head or "HEAD", _TRACK_SNAPSHOT, repo)

        # Measure in EVERY mode. Where the canon cannot describe the artifact the answer
        # comes back None ("not measurable") instead of the old hardcoded False ("violation").
        exempt_verdict, exempt_reason = _snapshot_custodian_equivalence(repo, new)
        custodian_exemption = {
            "state": {True: "proved", False: "disproved", None: "unmeasured"}[exempt_verdict],
            "reason": exempt_reason,
        }
        consistent, consistency_reason, consistency_mismatches = _snapshot_self_consistency(repo, new)
        self_consistency = {
            "state": {True: "consistent", False: "inconsistent", None: "unmeasured"}[consistent],
            "reason": consistency_reason,
            "mismatches": consistency_mismatches,
        }

        # `None` grants NO exemption — fail-CLOSED, exit code unchanged. It is recorded on
        # each finding so "proved violation" and "could not prove innocence" stop reading alike.
        snapshot_violations = _track_snapshot_violations(old, new, exempt_verdict is True)
        if exempt_verdict is None:
            snapshot_violations = [
                {**v, "exemption_unmeasured": True, "exemption_reason": exempt_reason}
                for v in snapshot_violations
            ]
        violations.extend(snapshot_violations)

    # Free-text scan (skip the two structured files — handled above).
    for p in site_paths:
        if p in (_TIER_BANDS, _TRACK_SNAPSHOT):
            continue
        violations.extend(_scan_free_text(p, hunks.get(p, [])))

    # ── Стоящее одобрение владельца (ADR-116, решение 2026-08-22) ──────────
    # Дословно: «я бы хотел чтобы цифры и юр вопросы пока мы строим на сайте
    # менялись без этого вопроса, я разрешаю». На фазе стройки классы B (числа)
    # и D (legal-файлы) уезжают в live БЕЗ карточки владельцу. Находки НЕ
    # исчезают — они переезжают в report["standing_approved"] (видимость без
    # гейта). A (solicitation), C (нейминг/расшифровка SPA) и E (honesty-токены)
    # владелец НЕ называл — они gated как прежде: снятие A до legal-clearance —
    # прямой юридический риск, E прячет paper под live. Отзыв — словом владельца
    # или go-live (тогда этот блок удаляется, тест держит обе стороны).
    standing: list[dict[str, Any]] = []
    if _STANDING_APPROVED_KLASSES:
        ce_state = (custodian_exemption or {}).get("state") \
            if isinstance(custodian_exemption, dict) else None
        kept_v = []
        for v in violations:
            in_standing = v["klass"] in _STANDING_APPROVED_KLASSES
            # Граница одобрения: владелец разрешил числам МЕНЯТЬСЯ без вопроса,
            # а не подделываться. ДОКАЗАННАЯ ручная правка снимка трека
            # (custodian DISPROVED — рука написала число, которого генератор не
            # выдавал) остаётся gated: это APY-честность (инв. #8), её он не
            # снимал. Недоказуемость (unmeasured, канон отстал в CI/worktree) —
            # штатный шум стройки, он и уезжает по стоящему одобрению.
            if (in_standing and v.get("rule") == "snapshot.number"
                    and ce_state == "disproved"):
                in_standing = False
            if in_standing:
                standing.append({**v, "standing_approved_by": _STANDING_APPROVAL_ADR})
            else:
                kept_v.append(v)
        violations = kept_v

    # Owner-approval bypass — drop violations covered by an owner-done card scope.
    approval = _approved_scope(commit_message, repo)
    bypassed: list[dict[str, Any]] = []
    if approval and approval.get("approves"):
        scope = approval["approves"]
        scope_files = {s for s in scope if "/" in str(s)}
        scope_klass = {str(s).upper() for s in scope if len(str(s)) == 1}
        kept = []
        for v in violations:
            if v["file"] in scope_files or v["klass"] in scope_klass:
                v = {**v, "bypassed_by": approval["card"]}
                bypassed.append(v)
            else:
                kept.append(v)
        violations = kept

    violations.sort(key=lambda d: (d["file"], d["line"], d["klass"]))
    unmeasured_count = sum(1 for v in violations if v.get("exemption_unmeasured"))
    return {
        "model": "owner_gate_check",
        "llm_forbidden": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "diff_mode": diff_mode,
        "ok": len(violations) == 0,
        "gated_count": len(violations),
        # How many of the gated findings are "could not prove innocence" rather than
        # "proved guilt". Kept SEPARATE from gated_count on purpose: the exit code does
        # not change, so nothing ships differently — but the two are no longer one number.
        "unmeasured_count": unmeasured_count,
        "custodian_exemption": custodian_exemption,
        "self_consistency": self_consistency,
        "site_paths": sorted(site_paths),
        "violations": violations,
        "approved_bypasses": bypassed,
        "approval": approval,
        # ADR-116: находки, уехавшие по стоящему одобрению владельца. Видимость
        # без гейта: они НЕ в gated_count, но и не исчезли из отчёта.
        "standing_approved": standing,
        "standing_approval_adr": _STANDING_APPROVAL_ADR if standing else None,
    }


def _write_report(report: dict[str, Any], repo: Path) -> Path:
    dst = repo / "data" / "owner_gate_check.json"
    try:
        from spa_core.utils.atomic import atomic_save

        atomic_save(report, str(dst))
        return dst
    except Exception:
        import tempfile
        import shutil

        dst.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(dst.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
        shutil.move(tmp, str(dst))
        return dst


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Owner-gate guard (auto-ship safety).")
    ap.add_argument("--diff-mode", choices=("git-range", "files", "worktree"),
                    default="worktree")
    ap.add_argument("--base")
    ap.add_argument("--head")
    ap.add_argument("--files", nargs="*")
    ap.add_argument("--commit-message", default=None)
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv)

    try:
        report = check_owner_gate(
            diff_mode=args.diff_mode, base=args.base, head=args.head,
            files=args.files, commit_message=args.commit_message,
        )
    except Exception as exc:  # tool/IO error
        print(f"owner-gate: ERROR {exc}", file=sys.stderr)
        return 1

    print("=== Owner-gate guard (auto-ship safety) ===")
    print(f"  diff-mode: {report['diff_mode']} · site paths: {len(report['site_paths'])}")
    for v in report["violations"]:
        mark = " [НЕ ИЗМЕРЕНО]" if v.get("exemption_unmeasured") else ""
        print(f"    [{v['klass']}]{mark} {v['file']}:{v['line']} {v['rule']} "
              f"({v['change']}) — {v['matched_text']}")
    ce = report.get("custodian_exemption")
    if ce:
        label = {"proved": "ДОКАЗАНО (вывод custodian)",
                 "disproved": "ОПРОВЕРГНУТО (не вывод custodian)",
                 "unmeasured": "НЕ ИЗМЕРЕНО"}[ce["state"]]
        print(f"  освобождение custodian: {label} — {ce['reason']}")
    sc = report.get("self_consistency")
    if sc:
        label = {"consistent": "СОГЛАСНЫ", "inconsistent": "РАСХОДЯТСЯ",
                 "unmeasured": "НЕ ИЗМЕРЕНО"}[sc["state"]]
        print(f"  сверка чисел с собственными bars: {label} — {sc['reason']}")
    if report["approved_bypasses"]:
        print(f"  owner-approved bypasses: {len(report['approved_bypasses'])} "
              f"(card {report['approval']['card']})")
    if report.get("standing_approved"):
        print(f"  стоящее одобрение владельца ({report['standing_approval_adr']}): "
              f"{len(report['standing_approved'])} находок класса B/D уехали без карточки")

    if args.report:
        dst = _write_report(report, _REPO_ROOT)
        print(f"  report → {dst}")

    if report["ok"]:
        print("  RESULT: CLEAN — no owner-gated changes; safe to auto-ship.")
        return 0
    print(f"  RESULT: GATED — {report['gated_count']} owner-gated change(s) → route to owner card.")
    if report.get("unmeasured_count"):
        # Deliberately NOT a different exit code: whether an unmeasurable exemption may
        # ship is the owner's decision (ADR-078), not this cycle's. Said out loud so the
        # red is readable instead of merely repeated.
        print(f"      из них НЕ ИЗМЕРЕНО (освобождение здесь недоказуемо): "
              f"{report['unmeasured_count']} — код возврата НЕ смягчён")
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
