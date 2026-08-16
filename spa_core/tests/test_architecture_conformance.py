"""Тесты сторожа architecture_conformance (ADR-066, Фаза 1).

Каждый positive control воспроизводит реальную находку аудита 2026-08-05
(правило deployment.md: проверка без настоящей поломки не принимается),
и у каждой проверки есть обратная сторона (исправное состояние → зелёно):

  B1: swarm_dwell (загружен, в манифесте нет) · зомби-retired · мёртвый active ·
      reboot-unsafe (artifact_freshness) · unresolved стареет, CRITICAL — нет;
  B2: agent_registry 19 дней протухания (generated_at из содержимого, не mtime);
  B3: 12 io_* без единого ресита потребления; свежий ресит гасит находку;
  UNCHECKED: launchctl недоступен ⇒ overall НЕ OK (класс fail-OPEN мониторов #29–#38).

Часы инъектируются (now=) — литеральных дат с дрейфом нет (deployment.md: время — вход).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import unittest

from spa_core.monitoring import architecture_conformance as ac

NOW = dt.datetime(2030, 1, 15, 12, 0, tzinfo=dt.timezone.utc)  # FROZEN-DATE-OK: injected-clock — часы инъектируются парой с отметками


def agent(label, intent="active", reboot_safe=True, consumer_required=False):
    return {"label": label, "intent": intent, "reboot_safe": reboot_safe,
            "plist_source": "launch_agents" if reboot_safe else "repo:launchd/x.plist",
            "schedule": "interval:300s", "program": "x.sh", "layer": "product",
            "role": "monitoring", "produces": [], "consumes": [],
            "consumer_required": consumer_required, "governed_by": [],
            "curation": "partial", "notes": ""}


def manifest(agents=(), artifacts=()):
    return {"schema_version": 1, "agents": list(agents), "artifacts": list(artifacts),
            "designed_architectures": []}


def run(m, fleet, ts_map=None, receipts=None, prev=None, drift=None, measured=True,
        curation=None):
    ts_map = ts_map or {}
    return ac.run_checks(m, fleet, lambda p: ts_map.get(p), receipts or {}, NOW,
                         prev_first_seen=prev, drift_problems=drift,
                         drift_measured=measured, curation=curation)


def keys(report):
    return {f["key"] for f in report["findings"]}


class B1Fleet(unittest.TestCase):
    def test_loaded_but_not_in_manifest_is_critical(self):
        """Инцидент swarm_dwell: работает — конституция о нём не знает."""
        r = run(manifest([agent("com.spa.a")]), {"com.spa.a", "com.spa.swarm_dwell"})
        self.assertIn("B1:unknown:com.spa.swarm_dwell", keys(r))
        self.assertEqual(r["overall"], "CRITICAL")

    def test_zombie_retired_running_is_critical(self):
        r = run(manifest([agent("com.spa.z", intent="retired")]), {"com.spa.z"})
        self.assertIn("B1:zombie:com.spa.z", keys(r))

    def test_designed_running_is_critical(self):
        r = run(manifest([agent("com.spa.hoi", intent="designed")]), {"com.spa.hoi"})
        self.assertIn("B1:premature:com.spa.hoi", keys(r))

    def test_active_not_loaded_is_critical(self):
        """Авария 2026-08-04 (67/69 обесточены) в терминах конституции."""
        r = run(manifest([agent("com.spa.a")]), set())
        self.assertIn("B1:dead:com.spa.a", keys(r))
        self.assertEqual(r["overall"], "CRITICAL")

    def test_reboot_unsafe_is_warn_strong(self):
        """Находка artifact_freshness: работает, ребут его убьёт."""
        r = run(manifest([agent("com.spa.af", reboot_safe=False)]), {"com.spa.af"})
        self.assertIn("B1:reboot_unsafe:com.spa.af", keys(r))
        self.assertEqual(r["overall"], "WARN")

    def test_healthy_fleet_is_ok(self):
        """Обратная сторона: конституция соблюдена → OK, без находок."""
        r = run(manifest([agent("com.spa.a"), agent("com.spa.r", intent="retired")]),
                {"com.spa.a"})
        self.assertEqual(r["findings"], [])
        self.assertEqual(r["overall"], "OK")

    def test_unresolved_running_is_weak_warn_not_critical(self):
        r = run(manifest([agent("com.spa.u", intent="unresolved")]), {"com.spa.u"})
        f = [x for x in r["findings"] if x["key"].startswith("B1:unresolved_running")]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["severity"], "WARN")
        self.assertEqual(f[0]["class"], "weak")


class B6CurationFromOrigin(unittest.TestCase):
    """Замер 08.08 (карточка `inbox-storozh-arhitektury-krichit-critical-o-c`):
    прод-дерево `architecture/` не получает НИКОГДА, перегенерировало манифест из
    своей стёртой памяти и выдало 4 CRITICAL про агентов, которых владелец
    разрешил поставить 08.08 (`own-31`). Локально `intent=retired` / записи нет,
    на `origin/main` — `active`. Каждый тест ниже — либо реплей этой аварии, либо
    контроль в обратную сторону: сторож не смеет становиться зеленее."""

    def reconcile(self, local_agents, origin_agents):
        return ac.reconcile_curation(manifest(local_agents), manifest(origin_agents))

    # ── реплей аварии 08.08 ──────────────────────────────────────────────────
    def test_local_retired_origin_active_is_not_zombie(self):
        """digest_weekly / tier1_digest / weekly_backup: локально retired,
        на origin active, во флоте загружены ⇒ ни одного зомби."""
        labels = ["com.spa.digest_weekly", "com.spa.tier1_digest",
                  "com.spa.weekly_backup"]
        m, cur = self.reconcile([agent(l, intent="retired") for l in labels],
                                [agent(l, intent="active") for l in labels])
        r = run(m, set(labels), curation=cur)
        self.assertEqual([k for k in keys(r) if k.startswith("B1:zombie")], [])
        self.assertEqual(r["counts"]["critical"], 0)
        self.assertEqual(r["curation"]["source"], ac.CURATION_REF)

    def test_agent_known_only_to_origin_is_not_unknown(self):
        """telegram_health: загружен, локальный манифест о нём не знает, origin
        знает и говорит active ⇒ не «в манифесте ОТСУТСТВУЕТ» (класс swarm_dwell
        не должен срабатывать на стёртую память)."""
        m, cur = self.reconcile([agent("com.spa.a")],
                                [agent("com.spa.a"), agent("com.spa.telegram_health")])
        r = run(m, {"com.spa.a", "com.spa.telegram_health"}, curation=cur)
        self.assertEqual(keys(r) & {"B1:unknown:com.spa.telegram_health"}, set())
        self.assertEqual(cur["added_from_origin"], ["com.spa.telegram_health"])

    # ── контроль в обратную сторону: настоящая авария обязана остаться ───────
    def test_real_zombie_survives_reconciliation(self):
        """ОБЯЗАТЕЛЬНЫЙ второй тест карточки: origin ТОЖЕ говорит retired, агент
        загружен ⇒ CRITICAL. Без него это была бы глушилка, а не починка."""
        m, cur = self.reconcile([agent("com.spa.z", intent="retired")],
                                [agent("com.spa.z", intent="retired")])
        r = run(m, {"com.spa.z"}, curation=cur)
        self.assertIn("B1:zombie:com.spa.z", keys(r))
        self.assertEqual(r["overall"], "CRITICAL")

    def test_origin_says_retired_local_says_active_becomes_zombie(self):
        """Сверка работает в ОБЕ стороны: решение «вывести», записанное в git,
        краснит агента, который локально всё ещё числится живым."""
        m, cur = self.reconcile([agent("com.spa.z", intent="active")],
                                [agent("com.spa.z", intent="retired")])
        r = run(m, {"com.spa.z"}, curation=cur)
        self.assertIn("B1:zombie:com.spa.z", keys(r))

    def test_origin_only_active_agent_not_loaded_is_dead_critical(self):
        """Добавленный с origin агент не приносит поблажки: intent=active и не
        загружен ⇒ B1:dead, как и любой другой."""
        m, cur = self.reconcile([agent("com.spa.a")],
                                [agent("com.spa.a"), agent("com.spa.gone")])
        r = run(m, {"com.spa.a"}, curation=cur)
        self.assertIn("B1:dead:com.spa.gone", keys(r))
        self.assertEqual(r["overall"], "CRITICAL")

    # ── границы приёма курации ──────────────────────────────────────────────
    def test_local_only_agent_keeps_local_curation(self):
        """Агента, которого origin не знает, локальная курация — единственное,
        что о нём известно; отбирать её нельзя."""
        m, cur = self.reconcile([agent("com.spa.new", intent="retired")],
                                [agent("com.spa.a")])
        r = run(m, {"com.spa.new"}, curation=cur)
        self.assertIn("B1:zombie:com.spa.new", keys(r))
        self.assertEqual(cur["local_only"], ["com.spa.new"])

    def test_mechanical_fields_stay_local(self):
        """С origin берётся КУРАЦИЯ, факты хоста — нет: `reboot_safe` origin'а
        не должен гасить находку «не переживёт ребут» на этом хосте."""
        loc = agent("com.spa.af", reboot_safe=False)
        org = agent("com.spa.af", reboot_safe=True)
        m, cur = self.reconcile([loc], [org])
        self.assertFalse(m["agents"][0]["reboot_safe"])
        r = run(m, {"com.spa.af"}, curation=cur)
        self.assertIn("B1:reboot_unsafe:com.spa.af", keys(r))

    def test_curated_fields_match_builder(self):
        """Новое курируемое поле в генераторе обязано попасть и сюда — иначе оно
        молча продолжит читаться с устаревшей локальной копии."""
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(ac.__file__)))), "scripts", "build_architecture_manifest.py")
        spec = importlib.util.spec_from_file_location("bam_probe", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(set(ac.CURATED_FIELDS), set(mod.CURATED_DEFAULTS))

    # ── расхождение НАЗЫВАЕТСЯ, а не проглатывается ─────────────────────────
    def test_drift_is_named_as_warn_finding(self):
        m, cur = self.reconcile([agent("com.spa.z", intent="retired")],
                                [agent("com.spa.z", intent="active")])
        r = run(m, {"com.spa.z"}, curation=cur)
        f = [x for x in r["findings"] if x["key"] == "B6:curation_drift"]
        self.assertEqual(len(f), 1)
        self.assertEqual((f[0]["severity"], f[0]["class"]), ("WARN", "strong"))
        self.assertIn("com.spa.z", f[0]["message"])
        self.assertEqual(r["overall"], "WARN")

    def test_identical_curation_is_silent_and_ok(self):
        """Обратная сторона: расхождения нет ⇒ ни находки, ни шума."""
        m, cur = self.reconcile([agent("com.spa.a")], [agent("com.spa.a")])
        r = run(m, {"com.spa.a"}, curation=cur)
        self.assertEqual(r["findings"], [])
        self.assertEqual(r["overall"], "OK")

    def test_unreachable_origin_is_unchecked_not_silent_fallback(self):
        """Класс fail-OPEN: не смогли сверить ⇒ НЕ «всё хорошо». Локальная копия
        используется (иначе слепота), но вердикт честно не OK."""
        m, cur = ac.reconcile_curation(manifest([agent("com.spa.a")]), None,
                                       reason="нет origin/main")
        self.assertFalse(cur["measured"])
        r = run(m, {"com.spa.a"}, curation=cur)
        self.assertTrue(any(u["check"] == "B6_curation" for u in r["unchecked"]))
        self.assertEqual(r["overall"], "UNCHECKED")

    def test_curation_not_requested_changes_nothing(self):
        """curation=None — «сверка не запрашивалась»: чистая функция остаётся
        прежней для всех остальных вызовов."""
        r = run(manifest([agent("com.spa.a")]), {"com.spa.a"})
        self.assertEqual(r["overall"], "OK")
        self.assertIsNone(r["curation"])

    def test_origin_manifest_refuses_outside_a_repo(self):
        """`git show` вне репозитория — не исключение и не молчание, а причина."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            data, why = ac.origin_manifest(root=td)
            self.assertIsNone(data)
            self.assertTrue(why)


class B2Freshness(unittest.TestCase):
    def art(self, slo=26):
        return {"path": "data/agent_registry.json", "producer": None,
                "consumers": [], "slo_hours": slo, "status": "active"}

    def test_stale_beyond_slo_is_flagged(self):
        """Инцидент реестра: 19 дней — против SLO 26ч."""
        r = run(manifest([], [self.art()]),
                set(), ts_map={"data/agent_registry.json": NOW - dt.timedelta(days=19)})
        self.assertIn("B2:stale:data/agent_registry.json", keys(r))

    def test_fresh_is_green_missing_is_flagged(self):
        ok = run(manifest([], [self.art()]), set(),
                 ts_map={"data/agent_registry.json": NOW - dt.timedelta(hours=1)})
        self.assertEqual([k for k in keys(ok) if k.startswith("B2")], [])
        missing = run(manifest([], [self.art()]), set(), ts_map={})
        self.assertIn("B2:missing:data/agent_registry.json", keys(missing))

    def test_planned_artifact_not_expected(self):
        r = run(manifest([], [{"path": "data/loop_health.json", "producer": None,
                               "consumers": [], "status": "planned"}]), set())
        self.assertEqual(r["findings"], [])


class B3Consumption(unittest.TestCase):
    def setup_io(self):
        a = agent("com.spa.io_quant", consumer_required=True)
        art = {"path": "data/investment_os/quant.json", "producer": "com.spa.io_quant",
               "consumers": ["orchestrator_protocol"], "slo_hours": 26, "status": "active"}
        return manifest([a], [art])

    def test_no_receipt_is_flagged(self):
        """Ядро аудита: отчёт офиса без единого читателя."""
        m = self.setup_io()
        r = run(m, {"com.spa.io_quant"},
                ts_map={"data/investment_os/quant.json": NOW - dt.timedelta(hours=1)})
        self.assertIn("B3:no_consumption:data/investment_os/quant.json", keys(r))

    def test_fresh_receipt_clears_finding(self):
        m = self.setup_io()
        r = run(m, {"com.spa.io_quant"},
                ts_map={"data/investment_os/quant.json": NOW - dt.timedelta(hours=1)},
                receipts={"data/investment_os/quant.json": NOW - dt.timedelta(hours=2)})
        self.assertEqual([k for k in keys(r) if k.startswith("B3")], [])
        self.assertEqual(r["overall"], "OK")

    def test_stale_receipt_is_flagged(self):
        """Потребитель когда-то читал и замолчал — не то же, что «читает»."""
        m = self.setup_io()
        r = run(m, {"com.spa.io_quant"},
                ts_map={"data/investment_os/quant.json": NOW - dt.timedelta(hours=1)},
                receipts={"data/investment_os/quant.json": NOW - dt.timedelta(days=5)})
        self.assertIn("B3:consumption_stale:data/investment_os/quant.json", keys(r))


class UncheckedHonesty(unittest.TestCase):
    def test_fleet_unmeasured_is_not_ok(self):
        """Класс fail-OPEN (#29–#38): «не смог посмотреть» ≠ «всё хорошо»."""
        r = run(manifest([agent("com.spa.a")]), None)
        self.assertEqual(r["overall"], "UNCHECKED")
        self.assertEqual(r["exit_code"], 1)
        self.assertTrue(any(u["check"] == "B1_fleet" for u in r["unchecked"]))

    def test_drift_unmeasured_is_reported(self):
        r = run(manifest([]), set(), measured=False)
        self.assertTrue(any(u["check"] == "B5_manifest" for u in r["unchecked"]))
        self.assertEqual(r["overall"], "UNCHECKED")

    def test_drift_problem_is_warn(self):
        r = run(manifest([]), set(), drift=["com.spa.x: schedule изменился"], measured=True)
        self.assertTrue(any(f["check"] == "B5" for f in r["findings"]))


class B5DriftIsActionable(unittest.TestCase):
    """Цикл #264: находка B5 держала диагноз в руках и выбрасывала его.

    Живой замер 2026-08-16: прод-дерево не получает `launchd/` при автосинке,
    поэтому `com.spa.site_freshness` пропал из фактов, и генератор печатал ТРИ
    строки DRIFT. Сторож брал от него один код возврата и писал владельцу
    «манифест ↔ факты: manifest --check вернул дрейф (см. build_architecture_
    manifest.py)» — ни агента, ни поля, ни направления; вдобавок флага `--check`
    у скрипта нет вовсе, то есть повторить замер по инструкции самой находки
    было НЕЛЬЗЯ. Карточка моста из такой находки нечитаема по построению.
    """

    # ровно то, что напечатал генератор в проде 16.08 (скопировано с прогона)
    REAL = ["com.spa.site_freshness: plist_source 'repo:launchd/com.spa.site_freshness.plist' → None",
            "com.spa.site_freshness: schedule 'interval:21600s' → None",
            "com.spa.site_freshness: program 'agent_site_freshness.sh' → None"]

    def test_finding_names_agent_field_and_direction(self):
        """Положительный контроль: на неисправленном сторо́же текст находки не
        содержал ни имени агента, ни поля — краснеет именно на поведении."""
        r = run(manifest([]), set(), drift=ac.group_drift_by_agent(self.REAL))
        msgs = [f["message"] for f in r["findings"] if f["check"] == "B5"]
        self.assertEqual(len(msgs), 1, msgs)
        self.assertIn("com.spa.site_freshness", msgs[0])
        for field in ("plist_source", "schedule", "program"):
            self.assertIn(field, msgs[0])
        self.assertIn("agent_site_freshness.sh", msgs[0])

    def test_one_agent_gives_one_card_not_three(self):
        """Ключ находки = ЛИЧНОСТЬ агента: три поля одной причины не имеют права
        стать тремя карточками (мост заводит карточку на ключ)."""
        r = run(manifest([]), set(), drift=ac.group_drift_by_agent(self.REAL))
        self.assertEqual([f["key"] for f in r["findings"] if f["check"] == "B5"],
                         ["B5:drift:com.spa.site_freshness"])

    def test_key_survives_wording_change_of_a_field(self):
        """Ключ не заводится заново от правки формулировки одного поля —
        иначе карточка воскресала бы при каждом косметическом изменении."""
        other = list(self.REAL)
        other[1] = "com.spa.site_freshness: schedule 'interval:900s' → None"
        a = ac.group_drift_by_agent(self.REAL)[0]["key"]
        b = ac.group_drift_by_agent(other)[0]["key"]
        self.assertEqual(a, b)

    def test_two_agents_stay_two_findings(self):
        drift = ac.group_drift_by_agent(
            self.REAL + ["com.spa.daily_cycle: program 'a.sh' → 'b.sh'"])
        r = run(manifest([]), set(), drift=drift)
        self.assertEqual(sorted(f["key"] for f in r["findings"] if f["check"] == "B5"),
                         ["B5:drift:com.spa.daily_cycle",
                          "B5:drift:com.spa.site_freshness"])

    def test_line_without_agent_keeps_its_own_key(self):
        """Схемная строка про артефакт владельца не имеет — выдумывать его нельзя."""
        got = ac.group_drift_by_agent(
            ["artifact data/x.json: active без положительного slo_hours"])
        self.assertEqual(len(got), 1)
        self.assertNotIn("com.spa.", got[0]["key"])
        self.assertIn("slo_hours", got[0]["message"])

    def test_legacy_string_form_still_supported(self):
        """Обратный контроль: прежняя форма (просто строка) не сломана."""
        r = run(manifest([]), set(), drift=["com.spa.x: schedule изменился"])
        f = [f for f in r["findings"] if f["check"] == "B5"]
        self.assertEqual(len(f), 1)
        self.assertIn("com.spa.x: schedule изменился", f[0]["message"])

    def test_no_drift_no_finding(self):
        """Обратный контроль: исправное состояние остаётся зелёным."""
        r = run(manifest([]), set(), drift=ac.group_drift_by_agent([]))
        self.assertEqual([f for f in r["findings"] if f["check"] == "B5"], [])

    def test_measure_failure_key_has_no_exception_text(self):
        """Ключ падения не тащит текст исключения: иначе смена пути/строки
        рождала бы новую находку и новую карточку на каждый чих окружения."""
        import unittest.mock as mock
        with mock.patch.object(ac, "REPO_ROOT", "/nonexistent/spa-root"):
            got = ac._manifest_drift_problems()
        self.assertIsNotNone(got)
        self.assertEqual([g["key"] for g in got], ["measure_failed"])


class Aging(unittest.TestCase):
    def test_weak_ages_out_strong_does_not(self):
        """Слабый сигнал старше горизонта не голодит очередь; сильный — вечен."""
        m = manifest([agent("com.spa.u", intent="unresolved"),
                      agent("com.spa.af", reboot_safe=False)])
        old = (NOW - dt.timedelta(days=ac.WEAK_AGE_DAYS + 1)).isoformat()
        prev = {"B1:unresolved_running:com.spa.u": old,
                "B1:reboot_unsafe:com.spa.af": old}
        r = run(m, {"com.spa.u", "com.spa.af"}, prev=prev)
        self.assertEqual([f["key"] for f in r["aged"]],
                         ["B1:unresolved_running:com.spa.u"])
        self.assertIn("B1:reboot_unsafe:com.spa.af", keys(r))

    def test_first_seen_carried_from_previous_report(self):
        m = manifest([agent("com.spa.u", intent="unresolved")])
        seen = (NOW - dt.timedelta(days=3)).isoformat()
        r = run(m, {"com.spa.u"}, prev={"B1:unresolved_running:com.spa.u": seen})
        self.assertEqual(r["findings"][0]["first_seen"], seen)


class Plumbing(unittest.TestCase):
    def test_receipts_parser_takes_latest_and_survives_junk(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write('{"artifact":"a.json","consumer":"x","consumed_at":"2030-01-15T10:00:00+00:00"}\n')
            f.write("НЕ JSON\n")
            f.write('{"artifact":"a.json","consumer":"y","consumed_at":"2030-01-15T11:00:00+00:00"}\n')
            path = f.name
        try:
            got = ac.load_receipts(path)
            self.assertEqual(got["a.json"].hour, 11)
        finally:
            os.unlink(path)

    def test_artifact_timestamp_prefers_content_over_mtime(self):
        """mtime лжёт после синка/checkout — содержимое главнее."""
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         dir=".", prefix="ts_probe_") as f:
            json.dump({"generated_at": "2030-01-01T00:00:00+00:00"}, f)
            name = os.path.basename(f.name)
        try:
            ts = ac.artifact_timestamp(name, root=".")
            self.assertEqual((ts.year, ts.month, ts.day), (2030, 1, 1))
        finally:
            os.unlink(name)


class LiveAcceptance(unittest.TestCase):
    """Приёмка Фазы 1: на прод-хосте сторож обязан быть КРАСНЫМ ровно по
    классам находок аудита 2026-08-05. В CI (нет launchctl-флота) — skip."""

    def test_prod_fully_measured_and_b3_detects_counterfactually(self):
        """ИЗМЕНЁН ОСОЗНАННО 2026-08-06 (инв. 16, журнал W32): исходная версия
        была приколочена к переходному состоянию Фазы 1 («реситов ещё нет») и
        честно устарела, когда Фаза 2 погасила B3 настоящими реситами. Проверка
        УСИЛЕНА: (а) на проде всё ИЗМЕРЕНО (unchecked пуст — класс fail-OPEN);
        (б) репродукция аудита 2026-08-05 теперь КОНТРФАКТИЧЕСКАЯ — обнуляем
        реситы и B3 ОБЯЗАН вернуть «офис в никуда» при любом живом состоянии,
        навсегда, а не только до Фазы 2."""
        fleet = ac.gather_fleet()
        if not fleet:
            self.skipTest("не прод-хост: launchctl без com.spa.*")
        m = json.load(open(ac.MANIFEST_PATH))
        now = dt.datetime.now(dt.timezone.utc)
        drift = ac._manifest_drift_problems()
        r = ac.run_checks(m, fleet, ac.artifact_timestamp, ac.load_receipts(), now,
                          drift_problems=drift, drift_measured=drift is not None)
        self.assertEqual(r["unchecked"], [], "на проде всё должно быть измеримо")
        for f in r["findings"] + r["aged"]:
            self.assertTrue(f["key"].startswith(("B1:", "B2:", "B3:", "B5:")), f["key"])
        # контрфактический позитивный контроль: реситы исчезли ⇒ B3 краснеет
        no_receipts = ac.run_checks(m, fleet, ac.artifact_timestamp, {}, now,
                                    drift_problems=drift, drift_measured=drift is not None)
        self.assertTrue(
            any(k.startswith("B3:no_consumption:data/investment_os/")
                for k in keys(no_receipts)),
            "B3 перестал детектировать потерю потребления — театр")

    def test_exit_zero_mode_reports_but_returns_zero(self):
        """Плановый launchd-режим: вердикт в отчёте, exit 0 — иначе agent_health
        вечно видел бы «сломанного» сторожа и маскировал настоящие падения.
        CLI-режим (--run без флага) обязан сохранять честный ненулевой код."""
        import tempfile
        if not ac.gather_fleet():
            self.skipTest("не прод-хост: launchctl без com.spa.*")
        with tempfile.TemporaryDirectory() as td:
            report_path = os.path.join(td, "r.json")
            rc = ac.main(["--run", "--exit-zero", "--report", report_path])
            self.assertEqual(rc, 0)
            report = json.load(open(report_path))
            # ИЗМЕНЁН ОСОЗНАННО 2026-08-06 (инв. 16, журнал W32): исходная версия
            # требовала overall != OK — она писалась, когда прод был честно красным,
            # и устарела в момент, когда находки погасили (блок 1 ADR-067). Проверка
            # стала state-agnostic: exit-zero всегда 0, а честный режим обязан
            # возвращать РОВНО exit_code отчёта — при любом живом состоянии.
            self.assertIn(report["overall"], ("OK", "WARN", "CRITICAL", "UNCHECKED"))
            self.assertEqual(report["exit_code"],
                             ac.EXIT_BY_OVERALL[report["overall"]])
            rc_honest = ac.main(["--run", "--report", report_path])
            self.assertEqual(rc_honest, report["exit_code"])


if __name__ == "__main__":
    unittest.main()


class TimestampSchemaCompat(unittest.TestCase):
    def test_date_only_stamp_falls_back_to_mtime(self):
        """Инцидент 02:39 07.08: generated_at «2026-08-06» (без времени) читался
        как полночь и рождал ложный stale-WARN каждую ночь. Дата без времени
        точнее mtime не является — обязан победить mtime; полный ISO — побеждает."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "d.json")
            with open(p, "w") as f:
                json.dump({"generated_at": "2026-08-06"}, f)
            ts = ac.artifact_timestamp("d.json", td)
            mtime = dt.datetime.fromtimestamp(os.path.getmtime(p), tz=dt.timezone.utc)
            self.assertEqual(ts, mtime)
            with open(p, "w") as f:
                json.dump({"generated_at": "2026-08-06T15:30:00+00:00"}, f)
            ts2 = ac.artifact_timestamp("d.json", td)
            self.assertEqual((ts2.hour, ts2.minute), (15, 30))
