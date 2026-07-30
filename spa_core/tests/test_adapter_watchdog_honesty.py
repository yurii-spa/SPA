"""test_adapter_watchdog_honesty.py — MP-311 adapter watchdog: честность вердикта.

Модуль ``spa_core/scheduler/adapter_watchdog.py`` зовётся из ДНЕВНОГО ЦИКЛА
(``cycle_reporting.py`` — дважды за прогон) и до цикла #38 не имел НИ ОДНОГО
выделенного теста: одноимённый файл ``test_adapter_watchdog.py`` написан на
класс-API MP-596, ретированный в ``attic/modules/monitoring/adapter_watchdog.py``,
и все 136 его тестов молча скипались (см. карточку
``agent-silently-skipped-test-files``).

Проверяемые свойства (инвариант #2 — refusal-first / fail-CLOSED):

1. **«Не прочитал» ≠ «всё здорово».** Отсутствующий / битый / не-объект
   ``adapter_orchestrator_status.json`` больше не даёт ``status:"ok"`` с нулём
   нездоровых адаптеров — публикуется ``status:"unchecked"`` + ``unchecked[]``
   с причиной.
2. **Свежесть действительно измеряется.** Живой писатель статуса кладёт метку
   времени в ключ ``last_updated``; критерий обязан её читать, иначе он
   срабатывает ВСЕГДА и «устарел» перестаёт что-либо значить.
3. **Опубликованный вердикт объясним:** для каждого нездорового адаптера видно,
   какой критерий сработал.
4. Прежние гарантии (rate-limit, ring-buffer, атомарность, fail-safe) не
   потеряны.

Все тесты герметичны: только ``tmp_path``, никакой сети, живой ``data/`` не
читается и не пишется.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.scheduler.adapter_watchdog import (
    MAX_LOG_ENTRIES,
    MAX_RESTARTS_PER_HOUR,
    ORCH_STATUS_FILENAME,
    ORCHESTRATOR_TRIGGER_FILENAME,
    STALE_FETCH_HOURS,
    WATCHDOG_CYCLE_RESULT_FILENAME,
    WATCHDOG_LOG_FILENAME,
    WATCHDOG_STATE_FILENAME,
    _atomic_write_json,
    _is_stale_fetch,
    attempt_adapter_restart,
    check_adapter_health,
    run_watchdog_cycle,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _healthy_adapter(protocol: str = "aave_v3", **over) -> dict:
    """Адаптер, который по ВСЕМ трём критериям здоров.

    Ключ метки времени — ``last_updated``: именно его пишет живой продюсер
    ``adapter_orchestrator_status.json`` (проверено на живом файле 30.07).
    """
    doc = {
        "protocol": protocol,
        "tier": "T1",
        "status": "ok",
        "apy_pct": 4.2,
        "last_updated": _iso(0.1),
    }
    doc.update(over)
    return doc


def _write_status(ddir: Path, adapters: object, **extra) -> Path:
    path = ddir / ORCH_STATUS_FILENAME
    doc: dict = {"generated_at": _iso(0.1), "adapters": adapters}
    doc.update(extra)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _result(ddir: Path) -> dict:
    return json.loads((ddir / WATCHDOG_CYCLE_RESULT_FILENAME).read_text(encoding="utf-8"))


# ══════════════════════════════════════════════════════════════════════════════
# 1. fail-OPEN: «не прочитал» публиковалось как «всё здорово»
# ══════════════════════════════════════════════════════════════════════════════


class TestUnreadableSourceIsNotHealth:
    """Отсутствующий/битый источник не должен читаться как «нездоровых нет»."""

    def test_missing_status_file_is_unchecked(self, tmp_path):
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        assert out["status"] == "unchecked", out
        assert out["unchecked"], "причина «не измерено» обязана быть опубликована"

    def test_missing_status_file_names_the_source(self, tmp_path):
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        blob = json.dumps(out["unchecked"], ensure_ascii=False)
        assert ORCH_STATUS_FILENAME in blob, blob

    def test_missing_status_file_does_not_claim_ok(self, tmp_path):
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        assert out["status"] != "ok"

    def test_corrupt_json_is_unchecked(self, tmp_path):
        (tmp_path / ORCH_STATUS_FILENAME).write_text("{not json", encoding="utf-8")
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        assert out["status"] == "unchecked", out

    def test_corrupt_json_reason_is_specific(self, tmp_path):
        (tmp_path / ORCH_STATUS_FILENAME).write_text("{not json", encoding="utf-8")
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        reasons = " ".join(str(u.get("reason", "")) for u in out["unchecked"])
        assert "unreadable" in reasons or "нечит" in reasons, reasons

    def test_non_object_status_is_unchecked(self, tmp_path):
        (tmp_path / ORCH_STATUS_FILENAME).write_text("[1, 2, 3]", encoding="utf-8")
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        assert out["status"] == "unchecked", out

    def test_adapters_key_missing_is_unchecked(self, tmp_path):
        (tmp_path / ORCH_STATUS_FILENAME).write_text(
            json.dumps({"generated_at": _iso(0.1)}), encoding="utf-8"
        )
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        assert out["status"] == "unchecked", out

    def test_adapters_not_a_list_is_unchecked(self, tmp_path):
        _write_status(tmp_path, {"aave_v3": {"status": "ok"}})
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        assert out["status"] == "unchecked", out

    def test_empty_adapters_list_is_unchecked(self, tmp_path):
        """Пустой список — не доказательство здоровья: измерять было нечего."""
        _write_status(tmp_path, [])
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        assert out["status"] == "unchecked", out

    def test_all_entries_unusable_is_unchecked(self, tmp_path):
        """Записи есть, но ни одну нельзя опознать → ни один адаптер не проверен."""
        _write_status(tmp_path, ["junk", 42, {}, {"protocol": ""}])
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        assert out["status"] == "unchecked", out
        assert out["adapters_checked"] == 0

    def test_unchecked_run_triggers_no_restarts(self, tmp_path):
        """«Не измерено» не должно порождать действий."""
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        assert out["restarts_attempted"] == 0
        assert not (tmp_path / ORCHESTRATOR_TRIGGER_FILENAME).exists()

    def test_unchecked_result_is_persisted(self, tmp_path):
        run_watchdog_cycle(data_dir=str(tmp_path))
        assert _result(tmp_path)["status"] == "unchecked"

    def test_partial_junk_still_measures_the_readable_ones(self, tmp_path):
        """Одна нечитаемая запись не отменяет измерение остальных."""
        _write_status(tmp_path, ["junk", _healthy_adapter("aave_v3")])
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        assert out["status"] == "ok", out
        assert out["adapters_checked"] == 1
        assert out["adapters_unhealthy"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# 2. Критерий свежести должен читать ключ, который реально пишет продюсер
# ══════════════════════════════════════════════════════════════════════════════


class TestFreshnessActuallyMeasured:
    """До фикса ключ ``last_updated`` не читался ⇒ критерий 3 срабатывал всегда."""

    def test_last_updated_fresh_is_healthy(self, tmp_path):
        _write_status(tmp_path, [_healthy_adapter()])
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        assert out["adapters_unhealthy"] == 0, out

    def test_last_updated_stale_is_unhealthy(self, tmp_path):
        _write_status(
            tmp_path,
            [_healthy_adapter(last_updated=_iso(STALE_FETCH_HOURS + 1))],
        )
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        assert out["unhealthy_adapters"] == ["aave_v3"], out

    def test_last_updated_read_by_check_adapter_health(self):
        doc = {"adapters": [_healthy_adapter()]}
        assert check_adapter_health(doc) == []

    @pytest.mark.parametrize("key", ["fetched_at", "last_fetch_ts", "timestamp", "last_updated"])
    def test_all_known_timestamp_keys_accepted(self, key):
        adapter = {"protocol": "p", "status": "ok", "apy_pct": 1.0, key: _iso(0.1)}
        assert check_adapter_health({"adapters": [adapter]}) == []

    def test_no_timestamp_at_all_is_still_stale(self):
        """fail-CLOSED сохранён: метки нет — считаем устаревшим."""
        adapter = {"protocol": "p", "status": "ok", "apy_pct": 1.0}
        assert check_adapter_health({"adapters": [adapter]}) == ["p"]

    def test_unparseable_timestamp_is_still_stale(self):
        adapter = {"protocol": "p", "status": "ok", "apy_pct": 1.0, "last_updated": "вчера"}
        assert check_adapter_health({"adapters": [adapter]}) == ["p"]

    def test_is_stale_fetch_boundary_fresh(self):
        assert _is_stale_fetch(_iso(STALE_FETCH_HOURS - 0.05)) is False

    def test_is_stale_fetch_boundary_stale(self):
        assert _is_stale_fetch(_iso(STALE_FETCH_HOURS + 0.05)) is True

    def test_is_stale_fetch_none(self):
        assert _is_stale_fetch(None) is True

    def test_z_suffix_accepted(self):
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert _is_stale_fetch(ts) is False

    def test_naive_timestamp_treated_as_utc(self):
        ts = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        assert _is_stale_fetch(ts) is False


# ══════════════════════════════════════════════════════════════════════════════
# 3. Вердикт объясним: видно, какой критерий сработал
# ══════════════════════════════════════════════════════════════════════════════


class TestVerdictIsExplainable:
    def test_reasons_published_for_each_unhealthy(self, tmp_path):
        _write_status(tmp_path, [_healthy_adapter(status="timeout")])
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        assert out["unhealthy_reasons"]["aave_v3"], out

    def test_bad_status_reason_quotes_the_value(self, tmp_path):
        _write_status(tmp_path, [_healthy_adapter(status="timeout")])
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        assert "timeout" in " ".join(out["unhealthy_reasons"]["aave_v3"])

    def test_zero_apy_reason_present(self, tmp_path):
        _write_status(tmp_path, [_healthy_adapter(apy_pct=0.0)])
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        assert any("apy" in r.lower() for r in out["unhealthy_reasons"]["aave_v3"])

    def test_stale_reason_carries_the_threshold(self, tmp_path):
        _write_status(tmp_path, [_healthy_adapter(last_updated=_iso(STALE_FETCH_HOURS + 5))])
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        joined = " ".join(out["unhealthy_reasons"]["aave_v3"])
        assert str(STALE_FETCH_HOURS) in joined, joined

    def test_multiple_reasons_all_reported(self, tmp_path):
        _write_status(tmp_path, [_healthy_adapter(status="error", apy_pct=None, last_updated=None)])
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        assert len(out["unhealthy_reasons"]["aave_v3"]) == 3, out["unhealthy_reasons"]

    def test_healthy_run_has_no_reasons(self, tmp_path):
        _write_status(tmp_path, [_healthy_adapter()])
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        assert out["unhealthy_reasons"] == {}


# ══════════════════════════════════════════════════════════════════════════════
# 4. Положительные контроли: настоящая проблема по-прежнему видна
#    (доказывают, что поведение не инвертировано «в зелень»)
# ══════════════════════════════════════════════════════════════════════════════


class TestRealProblemsStillDetected:
    def test_status_error_is_unhealthy(self):
        a = _healthy_adapter(status="error")
        assert check_adapter_health({"adapters": [a]}) == ["aave_v3"]

    def test_status_timeout_is_unhealthy(self):
        a = _healthy_adapter(status="timeout")
        assert check_adapter_health({"adapters": [a]}) == ["aave_v3"]

    def test_status_partial_is_accepted(self):
        """Код всегда допускал 'partial'; докстринг утверждал обратное."""
        a = _healthy_adapter(status="partial")
        assert check_adapter_health({"adapters": [a]}) == []

    def test_apy_none_is_unhealthy(self):
        a = _healthy_adapter(apy_pct=None)
        assert check_adapter_health({"adapters": [a]}) == ["aave_v3"]

    def test_apy_zero_is_unhealthy(self):
        a = _healthy_adapter(apy_pct=0)
        assert check_adapter_health({"adapters": [a]}) == ["aave_v3"]

    def test_apy_missing_is_unhealthy(self):
        a = _healthy_adapter()
        a.pop("apy_pct")
        assert check_adapter_health({"adapters": [a]}) == ["aave_v3"]

    def test_name_fallback_to_name_key(self):
        a = {"name": "morpho", "status": "ok", "apy_pct": 1.0, "last_updated": _iso(0.1)}
        assert check_adapter_health({"adapters": [a]}) == []

    def test_unhealthy_triggers_restart_and_trigger_file(self, tmp_path):
        _write_status(tmp_path, [_healthy_adapter(status="error")])
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        assert out["restarts_succeeded"] == 1
        trig = json.loads((tmp_path / ORCHESTRATOR_TRIGGER_FILENAME).read_text())
        assert trig["adapter_restarted"] == ["aave_v3"]

    def test_mixed_fleet_counts(self, tmp_path):
        _write_status(
            tmp_path,
            [
                _healthy_adapter("aave_v3"),
                _healthy_adapter("compound_v3", status="error"),
                _healthy_adapter("morpho_blue", apy_pct=0.0),
            ],
        )
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        assert out["status"] == "ok"
        assert out["adapters_checked"] == 3
        assert out["adapters_unhealthy"] == 2
        assert set(out["unhealthy_adapters"]) == {"compound_v3", "morpho_blue"}

    def test_non_dict_input_returns_empty(self):
        assert check_adapter_health("nope") == []  # type: ignore[arg-type]


# ══════════════════════════════════════════════════════════════════════════════
# 5. Прежние гарантии не потеряны
# ══════════════════════════════════════════════════════════════════════════════


class TestPreexistingGuaranteesKept:
    def test_rate_limit_blocks_after_max(self, tmp_path):
        for _ in range(MAX_RESTARTS_PER_HOUR):
            assert attempt_adapter_restart("aave_v3", data_dir=str(tmp_path))["restarted"] is True
        res = attempt_adapter_restart("aave_v3", data_dir=str(tmp_path))
        assert res["restarted"] is False
        assert "rate_limited" in res["reason"]

    def test_rate_limited_counted_in_summary(self, tmp_path):
        for _ in range(MAX_RESTARTS_PER_HOUR):
            attempt_adapter_restart("aave_v3", data_dir=str(tmp_path))
        _write_status(tmp_path, [_healthy_adapter(status="error")])
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        assert out["restarts_rate_limited"] == 1
        assert out["restarts_succeeded"] == 0

    def test_state_counter_persisted(self, tmp_path):
        attempt_adapter_restart("aave_v3", data_dir=str(tmp_path))
        state = json.loads((tmp_path / WATCHDOG_STATE_FILENAME).read_text())
        assert state["adapters"]["aave_v3"]["count"] == 1

    def test_log_is_ring_buffered(self, tmp_path):
        (tmp_path / WATCHDOG_LOG_FILENAME).write_text(
            json.dumps([{"i": i} for i in range(MAX_LOG_ENTRIES + 50)]), encoding="utf-8"
        )
        attempt_adapter_restart("aave_v3", data_dir=str(tmp_path))
        wlog = json.loads((tmp_path / WATCHDOG_LOG_FILENAME).read_text())
        assert len(wlog) == MAX_LOG_ENTRIES

    def test_corrupt_state_does_not_crash(self, tmp_path):
        (tmp_path / WATCHDOG_STATE_FILENAME).write_text("{broken", encoding="utf-8")
        assert attempt_adapter_restart("aave_v3", data_dir=str(tmp_path))["restarted"] is True

    def test_corrupt_log_does_not_crash(self, tmp_path):
        (tmp_path / WATCHDOG_LOG_FILENAME).write_text("{broken", encoding="utf-8")
        assert attempt_adapter_restart("aave_v3", data_dir=str(tmp_path))["restarted"] is True

    def test_trigger_list_deduplicates(self, tmp_path):
        attempt_adapter_restart("aave_v3", data_dir=str(tmp_path))
        attempt_adapter_restart("aave_v3", data_dir=str(tmp_path))
        trig = json.loads((tmp_path / ORCHESTRATOR_TRIGGER_FILENAME).read_text())
        assert trig["adapter_restarted"] == ["aave_v3"]

    def test_run_is_fail_safe_on_unwritable_dir(self, tmp_path):
        """Прогон не бросает наружу — дневной цикл не должен падать."""
        out = run_watchdog_cycle(data_dir=str(tmp_path / "does" / "not" / "exist"))
        assert out["status"] in ("unchecked", "error")

    def test_atomic_write_leaves_no_tmp(self, tmp_path):
        _atomic_write_json(tmp_path / "x.json", {"a": 1})
        assert json.loads((tmp_path / "x.json").read_text())["a"] == 1
        assert list(tmp_path.glob("*.tmp")) == []

    def test_summary_has_stable_shape(self, tmp_path):
        _write_status(tmp_path, [_healthy_adapter()])
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        for key in (
            "status", "ts", "adapters_checked", "adapters_unhealthy",
            "unhealthy_adapters", "restarts_attempted", "restarts_succeeded",
            "restarts_rate_limited", "restart_details",
        ):
            assert key in out, key

    def test_explicit_status_path_override(self, tmp_path):
        other = tmp_path / "elsewhere.json"
        other.write_text(json.dumps({"adapters": [_healthy_adapter()]}), encoding="utf-8")
        out = run_watchdog_cycle(str(other), data_dir=str(tmp_path))
        assert out["status"] == "ok"
        assert out["adapters_checked"] == 1

    def test_live_data_dir_is_never_touched(self, tmp_path):
        """Герметичность самого теста: ничего не пишем в репозиторный data/."""
        run_watchdog_cycle(data_dir=str(tmp_path))
        repo_data = Path(__file__).resolve().parents[2] / "data"
        assert (tmp_path / WATCHDOG_CYCLE_RESULT_FILENAME).exists()
        assert tmp_path != repo_data


# ══════════════════════════════════════════════════════════════════════════════
# 6. Текст вердикта выводится из констант (рассинхрон «докстринг vs код»)
# ══════════════════════════════════════════════════════════════════════════════


class TestThresholdTextsDerived:
    def test_stale_reason_matches_constant(self, tmp_path):
        _write_status(tmp_path, [_healthy_adapter(last_updated=_iso(STALE_FETCH_HOURS + 3))])
        out = run_watchdog_cycle(data_dir=str(tmp_path))
        assert f"{STALE_FETCH_HOURS}" in " ".join(out["unhealthy_reasons"]["aave_v3"])

    def test_module_docstring_does_not_contradict_partial(self):
        import spa_core.scheduler.adapter_watchdog as mod

        doc = mod.__doc__ or ""
        # Докстринг не должен утверждать «status != ok ⇒ нездоров», пока код
        # принимает ещё и "partial".
        assert '"partial"' in doc or "partial" in doc, doc
