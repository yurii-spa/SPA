"""Проба `ci_claim_carriers_population_named` обязана РАЗЛИЧАТЬ, а не кивать.

# LLM_FORBIDDEN

`.claude/rules/acceptance.md` п. 3: новая проба регистрируется только с
тестом, где она зелена на ЦЕЛОМ контуре и красна на КАЖДОМ порванном звене —
с названным звеном, — и где она НЕ проходит подстрокой (ADR-333).

Контур здесь — прибор `spa_core/monitoring/ci_claim_provenance.py`. Каждое
звено рвётся ОТДЕЛЬНО, правкой КОПИИ прибора в одноразовом дереве; живой
прибор не трогается ни одной сценой, и `data/` живого дерева тоже (дерево
сцены несёт свой announce-лог).
"""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import card_acceptance as ca

_ROOT = Path(__file__).resolve().parents[2]
_PROBER = _ROOT / "spa_core" / "monitoring" / "ci_claim_provenance.py"
_PROBE = "ci_claim_carriers_population_named"

#: Претензия без личности: число есть, номера прогона нет.
CLAIM = ("контрольный прогон CI `main` **RED** (failed=67 из 137 166) — "
         "состав не читался")


def _scene(tmp: str, *, source: str | None = None,
           with_prober: bool = True) -> str:
    """Одноразовое дерево: носители и прибор кладёт САМА сцена.

    Поверхность живого звена пробы обязана быть НЕПУСТОЙ и обязана иметь
    кандидата у оси цитаты — иначе проба честно ответит «вакуум», и сцена
    измерит не то звено, которое рвала.
    """
    root = Path(tmp) / "дерево"
    (root / "spa_core" / "monitoring").mkdir(parents=True, exist_ok=True)
    if with_prober:
        text = source if source is not None else _PROBER.read_text(encoding="utf-8")
        (root / "spa_core" / "monitoring" / "ci_claim_provenance.py").write_text(
            text, encoding="utf-8")
    jrn = root / "docs" / "journal"
    jrn.mkdir(parents=True, exist_ok=True)
    (jrn / "W01.md").write_text("шапка\n\n" + CLAIM + "\n", encoding="utf-8")
    (jrn / "W02.md").write_text(
        "«незакрытая кавычка в записи без претензии\n", encoding="utf-8")
    trk = root / "nimbalyst-local" / "tracker"
    trk.mkdir(parents=True, exist_ok=True)
    (trk / "card.md").write_text("разбор: «" + CLAIM + "» — перемерено\n",
                                 encoding="utf-8")
    prod = root / "scripts" / "morning_work_digest.py"
    prod.parent.mkdir(parents=True, exist_ok=True)
    prod.write_text('def f(n):\n'
                    '    return f"АВТОПРОВЕРКА КОДА: КРАСНАЯ, красных {n}"\n',
                    encoding="utf-8")
    data = root / "data"
    data.mkdir(exist_ok=True)
    (data / "session_changes.jsonl").write_text(
        '{"ts": "t", "summary": "контрольный прогон 45967869368 заказан"}\n',
        encoding="utf-8")
    return str(root)


def _mutate(old: str, new: str, *, count: int = 1) -> str:
    """Правка КОПИИ прибора. Якорь обязан быть УНИКАЛЕН.

    Иначе «мутация не применилась» выглядит как «звено целое, проба зелена» —
    и сцена докладывает о себе, а не о пробе.
    """
    src = _PROBER.read_text(encoding="utf-8")
    assert src.count(old) == count, (
        f"якорь не уникален ({src.count(old)} вхождений) — сцена не собралась")
    return src.replace(old, new)


class TheProbeIsGreenOnTheWholeContour(unittest.TestCase):
    def test_the_whole_contour_is_satisfied(self):
        with TemporaryDirectory() as tmp:
            root = _scene(tmp)
            v, why = ca.run_probe(_PROBE, repo_root=root,
                                  data_dir=str(Path(root) / "data"))
            self.assertEqual(v, ca.SATISFIED, why)
            self.assertIn("НЕ МЕНЬШЕ", why)

    def test_the_probe_takes_no_argument(self):
        with TemporaryDirectory() as tmp:
            root = _scene(tmp)
            v, why = ca.run_probe(_PROBE + ":journal", repo_root=root)
            self.assertEqual(v, ca.UNMEASURED)
            self.assertIn("не принимает аргумента", why)

    def test_the_named_data_dir_reaches_the_probe(self):
        """Иначе число announce было бы о ЗАМОРОЖЕННОМ каноне своего дерева."""
        self.assertIn("data_dir", ca.probe_tree_inputs(_PROBE))
        self.assertIn("repo_root", ca.probe_tree_inputs(_PROBE))


class EachLinkBrokenSeparatelyChangesTheVerdict(unittest.TestCase):
    """Звено рвётся ПОРОЗНЬ, и каждое обязано быть НАЗВАНО в пояснении."""

    def _verdict(self, tmp, **kw) -> tuple[str, str]:
        root = _scene(tmp, **kw)
        return ca.run_probe(_PROBE, repo_root=root,
                            data_dir=str(Path(root) / "data"))

    def test_no_prober_at_all_is_unmeasured_not_a_verdict(self):
        with TemporaryDirectory() as tmp:
            v, why = self._verdict(tmp, with_prober=False)
            self.assertEqual(v, ca.UNMEASURED)
            self.assertIn("прибора провенанса нет", why)

    def test_a_missing_door_is_unmeasured_and_the_door_is_named(self):
        src = _mutate("def format_carriers(doc: dict) -> list[str]:",
                      "def _format_carriers_renamed(doc: dict) -> list[str]:")
        src = src.replace("lines.extend(format_carriers(doc))",
                          "lines.extend(_format_carriers_renamed(doc))")
        with TemporaryDirectory() as tmp:
            v, why = self._verdict(tmp, source=src)
            self.assertEqual(v, ca.UNMEASURED)
            self.assertIn("format_carriers", why)

    def test_dropping_a_carrier_from_the_declaration_is_caught(self):
        src = _mutate(
            '    CARRIER_JOURNAL: ("docs/journal", "*.md"),\n', "")
        with TemporaryDirectory() as tmp:
            v, why = self._verdict(tmp, source=src)
            self.assertEqual(v, ca.UNMEASURED)
            self.assertIn("journal", why)

    def test_a_dead_quotation_axis_is_caught_by_the_tracker_number(self):
        """Пересказ, зачтённый как своя претензия, УДВАИВАЕТ население."""
        src = _mutate("    return QUOTE_NONE, \"претензия не накрыта ни одной "
                      "цитатой\"",
                      "    return QUOTE_NONE, \"ось снята\"")
        src = src.replace(
            "    for (a, b), kind in candidates:",
            "    for (a, b), kind in []:")
        with TemporaryDirectory() as tmp:
            v, why = self._verdict(tmp, source=src)
            self.assertNotEqual(v, ca.SATISFIED)
            self.assertIn("трекер", why)

    def test_collapsing_the_undecided_axis_is_caught_by_the_bracket(self):
        src = _mutate(
            '        return QUOTE_UNDECIDED, (f"у записи есть открыватель цитаты в позиции "',
            '        return QUOTE_NONE, (f"у записи есть открыватель цитаты в позиции "')
        with TemporaryDirectory() as tmp:
            v, why = self._verdict(tmp, source=src)
            self.assertNotEqual(v, ca.SATISFIED)
            self.assertIn("вилку", why)

    def test_swallowing_an_unreadable_file_is_caught(self):
        src = _mutate('            unread.append(f"{path}: {type(exc).__name__}: {exc}")',
                      '            pass')
        with TemporaryDirectory() as tmp:
            root = _scene(tmp, source=src)
            (Path(root) / "docs" / "journal" / "битый.md").write_bytes(
                b"\xff\xfe\x00CI control RED 5")
            v, why = ca.run_probe(_PROBE, repo_root=root,
                                  data_dir=str(Path(root) / "data"))
            self.assertNotEqual(v, ca.SATISFIED)
            self.assertIn("не разобрано", why.lower())

    def test_claiming_the_digest_is_measured_is_caught(self):
        src = _mutate('        "status": "UNMEASURED",\n'
                      '        "files": 0,\n',
                      '        "status": "OK",\n'
                      '        "files": 0,\n')
        with TemporaryDirectory() as tmp:
            v, why = self._verdict(tmp, source=src)
            self.assertNotEqual(v, ca.SATISFIED)
            self.assertIn("сводка", why)

    def test_losing_the_computed_number_outcome_is_caught(self):
        src = _mutate('                doc["templates_with_computed_number"] += 1\n',
                      '                pass\n')
        with TemporaryDirectory() as tmp:
            v, why = self._verdict(tmp, source=src)
            self.assertNotEqual(v, ca.SATISFIED)
            self.assertIn("вычисляемое число", why)

    def test_a_duration_read_as_a_count_is_caught(self):
        src = _mutate("        if _DURATION_RE.match(segment, m.end()):",
                      "        if False:")
        with TemporaryDirectory() as tmp:
            v, why = self._verdict(tmp, source=src)
            self.assertNotEqual(v, ca.SATISFIED)
            self.assertIn("длительност", why.lower())


class TheProbeDoesNotPassOnProse(unittest.TestCase):
    """ADR-333: упоминание носителя в тексте мерой не является."""

    def test_a_stub_that_only_names_the_carriers_is_not_satisfied(self):
        stub = '''"""Носители: announce, tracker, journal, digest. Вилка населения,
не разобрано, НЕ ИЗМЕРЕНО, предмет, цитата, длительность."""
CARRIER_ANNOUNCE = "announce"
CARRIER_TRACKER = "tracker"
CARRIER_JOURNAL = "journal"
CARRIER_DIGEST = "digest"
CARRIERS = (CARRIER_ANNOUNCE, CARRIER_TRACKER, CARRIER_JOURNAL, CARRIER_DIGEST)
CARRIER_PATHS = {CARRIER_TRACKER: ("nimbalyst-local/tracker", "*.md"),
                 CARRIER_JOURNAL: ("docs/journal", "*.md")}
DIGEST_PRODUCER = "scripts/morning_work_digest.py"
QUOTATION_UNDECIDED = "unmeasured_quotation_undecided"


def markdown_records(text):
    return []


def carrier_census(carrier, **kw):
    return {"carrier": carrier, "population_floor": 0, "population_ceiling": 0,
            "claims": [], "unread_files": [], "status": "OK", "unmeasured": []}


def run_census(**kw):
    return {"status": "OK", "carriers": {c: carrier_census(c) for c in CARRIERS},
            "population_floor_total": 0, "population_ceiling_total": 0}


def format_carriers(doc):
    return ["носители: вилка НЕ МЕНЬШЕ 0, НЕ РАЗОБРАНО 0, НЕ ИЗМЕРЕНО нет"]
'''
        with TemporaryDirectory() as tmp:
            root = _scene(tmp, source=stub)
            v, why = ca.run_probe(_PROBE, repo_root=root,
                                  data_dir=str(Path(root) / "data"))
            self.assertNotEqual(v, ca.SATISFIED, why)

    def test_an_empty_surface_is_a_vacuum_not_a_clean_tree(self):
        """«Предмет ноль» на дереве без носителей — вакуум, а не чистота."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "пустое"
            (root / "spa_core" / "monitoring").mkdir(parents=True)
            (root / "spa_core" / "monitoring" / "ci_claim_provenance.py").write_text(
                _PROBER.read_text(encoding="utf-8"), encoding="utf-8")
            data = root / "data"
            data.mkdir()
            (data / "session_changes.jsonl").write_text("", encoding="utf-8")
            v, why = ca.run_probe(_PROBE, repo_root=str(root),
                                  data_dir=str(data))
            self.assertEqual(v, ca.UNMEASURED)
            self.assertIn("ПУСТА", why)


class TheProbeIsRegisteredAndCallable(unittest.TestCase):
    def test_the_probe_is_in_the_registry(self):
        self.assertIn(_PROBE, ca.PROBES)

    def test_an_unregistered_name_is_unmeasured_not_satisfied(self):
        v, why = ca.run_probe("ci_claim_carriers_population_named_NOPE")
        self.assertEqual(v, ca.UNMEASURED)
        self.assertIn("не зарегистрирована", why)


if __name__ == "__main__":
    unittest.main()
