#!/usr/bin/env python3
"""Аудит записей ``status:`` + сторож неатрибутированных переходов.

Каждый тест — авария 2026-08-09 00:25 UTC (карточка
``inbox-statusy-kartochek-vladeltsa-perepisalis``) либо её ближайший сосед: три карточки
owner-gate сайта сменили статус САМИ, живой вопрос владельцу закрылся без ответа
владельца, и ни один сторож не сказал ни слова. Проверка, никогда не видевшая настоящей
поломки, — украшение (``.claude/rules/deployment.md``), поэтому положительный контроль
здесь есть у каждой: снятая починка краснит ровно свою цель.

Время — вход, а не окружение: и запись журнала, и прогон сторожа принимают ``now``,
поэтому у теста нет причины сломаться оттого, что сдвинулся календарь (preference #1
того же правила).

# FROZEN-DATE-OK: injected-clock — даты 2026-08-09 00:19/00:25/00:31 UTC суть отметки
# самой аварии, и обе стороны закреплены одним якорем: тесты с этими датами передают
# ``now`` И в ``record_status_write``/``record_owner_answer``, И в ``sentinel.run`` —
# ни одна из них не сравнивает пришпиленную отметку с реальными часами. Тесты, где
# отметку ставит настоящий писатель (``set_status`` часов не принимает), календарных
# литералов не используют вовсе: там часы реальные с ОБЕИХ сторон.

Прод не участвует: и трекер, и ``data/`` живут в ``tmp_path`` — писать в живую очередь
из теста ровно тот класс, за который проект уже платил (``data/telegram/user_prefs.json``,
цикл #180).
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import pytest

from spa_core.monitoring import tracker_status_sentinel as sentinel
from spa_core.owner_queue import status_audit
from spa_core.owner_queue.queue import OwnerDoneForbidden, set_status

T0 = dt.datetime(2026, 8, 9, 0, 19, tzinfo=dt.timezone.utc)   # сессия записала статусы
T1 = dt.datetime(2026, 8, 9, 0, 25, tzinfo=dt.timezone.utc)   # немой писатель
T2 = dt.datetime(2026, 8, 9, 0, 31, tzinfo=dt.timezone.utc)   # прогон сторожа

CARD = "owner-decision-sait-avtonomnaya-pravka-zadela-owner-gat-3.md"


def _tree(tmp_path: Path) -> Path:
    """Рабочее дерево-двойник: ``.git`` (иначе аудит не опознает дерево) + трекер."""
    (tmp_path / ".git").mkdir()
    (tmp_path / sentinel.TRACKER_REL).mkdir(parents=True)
    (tmp_path / "data").mkdir()
    return tmp_path


def _card(tree: Path, name: str = CARD, status: str = "needs-owner") -> Path:
    p = tree / sentinel.TRACKER_REL / name
    p.write_text(
        "---\n"
        "trackerStatus:\n"
        "  type: owner-decision\n"
        f'title: "Сайт: автономная правка задела owner-gated область — нужно решение"\n'
        f"status: {status}\n"
        "created: 2026-08-08\n"
        "---\n\n"
        "## Что случилось и почему это важно\n\nтело карточки\n",
        encoding="utf-8",
    )
    return p


def _rewrite_status_line(card: Path, new: str) -> None:
    """Ровно то, что сделал немой писатель: переписана ОДНА строка, тело цело."""
    lines = card.read_text(encoding="utf-8").splitlines(keepends=True)
    for i, ln in enumerate(lines):
        if ln.startswith("status:"):
            lines[i] = f"status: {new}\n"
            break
    card.write_text("".join(lines), encoding="utf-8")


# ── сторож: немой писатель ───────────────────────────────────────────────────

def test_silent_rewrite_of_owner_question_is_critical(tmp_path):
    """ГЛАВНЫЙ: вопрос владельца закрылся сам — сторож обязан назвать это вслух."""
    tree = _tree(tmp_path)
    card = _card(tree)
    first = sentinel.run(root=tree, now=T0)
    assert first["verdict"] == sentinel.VERDICT_UNCHECKED  # первый прогон меряет нечем

    _rewrite_status_line(card, "ingested")  # 00:25, никакой записи в журнале

    r = sentinel.run(root=tree, now=T1)
    assert r["verdict"] == sentinel.VERDICT_FINDINGS
    assert r["critical"] == 1
    (f,) = r["unattributed"]
    assert f["card"] == CARD
    assert (f["from"], f["to"]) == ("needs-owner", "ingested")
    assert f["severity"] == "CRITICAL"
    assert f["reason"] == "no_record"
    assert sentinel.exit_code(r) == 2


def test_owner_only_status_without_a_record_is_critical(tmp_path):
    """`owner-done` в обход писателя = обход инварианта #14, и это обязано быть слышно."""
    tree = _tree(tmp_path)
    card = _card(tree, status="ingested")
    sentinel.run(root=tree, now=T0)
    _rewrite_status_line(card, "owner-done")

    r = sentinel.run(root=tree, now=T1)
    (f,) = r["unattributed"]
    assert f["severity"] == "CRITICAL"
    assert f["to"] == "owner-done"


def test_ordinary_silent_transition_is_warn_not_critical(tmp_path):
    """Тяжесть — по цене ошибки: `new -> in-progress` подозрителен, но вопрос не теряет."""
    tree = _tree(tmp_path)
    card = _card(tree, name="inbox-probe.md", status="new")
    sentinel.run(root=tree, now=T0)
    _rewrite_status_line(card, "in-progress")

    r = sentinel.run(root=tree, now=T1)
    (f,) = r["unattributed"]
    assert f["severity"] == "WARN"
    assert r["critical"] == 0
    assert sentinel.exit_code(r) == 1


def test_agent_hand_setting_owner_done_on_an_owner_question_is_critical(tmp_path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ инварианта #14 в его дословной формулировке.

    «Агентам ЗАПРЕЩЕНО переводить карточку решения в ``owner-done``.» Соседний тест
    берёт `ingested -> owner-done`; здесь — ровно запрещённый инвариантом случай:
    ЖИВОЙ вопрос владельца (`needs-owner`) закрывается как отвеченный владельцем, а
    владельца никто не спрашивал. Это одновременно и уход из `needs-owner`, и приход
    в `owner-done` — обе ступени лестницы тяжести обязаны сойтись на CRITICAL.
    """
    tree = _tree(tmp_path)
    card = _card(tree, status="needs-owner")
    sentinel.run(root=tree, now=T0)

    _rewrite_status_line(card, "owner-done")  # рука агента, журнал молчит

    r = sentinel.run(root=tree, now=T1)
    assert r["verdict"] == sentinel.VERDICT_FINDINGS
    (f,) = r["unattributed"]
    assert (f["from"], f["to"]) == ("needs-owner", "owner-done")
    assert f["severity"] == "CRITICAL"
    assert f["reason"] == "no_record"
    assert r["critical"] == 1
    assert sentinel.exit_code(r) == 2


def test_without_the_owner_done_rung_the_same_breach_goes_quiet(tmp_path, monkeypatch):
    """Контроль на сторожа, а не на фикстуру: «краснеет ли это при снятии сторожа».

    Проверка, никогда не видевшая настоящей поломки, — украшение
    (``.claude/rules/deployment.md``). Здесь ступень `→ owner-done` снимается ТОЛЬКО
    в памяти теста, и тот же самый обход инварианта #14 немедленно теряет CRITICAL.
    Значит тяжесть даёт лестница сторожа, а не совпадение фикстуры. Прод не тронут:
    ``monkeypatch`` возвращает константу назад.
    """
    tree = _tree(tmp_path)
    # `ingested` — чтобы вторая ступень (уход из `needs-owner`) не подменила первую:
    # мерим ровно вклад ступени `→ owner-done`.
    card = _card(tree, status="ingested")
    sentinel.run(root=tree, now=T0)
    _rewrite_status_line(card, "owner-done")

    monkeypatch.setattr(sentinel, "OWNER_ONLY", "статус-которого-не-бывает")

    r = sentinel.run(root=tree, now=T1)
    (f,) = r["unattributed"]
    assert f["severity"] == "WARN"          # ← со сторожем здесь CRITICAL
    assert r["critical"] == 0
    assert sentinel.exit_code(r) == 1       # ← со сторожем здесь 2


def test_generic_field_writer_may_not_smuggle_a_status(tmp_path):
    """Обходной путь мимо сторожа: записать `status:` как обычное поле frontmatter.

    ``set_fields`` — универсальный писатель полей; пропусти он ``status``, и
    `owner-done` уехал бы в карточку без проверки инварианта #14 И без строки в
    журнале аудита, то есть сторож увидел бы неатрибутированный переход вместо
    отказа. Отказ обязан быть до записи: карточка и журнал остаются нетронутыми.
    """
    from spa_core.owner_queue.queue import set_fields

    tree = _tree(tmp_path)
    card = _card(tree, status="needs-owner")
    with pytest.raises(OwnerDoneForbidden):
        set_fields(card, {"status": "owner-done"})
    assert status_audit.read_status(card) == "needs-owner"
    assert status_audit.read_audit(tree)[0] == []


def test_card_creator_may_not_smuggle_a_status_through_extra_fields(tmp_path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на настоящий обход (замерен 19.08, живой CLI агента).

    ``set_fields`` ключ ``status`` отказывал с самого начала, а ``create_card`` — нет:
    гейт инварианта #14 смотрел ТОЛЬКО на параметр ``status=``. Обе двери открыты из
    документированной команды агента, и вели они в разные стороны::

        orchestrator_queue.py create … --status owner-done       → REFUSED (rc 2)
        orchestrator_queue.py create … --field status=owner-done → карточка создана

    Соседний тест (``…_splits_the_sentinel_from_the_owner_queue``) меряет, во что это
    обходилось: карточка с ДВУМЯ ``status:``, вопрос владельца пропадает из его очереди
    и выглядит закрытым владельцем, а сторож переходов молчит по построению.

    Отказ обязан быть ДО записи: файла карточки после него быть не должно.
    """
    from spa_core.owner_queue.queue import create_card

    tree = _tree(tmp_path)
    tracker = tree / sentinel.TRACKER_REL
    with pytest.raises(OwnerDoneForbidden):
        create_card("owner-decision", "Проба обхода", "тело",
                    extra_fields={"status": "owner-done"}, tracker_dir=tracker)
    assert list(tracker.glob("*.md")) == []
    assert status_audit.read_audit(tree)[0] == []


def test_a_second_status_line_splits_the_sentinel_from_the_owner_queue(tmp_path):
    """ПОЧЕМУ отказ выше обязан стоять в СОЗДАТЕЛЕ: сторож этот класс не видит.

    Карточка с двумя верхнеуровневыми ``status:`` читается двумя читателями по-разному:
    ``status_audit.status_of_text`` (сторож переходов) берёт ПЕРВУЮ строку,
    ``queue._parse_frontmatter`` (CLI, доска, Telegram) — словарь, где побеждает
    ПОСЛЕДНЯЯ. Владелец теряет вопрос: в его очереди ``needs-owner`` карточки нет, а
    везде, где печатается статус, стоит ``owner-done``.

    Сторож переходов тут бессилен не по недосмотру, а по построению: карточка для него
    новая (``appeared``), перехода не было, записи в журнале не требуется — он честно
    печатает OK. Значит единственная защита — отказ в точке рождения карточки.
    Тест характеризующий: закроют расхождение читателей — он покажет, что защиту в
    ``create_card`` надо пересмотреть, а не что она стала не нужна.
    """
    from spa_core.owner_queue.queue import list_cards, load_card

    tree = _tree(tmp_path)
    tracker = tree / sentinel.TRACKER_REL
    card = tracker / "owner-decision-dve-stroki-status.md"
    card.write_text(
        "---\n"
        "trackerStatus:\n"
        "  type: owner-decision\n"
        'title: "Вопрос владельцу"\n'
        "status: needs-owner\n"
        "created: 2026-08-09\n"
        "status: owner-done\n"
        "---\n\nтело\n",
        encoding="utf-8",
    )
    assert status_audit.read_status(card) == "needs-owner"   # то, что видит сторож
    assert load_card(card).status == "owner-done"            # то, что видит владелец
    assert list_cards("owner-decision", "needs-owner", tracker_dir=tracker) == []

    sentinel.run(root=tree, now=T0)
    r = sentinel.run(root=tree, now=T1)
    assert r["verdict"] == sentinel.VERDICT_OK
    assert r["unattributed"] == []


# ── сторож: законные переходы молчат ─────────────────────────────────────────

def test_needs_owner_to_ingested_is_the_one_move_an_agent_may_make(tmp_path):
    """ОБРАТНЫЙ КОНТРОЛЬ: единственный разрешённый агенту переход не краснеет.

    Инвариант #14 оставляет агенту ровно одно движение — `needs-owner → ingested`
    после инжеста ответа владельца. Сторож, который краснел бы и на него, за неделю
    научил бы всех себя игнорировать, и настоящий обход утонул бы в собственном шуме.
    Часы настоящие с обеих сторон: ``set_status`` их не принимает.
    """
    tree = _tree(tmp_path)
    card = _card(tree, status="needs-owner")
    sentinel.run(root=tree)

    set_status(card, "ingested")

    r = sentinel.run(root=tree)
    assert r["verdict"] == sentinel.VERDICT_OK, r["unattributed"]
    assert r["unattributed"] == []
    (a,) = r["attributed"]
    assert (a["from"], a["to"]) == ("needs-owner", "ingested")
    assert "queue.set_status" in a["writer"]
    assert sentinel.exit_code(r) == 0


def test_refused_owner_done_leaves_the_sentinel_with_nothing_to_report(tmp_path):
    """Агент попробовал через API — отказ; значит и перехода нет, и тревоги нет.

    Пара «писатель отказал + сторож молчит» обязана сходиться: отказ, после которого
    сторож всё равно кричит, означал бы, что что-то всё-таки записалось.
    """
    tree = _tree(tmp_path)
    card = _card(tree, status="needs-owner")
    sentinel.run(root=tree)

    with pytest.raises(OwnerDoneForbidden):
        set_status(card, "owner-done")

    r = sentinel.run(root=tree)
    assert r["verdict"] == sentinel.VERDICT_OK, r
    assert r["transitions"] == 0
    assert sentinel.exit_code(r) == 0



def test_set_status_is_attributed_and_names_the_writer(tmp_path):
    """Штатный перевод карточки объяснён журналом — сторож молчит и называет писателя.

    Часы здесь настоящие с ОБЕИХ сторон: ``set_status`` их не принимает, и подсунуть
    сторожу дату 2026-08-09 против отметки «сейчас» значило бы сломать тест календарём.
    """
    tree = _tree(tmp_path)
    card = _card(tree, status="new", name="inbox-probe.md")
    sentinel.run(root=tree)

    set_status(card, "in-progress")

    r = sentinel.run(root=tree)
    assert r["verdict"] == sentinel.VERDICT_OK, r["unattributed"]
    assert r["unattributed"] == []
    (a,) = r["attributed"]
    assert a["from"] == "new" and a["to"] == "in-progress"
    assert "queue.set_status" in a["writer"]
    assert sentinel.exit_code(r) == 0


def test_owner_answer_is_attributed(tmp_path, monkeypatch):
    """Ответ ВЛАДЕЛЬЦА — тоже запись статуса; законное закрытие не должно краснеть."""
    from spa_core.owner_queue import owner_answer

    tree = _tree(tmp_path)
    card = _card(tree)
    sentinel.run(root=tree, now=T0)

    owner_answer.record_owner_answer(
        card, choice_num="1", choice_label="одобрить",
        actor_chat_id="42", owner_chat_id="42", now=T1,
    )

    r = sentinel.run(root=tree, now=T1)
    assert r["unattributed"] == []
    (a,) = r["attributed"]
    assert a["to"] == "owner-done"
    assert "owner_answer" in a["writer"]


def test_chain_of_two_writes_is_attributed(tmp_path):
    """Между снимками карточка прошла `new -> in-progress -> done` — цепочка объяснена."""
    tree = _tree(tmp_path)
    card = _card(tree, status="new", name="inbox-probe.md")
    sentinel.run(root=tree)

    set_status(card, "in-progress")
    set_status(card, "done")

    r = sentinel.run(root=tree)
    assert r["unattributed"] == []
    (a,) = r["attributed"]
    assert (a["from"], a["to"]) == ("new", "done")


# ── сторож: чем НЕЛЬЗЯ оправдаться ───────────────────────────────────────────

def test_stale_record_cannot_launder_a_new_transition(tmp_path):
    """Старая законная запись не выдаёт индульгенцию последующим молчаливым правкам."""
    tree = _tree(tmp_path)
    card = _card(tree, status="new", name="inbox-probe.md")

    status_audit.record_status_write(card, old="new", new="needs-owner",
                                     source="queue.set_status",
                                     now=T0 - dt.timedelta(days=3))
    _rewrite_status_line(card, "needs-owner")
    sentinel.run(root=tree, now=T0)          # снимок УЖЕ с needs-owner
    _rewrite_status_line(card, "ingested")   # а вот это никто не объяснял

    r = sentinel.run(root=tree, now=T1)
    (f,) = r["unattributed"]
    assert f["reason"] == "no_record"
    assert f["severity"] == "CRITICAL"


def test_record_about_another_transition_is_named_not_accepted(tmp_path):
    """Журнал объясняет ДРУГОЙ переход — это находка, а не «объяснено»."""
    tree = _tree(tmp_path)
    card = _card(tree, status="new", name="inbox-probe.md")
    sentinel.run(root=tree, now=T0)

    status_audit.record_status_write(card, old="new", new="in-progress",
                                     source="queue.set_status", now=T1)
    _rewrite_status_line(card, "done")  # а на диске оказалось совсем другое

    r = sentinel.run(root=tree, now=T1)
    (f,) = r["unattributed"]
    assert f["reason"] == "chain_mismatch"
    assert "'new' -> 'in-progress'" in f["detail"]


def test_missing_audit_file_is_not_read_as_calm(tmp_path):
    """Журнала нет вовсе (его и не было 09.08) — переходы обязаны остаться видимыми."""
    tree = _tree(tmp_path)
    card = _card(tree)
    sentinel.run(root=tree, now=T0)
    _rewrite_status_line(card, "ingested")
    assert not (tree / status_audit.AUDIT_REL).exists()

    r = sentinel.run(root=tree, now=T1)
    assert r["critical"] == 1


def test_broken_audit_line_is_unchecked_not_silence(tmp_path):
    """Битая строка журнала = «часть не прочитана», а не «записей нет»."""
    tree = _tree(tmp_path)
    _card(tree)
    (tree / status_audit.AUDIT_REL).write_text("{не json\n", encoding="utf-8")
    sentinel.run(root=tree, now=T0)

    r = sentinel.run(root=tree, now=T1)
    assert r["verdict"] == sentinel.VERDICT_UNCHECKED
    assert any("нечитаемая запись журнала" in u for u in r["unchecked"])
    assert sentinel.exit_code(r) == 2


def test_first_run_without_previous_snapshot_is_unchecked(tmp_path):
    """Не с чем сравнивать ⇒ «не измерено», а не «нарушений не найдено» (fail-CLOSED)."""
    tree = _tree(tmp_path)
    _card(tree)
    r = sentinel.run(root=tree, now=T0)
    assert r["verdict"] == sentinel.VERDICT_UNCHECKED
    assert sentinel.exit_code(r) == 2
    assert r["unattributed"] == []


def test_appeared_and_vanished_cards_are_not_transitions(tmp_path):
    """Новая карточка — не переход; исчезнувшая — тоже. Иначе сторож утонет в шуме."""
    tree = _tree(tmp_path)
    old = _card(tree, name="inbox-old.md", status="new")
    sentinel.run(root=tree, now=T0)
    old.unlink()
    _card(tree, name="inbox-fresh.md", status="new")

    r = sentinel.run(root=tree, now=T1)
    assert r["unattributed"] == []
    assert r["appeared"] == ["inbox-fresh.md"] and r["vanished"] == ["inbox-old.md"]


# ── журнал аудита сам по себе ────────────────────────────────────────────────

def test_record_names_process_tree_and_source(tmp_path):
    """«Кто, какой pid, какая карточка, из какого дерева» — дословный запрос карточки."""
    tree = _tree(tmp_path)
    card = _card(tree, status="new", name="inbox-probe.md")

    set_status(card, "done")

    entries, broken = status_audit.read_audit(tree)
    assert broken == []
    (e,) = entries
    assert e["card"] == "inbox-probe.md"
    assert e["old"] == "new" and e["new"] == "done"
    assert e["source"] == "queue.set_status"
    assert e["pid"] == os.getpid()
    assert Path(e["tree"]) == tree.resolve()
    assert e["argv"] and e["executable"] and e["cwd"]


def test_owner_done_refusal_leaves_no_record(tmp_path):
    """Инвариант #14 не ослаблен, и отказ НЕ порождает записи о несделанном переходе."""
    tree = _tree(tmp_path)
    card = _card(tree, status="needs-owner")
    with pytest.raises(OwnerDoneForbidden):
        set_status(card, "owner-done")
    assert status_audit.read_status(card) == "needs-owner"
    assert status_audit.read_audit(tree)[0] == []


def test_audit_failure_does_not_block_the_status_write(tmp_path, capsys):
    """Не записался журнал — потерян след, но не работа; и жалоба обязана быть громкой."""
    tree = _tree(tmp_path)
    card = _card(tree, status="new", name="inbox-probe.md")
    (tree / "data").chmod(0o500)  # каталог только на чтение
    try:
        set_status(card, "done")
        assert status_audit.read_status(card) == "done"
        assert "журнал не записан" in capsys.readouterr().err
    finally:
        (tree / "data").chmod(0o700)


def test_status_line_in_the_body_is_not_the_status(tmp_path):
    """Строка `status:` из ТЕЛА карточки статусом не является — фантомных переходов нет."""
    tree = _tree(tmp_path)
    p = tree / sentinel.TRACKER_REL / "inbox-probe.md"
    p.write_text("---\ntrackerStatus:\n  type: inbox\nstatus: new\n---\n\n"
                 "пример из чужого файла:\nstatus: ingested\n", encoding="utf-8")
    assert status_audit.read_status(p) == "new"


def test_snapshot_written_for_the_next_run(tmp_path):
    """Снимок — вход следующего прогона; без него сторож слеп навсегда."""
    tree = _tree(tmp_path)
    _card(tree)
    sentinel.run(root=tree, now=T0)
    snap = json.loads((tree / sentinel.SNAPSHOT_REL).read_text(encoding="utf-8"))
    assert snap["statuses"][CARD] == "needs-owner"
    assert snap["generated_at"] == T0.isoformat()


def test_dry_run_touches_neither_snapshot_nor_report(tmp_path):
    """Сухой прогон не пишет в живое состояние (урок карточки про `notify --check`)."""
    tree = _tree(tmp_path)
    _card(tree)
    sentinel.run(root=tree, now=T0, write=False)
    assert not (tree / sentinel.SNAPSHOT_REL).exists()
    assert not (tree / sentinel.REPORT_REL).exists()
