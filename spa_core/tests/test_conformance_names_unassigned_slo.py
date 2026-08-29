"""B2: «срок годности не назначен» обязано БЫТЬ СКАЗАНО, а не промолчано (цикл #426).

Positive control — замер этого цикла на живом `run_checks`, до правки:

    manifest: один активный артефакт `data/no_slo.json`, продюсер объявлен,
    потребитель объявлен, `slo_hours` ОТСУТСТВУЕТ; файл на диске не менялся
    40 суток. Вывод сторожа:

        B2 findings          — про этот путь НЕТ НИ ОДНОЙ
        unchecked            — про этот путь НЕТ НИ ОДНОЙ
        slo_budgets          — {'path': 'data/no_slo.json', 'declared_h': None,
                                'budget_h': None, ...}

    То есть единственный след — ОТСУТСТВИЕ значения в служебной строке, которую
    не читает ни один потребитель отчёта. Механика: `declared = float(
    art.get("slo_hours") or 0)` превращает пустое поле в ноль, а ниже стоит
    `if budget and age_h > budget` — при нулевом бюджете условие не срабатывает
    НИКОГДА. Читатель отчёта видит `OK`/`warn=0` и заключает «со свежестью
    порядок», тогда как верное утверждение — «свежесть НЕ ИЗМЕРЕНА».

Почему это не экзотика, а штатный покой системы. По ADR-158 срок годности
назначают ДВЕ роли по согласованию, и fail-CLOSED исход «не сошлись» — ровно
пустое поле: «агент остаётся в списке „нужен автор“, а не получает выдуманное
число». Состояние, объявленное владельцем честной точкой покоя, сторож читал
как чистый результат. Сегодня в манифесте 28 артефактов из 28 со сроком, то
есть карман пуст — и именно поэтому он немой: он открывается ровно в тот
момент, когда по ADR-158 объявят первый артефакт без согласованного срока
(в очереди их шесть: `pilot_requests.jsonl`, `interest.jsonl`,
`site_analytics.jsonl`, `investors.json`, `monitoring/signals/latest.json`,
`kill_switch_active.json`).

Обратная сторона проверяется отдельно и намеренно (ADR-164 п.2): пробел НЕ
эскалируется. Состояние работы, загнанное в `unchecked`, делает сторожа вечно
жёлтым, и разница между «измерено и чисто» и «мы туда не смотрели» исчезает.
Здесь исход НАЗЫВАЕТСЯ и СЧИТАЕТСЯ, а вердикт не трогает — и на это есть свой
контроль, чтобы починку нельзя было «улучшить» до тревоги.

Часы инъектируются (now=), литеральных дат нет (deployment.md: время — вход).
"""
from __future__ import annotations

import datetime as dt
import unittest

from spa_core.monitoring import architecture_conformance as ac

# FROZEN-DATE-OK: injected-clock — часы инъектируются парой с отметками
NOW = dt.datetime(2030, 1, 15, 12, 0, tzinfo=dt.timezone.utc)

STALE_H = 24 * 40  # ровно возраст из замера: сорок суток молчания
UNASSIGNED = "data/no_slo.json"
ASSIGNED = "data/with_slo.json"
PRODUCER = "com.spa.probe"


def agent(label=PRODUCER, schedule="interval:21600s"):
    return {"label": label, "intent": "active", "reboot_safe": True,
            "plist_source": "launch_agents", "schedule": schedule,
            "program": "x.sh", "layer": "product", "role": "monitoring",
            "produces": [], "consumes": [], "consumer_required": False,
            "governed_by": [], "curation": "partial", "notes": ""}


def artifact(path, slo_hours=None, consumers=("orchestrator_protocol",)):
    """slo_hours=None ⇒ поле ОТСУТСТВУЕТ (а не равно нулю).

    Разница существенна: отсутствие поля — это то, что по ADR-158 пишет
    несостоявшееся согласование двух ролей. Ноль был бы назначенным числом.
    """
    art = {"path": path, "producer": PRODUCER, "consumers": list(consumers),
           "status": "active", "notes": ""}
    if slo_hours is not None:
        art["slo_hours"] = slo_hours
    return art


def run(artifacts, ages_h):
    """Прогон только B2: флот НЕ измерен (B1 отключён), реситов нет."""
    m = {"schema_version": 1, "agents": [agent()],
         "artifacts": list(artifacts), "designed_architectures": []}
    ts = {p: NOW - dt.timedelta(hours=h) for p, h in ages_h.items()}
    return ac.run_checks(m, None, lambda p: ts.get(p), {}, NOW)


def mentions(report, path):
    """Всё, чем отчёт вообще называет путь — по ЛЮБОМУ из читаемых каналов."""
    return {
        "findings": [f["key"] for f in report["findings"] if path in f["message"]],
        "unchecked": [u for u in report["unchecked"] if path in str(u)],
        "slo_unassigned": [u for u in report.get("slo_unassigned") or []
                           if u["path"] == path],
    }


class GapIsSpokenAloud(unittest.TestCase):
    """Сорок суток молчания обязаны быть НАЗВАНЫ."""

    def test_artifact_without_slo_is_named(self):
        # Ровно замер до правки: до неё все три канала были пусты.
        rep = run([artifact(UNASSIGNED)], {UNASSIGNED: STALE_H})
        said = mentions(rep, UNASSIGNED)
        self.assertTrue(
            said["slo_unassigned"],
            f"активный артефакт без назначенного срока не назван НИГДЕ: {said}")
        row = said["slo_unassigned"][0]
        self.assertEqual(row["producer"], PRODUCER)
        self.assertEqual(row["consumers"], ["orchestrator_protocol"])
        self.assertIn("НЕ ИЗМЕРЕНА", row["reason"])

    def test_gap_is_counted_so_zero_cannot_pass_for_all_assigned(self):
        rep = run([artifact(UNASSIGNED)], {UNASSIGNED: STALE_H})
        self.assertEqual(rep["counts"]["slo_unassigned"], 1)
        # И обратная сторона: там, где сроки назначены, счётчик ноль —
        # иначе «названо» было бы неотличимо от «всегда жалуется».
        rep2 = run([artifact(ASSIGNED, slo_hours=26)], {ASSIGNED: 1})
        self.assertEqual(rep2["counts"]["slo_unassigned"], 0)
        self.assertEqual(rep2["slo_unassigned"], [])

    def test_observed_age_is_measured_even_though_no_deadline_exists(self):
        """Возраст — это ВХОД для двух ролей, а не следствие срока.

        Соблазн был не мерить: «срока нет — сравнивать не с чем». Но ADR-158
        велит ролям назначать срок по цене опоздания, а владелец отклонил
        вывод срока из расписания. Единственный оставшийся факт о молчании —
        наблюдённый возраст; без него у ролей нет ничего.
        """
        rep = run([artifact(UNASSIGNED)], {UNASSIGNED: STALE_H})
        row = rep["slo_unassigned"][0]
        self.assertTrue(row["exists"])
        self.assertAlmostEqual(row["observed_age_h"], float(STALE_H), places=1)

    def test_absent_file_says_so_instead_of_inventing_an_age(self):
        """«Файла нет» и «файл старый» лечатся по-разному — и звучат по-разному.

        Событийный артефакт (`kill_switch_active.json` появляется только когда
        стоп-кран сработал) отсутствует ШТАТНО. Подставить сюда возраст —
        значит выдумать факт.
        """
        rep = run([artifact(UNASSIGNED)], {})  # ts_of вернёт None
        row = rep["slo_unassigned"][0]
        self.assertFalse(row["exists"])
        self.assertIsNone(row["observed_age_h"])


class GapDoesNotEscalate(unittest.TestCase):
    """Граница ADR-164 п.2: назвать — да, объявить аварией — нет."""

    def test_gap_is_not_a_finding_and_not_unchecked(self):
        rep = run([artifact(UNASSIGNED)], {UNASSIGNED: STALE_H})
        said = mentions(rep, UNASSIGNED)
        self.assertEqual(
            said["findings"], [],
            "пробел в контракте выдан за находку — сторож станет вечно "
            "жёлтым, и его перестанут читать (ADR-164 п.2)")
        self.assertEqual(said["unchecked"], [], "то же самое через unchecked")

    def test_gap_alone_does_not_move_the_verdict(self):
        """Единственный артефакт без срока не смеет менять overall.

        Сравнение с контрольным прогоном, где ВСЁ то же самое, но срок
        назначен и артефакт свеж: вердикты обязаны совпасть.
        """
        control = run([artifact(ASSIGNED, slo_hours=26)], {ASSIGNED: 1})
        subject = run([artifact(UNASSIGNED)], {UNASSIGNED: STALE_H})
        self.assertEqual(subject["overall"], control["overall"])
        self.assertEqual(subject["counts"]["warn"], control["counts"]["warn"])
        self.assertEqual(subject["counts"]["unchecked"],
                         control["counts"]["unchecked"])


class AssignedSloIsUntouched(unittest.TestCase):
    """Обратная сторона: настоящее протухание обязано краснеть как раньше."""

    def test_stale_artifact_with_slo_still_reddens(self):
        rep = run([artifact(ASSIGNED, slo_hours=26)], {ASSIGNED: STALE_H})
        self.assertIn(f"B2:stale:{ASSIGNED}",
                      [f["key"] for f in rep["findings"]])
        self.assertEqual(rep["slo_unassigned"], [],
                         "артефакт с назначенным сроком попал в список "
                         "«срок не назначен» — правка съела чужой предмет")

    def test_both_kinds_coexist_without_shadowing_each_other(self):
        rep = run([artifact(ASSIGNED, slo_hours=26), artifact(UNASSIGNED)],
                  {ASSIGNED: STALE_H, UNASSIGNED: STALE_H})
        self.assertIn(f"B2:stale:{ASSIGNED}",
                      [f["key"] for f in rep["findings"]])
        self.assertEqual([u["path"] for u in rep["slo_unassigned"]],
                         [UNASSIGNED])


class OfficeStepSaysIt(unittest.TestCase):
    """Блок в JSON, который не звучит в шаге 0-офис, — тот же немой исход.

    Шаг 0-офис (`consume_office_reports.py`) — назначенный ЧИТАТЕЛЬ этого
    сторожа: протокол обязывает оркестратора гонять его каждый цикл и
    действовать по красным строкам. Проверка идёт через РЕАЛЬНЫЙ рендерер, а
    не через собственную выемку полей: своя выемка проверила бы мою же
    догадку о формате.
    """

    def _render(self, report):
        import importlib.util
        import os
        path = os.path.join(ac.REPO_ROOT, "scripts", "consume_office_reports.py")
        spec = importlib.util.spec_from_file_location("_cor_probe", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return "\n".join(mod._summarize_json(
            "data/architecture_conformance.json", report, now=NOW))

    def test_step_zero_office_prints_the_gap(self):
        rep = run([artifact(UNASSIGNED)], {UNASSIGNED: STALE_H})
        text = self._render(rep)
        self.assertIn("СРОК НЕ НАЗНАЧЕН", text)
        self.assertIn(UNASSIGNED, text)
        self.assertIn("НЕ ИЗМЕРЕНА", text)

    def test_step_zero_office_stays_quiet_when_all_slos_are_assigned(self):
        rep = run([artifact(ASSIGNED, slo_hours=26)], {ASSIGNED: 1})
        self.assertNotIn("СРОК НЕ НАЗНАЧЕН", self._render(rep))


if __name__ == "__main__":
    unittest.main()
