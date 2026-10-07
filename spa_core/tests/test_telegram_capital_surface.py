"""ADR-612 — Telegram Capital surface: read-only, same readers as Director OS, honest UNKNOWN.

Each test pins one property the owner named in the overnight epic (2026-10-07):
* every screen renders from the canonical readers (fixtures here), with source + data age;
* a reader that is absent / throws / is stale says so — never a number, never «ok»;
* a bool is never printed as a count (the Sherlock «True» defect, RM-TRUTH-01 Wave 2);
* keyboards only navigate (``nav:``) — no ``act:``, nothing that could move money;
* «/btc купи …» still only OPENS the view; free text that reads as «move money» is refused
  deterministically BEFORE the LLM classifier and is filed nowhere.

Hermetic: readers are injected, the classifier is never run, nothing is sent.
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.telegram import money_intent
from spa_core.telegram.views import capital as C

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)   # FROZEN-DATE-OK: injected-clock — READERS["now"]
NOW_MS = int(NOW.timestamp() * 1000)
REPO = Path(__file__).resolve().parents[2]
PATHS = ("capital", "capital.btc", "capital.lab", "capital.oracle", "capital.sherlock")


def _cell(value, state="MEASURED", reason=None, as_of=NOW_MS):
    return {"value": value, "state": state, "reason": reason, "as_of": as_of, "metric_type": "X", "source": "s"}


def lab_doc(as_of_ms=NOW_MS - 10 * 60_000):
    cid = "donchian@v1:BTC:1D:spot_long:0facf75089"
    return {
        "engine_health": _cell("HEALTHY", as_of=as_of_ms),
        "evidence_integrity": _cell("VERIFIED"),
        "strategies_researched": _cell(138),
        "robustness_pass": _cell({"backtest_qualified": 5, "robust": 0}),
        "forward_paper_active": _cell(5),
        "champions": _cell(0, state="MEASURED_ZERO"),
        "btc_signal_consensus_by_timeframe": _cell({"1D": {"long": 38, "flat": 7, "short": 1}}),
        "latest_btc_signal_forward": _cell({cid: {"timeframe": "1D", "position_held": 1, "action": "HOLD"}}),
        "forward_periods": _cell({cid: 5}),
        "performance_since_forward_start": _cell({cid: {"net_return": 0.0089, "days_elapsed": 4.0}}),
        "drawdown_forward": _cell({cid: -0.0088}),
        "last_observation": _cell({cid: {"bar_close_time": NOW_MS - 3_600_000}}),
        "live_capital": _cell(0, state="MEASURED_ZERO"),
    }


CIO_OK = {"state": "MEASURED", "ledger": {"chain_ok": True},
          "recommendation": {"stance": "INSUFFICIENT_EVIDENCE", "confidence": "LOW",
                             "generated_at": (NOW - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                             "evidence_cutoff_complete": False, "executes": False, "real_capital_usd": 0},
          "research_universe": {"cio_eligible": []}}
RF_OK = {"schema": "rf/v1", "generated_at": (NOW - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "denominators": {"scanned": 17060, "discovered": 90},
         "sherlock": {"reviewed_today": True, "evidence_ready": 1, "paper_active": 1, "cio_eligible": 0,
                      "counterparty_unknown": 66, "stale_evidence": 6,
                      "top_blockers": [{"gate": "fees_measured", "count": 72}]}}


@pytest.fixture
def readers(monkeypatch):
    state = {"lab": lab_doc(), "cio": CIO_OK, "rf": RF_OK}
    monkeypatch.setitem(C.READERS, "now", lambda: NOW)
    monkeypatch.setitem(C.READERS, "data_dir", lambda: Path("/nonexistent"))
    monkeypatch.setitem(C.READERS, "lab", lambda d: state["lab"])
    monkeypatch.setitem(C.READERS, "cio", lambda d, now: state["cio"])
    monkeypatch.setitem(C.READERS, "research", lambda d: state["rf"])
    return state


def _render(path):
    from spa_core.telegram.views import get_builder
    return get_builder(path)(arg="", lang="ru", page=0, prefs={})


def test_every_capital_screen_renders_with_boundary_source_and_nav_only_keyboard(readers):
    for path in PATHS:
        text, kb = _render(path)
        assert C.BOUNDARY in text, path
        cbs = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
        assert cbs and all(cb.startswith("nav:") for cb in cbs), (path, cbs)
        assert "view error" not in text


def test_screens_print_what_the_readers_measured(readers):
    lab, _ = _render("capital.lab")
    assert "Стратегий исследовано: 138" in lab and "На бумажном форвард-тесте: 5" in lab
    assert "+0.89%" in lab and "-0.88%" in lab and "10 мин назад" in lab
    btc, _ = _render("capital.btc")
    assert "НЕ приказ на сделку" in btc and "лонг 38" in btc
    oracle, _ = _render("capital.oracle")
    assert "НЕ имеет права исполнения" in oracle and "недостаточно" in oracle and "Исполняет сам: нет" in oracle
    sh, _ = _render("capital.sherlock")
    assert "С готовыми доказательствами: 1" in sh and "не измерены комиссии — 72" in sh


@pytest.mark.parametrize("path", PATHS)
def test_a_reader_that_throws_is_not_measured_never_a_number(readers, monkeypatch, path):
    def boom(*a, **k):
        raise OSError("disk")
    for key in ("lab", "cio", "research"):
        monkeypatch.setitem(C.READERS, key, boom)
    text, kb = _render(path)
    assert "не измерено" in text
    assert "138" not in text and "$0 ·" in text            # boundary still there; no stale number
    assert all(b["callback_data"].startswith("nav:") for row in kb["inline_keyboard"] for b in row)


def test_not_measured_cells_carry_the_reader_reason_without_home_path(readers):
    home = str(Path.home())
    readers["lab"] = {"engine_health": _cell(None, state="NOT_MEASURED",
                                             reason=f"status.json не найден по пути {home}/x"),
                      "strategies_researched": _cell(None, state="NOT_MEASURED", reason="evidence.db не найден")}
    text, _ = _render("capital.lab")
    assert "не измерено (evidence.db не найден)" in text
    assert home not in text


def test_stale_lab_is_flagged_not_presented_as_fresh(readers):
    readers["lab"] = lab_doc(as_of_ms=NOW_MS - 6 * 3_600_000)      # read_model.STALE_AFTER_H = 2
    for path in ("capital.lab", "capital.btc"):
        text, _ = _render(path)
        assert "УСТАРЕЛО" in text, path


def test_future_timestamp_is_distrusted(readers):
    readers["lab"] = lab_doc(as_of_ms=NOW_MS + 3 * 3_600_000)
    text, _ = _render("capital.lab")
    assert "НЕДОСТОВЕРНЫМ" in text


def test_oracle_broken_chain_withdraws_and_absent_recommendation_is_unknown(readers):
    readers["cio"] = {"integrity": "BROKEN"}
    assert "ОТОЗВАНА" in _render("capital.oracle")[0]
    readers["cio"] = {"state": "NOT_MEASURED", "reason": "no CIO recommendation yet"}
    text = _render("capital.oracle")[0]
    assert "не измерено" in text and "Позиция" not in text


def test_oracle_staleness_threshold_is_mission_controls_not_a_copy(readers):
    readers["cio"] = {**CIO_OK, "recommendation": {**CIO_OK["recommendation"],
                      "generated_at": (NOW - timedelta(hours=40)).strftime("%Y-%m-%dT%H:%M:%SZ")}}
    assert C._mc_stale_after_min("capital.investment_cio") == 1800
    assert "УСТАРЕЛО" in _render("capital.oracle")[0]               # 40 h > 30 h


def test_a_bool_is_never_printed_as_a_count(readers):
    readers["rf"] = {**RF_OK, "sherlock": {**RF_OK["sherlock"], "evidence_ready": True, "paper_active": False}}
    text = _render("capital.sherlock")[0]
    assert "С готовыми доказательствами: не измерено" in text
    assert "На бумажном тесте: не измерено" in text
    assert "True" not in text and "False" not in text


def test_sherlock_absent_block_is_unknown(readers):
    readers["rf"] = {"schema": "rf/v1", "generated_at": None}
    text = _render("capital.sherlock")[0]
    assert "Сводка Sherlock: не измерено" in text


# ── routing: a read command only OPENS a view ───────────────────────────────────────────────────
class _T:
    def __init__(self):
        self.sent = []
        self.edits = []

    def send_message(self, chat_id, text, kb):
        self.sent.append((text, kb))
        return {"ok": True, "result": {"message_id": 100 + len(self.sent)}}

    def edit_message_text(self, chat_id, message_id, text, kb):
        self.edits.append((message_id, text, kb))
        return {"ok": True}

    def answer_callback(self, callback_id):
        return None


def _router(R):
    r = R.Router(_T(), "42")
    r.spawn = lambda fn: fn()          # inline worker: deterministic
    return r


@pytest.mark.parametrize("cmd,path", [("/capital", "capital"), ("/btc", "capital.btc"), ("/lab", "capital.lab"),
                                      ("/oracle", "capital.oracle"), ("/sherlock", "capital.sherlock"),
                                      ("/btc купи 1 BTC сейчас", "capital.btc"), ("/oracle@spa_bot", "capital.oracle")])
def test_read_commands_route_to_their_view_and_nothing_else(readers, monkeypatch, cmd, path):
    from spa_core.telegram import router as R
    monkeypatch.setattr(R.prefs_store, "get_prefs", lambda chat_id: {})
    monkeypatch.setattr(R.prefs_store, "get_lang", lambda chat_id: "ru")
    r = _router(R)
    r.handle_command(cmd, "42")
    t = r.transport
    assert t.sent[0][0] == R.SLOW_PLACEHOLDER                    # answered at once
    mid, text, kb = t.edits[-1]                                   # then the screen, same message
    assert mid == 101
    assert text.startswith(R.html_safe(_render(path)[0]).split("\n")[0])
    assert all(b["callback_data"].startswith("nav:") for row in kb["inline_keyboard"] for b in row)


def test_a_tap_on_a_capital_button_edits_in_place(readers, monkeypatch):
    from spa_core.telegram import router as R
    monkeypatch.setattr(R.prefs_store, "get_prefs", lambda chat_id: {})
    monkeypatch.setattr(R.prefs_store, "get_lang", lambda chat_id: "ru")
    r = _router(R)
    r.handle_callback("nav:capital.lab", "42", 555, "cb")
    t = r.transport
    assert [e[0] for e in t.edits] == [555, 555] and t.edits[0][1] == R.SLOW_PLACEHOLDER
    assert "Стратегий исследовано: 138" in t.edits[1][1] and not t.sent


def test_slow_render_does_not_block_the_poll_loop_and_refuses_a_pile_up(readers, monkeypatch):
    import threading
    from spa_core.telegram import router as R
    monkeypatch.setattr(R.prefs_store, "get_prefs", lambda chat_id: {})
    monkeypatch.setattr(R.prefs_store, "get_lang", lambda chat_id: "ru")
    gate = threading.Event()
    monkeypatch.setitem(C.READERS, "lab", lambda d: gate.wait(5) and lab_doc())
    r = R.Router(_T(), "42")                                      # REAL thread
    r.handle_command("/lab", "42")                                # returns at once (render waits on gate)
    assert r.transport.sent[0][0] == R.SLOW_PLACEHOLDER and not r.transport.edits
    r.handle_command("/btc", "42")                                # second while first renders
    assert r.transport.sent[-1][0] == R.SLOW_BUSY
    gate.set()
    for _ in range(100):
        if r.transport.edits:
            break
        threading.Event().wait(0.05)
    assert r.transport.edits and "138" in r.transport.edits[-1][1]
    for _ in range(100):                                          # release happens after the edit
        if R._slow_state["token"] is None:
            break
        threading.Event().wait(0.02)
    assert R._slow_state["token"] is None


def test_a_render_that_crashes_still_releases_the_lock(readers, monkeypatch):
    from spa_core.telegram import router as R
    monkeypatch.setattr(R.prefs_store, "get_prefs", lambda chat_id: {})
    monkeypatch.setattr(R.prefs_store, "get_lang", lambda chat_id: "ru")
    r = _router(R)
    monkeypatch.setattr(r, "render_view", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    r.handle_command("/lab", "42")
    assert R._slow_state["token"] is None


def test_non_owner_gets_no_capital_screen(readers, monkeypatch):
    from spa_core.telegram import router as R
    t = _T()
    R.Router(t, "42").handle_command("/capital", "999")
    assert len(t.sent) == 1 and "Капитал" not in t.sent[0][0]


def test_capital_tree_has_no_action_children():
    from spa_core.telegram import menus
    for p in PATHS:
        assert p in menus.TREE
        for child in menus.TREE[p]["children"]:
            assert child.startswith("capital."), child


def test_capital_modules_import_neither_execution_nor_company_truth():
    for rel in ("spa_core/telegram/views/capital.py", "spa_core/telegram/money_intent.py"):
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
                names.update(f"{node.module}.{a.name}" for a in node.names)
            elif isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
        assert not [n for n in names if "execution" in n or "company_truth" in n], (rel, names)


# ── free text / voice: «move money» is refused before the classifier ────────────────────────────
#: re-review 07.10: ordinary owner questions the noun-stem version refused
RE_REVIEW_QUESTIONS = ["какой вывод по пулу aave?", "как дела с инвестиционным капиталом?",
                       "почему лонги по btc в лаборатории?", "положение портфеля сегодня?",
                       "объясни стратегию шорт btc", "отправь отчёт по портфелю",
                       "what is the short interest on btc?"]

REVIEW_BYPASSES = ["покупай биткоин", "докупи эфира", "давай купим биткоин", "продавай btc",
                   "зашорти btc на 10к", "отправь 1000 usdc на кошелек", "переложи деньги в aave",
                   "положи 50к в sUSDe", "закинь 10 тысяч в пул", "купи на все", "long btc 5x"]

#: orchestrator spot-check 07.10: withdraw / liquidate / go-live orders that slipped through
SPOT_CHECK_ORDERS = ["сними 5000 с пула", "ликвидируй всё", "включи live торговлю",
                     "enable live trading", "выйди из позиции по btc", "снять деньги с aave"]
SPOT_CHECK_NOT_ORDERS = ["включи отчёт", "запусти тесты", "почему не включено исполнение?",
                         "сними скриншот", "включи уведомления", "что с live торговлей?"]


@pytest.mark.parametrize("text", ["купи биткоин на 1000", "продай весь BTC", "Buy 0.5 btc now",
                                  "переведи 500 USDC на кошелёк", "открой лонг по биткоину",
                                  "вложить деньги в sUSDe", "sell all positions"] + REVIEW_BYPASSES
                         + SPOT_CHECK_ORDERS)
def test_money_action_phrases_are_detected(text):
    assert money_intent.is_money_action(text)


@pytest.mark.parametrize("text", ["что с биткоином?", "покажи лабораторию", "купить зонт в пятницу",
                                  "/btc купи", "/btc", "/capital", "как дела у Oracle", "сколько капитала в работе",
                                  "почему капитал $0?", "", "покажи капитал", "сколько стоит биткоин",
                                  "проверь Morpho", "что в пуле aave?", "расскажи про портфель",
                                  "купи 2 пачки молока", "купить зонт за 300", "почему Oracle держит кэш"]
                         + RE_REVIEW_QUESTIONS + SPOT_CHECK_NOT_ORDERS)
def test_read_questions_and_unrelated_tasks_are_not_money_actions(text):
    assert not money_intent.is_money_action(text)


def test_money_text_is_refused_before_the_classifier_and_filed_nowhere(monkeypatch):
    from spa_core.telegram import ask_router, inbox_intake
    from spa_core.telegram import bot as Bmod
    called = {"classifier": 0, "saved": 0}
    monkeypatch.setattr(ask_router, "classify_and_answer",
                        lambda m: called.__setitem__("classifier", called["classifier"] + 1) or ("task", ""))
    monkeypatch.setattr(inbox_intake, "save_inbox_task",
                        lambda *a, **k: called.__setitem__("saved", called["saved"] + 1) or (None, "x"))
    bot = object.__new__(Bmod.TelegramBot)
    sent = []
    bot.send_message = lambda text, chat_id=None, **kw: sent.append(text)
    bot._classify_route("купи биткоин на 1000", "42", source="voice")
    assert called == {"classifier": 0, "saved": 0}
    assert sent and "НЕ исполняю" in sent[0]
    # and an ordinary sentence still reaches the classifier exactly as before
    bot._classify_route("проверь Morpho", "42", source="telegram")
    assert called["classifier"] == 1


# ── review fixes (07.10): each with a positive control ─────────────────────────────────────────
def _bare_text_bot(monkeypatch, tmp_path):
    """A bot whose bare-text path is real down to the guard; nothing leaves the process."""
    from spa_core.telegram import ask_router, inbox_intake, long_message
    from spa_core.telegram import bot as Bmod
    calls = {"collector": 0, "classifier": 0, "saved": 0}
    monkeypatch.setattr(long_message, "store_path", lambda data_dir=None: tmp_path / "pending.json")
    monkeypatch.setattr(ask_router, "classify_and_answer",
                        lambda m: calls.__setitem__("classifier", calls["classifier"] + 1) or ("task", ""))
    monkeypatch.setattr(inbox_intake, "save_inbox_task",
                        lambda *a, **k: calls.__setitem__("saved", calls["saved"] + 1) or (None, "x"))
    bot = object.__new__(Bmod.TelegramBot)
    sent = []
    bot.send_message = lambda text, chat_id=None, **kw: sent.append(text)
    orig = Bmod.TelegramBot._handle_long_document
    monkeypatch.setattr(bot, "_handle_long_document",
                        lambda t, c: calls.__setitem__("collector", calls["collector"] + 1) or orig(bot, t, c),
                        raising=False)
    bot._handle_owner_text_answer = lambda *a, **k: False
    bot._handle_card_query = lambda *a, **k: False
    bot._get_router = lambda: type("R", (), {"is_owner": staticmethod(lambda c: True)})()
    return bot, sent, calls


@pytest.mark.parametrize("text", REVIEW_BYPASSES[:4])
def test_money_text_is_refused_before_the_long_document_collector(monkeypatch, tmp_path, text):
    bot, sent, calls = _bare_text_bot(monkeypatch, tmp_path)
    bot._handle_inbox_intake({"text": text}, text, "42")
    assert calls == {"collector": 0, "classifier": 0, "saved": 0}, calls
    assert sent and "НЕ исполняю" in sent[0]


def test_a_document_part_is_never_refused_its_words_are_kept(monkeypatch, tmp_path):
    from spa_core.telegram import long_message as lm
    bot, sent, calls = _bare_text_bot(monkeypatch, tmp_path)
    part = ("купи btc " + "спецификация " * 400)[: lm.CONTINUATION_MIN_CHARS + 10]
    bot._handle_inbox_intake({"text": part}, part, "42")
    assert calls["collector"] == 1 and not any("НЕ исполняю" in t for t in sent)


def test_inbox_card_with_money_text_is_stamped_suspected(tmp_path, monkeypatch):
    from spa_core.owner_queue import queue as Q
    from spa_core.telegram import inbox_intake as I
    monkeypatch.setattr(Q, "TRACKER_DIR", tmp_path)
    p, _ = I.save_inbox_task("обсудить: положить 50к в sUSDe?", source="telegram")
    txt = Path(p).read_text(encoding="utf-8")
    assert "money_intent: suspected" in txt and "Это НЕ приказ" in txt
    p2, _ = I.save_inbox_task("починить кнопку отчёта", source="telegram")
    assert "money_intent" not in Path(p2).read_text(encoding="utf-8")          # control
    p3, _ = I.save_inbox_document("купи 10к btc " + "x " * 50, "2 части")
    assert "money_intent: suspected" in Path(p3).read_text(encoding="utf-8")


def test_overview_does_not_print_a_broken_sherlock_counter(readers):
    readers["rf"] = {**RF_OK, "integrity": "BROKEN", "sherlock": {**RF_OK["sherlock"], "evidence_ready": 5}}
    text = _render("capital")[0]
    assert "повреждён" in text and "доказательствами 5" not in text
    readers["rf"] = {"sherlock": {"evidence_ready": 5}}                        # no schema
    text = _render("capital")[0]
    assert "Sherlock: не измерено" in text and "5" not in text.split("Sherlock:")[1].split("\n")[0]
    readers["rf"] = RF_OK                                                       # control
    assert "доказательствами 1" in _render("capital")[0]


def test_overview_oracle_carries_age_and_stale_flag(readers):
    assert "2 ч назад" in _render("capital")[0] and "УСТАРЕЛО" not in _render("capital")[0]
    readers["cio"] = {**CIO_OK, "recommendation": {**CIO_OK["recommendation"],
                      "generated_at": (NOW - timedelta(hours=40)).strftime("%Y-%m-%dT%H:%M:%SZ")}}
    assert "УСТАРЕЛО" in _render("capital")[0]
    readers["cio"] = {"integrity": "BROKEN"}
    assert "отозвана" in _render("capital")[0]


def test_a_bool_is_not_zero_dollars(readers):
    readers["lab"] = {**lab_doc(), "live_capital": _cell(False)}
    assert "по журналу лаборатории: не измерено" in _render("capital")[0]
    readers["cio"] = {**CIO_OK, "recommendation": {**CIO_OK["recommendation"], "real_capital_usd": False}}
    assert "по его журналу: не измерено" in _render("capital.oracle")[0]
    readers["lab"] = lab_doc()                                                  # control: 0 ⇒ $0
    assert "по журналу лаборатории: $0" in _render("capital")[0]


def test_undelivered_screen_is_said_not_left_as_a_placeholder(readers, monkeypatch):
    from spa_core.telegram import router as R
    monkeypatch.setattr(R.prefs_store, "get_prefs", lambda chat_id: {})
    monkeypatch.setattr(R.prefs_store, "get_lang", lambda chat_id: "ru")
    r = _router(R)
    r.transport.edit_message_text = lambda *a, **k: None                        # Telegram refused
    r.handle_command("/lab", "42")
    assert "Экран не собран" in r.transport.sent[-1][0] and "не измерено" in r.transport.sent[-1][0]
    r2 = _router(R)
    monkeypatch.setattr(r2, "render_view", lambda *a, **k: (_ for _ in ()).throw(KeyError("x")))
    r2.handle_command("/lab", "42")
    assert "Экран не собран (KeyError)" in r2.transport.sent[-1][0]
    r3 = _router(R)                                                             # control
    r3.handle_command("/lab", "42")
    assert not any("Экран не собран" in t for t, _ in r3.transport.sent)


def test_edit_path_fits_long_text():
    from spa_core.telegram import bot as Bmod
    b = object.__new__(Bmod.TelegramBot)
    seen = {}
    b._api_call = lambda method, params, **kw: seen.update(params) or {"ok": True}
    b.edit_message_text("42", 7, "<b>x</b> " + "а" * 6000)
    assert len(seen["text"]) <= Bmod.TG_TEXT_LIMIT


def test_a_hung_render_slot_is_reclaimed_after_the_deadline(monkeypatch):
    from spa_core.telegram import router as R
    t0 = 1_000_000.0
    tok = R._slow_acquire(t0)
    assert tok is not None and R._slow_acquire(t0 + 10) is None              # held
    tok2 = R._slow_acquire(t0 + R.SLOW_LOCK_DEADLINE_S + 1)                   # reclaimed
    assert tok2 is not None
    R._slow_release(tok)                                                      # stale owner: ignored
    assert R._slow_acquire(t0 + R.SLOW_LOCK_DEADLINE_S + 2) is None
    R._slow_release(tok2)
    assert R._slow_acquire(t0 + R.SLOW_LOCK_DEADLINE_S + 3) is not None      # control
    R._slow_release(R._slow_state["token"])


def test_questions_are_not_orders_but_an_explicit_imperative_still_is():
    assert not money_intent.is_money_action("почему не купить btc?")
    assert money_intent.is_money_action("купи btc?")                       # imperative wins
    assert money_intent.is_money_action("может, купим биткоин")
    # noun stems still feed the inbox stamp (weaker, never a refusal)
    assert money_intent.is_suspected("положение портфеля: вывод 10к из aave")


def test_long_document_buffer_state_has_a_third_outcome(tmp_path, monkeypatch):
    """inv. #17: «buffer unreadable / no last-part stamp» is NOT MEASURED (None) — never
    «closed» (which would let the money guard drop the owner's words) and never a success."""
    import json as _json
    from spa_core.telegram import long_message as lm
    store = lm.store_path(tmp_path)
    store.write_text(_json.dumps({"version": 1, "pending": {"1": {"parts": ["a"], "last_at": 100.0}}}))
    assert lm.is_open("1", now=110.0, data_dir=tmp_path) is True
    assert lm.is_open("1", now=100.0 + lm.WINDOW_S + 1, data_dir=tmp_path) is False
    assert lm.is_open("2", now=110.0, data_dir=tmp_path) is False
    store.write_text(_json.dumps({"version": 1, "pending": {"1": {"parts": ["a"]}}}))
    assert lm.is_open("1", now=110.0, data_dir=tmp_path) is None
    monkeypatch.setattr(lm, "_load", lambda p: (_ for _ in ()).throw(OSError("disk")))
    assert lm.is_open("1", now=110.0, data_dir=tmp_path) is None
