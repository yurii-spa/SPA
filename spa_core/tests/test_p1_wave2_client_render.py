"""P1 Wave 2 r3 (2026-10-10): the estimated annualised equivalent is never called «realized».

The defect ARB found: /snapshot's CLIENT script printed «~4,85 % (оценочный годовой эквивалент …)
реализованных» — the label said «estimate», the next word said «measured». A static scan of the built
HTML cannot see it (the text is assembled in the browser), so the class is held two ways:

1. Source guard (runs everywhere, deterministic): no landing source places a «realized»-class word
   right after/before a variable or call that prints the estimate (realizedApyQualified and the names
   pages bind it to: rrEn/rrRu, realizedNumEn/realizedNumRu, RLBL/RTXT on /snapshot). Positive control:
   every original defect quote is matched.
2. Rendered check (headless Chrome via CDP, scripts/check_rendered_estimate_label.py): /snapshot
   initial open, finishing the quiz, a different amount, EN→RU and RU→EN switch, plus the pages that
   carried the defect, in both locales — read as document.body.innerText AFTER client scripts ran.
   It needs Chrome and a built landing/dist; without them the test SKIPS WITH THE NAMED REASON
   (not measured ≠ passed).
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "landing" / "src"
DIST = ROOT / "landing" / "dist"
SCRIPT = ROOT / "scripts" / "check_rendered_estimate_label.py"

_EST_NAMES = r"(?:realizedNum(?:En|Ru)|rr(?:En|Ru)|RLBL|RTXT|realizedApyQualified\([^)]*\)|realizedLabelRR\([^)]*\))"
_WORD = r"(?:realized|реализованн|фактическ)"
# the estimate token, its closing template/concat punctuation, then (optionally «годовых»/«annualised»)
# a realized-class word — or that word right before the token.
GUARD_AFTER = re.compile(_EST_NAMES + r"[}'\"+\s]{0,6}(?:\s*(?:годовых|annualised|a year,?)\s*)?\s*" + _WORD, re.I)
GUARD_BEFORE = re.compile(_WORD + r"\w*[\s,:«\"'~+${(]{0,8}" + _EST_NAMES, re.I)

# Positive controls: the exact pre-fix source lines (112d43b39) — each MUST be caught.
ORIGINAL_DEFECTS = [
    "('Консервативный тир: T1/T2 стейбл-кредитование, ~'+RLBL+' реализованных, '+DDT+' (бумажный трек",
    "('The Conservative tier: T1/T2 stablecoin lending, ~'+RLBL+' realized, '+DDT+' (paper;",
    "data-ru={`Наш консервативный бумажный трек даёт ${realizedNumRu} реализованных при ${ddPctRu} просадки",
    "Our conservative paper track runs at {realizedNumEn} realized with {ddPctEn} drawdown",
    "погоня за 15,00 % несёт свой хвост; ${realizedNumRu} годовых фактических на бумаге — с начала трека",
    "trade-off: chasing 15.00% carries its tail; {realizedNumEn} annualised realized on paper (track-to-date",
    "Консервативная планка «${realizedNumRu} фактических на бумаге»",
    'The conservative "{realizedNumEn} realized on paper" baseline',
    "its measured result is ${rrEn} a year, realized on paper to date.",
    "Conservative (unlevered lending, ${rrEn} realized paper result${rrNoteEn})",
    "what an honest {realizedNumEn} realized track actually looks like.",
    "(исследовательская цель до 6,00 %, ${realizedNumRu} годовых фактических на бумаге)",
    "research target up to 6.00%, {realizedNumEn} annualised realized on paper",
    "conservative book — ${realizedNumEn} realized track-to-date.`}",
]


def _hits(text):
    return [m.group(0) for m in GUARD_AFTER.finditer(text)] + [m.group(0) for m in GUARD_BEFORE.finditer(text)]


@pytest.mark.parametrize("quote", ORIGINAL_DEFECTS)
def test_guard_catches_every_original_defect(quote):
    assert _hits(quote), f"guard is blind to the original defect: {quote!r}"


def test_guard_does_not_flag_the_period_return_phrase():
    # «фактически на бумаге» belongs to the MEASURED period return (realizedPhrase), not to the estimate.
    ok = "Conservative (кредитование без плеча, фактический бумажный результат ${realizedRu})"
    assert not _hits(ok)


def test_no_landing_source_calls_the_estimate_realized():
    found = []
    for f in sorted(SRC.rglob("*")):
        if f.suffix not in (".astro", ".jsx", ".js", ".ts", ".tsx") or not f.is_file():
            continue
        text = f.read_text(encoding="utf-8")
        for h in _hits(text):
            found.append(f"{f.relative_to(ROOT)}: {h[:120]}")
    assert not found, "the estimate is called realized:\n" + "\n".join(found)


def test_rendered_text_after_client_scripts():
    chrome = os.environ.get("SPA_CHROME") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not (Path(chrome).exists() or shutil.which(chrome)):
        pytest.skip(f"NOT MEASURED: headless Chrome not found at {chrome} (set SPA_CHROME)")
    if not (DIST / "snapshot" / "index.html").is_file():
        pytest.skip("NOT MEASURED: landing/dist not built (run `npm run build` in landing/)")
    out = Path(os.environ.get("TMPDIR", "/tmp")) / f"spa_render_{os.getpid()}.json"
    r = subprocess.run([sys.executable, str(SCRIPT), str(DIST), str(out)], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-2000:]
    rep = json.loads(out.read_text(encoding="utf-8"))
    snap = rep["snapshot"]
    assert all(x["quiz_ok"] and x["quiz2_ok"] and x["switch_ok"] and x["switch_back_ok"] for x in snap), snap
    assert all(x["result_start"]["amounts"] and x["result_start"]["has_label"] for x in snap)
    assert rep["snapshot_rerenders_on_language_switch"] is True
    bad = [f for x in snap for k in ("result_start", "result_after_switch", "result_switch_back", "result_other_amount")
           for f in x[k]["findings"]] + [f for x in snap for f in x["initial_findings"]] \
        + [(p["path"], p["lang"], f) for p in rep["pages"] for f in p["findings"]]
    assert not bad, bad
