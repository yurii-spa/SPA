"""Ось ПОРЯДКА при ОТКАЗЕ сверки: третий исход со СВОИМ словом (ADR-718, заказ G717 п. 3).

ПРЕДМЕТ. Цикл #861 (ADR-717) дал третий исход со своей причиной оси ПАМЯТИ копий — во
всех четырёх дверях, за которыми сверка с `origin` не состоялась. И тем же циклом было
НАЗВАНО, что население класса «ось гаснет вместе с соседом» измерено ровно на ОДНОЙ оси
из ТРЁХ: порядок по ОТМЕТКАМ (`mark_order`, ADR-220) и порядок по СЛЕДУ ПЕРЕХОДОВ
(`trail_order`, ADR-544) не проверялся вовсе.

ЗАМЕР ДО ПРАВКИ (14.10, одноразовый репозиторий, та же команда, что зовёт шаг 1
протокола; копии карточки-тетради расходятся, статусы разные, на состоявшейся сверке ось
порядка ОТВЕЧАЕТ): дверей отказа ЧЕТЫРЕ, ось ПАМЯТИ назвала себя в 4 из 4, ось ПОРЯДКА —
в 0 из 4; полей `origin_order*` в этих ветках не было ни одного. На живой популяции
(прод-трекер, 779 карточек, та же команда с неразрешимым ref): `origin_order` несут 0 из
779, строк stderr 4.

ЧЕМ ЭТО ВРЕДНО. В контракте читателя ОТСУТСТВИЕ `origin_order` означает «порядок НЕ
МЕРИЛСЯ» — так у `agrees`/`stale`/`hidden`/`undelivered`, где второй копии для
упорядочивания не существует, и stderr говорит это дословно, ОТДЕЛЬНОЙ строкой от
«порядок НЕ УСТАНОВЛЕН». Значит в дверях отказа два РАЗНЫХ состояния печатались
одинаково: «упорядочивать нечего» и «упорядочить было что, да спросить не удалось».

ЧТО ЗДЕСЬ ЗАКРЕПЛЕНО. Инвариант #17: «не измерено» — ОТДЕЛЬНОЕ значение СО СВОЕЙ
причиной, а не молчание, унаследованное от соседней оси. Причём значение именно СВОЁ:
`ORDER_UNMEASURED` прибора занят состоянием «обе оси спросили, и ни одна не установила
порядок», и подстановка его сюда воспроизвела бы чинимый дефект на уровень ниже.

ВРЕМЯ И ГИТ — входы сцены, а не окружение (`.claude/rules/deployment.md`): одноразовый
репозиторий создаётся `git init -b <имя>`, и то же имя читают все ссылки сцены.
Отметки времени в карточках сцены — ПРЕДМЕТ оси (`mark_order` сравнивает именно их),
поэтому они литеральные и к настенным часам не привязаны ничем.
"""

from __future__ import annotations

import contextlib
import io
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

# FROZEN-DATE-OK: дата ЕСТЬ предмет — `mark_order` сравнивает ровно эти две отметки
# МЕЖДУ СОБОЙ, и измеряется их ПОРЯДОК. Часов в мерке нет вовсе: ни «сегодня», ни окна
# свежести, ни TTL — стареть здесь нечему, и сдвиг календаря вердикта не меняет (это
# проверено шагом 1г цикла, `import_time_anchor_bombs`: при задержке 95 мин ни один
# вердикт не изменился). Инъекция часов (приём №1 `.claude/rules/deployment.md`)
# невозможна по построению: функции, которой их передать, здесь не существует.
EARLIER = "2026-09-01T00:00:00+00:00"
LATER = "2026-10-01T00:00:00+00:00"


def _notebook(records: tuple[int, ...], status: str,
              trail: tuple[str, ...] = (), body: str = "тело приказа") -> str:
    head = ["---", "type: inbox", f"status: {status}",
            'title: "TASK — стоячий приказ владельца"']
    if trail:
        head.append("status_trail:")
        head += [f'  - "{t}"' for t in trail]
    head += ["---", "", body, ""]
    return "\n".join(head) + "".join(
        f"\n## Цикл #{n} (замер цикла {n})\n\nчто сделано в цикле {n}\n" for n in records)


def _git(cwd: Path, *args: str) -> None:
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                       timeout=120)
    if r.returncode != 0:
        pytest.fail(f"предпосылка сцены НЕ ОБЕСПЕЧЕНА: git {' '.join(args)} → "
                    f"{r.returncode}: {r.stderr.strip()}")


def _init(root: Path) -> Path:
    tracker = root / drift.TRACKER_REL
    tracker.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", SCENE_REF, str(root)], check=True,
                   capture_output=True, timeout=120)
    _git(root, "config", "user.email", "probe@example.com")
    _git(root, "config", "user.name", "probe")
    return tracker


@pytest.fixture()
def scene(tmp_path: Path) -> Path:
    """Копии расходятся, статусы РАЗНЫЕ, и на состоявшейся сверке порядок УСТАНОВЛЕН.

    Это важно именно так: сцена, где порядок не устанавливается и на состоявшейся
    сверке, не умеет отличить «ось назвала третий исход» от «ось вообще ничего не
    умеет», и контроль в обратную сторону был бы пустым.
    """
    tracker = _init(tmp_path / "repo")
    root = tmp_path / "repo"
    card = tracker / "inbox-order.md"
    card.write_text(_notebook(
        (716, 717, 718), "new",
        trail=(f"{EARLIER} new -> new · queue.set_status · cycle-1",),
    ), encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "ref")
    card.write_text(_notebook(
        (716,), "in-progress",
        trail=(f"{EARLIER} new -> new · queue.set_status · cycle-1",
               f"{LATER} new -> in-progress · queue.set_status · cycle-2"),
    ), encoding="utf-8")
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


_BAD_REF = "refs/heads/no-such-ref-here"

#: Вердикты, которые означают «ось СПРОСИЛИ» — всё, что умеет сказать прибор.
_ASKED = frozenset({drift.ORDER_TREE_NEWER, drift.ORDER_ORIGIN_NEWER,
                    drift.ORDER_UNMEASURED})


# ── звено 1: сверка СОСТОЯЛАСЬ — всё как было (свойство, которое правка СОХРАНЯЕТ) ──

def test_link1_measured_run_still_decides_the_order(scene: Path) -> None:
    """Звено 1: на состоявшейся сверке ось порядка по-прежнему РЕШАЕТ, а не молчит.

    Обратная сторона правки: читатель, штампующий третий исход на всё, бесполезен ровно
    так же, как молчавший, — отказ снова стал бы неотличим от замера.
    """
    _rc, cards, _err = _ask(_Args(scene, SCENE_REF))
    card = _only(cards)
    assert card["origin_order"] in _ASKED, card
    assert card["origin_order"] == drift.ORDER_TREE_NEWER, (
        "предпосылка сцены НЕ ОБЕСПЕЧЕНА: порядок не устанавливается и на состоявшейся "
        f"сверке, обратный контроль был бы пустым — {card}")
    assert card["origin_check"] == oq.VERDICT_DIVERGED_TREE_NEWER, card


def test_link1b_measured_run_never_carries_the_third_outcome(scene: Path) -> None:
    """Звено 1б: на состоявшейся сверке третьего исхода НЕТ — ось не штампует его на всё.

    Отдельно от звена 1 НАМЕРЕННО: звено 1 обязано быть зелёным и ДО правки (оно про
    свойство, которое правка сохраняет), а это звено называет новое слово и потому до
    правки не существует. Слить их значило бы потерять зелёный контроль «ничего не
    сломано» в дифференциальном замере.
    """
    _rc, cards, _err = _ask(_Args(scene, SCENE_REF))
    assert _only(cards)["origin_order"] != oq.ORDER_NOT_COMPARED, cards


# ── звено 2: `analyze` ОТКАЗАЛ — ось обязана назвать СВОЙ третий исход ─────────────

def test_link2_refused_comparison_states_the_order_axis(scene: Path) -> None:
    """Звено 2: ref неразрешим ⇒ у оси порядка СВОЙ третий исход, а не молчание."""
    rc, cards, _err = _ask(_Args(scene, _BAD_REF))
    card = _only(cards)
    assert card["origin_check"] == oq.VERDICT_UNMEASURED, card
    assert "origin_order" in card, (
        "ось порядка молчит при отказе сверки — ровно замер до ADR-718: «упорядочить "
        "было что, да спросить не удалось» неотличимо от «упорядочивать нечего»")
    assert card["origin_order"] == oq.ORDER_NOT_COMPARED, card
    assert rc == 2


def test_link3_third_outcome_is_its_own_word_not_the_instruments(scene: Path) -> None:
    """Звено 3: третий исход — СВОЁ слово, а не `ORDER_UNMEASURED` прибора.

    `ORDER_UNMEASURED` занят состоянием «обе оси СПРОСИЛИ, и ни одна не установила
    порядок». Подставить его здесь значило бы снова напечатать два разных состояния
    одинаково — чинимый дефект на уровень ниже.
    """
    _rc, cards, _err = _ask(_Args(scene, _BAD_REF))
    verdict = _only(cards)["origin_order"]
    assert verdict not in _ASKED, (
        f"третий исход отказа совпал с вердиктом прибора `{verdict}` — потребитель "
        f"прочтёт «спросили и не решили» вместо «не спрашивали вовсе»")
    assert verdict == oq.ORDER_NOT_COMPARED, verdict


def test_link4_refused_comparison_order_reason_is_its_own(scene: Path) -> None:
    """Звено 4: причина оси говорит о СВОЁМ вопросе, а не пересказывает соседа.

    Вопрос оси (ADR-544) — «какая копия ДАЛЬШЕ ПРОДВИНУЛАСЬ по истории карточки».
    Причина соседа отвечает на вопрос о СОСТАВЕ списка, причина оси памяти — о ЗАПИСЯХ
    ЦИКЛА. Повтори ось чужое слово в слово — своей причины у неё нет, и дефект на месте.
    """
    _rc, cards, _err = _ask(_Args(scene, _BAD_REF))
    card = _only(cards)
    reason = card["origin_order_detail"]
    assert "ДАЛЬШЕ ПРОДВИНУЛАСЬ" in reason, reason
    assert "НЕ ИЗМЕРЕНО" in reason, reason
    assert "не «порядок не мерился»" in reason, reason
    assert "не «порядок НЕ УСТАНОВЛЕН»" in reason, reason
    assert reason != card["origin_memory_detail"], (
        "причина оси порядка дословно совпала с причиной оси памяти — это и есть "
        "наследование от соседа, только теперь с текстом")


def test_link5_both_sub_axes_are_named_not_just_the_axis(scene: Path) -> None:
    """Звено 5: причина называет ОБЕ мерки порядка, а не «порядок» вообще.

    Осей порядка две и они независимы (отметка о движении и след переходов, ADR-544).
    «Порядок не измерен» без имён не отвечает на вопрос, ЧТО именно не спрошено, —
    а чинятся эти две мерки по-разному.
    """
    _rc, cards, _err = _ask(_Args(scene, _BAD_REF))
    reason = _only(cards)["origin_order_detail"]
    assert "mark_order" in reason, reason
    assert "trail_order" in reason, reason


def test_link6_refusal_reaches_the_human_channel_too(scene: Path) -> None:
    """Звено 6: ТОТ ЖЕ третий исход виден в stderr — два выхода не разъезжаются."""
    _rc, _cards, err = _ask(_Args(scene, _BAD_REF))
    assert "ось ПОРЯДКА" in err, err
    assert "ДАЛЬШЕ ПРОДВИНУЛСЯ" in err, err


# ── звено 7: ЦЕНА В СТРОКАХ — один раз на список, а не на карточку ────────────────

def test_link7_one_line_for_the_whole_list_not_one_per_card(tmp_path: Path) -> None:
    """Звено 7: отказ говорится ОДИН раз, а поля стоят у КАЖДОЙ карточки.

    Сторожа, кричащего на каждой находке, выключают (урок #243): на живом трекере (779
    карточек, замер 14.10) правка добавляет РОВНО одну строку stderr, а не 779.
    """
    root = tmp_path / "repo"
    tracker = _init(root)
    for n in range(5):
        (tracker / f"inbox-card-{n}.md").write_text(
            _notebook((716,), "new", body=f"задание {n}"), encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "ref")

    _rc, cards, err = _ask(_Args(tracker, _BAD_REF))
    assert len(cards) == 5, cards
    assert all("origin_order" in c for c in cards), cards
    # Мерить надо СТРОКИ, а не вхождения подстроки: имя оси стои́т и в зачине строки, и
    # внутри её же причины — два вхождения в ОДНОЙ строке ценой в строках не являются.
    said = [ln for ln in err.splitlines() if "ось ПОРЯДКА" in ln]
    assert len(said) == 1, said


# ── звено 8: ПРИБОРА НЕТ ВОВСЕ — у оси порядка слово НЕ отнимается ────────────────

def test_link8_absent_instrument_keeps_the_order_word(
    scene: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Звено 8: прибора нет ⇒ ось порядка держит ТО ЖЕ слово, и причина это называет.

    Асимметрия с осью памяти намеренная и названа: вокабуляр памяти живёт в приборе,
    поэтому там значение переходит на слово читателя; вокабуляр порядка живёт У
    ЧИТАТЕЛЯ, и отнять его отсутствию прибора нечем.
    """
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) \
        else __builtins__.__import__

    def _fake(name, *a, **k):
        if name == "check_tracker_drift":
            raise ModuleNotFoundError("No module named 'check_tracker_drift'")
        return real_import(name, *a, **k)

    monkeypatch.delitem(sys.modules, "check_tracker_drift", raising=False)
    monkeypatch.setattr("builtins.__import__", _fake)
    _rc, cards, err = _ask(_Args(scene, SCENE_REF))
    monkeypatch.undo()

    card = _only(cards)
    assert card["origin_order"] == oq.ORDER_NOT_COMPARED, card
    assert "не ввезён" in card["origin_order_detail"], card
    assert "НЕ У КОГО" in card["origin_order_detail"], card
    # Причина обязана НАЗВАТЬ значение, под которым уехал вердикт: без него потребитель
    # знает, что мерить было нечем, но не знает, что именно он прочтёт в поле. Пробел
    # нашла мутация этого цикла — она убирала имя из причины и батарею ПЕРЕЖИЛА.
    assert oq.ORDER_NOT_COMPARED in card["origin_order_detail"], card
    assert "ось ПОРЯДКА" in err, err


# ── звено 9: корень репозитория не найден — третья дверь ──────────────────────────

def test_link9_unresolvable_repo_root_states_the_order_axis(
    scene: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Звено 9: расхождение есть, разложить нечем ⇒ ось порядка со СВОЕЙ причиной.

    ДВЕРЬ ОБЯЗАНА БЫТЬ ДОКАЗАНА, а не предположена. `analyze` сам зовёт `repo_root_of`
    (`check_tracker_drift.py`), поэтому отказ «на все зовы» уводит прогон в ПЕРВУЮ
    дверь («сверка не состоялась»), и тест, думающий, что мерит третью, мерит первую
    второй раз. Это нашла мутация этого же цикла: откат третьей двери на одну ось
    батарею ПЕРЕЖИЛ. Поэтому ломается РОВНО зов читателя (первый зов — тот, что делает
    `analyze`, — проходит), и факт попадания в третью дверь закреплён её собственной
    строкой stderr.
    """
    real_root = drift.repo_root_of
    calls = {"n": 0}

    def _fails_only_for_the_reader(path):
        calls["n"] += 1
        if calls["n"] == 1:          # этот зов делает сам `analyze`
            return real_root(path)
        raise drift.Unmeasured("корень репозитория не определяется (замер звена 9)")

    monkeypatch.setattr(drift, "repo_root_of", _fails_only_for_the_reader)
    _rc, cards, err = _ask(_Args(scene, SCENE_REF))
    assert calls["n"] >= 2, (
        "предпосылка звена НЕ ОБЕСПЕЧЕНА: читатель до своего зова `repo_root_of` не "
        f"дошёл (зовов {calls['n']}) — измерена НЕ та дверь")
    assert "версию с origin взять неоткуда" in err, (
        f"предпосылка звена НЕ ОБЕСПЕЧЕНА: прогон ушёл в другую дверь — {err}")
    card = _only(cards)
    assert card["origin_check"] == oq.VERDICT_UNMEASURED, card
    assert card["origin_order"] == oq.ORDER_NOT_COMPARED, card
    assert "ДАЛЬШЕ ПРОДВИНУЛАСЬ" in card["origin_order_detail"], card
    assert "ось ПОРЯДКА" in err, err


# ── звено 10: ВТОРАЯ ДВЕРЬ — сверку выключили флагом ─────────────────────────────

def test_link10_disabled_comparison_is_asked_and_unanswered(scene: Path) -> None:
    """Звено 10: `--no-origin-check` ⇒ ось порядка тоже НЕ ИЗМЕРЕНА, и это сказано.

    Код возврата при этом отказе остаётся 0 — решение ADR-166 (красный код на
    состояние, заказанное самим вызывающим, учит гасить сигнал); правка добавляет ось,
    а не вердикт состава, и это закреплено здесь же.
    """
    rc, cards, err = _ask(_Args(scene, SCENE_REF, origin_check=False))
    card = _only(cards)
    assert rc == 0, "правка не вправе менять код возврата заказанного отказа"
    assert card["origin_order"] == oq.ORDER_NOT_COMPARED, card
    assert "--no-origin-check" in card["origin_order_detail"], card
    assert "ось ПОРЯДКА" in err, err


# ── звено 11: «ось НЕ МЕРИЛАСЬ» осталось отличимым (зеркальный риск) ─────────────

def test_link11_axis_never_asked_still_has_no_fields_at_all(tmp_path: Path) -> None:
    """Звено 11: у карточки БЕЗ второй копии полей порядка по-прежнему нет ВОВСЕ.

    Главный риск правки: проставь третий исход всем подряд — и различие
    «упорядочивать нечего» / «спросить не удалось» исчезло бы с ДРУГОЙ стороны, тот же
    дефект зеркально.
    """
    root = tmp_path / "repo"
    tracker = _init(root)
    (tracker / "inbox-kept.md").write_text(_notebook((716,), "new"), encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "ref")
    # Карточка ЕСТЬ только в дереве: второй копии для упорядочивания не существует.
    (tracker / "inbox-fresh.md").write_text(_notebook((999,), "new"), encoding="utf-8")

    _rc, cards, _err = _ask(_Args(tracker, SCENE_REF))
    fresh = next(c for c in cards if c["id"] == "inbox-fresh")
    assert fresh["origin_check"] == oq.VERDICT_UNDELIVERED, fresh
    assert not [k for k in fresh if k.startswith("origin_order")], (
        "у карточки без второй копии ось порядка ПРОСТАВИЛИ — «упорядочивать нечего» "
        "стало неотличимо от «спросить не удалось» с другой стороны")


# ── звено 12: новое слово не читается ни одним из вердиктов прибора ──────────────

def test_link12_new_spelling_is_not_any_instrument_verdict() -> None:
    """Звено 12: `not_compared` не равен ни одному вердикту порядка у прибора.

    Опасность одна: потребитель прочтёт третий исход как решённый порядок или как
    «спросили и не решили». Закрыто здесь, сравнением с ПОЛНЫМ набором имён прибора,
    а не с парой, выбранной глазами.
    """
    instrument = {name: getattr(drift, name) for name in dir(drift)
                  if name.startswith("ORDER_")}
    assert instrument, "вокабуляр порядка у прибора не найден — предпосылка НЕ ОБЕСПЕЧЕНА"
    assert oq.ORDER_NOT_COMPARED not in set(instrument.values()), (
        f"третий исход читателя совпал с вердиктом прибора: {instrument}")


def test_link13_reader_owns_the_word_and_the_instrument_never_emits_it() -> None:
    """Звено 13: дом нового слова — ЧИТАТЕЛЬ, и в приборе его нет ни одной строкой.

    Объявить имя у прибора значило бы завести поле, которое прибор не производит
    никогда, — то самое «всегда зелёное» место, которое проект уже снимал как ложное
    успокоение (#810). Обратная сторона: имя обязано жить РОВНО в одном месте, иначе
    две копии контракта разъедутся молча (#143–#145).
    """
    instrument_src = (REPO_ROOT / "scripts" / "check_tracker_drift.py").read_text(
        encoding="utf-8")
    assert oq.ORDER_NOT_COMPARED not in instrument_src, (
        "слово третьего исхода появилось в приборе — либо мёртвое поле, либо вторая "
        "копия контракта")
    reader_src = (REPO_ROOT / "scripts" / "orchestrator_queue.py").read_text(
        encoding="utf-8")
    assert reader_src.count(f'"{oq.ORDER_NOT_COMPARED}"') == 1, (
        "написание третьего исхода встречается в читателе не один раз — вторая копия "
        "одного контракта")
