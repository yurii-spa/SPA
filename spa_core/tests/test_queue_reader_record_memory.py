"""Вердикт ПАМЯТИ копий обязан доходить до ЧИТАТЕЛЯ очереди — шаг 1 протокола.

**Каждый тест здесь воспроизводит настоящую аварию, а не придуманный случай.**
Проверка, никогда не видевшая живой поломки, — украшение
(правило `.claude/rules/deployment.md`).

Что случилось. Доставка 08.10 (`359ce9406`) принесла свою копию карточки стоячего
приказа владельца ПОВЕРХ УСТАРЕВШЕЙ и унесла **56 записей циклов** (#716…#806);
цикл #858 (ADR-714) закрыл БУДУЩУЮ потерю у двери доставки, цикл #859 (ADR-715) научил
прибор расхождения НАЗЫВАТЬ уже стоящее расхождение — и измерил его: прод-копии приказа
не хватает **94** записей (#716…#858), второй живой тетради
(`inbox-ozhivit-fidy-vne-ethereum-put-k-snyatiyu`) — **6**; обратных записей НЕТ НИ ОДНОЙ.

**Чего не хватало.** У вердикта прибора НЕТ ЧИТАТЕЛЯ: артефакта прибор не пишет, а шаги
протокола читают ОЧЕРЕДЬ (`orchestrator_queue list --json` — дословный контракт шагов 1
и 2). Замер 13.10 на прод-дереве, до правки: у карточки приказа шаг 1 отвечал
`origin_check=diverged_unmeasured`, `origin_order=unmeasured` («ни одна ось не установила
порядок»), а о 94 пропавших записях не было ни слова ни в JSON, ни в девяти строках
stderr. То есть сессия, пришедшая дописать свою запись цикла в прод-копию, узнала бы о
потере ровно ничего — и стёрла бы чужую память, как это уже случилось дважды.

**Что чинится.** Ось памяти (`Finding.memory*`, ADR-715) едет в вердикт читателя
(`origin_memory*`) и называется отдельной строкой stderr. Членство «это потеря» берётся
у прибора ОДНОЙ копией (`drift.MEMORY_FINDINGS`) — второй перечень имён здесь был бы
вторым объявлением одного контракта (ADR-220, класс #143–#145).

**Чего читатель НЕ делает.** Он не чинит копии и не прячет карточку: сторож называет,
решает сессия. Прод-дерево правится только с разрешения владельца
(`.claude/rules/deployment.md` п. 6).

Литеральных дат здесь нет: всё состояние задаётся содержимым фикстур, календарь на эти
тесты не влияет. Имя ветки одноразового репозитория объявлено ВХОДОМ (`git init -b`) —
`init.defaultBranch` хоста на вердикт не влияет (правило про git-окружение там же).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"
for _p in (str(_REPO_ROOT), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import check_tracker_drift as drift  # noqa: E402
import orchestrator_queue as oq  # noqa: E402

REF = "main"


# ── одноразовый репозиторий: «origin» — та же ветка, сети нет ────────────────

def _run(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / drift.TRACKER_REL).mkdir(parents=True)
    _run(root.parent, "init", "-q", "-b", REF, str(root))
    _run(root, "config", "user.email", "t@example.com")
    _run(root, "config", "user.name", "test")
    return root


def _tracker(root: Path) -> Path:
    return root / drift.TRACKER_REL


def _write(root: Path, name: str, text: str) -> Path:
    p = _tracker(root) / f"{name}.md"
    p.write_text(text, encoding="utf-8")
    return p


def _commit(root: Path, msg="c"):
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", msg)


def _notebook(records: list[int], body: str = "тело приказа") -> str:
    """Карточка-ТЕТРАДЬ: стоячий приказ владельца с записями циклов.

    Форма заголовка записи взята у двери доставки (перепись #858: «## Цикл #N» 193 раза,
    «## ЦИКЛ #N» 26, уровни `##` и `###`), а не придумана здесь.
    """
    head = ("---\ntrackerStatus:\n  type: inbox\n"
            "title: \"TASK — стоячий приказ владельца\"\nstatus: in-progress\n---\n\n"
            f"{body}\n")
    blocks = "".join(f"\n## Цикл #{n} (замер, ADR-{n})\n\nчто сделано в цикле {n}\n"
                     for n in records)
    return head + blocks


def _list_json(repo_root, extra_argv=()):
    """Ровно та команда, которую предписывают шаги 1 и 2 протокола."""
    argv = ["list", "--tracker-dir", str(_tracker(repo_root)),
            "--ref", REF, "--json", *extra_argv]
    oq.cmd_list(oq.build_parser().parse_args(argv))


def _card(capsys, card_id="inbox-order") -> dict:
    out, err = capsys.readouterr()
    cards = {c["id"]: c for c in json.loads(out)}
    assert card_id in cards, f"карточки {card_id} нет в выдаче шага 1: {sorted(cards)}"
    cards[card_id]["__stderr__"] = err
    return cards[card_id]


def _tree_poorer(root, name="inbox-order"):
    """ДОСЛОВНАЯ форма аварии 08.10: на ref память богаче, в дереве — беднее.

    Копия дерева при этом найдена в истории пути (так и было: доставка принесла ПРЕЖНЮЮ
    редакцию), поэтому класс — `stale`; у второй живой тетради замера 13.10 он такой же.
    """
    _write(root, name, _notebook([716]))
    _commit(root, "копия, которую доставка потом принесёт поверх")
    _write(root, name, _notebook([716, 717, 718]))
    _commit(root, "соседние циклы дописали свои записи")
    _write(root, name, _notebook([716]))        # дерево вернулось к бедной копии
    return name


def _tree_poorer_with_own_edit(root, name="inbox-order"):
    """Та же потеря, но у копии дерева ЕСТЬ своя правка ⇒ класс `diverged`.

    Ровно так выглядит прод-копия приказа сегодня: 94 записи пропали И поле захвата
    переписано живой сессией, поэтому содержимого дерева в истории нет.
    """
    _write(root, name, _notebook([716, 717, 718]))
    _commit(root, "память на ref")
    _write(root, name, _notebook([716], body="тело приказа + своя правка дерева"))
    return name


# ── АВАРИЯ: потеря записей не доходила до читателя очереди ───────────────────

def test_memory_loss_reaches_the_json_of_step_one(repo, capsys):
    """ЯДРО ДЕФЕКТА. Шаг 1 читает JSON — вердикт обязан быть ТАМ."""
    _tree_poorer(repo)
    _list_json(repo)
    card = _card(capsys)

    assert card["origin_memory"] in drift.MEMORY_FINDINGS, (
        f"потеря записей цикла не объявлена потерей: {card.get('origin_memory')!r}")
    assert card["origin_memory"] == drift.MEMORY_TREE_POORER
    assert card["origin_memory_missing_tree"] == 2, (
        "ЧИСЛО пропавших записей обязано быть в вердикте: выпарсивать его из прозы "
        "значило бы завести вторую мерку одного факта")
    assert card["origin_memory_missing_origin"] == 0


def test_memory_loss_is_named_in_stderr_by_card_name(repo, capsys):
    """Человек у терминала обязан увидеть то же, что и `| jq`."""
    name = _tree_poorer(repo)
    _list_json(repo)
    err = _card(capsys)["__stderr__"]

    assert "ПАМЯТЬ КОПИЙ РАЗОШЛАСЬ" in err
    assert name in err, "совет без ИМЕНИ карточки исполнить нельзя (урок #243)"
    assert "#717" in err and "#718" in err, (
        "пропавшие записи обязаны быть названы ПОИМЁННО: по строке без номеров читатель "
        "не отличит её от сотни других в списке расхождений")


def test_human_readable_list_shows_memory_too(repo, capsys):
    """Два выхода одного читателя не имеют права расходиться."""
    _tree_poorer(repo)
    argv = ["list", "--tracker-dir", str(_tracker(repo)), "--ref", REF]
    oq.cmd_list(oq.build_parser().parse_args(argv))
    out = capsys.readouterr().out
    assert drift.MEMORY_TREE_POORER in out


def test_memory_loss_is_carried_for_diverged_copies_too(repo, capsys):
    """Прод-копия приказа СЕГОДНЯ именно такая: записи пропали И есть своя правка.

    Спрашивать ось только у одного класса значило бы пропустить половину живого
    населения замера 13.10 (одна тетрадь `diverged`, вторая `stale`).
    """
    _tree_poorer_with_own_edit(repo)
    _list_json(repo)
    card = _card(capsys)
    assert card["origin_check"].startswith(oq.VERDICT_DIVERGED)
    assert card["origin_memory"] == drift.MEMORY_TREE_POORER
    assert card["origin_memory_missing_tree"] == 2


def test_memory_loss_does_not_drop_the_card_from_the_list(repo, capsys):
    """Сторож НАЗЫВАЕТ, а решает сессия: прятать карточку он не вправе."""
    _tree_poorer(repo)
    _list_json(repo)
    assert _card(capsys)["id"] == "inbox-order"


def test_order_axis_is_still_measured(repo, capsys):
    """Свойство, которое правка обязана СОХРАНИТЬ: оси порядка (ADR-544) на месте."""
    _tree_poorer_with_own_edit(repo)
    _list_json(repo)
    card = _card(capsys)
    assert "origin_order" in card and card["origin_order"]


# ── КОНТРОЛЬ В ОБРАТНУЮ СТОРОНУ: сторож, кричащий на всё, бесполезен ─────────

def test_plain_body_rewrite_is_not_memory_loss(repo, capsys):
    """САМЫЙ ВАЖНЫЙ обратный контроль.

    Почти вся разница двух копий — штатная переписка ТЕЛА карточки и поле захвата. Мера
    «любая разница = потеря памяти» дала бы на живой популяции 538 отказов из 2133
    переходов (замер #858), и такого сторожа выключают. Набор номеров записей цел ⇒
    вердикт «память совпала», и находкой это НЕ является.
    """
    _write(repo, "inbox-order", _notebook([716, 717, 718]))
    _commit(repo)
    _write(repo, "inbox-order", _notebook([716, 717, 718], body="тело переписано целиком"))
    _list_json(repo)
    card = _card(capsys)

    assert card["origin_memory"] == drift.MEMORY_EQUAL
    assert card["origin_memory"] not in drift.MEMORY_FINDINGS
    assert "origin_memory_note" not in card, (
        "на штатной переписке тела читатель обязан МОЛЧАТЬ: иначе раздел утонет в шуме")
    assert "ПАМЯТЬ КОПИЙ РАЗОШЛАСЬ" not in card["__stderr__"]


def test_card_without_cycle_records_is_not_a_notebook(repo, capsys):
    """Карточка-ЗАДАНИЕ (записей цикла нет ни в одной копии) находкой не становится.

    Тетрадей среди 1302 карточек трекера девятнадцать; членство решает СОДЕРЖИМОЕ, а не
    имя файла, и остальные 1283 раздел памяти не кормят.
    """
    _write(repo, "inbox-plain", "---\ntrackerStatus:\n  type: inbox\n"
                                "title: \"задание\"\nstatus: new\n---\n\nтело\n")
    _commit(repo)
    _write(repo, "inbox-plain", "---\ntrackerStatus:\n  type: inbox\n"
                                "title: \"задание\"\nstatus: new\n---\n\nдругое тело\n")
    _list_json(repo)
    card = _card(capsys, "inbox-plain")
    assert card["origin_memory"] == drift.MEMORY_NOT_A_NOTEBOOK
    assert "origin_memory_note" not in card
    assert "ПАМЯТЬ КОПИЙ РАЗОШЛАСЬ" not in card["__stderr__"]


# ── ТРИ ИСХОДА РАЗЛИЧИМЫ (инв. #17) ─────────────────────────────────────────

def test_unmeasured_memory_is_distinct_from_equal(repo, capsys, monkeypatch):
    """«НЕ измерено» не имеет права выглядеть как «записи совпали».

    Ветка настоящая: мера записи цикла берётся У ДВЕРИ доставки (`push_to_github`), и
    дверь может не ввезтись — тогда прибор отвечает `records_unmeasured` с причиной.
    Самое успокоительное из значений выдумывать запрещено.
    """
    monkeypatch.setattr(drift, "door_record_measure",
                        lambda: (_ for _ in ()).throw(drift.Unmeasured("дверь не ввезена")))
    _tree_poorer(repo)
    _list_json(repo)
    card = _card(capsys)

    assert card["origin_memory"] == drift.MEMORY_UNMEASURED
    assert card["origin_memory"] != drift.MEMORY_EQUAL
    assert "НЕ ИЗМЕРЕНА" in card["origin_memory_note"]
    assert "память копий НЕ ИЗМЕРЕНА" in card["__stderr__"]


def test_axis_not_asked_leaves_the_field_absent(repo, capsys):
    """Ось НЕ СПРАШИВАЛИ (второй копии нет) ⇒ поля нет вовсе, а не «совпала».

    Карточка есть в дереве и отсутствует на ref: сравнивать не с чем. Пустое поле,
    прочитанное как согласие, — ровно тот класс, ради которого появился `origin_check`.
    """
    _write(repo, "inbox-other", _notebook([716]))
    _commit(repo)
    _write(repo, "inbox-other", _notebook([716], body="своя правка, чтобы сверка состоялась"))
    _write(repo, "inbox-fresh", _notebook([716]))   # ПОСЛЕ коммита: на ref её нет вовсе
    _list_json(repo)
    card = _card(capsys, "inbox-fresh")

    assert card["origin_check"] == oq.VERDICT_UNDELIVERED
    assert "origin_memory" not in card, (
        "«не спрашивают» и «спросили и совпало» — разные исходы одного поля")


# ── ОДНА КОПИЯ ПРАВИЛА: членство читатель берёт у прибора ───────────────────

def test_membership_rule_comes_from_the_instrument_not_a_second_list(repo, capsys,
                                                                    monkeypatch):
    """Положительный контроль свойства «одна копия» (ADR-220).

    Если бы читатель нёс свой перечень имён вердиктов, подмена перечня У ПРИБОРА на него
    не подействовала бы — и две копии правила разъехались бы молча, как это уже трижды
    случилось (#143–#145). Поэтому: расширяем членство у ПРИБОРА и требуем, чтобы вердикт
    читателя пошёл за ним.
    """
    monkeypatch.setattr(drift, "MEMORY_FINDINGS",
                        frozenset(drift.MEMORY_FINDINGS | {drift.MEMORY_EQUAL}))
    _write(repo, "inbox-order", _notebook([716, 717]))
    _commit(repo)
    _write(repo, "inbox-order", _notebook([716, 717], body="переписанное тело"))
    _list_json(repo)
    card = _card(capsys)

    assert card["origin_memory"] == drift.MEMORY_EQUAL
    assert "origin_memory_note" in card, (
        "читатель не пошёл за мерой прибора ⇒ у него своя копия членства")
    assert "ПАМЯТЬ КОПИЙ РАЗОШЛАСЬ" in card["__stderr__"]


def test_section_order_follows_the_instrument(repo, capsys):
    """Первым назван тот, кто потерял БОЛЬШЕ: порядок тоже берётся у прибора.

    Читатель, печатающий находки в порядке обхода словаря или по алфавиту, на живой
    популяции поставил бы тетрадь с 94 пропавшими записями после тетради с шестью
    (`inbox-ozhivit-…` по алфавиту раньше `inbox-task-portfolio-…` — то есть именно так
    и вышло бы). Поэтому имена здесь выбраны так, чтобы АЛФАВИТ противоречил потере:
    первая редакция этой проверки звалась `inbox-big`/`inbox-small` и на чистом дереве
    проходила СЛУЧАЙНО, по алфавиту, ничего не измерив.

    И смотрим мы РАЗДЕЛ ПАМЯТИ, а не весь stderr: те же имена стоят в общих списках
    расхождений, и порядок там свой.
    """
    _write(repo, "inbox-aaa-loses-one", _notebook([1]))
    _write(repo, "inbox-zzz-loses-four", _notebook([1]))
    _commit(repo)
    _write(repo, "inbox-aaa-loses-one", _notebook([1, 2]))
    _write(repo, "inbox-zzz-loses-four", _notebook([1, 2, 3, 4, 5]))
    _commit(repo)
    _write(repo, "inbox-aaa-loses-one", _notebook([1]))
    _write(repo, "inbox-zzz-loses-four", _notebook([1]))
    _list_json(repo)
    err = capsys.readouterr().err

    assert "ПАМЯТЬ КОПИЙ РАЗОШЛАСЬ" in err
    section = err[err.index("ПАМЯТЬ КОПИЙ РАЗОШЛАСЬ"):]
    # Раздел кончается там, где начинается следующий пункт того же уровня.
    tail = section.find("\n    · ", 1)
    if tail != -1:
        section = section[:tail]
    assert "inbox-aaa-loses-one" in section and "inbox-zzz-loses-four" in section
    assert section.index("inbox-zzz-loses-four") < section.index("inbox-aaa-loses-one"), (
        "тетрадь с БОЛЬШЕЙ потерей обязана быть названа первой — порядок берётся у "
        "прибора (`report.memory_findings`), а не у алфавита")
