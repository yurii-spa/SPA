"""Живая копия карточки ОТСТАЛА от источника правды — `refresh_live_copy_from_ref`.

КАЖДЫЙ тест — положительный контроль аварии **20–21.08.2026**:

    `own-33-plist-marker-for-cycle-origin` стоял перед владельцем БЕЗ КНОПОК с 20.08
    и был отправлен ЧЕТЫРЕ раза — каждый раз честно без кнопок. Варианты в карточке
    ЕСТЬ, но только на `origin/main`: цикл #321 переписал вопрос перечнем
    «Вариант 1 / Вариант 2» в 19:53Z, через 52 минуты после отправки в 19:01Z. Бот
    шлёт из ПРОД-дерева, а каталог очереди туда не возит никто (автосинк возит
    `spa_core/`·`scripts/`·`tests/`, #193).

    Лекарства у этого состояния не было ВОВСЕ, и оба запрета были правы поодиночке:
    `materialize_card` не копирует поверх живой копии (она может нести ответ
    владельца, #178), `parse_options` не выдумывает варианты (ADR-075). Цикл #332
    научил сторожа НАЗЫВАТЬ причину (`card_stale_vs_origin`) — состояние стало
    видимым, но не вылеченным, и это разные утверждения.

**Что здесь закреплено — обеими сторонами.** Живая копия обновляется с ref только
когда доказано, что терять нечего; копия со следом ответа владельца не затирается
ни при каком расхождении. Обратные контроли (`owner_answer_present`, `status_*`,
`not_stale`, `unmeasured`) — не украшение: без них «починка» свелась бы к слепой
перезаписи, то есть к той же аварии в другую сторону.

Фикстуры — настоящие крошечные git-репозитории (без сети), как в
`test_buttonless_reason.py`: проверяется ЭФФЕКТ на git, а не подменённая заглушка.
Литеральных дат нет: время — ВХОД.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.owner_queue import origin_view
from spa_core.telegram import buttonless_reason as br
from spa_core.telegram import owner_decisions as od

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
REF = "main"

#: Тело, каким его дописал цикл #321 на origin — варианты разбираются.
_WITH_OPTIONS = (
    "## Что случилось и почему это важно\n\nЦикл идёт 52 раза в сутки.\n\n"
    "## Что от тебя нужно\n\n"
    "- **Вариант 1 (⭐ рекомендую) — разрешить метку.** Две строки в настройку.\n"
    "- **Вариант 2 — ничего не менять.** Источник запусков останется неизвестным.\n"
)
#: Тело, каким оно осталось в живом дереве — прозой, вариантов нет.
_WITHOUT_OPTIONS = (
    "## Что случилось и почему это важно\n\nЦикл идёт 52 раза в сутки.\n\n"
    "## Что от тебя нужно\n\n"
    "Разреши добавить две строки в настройку агента. Альтернатива — ничего не менять.\n"
)


def _card_text(body: str, *, status: str = "needs-owner", answer: bool = False) -> str:
    head = ["---", "trackerStatus:", "  type: owner-decision",
            'title: "Вопрос владельцу"', f"status: {status}"]
    if answer:
        head += ["owner_choice: '1'", "owner_answered_at: '2030-01-01T00:00:00+00:00'",
                 "owner_answer_via: telegram", "owner_answered_by: owner"]
    return "\n".join(head) + "\n---\n\n" + body


def _run(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


@pytest.fixture()
def repo(tmp_path):
    """Репозиторий с каталогом очереди и веткой-«origin». Сети не касается."""
    root = tmp_path / "repo"
    (root / origin_view.TRACKER_REL).mkdir(parents=True)
    _run(root.parent, "init", "-q", "-b", REF, str(root))
    _run(root, "config", "user.email", "t@example.com")
    _run(root, "config", "user.name", "test")
    return root


def _tracker(root: Path) -> Path:
    return root / origin_view.TRACKER_REL


def _write(root: Path, name: str, body: str, **kw) -> Path:
    p = _tracker(root) / f"{name}.md"
    p.write_text(_card_text(body, **kw), encoding="utf-8")
    return p


def _commit(root: Path, msg="c"):
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", msg)


def _stale(repo: Path, *, live_status: str = "needs-owner",
           live_answer: bool = False) -> Path:
    """Ровно состояние `own-33`: на ref варианты есть, в дереве их нет."""
    card = _write(repo, "own-33", _WITH_OPTIONS)
    _commit(repo)
    card.write_text(_card_text(_WITHOUT_OPTIONS, status=live_status, answer=live_answer),
                    encoding="utf-8")
    return card


def _beacon(tmp_path: Path) -> Path:
    """Живой маячок обработчика нажатий — иначе кнопок нет по ДРУГОЙ причине."""
    p = tmp_path / "beacon.json"
    p.write_text(json.dumps({
        "schema_version": 1, "source": "telegram_bot",
        "updated_at": NOW.isoformat(), "pid": 1,
        "capabilities": ["alert_actions"],
    }), encoding="utf-8")
    return p


# ===========================================================================
# ЯДРО АВАРИИ: отставшая копия обновляется, и владелец получает свой выбор
# ===========================================================================
def test_stale_live_copy_is_refreshed_from_the_ref(repo):
    """`own-33`: в живой копии 0 вариантов, на ref — 2. Была неизлечима, стала лечима."""
    card = _stale(repo)
    assert od.parse_options(card.read_text(encoding="utf-8")) == []

    rep = od.refresh_live_copy_from_ref(card, ref=REF)

    assert rep["verdict"] == od.REFRESH_DONE, rep
    assert len(od.parse_options(card.read_text(encoding="utf-8"))) == 2
    # Причина названа числами, а не «обновлено» — читателю отчёта нужен ЗАМЕР.
    assert "0" in rep["detail"] and "2" in rep["detail"]


def test_refresh_makes_the_buttonless_reason_stop_being_card_stale_vs_origin(repo, tmp_path):
    """Приёмка карточки-задания п.3: проверять ЭФФЕКТ, а не вызов.

    До починки сторож обязан говорить `card_stale_vs_origin` (это и есть авария),
    после — что угодно, кроме неё. Тест сломается и если починка перестанет
    работать, и если сторож разучится опознавать исходное состояние.
    """
    card = _stale(repo)
    before = br.explain(card, now=NOW, beacon_path=_beacon(tmp_path), ref=REF)
    assert before.code == br.CODE_STALE_VS_ORIGIN, before

    od.refresh_live_copy_from_ref(card, ref=REF)

    after = br.explain(card, now=NOW, beacon_path=_beacon(tmp_path), ref=REF)
    assert after.code != br.CODE_STALE_VS_ORIGIN, after
    # И это не «другая причина отказа»: кнопки собираются, вопрос стал отвечаемым.
    assert after.code == br.CODE_HEAL_PENDING, after


# ===========================================================================
# ОБРАТНЫЕ КОНТРОЛИ: чего перезапись не смеет коснуться НИ ПРИ КАКОМ расхождении
# ===========================================================================
def test_live_copy_carrying_the_owner_answer_is_never_overwritten(repo):
    """Главный запрет #178. Расхождение тел здесь ровно то же — решает СЛЕД ОТВЕТА."""
    card = _stale(repo, live_answer=True)
    before = card.read_text(encoding="utf-8")

    rep = od.refresh_live_copy_from_ref(card, ref=REF)

    assert rep["verdict"] == od.REFRESH_OWNER_ANSWER, rep
    assert card.read_text(encoding="utf-8") == before, "ответ владельца затёрт"


def test_closed_live_copy_is_not_reopened_by_a_refresh(repo):
    """Статус живой копии не `needs-owner` ⇒ вопрос уже не на владельце.

    Перезапись телом с ref вернула бы `status: needs-owner` и воскресила бы
    закрытый вопрос — тот же ущерб, что и стёртый ответ, только незаметнее.
    """
    card = _stale(repo, live_status="ingested")
    before = card.read_text(encoding="utf-8")

    rep = od.refresh_live_copy_from_ref(card, ref=REF)

    assert rep["verdict"] == od.REFRESH_STATUS, rep
    assert card.read_text(encoding="utf-8") == before


def test_card_closed_on_the_ref_does_not_overwrite_an_open_live_question(repo):
    """Обратная сторона: закрыт вопрос на ref, а в дереве он ещё открыт."""
    card = _write(repo, "own-33", _WITH_OPTIONS, status="ingested")
    _commit(repo)
    card.write_text(_card_text(_WITHOUT_OPTIONS), encoding="utf-8")
    before = card.read_text(encoding="utf-8")

    rep = od.refresh_live_copy_from_ref(card, ref=REF)

    assert rep["verdict"] == od.REFRESH_STATUS, rep
    assert card.read_text(encoding="utf-8") == before


def test_answer_trace_on_the_ref_is_a_carry_job_not_a_refresh(repo):
    """След ответа на ref — работа `carry_owner_answer`, и через эту дверь он не ходит.

    Иначе обновление вопроса стало бы задним ходом для записи ответа владельца
    мимо `record_owner_answer` (инв. #14 живёт внутри писателя, а не здесь).
    """
    card = _write(repo, "own-33", _WITH_OPTIONS, answer=True)
    _commit(repo)
    card.write_text(_card_text(_WITHOUT_OPTIONS), encoding="utf-8")
    before = card.read_text(encoding="utf-8")

    rep = od.refresh_live_copy_from_ref(card, ref=REF)

    assert rep["verdict"] == od.REFRESH_OWNER_ANSWER, rep
    assert card.read_text(encoding="utf-8") == before


def test_ref_without_options_is_not_richer_and_changes_nothing(repo):
    """«ref новее» — НЕ основание. Основание ровно одно: там выбор есть, здесь нет."""
    card = _write(repo, "own-33", _WITHOUT_OPTIONS)
    _commit(repo)
    card.write_text(_card_text(_WITHOUT_OPTIONS + "\nДописано в дереве.\n"),
                    encoding="utf-8")
    before = card.read_text(encoding="utf-8")

    rep = od.refresh_live_copy_from_ref(card, ref=REF)

    assert rep["verdict"] == od.REFRESH_NOT_STALE, rep
    assert card.read_text(encoding="utf-8") == before


def test_live_copy_that_already_has_options_is_left_alone(repo):
    """У живой копии выбор уже есть — она не «отставшая», и трогать её нечем."""
    card = _write(repo, "own-33", _WITHOUT_OPTIONS)
    _commit(repo)
    card.write_text(_card_text(_WITH_OPTIONS), encoding="utf-8")
    before = card.read_text(encoding="utf-8")

    rep = od.refresh_live_copy_from_ref(card, ref=REF)

    assert rep["verdict"] == od.REFRESH_NOT_STALE, rep
    assert card.read_text(encoding="utf-8") == before


def test_card_absent_on_the_ref_is_named_and_not_confused_with_agreement(repo):
    """Карточка, рождённая в живом дереве: сверять не с чем — это не «не отстала»."""
    card = _write(repo, "own-new", _WITHOUT_OPTIONS)
    _commit(repo)
    (_tracker(repo) / "own-new.md").unlink()
    _commit(repo, "remove")
    card = _write(repo, "own-new", _WITHOUT_OPTIONS)
    before = card.read_text(encoding="utf-8")

    rep = od.refresh_live_copy_from_ref(card, ref=REF)

    assert rep["verdict"] == od.REFRESH_ABSENT_ON_REF, rep
    assert card.read_text(encoding="utf-8") == before


def test_unmeasurable_ref_refuses_and_says_so_instead_of_reporting_success(tmp_path):
    """Не git-дерево ⇒ сверка не выполнилась. «Не измерено» не выдаёт себя за «ок»."""
    d = tmp_path / "nowhere" / origin_view.TRACKER_REL
    d.mkdir(parents=True)
    card = d / "own-33.md"
    card.write_text(_card_text(_WITHOUT_OPTIONS), encoding="utf-8")
    before = card.read_text(encoding="utf-8")

    rep = od.refresh_live_copy_from_ref(card, ref="no-such-ref")

    assert rep["verdict"] == od.REFRESH_UNMEASURED, rep
    assert rep["measured"] is False
    assert card.read_text(encoding="utf-8") == before


def test_missing_live_copy_never_raises(tmp_path):
    """Обновление не важнее уведомления: упасть здесь = потерять вопрос владельцу."""
    rep = od.refresh_live_copy_from_ref(tmp_path / "gone.md", ref=REF)
    assert rep["verdict"] == od.REFRESH_UNMEASURED, rep


# ===========================================================================
# ПРОВОДКА: чинится ТА отправка, а не следующая
# ===========================================================================
def _make_origin_main(repo: Path):
    """Настоящий ref `origin/main` — чтобы проверять умолчание, а не подставленный REF."""
    _run(repo, "update-ref", "refs/remotes/origin/main", "HEAD")


def test_materialize_card_refreshes_an_existing_stale_live_copy(repo, tmp_path):
    """`materialize_card` возвращал существующую копию НЕ ГЛЯДЯ — четыре раза подряд.

    Запрет «не копировать поверх» не ослаблен: он стал первым из четырёх условий,
    а не единственным правилом.
    """
    card = _stale(repo)
    _make_origin_main(repo)
    src_dir = tmp_path / "worktree" / origin_view.TRACKER_REL
    src_dir.mkdir(parents=True)
    src = src_dir / "own-33.md"
    src.write_text(_card_text(_WITH_OPTIONS), encoding="utf-8")

    out = od.materialize_card(src, live_root=repo)

    assert out == card
    assert len(od.parse_options(card.read_text(encoding="utf-8"))) == 2


def test_notify_refreshes_before_building_the_message_not_after(repo):
    """Порядок и есть починка: обновление ПОСЛЕ `load_card` вылечило бы следующий раз.

    Проверяется ЭФФЕКТ на тексте, который уедет владельцу: блок «Варианты:»
    собирается только из разобранных вариантов (`build_message`), и от живости
    маячка он НЕ зависит — иначе тест мерил бы состояние бота, а не порядок шагов.
    """
    from spa_core.owner_queue import notify as nt

    card = _stale(repo)
    _make_origin_main(repo)

    msg = nt.notify_needs_owner(card, dry_run=True)

    assert "<b>Варианты:</b>" in msg, msg
    assert len(od.parse_options(card.read_text(encoding="utf-8"))) == 2
