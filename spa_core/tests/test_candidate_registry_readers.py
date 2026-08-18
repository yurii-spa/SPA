"""Честность реестра кандидатов обязана ДОЖИТЬ до каждого читателя (цикл #288).

Класс — тот же, что ведёт весь журнал: «сторож отвечает не на тот вопрос».
Цикл #283 отделил «реестра нет» от «кандидатов ноль» у ОДНОГО читателя
(``alpha_agent``), и на этом честность остановилась внутри одного модуля.
Замер #288 нашёл ещё двоих:

* :func:`spa_core.agents.protocol_research_agent.fetch_defi_candidates` —
  «Fail-safe: missing files → empty list»: отсутствующий реестр приезжал
  неотличимо от измеренного нуля, и недельный отчёт писал ``status: ok``
  с ``new_candidates_found: 0`` — отчёт о работе, которой не было;
* :func:`spa_core.scheduler.loop_scheduler.run_strategic_loop` — читал уже
  ЧЕСТНЫЙ артефакт ``alpha_candidates.json`` и выбрасывал флаг, считая
  ``len(candidates or [])``.

Каждый тест ниже — положительный контроль: воспроизводит ровно то состояние
прода, которое измерено 2026-08-18 (реестра нет, писателя нет), и на
неисправленном коде краснеет. Обратные контроли (измеренный ноль обязан
остаться нулём) стоят рядом, иначе «починка» была бы просто инверсией.

Сеть не трогается, время не трогается, ``data/`` не трогается — всё во
временных каталогах.
"""
from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.adapter_sdk.candidate_registry import (
    REGISTRY_FILENAME,
    read_candidate_registry,
)
from spa_core.agents import alpha_agent, protocol_research_agent
from spa_core.scheduler import loop_scheduler

REPO_ROOT = Path(__file__).resolve().parents[2]


# ─── 1. Одно определение на репо ──────────────────────────────────────────────


class TestOneDefinition(unittest.TestCase):
    """Две копии одной проверки расходятся не «если», а «когда»."""

    def test_both_agents_delegate_to_the_same_reader(self):
        """У alpha_agent и protocol_research_agent ОДИН источник вердикта.

        Краснеет на origin: у ``protocol_research_agent`` не было
        ``candidate_set`` вовсе — он читал реестр своим кодом.
        """
        with TemporaryDirectory() as td:
            ddir = Path(td)
            (ddir / REGISTRY_FILENAME).write_text(
                json.dumps({"candidates": [{"protocol": "x"}]}), encoding="utf-8")

            canonical = read_candidate_registry(ddir)
            self.assertEqual(alpha_agent.candidate_set(ddir), canonical)
            self.assertEqual(protocol_research_agent.candidate_set(ddir), canonical)

    def test_the_reader_lives_outside_both_agents(self):
        """Определение живёт у семьи ПИСАТЕЛЯ, а не внутри одного потребителя."""
        self.assertEqual(
            read_candidate_registry.__module__,
            "spa_core.adapter_sdk.candidate_registry",
        )


# ─── 2. «Не измерено» ≠ «ноль» — у самого чтения ──────────────────────────────


class TestReaderTellsMissingFromZero(unittest.TestCase):

    def test_missing_registry_is_not_measured(self):
        """Состояние прода 2026-08-18: файла нет — и это НЕ ноль кандидатов."""
        with TemporaryDirectory() as td:
            got = read_candidate_registry(Path(td))
        self.assertFalse(got["measured"])
        self.assertEqual(got["items"], [])
        self.assertIn("не найден", got["reason"])

    def test_present_but_empty_registry_IS_a_measured_zero(self):
        """Обратный контроль: discovery отработал и честно никого не принёс."""
        with TemporaryDirectory() as td:
            ddir = Path(td)
            (ddir / REGISTRY_FILENAME).write_text(
                json.dumps({"candidates": []}), encoding="utf-8")
            got = read_candidate_registry(ddir)
        self.assertTrue(got["measured"])
        self.assertEqual(got["items"], [])
        self.assertEqual(got["reason"], "")

    def test_unreadable_registry_is_not_measured_and_does_not_raise(self):
        with TemporaryDirectory() as td:
            ddir = Path(td)
            (ddir / REGISTRY_FILENAME).write_text("NOT JSON", encoding="utf-8")
            got = read_candidate_registry(ddir)
        self.assertFalse(got["measured"])
        self.assertIn("нечитаем", got["reason"])


# ─── 3. Второй читатель: отчёт исследования ───────────────────────────────────


class TestProtocolResearchAgentCarriesTheHonesty(unittest.TestCase):
    """Честность обязана лежать в АРТЕФАКТЕ, а не только в логе."""

    def test_candidate_set_reports_unmeasured_when_registry_missing(self):
        """Краснеет на origin: функции ``candidate_set`` там нет."""
        with TemporaryDirectory() as td:
            got = protocol_research_agent.candidate_set(Path(td))
        self.assertFalse(got["measured"])
        self.assertEqual(got["items"], [])

    def test_status_artifact_names_the_unmeasured_input(self):
        """Краснеет на origin: ключа ``candidate_registry`` в отчёте не было,
        и ``new_candidates_found: 0`` читался как результат поиска."""
        with TemporaryDirectory() as td:
            ddir = Path(td)
            protocol_research_agent.run_research_cycle(data_dir=ddir)
            doc = json.loads(
                (ddir / protocol_research_agent.RESEARCH_STATUS_FILENAME)
                .read_text(encoding="utf-8"))

        self.assertIn("candidate_registry", doc)
        self.assertFalse(doc["candidate_registry"]["measured"])
        self.assertTrue(doc["candidate_registry"]["reason"])
        # Соседний ноль сохранён — но теперь рядом с ним стоит «не искали».
        self.assertEqual(doc["new_candidates_found"], 0)

    def test_measured_empty_registry_reports_measured_true(self):
        """Обратный контроль: присутствующий пустой реестр — измеренный ноль."""
        with TemporaryDirectory() as td:
            ddir = Path(td)
            (ddir / REGISTRY_FILENAME).write_text(
                json.dumps({"candidates": []}), encoding="utf-8")
            protocol_research_agent.run_research_cycle(data_dir=ddir)
            doc = json.loads(
                (ddir / protocol_research_agent.RESEARCH_STATUS_FILENAME)
                .read_text(encoding="utf-8"))

        self.assertTrue(doc["candidate_registry"]["measured"])
        self.assertEqual(doc["candidate_registry"]["reason"], "")
        self.assertEqual(doc["new_candidates_found"], 0)

    def test_return_value_lets_the_caller_tell_them_apart(self):
        """Краснеет на origin: возвращаемый словарь флага не нёс."""
        with TemporaryDirectory() as td:
            got = protocol_research_agent.run_research_cycle(data_dir=Path(td))
        self.assertIn("candidates_measured", got)
        self.assertFalse(got["candidates_measured"])
        self.assertTrue(got["candidates_reason"])

    def test_compatible_wrapper_still_returns_a_plain_list(self):
        """Обратный контроль: внешняя форма ``fetch_defi_candidates`` не сломана."""
        with TemporaryDirectory() as td:
            ddir = Path(td)
            (ddir / REGISTRY_FILENAME).write_text(
                json.dumps({"candidates": [{"protocol": "a"}, "мусор"]}),
                encoding="utf-8")
            got = protocol_research_agent.fetch_defi_candidates(ddir)
        self.assertEqual(got, [{"protocol": "a"}])


# ─── 4. Третий читатель: стратегическая петля ─────────────────────────────────


class TestStrategicLoopDoesNotDropTheHonesty(unittest.TestCase):
    """Производитель честен с #283 — потребитель выбрасывал это в `len()`."""

    def _run(self, artifact: dict | list) -> dict:
        with TemporaryDirectory() as td:
            ddir = Path(td)
            (ddir / "alpha_candidates.json").write_text(
                json.dumps(artifact), encoding="utf-8")
            return loop_scheduler.run_strategic_loop(
                "2026-08-17", llm_available=True, data_dir=str(ddir))

    def test_unmeasured_scan_yields_no_number_at_all(self):
        """Краснеет на origin: там выходило ``alpha_candidates_count == 0``,
        то есть «искали и не нашли» вместо «никто не искал»."""
        doc = self._run({"candidates": [],
                         "candidates_measured": False,
                         "candidates_reason": "реестр кандидатов не найден"})
        self.assertFalse(doc["alpha_candidates_measured"])
        self.assertIsNone(doc["alpha_candidates_count"])
        self.assertIn("реестр", doc["alpha_candidates_reason"])

    def test_measured_zero_stays_a_zero(self):
        """Обратный контроль — починка не должна быть просто инверсией."""
        doc = self._run({"candidates": [], "candidates_measured": True,
                         "candidates_reason": ""})
        self.assertTrue(doc["alpha_candidates_measured"])
        self.assertEqual(doc["alpha_candidates_count"], 0)

    def test_measured_candidates_are_counted(self):
        """Обратный контроль: живой счёт не потерян."""
        doc = self._run({"candidates": [{"protocol": "a"}, {"protocol": "b"}],
                         "candidates_measured": True})
        self.assertTrue(doc["alpha_candidates_measured"])
        self.assertEqual(doc["alpha_candidates_count"], 2)

    def test_artifact_of_the_wrong_shape_is_unmeasured_not_zero(self):
        doc = self._run(["не тот артефакт"])
        self.assertFalse(doc["alpha_candidates_measured"])
        self.assertIsNone(doc["alpha_candidates_count"])

    def test_pre_283_artifact_without_the_flag_is_read_as_measured(self):
        """Совместимость: старый артефакт без флага НЕ объявляется аварией.

        Иначе один прогон на старом снимке превратил бы всю историю в
        «не измерено» — ложный отказ опаснее пропуска (правило класса).
        """
        doc = self._run({"candidates": [{"protocol": "a"}]})
        self.assertTrue(doc["alpha_candidates_measured"])
        self.assertEqual(doc["alpha_candidates_count"], 1)


# ─── 5. Храповик: ЧЕТВЁРТЫЙ немой читатель не появится молча ──────────────────


class TestNoMuteReaderCanAppear(unittest.TestCase):
    """Сторож в обе стороны (п. 3 карточки).

    Проверяется не исходник ради исходника, а СВОЙСТВО: всякий боевой модуль,
    который трогает реестр кандидатов или поле ``candidates`` артефакта скана,
    обязан считаться с честностью замера. Список известных участников прибит:
    молча расшириться он не может — ни новым немым читателем, ни новым
    исключением.
    """

    #: Кто имеет право трогать реестр, НЕ спрашивая про `measured`, и почему.
    #: Список закреплён намеренно: тихо дописать себя сюда нельзя.
    _EXEMPT = {
        # Писатель. Он реестр СОЗДАЁТ — спрашивать его о «измерено ли» нечего.
        "spa_core/adapter_sdk/discovery.py",
    }

    def _live_modules(self) -> list[Path]:
        out: list[Path] = []
        for base in ("spa_core", "scripts"):
            root = REPO_ROOT / base
            if not root.is_dir():
                continue
            for p in root.rglob("*.py"):
                rel = p.relative_to(REPO_ROOT).as_posix()
                if "/tests/" in rel or rel.startswith("scripts/tests/"):
                    continue
                if p.name.startswith("test_"):
                    continue
                out.append(p)
        return out

    def _touches_the_registry(self, text: str) -> bool:
        return (
            "candidate_registry" in text
            or "alpha_candidates.json" in text
        )

    def _consults_honesty(self, text: str) -> bool:
        return "measured" in text

    def test_the_known_reader_set_is_exactly_what_we_measured(self):
        """Появился новый участник — тест обязан это НАЗВАТЬ, а не промолчать."""
        touching = {
            p.relative_to(REPO_ROOT).as_posix()
            for p in self._live_modules()
            if self._touches_the_registry(p.read_text(encoding="utf-8"))
        }
        expected = {
            "spa_core/adapter_sdk/discovery.py",            # писатель
            "spa_core/adapter_sdk/candidate_registry.py",   # единственное чтение
            "spa_core/agents/alpha_agent.py",               # читатель 1 (#283)
            "spa_core/agents/protocol_research_agent.py",   # читатель 2 (#288)
            "spa_core/scheduler/loop_scheduler.py",         # читатель 3 (#288)
        }
        self.assertEqual(
            touching, expected,
            "изменился круг модулей, трогающих реестр кандидатов: новый участник "
            "обязан либо спрашивать про `measured`, либо быть внесён в _EXEMPT "
            "с причиной — молча стать немым читателем нельзя",
        )

    def test_no_live_module_reads_the_registry_without_asking_measured(self):
        """Храповик: немых читателей — НОЛЬ.

        Краснеет на origin дважды: ``protocol_research_agent`` и
        ``loop_scheduler`` там про ``measured`` не знают вовсе.
        """
        mute: list[str] = []
        for p in self._live_modules():
            rel = p.relative_to(REPO_ROOT).as_posix()
            if rel in self._EXEMPT:
                continue
            text = p.read_text(encoding="utf-8")
            if self._touches_the_registry(text) and not self._consults_honesty(text):
                mute.append(rel)
        self.assertEqual(
            mute, [],
            "эти модули читают реестр кандидатов и не отличают «не измерено» от "
            "«ноль» — ровно та авария, что чинилась #283 и #288",
        )

    def test_the_exemption_list_is_only_the_writer(self):
        """Исключение — привилегия, и она должна оставаться одной штукой."""
        self.assertEqual(self._EXEMPT, {"spa_core/adapter_sdk/discovery.py"})

    def test_every_exempt_path_still_exists(self):
        """Исключение на несуществующий файл — тихо протухшее правило."""
        for rel in self._EXEMPT:
            self.assertTrue((REPO_ROOT / rel).is_file(), rel)

    def test_the_canonical_reader_is_importable_standalone(self):
        """Единственное определение не должно тянуть за собой агентов."""
        src = (REPO_ROOT / "spa_core" / "adapter_sdk" / "candidate_registry.py"
               ).read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
            elif isinstance(node, ast.Import):
                imported.extend(a.name for a in node.names)
        self.assertFalse(
            [m for m in imported if m.startswith("spa_core.agents")],
            "чтение реестра не имеет права зависеть от агентов — иначе "
            "«одно определение» станет циклическим импортом",
        )


if __name__ == "__main__":
    unittest.main()
