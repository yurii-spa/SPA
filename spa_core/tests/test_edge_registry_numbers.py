"""Ratchet: an edge-registry entry number (and its mnemonic) must be UNIQUE.

WHY THIS EXISTS — the accident it replays, cycle #249/#250 (2026-08-15)
  R&D work was written as registry entries #49 (XCV) and #50 (SST), then sat undelivered in a dead
  /tmp worktree for two days. In those two days other sessions claimed BOTH numbers (#49 RDT,
  #50 NTB). The collision was caught by EYES — a grep run by hand before publishing — not by any
  check. Had it not been caught, `docs/DYNAMIC_LEVERAGE_GUARDIAN.md` would carry two different
  ideas under one number, and the number in this registry is also the ADDRESS other entries link
  by ("счёт #10/#49", "#40 против #45"): a single duplicate makes every reference to it unreadable.
  The same class already happened one layer up with ADR numbers (ADR-067 claimed twice, card
  `inbox-nomera-adr-stalkivayutsya-dva-raza-za-de`).

  This is not a hypothesis: sessions dying between working and pushing is the routine failure of
  this project (five raises of orphaned R&D in one week — #239→#240→#241, #244→#246, #249→#250).
  As long as that holds, "number claimed at writing time" keeps drifting away from "number free at
  delivery time". The rule is written next to the registry itself (REGISTRY-NUMBER-RULE anchor) and
  pinned by `test_number_rule_is_documented_next_to_the_registry` below, so it cannot quietly go.

WIDER THAN ITS WARD (the lesson of the guard class: a guard that only echoes its ward is its ward)
  * mnemonics are addresses too (`#40 XSD`), so duplicate MNEMONICS red as well, not just numbers;
  * the parse is fence-aware — a header line QUOTED inside a ``` block is prose about an entry, not
    an entry. Today that changes no count (naive grep and fence-aware parse both see 55), so this is
    insurance against a FALSE red, bought before it fires rather than after;
  * gaps are deliberately NOT asserted. The live registry skips 24 and 26; demanding contiguity
    would red an honest registry, and a guard that reds on the correct state teaches people to
    switch it off (invariant #16).

Deterministic, hermetic, no network, no dates, no live track. Reads one markdown file.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
_REGISTRY = _ROOT / "docs" / "DYNAMIC_LEVERAGE_GUARDIAN.md"

# `- **#40 XSD: ...` / `- **#1 Dynamic Leverage Guardian** — ...`
_HEADER = re.compile(r"^- \*\*#(\d+)\b\s*(.*)$")
_MNEMONIC = re.compile(r"^([A-Z][A-Z0-9]{1,6}):")

_RULE_ANCHOR = "REGISTRY-NUMBER-RULE"


def parse_entries(text: str) -> list[tuple[int, str | None, int]]:
    """(number, mnemonic-or-None, 1-based line) for every registry entry header.

    Lines inside fenced code blocks are skipped: a quoted header is prose ABOUT an entry.
    """
    out: list[tuple[int, str | None, int]] = []
    in_fence = False
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADER.match(line)
        if not m:
            continue
        mn = _MNEMONIC.match(m.group(2))
        out.append((int(m.group(1)), mn.group(1) if mn else None, lineno))
    return out


def duplicate_numbers(entries) -> dict[int, list[int]]:
    seen: dict[int, list[int]] = {}
    for num, _mn, lineno in entries:
        seen.setdefault(num, []).append(lineno)
    return {n: ls for n, ls in seen.items() if len(ls) > 1}


def duplicate_mnemonics(entries) -> dict[str, list[int]]:
    seen: dict[str, list[int]] = {}
    for _num, mn, lineno in entries:
        if mn:
            seen.setdefault(mn, []).append(lineno)
    return {m: ls for m, ls in seen.items() if len(ls) > 1}


def _live_entries():
    return parse_entries(_REGISTRY.read_text(encoding="utf-8"))


# ─────────────────────────── the live registry ───────────────────────────

def test_registry_is_parseable_at_all():
    # a guard that silently finds nothing is a guard that always passes: pin that the parse WORKS.
    entries = _live_entries()
    assert len(entries) >= 50, f"registry parse collapsed: only {len(entries)} entries found"


def test_no_duplicate_entry_numbers():
    dups = duplicate_numbers(_live_entries())
    assert not dups, (
        "два разных заголовка реестра под одним номером — ссылки на этот номер стали нечитаемы; "
        f"номер → строки: {dups}"
    )


def test_no_duplicate_mnemonics():
    dups = duplicate_mnemonics(_live_entries())
    assert not dups, (
        "мнемоника записи — тоже адрес (`#40 XSD`); дубль делает ссылку неоднозначной; "
        f"мнемоника → строки: {dups}"
    )


def test_number_rule_is_documented_next_to_the_registry():
    # the fix is half test, half rule; without the rule the next session re-claims a number early.
    # anchored on a machine-readable marker, NOT on the prose around it, so rewording stays free.
    assert _RULE_ANCHOR in _REGISTRY.read_text(encoding="utf-8"), (
        f"пропал якорь {_RULE_ANCHOR} — правило «номер берётся в момент ДОСТАВКИ» больше нигде "
        "не записано, а один тест его не заменяет"
    )


# ─────────────────── positive controls: the guard must RED ───────────────────
# Each replays the real 2026-08-15 collision rather than a hypothetical one.

_TWO_49 = """### Реестр идей

- **#48 PKP: something** — статус: ok
- **#49 RDT: rebalance drift tax** — статус: ok
- **#49 XCV: cross-criterion vote** — статус: ok
"""

_TWO_XSD = """### Реестр идей

- **#40 XSD: cross-sectional drift** — статус: ok
- **#56 XSD: another thing wearing the same badge** — статус: ok
"""


def test_positive_control_duplicate_number_is_caught():
    entries = parse_entries(_TWO_49)
    assert len(entries) == 3
    assert duplicate_numbers(entries) == {49: [4, 5]}


def test_positive_control_duplicate_mnemonic_is_caught():
    entries = parse_entries(_TWO_XSD)
    assert duplicate_mnemonics(entries) == {"XSD": [3, 4]}


# ─────────────────── reverse controls: the guard must NOT red ───────────────────

_QUOTED_IN_FENCE = """### Реестр идей

- **#49 RDT: rebalance drift tax** — статус: ok

Пример того, как ВЫГЛЯДИТ заголовок записи:

```
- **#49 XCV: это цитата, а не запись реестра**
```

- **#50 NTB: no-trade band** — статус: ok
"""


def test_reverse_control_quoted_header_in_a_fence_is_not_an_entry():
    entries = parse_entries(_QUOTED_IN_FENCE)
    assert [e[0] for e in entries] == [49, 50]
    assert duplicate_numbers(entries) == {}


def test_reverse_control_gaps_are_allowed():
    # the live registry skips 24 and 26 on purpose; contiguity is NOT a rule and must not be one.
    # ONE claim per test: duplicates are `test_no_duplicate_entry_numbers`'s job, not this one's —
    # measured, not assumed: mutation M1 (a real duplicate #49) reddened this test too until the
    # borrowed assertion was removed, i.e. it reported the wrong reason for the right fault.
    nums = sorted(n for n, _mn, _l in _live_entries())
    assert nums, "реестр не разобрался — об этом кричит test_registry_is_parseable_at_all"
    assert set(range(1, max(nums) + 1)) - set(nums), (
        "если пропусков не стало — это не повод начинать проверять непрерывность: "
        "требование сплошной нумерации покрасит исправный реестр при первом же списании записи"
    )
