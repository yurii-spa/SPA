"""Проводка прибора переписи разборов ленты до ЧИТАТЕЛЯ — ADR-785.

Карточка ``inbox-u-pribora-perepisi-razborov-lenty-net-ch``. Предмет батареи — не
«работает ли прибор» (это батарея ``test_ledger_parse_census.py``, 154 passed), а
**доходит ли его число до кого-нибудь, кроме набравшего команду руками**. Пять ADR
(777, 779, 782, 783, 784) и четыре цикла работы прожили без читателя, и это было
измерено: прибор не писал ВООБЩЕ ничего — печатал отчёт в терминал.

Каждый тест ниже — положительный контроль на ОДНО порванное звено, и он НАЗЫВАЕТ
звено. Проверка, никогда не видевшая настоящей поломки, — украшение
(``.claude/rules/deployment.md``, «Проверка сторожа сторожей»).

**Почему звенья рвутся заглушкой, а не правкой дерева.** Настоящий контур стоит
**24 с** (четыре замера с настоящими видами), и десять контролей на нём превратили бы
батарею в предписанный прогон. Поэтому корень и оба модуля приходят ВХОДОМ
(:func:`card_acceptance.ledger_census_reader_links`), контроли подают сцену, а ОДИН
тест зовёт настоящий контур целиком — он и не даёт сцене разойтись с предметом.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import ledger_parse_census as lpc

_ROOT = Path(__file__).resolve().parents[2]
# FROZEN-DATE-OK: injected-clock — обе отметки синтезируются от этого якоря и
#: передаются `now=` в `measurement_due`/`run`; стенных часов ни один тест не касается.
_ANCHOR = dt.datetime(2026, 10, 22, 12, 0, tzinfo=dt.timezone.utc)


class _FakeCensus:
    """Исправный прибор-сцена: пишет артефакт, держит такт, находку даёт по бюджету.

    Нужен затем, чтобы порванным было РОВНО ОДНО звено. Исправная сцена, у которой
    сломали одну деталь, называет виновника; сломанная сцена с настоящим прибором
    называет что попало.
    """

    F_MARGIN_SHORT = lpc.F_MARGIN_SHORT
    #: Объявление населения берётся у НАСТОЯЩЕГО прибора: путь ленты проба читает
    #: из него, а не из литерала, и сцена обязана отвечать на тот же вопрос, что
    #: боевой модуль, иначе контроли проверяли бы форму сцены.
    LEDGERS = lpc.LEDGERS

    def __init__(self, *, writes: bool = True, always_margin: bool = False,
                 never_margin: bool = False, fake_freshness: bool = False,
                 with_conditions: bool = True, with_stamp: bool = True) -> None:
        self.writes = writes
        self.always_margin = always_margin
        self.never_margin = never_margin
        self.fake_freshness = fake_freshness
        self.with_conditions = with_conditions
        self.with_stamp = with_stamp
        self.calls = 0

    def run(self, root=None, *, data_dir=None, dest=None, if_due=True,
            budget_s=1.0, **kw) -> dict:
        self.calls += 1
        target = Path(dest)
        #: Такт держится ФАЙЛОМ, как у настоящего прибора: иначе контроль «такт
        #: подделал свежесть» проверял бы сцену, а не предмет.
        if if_due and target.is_file() and not self.fake_freshness:
            return {"measured": False, "reason": "внутри такта (сцена)",
                    "artifact": str(target)}
        breached = budget_s < 1e-6
        findings = []
        if (breached and not self.never_margin) or self.always_margin:
            findings.append({"kind": self.F_MARGIN_SHORT, "id": "research_factory",
                             "text": "сцена"})
        doc: dict = {"status": "FINDINGS" if findings else "CLEAN",
                     "findings": findings, "rows": [], "population": {},
                     "unmeasured": {}, "advisory": True}
        if self.with_stamp:
            #: Отметка берётся от ЯКОРЯ и сдвигается на номер зова: подделка свежести
            #: обязана быть ВИДНА как смена отметки, а стенные часы в тесте дали бы
            #: разные значения от длительности прогона (ADR-348).
            doc["generated_at"] = (_ANCHOR + dt.timedelta(seconds=self.calls)).isoformat()
        if self.with_conditions:
            doc["conditions"] = {"load_average": [1.0, 1.0, 1.0], "elapsed_s": 0.5,
                                 "cpu_count": 8, "load_unmeasured": None}
        if self.writes:
            target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return {"measured": True, "doc": doc, "artifact": str(target)}


class _FakeBridge:
    def __init__(self, *, carries: bool = True) -> None:
        self.CENSUS_STAGE = ("ledger_parse_census",) if carries else ("someone_else",)


def _stand_root(tmp: Path) -> Path:
    """Одноразовый корень с РЕАЛЬНЫМИ конституцией и шагом 0-офис (их и будем рвать)."""
    root = tmp / "tree"
    (root / "architecture").mkdir(parents=True)
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(_ROOT / "architecture" / "manifest.json",
                 root / "architecture" / "manifest.json")
    shutil.copy2(_ROOT / "scripts" / "consume_office_reports.py",
                 root / "scripts" / "consume_office_reports.py")
    return root


def _links(root: Path, **kw) -> list[str]:
    return ca.ledger_census_reader_links(
        root, bridge=kw.pop("bridge", _FakeBridge()),
        census=kw.pop("census", _FakeCensus()), stand_rows=12)


class LedgerCensusReaderWiring(unittest.TestCase):
    """Каждое звено рвётся отдельно и НАЗЫВАЕТСЯ."""

    def test_whole_contour_is_intact_on_the_real_tree(self):
        """Настоящий контур целиком — единственный дорогой тест батареи (≈24 с).

        Он и есть то, что не даёт сцене разойтись с предметом: остальные контроли
        подают заглушку, и без этого теста они доказывали бы исправность сцены.
        """
        self.assertEqual(ca.ledger_census_reader_links(), [],
                         "настоящая проводка порвана — см. названные звенья")
        status, why = ca.PROBES["ledger_census_artifact_reaches_the_cycle"](None)
        self.assertEqual(status, ca.SATISFIED, why)

    def test_scene_itself_is_intact(self):
        """Контроль шума: на целой сцене звеньев не рвётся ни одного.

        Без него любой тест ниже был бы зелёным по построению — он краснел бы от
        поломки сцены, а не от поломки звена.
        """
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(_links(_stand_root(Path(t))), [])

    # --- звено 1: срок годности в конституции ---

    def test_link_1_red_when_the_artifact_is_not_declared(self):
        with tempfile.TemporaryDirectory() as t:
            root = _stand_root(Path(t))
            man = root / "architecture" / "manifest.json"
            doc = json.loads(man.read_text(encoding="utf-8"))
            doc["artifacts"] = [a for a in doc["artifacts"]
                                if a.get("path") != ca._LPC_ARTIFACT]
            man.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            broken = _links(root)
        self.assertTrue(any("звено 1" in b for b in broken), broken)
        self.assertTrue(any("срок годности не объявлен" in b for b in broken), broken)

    def test_link_1_red_when_the_declaration_carries_no_slo(self):
        """Объявление БЕЗ срока сроком не является — возраст по-прежнему нечем судить."""
        with tempfile.TemporaryDirectory() as t:
            root = _stand_root(Path(t))
            man = root / "architecture" / "manifest.json"
            doc = json.loads(man.read_text(encoding="utf-8"))
            for a in doc["artifacts"]:
                if a.get("path") == ca._LPC_ARTIFACT:
                    a.pop("slo_hours", None)
            man.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            broken = _links(root)
        self.assertTrue(any("slo_hours нет" in b for b in broken), broken)

    # --- звено 2: три реестра шага 0-офис, и каждый рвётся САМ ---

    def _office_without(self, root: Path, anchor: str) -> list[str]:
        office = root / "scripts" / "consume_office_reports.py"
        src = office.read_text(encoding="utf-8")
        self.assertIn(anchor, src, "якорь реестра не найден — сцена не обеспечена")
        office.write_text(src.replace(anchor, "# вырезано контролем", 1), encoding="utf-8")
        return _links(root)

    def test_link_2a_red_without_the_form_registry(self):
        with tempfile.TemporaryDirectory() as t:
            broken = self._office_without(_stand_root(Path(t)),
                                          ca._LPC_OFFICE_ANCHORS["звено 2а"][0])
        self.assertTrue(any("звено 2а" in b for b in broken), broken)

    def test_link_2b_red_without_the_producer_registry(self):
        with tempfile.TemporaryDirectory() as t:
            broken = self._office_without(_stand_root(Path(t)),
                                          ca._LPC_OFFICE_ANCHORS["звено 2б"][0])
        self.assertTrue(any("звено 2б" in b for b in broken), broken)

    def test_link_2c_red_without_the_rendering_branch(self):
        """Без ветки отрисовки файл читается ВХОЛОСТУЮ — открыт, а чисел в контексте нет."""
        with tempfile.TemporaryDirectory() as t:
            broken = self._office_without(_stand_root(Path(t)),
                                          ca._LPC_OFFICE_ANCHORS["звено 2в"][0])
        self.assertTrue(any("звено 2в" in b for b in broken), broken)
        self.assertTrue(any("ВХОЛОСТУЮ" in b for b in broken), broken)

    def test_the_name_in_a_comment_does_not_satisfy_any_registry(self):
        """ADR-333: проба НЕ проходит подстрокой.

        Имя артефакта, оставленное в комментарии вместо объявления, обязано оставить
        все три звена порванными — иначе «объявлено» означало бы «упомянуто».
        """
        with tempfile.TemporaryDirectory() as t:
            root = _stand_root(Path(t))
            office = root / "scripts" / "consume_office_reports.py"
            src = office.read_text(encoding="utf-8")
            for anchor, _ in ca._LPC_OFFICE_ANCHORS.values():
                src = src.replace(anchor, "# ledger_parse_census.json упомянут", 1)
            office.write_text(src, encoding="utf-8")
            broken = _links(root)
        for link in ("звено 2а", "звено 2б", "звено 2в"):
            self.assertTrue(any(link in b for b in broken), (link, broken))

    # --- звено 3: ступень моста ---

    def test_link_3_red_when_the_bridge_stage_drops_the_name(self):
        with tempfile.TemporaryDirectory() as t:
            broken = _links(_stand_root(Path(t)), bridge=_FakeBridge(carries=False))
        self.assertTrue(any("звено 3" in b for b in broken), broken)
        self.assertTrue(any("CENSUS_STAGE" in b for b in broken), broken)

    # --- звено 4: производящий зов ПИШЕТ ---

    def test_link_4_red_when_the_producing_call_writes_nothing(self):
        """Ровно то состояние, в котором прибор прожил пять ADR: считает и не пишет."""
        with tempfile.TemporaryDirectory() as t:
            broken = _links(_stand_root(Path(t)), census=_FakeCensus(writes=False))
        self.assertTrue(any("звено 4" in b for b in broken), broken)
        self.assertTrue(any("НЕ НАПИСАЛ артефакт" in b for b in broken), broken)

    def test_link_4_red_without_a_stamp(self):
        """Артефакт без ``generated_at`` — возраст наблюдения прочитать нечем."""
        with tempfile.TemporaryDirectory() as t:
            broken = _links(_stand_root(Path(t)), census=_FakeCensus(with_stamp=False))
        self.assertTrue(any("generated_at" in b for b in broken), broken)

    def test_link_4_red_without_measurement_conditions(self):
        """Условия замера — несущая часть артефакта, а не украшение (ADR-784).

        ``parse_s`` есть ВРЕМЯ: 15 суток запаса на спокойной машине против 0 под
        нагрузкой при темпе, не изменившемся на 0,3 %. Без условий ступень родила бы
        находку от чужого прогона рядом.
        """
        with tempfile.TemporaryDirectory() as t:
            broken = _links(_stand_root(Path(t)),
                            census=_FakeCensus(with_conditions=False))
        self.assertTrue(any("без условий замера" in b for b in broken), broken)

    # --- звено 5: находка ДИФФЕРЕНЦИАЛЬНА ---

    def test_link_5_red_when_the_breached_budget_births_nothing(self):
        with tempfile.TemporaryDirectory() as t:
            broken = _links(_stand_root(Path(t)), census=_FakeCensus(never_margin=True))
        self.assertTrue(any("звено 5" in b for b in broken), broken)
        self.assertTrue(any("НЕ родил находку" in b for b in broken), broken)

    def test_link_5_red_when_the_finding_never_goes_silent(self):
        """Находка на ЛЮБОМ входе — несмолкаемость, а не чувствительность (ADR-782).

        Это обратное направление того же звена, и без него «находка есть» означало бы
        «прибор всегда что-то печатает».
        """
        with tempfile.TemporaryDirectory() as t:
            broken = _links(_stand_root(Path(t)), census=_FakeCensus(always_margin=True))
        self.assertTrue(any("несмолкаемость" in b for b in broken), broken)

    # --- такт не подделывает свежесть ---

    def test_tact_red_when_freshness_is_faked(self):
        """Отметка, обновлённая БЕЗ замера, ломает того сторожа, ради которого заведена."""
        with tempfile.TemporaryDirectory() as t:
            broken = _links(_stand_root(Path(t)), census=_FakeCensus(fake_freshness=True))
        self.assertTrue(any("такт" in b for b in broken), broken)
        self.assertTrue(any("выдан за возраст наблюдения" in b for b in broken), broken)


class ArtifactContract(unittest.TestCase):
    """Сам артефакт: три исхода, такт и условия замера — на настоящем приборе."""

    def test_status_derives_from_the_single_verdict_rule(self):
        """Ярлык — ПРОИЗВОДНОЕ от :func:`exit_code`, а не второе суждение.

        Вторая копия правила вердикта разошлась бы с первой молча — ровно класс,
        который сам прибор ловит у других (ADR-782, «одно имя — один объект»).
        """
        clean = {"population": {"code_files_undeclared": [], "code_files_missing": [],
                                "ledgers_declared": 1, "declared": 1,
                                "code_files_in_tree": []},
                 "findings": [], "unmeasured": {}, "rows": []}
        self.assertEqual(lpc.status(clean), lpc.STATUS_CLEAN)
        finding = dict(clean, findings=[{"kind": "x", "id": "y", "text": "z"}])
        self.assertEqual(lpc.status(finding), lpc.STATUS_FINDINGS)
        blind = dict(clean, unmeasured={"research_factory": "вид не разрешён"})
        self.assertEqual(lpc.status(blind), lpc.STATUS_UNMEASURED)
        #: НЕ ИЗМЕРЕНО сильнее находки — инв. #17. Член, о котором мы не знаем ничего,
        #: не вправе докладываться кодом «измерено, вот что нашли».
        both = dict(blind, findings=[{"kind": "x", "id": "y", "text": "z"}])
        self.assertEqual(lpc.status(both), lpc.STATUS_UNMEASURED)
        for code, label in lpc._STATUS_BY_CODE.items():
            self.assertIn(label, (lpc.STATUS_CLEAN, lpc.STATUS_FINDINGS,
                                  lpc.STATUS_UNMEASURED), code)

    def test_measurement_due_keeps_three_outcomes_apart(self):
        """Артефакта нет · отметка не прочитана · отметка свежая — три разных ответа."""
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "a.json"
            due, why = lpc.measurement_due(out, now=_ANCHOR)
            self.assertTrue(due)
            self.assertIn("артефакта нет", why)

            out.write_text("{не json", encoding="utf-8")
            due, why = lpc.measurement_due(out, now=_ANCHOR)
            self.assertTrue(due, "нечитаемая отметка НЕ ИМЕЕТ ПРАВА означать «мерили "
                                 "недавно» — это подстановка молчания на место наблюдения")
            self.assertIn("не прочитана", why)

            out.write_text(json.dumps({"generated_at": _ANCHOR.isoformat()}),
                           encoding="utf-8")
            due, why = lpc.measurement_due(out, now=_ANCHOR + dt.timedelta(days=1))
            self.assertFalse(due)
            self.assertIn("из 7", why)
            due, _ = lpc.measurement_due(out, now=_ANCHOR + dt.timedelta(days=8))
            self.assertTrue(due)

            #: Отметка без пояса — тоже «мерим»: сравнивать её с момента в UTC значило
            #: бы судить о возрасте по часам неизвестного места.
            out.write_text(json.dumps({"generated_at": "2026-10-22T12:00:00"}),
                           encoding="utf-8")
            due, why = lpc.measurement_due(out, now=_ANCHOR)
            self.assertTrue(due)
            self.assertIn("без пояса", why)

    def test_inside_the_tact_nothing_is_written_and_no_verdict_is_invented(self):
        with tempfile.TemporaryDirectory() as t:
            data = Path(t) / "data"
            data.mkdir()
            dest = data / lpc.ARTIFACT
            dest.write_text(json.dumps({"generated_at": _ANCHOR.isoformat(),
                                        "status": "CLEAN"}), encoding="utf-8")
            before = dest.read_bytes()
            res = lpc.run(root=_ROOT, data_dir=data,
                          now=_ANCHOR + dt.timedelta(hours=1))
        self.assertFalse(res["measured"])
        self.assertNotIn("doc", res, "внутри такта вердикта нет — его там взять негде")
        self.assertIn("reason", res)
        self.assertEqual(dest.read_bytes() if dest.exists() else before, before,
                         "артефакт переписан внутри такта")

    def test_load_label_keeps_a_measured_idle_machine_apart_from_no_observation(self):
        """Простаивающая машина и НЕИЗМЕРЕННАЯ загрузка — разные ответы.

        ``[0.0, 0.0, 0.0]`` есть ЗАМЕР, и falsy-проверка (``or``) не отличила бы его от
        отсутствия наблюдения. Ровно этот сигнал (``or_falsy``) и поймал храповик
        ``test_absent_observation_ratchet``, когда прибор стал писателем артефакта.
        """
        idle = lpc._load_label({"load_average": [0.0, 0.0, 0.0]})
        self.assertIn("0.0", idle)
        self.assertNotIn("НЕ ИЗМЕРЕНА", idle, "замер простоя выдан за отсутствие замера")

        blind = lpc._load_label({"load_average": None,
                                 "load_unmeasured": "getloadavg недоступен"})
        self.assertIn("НЕ ИЗМЕРЕНА", blind)
        self.assertIn("getloadavg", blind, "третий исход обязан НАЗВАТЬ причину")
        self.assertIn("НЕ ИЗМЕРЕНА", lpc._load_label({}))

    def test_min_rate_days_label_does_not_pass_a_module_default_off_as_measured(self):
        """Блока ряда в замере нет ⇒ так и сказано, а не напечатана константа модуля."""
        absent = lpc._min_rate_days_label({})
        self.assertIn("НЕ ОБЪЯВЛЕН", absent)
        declared = lpc._min_rate_days_label({"rate": {"min_rate_days": 5}})
        self.assertIn("5", declared)
        self.assertNotIn("НЕ ОБЪЯВЛЕН", declared)
        #: Блок есть, а поля в нём нет — это умолчание МОДУЛЯ, и оно помечено словами,
        #: иначе решение, которого замер не делал, читалось бы как его часть.
        fallback = lpc._min_rate_days_label({"rate": {}})
        self.assertIn("по умолчанию модуля", fallback)

    def test_report_names_a_missing_rate_block_instead_of_dropping_it(self):
        """Отсутствие ряда НАЗВАНО в отчёте, а не молча исчезло из него."""
        doc = {"data_dir": "/x", "budget_s": 1.0, "min_growth_factor": 4.0,
               "rows": [], "findings": [], "unmeasured": {},
               "population": {"code_files_undeclared": [], "code_files_missing": [],
                              "ledgers_declared": 0, "declared": 0,
                              "code_files_in_tree": []}}
        text = "\n".join(lpc.format_report(doc))
        self.assertIn("ряда суток в отчёте нет вовсе", text)
        self.assertIn("НЕ ИЗМЕРЕНО", text)

    def test_the_artifact_carries_the_conditions_of_its_own_measurement(self):
        """Загрузка машины и длительность — в артефакте, и третий исход у них СВОЙ."""
        cond = lpc.measurement_conditions()
        self.assertIn("load_average", cond)
        self.assertIn("cpu_count", cond)
        if cond["load_average"] is None:
            self.assertTrue(cond["load_unmeasured"],
                            "загрузка не прочитана ⇒ обязана быть НАЗВАННАЯ причина, "
                            "а не ноль: ноль означал бы «машина простаивала»")
        else:
            self.assertIsNone(cond["load_unmeasured"])
            self.assertEqual(len(cond["load_average"]), 3)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
