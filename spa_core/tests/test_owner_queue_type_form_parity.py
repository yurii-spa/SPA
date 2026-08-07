"""Тип карточки читают ДВА инструмента — и они обязаны читать его одинаково.

Авария, воспроизводимая каждым тестом здесь (замер цикла #143, перемерен #144, чинится #145):

    python3 scripts/orchestrator_queue.py list --type owner-decision --status needs-owner --json

это ЕДИНСТВЕННАЯ команда, которую `docs/STATE.md` даёт владельцу, чтобы увидеть свою очередь.
Она возвращала **20** карточек при **23** на диске. Невидимы были ровно три `own-rnd-*` — вопросы
владельцу, заведённые R&D-сессиями от руки, один из них про изменение правила демоушена тиров
ADR-055. Причина: `load_card` читал тип ТОЛЬКО из вложенного `trackerStatus.type`, а R&D-сессия
пишет плоский `type:`. Сборщик доски (`scripts/build_tracker_board.py`) понимал ОБЕ формы — и
честно показывал 23. Два читателя одного каталога разошлись, и разошлись молча: расхождение
видно только при сверке читателей друг с другом, чего никто не делал.

Класс — тот самый, за который проект платит с #29: читатель честно отвечает на СВОЙ вопрос
(«у кого есть вложенный `trackerStatus.type`?») и читается как ответ на нужный («что ждёт
владельца?»). Цена здесь — не деньги, а ОТКАЗ, который никогда не будет получен: вопрос до
владельца не доехал, и никто об этом не узнал.

Починка — один резолвер `spa_core.owner_queue.queue.resolve_tracker_type` на оба инструмента,
поэтому здесь проверяется не только результат, но и ПРОВОДКА: доска обязана звать общий
резолвер, а не свою копию правила (иначе они разойдутся снова, и тесты «по частям» это
пропустят — урок цикла #144).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from spa_core.owner_queue.queue import (
    OwnerDoneForbidden,
    list_cards,
    load_card,
    resolve_tracker_type,
    set_status,
)
from spa_core.owner_queue.notify import build_message

REPO = Path(__file__).resolve().parents[2]
TRACKER = REPO / "nimbalyst-local" / "tracker"
BOARD_SCRIPT = REPO / "scripts" / "build_tracker_board.py"

# Точная шапка настоящей карточки `own-rnd-xsd-rank-demotion-allocator` — той самой, что
# не доехала до владельца. Воспроизводим её герметично, а не читаем живой файл: владелец
# однажды ответит, статус сменится, и тест по живому файлу покраснел бы по причине, не
# имеющей отношения к проверяемому поведению (`.claude/rules/deployment.md`, «время в тестах»).
FLAT_FORM_CARD = textwrap.dedent(
    """\
    ---
    type: owner-decision
    status: needs-owner
    priority: medium
    created: 2026-08-07
    tags: [rnd, aggressive-tier, allocator, adr-055, advisory, paper]
    ---

    # Правило «выключать худшую книгу, а не убыточную» — менять ли правило отбора тиров

    ## Что случилось и почему это важно

    Тело карточки.
    """
)

NESTED_FORM_CARD = textwrap.dedent(
    """\
    ---
    trackerStatus:
      type: owner-decision
    title: "Карточка, созданная инструментом"
    status: needs-owner
    priority: high
    ---

    Тело карточки.
    """
)


def _board_module():
    """Загрузить сборщик доски по пути к файлу (он — скрипт, а не пакет)."""
    spec = importlib.util.spec_from_file_location("_btb_under_test", BOARD_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ── положительные контроли: ровно та авария ────────────────────────────────────


def test_flat_form_card_reaches_the_owner_queue(tmp_path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ аварии: плоская форма — в очереди владельца.

    На непочиненном коде `tracker_type` пуст ⇒ фильтр `--type owner-decision` карточку
    отбрасывает, и вопрос владельцу исчезает из его единственной команды.
    """
    _write(tmp_path, "own-rnd-xsd-rank-demotion-allocator.md", FLAT_FORM_CARD)
    found = list_cards(tracker_type="owner-decision", status="needs-owner", tracker_dir=tmp_path)
    assert [c.id for c in found] == ["own-rnd-xsd-rank-demotion-allocator"]


def test_both_forms_land_in_the_same_bucket(tmp_path):
    """Обе формы дают ОДИН тип — иначе очередь владельца зависит от того, кто писал карточку."""
    _write(tmp_path, "own-rnd-dwell-hysteresis-paper-module.md", FLAT_FORM_CARD)
    _write(tmp_path, "own-30-sozdana-instrumentom.md", NESTED_FORM_CARD)
    found = {c.id for c in list_cards(tracker_type="owner-decision", status="needs-owner",
                                      tracker_dir=tmp_path)}
    assert found == {"own-rnd-dwell-hysteresis-paper-module", "own-30-sozdana-instrumentom"}


def test_three_real_cards_of_the_incident_are_all_visible(tmp_path):
    """Все три невидимых вопроса владельцу (#143/#144, поимённо) — видны."""
    names = [
        "own-rnd-cdr-demotion-readmission-paper-module",
        "own-rnd-dwell-hysteresis-paper-module",
        "own-rnd-xsd-rank-demotion-allocator",
    ]
    for n in names:
        _write(tmp_path, f"{n}.md", FLAT_FORM_CARD)
    found = {c.id for c in list_cards(tracker_type="owner-decision", status="needs-owner",
                                      tracker_dir=tmp_path)}
    assert found == set(names)


# ── контроли наоборот: резолвер не должен стать всеядным ───────────────────────


def test_flat_type_of_another_kind_is_not_misfiled(tmp_path):
    """КОНТРОЛЬ НАОБОРОТ: `type: inbox` не обязан попадать в очередь владельца.

    Без него «починка», возвращающая один и тот же тип всем, прошла бы положительные
    контроли: очередь владельца стала бы полной, но перестала бы что-либо значить.
    """
    _write(tmp_path, "inbox-zadanie.md", FLAT_FORM_CARD.replace("type: owner-decision", "type: inbox"))
    assert list_cards(tracker_type="owner-decision", tracker_dir=tmp_path) == []
    assert [c.id for c in list_cards(tracker_type="inbox", tracker_dir=tmp_path)] == ["inbox-zadanie"]


def test_nested_declaration_wins_over_flat(tmp_path):
    """Приоритет — объявление инструмента: вложенная форма старше плоской при конфликте."""
    both = textwrap.dedent(
        """\
        ---
        trackerStatus:
          type: inbox
        type: owner-decision
        status: new
        ---

        Тело.
        """
    )
    _write(tmp_path, "inbox-konflikt-form.md", both)
    assert [c.id for c in list_cards(tracker_type="inbox", tracker_dir=tmp_path)] == ["inbox-konflikt-form"]
    assert list_cards(tracker_type="owner-decision", tracker_dir=tmp_path) == []


def test_declared_type_wins_over_filename_prefix(tmp_path):
    """Имя файла — догадка последней очереди, а не первой.

    Резолвер, начинающий с префикса имени, прошёл бы все положительные контроли выше
    (там имена начинаются с `own-`) и молча переклассифицировал бы карточку, чей тип
    объявлен явно и другой.
    """
    _write(tmp_path, "inbox-imya-vrazrez-s-tipom.md", FLAT_FORM_CARD)
    assert [c.id for c in list_cards(tracker_type="owner-decision", tracker_dir=tmp_path)] == [
        "inbox-imya-vrazrez-s-tipom"
    ]


def test_filename_fallback_only_when_nothing_is_declared():
    """Префикс имени работает ровно там, где объявления нет — и не выдумывает тип из ничего."""
    assert resolve_tracker_type({}, "own-30-bez-tipa.md") == "owner-decision"
    assert resolve_tracker_type({}, "owner-decision-bez-tipa.md") == "owner-decision"
    assert resolve_tracker_type({}, "inbox-bez-tipa.md") == "inbox"
    assert resolve_tracker_type({}, "agent-bez-tipa.md") == "agent-task"
    assert resolve_tracker_type({}, "zametka.md") == ""
    assert resolve_tracker_type({}, "") == ""


def test_empty_declaration_does_not_shadow_the_fallback(tmp_path):
    """Пустой `type:` — не объявление. Иначе карточка проваливается в «нет типа» молча."""
    assert resolve_tracker_type({"type": "   "}, "own-30-pustoi-tip.md") == "owner-decision"
    assert resolve_tracker_type({"trackerStatus": {"type": ""}, "type": "inbox"}, "x.md") == "inbox"


# ── проводка: доска обязана звать ОБЩИЙ резолвер, а не свою копию правила ───────


def test_board_delegates_to_the_shared_resolver():
    """МУТАЦИОННЫЙ сторож проводки: доска зовёт `resolve_tracker_type`, а не копию правила.

    Проверка результата этого не ловит — своя копия, пока она согласована, даёт те же
    ответы. Расходятся они позже и молча, что здесь и произошло. Урок цикла #144:
    мутировать надо проводку, а не только части.
    """
    btb = _board_module()
    calls = []

    def _sentinel(meta, name=""):
        calls.append((meta, name))
        return "sentinel-type"

    btb.resolve_tracker_type = _sentinel
    assert btb.card_type({"type": "owner-decision"}, "own-x.md") == "sentinel-type"
    assert calls == [({"type": "owner-decision"}, "own-x.md")]


def test_board_flattens_nested_form_into_the_shape_the_resolver_reads():
    """Стык двух парсеров: доска сводит `trackerStatus.type` в плоский `type`, резолвер его видит."""
    btb = _board_module()
    meta = btb.parse_frontmatter(NESTED_FORM_CARD)
    assert btb.card_type(meta, "own-30-sozdana-instrumentom.md") == "owner-decision"
    assert btb.card_type(btb.parse_frontmatter(FLAT_FORM_CARD), "own-rnd-x.md") == "owner-decision"


def test_board_script_imports_the_resolver_with_cli_syspath():
    """Импорт обязан работать при вызове `python3 scripts/build_tracker_board.py`.

    Тогда `sys.path[0]` = `scripts/`, корня репозитория на пути НЕТ — ровно в этот капкан
    цикл #111 уронил перевод алертов в CI (`ModuleNotFoundError`, проглоченный except).
    Здесь импорт не проглатывается, поэтому проверяем его в ДОЧЕРНЕМ процессе с таким же
    путём. Модуль только импортируется — доска НЕ перезаписывается.
    """
    code = (
        "import importlib.util, sys;"
        f"spec = importlib.util.spec_from_file_location('btb', r'{BOARD_SCRIPT}');"
        "mod = importlib.util.module_from_spec(spec);"
        "spec.loader.exec_module(mod);"
        "print(mod.resolve_tracker_type({'type': 'owner-decision'}, 'own-x.md'))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO / "scripts"),
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(REPO)},
    )
    assert proc.returncode == 0, f"импорт под CLI-путём упал:\n{proc.stderr}"
    assert proc.stdout.strip() == "owner-decision"


# ── сверка двух читателей на НАСТОЯЩЕМ каталоге ────────────────────────────────


@pytest.mark.skipif(not TRACKER.is_dir(), reason="каталог трекера отсутствует в этом дереве")
def test_cli_and_board_classify_the_real_tracker_identically():
    """ОБА читателя — один набор карточек, поимённо, а не по размерам.

    Это и есть сверка, которой никто не делал: расхождение видно ТОЛЬКО так. Сравниваются
    множества имён по каждому типу; «нет типа» у CLI и «other» у доски — одно и то же.
    Проверка не зависит от содержимого карточек и потому не протухает от смены статусов.
    """
    btb = _board_module()
    cli: dict[str, set[str]] = {}
    board: dict[str, set[str]] = {}
    for p in sorted(TRACKER.glob("*.md")):
        if p.name == "_BOARD.md":
            continue
        try:
            card = load_card(p)
        except Exception:  # noqa: BLE001 — битый файл не должен ронять сверку
            continue
        cli.setdefault(card.tracker_type or "other", set()).add(p.name)
        board.setdefault(btb.card_type(btb.parse_frontmatter(p.read_text(encoding="utf-8")), p.name),
                         set()).add(p.name)

    assert cli.keys() == board.keys(), (
        "CLI и доска разложили карточки по РАЗНЫМ типам:\n"
        f"  только у CLI:   {sorted(cli.keys() - board.keys())}\n"
        f"  только у доски: {sorted(board.keys() - cli.keys())}"
    )
    for t in sorted(cli):
        assert cli[t] == board[t], (
            f"тип `{t}`: читатели одного каталога разошлись — вопрос владельца может "
            f"быть виден на доске и невидим в его очереди.\n"
            f"  только у CLI:   {sorted(cli[t] - board[t])}\n"
            f"  только у доски: {sorted(board[t] - cli[t])}"
        )


# ── acceptance §3: мутации карточки на плоской форме тоже обязаны работать ──────


def test_set_status_works_on_the_flat_form(tmp_path):
    """Иначе ответ владельца по такой карточке нельзя было бы заинжестить."""
    p = _write(tmp_path, "own-rnd-xsd-rank-demotion-allocator.md", FLAT_FORM_CARD)
    set_status(p, "ingested")
    card = load_card(p)
    assert card.status == "ingested"
    assert card.tracker_type == "owner-decision"      # тип не пострадал от перезаписи
    assert "type: owner-decision" in p.read_text(encoding="utf-8")
    assert "priority: medium" in p.read_text(encoding="utf-8")


def test_owner_done_still_forbidden_on_the_flat_form(tmp_path):
    """Инвариант #14 не ослабевает оттого, что карточка написана от руки."""
    p = _write(tmp_path, "own-rnd-xsd-rank-demotion-allocator.md", FLAT_FORM_CARD)
    with pytest.raises(OwnerDoneForbidden):
        set_status(p, "owner-done")
    assert load_card(p).status == "needs-owner"       # файл не тронут


def test_notify_builds_a_message_for_the_flat_form(tmp_path):
    """Уведомление владельцу собирается — иначе `notify` по такой карточке молча пуст."""
    p = _write(tmp_path, "own-rnd-xsd-rank-demotion-allocator.md", FLAT_FORM_CARD)
    msg = build_message(load_card(p))
    assert "own-rnd-xsd-rank-demotion-allocator" in msg


def test_check_card_claim_reads_the_flat_form_status(tmp_path):
    """Шаг 0b читает плоские ключи — статус карточки не должен теряться на этой форме."""
    spec = importlib.util.spec_from_file_location(
        "_ccc_under_test", REPO / "scripts" / "check_card_claim.py"
    )
    ccc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ccc)
    meta = ccc.frontmatter(FLAT_FORM_CARD)
    assert meta.get("status") == "needs-owner"
    assert meta.get("type") == "owner-decision"
