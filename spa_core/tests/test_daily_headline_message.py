# FROZEN-DATE-OK: injected-clock — run_daily_digest/build_report_data принимают now=;
# даты баров и «сегодня» выведены из одного якоря _NOW, календарь на вердикт не влияет.
"""Утреннее ПЕРВОЕ сообщение владельцу (аудит 08.09).

# LLM_FORBIDDEN

Владелец получал 56 строк, где английские шапки мешались с русским хвостом,
единственная настоящая тревога дня стояла 51-й строкой кодом правила, а «жива
ли система» не отвечал никто. Здесь закреплено: заголовок ≤900 знаков, русский,
самое важное первым; каждый непрочитанный источник — «не измерено» (третий
исход), никогда догадка; утро — ровно ДВА сообщения под одним дневным стражем.
Transport mocked — nothing is sent to Telegram.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.telegram.reports import daily as D

_NOW = datetime(2026, 9, 8, 8, 10, tzinfo=timezone.utc)
_MARKERS = ("Система", "Что изменилось", "Ждут тебя", "paper")


def _w(ddir: Path, name: str, obj) -> None:
    (ddir / name).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _seed_full(ddir: Path) -> None:
    """Живые формы файлов 08.09, сжатые до нужного (числа — фикстурные)."""
    _w(ddir, "system_health.json", {
        "overall_status": "CRITICAL",
        "domains": {"d5_code_integrity": {"status": "CRITICAL"},
                    "d1_data_pipeline": {"status": "WARNING"},
                    "d2_connectivity": {"status": "OK"}},
        "checks": [{"id": "d5.security.secrets", "status": "CRITICAL", "domain": "d5_code_integrity"}],
    })
    _w(ddir, "agent_health.json", {"healthy_count": 74, "total_agents": 77})
    _w(ddir, "paper_trading_status.json", {
        "last_cycle_ts": "2026-09-08T07:27:38+00:00", "last_cycle_status": "ok",
        "paper_start_date": "2026-06-10", "risk_policy_approved": True,
    })
    _w(ddir, "emergency_status.json", {"status": "CLEAR"})
    _w(ddir, "golive_status.json", {"passed": 29, "total": 29,
                                    "real_track_days": 77, "evidenced_anchor": "2026-06-22"})
    _w(ddir, "adapter_status.json", {"adapters": {
        "pendle": {"display_name": "Pendle Finance (PT markets)", "apy": 8.0},
        "maple": {"display_name": "Maple Finance", "apy": 4.98},
        "compound_v3": {"display_name": "Compound V3 (Comet USDC)", "apy": 4.65},
    }})
    _w(ddir, "equity_curve_daily.json", {"is_demo": False, "daily": [
        {"date": "2026-06-22", "open_equity": 100134.79, "close_equity": 100150.66,
         "apy_today": 4.0, "positions": {"compound_v3": 40000.0}},
        {"date": "2026-09-07", "open_equity": 101223.79, "close_equity": 101237.29,
         "apy_today": 4.87, "positions": {"compound_v3": 40000.0, "maple": 20000.0}},
        {"date": "2026-09-08", "open_equity": 101237.29, "close_equity": 101251.32,
         "apy_today": 5.06, "positions": {"compound_v3": 40000.0, "maple": 5263.16,
                                          "pendle": 20000.0}},
    ]})
    _w(ddir, "allocation_audit_daily.json", {
        "verdict": "VIOLATION", "counts": {"OK": 27, "VIOLATION": 1, "UNCHECKED": 1},
        "findings": [
            {"rule_id": "CAP-03", "verdict": "OK", "subject": "aave_v3", "detail": "норма"},
            {"rule_id": "ECON-10", "verdict": "VIOLATION", "subject": "compound_v3",
             "detail": "доходность 4.65 % ниже медианы 4.81 %, а доля 40.0% больше "
                       "половины тир-потолка (20.0%)"},
            {"rule_id": "ADM-07/08", "verdict": "UNCHECKED", "subject": "pendle",
             "detail": "протокола нет в снимке оркестратора — источник TVL неизвестен"},
        ],
    })
    _w(ddir, "hy_paper_trading.json", {"seed_equity": 100000.0, "equity": 100466.77,
                                       "start_date": "2026-06-22"})
    _w(ddir, "lp_paper_trading.json", {"seed_equity": 100000.0, "equity": 100571.39,
                                       "start_date": "2026-06-22"})


def _seed_tracker(root: Path) -> Path:
    tdir = root / "nimbalyst-local" / "tracker"
    tdir.mkdir(parents=True)
    (tdir / "own-old.md").write_text(
        "---\ntitle: Старый вопрос\nstatus: needs-owner\ncreated: 2026-08-01\n---\nтело\n",
        encoding="utf-8")
    (tdir / "own-new.md").write_text(
        '---\ntitle: "Шесть модулей выдумывают остаток на кошельке"\nstatus: needs-owner\n'
        "created: 2026-09-07\n---\nтело\n", encoding="utf-8")
    (tdir / "inbox-done.md").write_text(
        "---\ntitle: Закрытая\nstatus: ingested\ncreated: 2026-09-08\n---\n"
        "В теле процитировано:\n```\nstatus: needs-owner\n```\n", encoding="utf-8")
    return tdir


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Каталог data/ + дерево с трекером; очередь владельца читается из ЭТОГО дерева."""
    ddir = tmp_path / "data"
    ddir.mkdir()
    _seed_full(ddir)
    _seed_tracker(tmp_path)
    monkeypatch.setattr(D, "_REPO_ROOT", tmp_path)
    return ddir


@pytest.fixture
def sent(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(D, "_send_html", lambda msg: (captured.append(msg) or True))
    return captured


def _headline(ddir: Path) -> str:
    from spa_core.reporting.daily_telegram_report import build_report_data
    data = build_report_data("2026-09-08", data_dir=ddir, now=_NOW)
    return D.build_headline_message(data, ddir)


# ── форма и бюджет ────────────────────────────────────────────────────────────

def test_headline_is_short_russian_and_ordered_most_important_first(repo):
    head = _headline(repo)
    assert len(head) <= D.HEADLINE_MAX_CHARS
    for m in _MARKERS:
        assert m in head, m
    assert head.startswith("🔴 Система: КРИТИЧНО")
    assert head.index("Система") < head.index("Что изменилось") < head.index("Ждут тебя")
    assert head.rstrip().endswith(D.HEADLINE_FOOTER)
    # Домен назван словами, техническое имя проверки — рядом, в скобках.
    assert "целостность кода" in head and "d5.security.secrets" in head
    assert "агенты 74 из 77 в порядке" in head
    assert "цикл 08.09 07:27 UTC" in head
    assert "стоп-кран не включён" in head and "аварий нет" in head


def test_headline_budget_is_a_hard_contract_even_under_a_flood(repo):
    """Много изменений + длинная карточка ⇒ компактный вариант, затем усечение."""
    eq = json.loads((repo / "equity_curve_daily.json").read_text(encoding="utf-8"))
    eq["daily"][-1]["positions"] = {f"pool_{i}": 1000.0 * (i + 1) for i in range(30)}
    _w(repo, "equity_curve_daily.json", eq)
    (D._REPO_ROOT / "nimbalyst-local" / "tracker" / "own-long.md").write_text(
        "---\ntitle: " + "очень длинный заголовок " * 20 + "\nstatus: needs-owner\n"
        "created: 2026-09-08\n---\n", encoding="utf-8")
    head = _headline(repo)
    assert len(head) <= D.HEADLINE_MAX_CHARS
    assert head.rstrip().endswith(D.HEADLINE_FOOTER)
    assert "Система" in head  # самое важное усечением не теряется


# ── третий исход: нет файла ⇒ «не измерено», не догадка и не падение ──────────

def test_missing_health_files_say_unmeasured_and_never_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_REPO_ROOT", tmp_path)  # трекера нет ⇒ очередь не измерена
    ddir = tmp_path / "data"
    ddir.mkdir()
    head = D.build_headline_message({}, ddir)
    assert len(head) <= D.HEADLINE_MAX_CHARS
    for m in _MARKERS:
        assert m in head, m
    assert head.count("не измерено") >= 5  # система · агенты · цикл · позиции · очередь · трек
    assert "🟢" not in head.split("\n")[0], "пустой каталог не имеет права выглядеть здоровым"
    assert "в порядке" not in head.split("\n")[0]


def test_corrupt_health_file_is_unmeasured_not_a_guess(repo):
    (repo / "system_health.json").write_text("{не json", encoding="utf-8")
    head = _headline(repo)
    assert head.startswith("⚪ Система: не измерено")


def test_kill_switch_file_contract_matches_governance(repo):
    """Файл есть ⇒ включён; явное active:false ⇒ выключен (kill_switch.check_manual_trigger)."""
    _w(repo, "kill_switch_active.json", {"active": True, "reason": "manual"})
    assert "СТОП-КРАН ВКЛЮЧЁН" in _headline(repo)
    _w(repo, "kill_switch_active.json", {"active": False})
    assert "стоп-кран не включён" in _headline(repo)


# ── что изменилось ────────────────────────────────────────────────────────────

def test_positions_diff_names_pools_by_display_name(repo):
    head = _headline(repo)
    assert "позиции 07.09 → 08.09" in head
    assert "• Pendle Finance (PT markets): $0 → $20,000" in head
    assert "• Maple Finance: $20,000 → $5,263" in head
    # Неизменившаяся позиция (Compound V3, 40000 → 40000) в «что изменилось» не попадает.
    assert "Compound V3" not in head


def test_positions_diff_falls_back_to_the_key_without_adapter_status(repo):
    (repo / "adapter_status.json").unlink()
    assert "• pendle: $0 → $20,000" in _headline(repo)


def test_non_ok_oversight_finding_is_rendered_by_its_detail_sentence(repo):
    head = _headline(repo)
    assert "⚠️ Нарушение: доходность 4.65 % ниже медианы 4.81 %" in head
    assert "(ECON-10, compound_v3)" in head
    assert "Не измерено правил надзора: 1 (pendle)" in head  # UNCHECKED — третий исход
    assert "CAP-03" not in head and "норма" not in head        # OK-находки не показываются


def test_all_ok_oversight_says_so_briefly(repo):
    _w(repo, "allocation_audit_daily.json", {"verdict": "OK", "findings": [
        {"rule_id": "CAP-03", "verdict": "OK", "subject": "aave_v3"}]})
    assert "✅ Надзор аллокации: нарушений нет" in _headline(repo)


# ── ждут тебя ─────────────────────────────────────────────────────────────────

def test_owner_queue_counts_frontmatter_status_and_names_the_newest(repo):
    head = _headline(repo)
    assert "Ждут тебя: карточек 2" in head
    assert "новая: «Шесть модулей выдумывают остаток на кошельке»" in head
    # «status: needs-owner», процитированный в ТЕЛЕ закрытой карточки, — не карточка
    # (живой случай: inbox-ochered-vladeltsa-pokazyvaet-20-kartoche.md).


# ── бумажный трек ─────────────────────────────────────────────────────────────

def test_track_block_uses_evidenced_days_and_marks_advisory_books_paper(repo):
    head = _headline(repo)
    assert "Бумажный трек" in head and "капитал виртуальный" in head
    assert "$101,251 · +$14 за день · +1.12% за 77 подтверждённых дн. (с 2026-06-22)" in head
    assert "APY сегодня 5.06%" in head
    assert "Советующие пакеты (paper, капитал не двигают): Σ $201,038" in head


# ── проводка: два сообщения, один страж ──────────────────────────────────────

def test_run_posts_exactly_two_messages_headline_first_and_once_per_day(repo, sent):
    res = D.run_daily_digest("2026-09-08", data_dir=repo, send=True, now=_NOW)
    assert res["sent"] is True
    assert len(sent) == 2
    assert sent[0] == res["headline"] and sent[1] == res["message"]
    assert len(sent[0]) <= D.HEADLINE_MAX_CHARS
    assert "Подробности — следующим сообщением" in sent[0]
    assert "SPA — отчёт за день" in sent[1]
    # Второй запуск в тот же день — страж, ни одного нового сообщения.
    again = D.run_daily_digest("2026-09-08", data_dir=repo, send=True, now=_NOW)
    assert again["skipped"] is True and len(sent) == 2


def test_details_message_still_carries_every_mandated_block(repo):
    """11 обязательных блоков (мандаты 19/20/29/31.08) не имеют права пропасть при разделении."""
    _, details, data = D.build_digest_messages("2026-09-08", data_dir=repo, now=_NOW, drain=False)
    missing = [m for m, _ in D._REQUIRED_BLOCKS if m not in details]
    assert missing == [], missing
    assert data["report_standard_gaps"] == []
    assert "Стандарт отчёта" not in details  # самопроверка — в data, не в тексте


def test_failed_headline_send_marks_nothing_and_details_are_not_sent(repo, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(D, "_send_html", lambda msg: (calls.append(msg) or False))
    res = D.run_daily_digest("2026-09-08", data_dir=repo, send=True, now=_NOW)
    assert res["sent"] is False and "headline" in str(res["error"])
    assert len(calls) == 1  # подробности без заголовка не уходят
    assert not (repo / D.GUARD_FILENAME).exists()


def test_check_mode_prints_both_and_never_sends(repo, monkeypatch, capsys):
    monkeypatch.setattr(D, "_send_html", lambda msg: pytest.fail("--check отправил сообщение"))
    assert D.main(["--check", "--data-dir", str(repo), "--date", "2026-09-08"]) == 0
    out = capsys.readouterr().out
    assert "Система" in out and "сообщение 2/2" in out and "отчёт за день" in out
    assert "<b>" not in out
