#!/usr/bin/env python3
"""Храповик машинного критерия приёмки у карточек типа `inbox` (ADR-208, правило
`.claude/rules/acceptance.md`, карточка `inbox-mashinnaya-priemka-obyazatelna-ishodnaya`).

Замер 11.09: 1021 карточка, машинный критерий у 5 (0,5 %). Остальные «готово» стоят на
прозе той же сессии, которая работу и делала. Замер 13.09 при введении правила:
inbox-карточек 511, без критерия — 462.

Устройство — как у `design_status_baseline.json` и `frozen_date_baseline.json`, и по той
же причине: запрет в лоб покрасил бы 462 карточки разом и научил бы всех отключать
проверку. Поэтому:

* база (`scripts/inbox_acceptance_baseline.json`) перечисляет карточки, существовавшие
  без критерия на момент введения правила, — они НЕ краснеют;
* **новая** inbox-карточка, ВЗЯТАЯ В РАБОТУ (статус вне `new`/`backlog`) без критерия,
  краснеет сразу. Приём заданий (`new`) не блокируется намеренно: карточки рождаются и
  из голосовых заданий владельца, а критерий фиксирует ТА сессия, что берёт карточку, —
  ДО работы (правило №4 карточки; механически — отказ `set-status` в очереди);
* база может только уменьшаться; добавлять в неё файл, чтобы погасить падение,
  запрещено — на этом храповик и держится.

Критерий в машинной форме — одно из двух полей frontmatter:
`acceptance_probe: <имя из card_acceptance.PROBES>` либо `finding_key:` (карточку
родил мост, и её критерий — исчезновение находки; закрывает мост сам).

Только stdlib, оффлайн.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_TRACKER = _REPO / "nimbalyst-local" / "tracker"
_BASELINE = _REPO / "scripts" / "inbox_acceptance_baseline.json"

_FM = re.compile(r"\A---\n(.*?)\n---", re.S)
_CRITERION = re.compile(r"^(acceptance_probe|finding_key):\s*\S", re.M)
_STATUS = re.compile(r"^status:\s*(\S+)", re.M)
#: Статусы приёма: карточка ещё ничья, критерий обязан появиться при взятии в работу.
INTAKE_STATUSES = frozenset({"new", "backlog"})


def _frontmatter(name: str) -> str:
    try:
        text = (_TRACKER / name).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = _FM.match(text)
    return m.group(1) if m else ""


def _inbox_cards() -> set[str]:
    if not _TRACKER.is_dir():
        return set()
    return {p.name for p in _TRACKER.iterdir()
            if p.is_file() and p.name.startswith("inbox-") and p.name.endswith(".md")}


def has_criterion(name: str) -> bool:
    return bool(_CRITERION.search(_frontmatter(name)))


def status_of(name: str) -> str:
    m = _STATUS.search(_frontmatter(name))
    return m.group(1) if m else "?"


def _baseline() -> set[str] | None:
    try:
        return set(json.loads(_BASELINE.read_text(encoding="utf-8"))["files"])
    except Exception:  # noqa: BLE001 — пропавшая база не должна проходить молча
        return None


def test_baseline_exists_and_is_readable() -> None:
    """Нет базы ⇒ храповик ничего не меряет. Fail-CLOSED."""
    assert _baseline() is not None, (
        f"{_BASELINE} отсутствует или не читается — храповик не отличит новую "
        "карточку от старой и молча пропустит всё")


def test_no_new_card_is_in_work_without_a_criterion() -> None:
    """Главная проверка: карточка, взятая в работу, обязана нести машинный критерий."""
    base = _baseline() or set()
    offenders = sorted(n for n in _inbox_cards()
                       if n not in base and status_of(n) not in INTAKE_STATUSES
                       and not has_criterion(n))
    assert not offenders, (
        "inbox-карточка взята в работу (или закрыта) без машинного критерия приёмки:\n  "
        + "\n  ".join(f"{n} (status: {status_of(n)})" for n in offenders)
        + "\n\nДО работы объявить пробу: python3 scripts/orchestrator_queue.py probe "
        "nimbalyst-local/tracker/<карточка>.md <имя пробы[:аргумент]>\n"
        "Имена — card_acceptance.PROBES; нет подходящей — зарегистрировать новую с "
        "положительным контролем в обе стороны. В базу файл НЕ добавлять: база только уменьшается "
        "(.claude/rules/acceptance.md).")


def test_baseline_holds_nothing_that_now_has_a_criterion() -> None:
    """База обязана сжиматься: карточка, получившая критерий, выпадает из неё."""
    base = _baseline() or set()
    cards = _inbox_cards()
    fixed = sorted(n for n in base if n in cards and has_criterion(n))
    assert not fixed, (
        "эти карточки уже несут критерий и обязаны выйти из базы (база только уменьшается): "
        f"{fixed}")


def test_baseline_holds_no_ghosts() -> None:
    """Удалённая карточка не должна вечно занимать место в базе."""
    base = _baseline() or set()
    ghosts = sorted(n for n in base if n not in _inbox_cards())
    assert not ghosts, f"в базе карточки, которых нет на диске: {ghosts}"


def test_detector_accepts_both_criterion_forms_and_rejects_prose(tmp_path) -> None:
    """Положительный контроль детектора в обе стороны."""
    assert _CRITERION.search("status: new\nacceptance_probe: tier_promotion_loop_closed\n")
    assert _CRITERION.search('status: new\nfinding_key: "tier_promote:x"\n')
    assert not _CRITERION.search("status: new\ntitle: acceptance_probe в заголовке\n")
    assert not _CRITERION.search("status: new\nacceptance_probe:\n"), "пустое поле — не критерий"
