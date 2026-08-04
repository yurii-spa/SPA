#!/usr/bin/env python3
"""Регресс-тесты «алерты простым языком» (spa_core/telegram/humanize.py).

Owner-задание (inbox 2026-07-20 + 2026-07-27): Tier-1 алерты владельцу должны
приходить человеческим русским, а не операторскими строками мониторов.

Что здесь закреплено — ровно те свойства, ради которых слой и существует:

1. **Никакой потери информации** — нераспознанная строка проходит ВЕРБАТИМ
   (иначе перевод мог бы молча съесть проблему, о которой и был алерт).
2. **Никакой выдумки** — все числа/пороги/имена в переводе взяты из исходной
   строки; проверяется посимвольно на реальном алерте владельца от 2026-07-27.
3. **Никогда не рейзит** — сломанный вход отдаёт исходный текст (алерт обязан
   дойти хотя бы «сырым»).
4. **Гейт push_policy не затронут** — whitelist/edge-trigger/ceiling работают
   как раньше; humanize — только рендер.

Всё герметично: реальный Telegram/Keychain не трогается (транспорт замокан).
"""
from __future__ import annotations

import re

import pytest

from spa_core.telegram import humanize as H
from spa_core.telegram import push_policy


# Реальный алерт, который владелец прислал как пример «приходит плохо» (27.07).
OWNER_EXAMPLE_BODY = (
    "🚨 <b>SPA Agent Health Alert</b>\n"
    "Status: CRITICAL | 6 issue(s) found\n"
    "\n"
    "⚠️ com.spa.daily_cycle — last_exit=1\n"
    "⚠️ daily cycle stale 26.7h (>26h)\n"
    "⚠️ track accrual STALE: newest evidenced bar 32.7h old (>30h SLA)\n"
    "⚠️ autopush lag 239.4h (>2h)\n"
    "⚠️ fleet parity stale 378.9h (>26h) — drift guard not re-run\n"
    "⚠️ capital-efficiency LAZY: 15% deployable capital idle at 0% "
    "— ~127bps/yr forgone (allocator left safe headroom unused)"
)


# ─── 1. Заголовки ────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("SPA Agent Health — CRITICAL", "Агенты: критическая проблема"),
        ("SPA Agent Health — recovered", "Агенты: всё восстановилось"),
        ("SPA System Health — CRITICAL", "Здоровье системы: критическая проблема"),
        ("SPA — Cycle Gap Detected", "Пропущен ежедневный цикл"),
        ("SPA Threat Reactor — Kill Switch", "Сработал аварийный стоп (kill-switch)"),
        ("SPA Rules Watchdog — CRITICAL breach", "Нарушены правила портфеля (критично)"),
        ("DataTrust Alarm", "Тревога: данным нельзя доверять"),
    ],
)
def test_known_titles_are_translated(raw, expected):
    assert H.humanize_title(raw) == expected


def test_title_prefix_keeps_the_agent_name():
    # Имя агента — часть заголовка; оно ДОЛЖНО дойти до владельца как есть.
    out = H.humanize_title("SPA Core Agent DOWN: com.spa.daily_cycle")
    assert out == "Ключевой агент не работает: com.spa.daily_cycle"


def test_unknown_title_passes_through_verbatim():
    # Незнакомый заголовок не подменяется и не «улучшается» — вербатим.
    assert H.humanize_title("SPA Brand New Monitor — WEIRD") == (
        "SPA Brand New Monitor — WEIRD"
    )


def test_title_with_html_markup_still_matches():
    assert H.humanize_title("<b>SPA Watchdog</b>") == "Сторож агентов"


# ─── 2. Построчный перевод тела ──────────────────────────────────────────────
@pytest.mark.parametrize(
    "line,must_contain",
    [
        ("Status: CRITICAL | 6 issue(s) found", ["критично", "6"]),
        ("last_exit=1", ["ошибкой", "1"]),
        ("malformed plist", ["plist"]),
        ("PID=0 (server down)", ["не запущен"]),
        ("log missing (never ran?)", ["нет лога"]),
        ("log stale 3.1h (>1.5h)", ["3.1 ч", "1.5 ч"]),
        ("daily cycle stale 26.7h (>26h)", ["26.7 ч", "26 ч"]),
        ("equity_curve stale 40.0h (>30h)", ["40.0 ч", "30 ч"]),
        (
            "track accrual STALE: newest evidenced bar 32.7h old (>30h SLA)",
            ["32.7 ч", "30 ч", "go-live"],
        ),
        ("track accrual STALE: freshness check error (fail-closed)", ["fail-closed"]),
        ("portfolio_health 41.5/100 (<60)", ["41.5", "60"]),
        ("2 CRITICAL red flag(s) on HELD protocols", ["2", "деньги"]),
        ("autopush lag 239.4h (>2h)", ["239.4 ч", "2 ч", "GitHub"]),
        (
            "fleet parity stale 378.9h (>26h) — drift guard not re-run",
            ["378.9 ч", "26 ч"],
        ),
        ("fleet parity DRIFT (declared, retired)", ["declared, retired"]),
        (
            "resilience posture stale 20.0h (>13h) — DR proof-chain not fresh",
            ["20.0 ч", "13 ч"],
        ),
        (
            "resilience posture DEGRADED (DR drill/offsite not passing)",
            ["DEGRADED"],
        ),
        (
            "tournament data-trust ALERT — mock data detected (human review)",
            ["mock data detected", "человек"],
        ),
        (
            "capital-efficiency UNKNOWN (idle book, feed unreadable — fail-closed)",
            ["неизвестна", "fail-closed"],
        ),
    ],
)
def test_technical_lines_become_russian_keeping_the_numbers(line, must_contain):
    out = H.humanize_body(line)
    assert out != line, "строка должна быть переведена"
    for token in must_contain:
        assert token in out, f"{token!r} потерян при переводе: {out!r}"


def test_capital_efficiency_bps_is_converted_exactly_not_guessed():
    out = H.humanize_body(
        "capital-efficiency LAZY: 15% deployable capital idle at 0% "
        "— ~127bps/yr forgone (allocator left safe headroom unused)"
    )
    assert "15%" in out
    assert "127 б.п." in out
    # 127 bps == 1.27% — ТОЧНЫЙ перевод, не «примерно полтора процента».
    assert "1.27% годовых" in out


def test_capital_efficiency_without_bps_estimate_stays_honest():
    # Мониторинг не всегда знает forgone-оценку — тогда её и не должно быть.
    out = H.humanize_body(
        "capital-efficiency LAZY: 15% deployable capital idle at 0% "
        "(allocator left safe headroom unused)"
    )
    assert "15%" in out
    assert "б.п." not in out


def test_agent_label_keeps_the_technical_id():
    # Владелец должен уметь назвать агента по имени в ответе — id не прячем.
    out = H.humanize_body("⚠️ com.spa.daily_cycle — last_exit=1")
    assert "com.spa.daily_cycle" in out
    assert "ежедневный цикл" in out
    assert "код выхода 1" in out


def test_leading_icon_is_preserved():
    out = H.humanize_body("⚠️ autopush lag 239.4h (>2h)")
    assert out.startswith("⚠️")


# ─── 3. Никакой потери информации ────────────────────────────────────────────
def test_unknown_line_passes_through_verbatim():
    # ЯДРО контракта: правила нет → строка доходит как есть. Иначе перевод
    # мог бы молча съесть проблему, ради которой алерт и послан.
    raw = "⚠️ квантовый флюкс-конденсатор рассинхронизирован 4.2ГГц (>4.0)"
    assert H.humanize_body(raw) == raw


def test_mixed_body_translates_known_and_keeps_unknown():
    body = "autopush lag 2.5h (>2h)\nsomething nobody has ever seen before"
    out = H.humanize_body(body).split("\n")
    assert "GitHub" in out[0]
    assert out[1] == "something nobody has ever seen before"


def test_every_number_of_the_owner_example_survives():
    # Побайтовая проверка «ничего не выдумано и ничего не потеряно» на реальном
    # алерте владельца: каждое число из исходника обязано быть в переводе.
    out = H.humanize_body(OWNER_EXAMPLE_BODY, title="SPA Agent Health — CRITICAL")
    for number in re.findall(r"\d+(?:\.\d+)?", OWNER_EXAMPLE_BODY):
        assert number in out, f"число {number} потеряно при переводе"


def test_owner_example_has_no_leftover_operator_jargon():
    out = H.humanize_body(OWNER_EXAMPLE_BODY, title="SPA Agent Health — CRITICAL")
    for jargon in ("last_exit=", "stale", "SLA", "lag", "bps/yr", "issue(s) found"):
        assert jargon not in out, f"жаргон {jargon!r} остался: {out!r}"


def test_duplicate_header_line_is_dropped_once():
    # Мониторы дублируют шапку внутри тела (владелец видел заголовок дважды).
    out = H.humanize_body(OWNER_EXAMPLE_BODY, title="SPA Agent Health — CRITICAL")
    assert "Проверка агентов" not in out
    assert out.startswith("Статус:")


def test_duplicate_header_dropped_only_at_the_top():
    # Тот же текст ПОСРЕДИ тела — это уже содержание, его не выбрасываем.
    body = "autopush lag 2.5h (>2h)\nSPA Agent Health Alert"
    out = H.humanize_body(body, title="SPA Agent Health Alert").split("\n")
    assert len(out) == 2, "строка посреди тела не должна исчезать"
    assert out[1] == "Проверка агентов"  # переведена, но НЕ выброшена


def test_body_without_title_keeps_its_own_header():
    out = H.humanize_body("SPA Agent Health Alert\nautopush lag 2.5h (>2h)")
    assert out.startswith("Проверка агентов")


# ─── 3b. Site Custodian (карточка владельца 2026-07-20) ──────────────────────
CUSTODIAN_MSG = (
    "🛡️ SITE CUSTODIAN — 2 FAIL(s) @ 2026-07-29T10:00:00Z\n"
    "  [CRITICAL] OVERSTATED_METRIC: home shows APY 8.0% > live API 3.3% (+0.2pp tol)\n"
    "  [FAIL] STALE_SNAPSHOT: snapshot as_of 2026-07-25 is 96.0h old (> 24h)\n"
    "  ⛔ KILL-RULE: site set to DEGRADED (SNAPSHOT_OVERSTATED)"
)


def test_site_custodian_alert_becomes_readable_without_losing_detail():
    out = H.humanize_body(CUSTODIAN_MSG)
    assert "Сайт-сторож: нашёл проблем — 2" in out
    assert "сайт показывает доходность ВЫШЕ реальной" in out
    assert "снимок данных для сайта устарел" in out
    assert "правило защиты" in out and "SNAPSHOT_OVERSTATED" in out
    # Detail-хвост тоже по-русски (owner-задание 2026-08-04). ДО этой правки две
    # проверки ниже требовали, чтобы хвост дожил ДОСЛОВНО ПО-АНГЛИЙСКИ
    # ("home shows APY 8.0% > live API 3.3% (+0.2pp tol)" / "snapshot as_of …
    # is 96.0h old (> 24h)") — то есть пинили ровно тот текст, на который
    # владелец пожаловался 04.08. Проверка не ослаблена, а УСИЛЕНА: вместо
    # одной англоязычной подстроки теперь сверяется КАЖДОЕ число исходной строки
    # (тест ниже) — потерять данные стало труднее, а не легче.
    # Обоснование + запись: docs/journal/2026-W32.md (инвариант #16).
    assert "страница «home» показывает 8.0% годовых" in out
    assert "живой API — 3.3% (допуск 0.2 п.п.)" in out
    assert "снимок сделан 2026-07-25, ему уже 96.0 ч — норма не старше 24 ч" in out
    assert "shows APY" not in out and "is 96.0h old" not in out


def test_no_number_or_date_is_lost_in_translation():
    """Контракт «никакой потери информации»: каждое число/дата исходника — в выводе."""
    out = H.humanize_body(CUSTODIAN_MSG)
    numbers = re.findall(r"\d+(?:[.\-:]\d+)*", CUSTODIAN_MSG)
    assert numbers, "в примере обязаны быть числа, иначе тест ничего не проверяет"
    for token in numbers:
        assert token in out, f"число/дата {token!r} потеряно при переводе"


@pytest.mark.parametrize("raw, expect", [
    ("  [FAIL] STALE_SNAPSHOT: snapshot as_of 2026-08-03 is 32.9h old (> 30h)",
     "снимок сделан 2026-08-03, ему уже 32.9 ч — норма не старше 30 ч"),
    ("  [FAIL] STALE_API: API last bar 2026-08-02 is 48.5h old (> 30h)",
     "последняя запись API — 2026-08-02, ей уже 48.5 ч — норма не старше 30 ч"),
    ("  [FAIL] MISSING_ASOF: snapshot has no parseable as_of",
     "у самого снимка данных дата не читается"),
    ("  [FAIL] MISSING_ASOF: track page has no as-of label",
     "на странице «track» нет отметки «данные на …»"),
    ("  [FAIL] SITE_BEHIND_SNAPSHOT: home as-of 2026-07-17 != snapshot as_of 2026-08-04",
     "на странице «home» дата 2026-07-17, а в свежем снимке 2026-08-04"),
    ("  [FAIL] SITE_BEHIND_SNAPSHOT: site real_track_days=30 != snapshot real_track_days=42",
     "на сайте real_track_days = 30, а в снимке 42"),
    ("  [FAIL] SNAPSHOT_BEHIND_API: snapshot days=26 != API days=42",
     "в снимке дней трека 26, а по API 42"),
    ("  [FAIL] UNAVAILABLE: https://earn-defi.com/pilot/ -> HTTP 404",
     "https://earn-defi.com/pilot/ отвечает кодом HTTP 404"),
    ("  [FAIL] VERIFIER_PIN_MISMATCH: live verify_spa.py 1a2b3c4d5e6f… != pin 9f8e7d6c5b4a…",
     "на сайте лежит версия 1a2b3c4d5e6f…, а закреплена 9f8e7d6c5b4a…"),
])
def test_every_custodian_detail_format_is_translated(raw, expect):
    """Каждый формат detail, который умеет писать site_freshness_monitor.py."""
    out = H.humanize_body(raw)
    assert expect in out
    # Латиницы из англоязычной формулировки не остаётся (URL/имена полей — можно).
    assert " is " not in out and " != " not in out and " -> " not in out


def test_owner_exact_complaint_2026_08_04_is_fully_readable():
    """Ровно то сообщение, на которое пожаловался владелец (inbox 04.08)."""
    raw = ("🛡️ SITE CUSTODIAN — 1 FAIL(s) @ 2026-08-04T08:51:55Z\n"
           "  [FAIL] STALE_SNAPSHOT: snapshot as_of 2026-08-03 is 32.9h old (> 30h)")
    out = H.humanize_body(raw)
    assert out == (
        "🛡️ Сайт-сторож: нашёл проблем — 1 (2026-08-04T08:51:55Z)\n"
        "  [проблема] снимок данных для сайта устарел — "
        "снимок сделан 2026-08-03, ему уже 32.9 ч — норма не старше 30 ч"
    )


def test_unknown_detail_format_passes_through_verbatim():
    """Новый формат хвоста появится раньше правила — он обязан дойти как есть."""
    raw = "  [FAIL] STALE_SNAPSHOT: some brand new phrasing nobody parsed yet"
    out = H.humanize_body(raw)
    assert "снимок данных для сайта устарел" in out      # код переведён
    assert "some brand new phrasing nobody parsed yet" in out  # хвост вербатим


def test_broken_detail_rule_does_not_kill_the_alert(monkeypatch):
    def boom(_match):
        raise RuntimeError("правило хвоста сломалось")

    monkeypatch.setattr(
        H, "_DETAIL_RULES",
        ((re.compile(r"^snapshot as_of .*$"), boom),), raising=True,
    )
    raw = "  [FAIL] STALE_SNAPSHOT: snapshot as_of 2026-08-03 is 32.9h old (> 30h)"
    assert H.humanize_body(raw) == raw  # исходник, исключения нет


def test_site_custodian_indentation_is_preserved():
    out = H.humanize_body(CUSTODIAN_MSG).split("\n")
    assert out[1].startswith("  ["), "отступ — часть структуры сообщения"


def test_unknown_custodian_code_keeps_the_code_itself():
    # Новый код появится раньше словаря — владелец должен увидеть хотя бы код.
    out = H.humanize_body("  [FAIL] BRAND_NEW_CODE: something happened")
    assert "BRAND_NEW_CODE" in out and "something happened" in out


# ─── 4. Fail-safe: алерт обязан дойти ────────────────────────────────────────
@pytest.mark.parametrize("bad", [None, "", 0])
def test_falsy_inputs_are_returned_unchanged(bad):
    assert H.humanize_title(bad) == bad
    assert H.humanize_body(bad) == bad


def test_non_string_body_does_not_raise():
    # Сломанный вызывающий не должен уронить доставку алерта.
    assert H.humanize_body(12345) == 12345
    assert H.humanize_title(["broken"]) == ["broken"]


def test_broken_rule_table_falls_back_to_raw_text(monkeypatch):
    def boom(_match):
        raise RuntimeError("правило сломалось")

    monkeypatch.setattr(
        H, "_RULES", ((re.compile(r"^autopush lag .*$"), boom),), raising=True
    )
    raw = "autopush lag 239.4h (>2h)"
    assert H.humanize_body(raw) == raw  # вернулся исходник, исключения нет


def test_humanize_returns_pair():
    title, body = H.humanize("SPA Watchdog", "autopush lag 2.5h (>2h)")
    assert title == "Сторож агентов"
    assert "GitHub" in body


# ─── 5. Интеграция с push_policy (только рендер, гейт не тронут) ─────────────
@pytest.fixture()
def sent(monkeypatch):
    captured: list[str] = []
    monkeypatch.setattr(
        push_policy, "_send", lambda text: (captured.append(text), True)[1]
    )
    return captured


def test_tier1_push_arrives_in_plain_russian(tmp_path, sent):
    push_policy.push_critical(
        "agent_health_critical",
        "CRITICAL",
        "SPA Agent Health — CRITICAL",
        OWNER_EXAMPLE_BODY,
        data_dir=str(tmp_path),
    )
    assert len(sent) == 1
    msg = sent[0]
    assert "🚨 <b>Агенты: критическая проблема</b>" in msg
    assert "GitHub" in msg and "go-live" in msg
    assert "last_exit=" not in msg and "issue(s) found" not in msg
    for number in ("26.7", "32.7", "239.4", "378.9", "127", "15"):
        assert number in msg


def test_humanize_failure_still_delivers_the_raw_alert(tmp_path, sent, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("humanize упал")

    monkeypatch.setattr(H, "humanize", boom, raising=True)
    push_policy.push_critical(
        "cycle_failed", "CRITICAL", "SPA FAIL-SAFE: safety check error",
        "raw body", data_dir=str(tmp_path),
    )
    assert len(sent) == 1, "алерт обязан дойти даже если перевод сломан"
    assert "SPA FAIL-SAFE: safety check error" in sent[0]
    assert "raw body" in sent[0]


def test_gate_still_blocks_offlist_events(tmp_path, sent):
    # Перевод НЕ должен был ослабить закрытый whitelist (fail-CLOSED).
    assert push_policy.push_critical(
        "definitely_not_whitelisted", "CRITICAL", "SPA Watchdog", "b",
        data_dir=str(tmp_path),
    ) is False
    assert sent == []


def test_edge_trigger_still_silences_a_persistent_condition(tmp_path, sent):
    for _ in range(3):
        push_policy.push_critical(
            "system_critical", "CRITICAL", "SPA System Health — CRITICAL", "b",
            data_dir=str(tmp_path),
        )
    assert len(sent) == 1, "edge-trigger должен остаться level-независимым"
