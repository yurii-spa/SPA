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
родил мост, и её критерий — исчезновение находки; закрывает мост сам). Карточка-НОСИТЕЛЬ
гасится с `carried_to=<существующий путь>` (ADR-377): содержимое уехало ВОТ ТУДА, и это
заработанное освобождение, а не флаг — путь обязан СУЩЕСТВОВАТЬ, имя без файла не
освобождает ничего.

**Поправка 18.09 (цикл #632): здесь жила ВТОРАЯ КОПИЯ правила, и она разошлась.**
Прежняя редакция этого текста утверждала, что освобождение «в frontmatter следа не
оставляет», и потому храповик `carried_to` не читал вовсе. След оно оставляет:
`owner_queue.queue.set_status` пишет поле прямо во frontmatter и там же проверяет
существование пути. Разошлись копии молча и предсказуемым образом — на первой же
карточке, погашенной НЕ приёмом заданий, а сессией (`inbox-desyat-testov-naslednikov-
heir-all-rows.md`, дубль, закрытый циклом #625 переносом в существующую карточку):
очередь закрытие приняла, храповик назвал его нарушением, и красным стал `main` на
ВЕРНОМ состоянии. Класс — ADR-220. Условие существования пути перенесено сюда целиком,
поэтому проверка не ослаблена: несуществующий путь нарушителем быть не перестаёт.

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
#: Куда уехало содержимое носителя. Освобождение ЗАРАБОТАННОЕ: путь обязан существовать.
_CARRIED = re.compile(r"^carried_to:\s*(\S.*?)\s*$", re.M)
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


def carried_home(name: str) -> "str | None":
    """Путь, куда уехало содержимое карточки-носителя, — ТОЛЬКО если он существует.

    Одно и то же условие с `owner_queue.queue.set_status`: обещание освобождения не
    даёт. Третьего исхода здесь нет намеренно — поля нет и файла нет читаются
    одинаково («освобождения не заработано»), и обе дороги ведут к тому же вердикту,
    что и раньше.
    """
    m = _CARRIED.search(_frontmatter(name))
    if not m:
        return None
    target = m.group(1).strip().strip("\"'")
    if not target:
        return None
    path = Path(target)
    if not path.is_absolute():
        path = _REPO / target
    return target if path.exists() else None


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
                       and not has_criterion(n) and not carried_home(n))
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


def test_a_carrier_is_freed_only_by_a_path_that_exists(tmp_path, monkeypatch) -> None:
    """Положительный контроль освобождения — в ОБЕ стороны.

    Без обратной стороны поправка #632 была бы опт-аутом: строка `carried_to:` гасила
    бы любой вопрос о критерии, и достаточно было бы её написать. Поэтому сцена одна,
    а карточек две — они различаются ровно существованием названного пути.
    """
    tracker = tmp_path / "tracker"
    tracker.mkdir()
    (tmp_path / "есть-такая-карточка.md").write_text("носитель уехал сюда", encoding="utf-8")
    (tracker / "inbox-uehalo.md").write_text(
        "---\nstatus: done\ncarried_to: есть-такая-карточка.md\n---\n", encoding="utf-8")
    (tracker / "inbox-obeschano.md").write_text(
        "---\nstatus: done\ncarried_to: нет-такой-карточки.md\n---\n", encoding="utf-8")
    monkeypatch.setattr("spa_core.tests.test_inbox_acceptance_ratchet._TRACKER", tracker)
    monkeypatch.setattr("spa_core.tests.test_inbox_acceptance_ratchet._REPO", tmp_path)

    assert carried_home("inbox-uehalo.md") == "есть-такая-карточка.md"
    assert carried_home("inbox-obeschano.md") is None, (
        "обещанный путь освободил носителя — это опт-аут, а не заработанное освобождение")
    assert carried_home("inbox-uehalo.md") and not has_criterion("inbox-uehalo.md"), (
        "сцена вырождена: освобождение проверяется только у карточки БЕЗ критерия")


def test_detector_accepts_both_criterion_forms_and_rejects_prose(tmp_path) -> None:
    """Положительный контроль детектора в обе стороны."""
    assert _CRITERION.search("status: new\nacceptance_probe: tier_promotion_loop_closed\n")
    assert _CRITERION.search('status: new\nfinding_key: "tier_promote:x"\n')
    assert not _CRITERION.search("status: new\ntitle: acceptance_probe в заголовке\n")
    assert not _CRITERION.search("status: new\nacceptance_probe:\n"), "пустое поле — не критерий"
