"""Тесты сторожа architecture_conformance (ADR-066, Фаза 1).

Каждая проверка сторожа рождается вместе с тестом, ВОСПРОИЗВОДЯЩИМ настоящую аварию
(правило `.claude/rules/deployment.md`: «проверка, никогда не видевшая настоящей поломки, —
украшение»). Аварии — аудит 2026-08-05:

  * `swarm_dwell` / `artifact_freshness` работали, не будучи объявленными нигде, и без
    персистентного plist — не пережили бы ребут; 19 дней никто не заметил;
  * `agent_registry.json` протух 475ч при SLO 26ч — брошенный продюсер;
  * 12 агентов `io_*` ежедневно писали продукт, которого не читал никто;
  * `checkpoint-7day` / `novel_edge_rnd` месяцами висели в «никто не решал».

Плюс контроли в ОБРАТНУЮ сторону: здоровый флот даёт ровно `OK` и код 0 — иначе сторож,
который всегда красный, обучает всех себя игнорировать.

Тесты герметичны: манифест, флот (`launchctl list` как СТРОКА), реситы и время
инъектируются. Ни сети, ни живого launchctl, ни живого `data/`.

# FROZEN-DATE-OK: часы ИНЪЕКТИРОВАНЫ (способ №1 правила `.claude/rules/deployment.md`).
# Литерал `NOW` — это и есть подаваемое время: КАЖДЫЙ прогон получает `now=NOW`, а все
# отметки (mtime артефактов, `consumed_at` реситов, `first_seen`) строятся ОТ него
# смещениями. Обе стороны закреплены, календарь на результат не влияет — измерено, а не
# заявлено: файл даёт те же 72 passed при `NOW` = 2019-01-01, 2026-08-05 и 2031-03-07.
# Дата 2026-08-05 выбрана лишь потому, что это день воспроизводимых здесь аварий.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from spa_core.monitoring import architecture_conformance as ac

NOW = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_live_launchctl(monkeypatch):
    """Ни один тест не смеет дотянуться до НАСТОЯЩЕГО флота.

    Первая версия файла об этом забыла: тест с `launchctl_output=None` молча вызвал живой
    `launchctl list` и получил 71 агента прод-машины — герметичный на вид тест зависел от
    состояния хоста и на другой машине (или в CI) дал бы другой результат. Теперь подпроцесс
    без явной инъекции недоступен, `read_fleet` детерминированно отдаёт `None`, и `None`
    честно значит «флот не измерен» независимо от машины.
    """

    def _forbidden(*a, **k):
        raise AssertionError("тест обратился к живому launchctl: {}".format(a))

    monkeypatch.setattr(ac.subprocess, "run", _forbidden)


# ═══════════════════════════════════════════════════════════════════════════
# Фикстуры-строители
# ═══════════════════════════════════════════════════════════════════════════
def agent(label, **kw):
    base = {
        "label": label,
        "plist_source": "launch_agents",
        "reboot_safe": True,
        "schedule": "interval:3600s",
        "program": "agent_x.sh",
        "layer": "product",
        "role": "monitoring",
        "intent": "active",
        "produces": [],
        "consumes": [],
        "consumer_required": False,
        "governed_by": [],
        "curation": "complete",
        "notes": "",
    }
    base.update(kw)
    return base


def manifest(agents, artifacts=None, designed=None):
    return {
        "schema_version": 1,
        "adr": "ADR-066",
        "agents": agents,
        "artifacts": artifacts or [],
        "designed_architectures": designed or [],
    }


def launchctl(*labels):
    """Строка ровно того формата, что отдаёт `launchctl list`."""
    lines = ["PID\tStatus\tLabel"]
    for lb in labels:
        lines.append("-\t0\t{}".format(lb))
    return "\n".join(lines) + "\n"


def write_manifest(tmp_path, doc):
    p = tmp_path / "architecture" / "manifest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return p


def keys(findings):
    return {f.key for f in findings}


def run(tmp_path, doc, *, fleet_str, data_dir=None, now=NOW, write=False):
    write_manifest(tmp_path, doc)
    ddir = data_dir or (tmp_path / "data")
    ddir.mkdir(parents=True, exist_ok=True)
    return ac.run_conformance(repo_root=tmp_path, data_dir=ddir,
                              launchctl_output=fleet_str, now=now, write=write)


# ═══════════════════════════════════════════════════════════════════════════
# B1 — fleet ↔ манифест в обе стороны
# ═══════════════════════════════════════════════════════════════════════════
def test_b1_loaded_but_undeclared_is_critical():
    """АВАРИЯ 2026-08-05: swarm_dwell работал, не будучи объявлен нигде — 19 дней тишины."""
    m = manifest([agent("com.spa.agent_health")])
    fleet, _ = ac.read_fleet(launchctl("com.spa.agent_health", "com.spa.swarm_dwell"))
    found = ac.check_b1_fleet_vs_manifest(m, fleet)
    hit = [f for f in found if f.key == "b1:loaded-not-declared:com.spa.swarm_dwell"]
    assert hit, "загруженный, но необъявленный агент обязан быть находкой"
    assert hit[0].severity == ac.CRITICAL
    assert hit[0].strength == ac.STRONG, "сильный сигнал не имеет права стареть"


def test_b1_declared_active_but_absent_from_fleet_is_critical():
    m = manifest([agent("com.spa.daily_cycle")])
    fleet, _ = ac.read_fleet(launchctl("com.spa.agent_health"))
    found = ac.check_b1_fleet_vs_manifest(m, fleet)
    assert "b1:active-not-loaded:com.spa.daily_cycle" in keys(found)


def test_b1_retired_but_still_loaded_is_a_zombie():
    m = manifest([agent("com.spa.weekly_backup", intent="retired", reboot_safe=False,
                        plist_source=None)])
    fleet, _ = ac.read_fleet(launchctl("com.spa.weekly_backup"))
    found = ac.check_b1_fleet_vs_manifest(m, fleet)
    hit = [f for f in found if f.key.startswith("b1:retired-but-loaded")]
    assert hit and hit[0].severity == ac.WARN


def test_b1_active_without_persistent_plist_is_critical():
    """АВАРИЯ 2026-08-05: агент жил, но plist'а в ~/Library/LaunchAgents нет — ребут его убьёт."""
    m = manifest([agent("com.spa.swarm_dwell", reboot_safe=False,
                        plist_source="repo:launchd/com.spa.swarm_dwell.plist")])
    fleet, _ = ac.read_fleet(launchctl("com.spa.swarm_dwell"))
    found = ac.check_b1_fleet_vs_manifest(m, fleet)
    hit = [f for f in found if f.key == "b1:active-not-reboot-safe:com.spa.swarm_dwell"]
    assert hit and hit[0].severity == ac.CRITICAL, (
        "загружен ≠ переживёт ребут: agent_health на этот вопрос не отвечает")


def test_b1_unresolved_intent_is_a_weak_finding():
    """АВАРИЯ 2026-08-05: checkpoint-7day / novel_edge_rnd — «никто не решал» месяцами.

    Слабая: закрывается только владельцем (R4), поэтому обязана стареть — иначе очередь
    навсегда забита неустранимым (урок irreversible-unchecked-starves-queue).
    """
    m = manifest([agent("com.spa.checkpoint-7day", intent="unresolved", reboot_safe=False,
                        notes="в реестре, не загружен, retired не помечен")])
    found = ac.check_b1_fleet_vs_manifest(m, {})
    hit = [f for f in found if f.key == "b1:intent-unresolved:com.spa.checkpoint-7day"]
    assert hit, "«никто не решал» обязано быть видимой находкой, а не молчанием"
    assert hit[0].severity == ac.WARN
    assert hit[0].strength == ac.WEAK
    assert "в реестре, не загружен" in hit[0].message, "причина цитируется, а не пересказывается"


def test_b1_unmeasured_fleet_is_unchecked_not_ok():
    """Фал-OPEN класса #29–#38: пустой ответ launchctl НЕ равен «загружено ноль агентов»."""
    m = manifest([agent("com.spa.agent_health")])
    found = ac.check_b1_fleet_vs_manifest(m, None, "launchctl недоступен")
    unmeasured = [f for f in found if f.key == "b1:fleet-unmeasured"]
    assert unmeasured and unmeasured[0].severity == ac.UNCHECKED
    assert not any(f.key.startswith("b1:active-not-loaded") for f in found), (
        "не измерив флот, нельзя утверждать, что агента в нём нет")


def test_read_fleet_refuses_to_call_empty_output_an_empty_fleet(monkeypatch):
    class _Proc:
        returncode = 0
        stdout = ""

    monkeypatch.setattr(ac.subprocess, "run", lambda *a, **k: _Proc())
    fleet, reason = ac.read_fleet()
    assert fleet is None, "пустой вывод = «не измерено», а не «агентов ноль»"
    assert "не дал ни одной разобранной строки" in reason


def test_read_fleet_reports_launchctl_failure(monkeypatch):
    def _boom(*a, **k):
        raise FileNotFoundError("launchctl")

    monkeypatch.setattr(ac.subprocess, "run", _boom)
    fleet, reason = ac.read_fleet()
    assert fleet is None and "launchctl недоступен" in reason


def test_read_fleet_keeps_only_spa_labels():
    fleet, _ = ac.read_fleet(launchctl("com.spa.x", "com.apple.something"))
    assert set(fleet) == {"com.spa.x"}


# ═══════════════════════════════════════════════════════════════════════════
# B2 — свежесть продуктов по SLO
# ═══════════════════════════════════════════════════════════════════════════
def _touch(root, rel, age_hours, now_ts):
    import os

    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}", encoding="utf-8")
    stamp = now_ts - age_hours * 3600.0
    os.utime(p, (stamp, stamp))
    return p


def test_b2_grossly_stale_registry_is_critical(tmp_path):
    """АВАРИЯ 2026-07-17→2026-08-05: реестр агентов протух 475ч при SLO 26ч (18×)."""
    now_ts = NOW.timestamp()
    _touch(tmp_path, "data/agent_registry.json", 475.9, now_ts)
    m = manifest([], artifacts=[{"path": "data/agent_registry.json", "producer": None,
                                 "consumers": [], "slo_hours": 26, "status": "active"}])
    found = ac.check_b2_artifact_freshness(m, tmp_path, now_ts)
    hit = [f for f in found if f.key == "b2:stale:data/agent_registry.json"]
    assert hit and hit[0].severity == ac.CRITICAL
    assert "брошенный продюсер" in hit[0].message


def test_b2_mild_staleness_is_warn_not_critical(tmp_path):
    """Контроль калибровки: пропущенный прогон ≠ брошенный продюсер."""
    now_ts = NOW.timestamp()
    _touch(tmp_path, "data/agent_health.json", 4.0, now_ts)
    m = manifest([], artifacts=[{"path": "data/agent_health.json", "producer": None,
                                 "consumers": [], "slo_hours": 3, "status": "active"}])
    found = ac.check_b2_artifact_freshness(m, tmp_path, now_ts)
    assert [f.severity for f in found] == [ac.WARN]


def test_b2_fresh_artifact_produces_no_finding(tmp_path):
    now_ts = NOW.timestamp()
    _touch(tmp_path, "data/agent_health.json", 1.0, now_ts)
    m = manifest([], artifacts=[{"path": "data/agent_health.json", "producer": None,
                                 "consumers": [], "slo_hours": 3, "status": "active"}])
    assert ac.check_b2_artifact_freshness(m, tmp_path, now_ts) == []


def test_b2_missing_artifact_is_critical_not_exempt(tmp_path):
    """«Никогда не производился» — худшая форма «не свежий», а не освобождение от проверки."""
    m = manifest([], artifacts=[{"path": "data/never_written.json",
                                 "producer": "com.spa.ghost", "consumers": [],
                                 "slo_hours": 26, "status": "active"}])
    found = ac.check_b2_artifact_freshness(m, tmp_path, NOW.timestamp())
    hit = [f for f in found if f.key == "b2:missing:data/never_written.json"]
    assert hit and hit[0].severity == ac.CRITICAL
    assert "com.spa.ghost" in hit[0].message


def test_b2_planned_artifact_is_not_yet_required(tmp_path):
    """Фазы 2–4 объявлены заранее — `planned` не обязан существовать сегодня."""
    m = manifest([], artifacts=[{"path": "data/loop_health.json", "producer": None,
                                 "consumers": [], "slo_hours": None, "status": "planned"}])
    assert ac.check_b2_artifact_freshness(m, tmp_path, NOW.timestamp()) == []


def test_b2_active_artifact_without_slo_cannot_pass_silently(tmp_path):
    m = manifest([], artifacts=[{"path": "data/x.json", "producer": None,
                                 "consumers": [], "slo_hours": None, "status": "active"}])
    found = ac.check_b2_artifact_freshness(m, tmp_path, NOW.timestamp())
    assert [f.key for f in found] == ["b2:no-slo:data/x.json"]


# ═══════════════════════════════════════════════════════════════════════════
# B3 — замыкание потребления
# ═══════════════════════════════════════════════════════════════════════════
def _io_manifest(consumers=("orchestrator_protocol",)):
    return manifest(
        [agent("com.spa.io_quant", role="analytics", consumer_required=True,
               produces=[{"artifact": "data/investment_os/quant.json", "slo_hours": 26}])],
        artifacts=[{"path": "data/investment_os/quant.json",
                    "producer": "com.spa.io_quant", "consumers": list(consumers),
                    "slo_hours": 26, "status": "active"}])


def test_b3_no_receipt_at_all_is_critical():
    """АВАРИЯ 2026-08-05: 12 io_* пишут честный продукт, которого не читает никто."""
    found = ac.check_b3_consumption_closure(_io_manifest(), [], "файла реситов нет", NOW)
    hit = [f for f in found if f.key == "b3:no-receipt:data/investment_os/quant.json"]
    assert hit and hit[0].severity == ac.CRITICAL
    assert hit[0].strength == ac.STRONG, "продукт без читателя — сильный сигнал, не стареет"


def test_b3_declared_consumer_without_receipt_is_not_enough():
    """«В манифесте написан потребитель» — мнение. Ресит — факт. Сторож требует факт."""
    found = ac.check_b3_consumption_closure(
        _io_manifest(consumers=("orchestrator_protocol", "digest_daily")), [], "", NOW)
    assert any(f.key.startswith("b3:no-receipt") for f in found)


def test_b3_no_declared_consumer_is_critical():
    found = ac.check_b3_consumption_closure(_io_manifest(consumers=()), [], "", NOW)
    hit = [f for f in found if f.key == "b3:no-consumer:data/investment_os/quant.json"]
    assert hit and hit[0].severity == ac.CRITICAL


def test_b3_fresh_receipt_closes_the_loop():
    """Контроль в обратную сторону: замкнутая петля НЕ даёт находки."""
    receipts = [{"artifact": "data/investment_os/quant.json", "consumer": "orchestrator_protocol",
                 "consumed_at": (NOW - timedelta(hours=2)).isoformat(),
                 "producer_generated_at": (NOW - timedelta(hours=3)).isoformat()}]
    assert ac.check_b3_consumption_closure(_io_manifest(), receipts, "", NOW) == []


def test_b3_stale_receipt_is_warn():
    """Прочитано неделю назад при суточном SLO — это архивирование, а не потребление."""
    receipts = [{"artifact": "data/investment_os/quant.json", "consumer": "orchestrator_protocol",
                 "consumed_at": (NOW - timedelta(hours=200)).isoformat()}]
    found = ac.check_b3_consumption_closure(_io_manifest(), receipts, "", NOW)
    hit = [f for f in found if f.key == "b3:receipt-stale:data/investment_os/quant.json"]
    assert hit and hit[0].severity == ac.WARN


def test_b3_unreadable_receipts_are_unchecked_not_pass():
    found = ac.check_b3_consumption_closure(_io_manifest(), None, "файл не читается", NOW)
    assert [f.severity for f in found] == [ac.UNCHECKED]
    assert "файл не читается" in found[0].message


def test_b3_consumer_required_without_any_product_is_critical():
    m = manifest([agent("com.spa.io_quant", consumer_required=True, produces=[])])
    found = ac.check_b3_consumption_closure(m, [], "", NOW)
    assert [f.key for f in found] == ["b3:required-without-product:com.spa.io_quant"]


def test_b3_product_missing_from_artifact_registry_is_critical():
    m = manifest([agent("com.spa.io_quant", consumer_required=True,
                        produces=[{"artifact": "data/investment_os/quant.json",
                                   "slo_hours": 26}])], artifacts=[])
    found = ac.check_b3_consumption_closure(m, [], "", NOW)
    assert [f.key for f in found] == ["b3:product-not-registered:data/investment_os/quant.json"]


@pytest.mark.parametrize("intent", ["retired", "designed", "unresolved"])
def test_b3_does_not_demand_a_reader_from_a_non_active_agent(intent):
    """Ретайрнутый ничего не пишет, designed ещё не запущен — требование читателя к ним
    было бы находкой, которую невозможно закрыть (мёртвый груз в очереди)."""
    m = _io_manifest()
    m["agents"][0]["intent"] = intent
    assert ac.check_b3_consumption_closure(m, [], "", NOW) == []


def test_b3_ignores_agents_without_consumer_required():
    m = manifest([agent("com.spa.agent_health",
                        produces=[{"artifact": "data/agent_health.json", "slo_hours": 3}])])
    assert ac.check_b3_consumption_closure(m, [], "", NOW) == []


def test_read_receipts_skips_broken_lines_without_losing_the_good_ones(tmp_path):
    p = tmp_path / ac.RECEIPTS_FILENAME
    p.write_text('{"artifact": "a", "consumed_at": "2026-08-05T10:00:00Z"}\n'
                 "не json\n\n"
                 '{"artifact": "b", "consumed_at": "2026-08-05T11:00:00Z"}\n',
                 encoding="utf-8")
    recs, reason = ac.read_receipts(tmp_path)
    assert [r["artifact"] for r in recs] == ["a", "b"]
    assert "1 строк реситов не разобрано" in reason


def test_read_receipts_missing_file_is_a_measured_fact_not_an_error(tmp_path):
    recs, reason = ac.read_receipts(tmp_path)
    assert recs == [] and "ни один потребитель ещё не отчитался" in reason


# ═══════════════════════════════════════════════════════════════════════════
# B4 — designed-дрейф
# ═══════════════════════════════════════════════════════════════════════════
def test_b4_designed_architecture_running_is_critical():
    """Спроектированное ≠ разрешённое: Head-of-Investment активируется только владельцем."""
    m = manifest([agent("com.spa.head_of_investment", intent="designed",
                        governed_by=["ADR-055"])])
    fleet, _ = ac.read_fleet(launchctl("com.spa.head_of_investment"))
    found = ac.check_b4_designed_drift(m, fleet)
    hit = [f for f in found if f.key.startswith("b4:designed-but-running")]
    assert hit and hit[0].severity == ac.CRITICAL
    assert "ADR-055" in hit[0].message


def test_b4_designed_but_not_running_is_the_intended_state():
    m = manifest([agent("com.spa.head_of_investment", intent="designed")])
    fleet, _ = ac.read_fleet(launchctl("com.spa.agent_health"))
    assert ac.check_b4_designed_drift(m, fleet) == []


def test_b4_unmeasured_fleet_with_designed_agents_is_unchecked():
    m = manifest([agent("com.spa.head_of_investment", intent="designed")])
    found = ac.check_b4_designed_drift(m, None, "launchctl недоступен")
    assert [f.severity for f in found] == [ac.UNCHECKED]


def test_b4_unmeasured_fleet_without_designed_agents_says_nothing():
    """Без designed-агентов измерять нечего — ложного «не измерено» тоже быть не должно."""
    assert ac.check_b4_designed_drift(manifest([agent("com.spa.x")]), None, "нет") == []


# ═══════════════════════════════════════════════════════════════════════════
# B5 — согласованность ролей/слоёв (ADR-004)
# ═══════════════════════════════════════════════════════════════════════════
def test_b5_dev_layer_agent_writing_product_artifact_is_critical():
    m = manifest([agent("com.spa.cc-kanban", layer="dev",
                        produces=[{"artifact": "data/investment_os/quant.json",
                                   "slo_hours": 26}])])
    found = ac.check_b5_role_layer_coherence(m)
    hit = [f for f in found if f.key.startswith("b5:dev-writes-product")]
    assert hit and hit[0].severity == ac.CRITICAL
    assert "ADR-004" in hit[0].message


def test_b5_product_layer_agent_writing_product_artifact_is_fine():
    m = manifest([agent("com.spa.io_quant", layer="product",
                        produces=[{"artifact": "data/investment_os/quant.json",
                                   "slo_hours": 26}])],
                 artifacts=[{"path": "data/investment_os/quant.json",
                             "producer": "com.spa.io_quant", "consumers": ["x"],
                             "slo_hours": 26, "status": "active"}])
    assert ac.check_b5_role_layer_coherence(m) == []


def test_b5_two_producers_for_one_artifact_is_critical():
    m = manifest([agent("com.spa.a", produces=[{"artifact": "data/x.json", "slo_hours": 3}]),
                  agent("com.spa.b", produces=[{"artifact": "data/x.json", "slo_hours": 3}])],
                 artifacts=[{"path": "data/x.json", "producer": "com.spa.a",
                             "consumers": ["y"], "slo_hours": 3, "status": "active"}])
    found = ac.check_b5_role_layer_coherence(m)
    hit = [f for f in found if f.key == "b5:multiple-producers:data/x.json"]
    assert hit and hit[0].severity == ac.CRITICAL


def test_b5_producer_mismatch_between_halves_of_the_manifest():
    m = manifest([agent("com.spa.a", produces=[])],
                 artifacts=[{"path": "data/x.json", "producer": "com.spa.a",
                             "consumers": ["y"], "slo_hours": 3, "status": "active"}])
    found = ac.check_b5_role_layer_coherence(m)
    assert [f.key for f in found] == ["b5:producer-mismatch:data/x.json"]


def test_b5_null_producer_with_a_claimant_is_reported():
    """`agent_registry.json` объявлен без продюсера намеренно — но если кто-то его заявит,
    половины манифеста разошлись, и это надо увидеть."""
    m = manifest([agent("com.spa.a", produces=[{"artifact": "data/agent_registry.json",
                                                "slo_hours": 26}])],
                 artifacts=[{"path": "data/agent_registry.json", "producer": None,
                             "consumers": ["z"], "slo_hours": 26, "status": "active"}])
    found = ac.check_b5_role_layer_coherence(m)
    assert [f.key for f in found] == ["b5:producer-null-but-claimed:data/agent_registry.json"]


def test_b5_null_producer_without_claimant_is_the_honest_declared_state():
    m = manifest([agent("com.spa.a")],
                 artifacts=[{"path": "data/agent_registry.json", "producer": None,
                             "consumers": ["z"], "slo_hours": 26, "status": "active"}])
    assert ac.check_b5_role_layer_coherence(m) == []


# ═══════════════════════════════════════════════════════════════════════════
# Старение слабых сигналов (ADR-066 P2)
# ═══════════════════════════════════════════════════════════════════════════
def test_weak_finding_ages_out_and_stops_holding_the_verdict():
    old = (NOW - timedelta(days=30)).isoformat()
    previous = {"findings": [{"key": "b1:intent-unresolved:com.spa.x", "first_seen": old}]}
    f = ac._f("B1", "b1:intent-unresolved:com.spa.x", ac.WARN, "com.spa.x", "…",
              strength=ac.WEAK)
    aged = ac.apply_aging([f], previous, NOW)
    assert aged[0].first_seen == old
    assert aged[0].aged_out is True
    assert ac._rollup(aged) == ac.OK, "устаревший слабый сигнал не держит вердикт красным"


def test_strong_finding_never_ages_out():
    old = (NOW - timedelta(days=365)).isoformat()
    previous = {"findings": [{"key": "b3:no-receipt:data/x.json", "first_seen": old}]}
    f = ac._f("B3", "b3:no-receipt:data/x.json", ac.CRITICAL, "data/x.json", "…")
    aged = ac.apply_aging([f], previous, NOW)
    assert aged[0].aged_out is False, "сильная находка не имеет права самопогаситься"
    assert ac._rollup(aged) == ac.CRITICAL


def test_weak_finding_inside_the_window_still_counts():
    recent = (NOW - timedelta(days=3)).isoformat()
    previous = {"findings": [{"key": "k", "first_seen": recent}]}
    f = ac._f("B1", "k", ac.WARN, "s", "…", strength=ac.WEAK)
    aged = ac.apply_aging([f], previous, NOW)
    assert aged[0].aged_out is False and ac._rollup(aged) == ac.WARN


def test_first_seen_is_stamped_for_a_brand_new_finding():
    f = ac._f("B1", "new-key", ac.WARN, "s", "…", strength=ac.WEAK)
    aged = ac.apply_aging([f], None, NOW)
    assert aged[0].first_seen == NOW.isoformat() and aged[0].aged_out is False


def test_broken_first_seen_does_not_silently_age_a_finding_out():
    previous = {"findings": [{"key": "k", "first_seen": "не-дата"}]}
    f = ac._f("B1", "k", ac.WARN, "s", "…", strength=ac.WEAK)
    aged = ac.apply_aging([f], previous, NOW)
    assert aged[0].aged_out is False, "нечитаемая отметка — не повод погасить сигнал"


# ═══════════════════════════════════════════════════════════════════════════
# Вердикт, коды возврата, отказ целиком
# ═══════════════════════════════════════════════════════════════════════════
def test_rollup_order_critical_beats_warn_beats_unchecked():
    assert ac._rollup([ac._f("B1", "a", ac.UNCHECKED, "s", "m"),
                       ac._f("B1", "b", ac.WARN, "s", "m"),
                       ac._f("B1", "c", ac.CRITICAL, "s", "m")]) == ac.CRITICAL
    assert ac._rollup([ac._f("B1", "a", ac.UNCHECKED, "s", "m"),
                       ac._f("B1", "b", ac.WARN, "s", "m")]) == ac.WARN
    assert ac._rollup([ac._f("B1", "a", ac.UNCHECKED, "s", "m")]) == ac.UNCHECKED
    assert ac._rollup([]) == ac.OK


def test_healthy_fleet_is_ok_and_exit_zero(tmp_path):
    """Контроль в обратную сторону: сторож, который всегда красный, — бесполезен."""
    now_ts = NOW.timestamp()
    _touch(tmp_path, "data/agent_health.json", 1.0, now_ts)
    ddir = tmp_path / "data"
    (ddir / ac.RECEIPTS_FILENAME).write_text(
        json.dumps({"artifact": "data/agent_health.json", "consumer": "digest_daily",
                    "consumed_at": (NOW - timedelta(hours=1)).isoformat()}) + "\n",
        encoding="utf-8")
    m = manifest([agent("com.spa.agent_health", consumer_required=True,
                        produces=[{"artifact": "data/agent_health.json", "slo_hours": 3}])],
                 artifacts=[{"path": "data/agent_health.json",
                             "producer": "com.spa.agent_health",
                             "consumers": ["digest_daily"], "slo_hours": 3,
                             "status": "active"}])
    doc = run(tmp_path, m, fleet_str=launchctl("com.spa.agent_health"), data_dir=ddir)
    assert doc["overall"] == ac.OK, doc["findings"]
    assert ac._EXIT_CODES[doc["overall"]] == 0
    assert doc["counts"]["critical"] == 0


def test_exit_codes_are_zero_one_two():
    assert ac._EXIT_CODES[ac.OK] == 0
    assert ac._EXIT_CODES[ac.WARN] == 1
    assert ac._EXIT_CODES[ac.UNCHECKED] == 1, "«не измерено» — не зачёт"
    assert ac._EXIT_CODES[ac.CRITICAL] == 2


def _critical_without_fleet():
    """CRITICAL, не требующий измерения флота (в тестах launchctl недоступен по построению)."""
    return manifest([agent("com.spa.x")],
                    artifacts=[{"path": "data/never_written.json", "producer": "com.spa.x",
                                "consumers": ["y"], "slo_hours": 26, "status": "active"}])


def test_cli_returns_two_on_critical(tmp_path):
    write_manifest(tmp_path, _critical_without_fleet())
    (tmp_path / "data").mkdir()
    code = ac.main(["--manifest", str(tmp_path / "architecture" / "manifest.json"),
                    "--repo-root", str(tmp_path), "--data-dir", str(tmp_path / "data"),
                    "--no-write"])
    assert code == 2


def test_cli_launchd_mode_does_not_report_findings_as_a_process_failure(tmp_path):
    """Под launchd находка — содержание отчёта, а не сбой агента.

    Возвращая 2, сторож вечно висел бы в agent_health как `last_exit=2` (ровно так там
    сейчас числится daily_backup) — и настоящая поломка сторожа стала бы неотличима от
    честной находки, а жёлтый флот приучил бы всех себя не читать.
    """
    write_manifest(tmp_path, _critical_without_fleet())
    (tmp_path / "data").mkdir()
    args = ["--manifest", str(tmp_path / "architecture" / "manifest.json"),
            "--repo-root", str(tmp_path), "--data-dir", str(tmp_path / "data"),
            "--no-write", "--exit-zero-on-findings"]
    assert ac.main(args) == 0


def test_cli_launchd_mode_still_reports_the_guard_s_own_crash(tmp_path, monkeypatch):
    """…но собственная поломка сторожа обязана остаться ненулевой — иначе он умрёт молча."""
    monkeypatch.setattr(ac, "check_b5_role_layer_coherence",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("бум")))
    write_manifest(tmp_path, manifest([agent("com.spa.x")]))
    (tmp_path / "data").mkdir()
    code = ac.main(["--manifest", str(tmp_path / "architecture" / "manifest.json"),
                    "--repo-root", str(tmp_path), "--data-dir", str(tmp_path / "data"),
                    "--no-write", "--exit-zero-on-findings"])
    assert code == 2


def test_unreadable_manifest_is_critical_not_ok(tmp_path):
    """Без конституции сверять не с чем — и это отказ, а не «нечего проверять»."""
    p = tmp_path / "architecture" / "manifest.json"
    p.parent.mkdir(parents=True)
    p.write_text("{ это не json", encoding="utf-8")
    (tmp_path / "data").mkdir()
    doc = ac.run_conformance(repo_root=tmp_path, data_dir=tmp_path / "data",
                             launchctl_output=launchctl("com.spa.x"), now=NOW, write=False)
    assert doc["overall"] == ac.CRITICAL
    assert any(f["key"] == "b0:manifest-unreadable" for f in doc["findings"])


def test_empty_manifest_is_critical_not_ok(tmp_path):
    """Ноль объявленных агентов = «читали не то», а не «архитектура соблюдена»."""
    (tmp_path / "data").mkdir()
    doc = run(tmp_path, manifest([]), fleet_str=launchctl("com.spa.x"))
    assert doc["overall"] == ac.CRITICAL


def test_checker_crash_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "check_b2_artifact_freshness",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("бум")))
    doc = run(tmp_path, manifest([agent("com.spa.x")]), fleet_str=launchctl("com.spa.x"))
    assert doc["overall"] == ac.CRITICAL
    assert any("сам сторож упал" in f["message"] for f in doc["findings"])


def test_report_is_written_atomically_and_reloads(tmp_path):
    ddir = tmp_path / "data"
    ddir.mkdir(parents=True)
    m = manifest([agent("com.spa.x", intent="unresolved", reboot_safe=False)])
    doc = run(tmp_path, m, fleet_str=launchctl(), data_dir=ddir, write=True)
    saved = json.loads((ddir / ac.STATE_FILENAME).read_text(encoding="utf-8"))
    assert saved["overall"] == doc["overall"]
    assert saved["monitor"] == "architecture_conformance"

    # Второй прогон через 30 дней обязан ПОДХВАТИТЬ first_seen из первого и состарить слабое.
    later = NOW + timedelta(days=30)
    doc2 = ac.run_conformance(repo_root=tmp_path, data_dir=ddir,
                              launchctl_output=launchctl(), now=later, write=False)
    weak = [f for f in doc2["findings"] if f["key"] == "b1:intent-unresolved:com.spa.x"]
    assert weak and weak[0]["first_seen"] == NOW.isoformat()
    assert weak[0]["aged_out"] is True


def test_unwritable_data_dir_does_not_crash_the_monitor(tmp_path):
    m = manifest([agent("com.spa.x")])
    write_manifest(tmp_path, m)
    doc = ac.run_conformance(repo_root=tmp_path, data_dir=tmp_path / "нет" / "такого",
                             launchctl_output=launchctl("com.spa.x"), now=NOW, write=True)
    assert doc["overall"] in (ac.OK, ac.WARN, ac.UNCHECKED, ac.CRITICAL)


def test_report_lists_unchecked_separately(tmp_path):
    doc = run(tmp_path, manifest([agent("com.spa.x")]), fleet_str=None)
    assert doc["fleet_loaded"] is None
    assert any(u["check"] == "B1" for u in doc["unchecked"])


def test_format_report_text_marks_unmeasured_fleet_verbatim(tmp_path):
    doc = run(tmp_path, manifest([agent("com.spa.x")]), fleet_str=None)
    text = ac.format_report_text(doc)
    assert "НЕ ИЗМЕРЕНО" in text, "число «0 во флоте» соврало бы о том, чего не мерили"


def test_aged_out_findings_are_kept_in_the_file_but_out_of_the_text(tmp_path):
    old = (NOW - timedelta(days=40)).isoformat()
    ddir = tmp_path / "data"
    ddir.mkdir(parents=True)
    (ddir / ac.STATE_FILENAME).write_text(json.dumps(
        {"findings": [{"key": "b1:intent-unresolved:com.spa.x", "first_seen": old}]}),
        encoding="utf-8")
    doc = run(tmp_path, manifest([agent("com.spa.x", intent="unresolved", reboot_safe=False)]),
              fleet_str=launchctl(), data_dir=ddir)
    assert doc["counts"]["aged_out"] == 1
    assert any(f["aged_out"] for f in doc["findings"]), "находка остаётся в отчёте честно"
    assert "com.spa.x" not in ac.format_report_text(doc)


# ═══════════════════════════════════════════════════════════════════════════
# Алерт — только через push_policy
# ═══════════════════════════════════════════════════════════════════════════
def test_alert_key_is_on_the_closed_tier1_whitelist():
    from spa_core.telegram import push_policy

    assert "architecture_conformance_critical" in push_policy.TIER1_WHITELIST, (
        "не-whitelisted ключ молча уезжает в дайджест — тревога не дошла бы никогда")


def test_alert_pushes_on_critical_with_a_set_fingerprint(monkeypatch):
    calls = {}

    class _FakePolicy:
        @staticmethod
        def push_critical(key, severity, title, body, **kw):
            calls["push"] = (key, severity, title, kw.get("dedup_key"))
            return True

        @staticmethod
        def resolve(*a, **k):
            calls["resolve"] = a
            return True

    import sys
    import types

    mod = types.ModuleType("spa_core.telegram")
    mod.push_policy = _FakePolicy
    monkeypatch.setitem(sys.modules, "spa_core.telegram", mod)

    doc = {"overall": ac.CRITICAL,
           "findings": [{"key": "b3:no-receipt:b", "severity": ac.CRITICAL, "aged_out": False},
                        {"key": "b1:x:a", "severity": ac.CRITICAL, "aged_out": False},
                        {"key": "aged", "severity": ac.CRITICAL, "aged_out": True}],
           "counts": {}}
    assert ac._alert(doc) is True
    key, severity, _title, dedup = calls["push"]
    assert key == "architecture_conformance_critical" and severity == ac.CRITICAL
    assert dedup == "b1:x:a|b3:no-receipt:b", "отпечаток = отсортированное МНОЖЕСТВО находок"
    assert "resolve" not in calls


def test_alert_resolves_when_no_longer_critical(monkeypatch):
    calls = {}

    class _FakePolicy:
        @staticmethod
        def push_critical(*a, **k):
            calls["push"] = a
            return True

        @staticmethod
        def resolve(key, *a, **k):
            calls["resolve"] = key
            return True

    import sys
    import types

    mod = types.ModuleType("spa_core.telegram")
    mod.push_policy = _FakePolicy
    monkeypatch.setitem(sys.modules, "spa_core.telegram", mod)

    assert ac._alert({"overall": ac.WARN, "findings": [], "counts": {}}) is True
    assert calls["resolve"] == "architecture_conformance_critical"
    assert "push" not in calls


def test_alert_never_raises_when_push_policy_is_broken(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "spa_core.telegram", None)
    assert ac._alert({"overall": ac.CRITICAL, "findings": [], "counts": {}}) is False


def test_run_does_not_alert_unless_asked(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(ac, "_alert", lambda doc: called.append(doc))
    run(tmp_path, manifest([agent("com.spa.x")]), fleet_str=launchctl())
    assert called == [], "молчаливый прогон не имеет права слать в Telegram"


# ═══════════════════════════════════════════════════════════════════════════
# Инварианты проекта
# ═══════════════════════════════════════════════════════════════════════════
def test_module_declares_llm_forbidden():
    import inspect

    src = inspect.getsource(ac)
    assert "LLM_FORBIDDEN" in src
    for banned in ("openai", "anthropic", "claude_client", "ask_router"):
        assert banned not in src, "монитор — LLM-free зона (инвариант #3)"


def test_module_uses_only_stdlib_plus_spa_core():
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(ac))
    third_party = {"requests", "numpy", "pandas", "scipy", "yaml", "aiohttp", "httpx"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [(node.module or "").split(".")[0]]
        else:
            continue
        assert not (set(names) & third_party), "только stdlib в рантайме (инвариант #4)"


def test_writes_go_through_atomic_save():
    import inspect

    src = inspect.getsource(ac)
    assert "atomic_save" in src
    assert 'open(' not in src.split("def run_conformance")[1].split("def _alert")[0].replace(
        "with open(ddir / STATE_FILENAME, encoding=\"utf-8\") as fh:", ""), (
        "state-файл пишется только атомарно (инвариант #5)")


def test_launchctl_parsing_is_not_a_second_copy():
    """Урок цикла #47: близнец-арифметика чинится в одном месте, а живёт в двух."""
    import inspect

    src = inspect.getsource(ac)
    assert "from spa_core.monitoring.agent_health_monitor import parse_launchctl_list" in src
    assert "split(\"\\t\")" not in src, "разбор launchctl не дублируется"


@pytest.mark.parametrize("check,fn", [
    ("B1", ac.check_b1_fleet_vs_manifest),
    ("B2", ac.check_b2_artifact_freshness),
    ("B3", ac.check_b3_consumption_closure),
    ("B4", ac.check_b4_designed_drift),
    ("B5", ac.check_b5_role_layer_coherence),
])
def test_every_adr_066_check_exists_and_labels_its_findings(check, fn):
    """Все пять проверок ADR-066 реализованы, и каждая находка помечена своей буквой —
    иначе мост «находка→карточка» (Фаза 3) не сможет маршрутизировать по проверке."""
    assert callable(fn) and (fn.__doc__ or "").strip(), "у проверки должно быть обоснование"
    prefixes = {ac.check_b1_fleet_vs_manifest: "b1:", ac.check_b2_artifact_freshness: "b2:",
                ac.check_b3_consumption_closure: "b3:", ac.check_b4_designed_drift: "b4:",
                ac.check_b5_role_layer_coherence: "b5:"}
    import inspect

    src = inspect.getsource(fn)
    assert '"{}"'.format(check) in src, "находки проверки помечаются её буквой"
    assert '"{}'.format(prefixes[fn]) in src, "ключ находки начинается с префикса проверки"
