"""Контроль пробы `edge_corpus_screen_pinned_by_name` (ADR-1108, цикл #1254).

Проба объявлена критерием карточки `inbox-lovushka-naseleniya-kromki-srabotala-kor` и по
`.claude/rules/acceptance.md` п. 3 регистрируется только с контролем В ОБЕ СТОРОНЫ: зелёная
на целом контуре и КРАСНАЯ на каждом порванном звене — с названным звеном.

**Несущий замер этого файла — слепота счётчиков, и она ИЗМЕРЕНА, а не предположена**
(`test_renaming_a_member_leaves_every_count_untouched`): переименование одного члена
остатка оставляет население 47 и ведра 30/4/7/6 дословно теми же. Прежняя редакция
ловушки держалась на этих четырёх числах, то есть молчаливая подмена члена остатка
заказа #103 проходила бы ЗЕЛЁНОЙ. Это положительный контроль усиления: проверка, никогда
не видевшая настоящей поломки, есть украшение (`.claude/rules/deployment.md`).

Сцены строятся так, что живой КОРПУС остаётся настоящим (сцена подменяет только
ОЖИДАНИЕ в копии файла-ловушки) — иначе проба мерила бы выдуманный корпус, а вопрос у неё
про расхождение закреплённого с настоящим.

Чего этот файл НЕ проверяет, и это сказано вслух: ветка пробы «переименование сдвинуло
счётчики ⇒ `unmeasured`» сценой не покрыта — синтезировать корпус, где переименование
меняет ведра, нечем, кроме подделки самого прибора, а подделанный прибор отвечал бы на
вопрос о подделке. Ветка оставлена как fail-CLOSED по инв. #17 и названа здесь, а не
выдана за проверенную.
"""

from __future__ import annotations

import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import spa_core.monitoring.card_acceptance as ca  # noqa: E402

TRAP = ROOT / "spa_core" / "tests" / "test_edge_boundary_dataflow_census.py"
PROBE = "edge_corpus_screen_pinned_by_name"


def _probe(root: Path) -> tuple[str, str]:
    return ca.PROBES[PROBE](None, repo_root=str(root))


@contextlib.contextmanager
def _scene(tail: str):
    """Одноразовое дерево: НАСТОЯЩИЙ корпус + копия ловушки с подменённым ожиданием.

    `scripts/` подаётся символической ссылкой намеренно: корпус обязан остаться живым,
    иначе проба отвечала бы о выдуманном населении, а не о расхождении закреплённого с
    настоящим.
    """
    tmp = Path(tempfile.mkdtemp(prefix="spa_edge_scene_"))
    try:
        (tmp / "scripts").symlink_to(SCRIPTS, target_is_directory=True)
        (tmp / "spa_core" / "tests").mkdir(parents=True)
        (tmp / "spa_core" / "tests" / TRAP.name).write_text(
            TRAP.read_text(encoding="utf-8") + tail, encoding="utf-8")
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _pinned() -> dict[str, tuple[str, ...]]:
    import importlib.util

    spec = importlib.util.spec_from_file_location("spa_trap_for_control", TRAP)
    mod = importlib.util.module_from_spec(spec)          # type: ignore[arg-type]
    sys.modules["spa_trap_for_control"] = mod
    try:
        spec.loader.exec_module(mod)                     # type: ignore[union-attr]
        return {k: tuple(sorted(v)) for k, v in mod.CENSUS_100_SCREEN.items()}
    finally:
        sys.modules.pop("spa_trap_for_control", None)


def _override(mapping: dict[str, tuple[str, ...]]) -> str:
    return "\n\nCENSUS_100_SCREEN = " + repr({k: tuple(v) for k, v in mapping.items()}) + "\n"


class TestCountsAreBlindToASilentSwap(unittest.TestCase):
    """Положительный контроль САМОГО усиления: класс настоящий и счётчики его не видят."""

    def test_renaming_a_member_leaves_every_count_untouched(self):
        import edge_boundary_dataflow_census as bdc
        import edge_split_protocol_diagnostic as spd

        def screen(corpus: Path):
            with contextlib.redirect_stdout(io.StringIO()):
                census = spd.section1_census(corpus)
            return census

        with bdc.corpus_without_self(SCRIPTS) as mirror:
            before = screen(Path(mirror))
            scene = Path(tempfile.mkdtemp(prefix="spa_edge_swap_")) / "corpus"
            shutil.copytree(mirror, scene)
        try:
            names = sorted(Path(m).name for v in before["buckets"].values() for m in v)
            victim = names[0]
            (scene / victim).rename(scene / (victim[:-3] + "_renamed.py"))
            after = screen(scene)

            self.assertEqual(after["population"], before["population"],
                             "сцена обязана сохранить население — иначе это не тот класс")
            self.assertEqual({k: len(v) for k, v in after["buckets"].items()},
                             {k: len(v) for k, v in before["buckets"].items()},
                             "ВСЕ ЧЕТЫРЕ счётчика обязаны остаться дословно теми же: "
                             "именно поэтому ожидание на счётчиках пропускало подмену")
            self.assertNotEqual(
                {k: tuple(sorted(Path(m).name for m in v)) for k, v in after["buckets"].items()},
                {k: tuple(sorted(Path(m).name for m in v)) for k, v in before["buckets"].items()},
                "карта имён обязана РАЗОЙТИСЬ — иначе усиление ничего не добавляет")
        finally:
            shutil.rmtree(scene.parent, ignore_errors=True)


class TestTheProbeIsGreenOnTheWholeContour(unittest.TestCase):

    def test_the_live_tree_satisfies_the_criterion(self):
        verdict, why = _probe(ROOT)
        self.assertEqual(verdict, ca.SATISFIED, why)
        self.assertIn("47", why, "число населения обязано быть НАЗВАНО в вердикте")


class TestTheProbeIsRedOnEachBrokenLink(unittest.TestCase):
    """Каждое звено рвётся по отдельности, и проба обязана назвать именно его."""

    def test_an_expectation_without_the_name_map_fails(self):
        with _scene("\n\nCENSUS_100_SCREEN = None\n") as root:
            verdict, why = _probe(root)
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("CENSUS_100_SCREEN", why)
        self.assertIn("счётчик", why, "звено обязано быть названо: ожидание на счётчиках")

    def test_a_member_moved_between_buckets_with_counts_preserved_fails(self):
        """ТО САМОЕ звено: итоги сходятся, а член подменён."""
        pinned = _pinned()
        a, b = "RE-RUNS ON THE SLICE", "BOUNDARY USED, BUT NEVER AS A SLICE INDEX"
        swapped = dict(pinned)
        swapped[a] = tuple(sorted(set(pinned[a]) - {pinned[a][0]} | {pinned[b][0]}))
        swapped[b] = tuple(sorted(set(pinned[b]) - {pinned[b][0]} | {pinned[a][0]}))
        self.assertEqual({k: len(v) for k, v in swapped.items()},
                         {k: len(v) for k, v in pinned.items()},
                         "сцена обязана сохранить счётчики — иначе звено не то")

        with _scene(_override(swapped)) as root:
            verdict, why = _probe(root)
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("СМЕНИЛ ВЕДРО", why)
        self.assertIn(pinned[a][0], why, "ИМЯ сдвинувшегося модуля обязано быть названо")

    def test_a_member_missing_from_the_pin_fails_and_names_it(self):
        pinned = _pinned()
        b = "BOUNDARY USED, BUT NEVER AS A SLICE INDEX"
        dropped = pinned[b][0]
        thin = dict(pinned)
        thin[b] = tuple(n for n in pinned[b] if n != dropped)

        with _scene(_override(thin)) as root:
            verdict, why = _probe(root)
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("ПРИБАВИЛСЯ", why)
        self.assertIn(dropped, why)

    def test_the_criterion_does_not_pass_by_substring(self):
        """ADR-333: объявление, лежащее в тексте, критерия не выполняет."""
        pinned = _pinned()
        prose = ('\n\nCENSUS_100_SCREEN = None\n'
                 '_PROSE = """перевыведено замером, карта «имя → ведро»: '
                 + repr({k: tuple(v) for k, v in pinned.items()}) + '"""\n')
        with _scene(prose) as root:
            verdict, why = _probe(root)
        self.assertNotEqual(verdict, ca.SATISFIED,
                            "карта, присутствующая только как ТЕКСТ, критерия не выполняет: "
                            f"{why}")


class TestTheThirdOutcomeIsDistinguishable(unittest.TestCase):
    """Инв. #17: «не измерено» никогда не выдаётся ни за «чисто», ни за находку."""

    def test_a_tree_without_the_trap_is_unmeasured(self):
        tmp = Path(tempfile.mkdtemp(prefix="spa_edge_notrap_"))
        try:
            (tmp / "scripts").symlink_to(SCRIPTS, target_is_directory=True)
            verdict, why = _probe(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(verdict, ca.UNMEASURED, why)
        self.assertIn("ловушки нет", why, "причина обязана быть названа")

    def test_a_tree_without_the_corpus_is_unmeasured(self):
        tmp = Path(tempfile.mkdtemp(prefix="spa_edge_nocorpus_"))
        try:
            (tmp / "spa_core" / "tests").mkdir(parents=True)
            (tmp / "spa_core" / "tests" / TRAP.name).write_text(
                TRAP.read_text(encoding="utf-8"), encoding="utf-8")
            verdict, why = _probe(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(verdict, ca.UNMEASURED, why)
        self.assertIn("корпус не читается", why)

    def test_the_probe_takes_no_argument_and_says_so(self):
        verdict, why = ca.PROBES[PROBE]("some-file.md", repo_root=str(ROOT))
        self.assertEqual(verdict, ca.UNMEASURED, why)
        self.assertIn("не принимает аргумента", why)


if __name__ == "__main__":
    unittest.main()
