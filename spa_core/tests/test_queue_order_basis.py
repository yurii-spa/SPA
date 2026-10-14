"""БАЗИС вердикта порядка: ЧЕМ он добыт, машинным словом (ADR-719, заказ G718 п. 1).

ПРЕДМЕТ. Осей порядка две и они независимы — отметка о движении (`mark_order`, ADR-220)
и след переходов (`trail_order`, ADR-544). До цикла #863 до читателя очереди доезжал
ОДИН вердикт, а «какая из двух мерок говорила, а какая молчала» читалось только из ПРОЗЫ
`order_detail`. Разбор подстрокой запрещён (ADR-333), то есть машинно это не читалось
никак.

ЗАМЕР ДО ПРАВКИ (14.10, живой прод-трекер, origin/main 55eb3db5c, 787 карточек,
расошедшихся пар 170; базис пересчитан ТОЛЬКО для замера):

    вердикт `unmeasured`  112 = neither_decided 108 + axes_disagree   4
    вердикт `tree_newer`   27 = mark_only        27
    вердикт `origin_newer` 31 = trail_only       19 + mark_only 10 + both_agree 2
    полей, называющих ОСЬ поимённо: НИ ОДНОГО

ЧЕМ ЭТО ВРЕДНО — два следствия, и оба про РЕШЕНИЯ, а не про оформление:

1. `unmeasured` несёт ДВА РАЗНЫХ состояния под одним именем: «обе оси спросили, и ни
   одна не решила» (108 — штатная тишина) и «обе решили и РАСХОДЯТСЯ» (4 — тревога
   fail-CLOSED, предмет ADR-544). Ровно тот дефект, который ADR-718 снял уровнем выше
   («не сверяли» против «сверили и не решили»); внутри самого `unmeasured` он остался.
   Один из тех четырёх — карточка РЕШЕНИЯ ВЛАДЕЛЬЦА
   (`owner-decision-kritichnaya-nahodka-petli-com-spa-digest-2`).
2. Все **27** вердиктов `tree_newer` стоят на `mark_only` — на ОДНОЙ оси, и именно той,
   которая на 8 живых парах выдала неверный `tree_newer` из джиттера писателя в 68–175
   мкс (ADR-544). Цена ложного `tree_newer` там же названа: запись `owner-done` поверх
   `ingested`, то есть РАСКРЫТИЕ решения владельца. Сессия, читающая вердикт, не могла
   отличить «обе оси согласны» (так добыты 2) от «говорила только склонная к джиттеру»
   (27).

ЧТО ЗДЕСЬ ЗАКРЕПЛЕНО. Инвариант #17 в его СЛАБОМ месте: мало чтобы «не измерено» было
отдельным значением — различимы обязаны быть и РАЗНЫЕ ПРИЧИНЫ одного «не измерено».
Плюс: правка НИ В ОДНОЙ ветке не меняет ни вердикт, ни прозу (звенья 3 и 4), и
fail-CLOSED ADR-544 не ослаблен (звено 5).

ВРЕМЯ И ГИТ — входы сцены, а не окружение (`.claude/rules/deployment.md`): одноразовый
репозиторий создаётся `git init -b <имя>`, и то же имя читают все ссылки сцены.
"""

from __future__ import annotations

import contextlib
import io
import itertools
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import check_tracker_drift as drift          # noqa: E402
import orchestrator_queue as oq              # noqa: E402

#: Имя ветки сцены — ВХОД, а не умолчание хоста (`init.defaultBranch` на `ubuntu-latest`
#: даёт `master`, Apple Git на Маке — `main`).
SCENE_REF = "scene-main"

_BAD_REF = "refs/heads/no-such-ref-here"

# FROZEN-DATE-OK: дата ЕСТЬ предмет — `mark_order` сравнивает ровно эти две отметки
# МЕЖДУ СОБОЙ, и измеряется их ПОРЯДОК. Часов в мерке нет вовсе: ни «сегодня», ни окна
# свежести, ни TTL — стареть здесь нечему, и сдвиг календаря вердикта не меняет.
# Инъекция часов (приём №1 `.claude/rules/deployment.md`) невозможна по построению:
# функции, которой их передать, здесь не существует.
EARLIER = "2026-09-01T00:00:00+00:00"
LATER = "2026-10-01T00:00:00+00:00"


def _card(status: str, trail: tuple[str, ...] = (), body: str = "тело") -> str:
    head = ["---", "type: inbox", f"status: {status}", 'title: "TASK — карточка сцены"']
    if trail:
        head.append("status_trail:")
        head += [f'  - "{t}"' for t in trail]
    head += ["---", "", body, ""]
    return "\n".join(head)


#: Пять сцен — по одной на КАЖДОЕ слово вокабуляра прибора, и ни одной лишней.
#:
#: Сцена здесь — ПАРА ТЕКСТОВ (копия дерева, копия ref) со своими статусами. Пара
#: подобрана так, чтобы оси сказали ровно то, что нужно базису:
#:
#: * `both_agree`      — отметка дерева РАНЬШЕ, статус ref в следе дерева не встречался;
#: * `axes_disagree`   — отметка дерева ПОЗЖЕ (`tree_newer`), а след говорит `origin_newer`;
#: * `mark_only`       — статусы СОВПАДАЮТ (след порядка не устанавливает), отметки есть у обеих;
#: * `trail_only`      — у копии ref отметок нет вовсе (отметки fail-CLOSED), след полон;
#: * `neither_decided` — у ref отметок нет И статусы совпадают: молчат обе.
_SCENES: dict[str, tuple[str, str, str, str]] = {
    drift.BASIS_BOTH_AGREE: (
        _card("in-progress", (f"{EARLIER} new -> in-progress · queue.set_status · c1",), "дерево"),
        _card("done", (f"{LATER} new -> done · queue.set_status · c2",), "ref"),
        "in-progress", "done"),
    drift.BASIS_AXES_DISAGREE: (
        _card("in-progress", (f"{LATER} new -> in-progress · queue.set_status · c1",), "дерево"),
        _card("done", (f"{EARLIER} new -> done · queue.set_status · c2",), "ref"),
        "in-progress", "done"),
    drift.BASIS_MARK_ONLY: (
        _card("done", (f"{LATER} new -> done · queue.set_status · c1",), "дерево"),
        _card("done", (f"{EARLIER} new -> done · queue.set_status · c2",), "ref"),
        "done", "done"),
    drift.BASIS_TRAIL_ONLY: (
        _card("in-progress", (f"{EARLIER} new -> in-progress · queue.set_status · c1",), "дерево"),
        _card("done", (), "ref"),
        "in-progress", "done"),
    drift.BASIS_NEITHER_DECIDED: (
        _card("new", (f"{EARLIER} new -> new · queue.set_status · c1",), "дерево"),
        _card("new", (), "ref"),
        "new", "new"),
}


def _axes(basis: str) -> drift.OrderVerdict:
    tree_text, origin_text, tree_status, origin_status = _SCENES[basis]
    return drift.combined_order_axes(tree_text, origin_text, tree_status, origin_status)


# ── звено 1: вокабуляр ПОЛОН — ни одна пара осей не выпадает ──────────────────────

def test_link1_every_pair_of_axis_verdicts_gets_a_basis() -> None:
    """Звено 1: базис есть у КАЖДОЙ пары вердиктов осей — обходом словаря, не парой из головы.

    Пара значений из головы не краснеет от нового слова в вокабуляре оси; обход краснеет.
    Это тот же приём, которым #862 собирал набор имён прибора.
    """
    vocabulary = sorted(drift.ORDER_DECIDED | {drift.ORDER_UNMEASURED})
    assert len(vocabulary) == 3, f"вокабуляр оси изменился — пересмотри сцены: {vocabulary}"
    for mark, trail in itertools.product(vocabulary, repeat=2):
        got = drift._order_basis(mark, trail)
        assert got in drift.ORDER_BASES, (
            f"пара осей ({mark}, {trail}) выпала из вокабуляра базиса: {got!r}")


def test_link1b_every_declared_basis_is_reached_by_a_real_scene() -> None:
    """Звено 1б: каждое слово вокабуляра ДОСТИГАЕТСЯ настоящим зовом — мёртвых слов нет.

    Обратная сторона: объявленное и недостижимое значение есть то самое «всегда зелёное
    поле», которое проект уже снимал как ложное успокоение (#810). Равенство множеств,
    а не включение: и лишняя сцена, и необъявленное слово обязаны краснить.
    """
    assert set(_SCENES) == set(drift.ORDER_BASES), (
        f"вокабуляр и сцены разошлись: без сцены {sorted(drift.ORDER_BASES - set(_SCENES))}, "
        f"лишние сцены {sorted(set(_SCENES) - drift.ORDER_BASES)}")
    for basis in drift.ORDER_BASES:
        assert _axes(basis).basis == basis, (
            f"сцена для {basis!r} до него не доводит: {_axes(basis)}")


# ── звено 2: базис ВЫВОДИТСЯ ИЗ ПАРЫ, и вывод этот ОДИН ───────────────────────────

def test_link2_basis_is_derived_from_the_pair_it_reports() -> None:
    """Звено 2: базис согласован с парой осей, которую сам же несёт.

    Базис и пара — две формы одного факта, и расходиться им нельзя: вывод живёт в ОДНОМ
    месте (`_order_basis`), а не у каждого читателя (ADR-220).
    """
    for basis in drift.ORDER_BASES:
        got = _axes(basis)
        assert drift._order_basis(got.mark, got.trail) == got.basis, got


# ── звено 3: ВЕРДИКТ и ПРОЗА правкой НЕ ТРОНУТЫ (свойство, которое правка СОХРАНЯЕТ) ──

def test_link3_verdict_matches_the_combination_rule_on_every_basis() -> None:
    """Звено 3: сведение осей не изменилось ни в одной из пяти ветвей.

    Правка добавляет ответ на вопрос «чем добыт», а не переписывает «что добыто». Если
    бы она сдвинула хоть одну ветвь, это звено покраснело бы — и оно зелено ДО правки
    тоже (кроме обращений к новым полям), что в дифференциальном замере и видно.
    """
    expected = {
        drift.BASIS_BOTH_AGREE: drift.ORDER_ORIGIN_NEWER,
        drift.BASIS_AXES_DISAGREE: drift.ORDER_UNMEASURED,
        drift.BASIS_MARK_ONLY: drift.ORDER_TREE_NEWER,
        drift.BASIS_TRAIL_ONLY: drift.ORDER_ORIGIN_NEWER,
        drift.BASIS_NEITHER_DECIDED: drift.ORDER_UNMEASURED,
    }
    for basis, want in expected.items():
        assert _axes(basis).verdict == want, (basis, _axes(basis))


def test_link4_the_old_shape_is_a_shim_over_one_implementation() -> None:
    """Звено 4: прежняя форма (вердикт, причина) — та же мерка, а не вторая её копия.

    Второй экземпляр сведения «для старых вызывающих» расходится молча — ADR-220 ровно
    про это. Сверка побайтовая, включая прозу.
    """
    for basis, (tree_text, origin_text, ts, os_) in _SCENES.items():
        got = drift.combined_order_axes(tree_text, origin_text, ts, os_)
        assert drift.combined_order(tree_text, origin_text, ts, os_) == (got.verdict,
                                                                        got.detail), basis


def test_link5_disagreeing_axes_still_refuse_a_verdict() -> None:
    """Звено 5: `axes_disagree` по-прежнему БЕЗ вердикта — fail-CLOSED ADR-544 не ослаблен.

    Соблазн «раз мы теперь называем базис, можно и выбрать ось» прямо противоречит
    ADR-544: предпочтение одной оси возвело бы разбор восьми случаев в машинное правило.
    Базис делает состояние ВИДИМЫМ, вердикта он не добывает.
    """
    got = _axes(drift.BASIS_AXES_DISAGREE)
    assert got.verdict == drift.ORDER_UNMEASURED, got
    assert got.mark in drift.ORDER_DECIDED and got.trail in drift.ORDER_DECIDED, got
    assert got.mark != got.trail, got


# ── сцена ЧИТАТЕЛЯ: настоящий одноразовый репозиторий и настоящая команда шага 1 ──

def _git(cwd: Path, *args: str) -> None:
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                       timeout=120)
    if r.returncode != 0:
        pytest.fail(f"предпосылка сцены НЕ ОБЕСПЕЧЕНА: git {' '.join(args)} → "
                    f"{r.returncode}: {r.stderr.strip()}")


def _repo(root: Path) -> Path:
    tracker = root / drift.TRACKER_REL
    tracker.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", SCENE_REF, str(root)], check=True,
                   capture_output=True, timeout=120)
    _git(root, "config", "user.email", "probe@example.com")
    _git(root, "config", "user.name", "probe")
    return tracker


def _scene_on_disk(tmp_path: Path, basis: str) -> Path:
    """Разложить пару текстов сцены по двум копиям: ref — в коммит, дерево — поверх.

    Копия дерева НЕ попадает в историю, поэтому `_proven_behind` её прежней версией ref
    не признаёт, и класс находки — `diverged`, где ось порядка и спрашивается.
    """
    tree_text, origin_text, _ts, _os = _SCENES[basis]
    root = tmp_path / "repo"
    tracker = _repo(root)
    card = tracker / "inbox-order.md"
    card.write_text(origin_text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "ref")
    card.write_text(tree_text, encoding="utf-8")
    return tracker


class _Args:
    json = True
    type = None
    status = None
    now = None

    def __init__(self, tracker_dir: Path, ref: str | None, origin_check: bool = True):
        self.tracker_dir = str(tracker_dir)
        self.ref = ref
        self.origin_check = origin_check


def _ask(args: _Args) -> tuple[int, list[dict], str]:
    """Спросить НАСТОЯЩУЮ команду шага 1 → (код, карточки из JSON, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = oq.cmd_list(args)
    return rc, json.loads(out.getvalue()), err.getvalue()


def _only(cards: list[dict]) -> dict:
    assert len(cards) == 1, f"предпосылка сцены НЕ ОБЕСПЕЧЕНА: карточек {len(cards)}"
    return cards[0]


# ── звено 6: базис ДОЕЗЖАЕТ до читателя машинным полем ───────────────────────────

@pytest.mark.parametrize("basis", sorted(drift.ORDER_BASES))
def test_link6_reader_carries_the_basis_machine_readably(tmp_path: Path, basis: str) -> None:
    """Звено 6: у читателя есть `origin_order_basis` и пара осей — на КАЖДОМ базисе.

    Параметризация по вокабуляру, а не по паре значений: новое слово базиса без проводки
    до читателя обязано краснить само.
    """
    tracker = _scene_on_disk(tmp_path, basis)
    _rc, cards, _err = _ask(_Args(tracker, SCENE_REF))
    card = _only(cards)
    want = _axes(basis)
    assert card.get("origin_order_basis") == basis, (
        f"базис не доехал до читателя — ровно замер до ADR-719: «чем добыт вердикт» "
        f"читалось только из прозы. карточка: {card}")
    assert card.get("origin_order_mark") == want.mark, card
    assert card.get("origin_order_trail") == want.trail, card
    assert card.get("origin_order") == want.verdict, card


def test_link7_one_verdict_two_bases_are_distinguishable(tmp_path: Path) -> None:
    """Звено 7 — ПРЕДМЕТ ЗАКАЗА: `axes_disagree` и `neither_decided` различимы МАШИННО.

    Оба несут ОДИН вердикт `unmeasured` (и это верно — fail-CLOSED), и до #863 этим
    вердиктом исчерпывалось всё, что читатель знал. На живой популяции под ним стояли
    108 штатных тишин и 4 тревоги.
    """
    clash = _only(_ask(_Args(_scene_on_disk(tmp_path / "a", drift.BASIS_AXES_DISAGREE),
                             SCENE_REF))[1])
    quiet = _only(_ask(_Args(_scene_on_disk(tmp_path / "b", drift.BASIS_NEITHER_DECIDED),
                             SCENE_REF))[1])
    assert clash["origin_order"] == quiet["origin_order"] == drift.ORDER_UNMEASURED, (
        "предпосылка сцены НЕ ОБЕСПЕЧЕНА: вердикты уже различны, и различать базисом "
        f"было бы нечего — {clash}, {quiet}")
    assert clash["origin_order_basis"] != quiet["origin_order_basis"], (clash, quiet)
    assert clash["origin_order_basis"] == drift.BASIS_AXES_DISAGREE, clash
    assert quiet["origin_order_basis"] == drift.BASIS_NEITHER_DECIDED, quiet


def test_link8_basis_is_readable_without_touching_the_prose(tmp_path: Path) -> None:
    """Звено 8: ответ добывается ПОЛЕМ, а не разбором подстроки (ADR-333).

    Проверка устроена так, чтобы покраснеть, если базис окажется куском прозы: значение
    обязано быть ТОЧНЫМ членом вокабуляра, а не подстрокой `origin_order_detail`.
    """
    card = _only(_ask(_Args(_scene_on_disk(tmp_path, drift.BASIS_AXES_DISAGREE),
                            SCENE_REF))[1])
    basis = card["origin_order_basis"]
    assert basis in drift.ORDER_BASES, card
    assert basis not in card["origin_order_detail"], (
        "базис читается как подстрока прозы — значит проза и есть носитель ответа, "
        f"а это запрещено (ADR-333): {card}")


# ── звено 9: ДВЕРИ ОТКАЗА — слово ЧИТАТЕЛЯ, а не подстановка слова прибора ───────

@pytest.mark.parametrize("door,make_args", [
    ("ref неразрешим", lambda t: _Args(t, _BAD_REF)),
    ("сверку выключили", lambda t: _Args(t, SCENE_REF, origin_check=False)),
])
def test_link9_refusal_doors_say_the_axis_was_never_asked(tmp_path: Path, door: str,
                                                          make_args) -> None:
    """Звено 9: за дверью отказа базис — `not_asked`, и обе оси `not_compared`.

    Отсутствие полей здесь читалось бы как «ось не спрашивают у этого класса», то есть
    как штатная тишина — подмена, против которой написан ADR-718.
    """
    tracker = _scene_on_disk(tmp_path, drift.BASIS_AXES_DISAGREE)
    _rc, cards, _err = _ask(make_args(tracker))
    card = _only(cards)
    assert card.get("origin_order") == oq.ORDER_NOT_COMPARED, (door, card)
    assert card.get("origin_order_basis") == oq.BASIS_NOT_ASKED, (door, card)
    assert card.get("origin_order_mark") == oq.ORDER_NOT_COMPARED, (door, card)
    assert card.get("origin_order_trail") == oq.ORDER_NOT_COMPARED, (door, card)


def test_link10_the_doors_word_is_not_borrowed_from_the_instrument() -> None:
    """Звено 10: `not_asked` — СВОЁ слово читателя, а не `neither_decided` прибора.

    Подставить `neither_decided` значило бы воспроизвести чинимый дефект на уровень ниже:
    «не спрашивали ни одну» под именем «спросили обе и не узнали». И наоборот — слова
    читателя не должно быть в вокабуляре прибора: прибор его не производит никогда, и
    объявленное там оно было бы всегда мёртвым (#810).
    """
    assert oq.BASIS_NOT_ASKED not in drift.ORDER_BASES
    assert oq.BASIS_NOT_ASKED != drift.BASIS_NEITHER_DECIDED


# ── звено 11: у класса, которого о порядке не спрашивают, полей НЕТ ──────────────

def test_link11_classes_never_asked_about_order_carry_no_basis(tmp_path: Path) -> None:
    """Звено 11: совпавшая карточка не несёт ни вердикта порядка, ни базиса.

    Отсутствие поля — действующий контракт («порядок не мерился, упорядочивать нечего»),
    и штамповать туда значение значило бы завести мёртвое поле на 1159 карточках из 1329
    (замер 14.10 на живом трекере).
    """
    root = tmp_path / "repo"
    tracker = _repo(root)
    (tracker / "inbox-same.md").write_text(_card("new", body="совпадает"), encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "ref")
    _rc, cards, _err = _ask(_Args(tracker, SCENE_REF))
    card = _only(cards)
    assert "origin_order" not in card, card
    assert "origin_order_basis" not in card, (
        "базис появился там, где ось не спрашивают — это мёртвое поле, а не ответ")


# ── звено 12: СТРОКА ТРЕВОГИ в stderr — в обе стороны ───────────────────────────

def test_link12_stderr_names_the_clash_when_there_is_one(tmp_path: Path) -> None:
    """Звено 12: расхождение осей НАЗВАНО человеку отдельной строкой."""
    _rc, _cards, err = _ask(_Args(_scene_on_disk(tmp_path, drift.BASIS_AXES_DISAGREE),
                                  SCENE_REF))
    assert "ОСИ РАСХОДЯТСЯ" in err, err
    assert "inbox-order" in err, err


def test_link12b_stderr_stays_silent_when_axes_do_not_clash(tmp_path: Path) -> None:
    """Звено 12б: без расхождения строки НЕТ — сторож не кричит на каждой находке.

    Обратная сторона звена 12 и урок #243: сторожа, печатающего тревогу всегда,
    выключают, и тогда он молчит и в тот раз, когда тревога настоящая.
    """
    _rc, _cards, err = _ask(_Args(_scene_on_disk(tmp_path, drift.BASIS_NEITHER_DECIDED),
                                  SCENE_REF))
    assert "своя правка в дереве" in err, (
        f"предпосылка сцены НЕ ОБЕСПЕЧЕНА: расхождения копий нет вовсе — {err}")
    assert "ОСИ РАСХОДЯТСЯ" not in err, err


# ── звено 13: ВСЕ ЧЕТЫРЕ двери, включая те, что через CLI не поставить ───────────

class _Card:
    """Минимальная карточка: дверям отказа от неё нужен только идентификатор."""

    def __init__(self, cid: str) -> None:
        self.id = cid


def test_link13_the_door_without_an_instrument_still_carries_the_basis() -> None:
    """Звено 13: в двери «прибора нет вовсе» базис ЖИВ — он слово ЧИТАТЕЛЯ.

    Эта дверь через CLI не ставится (прибор в дереве есть), поэтому мерится прямо у
    функции двери. Асимметрия намеренна и названа в её докстринге: ось ПАМЯТИ теряет и
    меру, и вокабуляр — оба живут в приборе, — а вокабуляр порядка живёт у читателя, и
    отнять его отсутствию прибора нечем.
    """
    rows = oq._axes_unmeasured_without_instrument([_Card("inbox-x")], "прибор не ввезён")
    row = rows["inbox-x"]
    assert row["origin_order"] == oq.ORDER_NOT_COMPARED, row
    assert row["origin_order_basis"] == oq.BASIS_NOT_ASKED, row
    assert row["origin_order_mark"] == oq.ORDER_NOT_COMPARED, row
    assert row["origin_order_trail"] == oq.ORDER_NOT_COMPARED, row


def test_link13b_one_point_feeds_every_refusal_door() -> None:
    """Звено 13б: обе двери берут поля из ОДНОЙ точки — наборы ключей совпадают.

    Четыре места, где третью ось забудут добавить, разъехались бы молча (это и есть довод
    `_axes_unmeasured`). Сверяются КЛЮЧИ, а не причины: причины у дверей РАЗНЫЕ по
    построению — каждая ось собирает свою из своего вопроса.
    """
    withought = oq._axes_unmeasured_without_instrument([_Card("inbox-x")], "прибора нет")
    withdrift = oq._axes_unmeasured([_Card("inbox-x")], "ref неразрешим", drift,
                                    "origin/main")
    order_keys = {k for k in withought["inbox-x"] if k.startswith("origin_order")}
    assert order_keys == {k for k in withdrift["inbox-x"] if k.startswith("origin_order")}, (
        f"двери отказа несут РАЗНЫЕ наборы полей порядка: {order_keys} против "
        f"{ {k for k in withdrift['inbox-x'] if k.startswith('origin_order')} }")
    assert "origin_order_basis" in order_keys, order_keys


# ── звено 14: СВОЙ выход прибора (`as_dict`) тоже несёт базис ────────────────────

def test_link14_instrument_json_output_carries_the_basis() -> None:
    """Звено 14: базис есть и в СОБСТВЕННОМ выходе прибора, не только у читателя.

    Звено добавлено ПО НАХОДКЕ МУТАЦИИ: мутант `"order_basis": self.order_basis` → `""`
    в `Finding.as_dict()` ВЫЖИЛ у батарей #863, потому что все они читают находку
    атрибутом через читателя, а `--json` самого прибора не смотрел никто. Это был не
    равносильный мутант, а дыра покрытия: собственный выход прибора терял базис МОЛЧА.
    """
    got = _axes(drift.BASIS_AXES_DISAGREE)
    f = drift.Finding(kind=drift.KIND_DIVERGED, card_id="inbox-x",
                      order=got.verdict, order_detail=got.detail,
                      order_basis=got.basis, order_mark=got.mark, order_trail=got.trail)
    d = f.as_dict()
    assert d["order_basis"] == got.basis == drift.BASIS_AXES_DISAGREE, d
    assert d["order_mark"] == got.mark, d
    assert d["order_trail"] == got.trail, d
