#!/usr/bin/env python3
"""Ключ близнеца НЕИЗМЕНЯЕМ: работа по карточке не имеет права отключить защиту (ADR-866).

Авария, воспроизводимая каждым тестом этого файла. Защита очереди от дублей
(`queue._open_twin`) узнавала близнеца по ПОЛНОМУ ТЕЛУ открытой карточки — а тело
дописывает сам приём сразу после рождения (штамп критерия `## Как понять, что готово`,
пометка истории при вердикте PARTIAL), дальше дописывают цикл и ответ владельцу
(ADR-863). Ключ сравнения был ИЗМЕНЯЕМЫМ, и изменяла его система сама: как только по
карточке начали работать, она перестала быть близнецом.

Замер #981 на живой очереди: просьба владельца «проверь дашборд» родилась **десять**
раз (`inbox-prover-dashbord` … `-10`), при побайтно одинаковом тексте задания. Вред не в
лишних файлах: ADR-860 сделал ПОВТОР просьбы осью вердикта шага 0a, поэтому повторы,
которые очередь плодит сама, кормят эту ось — и шаг 0a каждый цикл заново требует «возьми
эту карточку первой».

Положительный контроль у НАСТОЯЩЕЙ двери: две сцены, отличающиеся РОВНО допиской тела
(`.claude/rules/deployment.md`, «Проверка сторожа сторожей»). До правки они давали
«СЛИЛОСЬ» против «РОДИЛАСЬ ВТОРАЯ»; обратная сцена (ДРУГАЯ просьба под тем же заголовком)
держит защиту от превращения в глухоту.

Литеральных дат нет: у ключа нет понятия свежести, и заводить фикстуру с датой значило бы
поставить бомбу на пустом месте. Литеральных pid нет: ни одного процесса дверь не
спрашивает.
"""
from __future__ import annotations

import json
import subprocess
import sys
from io import StringIO
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from spa_core.owner_queue import queue as q
from spa_core.owner_queue.queue import (
    TWIN_BY_BODY,
    TWIN_BY_KEY,
    TWIN_KEY_FIELD,
    TWIN_NONE,
    TWIN_UNMEASURED,
    create_card,
    load_card,
    set_status,
    twin_key,
    twin_verdict,
)

TITLE = "проверь дашборд"

#: Тело задания — дословно то, которое приём пишет голосовой просьбе владельца.
BODY = (
    "## Задание (из Telegram)\n\nпроверь дашборд\n\n"
    "## Расшифровка голосового (whisper)\n\nпроверь дашборд на телефоне\n"
)

#: Дописка, которую делает САМ приём (`owner_queue/intake.py`, ветка `task`) сразу после
#: рождения карточки. Именно она и была ключом аварии.
INTAKE_STAMP = ("\n## Как понять, что готово\n"
                "Задача выполнена и проверена (детали — обычный цикл).\n")


def _append_as_the_intake_does(path: Path, text: str = INTAKE_STAMP) -> None:
    """Дописать тело так, как это делает приём/цикл — ПОВЕРХ родившейся карточки."""
    path.write_text(path.read_text(encoding="utf-8").rstrip("\n") + text, encoding="utf-8")


def _cards(d: Path) -> list[str]:
    return sorted(p.name for p in d.glob("inbox-*.md"))


# ---------------------------------------------------------------------------
# 1. САМА АВАРИЯ: дописка тела больше не отключает защиту
# ---------------------------------------------------------------------------

def test_the_intake_stamp_no_longer_breaks_the_twin_guard(tmp_path):
    """Авария #981 дословно: родили → приём дописал тело → та же просьба пришла снова.

    До ADR-866 второй вызов рождал `-2`. Это ТОТ САМЫЙ тест, который краснеет, если
    ключ снова станет изменяемым.
    """
    first = create_card("inbox", TITLE, BODY, tracker_dir=tmp_path, source="voice")
    _append_as_the_intake_does(first)
    again = create_card("inbox", TITLE, BODY, tracker_dir=tmp_path, source="voice")
    assert again == first, f"родилась вторая карточка: {_cards(tmp_path)}"
    assert _cards(tmp_path) == [first.name]


def test_ten_repeats_after_ten_appends_are_still_one_card(tmp_path):
    """Десять просьб — одна карточка, даже если тело дописывают после каждой.

    Население аварии было именно таким: каждый цикл дописывал якорь своей строкой.
    """
    first = create_card("inbox", TITLE, BODY, tracker_dir=tmp_path, source="voice")
    for i in range(9):
        _append_as_the_intake_does(first, f"\n## Сведена в якорь циклом #{i}\nтекст\n")
        assert create_card("inbox", TITLE, BODY, tracker_dir=tmp_path,
                           source="voice") == first
    assert _cards(tmp_path) == [first.name]


# ---------------------------------------------------------------------------
# 2. ОБРАТНЫЙ КОНТРОЛЬ: защита не стала глухотой
# ---------------------------------------------------------------------------

def test_a_different_request_under_the_same_title_still_gets_its_own_card(tmp_path):
    """ДРУГАЯ просьба с тем же заголовком обязана родиться своей.

    Без этой сцены «починка» могла бы просто склеивать всё, что названо одинаково, —
    и съедала бы разные задания владельца.
    """
    first = create_card("inbox", TITLE, BODY, tracker_dir=tmp_path, source="voice")
    _append_as_the_intake_does(first)
    other = create_card("inbox", TITLE, BODY.replace("дашборд", "почту"),
                        tracker_dir=tmp_path, source="voice")
    assert other != first
    assert len(_cards(tmp_path)) == 2


def test_a_candidate_with_another_key_is_measured_not_unmeasured(tmp_path):
    """«Другая просьба» — ИЗМЕРЕННЫЙ ответ, а не «не измерено».

    Ключ у кандидата ЕСТЬ и он другой ⇒ вопрос решён, и выдавать это третьим исходом
    значило бы объявить неизмеренным то, что измерено (инв. #17 наизнанку).
    """
    create_card("inbox", TITLE, BODY, tracker_dir=tmp_path, source="voice")
    v = twin_verdict("inbox", TITLE, BODY.replace("дашборд", "почту"), tracker_dir=tmp_path)
    assert v["kind"] == TWIN_NONE, v
    assert v["measured"] is True


def test_a_closed_keyed_card_does_not_suppress_a_returning_request(tmp_path):
    """Статус правит ключом: закрытый вопрос, вернувшийся снова, — новый вопрос.

    Ключ не имеет права оживить прежнюю защиту закрытой карточки — иначе закрытая
    вчера карточка навсегда глушила бы ту же проблему сегодня. Карточка-решение взята
    намеренно: `inbox` в `done` не переводится без машинной пробы (храповик приёмки), и
    обходить ЧУЖОЙ сторож ради этой сцены было бы его молчаливым ослаблением (инв. #16).
    """
    first = create_card("owner-decision", TITLE, BODY, tracker_dir=tmp_path)
    assert load_card(first).fields.get(TWIN_KEY_FIELD) == twin_key(BODY)
    set_status(first, "ingested")
    second = create_card("owner-decision", TITLE, BODY, tracker_dir=tmp_path)
    assert second != first
    assert len(sorted(p.name for p in tmp_path.glob("owner-decision-*.md"))) == 2


# ---------------------------------------------------------------------------
# 3. КЛЮЧ ПИШЕТСЯ ПРИ РОЖДЕНИИ И НЕ ПЕРЕПИСЫВАЕТСЯ РАБОТОЙ
# ---------------------------------------------------------------------------

def test_the_key_is_written_at_birth(tmp_path):
    born = create_card("inbox", TITLE, BODY, tracker_dir=tmp_path, source="voice")
    stored = load_card(born).fields.get(TWIN_KEY_FIELD)
    assert stored == twin_key(BODY)
    assert stored.startswith("sha256:")


def test_work_on_the_card_does_not_change_its_key(tmp_path):
    """Тело меняется, ключ — нет. Это и есть предмет правки."""
    born = create_card("inbox", TITLE, BODY, tracker_dir=tmp_path, source="voice")
    before = load_card(born).fields.get(TWIN_KEY_FIELD)
    _append_as_the_intake_does(born)
    _append_as_the_intake_does(born, "\n## Ответ владельцу\nдоставлен\n")
    after = load_card(born)
    assert after.fields.get(TWIN_KEY_FIELD) == before
    assert after.body.strip() != BODY.strip(), "сцена не собралась: тело не изменилось"
    assert twin_verdict("inbox", TITLE, BODY, tracker_dir=tmp_path)["kind"] == TWIN_BY_KEY


def test_a_caller_supplied_key_is_not_overwritten(tmp_path):
    """Объявленный вызывающим ключ — его решение, а не умолчание двери."""
    born = create_card("inbox", TITLE, BODY, tracker_dir=tmp_path,
                       extra_fields={TWIN_KEY_FIELD: "sha256:deadbeef"})
    assert load_card(born).fields.get(TWIN_KEY_FIELD) == "sha256:deadbeef"


def test_the_key_discriminates_exactly_as_the_old_body_compare_did(tmp_path):
    """Нормализация ключа — та же, что была у сверки тела: ни строже, ни слабее.

    Правка про НЕИЗМЕНЯЕМОСТЬ не имеет права заодно ослабить или усилить различение:
    иначе «починили» и «подменили мерку» стало бы одним наблюдением.
    """
    assert twin_key(BODY) == twin_key(BODY + "\n\n")
    assert twin_key(BODY) == twin_key("\n" + BODY)
    assert twin_key(BODY) != twin_key(BODY + "ещё одно нарушение\n")
    first = create_card("inbox", TITLE, BODY, tracker_dir=tmp_path, source="voice")
    assert create_card("inbox", TITLE, BODY + "\n\n", tracker_dir=tmp_path,
                       source="voice") == first


# ---------------------------------------------------------------------------
# 4. ТРЕТИЙ ИСХОД: старое население без ключа (инв. #17)
# ---------------------------------------------------------------------------

def _legacy_card(d: Path, name: str, body: str, status: str = "new") -> Path:
    """Карточка СТАРОГО населения: ключа нет, тело уже дописано работой."""
    p = d / name
    p.write_text("---\ntrackerStatus:\n  type: inbox\n"
                 f"title: {TITLE}\nstatus: {status}\nsource: voice\n---\n\n"
                 + body, encoding="utf-8")
    return p


def test_a_keyless_candidate_with_an_appended_body_is_the_third_outcome(tmp_path):
    """Ключа нет, тело разошлось ⇒ «та же это просьба» НЕ ИЗМЕРЕНО — и это НАЗВАНО.

    Выдать это за «близнеца нет» значило бы ровно то молчание, из-за которого десять
    одинаковых просьб выглядели десятью просьбами.
    """
    _legacy_card(tmp_path, "inbox-prover-dashbord.md", BODY + INTAKE_STAMP)
    v = twin_verdict("inbox", TITLE, BODY, tracker_dir=tmp_path)
    assert v["kind"] == TWIN_UNMEASURED, v
    assert v["measured"] is False
    assert v["keyless"] == ["inbox-prover-dashbord.md"]
    assert v["path"] is None


def test_the_card_born_after_an_unmeasured_twin_carries_a_key_and_absorbs_the_next(tmp_path):
    """Старое население НЕ переписывается календарём — граница рисуется ПОЛЕМ.

    Тело старой карточки уже дописано, и текст рождения из него не восстановить:
    догадка здесь была бы подстановкой. Поэтому карточка рождается (прежнее поведение),
    но уже С КЛЮЧОМ — и размножение останавливается на следующем повторе, а не длится
    бесконечно.
    """
    _legacy_card(tmp_path, "inbox-prover-dashbord.md", BODY + INTAKE_STAMP)
    born = create_card("inbox", TITLE, BODY, tracker_dir=tmp_path, source="voice")
    assert born.name == "inbox-prover-dashbord-2.md"
    assert load_card(born).fields.get(TWIN_KEY_FIELD) == twin_key(BODY)
    assert create_card("inbox", TITLE, BODY, tracker_dir=tmp_path, source="voice") == born
    assert len(_cards(tmp_path)) == 2


def test_a_keyless_candidate_with_the_same_body_still_merges(tmp_path):
    """Защита старого населения НЕ опускается ниже прежней: тело совпало ⇒ слито.

    Род при этом НАЗВАН «ключ не измерен» — утверждения «слито по ключу» и «слито по
    телу» остаются разными.
    """
    legacy = _legacy_card(tmp_path, "inbox-prover-dashbord.md", BODY)
    v = twin_verdict("inbox", TITLE, BODY, tracker_dir=tmp_path)
    assert v["kind"] == TWIN_BY_BODY, v
    assert v["measured"] is False
    assert create_card("inbox", TITLE, BODY, tracker_dir=tmp_path, source="voice") == legacy


def test_a_closed_keyless_card_is_not_even_a_candidate(tmp_path):
    """Закрытая карточка в «неизмеренное» не попадает: вопрос о ней не задаётся."""
    _legacy_card(tmp_path, "inbox-prover-dashbord.md", BODY + INTAKE_STAMP, status="done")
    v = twin_verdict("inbox", TITLE, BODY, tracker_dir=tmp_path)
    assert v["kind"] == TWIN_NONE, v
    assert v["keyless"] == []


# ---------------------------------------------------------------------------
# 5. FAIL-CLOSED В СТОРОНУ ВЛАДЕЛЬЦА — и третий исход у сбоя тоже НАЗВАН
# ---------------------------------------------------------------------------

def test_a_failing_lookup_is_the_third_outcome_and_still_creates_the_card(tmp_path,
                                                                         monkeypatch):
    """Поиск близнеца рухнул ⇒ карточка создаётся, а вопрос помечен НЕ ИЗМЕРЕННЫМ.

    Прежняя редакция возвращала здесь `None`, то есть «близнеца нет» — молчание,
    неотличимое от измеренного ответа.
    """
    def boom(*a, **k):
        raise OSError("каталог недоступен")

    monkeypatch.setattr(q.Path, "glob", boom)
    v = twin_verdict("inbox", TITLE, BODY, tracker_dir=tmp_path)
    assert v["kind"] == TWIN_UNMEASURED and v["path"] is None
    assert "OSError" in v["reason"]
    created = create_card("inbox", TITLE, BODY, tracker_dir=tmp_path, source="voice")
    assert created.exists() and load_card(created).title == TITLE


def test_a_broken_card_on_disk_never_blocks_a_new_one(tmp_path):
    """Битый файл не имеет права проглотить просьбу владельца."""
    (tmp_path / "inbox-prover-dashbord.md").write_text("не карточка вовсе",
                                                       encoding="utf-8")
    created = create_card("inbox", TITLE, BODY, tracker_dir=tmp_path, source="voice")
    assert created.exists() and load_card(created).title == TITLE


def test_merge_open_twin_false_never_consults_the_key(tmp_path):
    """Пульт владеет идемпотентностью сам (`submission_id`, ADR-760) — ключ его не правит.

    Осознанная вторая заметка с тем же текстом есть НОВАЯ просьба, и склеивать её
    ключом было бы потерей.
    """
    first = create_card("inbox", TITLE, BODY, tracker_dir=tmp_path, source="voice")
    second = create_card("inbox", TITLE, BODY, tracker_dir=tmp_path, source="voice",
                         merge_open_twin=False)
    assert second != first
    assert len(_cards(tmp_path)) == 2


# ---------------------------------------------------------------------------
# 6. НАСТОЯЩИЙ ЧИТАТЕЛЬ: ось повтора шага 0a (ADR-860) перестаёт расти
# ---------------------------------------------------------------------------

_STARVATION = (Path(__file__).resolve().parents[2] / "scripts"
               / "check_owner_order_starvation.py")


def _starvation_axis(tracker_dir: Path) -> dict:
    """Поднять НАСТОЯЩИЙ шаг 0a на одноразовом трекере и вернуть его JSON.

    Проводка спрашивается у прибора, а не у его печати: сверять текст подстрокой
    здесь нельзя (ADR-333) — печать, собранная из того же числа, подтверждала бы сама
    себя.
    """
    out = subprocess.run(
        [sys.executable, str(_STARVATION), "--tracker-dir", str(tracker_dir),
         "--ref", "", "--no-write", "--json"],
        capture_output=True, text=True, timeout=300)
    if not out.stdout.strip():
        pytest.fail("шаг 0a не напечатал JSON — проводка НЕ ИЗМЕРЕНА: "
                    f"rc={out.returncode} stderr={out.stderr[-400:]}")
    return json.loads(out.stdout)


def test_the_step_0a_repeat_axis_does_not_grow_for_a_request_that_merged(tmp_path):
    """Вред закрыт у ЧИТАТЕЛЯ: ось повтора шага 0a про слитую просьбу не растёт.

    Это и есть то, ради чего правка сделана. Контроль в обе стороны идёт по РОДУ
    населения, а не по словам отчёта: одна карточка ⇒ повторов 0, две разные просьбы
    под одним заголовком ⇒ тоже 0 (ось считает ПОВТОР, а не одноимённость), а две
    карточки ОДНОЙ просьбы (старое население) ⇒ 2.
    """
    merged = tmp_path / "merged"
    merged.mkdir()
    first = create_card("inbox", TITLE, BODY, tracker_dir=merged, source="voice")
    _append_as_the_intake_does(first)
    create_card("inbox", TITLE, BODY, tracker_dir=merged, source="voice")
    assert len(_cards(merged)) == 1, "сцена не собралась: карточки не слились"
    assert _starvation_axis(merged)["repeated_cards"] == 0

    bred = tmp_path / "bred"
    bred.mkdir()
    _legacy_card(bred, "inbox-prover-dashbord.md", BODY + INTAKE_STAMP)
    _legacy_card(bred, "inbox-prover-dashbord-2.md", BODY)
    assert _starvation_axis(bred)["repeated_cards"] == 2, (
        "сцена не собралась: ось шага 0a не увидела повтора, который в трекере ЕСТЬ")
