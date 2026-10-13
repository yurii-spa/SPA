"""Ось ПАМЯТИ при ОТКАЗЕ сверки: третий исход со СВОЕЙ причиной (ADR-717, заказ G716 п. 3).

ПРЕДМЕТ. Цикл #860 (ADR-716) довёл ось памяти копий до читателя очереди — шага 1
протокола. Довёл ТОЛЬКО ПО ЗАПРОСУ прибора: все ветки, где сверка с `origin` не
состоялась, возвращали вердикты, в которых полей `origin_memory*` НЕТ ВОВСЕ. А
«полей нет» в контракте #860 означает ровно одно — «ось НЕ СПРАШИВАЛИ» (так у
`hidden`/`undelivered`, где второй копии для сравнения не существует). Значит два
РАЗНЫХ состояния печатались одинаково, и самое тихое из них было неотличимо от
штатного.

ЗАМЕР ДО ПРАВКИ (13.10, одноразовый репозиторий, дерево богаче на одну запись цикла,
`--ref` неразрешим): stderr читателя — три строки про СОСТАВ списка и НОЛЬ про память;
в JSON `origin_check=unmeasured` и ни одного ключа `origin_memory*`. Сессия, пришедшая
дописать свою запись в прод-копию приказа, узнала бы ровно столько же, сколько узнаёт
у карточки-задания без второй копии, — то есть ничего, — и дописала бы вслепую. Именно
так уже дважды терялась память приказа (ADR-714: 56 записей 08.10 и 9 записей 25.09).

ЧТО ЗДЕСЬ ЗАКРЕПЛЕНО — инвариант #17 в чистом виде: «не измерено» обязано быть
ОТДЕЛЬНЫМ значением СО СВОЕЙ причиной, а не наследоваться молчанием от соседней оси.
Причина соседа («ref не разрешается») отвечает на вопрос о СОСТАВЕ списка; на вопрос
«сколько записей цикла не хватает этой копии» она не отвечает ничего.

ЧЕТЫРЕ ДВЕРИ одного класса, и каждая проверяется отдельно, потому что чинится отдельно:
прибор не ввезён · `analyze` отказал · корень репозитория не найден · сверка выключена
флагом `--no-origin-check`.

ВРЕМЯ И ГИТ — входы сцены, а не окружение (`.claude/rules/deployment.md`): одноразовый
репозиторий создаётся `git init -b <имя>`, и то же имя читают все ссылки сцены;
литеральных дат в файле нет вовсе.
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
#: даёт `master`, Apple Git на Маке — `main`; фикстура, назвавшая потом `origin/main`,
#: зелена здесь и красна там).
SCENE_REF = "scene-main"


def _notebook(records: tuple[int, ...], body: str = "тело приказа") -> str:
    head = ("---\ntype: inbox\nstatus: in-progress\n"
            "title: \"TASK — стоячий приказ владельца\"\n---\n\n"
            f"{body}\n")
    return head + "".join(
        f"\n## Цикл #{n} (замер цикла {n})\n\nчто сделано в цикле {n}\n" for n in records)


def _git(cwd: Path, *args: str) -> None:
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                       timeout=120)
    if r.returncode != 0:
        pytest.fail(f"предпосылка сцены НЕ ОБЕСПЕЧЕНА: git {' '.join(args)} → "
                    f"{r.returncode}: {r.stderr.strip()}")


@pytest.fixture()
def scene(tmp_path: Path) -> Path:
    """Одноразовый репозиторий: тетрадь, у которой копия дерева БЕДНЕЕ на две записи."""
    root = tmp_path / "repo"
    tracker = root / drift.TRACKER_REL
    tracker.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", SCENE_REF, str(root)], check=True,
                   capture_output=True, timeout=120)
    _git(root, "config", "user.email", "probe@example.com")
    _git(root, "config", "user.name", "probe")
    card = tracker / "inbox-order.md"
    card.write_text(_notebook((716, 717, 718)), encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "ref")
    card.write_text(_notebook((716,)), encoding="utf-8")   # дереву не хватает #717, #718
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


# ── звено 1: сверка СОСТОЯЛАСЬ — всё как было (свойство, которое правка СОХРАНЯЕТ) ──

def test_link1_measured_run_still_names_the_loss_with_numbers(scene: Path) -> None:
    """Звено 1: на состоявшейся сверке ось памяти по-прежнему несёт вердикт и ЧИСЛА."""
    rc, cards, err = _ask(_Args(scene, SCENE_REF))
    card = _only(cards)
    assert card["origin_memory"] in drift.MEMORY_FINDINGS, card
    assert card["origin_memory_missing_tree"] == 2, card
    assert "#717" in card["origin_memory_detail"], card
    assert "ПАМЯТЬ КОПИЙ РАЗОШЛАСЬ" in err
    assert rc in (0, 1, 2)      # код состава — не предмет этого звена


# ── звено 2: `analyze` ОТКАЗАЛ — ось обязана назвать СВОЮ причину ───────────────────

def test_link2_refused_comparison_still_states_the_memory_axis(scene: Path) -> None:
    """Звено 2: ref неразрешим ⇒ у оси памяти СВОЙ третий исход, а не молчание."""
    rc, cards, err = _ask(_Args(scene, "refs/heads/no-such-ref-here"))
    card = _only(cards)
    assert card["origin_check"] == oq.VERDICT_UNMEASURED, card
    assert "origin_memory" in card, (
        "ось памяти молчит при отказе сверки — ровно замер до ADR-717: «спросили и не "
        "узнали» неотличимо от «не спрашивали»")
    assert card["origin_memory"] == drift.MEMORY_UNMEASURED, card
    assert rc == 2


def test_link3_refused_comparison_memory_reason_is_its_own(scene: Path) -> None:
    """Звено 3: причина оси говорит о ЗАПИСЯХ ЦИКЛА, а не пересказывает соседа.

    Причина соседа отвечает на вопрос о СОСТАВЕ списка. Если ось повторяет её слово в
    слово и ничего не добавляет — «своей причины» у неё нет, и дефект на месте.
    """
    _rc, cards, _err = _ask(_Args(scene, "refs/heads/no-such-ref-here"))
    reason = _only(cards)["origin_memory_detail"]
    assert "ЗАПИСЕЙ ЦИКЛА" in reason, reason
    assert "НЕ ИЗМЕРЕНО" in reason, reason
    assert "не «записи совпали»" in reason, reason


def test_link4_refusal_reaches_the_human_channel_too(scene: Path) -> None:
    """Звено 4: ТОТ ЖЕ третий исход виден в stderr — два выхода не разъезжаются."""
    _rc, _cards, err = _ask(_Args(scene, "refs/heads/no-such-ref-here"))
    assert "ось ПАМЯТИ" in err, err
    assert "ЗАПИСИ ЦИКЛА" in err, err


def test_link5_one_line_for_the_whole_list_not_one_per_card(tmp_path: Path) -> None:
    """Звено 5: ЦЕНА В СТРОКАХ — отказ говорится ОДИН раз, а не на каждую карточку.

    Сторожа, кричащего на каждой находке, выключают (урок #243): на живом трекере это
    были бы 244 строки вместо одной. Поэтому `origin_memory_note` — который
    приписывается к КАЖДОЙ строке списка глазами — в этой ветке НЕ ставится.
    """
    root = tmp_path / "repo"
    tracker = root / drift.TRACKER_REL
    tracker.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", SCENE_REF, str(root)], check=True,
                   capture_output=True, timeout=120)
    _git(root, "config", "user.email", "probe@example.com")
    _git(root, "config", "user.name", "probe")
    for n in range(5):
        (tracker / f"inbox-card-{n}.md").write_text(
            _notebook((716,), body=f"задание {n}"), encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "ref")

    _rc, cards, err = _ask(_Args(tracker, "refs/heads/no-such-ref-here"))
    assert len(cards) == 5, cards
    assert all("origin_memory" in c for c in cards), cards
    assert not any("origin_memory_note" in c for c in cards), (
        "нота памяти приписана к каждой карточке — список утонет в шуме")
    assert err.count("ось ПАМЯТИ") == 1, err


# ── звено 6: ПРИБОРА НЕТ ВОВСЕ — другой отказ, и он назван отдельно ────────────────

def test_link6_absent_instrument_is_a_distinct_named_refusal(
    scene: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Звено 6: прибор не ввезён ⇒ ось говорит, что спросить НЕ У КОГО.

    Это не то же, что «прибор отказал»: там мера есть и не сработала, здесь меры нет
    вовсе, и чинится это разным. Положительный контроль — настоящий отказ ввоза.
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
    assert card["origin_memory"] == oq.VERDICT_UNMEASURED, card
    assert "не ввезён" in card["origin_memory_detail"], card
    assert "НЕ У КОГО" in card["origin_memory_detail"], card
    assert "ось ПАМЯТИ" in err, err


def test_link7_neither_spelling_can_be_read_as_loss_or_as_agreement() -> None:
    """Звено 7: оба написания третьего исхода НЕ читаются ни «потерей», ни «совпало».

    У ветки «прибора нет» вокабуляр прибора взять негде по той самой причине, о которой
    речь, поэтому значение там — слово самого читателя. Опасность этого ровно одна:
    потребитель прочтёт его как находку или как согласие. Закрыто здесь.
    """
    for spelling in (drift.MEMORY_UNMEASURED, oq.VERDICT_UNMEASURED):
        assert spelling not in drift.MEMORY_FINDINGS, spelling
        assert spelling != drift.MEMORY_EQUAL, spelling
        assert spelling != drift.MEMORY_NOT_A_NOTEBOOK, spelling


# ── звено 8: корень репозитория не найден — третья ветка отказа ────────────────────

def test_link8_unresolvable_repo_root_states_the_axis(
    scene: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Звено 8: находки есть, разложить их нечем ⇒ ось памяти со СВОЕЙ причиной.

    АДРЕС ДВЕРИ ПЕРЕНАВЕДЁН циклом #862, и это НЕ ослабление (инв. #16): утверждение
    теста не изменилось ни на слово — та же дверь, тот же ожидаемый исход, — изменился
    только способ в неё попасть. Прежняя редакция ломала `repo_root_of` НА ВСЕ ЗОВЫ, а
    его зовёт и сам `analyze` (`check_tracker_drift.py`), поэтому прогон уходил в ПЕРВУЮ
    дверь («сверка не состоялась») и третью не трогал вовсе: тест, думавший, что мерит
    третью, мерил первую второй раз.

    ИЗМЕРЕНО, а не выведено (#862): при полностью ослеплённой ТРЕТЬЕЙ двери — обе оси
    погашены — эта батарея была ЗЕЛЕНОЙ 11 из 11. Теперь ломается РОВНО зов читателя
    (первый зов, тот, что делает `analyze`, проходит), и попадание в третью дверь
    закреплено её собственной строкой stderr.
    """
    real_root = drift.repo_root_of
    calls = {"n": 0}

    def _no_root(path):
        calls["n"] += 1
        if calls["n"] == 1:          # этот зов делает сам `analyze`
            return real_root(path)
        raise drift.Unmeasured("корень репозитория не определяется (замер звена 8)")

    monkeypatch.setattr(drift, "repo_root_of", _no_root)
    _rc, cards, err = _ask(_Args(scene, SCENE_REF))
    assert calls["n"] >= 2, (
        "предпосылка звена НЕ ОБЕСПЕЧЕНА: читатель до своего зова `repo_root_of` не "
        f"дошёл (зовов {calls['n']}) — измерена НЕ та дверь")
    assert "версию с origin взять неоткуда" in err, (
        f"предпосылка звена НЕ ОБЕСПЕЧЕНА: прогон ушёл в другую дверь — {err}")
    card = _only(cards)
    assert card["origin_check"] == oq.VERDICT_UNMEASURED, card
    assert card["origin_memory"] == drift.MEMORY_UNMEASURED, card
    assert "ЗАПИСЕЙ ЦИКЛА" in card["origin_memory_detail"], card
    assert "ось ПАМЯТИ" in err, err


# ── звено 9: ВТОРАЯ ДВЕРЬ — сверку выключили флагом ────────────────────────────────

def test_link9_disabled_comparison_is_asked_and_unanswered_not_unasked(
    scene: Path,
) -> None:
    """Звено 9: `--no-origin-check` ⇒ ось памяти тоже НЕ ИЗМЕРЕНА, и это сказано.

    Код возврата при этом отказе остаётся 0 — решение ADR-166 (красный код на
    заказанное вызывающим состояние учит гасить сигнал); правка добавляет ось, а не
    вердикт состава, и это закреплено здесь же.
    """
    rc, cards, err = _ask(_Args(scene, SCENE_REF, origin_check=False))
    card = _only(cards)
    assert rc == 0, "правка не вправе менять код возврата заказанного отказа"
    assert card["origin_memory"] == drift.MEMORY_UNMEASURED, card
    assert "--no-origin-check" in card["origin_memory_detail"], card
    assert "ось ПАМЯТИ" in err, err


# ── звено 10: «ось НЕ СПРАШИВАЮТ» осталось отличимым ──────────────────────────────

def test_link10_axis_never_asked_still_has_no_fields_at_all(tmp_path: Path) -> None:
    """Звено 10: у карточки БЕЗ второй копии полей памяти по-прежнему нет ВОВСЕ.

    Это обратная сторона правки и её главный риск: если бы третий исход проставлялся
    всем подряд, различие «не спрашивают» (сравнивать нечего) и «спросили и не узнали»
    исчезло бы с другой стороны — тот же дефект зеркально.
    """
    root = tmp_path / "repo"
    tracker = root / drift.TRACKER_REL
    tracker.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", SCENE_REF, str(root)], check=True,
                   capture_output=True, timeout=120)
    _git(root, "config", "user.email", "probe@example.com")
    _git(root, "config", "user.name", "probe")
    (tracker / "inbox-kept.md").write_text(_notebook((716,)), encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "ref")
    # Карточка ЕСТЬ только в дереве: второй копии для сравнения не существует.
    (tracker / "inbox-fresh.md").write_text(_notebook((999,)), encoding="utf-8")

    _rc, cards, _err = _ask(_Args(tracker, SCENE_REF))
    fresh = next(c for c in cards if c["id"] == "inbox-fresh")
    assert fresh["origin_check"] == oq.VERDICT_UNDELIVERED, fresh
    assert not [k for k in fresh if k.startswith("origin_memory")], (
        "у карточки без второй копии ось памяти ПРОСТАВИЛИ — «не спрашивают» стало "
        "неотличимо от «спросили и не узнали» с другой стороны")


# ── звено 11: вокабуляр третьего исхода НЕ переписан в читателя литералом ─────────

def test_link11_reader_does_not_keep_its_own_copy_of_the_instrument_word() -> None:
    """Звено 11: `"records_unmeasured"` не живёт в читателе второй копией.

    Две копии одного контракта в этом репозитории уже трижды разъезжались молча
    (#143–#145): одну поправили, вторую забыли. Поэтому читатель обязан брать имя
    вердикта у прибора, а не держать своё написание.

    Мера здесь — AST, а не подстрока, и это НЕ придирка: первая редакция этой проверки
    искала написание в тексте файла и покраснела на СВОЁМ ЖЕ объяснении («переписать
    `records_unmeasured` сюда литералом значило бы…»). Проза, запрещающая копию, копией
    не является; различить их подстрокой нельзя по построению (ADR-333).
    """
    import ast

    path = REPO_ROOT / "scripts" / "orchestrator_queue.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    live = [n for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings and n.value == drift.MEMORY_UNMEASURED]
    assert not live, (
        f"имя вердикта прибора переписано в читателя ЖИВЫМ литералом "
        f"(строки {[n.lineno for n in live]}) — вторая копия контракта")
