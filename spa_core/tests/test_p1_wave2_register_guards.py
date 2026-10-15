"""P1 Wave 2 register guards (2026-10-08) — one regression guard per closed P1 of the independent review.

Register: the W2 independent review found 17 P1 public-truth defects (stale go-live date, legal gate
missing, «Gnosis Safe is used», solicitation copy on /packages, hand-typed protocol lists with Spark /
Morpho-as-T1, the 30-day gate shown open at 107/30, «Live Strategies», «live capital», a hedged book we
do not run, «~0.00% over the same year», a backtest labelled «realized», two different Aggressive tails).

Each guard has two sides, so it cannot pass vacuously:
  * the defect's ORIGINAL wording matches the guard's pattern (positive control on the quote itself);
  * the pattern is absent from every file under ``landing/src`` (the generation source, not one page).
Where the fix moved a sentence onto a generator (book_exposure.js, golive_label.js), the generator is
run by real ``node`` against a fixture and its OUTCOME is checked; ``node`` absent ⇒ a loud
«НЕ ИЗМЕРЕНО» failure, never a skip (lesson pyflakes, cycle #465).
"""
# FROZEN-DATE-OK: historical-incident — the literal dates are verbatim quotes of the 2026-10-08 defects and a
# fixture snapshot whose own as_of is the clock goLiveLabel judges by; nothing compares against the wall clock.
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "landing" / "src"
LIB = SRC / "lib"

# id → (pattern, the defect's original quote from the review — the pattern must match it)
GUARDS = {
    "P1-1": (r"July 21, 2026|21 июля 2026", "The target go-live date is approximately July 21, 2026"),
    "P1-2": (r"after confirmed 30-day verified track|подтверждённого верифицированного трека в 30 дней",
             "Go-live: real capital deployment after confirmed 30-day verified track"),
    # P1-2b (found 09.10 on the final build): zero AUTOMATED blockers was printed as «no open blockers»
    # while live capital still needs an owner decision and a legal review.
    "P1-2b": (r"no open blockers|открытых блокеров нет",
              "29 / 29 100 % criteria pass — no open blockers"),
    "P1-3": (r"Gnosis Safe \(multisig\) is used|Используется Gnosis Safe",
             "A Gnosis Safe (multisig) is used — no transaction goes through"),
    "P1-4": (r"Join early-access|ранний доступ, чтобы войти|what you are buying|Want the validation report first",
             "Join early-access to get in the day it clears."),
    "P1-5": (r"Aave, Compound, Morpho, Spark", "T1/T2 stablecoin lending — Aave, Compound, Morpho, Spark."),
    "P1-6": (r"and 30 evidenced track-days|30 evidenced-дней трека",
             "custody, audit, legal, and 30 evidenced track-days — are owner-only"),
    "P1-7": (r"The track is THIN\.|Трек ТОНКИЙ|THIN \(accruing to 30\)", "the track is THIN (accruing to 30)"),
    "P1-8": (r"The track is THIN</strong> — accruing to 30", "The track is THIN</strong> — accruing to 30"),
    "P1-9": (r"Compare with Live Strategies|14\.00–28\.00% APY|Capital-preservation · T1 only",
             "Compare with Live Strategies"),
    "P1-10": (r"The desk's live capital is|Живой капитал деска",
              "The desk's live capital is conservative stablecoin lending"),
    "P1-11": (r"delta-hedged carry \(β≈0\)|targets ±0\.50% \(a market-neutral book\)|On a hedged-carry book",
              "the book is stablecoin lending + delta-hedged carry (β≈0)"),
    "P1-12": (r"max-drawdown ~0\.00%|макс\. просадкой? ~0,00", "the same year: max-drawdown ~0.00%"),
    "P1-13": (r"Real book \(~4\.50% T1\)|Реальная книга \(~4,50", "Real book (~4.50% T1)"),
    "P1-14": (r"Ядро деска — Aave/Compound/Morpho/Spark|Четыре протокола ядра деска",
              "Ядро деска — Aave/Compound/Morpho/Spark, ~4,50 % supply APY, Tier 1."),
    "P1-15": (r"realized drawdown <strong>−66|реальная просадка eth_directional|real eth_directional drawdown",
              "real eth_directional drawdown: peak $129,392"),
    "P1-16": (r"lost ~50\.00%|~50\.00% drawdown|~50,00 % на обвале|теряла ~50,00",
              "one book lost ~50.00% through the ETH crash"),
    # Round 2 (ARB 09.10): the estimate is not «actual»; paper is not «live»; no unverified audit
    # claim; no call to allocate capital in the modelled product.
    "R2-1": (r"против фактических бумажных|vs the realized paper|realized paper rate|реализованной paper-ставке|фактическ\w* бумажн\w* ставк",
             "Хвост в цифрах: 15,00 % против фактических бумажных 4,85 % (оценочный годовой эквивалент"),
    "R2-2": (r"live conservative paper track|live paper track|Живой paper-трек|живой бумажный трек|живого бумажного трека|runs live in paper|работает live в paper|live-paper trade-shape|live paper tests|Live paper metrics|Живые бумажные показатели",
             "Our live conservative paper track runs at"),
    "R2-3": (r"multiple independent audits|несколькими независимыми аудитами",
             "SPA monitors only protocols with multiple independent audits, but this does not guarantee safety."),
    "R2-4": (r"only allocate capital that you can afford|Размещайте только тот капитал",
             "You should only allocate capital that you can afford to lose entirely."),
}

_EXT = {".astro", ".js", ".jsx", ".json", ".ts", ".md", ".mdx"}


def _source_files():
    for p in SRC.rglob("*"):
        if p.is_file() and p.suffix in _EXT:
            yield p


def _norm(text: str) -> str:
    return text.replace(" ", " ")


@pytest.mark.parametrize("pid", sorted(GUARDS))
def test_guard_pattern_matches_the_original_defect(pid):
    """Positive control: a guard that cannot see the defect it was written for proves nothing."""
    pat, quote = GUARDS[pid]
    assert re.search(pat, _norm(quote)), f"{pid}: the guard does not match its own defect quote"


@pytest.mark.parametrize("pid", sorted(GUARDS))
def test_defect_is_absent_from_the_generation_source(pid):
    pat, _ = GUARDS[pid]
    rx = re.compile(pat)
    files = list(_source_files())
    assert files, "НЕ ИЗМЕРЕНО: landing/src не найден"
    hits = [str(p.relative_to(ROOT)) for p in files if rx.search(_norm(p.read_text(encoding="utf-8", errors="replace")))]
    assert not hits, f"{pid} returned in: {hits}"


def test_aggressive_tail_is_one_backtest_number_everywhere():
    """P1-16: the Aggressive tail is the eth_directional BACKTEST max drawdown −66.35 % from
    annual_contrast.json (as of 2026-06-25) — the same figure on the band source and in lesson 19,
    and labelled as a backtest in both."""
    bands = json.loads((LIB / "tier_bands.json").read_text(encoding="utf-8"))["aggressive"]
    assert "66.35" in bands["tail_en"] and "BACKTEST" in bands["tail_en"]
    assert "66,35" in bands["tail_ru"] and "БЭКТЕСТ" in bands["tail_ru"]
    lesson = (SRC / "pages" / "academy" / "19-aggressive-lab-annual-contrast.astro").read_text(encoding="utf-8")
    assert "66,30" not in lesson and "−66,35" in _norm(lesson).replace("−66,35 %", "−66,35")


def test_pages_read_the_generators_not_literals():
    """The fixed sentences are wired to the generators, so the next build cannot reintroduce them."""
    wiring = {
        "pages/risk-disclosure.astro": ["goLiveLabel(", "GO_LIVE"],
        "pages/status.astro": ["GO_LIVE.en"],
        "pages/readiness.astro": ["remainingBlockers(", "trackGateSentence("],
        "pages/fundability.astro": ["trackGateSentence("],
        "pages/competitive-position.astro": ["trackGateSentence("],
        "pages/packages.astro": ["holdingsSentence("],
        "pages/strategies/research.astro": ["BANDS.conservative", "tierSummary("],
        "pages/academy/03-lending-aave-compound.astro": ["holdingsSentence(", "realizedPhrase("],
        "pages/annual-contrast.astro": ["measuredDrawdownWindow("],
    }
    missing = [f"{f}: {n}" for f, needles in wiring.items()
               for n in needles if n not in (SRC / f).read_text(encoding="utf-8")]
    assert not missing, missing


def _node() -> str:
    found = shutil.which("node")
    if not found:
        pytest.fail("НЕ ИЗМЕРЕНО: `node` не найден — исход генераторов не наблюдён")
    return found


def _run_js(tmp_path: Path, body: str) -> dict:
    """Copy the real generator files next to a stub shelf and run them under node."""
    for name in ("book_exposure.js", "pct_format.js", "golive_label.js"):
        shutil.copy(LIB / name, tmp_path / name.replace(".js", ".mjs"))
    for name in ("book_exposure.mjs",):
        p = tmp_path / name
        p.write_text(p.read_text(encoding="utf-8").replace("'./site_numbers.js'", "'./stub_numbers.mjs'")
                     .replace("'./pct_format.js'", "'./pct_format.mjs'"), encoding="utf-8")
    (tmp_path / "stub_numbers.mjs").write_text("export default {};\n", encoding="utf-8")
    (tmp_path / "run.mjs").write_text(body, encoding="utf-8")
    out = subprocess.run([_node(), str(tmp_path / "run.mjs")], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_holdings_sentence_comes_from_the_shelf_and_says_not_measured_without_it(tmp_path):
    shelf = {"exposure": {"state": "MEASURED", "as_of": "x", "cash_share": {"value": 5.0},
                          "rows": [{"protocol": "compound_v3", "tier": "T1", "share": {"value": 40.0}},
                                   {"protocol": "fluid_fusdc", "tier": "T2", "share": {"value": 20.0}},
                                   {"protocol": "maple", "tier": "T2", "share": {"value": 20.0}},
                                   {"protocol": "morpho_blue_base", "tier": "T2", "share": {"value": 10.0}},
                                   {"protocol": "aave_v3", "tier": "T1", "share": {"value": 5.0}}]}}
    r = _run_js(tmp_path, f"""
import {{ holdingsSentence, tierSummary }} from './book_exposure.mjs';
const S = {json.dumps(shelf)};
console.log(JSON.stringify({{
  en: holdingsSentence(false, S), ru: holdingsSentence(true, S), tiers: tierSummary(false, S),
  absent: holdingsSentence(false, {{}}), unmeasured: holdingsSentence(true, {{exposure: {{state: 'NOT_MEASURED'}}}}),
}}));
""")
    assert "Fluid (fUSDC) (T2, 20.00%)" in r["en"] and "Morpho Blue (Base) (T2, 10.00%)" in r["en"]
    assert "Spark" not in r["en"]
    assert r["tiers"] == "T1 45.00% · T2 50.00% · cash 5.00%"
    assert "20,00 %" in r["ru"]
    assert r["absent"] == "book composition not measured right now"   # absence ≠ an empty list (inv #17)
    assert r["unmeasured"] == "состав книги сейчас не измерен"


def test_gate_sentence_follows_the_snapshot_not_a_literal(tmp_path):
    r = _run_js(tmp_path, """
import { trackGateSentence, remainingBlockers } from './golive_label.mjs';
const passed = { real_track_days: 107, days_needed: 30, as_of: '2026-10-08', go_live_target: '2026-07-21' };
const open = { real_track_days: 12, days_needed: 30, as_of: '2026-07-03' };
console.log(JSON.stringify({
  passed: trackGateSentence(passed), open: trackGateSentence(open, true),
  blkPassed: remainingBlockers(passed), blkOpen: remainingBlockers(open),
}));
""")
    assert "minimum is met (107/30)" in r["passed"] and "legal review" in r["passed"]
    assert "accruing" not in r["passed"]
    assert "12/30" in r["open"]                      # the open branch still tells the truth when it applies
    assert "30-day" not in r["blkPassed"] and "legal review" in r["blkPassed"]
    assert "30-day evidenced track" in r["blkOpen"]
