#!/usr/bin/env python3
"""Закрытый перечень обязательных полей отчёта обязан СПРОСИТЬ производителя — ADR-1116.

`scripts/cartographer/brief.py::REQUIRED_DIFF_KEYS` перечисляет поля, без которых
сохранённое сравнение (`diff.json`) не принимается к публикации брифинга. Перечень
НАБРАН РУКОЙ, а документ производит ДРУГОЙ модуль — `scripts/cartographer/diff.py`.
Новое поле в производителе до сих пор не краснило ничего: читатель просто не требовал
его, то есть принимал документ, в котором поля нет, и публиковал брифинг молча.

**Почему это именно наш класс (ADR-1113).** Перечень сверяется ВНУТРЬ прочитанного
документа (`for k in REQUIRED_DIFF_KEYS if k not in stored`) — потеря члена меняет
вердикт, значит он положительный контроль, и его полнота есть вопрос. ADR-1114/1115
измерили: у этого перечня внешний источник полноты ЕСТЬ, и это **ПРОИЗВОДИТЕЛЬ**
документа. Мерки у него не было — её даёт этот файл.

**Производителя спрашивают ДВАЖДЫ, и согласие — предпосылка замера.** ADR-1115 сам
предупредил, на чём ошибаются восемь отклонённых кандидатов: ключи ОДНОГО прочитанного
документа — ЭКЗЕМПЛЯР, а не контракт. Поэтому:

* дверь ПОВЕДЕНИЯ — настоящий `diff.compare()` на настоящей сцене, ключи его вывода;
* дверь ДЕРЕВА — AST литерала, из которого документ собран, плюс поздние присваивания.

Расходятся ⇒ **НЕ ИЗМЕРЕНО** с названной разницей: такое расхождение означает, что
какое-то поле условно, и тогда «ключи одного прогона» действительно не контракт.
Согласны ⇒ вопрос о полноте поставлен корректно, и набор есть контракт.

**Мерка двусторонняя.** Контракт обязан быть РОВНО объединением двух объявлений
читателя: `REQUIRED_DIFF_KEYS` (требуем) и `NOT_REQUIRED_DIFF_KEYS` (не требуем, с
причиной). Отсюда три находки, и каждая своя:

1. поле производителя не названо ни там, ни там — новое поле проехало молча;
2. требуется поле, которого производитель больше не выдаёт — читатель отказал бы
   КАЖДОМУ верному документу (краснота на верном состоянии);
3. объявлено исключение для поля, которого в контракте нет — мусор в объявлении.

**Третий исход (инв. #17)** назван у каждой двери: нет сцены, нет функции `compare`,
ключ задан не литералом — «НЕ ИЗМЕРЕНО» с причиной, а не тихий зелёный.

**Сцена берётся у соседа намеренно.** `tests/cartographer/test_diff.py::_snap` —
канонический снимок в форме, которую принимает `validate_snapshot`. Вторая копия
фикстуры разошлась бы с первой, и тогда две мерки судили бы о РАЗНЫХ производителях.

**Перемер утверждения предшественника (цикл #1262).** ADR-1115 закончил словами «два
подтверждённых источника — предмет СЛЕДУЮЩЕЙ работы, и мерки у них по-прежнему нет».
Перемерено: у второго подтверждённого —
`spa_core/tests/test_site_snapshot_view_shape.py::NOT_IN_VIEW` — мерка ЕСТЬ и давно:
три проверки (снимок ⊆ переходник ∪ объявленное · объявленное ⊆ снимок · у каждого
исключения причина) плюс положительный контроль снятием настоящего поля, и она
ИСПОЛНЯЕТСЯ (замер на `cf5d12299`: `node` есть, файлы есть, 1 failed / 3 passed).
Предмет был ОДИН, а не два; это записано и в приборе (`MEASURES`), чтобы прозой
больше не повторялось.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CARTO = ROOT / "scripts" / "cartographer"
DIFF_SRC = CARTO / "diff.py"
SCENE_SRC = ROOT / "tests" / "cartographer" / "test_diff.py"


class NotMeasured(RuntimeError):
    """Замер не состоялся; причина названа."""


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise NotMeasured(f"модуль {path} не загружается — спросить нечего")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def observed_contract() -> set:
    """Дверь ПОВЕДЕНИЯ: ключи документа, который производитель РЕАЛЬНО собрал."""
    if not SCENE_SRC.is_file():
        raise NotMeasured(f"канонической сцены нет ({SCENE_SRC}) — производителя не запустить")
    scene = _load(SCENE_SRC, "_c1262_scene")
    snap = getattr(scene, "_snap", None)
    diff_mod = getattr(scene, "d", None)
    if snap is None or diff_mod is None:
        raise NotMeasured("сцена больше не отдаёт `_snap`/`d` — форма соседа сменилась")
    with tempfile.TemporaryDirectory() as td:
        dirs = []
        for name, over in (("old", {}), ("new", {"finished_at": "2026-09-20T10:00:09+00:00"})):
            p = Path(td) / name
            p.mkdir()
            (p / "snapshot.json").write_text(json.dumps(snap(**over)), encoding="utf-8")
            dirs.append(p)
        try:
            produced = diff_mod.compare(diff_mod.load_set(dirs[0]), diff_mod.load_set(dirs[1]))
        except Exception as exc:  # noqa: BLE001 — любая причина отказа есть «не измерено»
            raise NotMeasured(f"производитель не собрал документ: {type(exc).__name__}: {exc}") from None
    if not isinstance(produced, dict) or not produced:
        raise NotMeasured("производитель вернул не документ")
    return set(produced)


def declared_contract(source: str) -> set:
    """Дверь ДЕРЕВА: ключи, которые производитель ОБЪЯВЛЯЕТ в `compare()`.

    Спрашивается литерал, из которого документ собран, и поздние присваивания
    `diff[...] = ...`. Ключ, заданный не литералом, — НЕ ИЗМЕРЕНО: набор по дереву
    такого не определить, и выдумывать его значило бы ответить о другом наборе.
    """
    tree = ast.parse(source)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "compare"),
              None)
    if fn is None:
        raise NotMeasured("в производителе нет функции `compare` — объявления не найти")
    keys: set = set()
    literal_seen = False
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (isinstance(target, ast.Name) and target.id == "diff"
                    and isinstance(node.value, ast.Dict)):
                literal_seen = True
                for key in node.value.keys:
                    if key is None:
                        raise NotMeasured("в литерале документа есть `**` — набор ключей "
                                          "по дереву не определить")
                    if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                        raise NotMeasured("ключ документа задан НЕ строковым литералом")
                    keys.add(key.value)
            elif (isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
                    and target.value.id == "diff"):
                sl = target.slice
                if not (isinstance(sl, ast.Constant) and isinstance(sl.value, str)):
                    raise NotMeasured("позднее присваивание в документ идёт НЕ по "
                                      "строковому литералу")
                keys.add(sl.value)
    if not literal_seen:
        raise NotMeasured("литерала документа в `compare()` не найдено — "
                          "производитель собирает его иначе")
    return keys


def agreed_contract(observed: set, declared: set) -> set:
    """ЕДИНСТВЕННАЯ дверь к согласию двух дверей; расхождение — НЕ ИЗМЕРЕНО.

    Вынесено отдельной функцией не ради красоты: сегодня двери СОГЛАСНЫ, и мутация
    «снять согласие» выживала — ни одна сцена её не различала (урок циклов
    #1202/#1217). Различающие сцены ниже подают несогласные наборы прямо сюда.
    """
    if set(observed) != set(declared):
        raise NotMeasured(
            "две двери к производителю не согласны, значит какое-то поле условно и ОДИН "
            f"документ контрактом не является: только в прогоне {sorted(set(observed) - set(declared))}, "
            f"только в дереве {sorted(set(declared) - set(observed))}")
    return set(observed)


def verdict(contract: set, required, exempt) -> dict:
    """ЕДИНСТВЕННАЯ дверь к алгебре мерки: три находки, каждая со своей причиной."""
    required, exempt = set(required), set(exempt)
    return {
        "unclassified": sorted(contract - required - exempt),
        "stale_required": sorted(required - contract),
        "stale_exempt": sorted(exempt - contract),
        "both": sorted(required & exempt),
    }


class TheReaderAsksTheProducer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.brief = _load(CARTO / "brief.py", "_c1262_brief")

    def _contract(self) -> set:
        """Контракт производителя — только когда ОБЕ двери согласны."""
        try:
            observed = observed_contract()
            declared = declared_contract(DIFF_SRC.read_text(encoding="utf-8"))
        except NotMeasured as exc:
            self.fail(f"НЕ ИЗМЕРЕНО — {exc}")
        except OSError as exc:
            self.fail(f"НЕ ИЗМЕРЕНО — исходник производителя не прочитан: {exc}")
        try:
            return agreed_contract(observed, declared)
        except NotMeasured as exc:
            self.fail(f"НЕ ИЗМЕРЕНО — {exc}")

    def test_the_two_doors_to_the_producer_agree(self):
        """Предпосылка замера, и она проверяется ОТДЕЛЬНО от самой мерки."""
        self.assertTrue(self._contract())

    def test_the_pair_exhausts_the_producer_document(self):
        got = verdict(self._contract(), self.brief.REQUIRED_DIFF_KEYS,
                      self.brief.NOT_REQUIRED_DIFF_KEYS)
        self.assertEqual(got["unclassified"], [], (
            f"производитель выдаёт поля, которых читатель не требует и не освобождал: "
            f"{got['unclassified']}. Либо в REQUIRED_DIFF_KEYS, либо в "
            f"NOT_REQUIRED_DIFF_KEYS С ПРИЧИНОЙ — «ни там, ни там» и есть молчаливый проезд"))
        self.assertEqual(got["stale_required"], [], (
            f"читатель требует поля, которых производитель больше не выдаёт: "
            f"{got['stale_required']} — он отказал бы КАЖДОМУ верному документу"))
        self.assertEqual(got["stale_exempt"], [], (
            f"в освобождениях поля, которых в контракте нет: {got['stale_exempt']}"))
        self.assertEqual(got["both"], [], (
            f"поле названо и требуемым, и освобождённым: {got['both']} — "
            f"два объявления об одном поле спорят"))

    def test_every_exemption_carries_a_reason(self):
        empty = sorted(k for k, v in self.brief.NOT_REQUIRED_DIFF_KEYS.items()
                       if not str(v).strip())
        self.assertEqual(empty, [], f"освобождение без причины: {empty}")

    # ── положительные контроли: каждая находка воспроизведена ────────────────

    def test_a_new_producer_key_is_named(self):
        contract = self._contract() | {"brand_new_field_c1262"}
        got = verdict(contract, self.brief.REQUIRED_DIFF_KEYS,
                      self.brief.NOT_REQUIRED_DIFF_KEYS)
        self.assertEqual(got["unclassified"], ["brand_new_field_c1262"])

    def test_a_requirement_the_producer_dropped_is_named(self):
        victim = self.brief.REQUIRED_DIFF_KEYS[0]
        got = verdict(self._contract() - {victim}, self.brief.REQUIRED_DIFF_KEYS,
                      self.brief.NOT_REQUIRED_DIFF_KEYS)
        self.assertEqual(got["stale_required"], [victim])

    def test_an_exemption_the_producer_dropped_is_named(self):
        victim = sorted(self.brief.NOT_REQUIRED_DIFF_KEYS)[0]
        got = verdict(self._contract() - {victim}, self.brief.REQUIRED_DIFF_KEYS,
                      self.brief.NOT_REQUIRED_DIFF_KEYS)
        self.assertEqual(got["stale_exempt"], [victim])

    def test_the_tree_door_reads_the_literal_and_not_a_memory(self):
        """Контроль САМОЙ двери: подложен исходник, и ответ обязан смениться."""
        synthetic = (
            "def compare(old, new):\n"
            "    diff = {'alpha': 1, 'beta': 2}\n"
            "    diff['gamma'] = 3\n"
            "    return diff\n")
        self.assertEqual(declared_contract(synthetic), {"alpha", "beta", "gamma"})

    def test_the_tree_door_refuses_a_computed_key(self):
        synthetic = ("NAME = 'x'\n"
                     "def compare(old, new):\n"
                     "    diff = {NAME: 1}\n"
                     "    return diff\n")
        with self.assertRaises(NotMeasured):
            declared_contract(synthetic)

    def test_the_tree_door_refuses_a_producer_without_compare(self):
        with self.assertRaises(NotMeasured):
            declared_contract("def collect():\n    return {}\n")

    # ── различающие сцены для самого согласия (мутация «снять согласие») ─────

    def test_the_agreement_gate_passes_equal_sets(self):
        self.assertEqual(agreed_contract({"a", "b"}, {"b", "a"}), {"a", "b"})

    def test_the_agreement_gate_refuses_a_key_only_the_run_produced(self):
        with self.assertRaises(NotMeasured) as ctx:
            agreed_contract({"a", "b"}, {"a"})
        self.assertIn("только в прогоне ['b']", str(ctx.exception))

    def test_the_agreement_gate_refuses_a_key_only_the_tree_declares(self):
        with self.assertRaises(NotMeasured) as ctx:
            agreed_contract({"a"}, {"a", "b"})
        self.assertIn("только в дереве ['b']", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
