"""test_briefing_track_integrity.py — число, которое росло три дня, и никто его не читал.

## Авария (замер 2026-08-12, цикл #201)

09.08 закрывали класс «код есть, никто не зовёт»: тест-храповик расхождения
доказательной базы с кривой требовал `SPA_LIVE_TRACK=1` и потому не запускался ни в
CI, ни агентом. Лечение — карточка `agent-divergence-ratchet-has-no-runner` — было
верным: проверку встроили в `cycle_health_monitor.check_evidence_matches_curve`,
который реально ходит по живому дереву каждые 300 с, и положили ЧИСЛО в состояние
монитора. Карточка прямо предупреждала, чем это кончится иначе: «повторим дефект
правила честности, где вывод записывался, но никем не читался».

Ровно это и вышло. Замер 12.08 (`grep` по всему дереву): у `divergent_days` **нет ни
одного читателя** вне собственных unit-тестов. Ни брифинга, ни тревоги, ни SLO, ни
дашборда. За это время число выросло **16/51 → 18/54, худшее расхождение $215.99, и
последняя разошедшаяся дата — сегодняшняя**, то есть дефект живой, а не исторический.

Класс прежний и главный для этого проекта: сторож отвечает на свой вопрос
безупречно, а на нужный («узнает ли об этом хоть кто-нибудь?») не отвечает никто.
Числа в файле, который никто не открывает, ровно столько же, сколько его отсутствия.

## Что закрепляют тесты

Каждый — положительный контроль: на дереве без починки красный (функций нет вовсе,
раздела в брифинге нет, строки в таблице нет).

  1. Живой замер 12.08 доезжает до брифинга ЧИСЛАМИ, а не пересказом.
  2. Три разных «не измерено» (нет файла · нет проверки в снимке · монитор отказался)
     печатаются как НЕ ИЗМЕРЕНО и никогда — как согласие. Отдельно важен второй:
     прод на мониторе до 10.08 даёт снимок без ключа, и молчание читалось бы как
     «сходится» (класс «доставлено ≠ работает», правило deployment.md).
  3. Протухший снимок отдаёт ПОСЛЕДНИЕ ИЗВЕСТНЫЕ числа с пометкой, а не текущие.
  4. Зелёная строка достижима ровно одним путём — свежий снимок с нулём расхождений.
  5. Проводка: раздел и строка таблицы действительно попадают в файл (урок #144 —
     удаление одного вызова оставляло 22 своих теста зелёными).
  6. Обе поверхности читают ОДИН снимок и не могут разойтись (урок #197).
"""
from datetime import datetime, timedelta, timezone

import update_system_briefing as usb


# ---------------------------------------------------------------------------
# Helpers — снимок формы data/cycle_health.json
# ---------------------------------------------------------------------------
NOW = datetime(2026, 8, 12, 12, 5, 54, tzinfo=timezone.utc)


def _fresh_ts(minutes_ago: float = 2.0) -> str:
    """Отметка «сейчас» по РЕАЛЬНЫМ часам.

    Свежесть снимка `track_integrity_state` берёт из `_age_minutes`, который ходит к
    настоящим часам; поэтому отметку строим относительно них, а фиксированный `now`
    инъектируем только туда, где он вход (сравнение с «сегодня»). Обе стороны
    закреплены, литеральных дат в фикстуре нет — тест не протухнет от календаря.
    """
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _snap(divergent=18, compared=54, worst=215.99, latest="2026-08-12",
          status=None, ts=None, with_check=True):
    """Снимок cycle_health.json — форма ровно как у живого файла 12.08."""
    checks = {
        "cycle_gap": {"status": "OK", "hours_since": 3.0},
        "equity_anomaly": {"status": "OK", "today_change_pct": 0.01},
        "data_freshness": {"status": "OK", "stale_files": [], "missing_files": []},
    }
    if with_check:
        checks["evidence_vs_curve"] = {
            "status": status or ("WARNING" if divergent else "HEALTHY"),
            "divergent_days": divergent,
            "compared_days": compared,
            "max_delta_usd": worst,
            "latest_divergent": latest,
            "detail": (f"{divergent} из {compared} дат расходятся (own-32), "
                       f"максимум ${worst}") if divergent else
                      f"все {compared} общих дат сходятся",
        }
    return {"overall": "HEALTHY", "checks": checks, "unchecked": [],
            "checked_at": ts or _fresh_ts(2.0), "recommendations": []}


def _patch(monkeypatch, snap):
    """Подменяем ТОЛЬКО cycle_health.json — остальные разделы брифинга не трогаем."""
    def fake_read_json(name):
        return snap if name == "cycle_health.json" else {}
    monkeypatch.setattr(usb, "read_json", fake_read_json)


# ---------------------------------------------------------------------------
# 1. Живой замер 12.08 доезжает числами
# ---------------------------------------------------------------------------
def test_live_measurement_reaches_the_briefing_as_numbers(monkeypatch):
    """Тот самый снимок, который три дня рос незамеченным."""
    _patch(monkeypatch, _snap())
    text = usb.build_track_integrity_section()

    assert "18" in text and "54" in text, "число расходящихся дат обязано быть в брифинге"
    assert "215.99" in text, "худшее расхождение — деньги, их нельзя округлять до слов"
    assert "2026-08-12" in text, "последняя расходящаяся дата обязана быть названа"
    assert "own-32" in text, "у находки обязана быть ссылка на её механизм"
    assert "✅" not in text, "расхождение НЕ смеет получить зелёную отметку"


def test_the_headline_cell_says_the_same_thing(monkeypatch):
    """Таблица at-a-glance — то, что читают; пересказ в ней запрещён."""
    _patch(monkeypatch, _snap())
    cell = usb.track_integrity_cell(usb.track_integrity_state(_snap()))

    assert "18" in cell and "54" in cell
    assert "215.99" in cell
    assert cell.startswith("⚠️"), "расхождение обязано быть видно значком, а не текстом внутри"


# ---------------------------------------------------------------------------
# 2. Три разных «не измерено» — и ни одно из них не «сходится»
# ---------------------------------------------------------------------------
def test_missing_snapshot_is_not_measured_not_fine(monkeypatch):
    _patch(monkeypatch, {})
    st = usb.track_integrity_state({})
    text = usb.build_track_integrity_section()

    assert st["state"] == "missing"
    assert "НЕ ИЗМЕРЕНО" in text
    assert "✅" not in text


def test_snapshot_without_the_check_is_not_measured(monkeypatch):
    """Прод на мониторе до 10.08 отдаёт снимок БЕЗ ключа.

    Это самый опасный из трёх случаев: проверка доставлена на origin, а исполняется
    старый код, — и молчание читалось бы как «сходится». Отсутствие проверки обязано
    называться отсутствием проверки.
    """
    snap = _snap(with_check=False)
    _patch(monkeypatch, snap)
    st = usb.track_integrity_state(snap)
    text = usb.build_track_integrity_section()

    assert st["state"] == "no_check"
    assert "НЕ ИЗМЕРЕНО" in text
    assert "старой версии" in text, "надо назвать ПРИЧИНУ — иначе это просто «нет данных»"
    assert "✅" not in text


def test_monitor_refusal_is_carried_through_verbatim(monkeypatch):
    """Монитор сказал UNCHECKED — брифинг обязан повторить, а не перевести в OK."""
    snap = _snap(divergent=None, status="UNCHECKED", worst=None, latest=None)
    snap["checks"]["evidence_vs_curve"]["detail"] = "нет общих дат — сравнивать нечего"
    _patch(monkeypatch, snap)
    st = usb.track_integrity_state(snap)
    text = usb.build_track_integrity_section()

    assert st["state"] == "unchecked"
    assert "нет общих дат" in text, "причина отказа монитора печатается дословно"
    assert "✅" not in text


# ---------------------------------------------------------------------------
# 3. Протухший снимок — последние известные числа, и это сказано вслух
# ---------------------------------------------------------------------------
def test_stale_snapshot_never_passes_for_the_present(monkeypatch):
    old = _fresh_ts(minutes_ago=usb.TRACK_SNAPSHOT_STALE_MIN + 5)
    snap = _snap(ts=old)
    _patch(monkeypatch, snap)
    st = usb.track_integrity_state(snap)
    text = usb.build_track_integrity_section()

    assert st["state"] == "stale"
    assert "ПРОТУХ" in text
    assert "ПОСЛЕДНИЕ ИЗВЕСТНЫЕ" in text
    assert "18" in text, "последние известные числа не прячем — прячем только их свежесть"


def test_undateable_snapshot_is_stale_not_fresh():
    """Свежесть недоказуема ⇒ снимок протухший (fail-CLOSED, а не «наверное свежий»)."""
    st = usb.track_integrity_state(_snap(ts="не-дата"))
    assert st["state"] == "stale"


# ---------------------------------------------------------------------------
# 4. Зелёная строка достижима ровно одним путём
# ---------------------------------------------------------------------------
def test_green_line_requires_a_fresh_measured_zero(monkeypatch):
    snap = _snap(divergent=0, worst=0.0, latest=None)
    _patch(monkeypatch, snap)
    st = usb.track_integrity_state(snap)
    text = usb.build_track_integrity_section()

    assert st["state"] == "fresh" and st["divergent_days"] == 0
    assert "✅" in text
    assert "54" in text, "и в согласии называем, СКОЛЬКО дат сошлось"


# ---------------------------------------------------------------------------
# 5. «Живое» расхождение отличается от исторического — в обе стороны
# ---------------------------------------------------------------------------
def test_todays_divergence_is_marked_live():
    st = usb.track_integrity_state(_snap(latest="2026-08-12"), now=NOW)
    assert st["live_today"] is True
    assert "ЖИВОЕ" in usb.track_integrity_cell(st)


def test_older_divergence_is_not_marked_live():
    """Контроль в обратную сторону: вчерашнее расхождение — не сегодняшнее."""
    st = usb.track_integrity_state(_snap(latest="2026-08-11"), now=NOW)
    assert st["live_today"] is False
    assert "ЖИВОЕ" not in usb.track_integrity_cell(st)


# ---------------------------------------------------------------------------
# 6. Проводка: раздел и строка ДЕЙСТВИТЕЛЬНО попадают в файл
# ---------------------------------------------------------------------------
def test_the_section_and_the_row_are_actually_wired_into_the_file(monkeypatch, tmp_path):
    """Урок #144: удаление ОДНОГО вызова оставляло свои тесты зелёными.

    Поэтому проверяем не функцию, а записанный файл — то, что откроет сессия.
    """
    _patch(monkeypatch, _snap())
    monkeypatch.setattr(usb, "DOCS_DIR", str(tmp_path))
    monkeypatch.setattr(usb, "OUTPUT", str(tmp_path / "SYSTEM_BRIEFING.md"))
    monkeypatch.setattr(usb, "build_launchd_section", lambda: "## launchd\n")

    usb.main()
    written = (tmp_path / "SYSTEM_BRIEFING.md").read_text(encoding="utf-8")

    assert "Track integrity" in written, "строки в таблице at-a-glance нет — её никто не увидит"
    assert "| Track integrity |" in written, "строка обязана быть В ТАБЛИЦЕ, а не рядом"
    assert "🧾 Track integrity" in written, "раздела с подробностями нет"
    assert written.count("18") >= 1 and "215.99" in written


def test_both_surfaces_read_one_snapshot(monkeypatch, tmp_path):
    """Урок #197: две поверхности с двумя источниками расходятся.

    Один и тот же снимок обязан дать одну и ту же строку в таблице и в разделе.
    """
    snap = _snap(divergent=7, compared=40, worst=12.5, latest="2026-08-11")
    _patch(monkeypatch, snap)
    monkeypatch.setattr(usb, "DOCS_DIR", str(tmp_path))
    monkeypatch.setattr(usb, "OUTPUT", str(tmp_path / "SYSTEM_BRIEFING.md"))
    monkeypatch.setattr(usb, "build_launchd_section", lambda: "## launchd\n")

    usb.main()
    written = (tmp_path / "SYSTEM_BRIEFING.md").read_text(encoding="utf-8")
    cell = usb.track_integrity_cell(usb.track_integrity_state(snap))

    assert f"| Track integrity | {cell} |" in written
    assert "7" in cell and "40" in cell
    assert "18" not in written.split("## 🧾")[1][:400], "числа обязаны быть из ЭТОГО снимка"
