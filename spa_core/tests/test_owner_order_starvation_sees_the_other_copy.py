#!/usr/bin/env python3
"""Сторож голодания читал НЕ ТУ копию очереди и верил статусу «в работе» (#484).

КАЖДЫЙ тест здесь — положительный контроль ИЗМЕРЕННОЙ аварии 2026-09-04, а не украшение.

**Что измерено.** `scripts/check_owner_order_starvation.py` написан РАДИ одной карточки —
`inbox-task-portfolio-cio-dynamic-capital-alloc`: она несёт «## УКАЗАНИЕ ВЛАДЕЛЬЦА
2026-08-22: ЗАПУСТИТЬ СЛЕДУЮЩИМ ЦИКЛОМ», приоритет `critical`, и простояла невзятой при
40+ прошедших циклах. 04.09 он ответил **код 0, «голодающих приказов нет»** — и ответил
честно, по своему контракту. Приказ при этом голодал уже 329 часов.

Слепота была ДВОЙНОЙ, и каждая половина сама по себе достаточна:

| | прод-дерево | `origin/main` |
|---|---|---|
| `status` | `done` | `in-progress` |
| `priority` | `high` | **`critical`** |
| блок «УКАЗАНИЕ ВЛАДЕЛЬЦА …» | **ОТСУТСТВУЕТ** | есть |

1. **Читалась не та копия.** `nimbalyst-local/` в прод-дерево не возит НИКТО (автосинк
   берёт только `spa_core/` · `scripts/` · `tests/`), поэтому сторож, читающий очередь с
   диска, отвечает про КАТАЛОГ, а читается как ответ про ОЧЕРЕДЬ. Прод-копию закрыл 31.08
   голый однострочник `python3 -c` в ходе массового закрытия 34 карточек; приказа в ней нет
   вообще.
2. **Статус «в работе» выводил карточку из-под сторожа НАВСЕГДА.** `STARVING_STATUSES` —
   только `new`/`backlog`; достаточно один раз «взять» карточку и умереть. `in-progress`
   поставила `cycle-96657` 26.08, а вердикт занятости тем же кодом, что у шагов 0a/0b, —
   `free`: «захватов не найдено, всё измерено». Статус говорит «в работе», работать некому
   девять суток.

**Замер после починки** (живая очередь, 895 карточек на `origin/main`): критических карточек
с маркером приказа — **ОДНА**, ровно та самая. Шума новая проверка не создаёт: было «код 0,
не найдено», стало «код 1, приказ от 2026-08-22, стоит `in-progress` 329.4 ч, мимо прошло
циклов 231, копия: origin/main, держателя НЕТ (`free`)».

**Третья половина, найденная тем же прогоном:** `check_card_claim` берёт журнал объявлений
от СВОЕГО `data/`, а `data/` в git-worktree нет ПО ПОСТРОЕНИЮ — из worktree измеритель
отвечал `unchecked` («журнала нет»), и весь ответ вырождался в «не измерено». Журнал
передаётся явно, тем же значением, которым сторож меряет «сколько циклов мимо».

Время здесь — ВХОД (`now=`), личность держателя — ВХОД (`claim_verdict=`); ни одна проверка
не спрашивает о них живую машину.
"""
from __future__ import annotations

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

import check_owner_order_starvation as starv  # noqa: E402

REF = "main"
# FROZEN-DATE-OK: injected-clock — обе стороны закреплены: дата приказа стои́т в фикстуре,
# а `now` передаётся параметром `now=NOW` в КАЖДЫЙ вызов; календарь на вердикт не влияет.
ORDER_DATE = "2026-08-22"
NOW = datetime(2026, 9, 4, 17, 0, tzinfo=timezone.utc)

_ORDER_BODY = (f"## УКАЗАНИЕ ВЛАДЕЛЬЦА {ORDER_DATE} (cloud-сессия): ЗАПУСТИТЬ СЛЕДУЮЩИМ ЦИКЛОМ\n\n"
               "Начать работу по CIO.\n")


def _run(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


def _card(*, status, priority, body=_ORDER_BODY, title="TASK — Portfolio CIO"):
    return (f"---\ntrackerStatus:\n  type: inbox\ntitle: \"{title}\"\n"
            f"status: {status}\npriority: {priority}\n---\n\n{body}\n")


@pytest.fixture()
def repo(tmp_path):
    """Репозиторий с трекером и веткой-«origin». Сети нет."""
    root = tmp_path / "repo"
    (root / "nimbalyst-local" / "tracker").mkdir(parents=True)
    _run(root.parent, "init", "-q", "-b", REF, str(root))
    _run(root, "config", "user.email", "t@example.com")
    _run(root, "config", "user.name", "test")
    return root


def _tracker(root: Path) -> Path:
    return root / "nimbalyst-local" / "tracker"


def _write(root: Path, name: str, text: str) -> Path:
    p = _tracker(root) / f"{name}.md"
    p.write_text(text, encoding="utf-8")
    return p


def _commit(root: Path, msg="c"):
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", msg)


def _incident(root: Path):
    """Авария дословно: на ref приказ жив, в дереве его закрыли и стёрли."""
    _write(root, "order", _card(status="in-progress", priority="critical"))
    _commit(root, "приказ владельца на ref")
    _write(root, "order", _card(status="done", priority="high", body="Закрыто.\n"))


def _free(_card_id):
    return "free", ""


def _claimed(_card_id):
    return "claimed", ""


def _unchecked(_card_id):
    return "unchecked", "журнала объявлений нет"


def test_tree_only_sees_nothing_this_is_the_incident(repo):
    """Половина 1: по дереву сторож честно молчит — приказа там НЕТ."""
    _incident(repo)
    from spa_core.owner_queue.queue import list_cards
    tree = list_cards(tracker_dir=str(_tracker(repo)))
    assert starv.starving_owner_orders(tree, now=NOW, claim_verdict=_free) == [], (
        "предпосылка аварии: в прод-копии ни приоритета `critical`, ни приказа")


def test_ref_copy_surfaces_the_starving_order(repo):
    """Та же очередь, прочитанная с ref, приказ НАХОДИТ."""
    _incident(repo)
    ref_cards = starv.cards_from_ref(_tracker(repo), ref=REF)
    found = starv.starving_owner_orders(ref_cards, now=NOW, claim_verdict=_free,
                                        source=REF)
    assert [f["marker_date"] for f in found] == [ORDER_DATE]
    assert found[0]["source"] == REF, "копия обязана быть НАЗВАНА — их две и они расходятся"


def test_merge_is_fail_closed_one_copy_starving_is_enough(repo):
    """Молчание требует, чтобы голода не увидела НИ ОДНА копия."""
    _incident(repo)
    from spa_core.owner_queue.queue import list_cards
    tree = starv.starving_owner_orders(list_cards(tracker_dir=str(_tracker(repo))),
                                       now=NOW, claim_verdict=_free)
    ref = starv.starving_owner_orders(starv.cards_from_ref(_tracker(repo), ref=REF),
                                      now=NOW, claim_verdict=_free, source=REF)
    merged = starv.merge_findings(tree, ref)
    assert len(merged) == 1 and merged[0]["source"] == REF


def test_unreadable_ref_is_a_third_outcome_not_an_empty_queue(tmp_path):
    """Ref не читается ⇒ Unmeasured наружу. Пустой список означал бы «там голода нет»."""
    tracker = tmp_path / "nimbalyst-local" / "tracker"
    tracker.mkdir(parents=True)
    with pytest.raises(starv.origin_view.Unmeasured):
        starv.cards_from_ref(tracker, ref="no-such-ref")


def test_in_progress_without_a_holder_is_starvation(repo):
    """Половина 2: статус «в работе» — вопрос, а не ответ."""
    _write(repo, "order", _card(status="in-progress", priority="critical"))
    _commit(repo)
    cards = starv.cards_from_ref(_tracker(repo), ref=REF)
    found = starv.starving_owner_orders(cards, now=NOW, claim_verdict=_free, source=REF)
    assert len(found) == 1, "держателя НЕТ — карточка голодает, что бы ни говорил статус"
    assert "держателя НЕТ" in found[0]["held_check"]
    assert "free" in found[0]["held_check"], "вердикт занятости обязан быть НАЗВАН"


def test_in_progress_with_a_live_holder_is_not_starvation(repo):
    """Обратный контроль: живой держатель — это работа, а не голод."""
    _write(repo, "order", _card(status="in-progress", priority="critical"))
    _commit(repo)
    cards = starv.cards_from_ref(_tracker(repo), ref=REF)
    assert starv.starving_owner_orders(cards, now=NOW, claim_verdict=_claimed,
                                       source=REF) == []


def test_unmeasured_holder_is_starvation_and_says_why(repo):
    """«Занятость не измерена» — fail-CLOSED, и причина НАЗЫВАЕТСЯ.

    Молчаливое «наверное, кто-то держит» — самое успокоительное из прочтений, и ровно оно
    скрывало приказ. «Не измерено» без причины неотличимо от «нечем проверить сегодня».
    """
    _write(repo, "order", _card(status="in-progress", priority="critical"))
    _commit(repo)
    cards = starv.cards_from_ref(_tracker(repo), ref=REF)
    found = starv.starving_owner_orders(cards, now=NOW, claim_verdict=_unchecked,
                                        source=REF)
    assert len(found) == 1
    assert "НЕ ИЗМЕРЕНА" in found[0]["held_check"]
    assert "журнала объявлений нет" in found[0]["held_check"]


def test_without_a_claim_measurer_in_progress_is_not_guessed(repo):
    """`claim_verdict` не передан ⇒ статус «в работе» не судится вовсе.

    Это не послабление, а отказ гадать: измеритель — ВХОД, и его отсутствие обязано
    выглядеть как «не спрашивали», а не как «спросили и никого не нашли».
    """
    _write(repo, "order", _card(status="in-progress", priority="critical"))
    _commit(repo)
    cards = starv.cards_from_ref(_tracker(repo), ref=REF)
    assert starv.starving_owner_orders(cards, now=NOW, source=REF) == []


def test_new_status_still_starves_without_any_holder_question(repo):
    """Прежнее условие целое: невзятая карточка голодает и без разговора о держателе."""
    _write(repo, "order", _card(status="new", priority="critical"))
    _commit(repo)
    cards = starv.cards_from_ref(_tracker(repo), ref=REF)
    found = starv.starving_owner_orders(cards, now=NOW, source=REF)
    assert len(found) == 1
    assert found[0]["held_check"] == "", (
        "пустая строка = «карточка не взята вовсе», это НЕ «держателя искали и не нашли»")


def test_non_critical_and_markerless_cards_stay_out(repo):
    """Сигнал остаётся узким: приоритет И маркер приказа, а не любая карточка."""
    _write(repo, "loud", _card(status="new", priority="high"))
    _write(repo, "quiet", _card(status="new", priority="critical", body="Просто задача.\n"))
    _commit(repo)
    cards = starv.cards_from_ref(_tracker(repo), ref=REF)
    assert starv.starving_owner_orders(cards, now=NOW, claim_verdict=_free,
                                       source=REF) == []


def test_render_names_the_copy_and_the_holder_verdict(repo):
    """Читателю нужны ОБА: в какой копии увидели и почему статус не означает работу."""
    _incident(repo)
    found = starv.starving_owner_orders(starv.cards_from_ref(_tracker(repo), ref=REF),
                                        now=NOW, claim_verdict=_free, source=REF)
    text = starv.render(found, starv.DEFAULT_MIN_HOURS)
    assert f"[копия: {REF}]" in text
    assert "держателя НЕТ" in text
