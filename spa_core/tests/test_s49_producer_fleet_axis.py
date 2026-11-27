"""Контроль оси «производитель меры §49 — во флоте или нет» (ADR-1122, циклы #1266 (замер) + #1268 (приёмка и доставка)).

Предмет. Сводка §49 приказа владельца «Portfolio CIO»
(`scripts/cio_acceptance_rollup.py`) печатала у неизмеренного критерия «артефакт
протух: 581 ч при пределе 9,28 ч», а у цены — `PRODUCER`: «вернуть производителя
в такт». Обе строки верны, и обе читаются как ДОЛГ АГЕНТА. Замер 2026-11-27 на
прод-дереве (дверь `launchctl list`): у **всех 13** критериев §49 объявленный
производитель меры ОДИН — `com.spa.decision_loop`, и во флоте его НЕТ с
2026-10-29. Включить службу вправе только владелец
(`.claude/rules/deployment.md` п. 6), значит эта цена работой агента над кодом не
платится вовсе — а 530 циклов голодающего приказа читали её как свою.

Это класс ADR-995 («молчит 11 ч» о службе, выключенной 14 дней), но у ЧИТАТЕЛЯ
приёмки: «производитель опоздал» и «производителя нет во флоте» чинят РАЗНЫЕ
люди, а печатались одним словом (инв. #17).

Каждый тест — положительный контроль на конкретный способ соврать, а не
украшение (`.claude/rules/deployment.md`, «Проверка сторожа сторожей»): ось,
раздающая ярлык «ВО ФЛОТЕ / НЕТ ВО ФЛОТЕ», опасна ровно тем же, чем опасна сама
сводка — ложный ярлык по форме неотличим от верного, а читатель по нему выбирает
АДРЕСАТА починки.

Состояние флота — ВХОД (`loaded` / `fleet_asked`), поэтому ни один тест здесь не
спрашивает живую машину: вердикт, зависящий от того, что сегодня загружено на
хосте, был бы бомбой того же рода, что литеральная дата и литеральный pid
(`.claude/rules/deployment.md`, § про календарь и § про личность процесса).
Литеральных дат нет: у этой оси нет понятия свежести — свежесть есть вопрос
соседа (`s49_surface_freshness`), и заводить её здесь фикстурой значило бы
поставить бомбу на пустом месте. Литеральных pid нет: ни одного процесса ось не
спрашивает.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys

import pytest

from spa_core.monitoring import s49_criterion_price as price_meter
from spa_core.monitoring import s49_surface_freshness as fleet_meter

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import cio_acceptance_rollup as rollup  # noqa: E402

#: Имя ветки одноразовой сцены объявляется ЯВНО: `git init` без `-b` берёт
#: `init.defaultBranch` ХОСТА (`main` у Apple Git, `master` на `ubuntu-latest`),
#: и сцена, назвавшая потом `origin/main`, была бы зелена здесь и красна в CI
#: (`.claude/rules/deployment.md`, § GIT-ОКРУЖЕНИЕ).
BRANCH = "main"

LABEL = "com.spa.probe_producer"
OTHER = "com.spa.other_producer"

SECTION = """49. Acceptance criteria

Работа считается выполненной только когда доказано следующее.
Economics
Решения используют net expected return, а не raw APY.


⸻


50. Definition of Done
"""


def _manifest(artifacts: list[dict]) -> dict:
    return {"artifacts": artifacts}


def _artifact(path: str, producer: str | None, criterion: str = "Economics",
              slo_hours: float = 9.28) -> dict:
    entry = {"path": path, "slo_hours": slo_hours,
             "notes": f"мера ТЗ §49 `{criterion}` — проверяется пробой"}
    if producer is not None:
        entry["producer"] = producer
    return entry


def _scene(tmp_path, manifest: dict | None = None) -> str:
    """Одноразовое дерево с карточкой приказа и (по желанию) конституцией."""
    root = tmp_path / "repo"
    (root / os.path.dirname(rollup.CARD_REL)).mkdir(parents=True)
    subprocess.run(["git", "init", "-b", BRANCH], cwd=root, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    (root / rollup.CARD_REL).write_text(
        '---\ntitle: "TASK"\nstatus: in-progress\n---\n\n## Задание\n\nпреамбула'
        "\n\n\n⸻\n\n\n" + SECTION, encoding="utf-8")
    if manifest is not None:
        path = root / price_meter.MANIFEST_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "card"], cwd=root, check=True,
                   capture_output=True)
    return str(root)


def _axis(*, loaded=None, fleet_asked=False, names=("Economics",)) -> dict:
    """Ось на ПОДАННОЙ конституции: её читатель подменён фикстурой ниже, поэтому
    `repo_root` здесь роли не играет и назван так, чтобы это было видно."""
    return rollup.producer_axis(list(names), repo_root="/manifest-is-injected",
                                loaded=loaded, fleet_asked=fleet_asked, now=None)


def _inject(monkeypatch, manifest: dict) -> dict:
    """Конституция — ВХОД сцены, а не файл на диске: читатель у неё ОДИН
    (`price_meter.read_manifest`), и подменяется ровно он."""
    monkeypatch.setattr(price_meter, "read_manifest", lambda root: manifest)
    return manifest


@pytest.fixture()
def one_producer(monkeypatch):
    """Конституция с ОДНИМ объявленным производителем."""
    return _inject(monkeypatch, _manifest(
        [_artifact("data/keep_dominance_census.json", LABEL)]))


# ───────────────────────── 1. различает ли ось вообще ─────────────────────────

class TestTheAxisDistinguishesTheTwoStates:
    def test_the_same_constitution_answers_differently_on_two_fleets(self, one_producer):
        """ДИФФЕРЕНЦИАЛЬНЫЙ контроль: меняется ТОЛЬКО вход флота.

        Ось, отвечающая одинаково на «служба загружена» и «службы нет», и есть
        тот дефект, против которого она написана, — и отличить её от рабочей
        можно только парой сцен с одним манифестом.
        """
        up = _axis(loaded={LABEL})
        down = _axis(loaded=set())
        assert up["rows"]["Economics"]["state"] == fleet_meter.LOADED
        assert down["rows"]["Economics"]["state"] == fleet_meter.NOT_LOADED
        assert up["rows"]["Economics"]["producer"] == LABEL
        assert down["rows"]["Economics"]["producer"] == LABEL

    def test_a_neighbour_label_in_the_fleet_does_not_count(self, one_producer):
        """Загружен СОСЕД — ответ обязан остаться «НЕТ ВО ФЛОТЕ»."""
        row = _axis(loaded={OTHER})["rows"]["Economics"]
        assert row["state"] == fleet_meter.NOT_LOADED


# ───────────────────── 2. третий исход: флот не спрошен ──────────────────────

class TestNotMeasuredIsItsOwnOutcome:
    def test_an_unasked_fleet_is_neither_loaded_nor_absent(self, one_producer):
        """`fleet_asked=True` при `loaded=None` ⇒ НЕ ИЗМЕРЕНО (инв. #17).

        Подставить пустое множество значило бы объявить выключенными ВСЕХ
        производителей разом — ответ уверенно неверный, то есть хуже честно
        неизмеренного.
        """
        row = _axis(loaded=None, fleet_asked=True)["rows"]["Economics"]
        assert row["state"] == fleet_meter.FLEET_UNMEASURED
        assert row["state"] != fleet_meter.NOT_LOADED
        assert row["state"] != fleet_meter.LOADED

    def test_an_empty_fleet_and_an_unasked_fleet_are_not_the_same_answer(self, one_producer):
        empty = _axis(loaded=set())["rows"]["Economics"]
        unasked = _axis(loaded=None, fleet_asked=True)["rows"]["Economics"]
        assert empty["state"] != unasked["state"]

    def test_the_report_counts_the_labels_it_was_actually_given(self, one_producer):
        """`fleet_labels` — ЗАМЕР поданного множества, а не украшение строки.

        Дыра найдена мутацией цикла #1268 (`len(loaded)` → `0`): число печатается
        читателю («флот спрошен, ярлыков N»), и ни одна сцена его не сверяла —
        ноль при спрошенном флоте читался бы как «флот пуст», то есть как
        «выключены ВСЕ производители разом». Мерка дифференциальная: два флота
        РАЗНОГО размера обязаны дать РАЗНЫЕ числа, иначе проверку закрыла бы и
        любая константа.
        """
        one = _axis(loaded={LABEL})
        three = _axis(loaded={LABEL, "com.spa.other", "com.spa.third"})
        assert one["fleet_labels"] == 1
        assert three["fleet_labels"] == 3
        assert _axis(fleet_asked=True)["fleet_labels"] is None

    def test_the_report_says_whether_the_fleet_was_asked_at_all(self, one_producer):
        assert _axis(loaded={LABEL})["fleet_measured"] is True
        assert _axis(loaded=None, fleet_asked=True)["fleet_measured"] is False

    def test_the_fleet_is_asked_by_the_single_door_when_no_input_is_given(
            self, one_producer, monkeypatch):
        """Своей копии `launchctl` у сводки нет: спрашивает дверь соседа."""
        called: list[bool] = []

        def door():
            called.append(True)
            return {LABEL}

        monkeypatch.setattr(rollup.fleet_meter, "fleet_loaded", door)
        row = _axis()["rows"]["Economics"]
        assert called, "дверь живости не спрошена — ось мерила что-то своё"
        assert row["state"] == fleet_meter.LOADED


# ──────────────── 3. исходы, у которых спрашивать НЕ О КОМ ───────────────────

class TestThereIsNobodyToAsk:
    def test_a_criterion_without_a_binding_gets_its_own_outcome(self, one_producer):
        """«Привязки нет» ≠ «служба выключена»: чинится решением, не рубильником."""
        row = _axis(names=("Risk",))["rows"]["Risk"]
        assert row["state"] == fleet_meter.PRODUCER_UNKNOWN
        assert row["artifacts"] == []
        assert "НИ ОДНОГО артефакта" in row["why"]

    def test_an_artifact_without_a_declared_producer(self, monkeypatch):
        _inject(monkeypatch, _manifest([_artifact("data/x.json", None)]))
        row = _axis(loaded=set())["rows"]["Economics"]
        assert row["state"] == fleet_meter.PRODUCER_UNKNOWN
        assert row["artifacts"] == ["data/x.json"]

    def test_colliding_producers_are_not_resolved_silently(self, monkeypatch):
        """Два артефакта одного критерия с РАЗНЫМИ производителями.

        Выбрать первого молча значило бы спрятать столкновение объявлений — и
        напечатать живость службы, которой критерий, может быть, и не обязан.
        """
        _inject(monkeypatch, _manifest([_artifact("data/a.json", LABEL),
                                        _artifact("data/b.json", OTHER)]))
        row = _axis(loaded={LABEL, OTHER})["rows"]["Economics"]
        assert row["state"] == rollup.PRODUCERS_COLLIDE
        assert LABEL in row["why"] and OTHER in row["why"]
        assert row["state"] not in (fleet_meter.LOADED, fleet_meter.NOT_LOADED)

    def test_a_door_that_returns_nothing_is_not_read_as_loaded(
            self, one_producer, monkeypatch):
        """Дверь не вернула строку о производителе, которого сама же назвала.

        Сцена искусственная НАМЕРЕННО: на живой двери этот случай не наступает
        (вход есть ⇒ группа есть), и ровно поэтому ветка без сцены была бы
        зелена по построению. Исход обязан быть НЕ ИЗМЕРЕНО — ни «загружен»,
        ни «выключен»: ответа у нас нет.
        """
        monkeypatch.setattr(rollup.fleet_meter, "producer_rows",
                            lambda inputs, **kw: [])
        row = _axis(loaded={LABEL})["rows"]["Economics"]
        assert row["state"] == fleet_meter.FLEET_UNMEASURED
        assert row["producer"] == LABEL
        assert "НЕ ИЗМЕРЕНА" in row["why"]

    def test_every_outcome_has_a_printable_label(self):
        """Исход без ярлыка печатался бы машинным словом — читатель его не поймёт."""
        for state in (fleet_meter.LOADED, fleet_meter.NOT_LOADED,
                      fleet_meter.FLEET_UNMEASURED, fleet_meter.PRODUCER_UNKNOWN,
                      rollup.PRODUCERS_COLLIDE):
            assert state in rollup.PRODUCER_STATE_RU

    def test_the_labels_are_pairwise_distinct(self):
        """НАЛИЧИЕ ярлыка и РАЗЛИЧИМОСТЬ ярлыков — два разных утверждения.

        Дыра найдена мутацией цикла #1268 (`PRODUCERS_COLLIDE: "ВО ФЛОТЕ"`): проверка
        выше зелена, пока ярлык есть хоть какой, поэтому подмена ярлыка на чужой
        выживала. Исходы различимы машинно (инв. #17), а читателю они предъявляются
        СТРОКОЙ — и если две строки совпали, различимость до него не доезжает:
        «объявления расходятся» он прочёл бы как «во флоте».
        """
        states = (fleet_meter.LOADED, fleet_meter.NOT_LOADED,
                  fleet_meter.FLEET_UNMEASURED, fleet_meter.PRODUCER_UNKNOWN,
                  rollup.PRODUCERS_COLLIDE)
        labels = [rollup.PRODUCER_STATE_RU[st] for st in states]
        assert len(set(labels)) == len(states), (
            "два исхода печатаются ОДНОЙ строкой — читатель их не различит: "
            + ", ".join(f"{st}={rollup.PRODUCER_STATE_RU[st]!r}" for st in states))


# ──────────────────── 4. ось не притворяется, что мерит свежесть ──────────────

def test_the_axis_does_not_claim_a_freshness_it_never_measured(one_producer, monkeypatch):
    """Двери живости подаётся `state=None`, а НЕ `fresh`.

    Подставить `fresh` значило бы соврать о том, чего ось не мерила (свежесть —
    вопрос `s49_surface_freshness`); подставить `unbound` — дверь отбросила бы
    вход, и производитель остался бы неклассифицированным.
    """
    seen: list[dict] = []
    real = fleet_meter.producer_rows

    def spy(inputs, **kw):
        rows = list(inputs)
        seen.extend(rows)
        return real(rows, **kw)

    monkeypatch.setattr(rollup.fleet_meter, "producer_rows", spy)
    _axis(loaded={LABEL})
    assert seen, "дверь классификации не вызвана — ось завела свою копию правила"
    assert {r["state"] for r in seen} == {None}


# ──────────────────────── 5. ось доходит ДО ЧИТАТЕЛЯ ─────────────────────────

def _measure(tmp_path, manifest, **kw):
    return rollup.measure(_scene(tmp_path, manifest),
                          probe_runner=lambda spec, **k: (rollup.NOT_SATISFIED, "ф"),
                          **kw)


@pytest.fixture()
def declared(monkeypatch):
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {"Economics": ["economics_probe"]})
    monkeypatch.setattr(rollup, "probe_tree_inputs", lambda spec: [])


class TestTheReaderGetsTheAxis:
    def test_the_row_carries_the_producer_and_the_lever_names_the_criterion(
            self, tmp_path, declared):
        manifest = _manifest([_artifact("data/keep_dominance_census.json", LABEL)])
        report = _measure(tmp_path, manifest, loaded=set())
        row = [r for r in report["rows"] if r["criterion"] == "Economics"][0]
        assert row["producer"]["state"] == fleet_meter.NOT_LOADED
        assert report["owner_lever_not_satisfied"] == ["Economics"]
        assert report["producer_counts"] == {fleet_meter.NOT_LOADED: 1}

    def test_a_satisfied_criterion_stays_out_of_the_owner_lever(
            self, tmp_path, declared):
        """Выполненный критерий в рычаг владельца НЕ входит, даже если производителя нет.

        Дыра найдена мутацией цикла #1268 (`if r["verdict"] != SATISFIED` → `if True`):
        во всех прежних сценах `probe_runner` отвечал `NOT_SATISFIED`, поэтому фильтр
        был бездействующим — классический дефект СЦЕНЫ, а не кода. На живом дереве
        27.11 различие НЕ теоретическое: `Owner visibility` ВЫПОЛНЕН при том же
        выключенном производителе, и рычаг обязан назвать 12 критериев, а не 13.
        Рычаг — утверждение «вот что НЕ ПЕРЕМЕРИТЬ без владельца»; выполненный
        критерий перемерять не надо, и записать его туда значило бы завысить цену
        отсутствия агента.
        """
        manifest = _manifest([_artifact("data/keep_dominance_census.json", LABEL)])
        report = rollup.measure(
            _scene(tmp_path, manifest),
            probe_runner=lambda spec, **k: (rollup.SATISFIED, "выполнен"),
            loaded=set())
        row = [r for r in report["rows"] if r["criterion"] == "Economics"][0]
        assert row["verdict"] == rollup.SATISFIED
        assert row["producer"]["state"] == fleet_meter.NOT_LOADED, (
            "предпосылка сцены не обеспечена: производителя обязано не быть во флоте")
        assert report["owner_lever_not_satisfied"] == [], (
            "выполненный критерий попал в рычаг владельца — цена отсутствия агента завышена")

    def test_a_loaded_producer_leaves_the_lever_measured_and_empty(
            self, tmp_path, declared):
        """«Мерили, таких нет» — пустой СПИСОК, а не `None` (инв. #17)."""
        manifest = _manifest([_artifact("data/keep_dominance_census.json", LABEL)])
        report = _measure(tmp_path, manifest, loaded={LABEL})
        assert report["owner_lever_not_satisfied"] == []
        assert report["producer_counts"] == {fleet_meter.LOADED: 1}

    def test_the_axis_reads_the_constitution_of_the_tree_under_verdict(
            self, tmp_path, declared):
        """Выжившая мутация #1266: `price_tree` подменён на `repo_root`.

        Сцены выше не различали эти два дерева (`measure_tree` в них None, и
        деревья СОВПАДАЛИ), поэтому подмена проходила насквозь зелёной — дефект
        был у СЦЕНЫ, а не у кода, и записан он здесь, а не замазан. Вред
        настоящий и ровно тот, о котором сводка уже говорит вслух словом
        `split_tree`: ответ о живости производителя, объявленного в ЧУЖОЙ
        конституции, есть вердикт НИ О ОДНОМ существующем дереве.

        Две конституции отличаются ТОЛЬКО производителем, и флот подан так, что
        верное дерево даёт «НЕТ ВО ФЛОТЕ», а неверное — «ВО ФЛОТЕ»: мутация,
        прочитавшая не то дерево, обязана поменять вердикт.
        """
        here = _scene(tmp_path / "here",
                      _manifest([_artifact("data/k.json", LABEL)]))
        there = _scene(tmp_path / "there",
                       _manifest([_artifact("data/k.json", OTHER)]))
        report = rollup.measure(
            here, measure_tree=there, loaded={LABEL},
            probe_runner=lambda spec, **k: (rollup.NOT_SATISFIED, "ф"))
        row = [r for r in report["rows"] if r["criterion"] == "Economics"][0]
        assert row["producer"]["producer"] == OTHER, (
            "ось прочитала конституцию ДЕРЕВА ПРИБОРА, а вердикт вынесен о другом")
        assert row["producer"]["state"] == fleet_meter.NOT_LOADED
        assert report["owner_lever_not_satisfied"] == ["Economics"]

    def test_an_unreadable_constitution_kills_the_axis_and_not_the_summary(
            self, tmp_path, declared):
        """Непрочитанная конституция гасит ОСЬ: вердикты уже сняты и остаются верны.

        И молчать нельзя — «производителя нет во флоте» обязано быть отличимо от
        «ось не мерили вовсе»: `None` у рычага против пустого списка.
        """
        report = _measure(tmp_path, None, loaded=set())
        assert report["producer_problem"]
        assert price_meter.MANIFEST_REL in report["producer_problem"]
        assert report["owner_lever_not_satisfied"] is None
        assert report["producer_counts"] is None
        assert report["counts"][rollup.NOT_SATISFIED] == 1

    def test_the_printed_summary_names_the_owner_lever(self, tmp_path, declared, capsys):
        """Находка обязана дойти до ГЛАЗ, а не только до JSON."""
        manifest = _manifest([_artifact("data/keep_dominance_census.json", LABEL)])
        root = _scene(tmp_path, manifest)
        rollup.main(["--repo-root", root])
        out = capsys.readouterr().out
        assert "ПРОИЗВОДИТЕЛЬ ·" in out
        assert "производитель меры" in out


# ──────────────── 6. дверь ОДНА: своей копии `launchctl` нет ──────────────────

class TestTheFleetDoorIsNotDuplicated:
    def test_the_rollup_never_spells_launchctl_in_executable_code(self):
        """Вторая копия двери разошлась бы молча (ADR-220) — и читатель получил бы
        ДВА ответа о живости одной службы.

        Мерится AST, а НЕ подстрока: подстрокой этот самый файл и тот же вопрос у
        сводки покраснели бы на собственном ДОКСТРИНГЕ, который дверь честно
        НАЗЫВАЕТ. «Имя упомянуто» и «имя исполняется» — разные утверждения, и
        мерка, их путающая, учит убирать объяснение вместо копии (урок цикла
        #1217: дефект был У МЕРКИ, а не у кода).
        """
        tree = ast.parse(open(rollup.__file__, encoding="utf-8").read())
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                first = (node.body or [None])[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                        and isinstance(first.value.value, str):
                    docstrings.add(id(first.value))
        live = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in docstrings and "launchctl" in n.value]
        assert not live, live

    def test_the_axis_calls_the_neighbour_doors_by_name(self):
        """Мерится AST, а не подстрокой: упоминание двери в докстринге зовом не
        является (урок цикла #1217 о дефекте МЕРКИ, а не кода)."""
        tree = ast.parse(open(rollup.__file__, encoding="utf-8").read())
        axis = [n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "producer_axis"]
        assert len(axis) == 1, "функции `producer_axis` в сводке нет"
        called = {ast.unparse(n.func) for n in ast.walk(axis[0])
                  if isinstance(n, ast.Call)}
        for door in ("fleet_meter.fleet_loaded", "fleet_meter.producer_rows",
                     "fleet_meter.producer_of", "price_meter.read_manifest",
                     "price_meter.parse_bindings"):
            assert door in called, (door, sorted(called))


# ─────────────── 7. паритет с НАСТОЯЩИМ деревом (а не только сценой) ─────────

class TestTheRealTreeIsAnswerable:
    def test_every_real_s49_criterion_gets_a_declared_outcome(self):
        """На живом населении §49 и живой конституции ось отвечает КАЖДОМУ.

        Флот здесь всё равно ВХОД: проверяется словарность исходов и полнота
        населения, а не то, что загружено на этой машине сегодня.
        """
        card = os.path.join(_REPO, rollup.CARD_REL)
        if not os.path.isfile(card):
            pytest.fail("карточки приказа в дереве нет — паритет НЕ ИЗМЕРЕН, "
                        "и это не «ось в порядке»")
        with open(card, encoding="utf-8") as handle:
            names = rollup.parse_s49_criteria(handle.read())
        assert names, "население §49 не прочитано — условие не проверено"
        axis = rollup.producer_axis(names, repo_root=_REPO, loaded=set())
        assert set(axis["rows"]) == set(names)
        vocabulary = set(rollup.PRODUCER_STATE_RU)
        assert {r["state"] for r in axis["rows"].values()} <= vocabulary
        assert sum(axis["counts"].values()) == len(names)
