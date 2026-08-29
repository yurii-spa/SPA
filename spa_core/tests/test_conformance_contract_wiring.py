"""B7 — три сверки контрактов, подключённые к живому сторожу (ADR-154/158).

Сверки `artifact_contract` / `contract_manifest_parity` / `freshness_threshold_parity`
были написаны 28.08 и месяц НИКТО не вызывал — дословно та патология, ради которой
писался ADR-154 («контракты раньше оркестрации»). Здесь закреплено подключение.

Каждый контроль воспроизводит НАСТОЯЩУЮ находку первого живого прогона 29.08:

  contradiction     `com.spa.daily_cycle` объявляет пять артефактов, а пишет ещё четыре;
  different_artifact тот же агент: монитор сторожит `paper_trading_status.json`,
                     манифест — совсем другие пять файлов;
  threshold_mismatch `com.spa.bts-feed`: манифест разрешает 168ч (решение двух ролей
                     «исследовательский контур, потребителя нет»), монитор бьёт через 1ч.

И обратная сторона, которая важнее находок: мягкие исходы (`unmeasured` — 31 агент,
`undeclared` — 2, `declared_none` — 6, `not_compared`) НЕ становятся тревогой и НЕ
попадают в `unchecked`. Иначе сторож стал бы жёлтым навсегда (unchecked ⇒ exit 1),
разница между «измерено и чисто» и «не смотрели» стёрлась бы, и его перестали бы
читать. Мягкое место — блок `contracts` отчёта.

Часы инъектируются (now=) — литеральных дат нет (deployment.md: время — вход).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest

from spa_core.monitoring import architecture_conformance as ac

NOW = dt.datetime(2030, 1, 15, 12, 0, tzinfo=dt.timezone.utc)  # FROZEN-DATE-OK: injected-clock — часы инъектируются парой с отметками

EMPTY = {"schema_version": 1, "agents": [], "artifacts": [], "designed_architectures": []}


def run(**kw):
    """Пустая конституция + пустой флот: в отчёте видно ТОЛЬКО B7."""
    return ac.run_checks(EMPTY, set(), lambda p: None, {}, NOW, drift_measured=True, **kw)


def b7(report):
    return [f for f in report["findings"] if f["check"] == "B7"]


def ok_audit(rows=()):
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return {"total": len(rows), "counts": counts, "rows": list(rows)}


SILENT = {"contract_audit": ok_audit(), "manifest_parity": {"compared": 0, "findings": [],
                                                            "verdict": "not_compared"},
          "freshness_parity": {"compared": 0, "findings": [], "verdict": "not_compared"}}


class Contradiction(unittest.TestCase):
    def test_contradiction_is_a_finding(self):
        """Настоящая находка 29.08: daily_cycle пишет мимо собственного объявления."""
        row = {"label": "com.spa.daily_cycle", "module": "m", "verdict": "contradiction",
               "declared": ["data/current_positions.json"],
               "undeclared_writes": ["emergency_status.json", "market_regime.json"]}
        r = run(**{**SILENT, "contract_audit": ok_audit([row])})
        f = b7(r)
        self.assertEqual(len(f), 1, f)
        self.assertEqual(f[0]["key"], "B7:contradiction:com.spa.daily_cycle")
        self.assertEqual(f[0]["class"], "strong")   # не стареет: расхождение домов не рассасывается
        self.assertIn("emergency_status.json", f[0]["message"])

    def test_soft_verdicts_never_alarm(self):
        """Обратная сторона: 31 unmeasured + 2 undeclared обязаны молчать.

        Это не смягчение сторожа, а его условие жизни: мягкие исходы — состояние
        РАБОТЫ (объявления пишутся), и тревогой они делают сторожа нечитаемым.
        """
        rows = [{"label": f"com.spa.a{i}", "module": "m", "verdict": v, "declared": []}
                for i, v in enumerate(["unmeasured", "undeclared", "declared_none",
                                       "confirmed"])]
        r = run(**{**SILENT, "contract_audit": ok_audit(rows)})
        self.assertEqual(b7(r), [])
        self.assertEqual(r["unchecked"], [])
        self.assertEqual(r["contracts"]["contract"]["counts"],
                         {"unmeasured": 1, "undeclared": 1, "declared_none": 1, "confirmed": 1})


class ManifestParity(unittest.TestCase):
    def test_divergence_is_a_finding(self):
        p = {"compared": 60, "verdict": "declared_not_in_manifest",
             "findings": [{"label": "com.spa.x", "verdict": "declared_not_in_manifest",
                           "declared_only": ["data/x.json"], "note": "без SLO"}]}
        r = run(**{**SILENT, "manifest_parity": p})
        f = b7(r)
        self.assertEqual([x["key"] for x in f], ["B7:manifest_parity:com.spa.x"])
        self.assertIn("data/x.json", f[0]["message"])

    def test_agrees_is_silent(self):
        r = run(**{**SILENT, "manifest_parity": {"compared": 60, "findings": [],
                                                 "verdict": "agrees"}})
        self.assertEqual(b7(r), [])
        self.assertEqual(r["contracts"]["manifest_parity"]["compared"], 60)


class FreshnessParity(unittest.TestCase):
    def test_threshold_mismatch_is_a_finding(self):
        """Настоящая находка 29.08: манифест 168ч (решение двух ролей) против 1ч монитора."""
        p = {"compared": 14, "verdict": "threshold_mismatch",
             "findings": [{"label": "com.spa.bts-feed", "verdict": "threshold_mismatch",
                           "artifact": "data/perp_funding_rates.json",
                           "manifest_hours": 168.0, "monitor_hours": 1.0}]}
        f = b7(run(**{**SILENT, "freshness_parity": p}))
        self.assertEqual([x["key"] for x in f], ["B7:freshness_parity:com.spa.bts-feed"])
        self.assertIn("168.0", f[0]["message"])
        self.assertIn("1.0", f[0]["message"])

    def test_different_artifact_is_a_finding(self):
        p = {"compared": 14, "verdict": "different_artifact",
             "findings": [{"label": "com.spa.daily_cycle", "verdict": "different_artifact",
                           "monitor_artifact": "data/paper_trading_status.json",
                           "manifest_artifacts": ["data/current_positions.json"]}]}
        f = b7(run(**{**SILENT, "freshness_parity": p}))
        self.assertEqual(len(f), 1)
        self.assertIn("paper_trading_status.json", f[0]["message"])
        self.assertIn("никто не сторожит", f[0]["message"])


class GuardDidNotRun(unittest.TestCase):
    FAILED = {"contract_audit": None, "manifest_parity": None, "freshness_parity": None}

    def test_absent_audit_is_unchecked_not_ok(self):
        """Сверка не выполнилась ⇒ честный UNCHECKED, а не тишина (инвариант 2)."""
        r = run(**self.FAILED)
        self.assertEqual(b7(r), [])
        self.assertEqual({u["check"] for u in r["unchecked"]},
                         {"B7_contract", "B7_manifest_parity", "B7_freshness_parity"})
        self.assertEqual(r["overall"], "UNCHECKED")
        self.assertNotEqual(r["exit_code"], 0)

    def test_all_three_measured_and_clean_is_ok(self):
        """И обратно: измерено и чисто ⇒ OK. Без этого UNCHECKED был бы неотличим."""
        r = run(**{**SILENT, "manifest_parity": {"compared": 60, "findings": [],
                                                 "verdict": "agrees"},
                   "freshness_parity": {"compared": 14, "findings": [], "verdict": "agrees"}})
        self.assertEqual(r["overall"], "OK")


    def test_not_requested_is_not_the_same_as_failed(self):
        """Третий исход. «Не спрашивали» обязано молчать, «спросили и не смогли» — краснеть.

        Без различия один новый аргумент судил бы вызовы, которые о нём не знают:
        шесть тестов про B1/B3 покраснели бы на ИСПРАВНОМ дереве. Но и обратная
        опасность названа: молчание НЕ должно наступать на живом пути — там
        значение передаётся всегда (см. WiredIntoMain).
        """
        self.assertEqual(run()["unchecked"], [])            # не запрашивали
        self.assertEqual(run()["overall"], "OK")
        self.assertEqual(run(**self.FAILED)["overall"], "UNCHECKED")   # спросили, не смогли


class LeavingTheCensusIsAnEvent(unittest.TestCase):
    """Настоящее событие 29.08, и оно НЕ дало ни одной находки.

    В `run_daily_paper_cycle.sh` добавили третий и четвёртый шаги. Целей стало
    четыре, вывод точки входа честно ОТКАЗАЛ — и `com.spa.daily_cycle`, самый
    важный агент системы, исчез из переписи контрактов вместе со своим
    противоречием. Счётчик стал 71 вместо 72, и всё. Отказ был верным; молчание
    об убыли — нет. Родственное: «не измерено» ≠ «никто».
    """

    AGENT = {"label": "com.spa.daily_cycle", "intent": "active", "reboot_safe": True,
             "plist_source": "launch_agents", "schedule": "calendar:08:00",
             "program": "x.sh", "layer": "product", "role": "monitoring",
             "produces": [], "consumes": [], "consumer_required": False,
             "governed_by": [], "curation": "partial", "notes": ""}

    def _run(self, rows, prev, agent=None):
        man = {"schema_version": 1, "agents": [agent or self.AGENT],
               "artifacts": [], "designed_architectures": []}
        return ac.run_checks(man, {"com.spa.daily_cycle"}, lambda p: NOW, {}, NOW,
                             drift_measured=True, contract_audit=ok_audit(rows),
                             manifest_parity=SILENT["manifest_parity"],
                             freshness_parity=SILENT["freshness_parity"],
                             prev_contract_labels=prev)

    def test_agent_that_left_the_census_is_a_finding(self):
        r = self._run([], ["com.spa.daily_cycle"])
        self.assertEqual([f["key"] for f in b7(r)], ["B7:left_census:com.spa.daily_cycle"])
        self.assertIn("AGENT_MODULE", b7(r)[0]["message"])

    def test_agent_still_measured_is_silent(self):
        row = {"label": "com.spa.daily_cycle", "module": "m", "verdict": "confirmed",
               "declared": ["data/x.json"]}
        self.assertEqual(b7(self._run([row], ["com.spa.daily_cycle"])), [])

    def test_retired_agent_leaving_is_not_this_finding(self):
        """Агента вывели из строя — это вопрос B1, а не «перепись потеряла его»."""
        retired = dict(self.AGENT, intent="retired")
        self.assertEqual(b7(self._run([], ["com.spa.daily_cycle"], agent=retired)), [])

    def test_report_carries_the_population_for_the_NEXT_run(self):
        """КРУГ, а не деталь: сторож сравнивает с прошлым отчётом — значит отчёт
        обязан это прошлое нести. Мутация «не писать labels» оставляла набор
        зелёным, а сторожа — навсегда немым: сравнивать было бы не с чем."""
        row = {"label": "com.spa.daily_cycle", "module": "m", "verdict": "confirmed",
               "declared": ["data/x.json"]}
        r = self._run([row], [])
        self.assertEqual(r["contracts"]["contract"]["labels"], ["com.spa.daily_cycle"])
        d = tempfile.mkdtemp()
        rep = os.path.join(d, "r.json")
        json.dump(r, open(rep, "w"))
        self.assertEqual(ac._prev_contract_labels(rep), ["com.spa.daily_cycle"])

    def test_missing_previous_report_reads_as_empty_not_crash(self):
        self.assertEqual(ac._prev_contract_labels("/nope/never/r.json"), [])

    def test_first_run_without_history_is_silent(self):
        """Прошлого отчёта нет ⇒ убыли не бывает; пустая история не авария."""
        self.assertEqual(b7(self._run([], [])), [])


class TwoHousesOfMyOwnWiring(unittest.TestCase):
    """Сторож сравнивает вердикты ЛИТЕРАЛАМИ — значит литералы обязаны быть связаны.

    Литералы выбраны сознательно: сторож не должен падать из-за импорта того, что
    он проверяет. Цена приёма — ровно это расхождение домов, и оно закрывается тестом.
    """

    def test_literals_match_guard_constants(self):
        from spa_core.monitoring import artifact_contract as acon
        from spa_core.monitoring import freshness_threshold_parity as ftp
        src = open(ac.__file__, encoding="utf-8").read()
        for literal in (acon.CONTRADICTION, ftp.DIFFERENT_ARTIFACT):
            self.assertIn(f'"{literal}"', src,
                          f"вердикт {literal!r} переименован в сверке, а сторож ищет старый")


class GatherIsFailSafe(unittest.TestCase):
    def test_one_broken_guard_blinds_only_itself(self):
        """Сломанная сверка обязана ослепить себя, а не уронить сторожа."""
        from spa_core.monitoring import artifact_contract as acon
        real = acon.audit_fleet
        acon.audit_fleet = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("бум"))
        try:
            got = ac.gather_contracts()
        finally:
            acon.audit_fleet = real
        self.assertIsNone(got["contract"])
        self.assertIn("бум", got["errors"]["contract"])
        self.assertIsNotNone(got["manifest_parity"], "соседняя сверка ослепла заодно")


class WiredIntoMain(unittest.TestCase):
    """Мутировать ПРОВОДКУ, а не детали: run_checks можно оставить исправным и
    просто перестать передавать ему собранное — тесты выше остались бы зелёными."""

    def test_main_passes_contracts_into_the_report(self):
        row = {"label": "com.spa.zzz", "module": "m", "verdict": "contradiction",
               "declared": ["data/a.json"], "undeclared_writes": ["b.json"]}
        d = tempfile.mkdtemp()
        man, rep = os.path.join(d, "m.json"), os.path.join(d, "r.json")
        json.dump(EMPTY, open(man, "w"))
        saved = {k: getattr(ac, k) for k in
                 ("MANIFEST_PATH", "gather_fleet", "origin_manifest",
                  "_manifest_drift_problems", "gather_contracts", "subject_inputs")}
        ac.MANIFEST_PATH = man
        ac.gather_fleet = lambda: set()
        ac.origin_manifest = lambda *a, **k: (None, "тест")
        ac._manifest_drift_problems = lambda *a, **k: None
        ac.subject_inputs = lambda *a, **k: []
        ac.gather_contracts = lambda: {
            "contract": ok_audit([row]), "errors": {},
            "manifest_parity": {"compared": 1, "findings": [], "verdict": "agrees"},
            "freshness_parity": {"compared": 1, "findings": [], "verdict": "agrees"}}
        try:
            ac.main(["--run", "--exit-zero", "--report", rep])
        finally:
            for k, v in saved.items():
                setattr(ac, k, v)
        report = json.load(open(rep))
        self.assertIn("B7:contradiction:com.spa.zzz", {f["key"] for f in report["findings"]})
        self.assertEqual(report["contracts"]["manifest_parity"]["verdict"], "agrees")


if __name__ == "__main__":
    unittest.main()
