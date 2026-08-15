"""Шаг 2 обязан видеть ответ владельца из ЛЮБОГО дерева — иначе он теряет РЕШЕНИЕ.

**Каждый тест здесь воспроизводит настоящую аварию 14.08.** Проверка, никогда не видевшая
живой поломки, — украшение (правило `.claude/rules/deployment.md`).

Что случилось. Владелец ответил на карточку `owner-decision-stranitsa-treka-chetvertyi-den-pryachet`
**14.08 в 12:26:56Z** (Телеграм, вариант 1); след записан честно — `data/tracker_status_audit.jsonl`
строка 155, источник `owner_answer.record_owner_answer`, писатель `spa_core/telegram/bot.py`.
Шаг 2 протокола, предписанный ДОСЛОВНО так —

    python3 scripts/orchestrator_queue.py list --type owner-decision --status owner-done --json

— из worktree на `origin/main` вернул **пустой список**. То есть оттуда, где §3.4 прямо велит
работать. Причина устойчива и сама не пройдёт: бот пишет ответ в ПРОД-дерево, а на `origin/main`
он не уезжает ничем — мост доставки карточек везёт только то, что создал или закрыл сам за
прогон (`IDLE`, ADR-081), а ответа владельца он не создавал.

**Цена измерена:** два прогона цикла #230 (16:15Z и 17:01Z) прошли мимо живого решения владельца.
Нашёл его цикл #231 не шагом 2, а шагом 1-пред (`check_tracker_drift`), где расхождение теряется
среди десятков строк «своя правка»: одна строка «дерево: owner-done · origin/main: needs-owner»
среди двадцати однотипных.

**Чем это отличается от уже закрытого зеркала.** `inbox-otvet-vladeltsa-zhivet-tolko-v-host-dereve`
(#182) — про ЛОЖНОЕ «есть решение»: шаг 2 из прод-дерева выдавал карточки, давно разобранные на
origin. Здесь ЗЕРКАЛЬНАЯ половина — ЛОЖНОЕ «решений нет», и она опаснее: ложный положительный
стоит времени сессии, ложный отрицательный **теряет решение владельца**, а заметить его нечем —
пустой список выглядит ровно как честная пустая очередь.

**Границы, закреплённые обратными контролями ниже.** Инвариант #14 не ослабляется ни на строку:
`owner-done` по-прежнему ставит ТОЛЬКО владелец, здесь ничего не ЗАПИСЫВАЕТСЯ — чужая копия
только читается и называется. Опрашивается ТОЛЬКО главное дерево (туда пишет бот), а не все
рабочие деревья: опрос всех дал бы `owner-done` из десятков брошенных `/tmp`-worktree, где
решение давно разобрано, — ровно та находка-пустышка, которая приучает пролистывать раздел
целиком (урок #243).

Литеральных дат-фикстур здесь нет там, где они были бы бомбой: возраст ответа считается от
`now`, который передаётся ВХОДОМ (`.claude/rules/deployment.md`, порядок предпочтения п.1).
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"
for _p in (str(_REPO_ROOT), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import orchestrator_queue as oq  # noqa: E402
from spa_core.owner_queue.owner_answer import (  # noqa: E402
    CROSS_AGREES,
    CROSS_FOUND,
    CROSS_SAME_TREE,
    CROSS_UNMEASURED,
    scan_owner_answers_elsewhere,
)

TRACKER_REL = "nimbalyst-local/tracker"
BRANCH = "main"

# FROZEN-DATE-OK: injected-clock — `now=NOW` передаётся ВХОДОМ в каждый вызов
# (`scan_owner_answers_elsewhere(..., now=)` и `args.now`), а отметка ответа владельца
# `ANSWERED_AT` выведена от того же якоря: разница между ними фиксирована (ровно 4 ч), и
# проверяется именно она. Обе стороны закреплены ⇒ сдвиг календаря покрасить тест не может.
# Это преференция #1 правила `.claude/rules/deployment.md`, а не исключение из него.
#: Момент ответа владельца и «сейчас» — ОБЕ стороны закреплены, поэтому тест бессмертен.
ANSWERED_AT = "2026-08-14T12:26:56+00:00"
NOW = datetime(2026, 8, 14, 16, 26, 56, tzinfo=timezone.utc)   # ровно 4 ч спустя


def _run(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


def _card(status: str, *, answered: bool = False, title: str = "вопрос владельцу") -> str:
    extra = (f"owner_choice: 1\nowner_answered_at: {ANSWERED_AT}\n"
             f"owner_answer_via: telegram_button\n" if answered else "")
    body = "## Решение владельца\n\n**Вариант 1**" if answered else "## Что от тебя нужно\n\nвыбери"
    return (f"---\ntrackerStatus:\n  type: owner-decision\n"
            f'title: "{title}"\nstatus: {status}\n{extra}---\n\n{body}\n')


@pytest.fixture()
def trees(tmp_path):
    """Прод-дерево + линкованный worktree — ровно расстановка 14.08.

    Возвращает (главное дерево, worktree). Бот пишет в главное; цикл работает во втором.
    """
    main = tmp_path / "prod"
    (main / TRACKER_REL).mkdir(parents=True)
    _run(tmp_path, "init", "-q", "-b", BRANCH, str(main))
    _run(main, "config", "user.email", "t@example.com")
    _run(main, "config", "user.name", "test")
    # карточка уезжает на origin в состоянии «ждёт владельца»
    (main / TRACKER_REL / "owner-decision-track-page.md").write_text(
        _card("needs-owner"), encoding="utf-8")
    _run(main, "add", "-A")
    _run(main, "commit", "-q", "-m", "вопрос владельцу")

    wt = tmp_path / "wt"
    _run(main, "worktree", "add", "-q", "--detach", str(wt), BRANCH)
    return main, wt


def _owner_answers_in_prod(main: Path, name: str = "owner-decision-track-page") -> None:
    """Бот записывает ответ владельца в ПРОД-дерево. На origin он не уезжает ничем."""
    (main / TRACKER_REL / f"{name}.md").write_text(_card("owner-done", answered=True),
                                                   encoding="utf-8")


def _tracker(root: Path) -> Path:
    return root / TRACKER_REL


def _step2(root: Path, capsys, *, status="owner-done", now=NOW):
    """Ровно та команда, которую предписывает шаг 2 протокола. → (rc, карточки, stderr)."""
    argv = ["list", "--type", "owner-decision", "--status", status,
            "--tracker-dir", str(_tracker(root)), "--ref", BRANCH, "--json"]
    args = oq.build_parser().parse_args(argv)
    args.now = now
    rc = oq.cmd_list(args)
    cap = capsys.readouterr()
    return rc, json.loads(cap.out), cap.err


# ── ЯДРО ДЕФЕКТА: пустой список вместо живого решения ────────────────────────

def test_step2_from_worktree_sees_the_owner_answer(trees, capsys):
    """АВАРИЯ 14.08 ДОСЛОВНО: ответ в прод-дереве, шаг 2 из worktree.

    На неисправленном коде здесь ноль карточек — и это выглядит как честная пустая очередь.
    """
    main, wt = trees
    _owner_answers_in_prod(main)

    rc, cards, _err = _step2(wt, capsys)

    assert cards, "шаг 2 из worktree обязан увидеть ответ владельца — иначе решение потеряно"
    assert [c["id"] for c in cards] == ["owner-decision-track-page"]
    assert cards[0]["status"] == "owner-done"
    assert rc == 0


def test_answer_is_visible_in_stdout_not_only_in_stderr(trees, capsys):
    """Шаг 2 читает JSON. Урок #178: всё, что живёт в stderr-прозе, `| jq` не видит НИКОГДА."""
    main, wt = trees
    _owner_answers_in_prod(main)

    _rc, cards, _err = _step2(wt, capsys)

    assert cards[0]["cross_tree_check"] == CROSS_FOUND
    assert cards[0]["source_tree"] == str(main.resolve())
    assert cards[0]["local_status"] == "needs-owner", (
        "машинно видно и то, чем карточка притворялась в читаемом дереве"
    )


def test_stderr_line_is_loud_and_names_the_card(trees, capsys):
    """Требование карточки: отдельная ГРОМКАЯ строка, а не одна из двадцати у drift-сторожа."""
    main, wt = trees
    _owner_answers_in_prod(main)

    _rc, _cards, err = _step2(wt, capsys)

    assert "ОТВЕТ ВЛАДЕЛЬЦА ЕСТЬ В ГЛАВНОМ ДЕРЕВЕ" in err
    assert "owner-decision-track-page" in err


def test_how_long_the_answer_has_been_waiting_is_named(trees, capsys):
    """«Ответ пролежал без разбора N часов» — находка того же класса, что «вопрос без ответа».

    Время — ВХОД: обе стороны (`owner_answered_at` и `now`) закреплены фикстурой.
    """
    main, wt = trees
    _owner_answers_in_prod(main)

    _rc, cards, err = _step2(wt, capsys)

    assert cards[0]["age_hours"] == pytest.approx(4.0)
    assert "ждёт 4.0 ч" in err


def test_missing_answer_timestamp_is_named_not_guessed(trees, capsys):
    """Момента ответа нет ⇒ так и сказано. Подставлять «0 часов» значило бы соврать свежестью."""
    main, wt = trees
    (main / TRACKER_REL / "owner-decision-track-page.md").write_text(
        _card("owner-done", answered=False), encoding="utf-8")

    _rc, cards, err = _step2(wt, capsys)

    assert cards[0]["age_hours"] is None
    assert "момент ответа НЕ записан" in err


def test_card_absent_from_the_worktree_entirely_is_still_seen(trees, capsys):
    """Карточка родилась в прод-дереве и на origin не уезжала — в worktree её файла нет вовсе."""
    main, wt = trees
    (main / TRACKER_REL / "owner-decision-born-in-prod.md").write_text(
        _card("owner-done", answered=True, title="решение, рождённое в проде"), encoding="utf-8")

    _rc, cards, _err = _step2(wt, capsys)

    ids = {c["id"] for c in cards}
    assert "owner-decision-born-in-prod" in ids
    found = next(c for c in cards if c["id"] == "owner-decision-born-in-prod")
    assert found["local_status"] == "(файла нет)"


def test_both_copies_appear_as_two_distinguishable_entries(trees, capsys):
    """Копий карточки ДВЕ — столько записей и выдаётся, и каждая говорит, откуда она.

    Схлопнуть их в одну было бы соблазнительно (ровно один `id` — «чище»), но это чинило бы
    видимость враньём о числе: копии реально расходятся, и какая из них уедет на origin —
    решает сессия, а не список. Поэтому у записи главного дерева стоит `source_tree`, а у
    своей его нет вовсе.
    """
    main, wt = trees
    _owner_answers_in_prod(main)
    argv = ["list", "--type", "owner-decision",
            "--tracker-dir", str(_tracker(wt)), "--ref", BRANCH, "--json"]
    args = oq.build_parser().parse_args(argv)
    args.now = NOW
    oq.cmd_list(args)
    cards = json.loads(capsys.readouterr().out)

    assert len(cards) == 2, "две копии карточки — две записи"
    assert {c["status"] for c in cards} == {"needs-owner", "owner-done"}
    own = [c for c in cards if "source_tree" not in c]
    foreign = [c for c in cards if c.get("source_tree")]
    assert len(own) == len(foreign) == 1, "у своей записи источника нет, у чужой он назван"
    assert own[0]["status"] == "needs-owner", "своя копия НЕ переписана чужой"
    assert foreign[0]["source_tree"] == str(main.resolve())


def test_human_readable_output_shows_it_too(trees, capsys):
    """Два выхода не имеют права расходиться: глазами видно то же, что и `| jq`."""
    main, wt = trees
    _owner_answers_in_prod(main)
    args = oq.build_parser().parse_args(
        ["list", "--type", "owner-decision", "--status", "owner-done",
         "--tracker-dir", str(_tracker(wt)), "--ref", BRANCH])
    args.now = NOW
    oq.cmd_list(args)

    assert CROSS_FOUND in capsys.readouterr().out


# ── ОБРАТНЫЕ КОНТРОЛИ: сторож не имеет права звонить на верном состоянии ─────

def test_no_answer_anywhere_is_an_honest_empty_list(trees, capsys):
    """Ответа нет нигде ⇒ пусто, тихо, код 0. Иначе сторож стал бы вечной находкой."""
    main, wt = trees

    rc, cards, err = _step2(wt, capsys)

    assert cards == []
    assert rc == 0
    assert "ОТВЕТ ВЛАДЕЛЬЦА ЕСТЬ В ГЛАВНОМ ДЕРЕВЕ" not in err
    verdict, findings, reason = scan_owner_answers_elsewhere(_tracker(wt), now=NOW)
    assert (verdict, findings, reason) == (CROSS_AGREES, [], None)


def test_reading_the_prod_tree_itself_raises_nothing(trees, capsys):
    """Из прод-дерева второго дерева спрашивать не о чем — заплатка #231 не должна звонить.

    Без этого контроля «починка» разбудила бы сессию на ВЕРНОМ действии (ADR-084: гасим
    маршрут, а не проверку).
    """
    main, _wt = trees
    _owner_answers_in_prod(main)

    rc, cards, err = _step2(main, capsys)

    assert [c["id"] for c in cards] == ["owner-decision-track-page"], "своя копия видна как всегда"
    assert "ОТВЕТ ВЛАДЕЛЬЦА ЕСТЬ В ГЛАВНОМ ДЕРЕВЕ" not in err
    assert rc == 0
    assert scan_owner_answers_elsewhere(_tracker(main), now=NOW)[0] == CROSS_SAME_TREE


def test_already_ingested_locally_is_not_a_finding(trees, capsys):
    """Сессия уже разобрала ответ и доставила ⇒ находки нет: иначе она вечная."""
    main, wt = trees
    _owner_answers_in_prod(main)
    (_tracker(wt) / "owner-decision-track-page.md").write_text(
        _card("ingested"), encoding="utf-8")

    _rc, _cards, err = _step2(wt, capsys, status="ingested")

    assert "ОТВЕТ ВЛАДЕЛЬЦА ЕСТЬ В ГЛАВНОМ ДЕРЕВЕ" not in err
    assert scan_owner_answers_elsewhere(_tracker(wt), now=NOW)[0] == CROSS_AGREES


def test_nothing_is_written_to_either_tree(trees, capsys):
    """Инв. #14: сторож ТОЛЬКО читает. Байты обеих копий обязаны остаться прежними."""
    main, wt = trees
    _owner_answers_in_prod(main)
    prod_card = main / TRACKER_REL / "owner-decision-track-page.md"
    wt_card = _tracker(wt) / "owner-decision-track-page.md"
    before = (prod_card.read_bytes(), wt_card.read_bytes())

    _step2(wt, capsys)

    assert (prod_card.read_bytes(), wt_card.read_bytes()) == before


def test_agents_still_cannot_set_owner_done(trees):
    """Инв. #14 не ослаблен ни на строку — отказ writer'а остаётся на месте."""
    from spa_core.owner_queue.queue import OwnerDoneForbidden, set_status
    main, _wt = trees
    with pytest.raises(OwnerDoneForbidden):
        set_status(main / TRACKER_REL / "owner-decision-track-page.md", "owner-done")


# ── FAIL-CLOSED: «не измерено» никогда не читается как «решений нет» ─────────

def test_unmeasurable_tree_is_named_not_silently_ok(tmp_path, capsys):
    """Трекер вне репозитория ⇒ вердикт «не измерено», а не молчаливое «совпало»."""
    lonely = tmp_path / "nowhere" / TRACKER_REL
    lonely.mkdir(parents=True)

    verdict, findings, reason = scan_owner_answers_elsewhere(lonely, now=NOW)

    assert verdict == CROSS_UNMEASURED
    assert findings == []
    assert reason


def test_empty_and_unmeasured_list_returns_two(tmp_path, capsys, monkeypatch):
    """ГВОЗДЬ ЖАЛОБЫ: пустая очередь неотличима от честной пустой.

    Когда карточек ноль, полей в JSON нет по построению — остаётся ровно один канал, и это
    код возврата (после ADR-084 ненулевой код и есть канал недоставки). Измеренная пустота
    по-прежнему даёт 0 — это проверяет `test_no_answer_anywhere_is_an_honest_empty_list`.
    """
    lonely = tmp_path / "nowhere" / TRACKER_REL
    lonely.mkdir(parents=True)
    args = oq.build_parser().parse_args(
        ["list", "--type", "owner-decision", "--status", "owner-done",
         "--tracker-dir", str(lonely), "--json", "--no-origin-check"])
    args.now = NOW

    rc = oq.cmd_list(args)
    cap = capsys.readouterr()

    assert rc == 2, "«не измерено» над пустым списком не имеет права выглядеть как «решений нет»"
    assert json.loads(cap.out) == []
    assert "НЕ ИЗМЕРЕН" in cap.err


def test_unmeasured_verdict_rides_in_the_json_for_every_card(trees, capsys, monkeypatch):
    """Не измерилось, но карточки есть ⇒ у КАЖДОЙ стоит `unmeasured`.

    Отсутствие поля читалось бы как «сверено и ок» — тот самый fail-OPEN, которым живёт класс.
    """
    _main, wt = trees
    (_tracker(wt) / "owner-decision-track-page.md").write_text(
        _card("owner-done", answered=True), encoding="utf-8")
    monkeypatch.setattr(oq, "scan_owner_answers_elsewhere",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("git недоступен")))

    _rc, cards, err = _step2(wt, capsys)

    assert cards and all(c["cross_tree_check"] == CROSS_UNMEASURED for c in cards)
    assert "НЕ ИЗМЕРЕН" in err


def test_guard_failure_never_breaks_the_queue(trees, capsys, monkeypatch):
    """Сторож — довесок к списку, а не его условие: упал он — список всё равно выдан."""
    _main, wt = trees
    (_tracker(wt) / "owner-decision-track-page.md").write_text(
        _card("owner-done", answered=True), encoding="utf-8")
    monkeypatch.setattr(oq, "scan_owner_answers_elsewhere",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("диск отвалился")))

    rc, cards, _err = _step2(wt, capsys)

    assert [c["id"] for c in cards] == ["owner-decision-track-page"]
    assert rc == 0


def test_only_the_main_tree_is_polled_not_every_worktree(trees, tmp_path, capsys):
    """Граница из карточки: опрашивается ТОЛЬКО главное дерево, куда пишет бот.

    Обратный контроль к соблазну «спросить все деревья»: в брошенном worktree лежит
    `owner-done`, давно разобранный, — и он НЕ имеет права стать находкой (урок #243:
    находки-пустышки приучают пролистывать раздел целиком).
    """
    main, wt = trees
    abandoned = tmp_path / "abandoned"
    _run(main, "worktree", "add", "-q", "--detach", str(abandoned), BRANCH)
    (_tracker(abandoned) / "owner-decision-track-page.md").write_text(
        _card("owner-done", answered=True), encoding="utf-8")

    verdict, findings, _reason = scan_owner_answers_elsewhere(_tracker(wt), now=NOW)

    assert (verdict, findings) == (CROSS_AGREES, [])
