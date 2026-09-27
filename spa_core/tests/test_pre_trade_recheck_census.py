"""Приёмка прибора `pre_trade_recheck_census` (критерий §49 `Pre-trade safety`).

Каждый тест — либо воспроизведение настоящего исхода живой цепочки аудита, либо
контроль ОДНОГО звена в обратную сторону, и звено названо в имени теста.

FROZEN-DATE-OK: injected-clock — часы прибора инъектируются аргументом `now=`
(`run_census(..., now=_NOW)`), а все отметки времени цепочки задаются фикстурой
относительно того же якоря `_NOW`. Обе стороны закреплены: тест не зависит ни от
календаря, ни от длительности прогона. Литеральная дата здесь — ПРЕДМЕТ замера
(окно «предложение→исполнение» считается по отметкам самой цепочки), а не
окружение.
"""

# FROZEN-DATE-OK: injected-clock — часы прибора инъектируются аргументом
# (`run_census(..., now=_NOW)`, `census.run(root=..., now=_NOW)`), а все отметки
# времени цепочки фикстура выводит от ТОГО ЖЕ якоря `_NOW` через timedelta.
# Закреплены обе стороны: ни календарь, ни длительность прогона на вердикт не
# влияют, и это проверено тестом `test_window_is_measured_from_the_chain_...`.

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import pre_trade_recheck_census as census

#: Якорь времени. Всё, что тест подаёт прибору, происходит от него — и он же
#: передаётся прибору аргументом, поэтому стенных часов в тесте нет ни одних.
_NOW = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)


# ── фикстуры цепочки ────────────────────────────────────────────────────────

def _event(event_id: str, event_type: str, ts: datetime, snapshot_id: str,
           prev: str | None = None, data: dict | None = None) -> dict:
    return {"event_id": event_id, "correlation_id": f"corr-{event_id}",
            "snapshot_id": snapshot_id, "event_type": event_type,
            "timestamp": ts.isoformat(), "data": (data or {}),
            "prev_event_id": prev}


def _chain(*, exec_snapshot: str | None = None, window_s: float = 0.6,
           recheck: str | None = None, ttl: bool = False,
           trade_id: str = "T034", tag: str = "a") -> list[dict]:
    """Одна живая цепочка: предложение → вердикт → исполнение.

    ``exec_snapshot=None`` воспроизводит ЖИВОЙ исход: исполнение стои́т на том же
    наблюдении, что и предложение.
    """
    prop_ts = _NOW - timedelta(hours=1)
    snap = f"2026-09-27:{tag}snapshot"
    rows = [_event(f"{tag}-prop", census.EVENT_PROPOSAL, prop_ts, snap,
                   data={"valid_until": "x"} if ttl else {})]
    prev = f"{tag}-prop"
    if recheck:
        rows.append(_event(f"{tag}-re", recheck, prop_ts + timedelta(seconds=0.1),
                           snap, prev=prev))
        prev = f"{tag}-re"
    rows.append(_event(f"{tag}-verdict", census.EVENT_VERDICT,
                       prop_ts + timedelta(seconds=0.2), snap, prev=prev))
    rows.append(_event(f"{tag}-exec", census.EVENT_EXECUTED,
                       prop_ts + timedelta(seconds=window_s),
                       exec_snapshot if exec_snapshot is not None else snap,
                       prev=f"{tag}-verdict", data={"trade_id": trade_id}))
    return rows


def _write(data_dir: Path, rows: list[dict]) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / census.CHAIN_FILENAME
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _run(data_dir: Path, **kw):
    kw.setdefault("now", _NOW)
    return census.run_census(data_dir, **kw)


# ── ЖИВОЙ ИСХОД ─────────────────────────────────────────────────────────────

def test_live_shape_same_snapshot_is_no_recheck(tmp_path):
    """Замер 27.09: исполнение стои́т на ТОМ ЖЕ наблюдении ⇒ второго взгляда нет."""
    _write(tmp_path / "data", _chain())
    report = _run(tmp_path / "data")
    assert report["measured"] is True
    assert report["status"] == census.STATUS_WARNING
    assert report["no_recheck"] == 1
    assert report["recheck_present"] == 0
    assert report["findings"][0]["second_observation"] is False


def test_window_is_measured_from_the_chain_not_from_the_wall_clock(tmp_path):
    """Окно — разность отметок цепочки, а не «сколько шёл прогон»."""
    _write(tmp_path / "data", _chain(window_s=1.961))
    report = _run(tmp_path / "data")
    assert report["window_s_max"] == pytest.approx(1.961, abs=1e-6)
    # Час спустя тот же вход даёт ТО ЖЕ окно: длительность прогона ни при чём.
    later = census.run_census(tmp_path / "data", now=_NOW + timedelta(hours=1))
    assert later["window_s_max"] == report["window_s_max"]


# ── звено: ВТОРОЕ НАБЛЮДЕНИЕ ────────────────────────────────────────────────

def test_link_second_observation_different_snapshot_flips_to_ok(tmp_path):
    """Звено «второе наблюдение»: иной `snapshot_id` ⇒ проверка была ⇒ OK."""
    _write(tmp_path / "data", _chain(exec_snapshot="2026-09-27:SECOND-LOOK"))
    report = _run(tmp_path / "data")
    assert report["status"] == census.STATUS_OK
    assert report["recheck_present"] == 1
    assert report["no_recheck"] == 0


def test_link_snapshot_absent_is_not_read_as_matching(tmp_path):
    """Ярлыка наблюдения НЕТ ⇒ `None`, а не «совпал» (инвариант #17)."""
    rows = _chain()
    rows[-1]["snapshot_id"] = ""
    _write(tmp_path / "data", rows)
    report = _run(tmp_path / "data")
    assert report["findings"][0]["second_observation"] is None


# ── звено: СОБЫТИЕ ПОВТОРНОЙ ПРОВЕРКИ ───────────────────────────────────────

@pytest.mark.parametrize("event_type", census.RECHECK_EVENT_TYPES)
def test_link_any_recheck_event_in_vocabulary_flips_to_ok(tmp_path, event_type):
    """Звено «событие перепроверки»: любое имя из перечня признаётся проверкой.

    Перечень намеренно широк, чтобы «у нас это называется иначе» не читалось
    как находка. Проверяется КАЖДОЕ имя, а не первое.
    """
    _write(tmp_path / "data", _chain(recheck=event_type))
    report = _run(tmp_path / "data")
    assert report["status"] == census.STATUS_OK, event_type
    assert report["recheck_present"] == 1


def test_link_unrelated_event_between_is_not_counted_as_a_recheck(tmp_path):
    """Обратная сторона: посторонее событие перепроверкой НЕ считается."""
    _write(tmp_path / "data", _chain(recheck="cycle_start"))
    report = _run(tmp_path / "data")
    assert report["status"] == census.STATUS_WARNING
    assert report["no_recheck"] == 1


# ── звено: ДОПУСК ВЛАДЕЛЬЦА (третий исход и достижимость CRITICAL) ──────────

def test_link_no_owner_tolerance_is_a_third_outcome_not_clean(tmp_path):
    """Допуска нет ⇒ вопрос «слишком стар» НЕ ИЗМЕРЕН и назван причиной."""
    _write(tmp_path / "data", _chain())
    report = _run(tmp_path / "data")
    assert report["freshness_judgeable"] is False
    assert report["tolerance_s"] is None
    assert "НЕ ИЗМЕРЕН" in report["freshness_unjudgeable_reason"]
    assert report["stale_beyond_tolerance"] == 0


def test_link_declared_tolerance_makes_critical_reachable(tmp_path):
    """Владелец объявил допуск ⇒ превышение даёт CRITICAL. Ступень достижима."""
    _write(tmp_path / "data", _chain(window_s=2.0))
    report = _run(tmp_path / "data", tolerance_s=0.5)
    assert report["status"] == census.STATUS_CRITICAL
    assert report["stale_beyond_tolerance"] == 1
    assert report["freshness_judgeable"] is True


def test_link_window_inside_declared_tolerance_is_not_critical(tmp_path):
    """Обратная сторона: окно внутри допуска CRITICAL не даёт."""
    _write(tmp_path / "data", _chain(window_s=0.1))
    report = _run(tmp_path / "data", tolerance_s=0.5)
    assert report["status"] == census.STATUS_WARNING
    assert report["stale_beyond_tolerance"] == 0


def test_link_recheck_present_beats_tolerance(tmp_path):
    """Перепроверка была ⇒ старость окна претензией не является."""
    _write(tmp_path / "data", _chain(window_s=9999.0, recheck="pre_trade_check"))
    report = _run(tmp_path / "data", tolerance_s=0.5)
    assert report["status"] == census.STATUS_OK


def test_owner_column_is_read_and_carries_no_freshness_dial(tmp_path):
    """Замер 27.09: в колонке владельца нет ручки свежести/TTL — она ПЕЧАТАЕТСЯ."""
    policy = census.load_owner_tolerance()
    assert policy["measured"] is True
    assert policy["tolerance_dial"] is None
    assert policy["dials"], "колонка обязана быть напечатана, а не утверждена"
    assert "min_hold_days" in policy["dials"]


def test_owner_column_unreadable_is_a_third_outcome(tmp_path):
    """Колонка недоступна ⇒ третий исход с причиной, а не подставленный допуск."""
    class _Boom:
        def __getattr__(self, name):  # noqa: D105
            raise RuntimeError("колонка недоступна")

    policy = census.load_owner_tolerance(_Boom())
    # dir() у объекта работает, поэтому ручек просто не наберётся — но допуск
    # НЕ выдумывается ни в одном случае.
    assert policy["tolerance_dial"] is None
    assert policy["tolerance_s"] is None


# ── звено: §28 СРОК ГОДНОСТИ ────────────────────────────────────────────────

def test_link_ttl_absent_on_live_shape(tmp_path):
    """§28: у живой формы срока годности нет ни у одного исполнения."""
    _write(tmp_path / "data", _chain())
    report = _run(tmp_path / "data")
    assert report["ttl_declared_count"] == 0


def test_link_ttl_present_is_seen(tmp_path):
    """Обратная сторона: объявленный `valid_until` прибор ВИДИТ."""
    _write(tmp_path / "data", _chain(ttl=True))
    report = _run(tmp_path / "data")
    assert report["ttl_declared_count"] == 1


# ── ТРЕТИЙ ИСХОД: нет предмета / нет записи ─────────────────────────────────

def test_missing_chain_is_unmeasured_with_named_reason(tmp_path):
    """Файла цепочки нет ⇒ НЕ ИЗМЕРЕНО с причиной, а не «проверок ноль»."""
    (tmp_path / "data").mkdir()
    report = _run(tmp_path / "data")
    assert report["measured"] is False
    assert report["status"] == census.STATUS_UNMEASURED
    assert "нет на диске" in report["reason"]


def test_no_executions_is_unmeasured_not_ok(tmp_path):
    """Исполнений нет ⇒ предмета замера нет. Это НЕ «проверка на месте»."""
    rows = [r for r in _chain() if r["event_type"] != census.EVENT_EXECUTED]
    _write(tmp_path / "data", rows)
    report = _run(tmp_path / "data")
    assert report["measured"] is False
    assert report["status"] != census.STATUS_OK
    assert "trade_executed" in report["reason"]


def test_chain_not_reaching_proposal_is_an_unmeasured_record(tmp_path):
    """Цепочка не доходит до предложения ⇒ запись НЕ ИЗМЕРЕНА, а не «без проверки»."""
    rows = _chain()
    orphan = [r for r in rows if r["event_type"] == census.EVENT_EXECUTED]
    orphan[0]["prev_event_id"] = "missing-link"
    _write(tmp_path / "data", orphan)
    report = _run(tmp_path / "data")
    assert report["measured"] is False
    assert report["records_unmeasured"] == 1
    assert "не доходит" in report["unmeasured_records"][0]["reason"]


def test_unparsable_timestamp_is_an_unmeasured_record(tmp_path):
    """Непарсимая отметка ⇒ окно НЕ ИЗМЕРЕНО, а не ноль секунд."""
    rows = _chain()
    rows[-1]["timestamp"] = "не-дата"
    _write(tmp_path / "data", rows)
    report = _run(tmp_path / "data")
    assert report["records_unmeasured"] == 1
    assert report["unmeasured_records"][0]["window_s"] is None


def test_unparsable_lines_are_counted_not_swallowed(tmp_path):
    """Битая строка журнала СЧИТАЕТСЯ, а не молча пропадает."""
    data_dir = tmp_path / "data"
    _write(data_dir, _chain())
    with (data_dir / census.CHAIN_FILENAME).open("a", encoding="utf-8") as fh:
        fh.write("{битый json\n")
    report = _run(data_dir)
    assert report["unparsable_lines"] == 1


# ── ось ЧИТАТЕЛЕЙ: разбор по AST, а НЕ подстрокой ───────────────────────────

def test_reader_axis_ignores_a_mere_mention_of_the_module_name(tmp_path):
    """Настоящая поломка первой редакции: подстрока нашла САМУ СЕБЯ.

    Файл, лишь УПОМИНАЮЩИЙ имя модуля в строке/комментарии/константе, читателем
    гейта не является. Первая редакция мерила подстрокой и объявила сам прибор
    читателем на денежном пути (`.claude/rules/acceptance.md` п. 3 — проба не
    имеет права проходить подстрокой).
    """
    root = tmp_path / "repo"
    (root / "spa_core" / "execution").mkdir(parents=True)
    (root / census.GATE_MODULE).write_text("class PreExecutionSafety: pass\n",
                                          encoding="utf-8")
    (root / "spa_core" / "mentions.py").write_text(
        '# см. spa_core.execution.safety_checks\n'
        'NEEDLE = "spa_core.execution.safety_checks"\n'
        'DOC = """spa_core.execution.safety_checks"""\n', encoding="utf-8")
    axis = census.gate_reader_axis(root)
    assert axis["measured"] is True
    assert axis["money_path_callers"] == []


@pytest.mark.parametrize("source", [
    "import spa_core.execution.safety_checks\n",
    "from spa_core.execution.safety_checks import PreExecutionSafety\n",
    "from spa_core.execution import safety_checks\n",
])
def test_reader_axis_catches_every_import_form(tmp_path, source):
    """Три формы импорта — одно утверждение.

    Господствующую форму (`from spa_core.execution import safety_checks`)
    подстрока НЕ ловила вовсе, и из-за этого первая редакция потеряла
    `gate_chain_audit.py` — читателя, который есть.
    """
    root = tmp_path / "repo"
    (root / "spa_core" / "execution").mkdir(parents=True)
    (root / census.GATE_MODULE).write_text("class PreExecutionSafety: pass\n",
                                          encoding="utf-8")
    (root / "spa_core" / "caller.py").write_text(source, encoding="utf-8")
    axis = census.gate_reader_axis(root)
    assert axis["money_path_callers"] == ["spa_core/caller.py"], source


def test_reader_axis_separates_inert_and_test_callers(tmp_path):
    """Инертный читатель и тест — не денежный путь, и каждый НАЗВАН."""
    root = tmp_path / "repo"
    (root / "spa_core" / "execution").mkdir(parents=True)
    (root / "spa_core" / "tests").mkdir(parents=True)
    (root / census.GATE_MODULE).write_text("class PreExecutionSafety: pass\n",
                                          encoding="utf-8")
    body = "from spa_core.execution import safety_checks\n"
    (root / census.GATE_INERT_CALLERS[0]).write_text(body, encoding="utf-8")
    (root / "spa_core" / "tests" / "test_x.py").write_text(body, encoding="utf-8")
    axis = census.gate_reader_axis(root)
    assert axis["money_path_callers"] == []
    assert census.GATE_INERT_CALLERS[0] in axis["inert_callers"]
    assert "spa_core/tests/test_x.py" in axis["test_callers"]


def test_reader_axis_without_a_root_is_unmeasured_not_empty(tmp_path):
    """Корня нет ⇒ `None`, а не «читателей ноль» (инвариант #17)."""
    axis = census.gate_reader_axis(tmp_path / "нет-такого")
    assert axis["measured"] is False
    assert axis["money_path_callers"] is None
    assert axis["reason"]


def test_reader_axis_unparsed_file_is_a_third_outcome(tmp_path):
    """Файл не разобрался ⇒ он НАЗВАН, а не сочтён «не импортирует»."""
    root = tmp_path / "repo"
    (root / "spa_core" / "execution").mkdir(parents=True)
    (root / census.GATE_MODULE).write_text("class PreExecutionSafety: pass\n",
                                          encoding="utf-8")
    (root / "spa_core" / "broken.py").write_text("def (\n", encoding="utf-8")
    axis = census.gate_reader_axis(root)
    assert "spa_core/broken.py" in axis["unparsed_files"]


# ── побочная ось: ЯРЛЫК исполнения ──────────────────────────────────────────

def test_identity_axis_names_colliding_labels(tmp_path):
    """Живой исход: один `trade_id` называет РАЗНЫЕ денежные события."""
    rows = _chain(trade_id="T007", tag="a") + _chain(trade_id="T007", tag="b")
    rows[-1]["data"] = {"trade_id": "T007", "diff_usd": 28500.06}
    _write(tmp_path / "data", rows)
    report = _run(tmp_path / "data")
    ident = report["identity"]
    assert ident["events"] == 2
    assert ident["distinct_labels"] == 1
    assert ident["colliding_labels"][0]["trade_id"] == "T007"
    assert ident["colliding_labels"][0]["payloads_distinct"] == 2


def test_population_is_counted_by_event_not_by_label(tmp_path):
    """Два исполнения под ОДНИМ ярлыком — это ДВА исполнения, а не одно.

    Считать по `trade_id` значило бы молча слить 14 исполнений в 12.
    """
    rows = _chain(trade_id="T007", tag="a") + _chain(trade_id="T007", tag="b")
    _write(tmp_path / "data", rows)
    report = _run(tmp_path / "data")
    assert report["executions"] == 2
    assert report["no_recheck"] == 2


# ── АРТЕФАКТ: проверяется НА ДИСКЕ ──────────────────────────────────────────

def test_run_writes_the_artifact_to_disk(tmp_path):
    """Урок ADR-480: `measured=True` при ОТСУТСТВУЮЩЕМ артефакте.

    Контроль читает ДИСК, а не вывод: обратный порядок доводов `atomic_save`
    отвергает fail-CLOSED, и тогда артефакта не появляется ВОВСЕ, а ступень
    докладывает успех.
    """
    _write(tmp_path / "data", _chain())
    out = census.run(root=str(tmp_path), now=_NOW)
    assert out["measured"] is True
    path = tmp_path / "data" / census.ARTIFACT_NAME
    assert path.exists(), "артефакта нет НА ДИСКЕ"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["status"] == census.STATUS_WARNING
    assert doc["criterion"] == census.CRITERION


def test_run_leaves_an_artifact_even_when_unmeasured(tmp_path):
    """Третий исход обязан ДОЕХАТЬ: иначе офис не отличит его от «не запускалась»."""
    (tmp_path / "data").mkdir()
    out = census.run(root=str(tmp_path), now=_NOW)
    assert out["measured"] is False
    doc = json.loads((tmp_path / "data" / census.ARTIFACT_NAME)
                     .read_text(encoding="utf-8"))
    assert doc["status"] == census.STATUS_UNMEASURED
    assert doc["reason"]


# ── ОТЧЁТ: «не измерено» печатается как таковое ─────────────────────────────

def test_report_prints_unmeasured_as_such(tmp_path):
    """Шаг 0-офис обязан прочитать «НЕ ИЗМЕРЕНО», а не пустую сводку."""
    (tmp_path / "data").mkdir()
    report = _run(tmp_path / "data")
    text = "\n".join(census.format_report(report))
    assert "НЕ ИЗМЕРЕНО" in text
    assert census.CRITERION.split("—")[0].strip() in text


def test_report_says_unmeasured_when_a_field_is_absent(tmp_path):
    """Поля НЕТ в артефакте ⇒ «НЕ ИЗМЕРЕНО», а не «их ноль» (инвариант #17)."""
    _write(tmp_path / "data", _chain())
    report = _run(tmp_path / "data")
    stripped = {k: v for k, v in report.items()
                if k not in ("findings", "gate_readers", "identity")}
    text = "\n".join(census.format_report(stripped))
    assert "артефакт не несёт поля `findings`" in text
    assert "поля `gate_readers`" in text
    assert "поля `identity`" in text


def test_summary_line_names_the_criterion_and_the_counts(tmp_path):
    """Сводка офиса несёт предмет и числа, а не только вердикт."""
    _write(tmp_path / "data", _chain())
    line = census.summary_line(_run(tmp_path / "data"))
    assert "Pre-trade safety" in line
    assert "исполнений 1" in line


def test_report_prints_the_window_and_refuses_to_price_it(tmp_path):
    """Окно печатается; в доллары НЕ переводится — вреда в деньгах не измерено."""
    _write(tmp_path / "data", _chain())
    text = "\n".join(census.format_report(_run(tmp_path / "data")))
    assert "[ОКНО]" in text
    assert "вред в долларах" in text


# ── коды возврата ───────────────────────────────────────────────────────────

def test_exit_code_unmeasured_is_not_zero(tmp_path):
    """«Не измерено» не выдаётся за «чисто» и кодом возврата."""
    (tmp_path / "data").mkdir()
    code = census.main(["--data-dir", str(tmp_path / "data"),
                        "--repo-root", str(tmp_path)])
    assert code == census.EXIT_UNMEASURED


def test_exit_code_is_one_only_on_critical(tmp_path):
    """Ненулевой код — на CRITICAL; WARNING печатается, но кодом не нудит."""
    data_dir = tmp_path / "data"
    _write(data_dir, _chain(window_s=2.0))
    warn = census.main(["--data-dir", str(data_dir), "--repo-root", str(tmp_path)])
    crit = census.main(["--data-dir", str(data_dir), "--repo-root", str(tmp_path),
                        "--tolerance-s", "0.5"])
    assert warn == 0
    assert crit == 1
