"""Батарея §40 ТЗ «Portfolio CIO» — ``spa_core/analytics/release_stage_census.py``.

Прибор спрашивает, на какой ступени лестницы владельца (Stage 0…4) система стои́т ПО
ПОВЕДЕНИЮ (взвод `cio_arming`, журнал ADR-060), объявляет ли ступень хоть один артефакт
`data/*.json` словарём владельца, согласен ли ярлык записи с поведением, и какие двери есть у
стадий 2/3/4. Сцены строятся в ``tmp_path``; живой ``data/`` не читается (кроме одного теста
паритета с живой карточкой дерева).

Дни сцен — смещения от инъектированного ``now``; литеральных дат нет. Часы — ТОЛЬКО вход
``now=`` (штамп отчёта).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import textwrap
from pathlib import Path

import pytest

from spa_core.analytics import release_stage_census as R
from spa_core.analytics.transaction_economics import UNMEASURED
from spa_core.monitoring import card_acceptance as CA
from spa_core.paper_trading import cio_arming

PROBE = "release_stage_is_declared_and_matches_behaviour"
_REPO = R.REPO_ROOT
_LIVE_CARD = os.path.join(_REPO, R.CARD_REL)
NOW = dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.timezone.utc)   # FROZEN-DATE-OK: injected-clock — якорь передаётся входом now= в run(); стенные часы прибор не спрашивает
ARMED_ALL = cio_arming.ARMED_BOOKS
ARMED_NONE: dict = {}


def _day(i: int) -> str:
    return (NOW.date() - dt.timedelta(days=40) + dt.timedelta(days=i)).isoformat()


# ───────────────────────────── карточка ───────────────────────────────────────

def _card(tmp: Path, body: str) -> str:
    p = tmp / "card.md"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(p)


def _good_card_text() -> str:
    out = ["---", "title: x", "---", "39. Observation period", "что-то", "", "⸻", "", R.SECTION_HEAD, R.OWNER_LEAD]
    for s in R.OWNER_STAGES:
        out += [f"Stage {s['n']}", s["name"], *s["lines"], "", "", "⸻", ""]
    out += [R.NEXT_SECTION_HEAD, "Если будет разрешен auto-execution, предусмотреть:"]
    return "\n".join(out) + "\n"


def test_constants_agree_with_the_real_owner_card():
    p = R.parity(_LIVE_CARD)
    assert p["parsed"]["measured"], p["parsed"].get("reason")
    assert p["agrees"] is True, p["mismatches"]
    assert len(p["parsed"]["stages"]) == R.OWNER_STAGES_DECLARED == 5


def test_parity_agrees_on_a_card_in_the_owner_form(tmp_path):
    p = R.parity(_card(tmp_path, _good_card_text()))
    assert p["agrees"] is True, p["mismatches"]


def test_parity_names_a_renamed_stage(tmp_path):
    text = _good_card_text().replace("\nShadow CIO\n", "\nShadow mode\n")
    p = R.parity(_card(tmp_path, text))
    assert p["agrees"] is False and any("Stage 1" in m and "Shadow mode" in m for m in p["mismatches"])


def test_parity_names_a_drifted_meaning_line(tmp_path):
    text = _good_card_text().replace("Recommendations only.", "Recommendations and trades.")
    p = R.parity(_card(tmp_path, text))
    assert p["agrees"] is False and any("строки смысла" in m and "Stage 1" in m for m in p["mismatches"])


def test_parity_names_a_missing_stage_by_its_numbers(tmp_path):
    text = _good_card_text().replace("Stage 3\nLimited auto-execution\nТолько внутри заранее утвержденных bands.\n", "")
    p = R.parity(_card(tmp_path, text))
    assert p["agrees"] is False and any("номера стадий" in m for m in p["mismatches"])


def test_parity_names_a_missing_lead(tmp_path):
    text = _good_card_text().replace(R.OWNER_LEAD + "\n", "")
    p = R.parity(_card(tmp_path, text))
    assert p["agrees"] is False and any("нет строки" in m for m in p["mismatches"])


def test_parity_requires_the_second_boundary(tmp_path):
    text = _good_card_text().replace(R.NEXT_SECTION_HEAD, "хвост без границы")
    p = R.parity(_card(tmp_path, text))
    assert p["agrees"] is None and "вторая граница" in p["parsed"]["reason"]


def test_parity_is_unmeasured_without_a_card(tmp_path):
    p = R.parity(str(tmp_path / "none.md"))
    assert p["agrees"] is None and "не прочитана" in p["parsed"]["reason"]


# ───────────────────────────── стенд ──────────────────────────────────────────

def _rec(i: int, *, book: str | None = "conservative", extra: dict | None = None) -> dict:
    rec = {"cycle_date": _day(i), "generated_at": f"{_day(i)}T06:00:00+00:00", "verdict": "HOLD",
           "mode": "paper", "admissible_trim": {"adr": "ADR-850", "caps": {"max_trade_usd": 15000.0}}}
    if book is not None:
        rec["book_id"] = book
    if extra:
        rec.update(extra)
    return rec


def _write_journal(ddir: Path, rows: list, book: str = "conservative") -> Path:
    ddir.mkdir(parents=True, exist_ok=True)
    p = ddir / R.history_filename(book)
    with open(p, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return p


def _rationale(ddir: Path, book: str, *, mode: str | None = "SHADOW",
               note: str | None = "ADR-060 phase 0. Verdict is ADVISORY: no position was changed by it.") -> Path:
    ddir.mkdir(parents=True, exist_ok=True)
    doc = {"generated_at": f"{_day(10)}T06:00:00+00:00", "book_id": book}
    if mode is not None:
        doc["mode"] = mode
    if note is not None:
        doc["note"] = note
    p = ddir / R.rationale_filename(book)
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def _eval_file(ddir: Path, *, ready=False, statuses=("PASS", "PASS", "UNCHECKED"),
               blockade: str | None = "UNREACHABLE_UNTIL_CHANGED") -> None:
    ddir.mkdir(parents=True, exist_ok=True)
    names = ["observation_days", "hit_rate", "net_bps_if_followed"]
    doc = {"ready_to_arm": ready, "status": "READY" if ready else "NOT_READY", "observation_days": 98,
           "criteria": [{"criterion": n, "status": s} for n, s in zip(names, statuses)],
           "arming_blockade": {"verdict": blockade}}
    (ddir / R.EVAL_FILE).write_text(json.dumps(doc), encoding="utf-8")


def _limits_file(ddir: Path, *, binding=6, literal=2, absent=4, total=12) -> None:
    ddir.mkdir(parents=True, exist_ok=True)
    doc = {"generated_at": "x", "limits_total": total,
           "tally": {"BINDING": binding, "LITERAL": literal, "DECLARED_INERT": 0, "ABSENT": absent, "UNCHECKED": 0}}
    (ddir / R.LIMITS_FILE).write_text(json.dumps(doc), encoding="utf-8")


def _readiness(ddir: Path, *, live=False, custody=False, ready=False, posture="PAPER_SAFE") -> None:
    ddir.mkdir(parents=True, exist_ok=True)
    doc = {"posture": posture, "ready_for_live": ready, "audited_at": "x",
           "checks": {"execution_mode_not_live": {"ok": True, "live_mode": live},
                      "custody_connected": {"ok": True, "custody_connected": custody}}}
    (ddir / R.READINESS_FILE).write_text(json.dumps(doc), encoding="utf-8")


def _telegram(root: Path, verbs=("aa", "mute", "od")) -> None:
    d = root / R.TELEGRAM_REL
    d.mkdir(parents=True, exist_ok=True)
    (d / "bot.py").write_text("\n".join(f'X = "act:{v}:"' for v in verbs) + "\n", encoding="utf-8")


def _stand(tmp: Path, *, label_mode="SHADOW", declare=False, stage_field=False,
           verbs=("aa", "mute", "od"), binding=6, ready=False, card=True, journals=True) -> Path:
    ddir = tmp / "data"
    ddir.mkdir(parents=True, exist_ok=True)
    extra = {"armed": True} if stage_field else None
    if journals:
        for book in R.BOOKS:
            _write_journal(ddir, [_rec(i, book=book, extra=extra) for i in range(12)], book)
    for book in R.BOOKS:
        _rationale(ddir, book, mode=label_mode, note=("ADVISORY: no position was changed by it" if label_mode == "SHADOW" else "armed"))
    _eval_file(ddir, ready=ready)
    _limits_file(ddir, binding=binding, absent=12 - binding - 2 if binding <= 10 else 0, literal=2 if binding <= 10 else 0)
    _readiness(ddir)
    if declare:
        (ddir / "cio_stage.json").write_text(json.dumps({"stage": "Stage 3", "generated_at": "x"}), encoding="utf-8")
    _telegram(tmp, verbs)
    if card:
        (tmp / R.CARD_REL).parent.mkdir(parents=True, exist_ok=True)
        (tmp / R.CARD_REL).write_text(_good_card_text(), encoding="utf-8")
    return ddir


def _run(tmp: Path, ddir: Path, **kw):
    return R.run(root=str(tmp), data_dir=str(ddir), card_path=os.path.join(str(tmp), R.CARD_REL), write=False, now=NOW, **kw)


# ───────────────────────────── журнал ─────────────────────────────────────────

def test_load_journal_is_unmeasured_without_the_file(tmp_path):
    rows, why, bad = R.load_journal(str(tmp_path), "conservative")
    assert rows is None and "нет" in why and bad == 0


def test_load_journal_is_unmeasured_on_an_empty_file(tmp_path):
    _write_journal(tmp_path, [])
    rows, why, _ = R.load_journal(str(tmp_path))
    assert rows is None and "пуст" in why


def test_load_journal_routes_each_book_to_the_writers_file(tmp_path):
    _write_journal(tmp_path, [_rec(0, book="balanced")], "balanced")
    assert (tmp_path / "allocation_rationale_history_balanced.jsonl").exists()
    rows, why, _ = R.load_journal(str(tmp_path), "balanced")
    assert rows is not None and rows[0]["book_id"] == "balanced", why
    assert R.load_journal(str(tmp_path), "conservative")[0] is None


def test_load_journal_counts_corrupt_lines_instead_of_dropping_them_silently(tmp_path):
    p = _write_journal(tmp_path, [_rec(0), _rec(1)])
    with open(p, "a", encoding="utf-8") as fh:
        fh.write("{битая\n[1,2]\n")
    rows, _, bad = R.load_journal(str(tmp_path))
    assert len(rows) == 2 and bad == 2


# ───────────────────────────── ось B — поведение ──────────────────────────────

def _journals(tmp: Path, books=("conservative",), n=5, unnamed=False, **kw):
    for b in books:
        _write_journal(tmp / "data", [_rec(i, book=(None if unnamed else b), **kw) for i in range(n)], b)
    return R.load_journals(str(tmp / "data"))


def test_an_armed_book_with_records_is_auto_within_bands_and_names_its_arming(tmp_path):
    books = R.measure_books(_journals(tmp_path), armed_books=ARMED_ALL)
    c = books["conservative"]
    assert c["behaviour"] == "auto_within_bands" and c["stage_shape"] == "3/4"
    assert c["armed"] is True and c["armed_adr"] == "ADR-324" and c["armed_at"] == "2026-09-11"
    assert c["records"] == 5 and c["first_record"] == _day(0) and c["last_record"] == _day(4)


def test_an_unarmed_book_with_records_is_recommendations_only(tmp_path):
    books = R.measure_books(_journals(tmp_path), armed_books=ARMED_NONE)
    c = books["conservative"]
    assert c["behaviour"] == "recommendations_only" and c["stage_shape"] == "1" and c["armed"] is False


def test_an_unarmed_book_without_records_is_no_records(tmp_path):
    js = _journals(tmp_path)
    js["balanced"] = ([], None, 0)
    books = R.measure_books(js, armed_books=ARMED_NONE)
    assert books["balanced"]["behaviour"] == "no_records" and books["balanced"]["stage_shape"] == "0"


def test_a_book_without_a_journal_is_unmeasured_with_the_reason(tmp_path):
    books = R.measure_books(_journals(tmp_path), armed_books=ARMED_ALL)
    b = books["balanced"]
    assert b["behaviour"] == UNMEASURED and "нет" in b["reason"] and b["stage_shape"] is None
    assert b["armed"] is True  # взвод — свойство кода, оно измерено и без журнала


def test_shadow_days_before_arming_is_the_distance_from_the_first_record(tmp_path):
    armed = {"conservative": {"armed_at": (dt.date.fromisoformat(_day(0)) + dt.timedelta(days=36)).isoformat(),
                              "armed_by": "владелец", "adr": "ADR-324"}}
    books = R.measure_books(_journals(tmp_path), armed_books=armed)
    assert books["conservative"]["shadow_days_before_arming"] == 36


def test_pre_adr_309_rows_without_a_book_id_belong_to_the_file_they_are_written_in(tmp_path):
    books = R.measure_books(_journals(tmp_path, unnamed=True), armed_books=ARMED_NONE)
    assert books["conservative"]["records"] == 5


# ───────────────────────────── реальный капитал ───────────────────────────────

def test_real_capital_is_unmeasured_without_the_readiness_artifact(tmp_path):
    r = R.measure_real_capital(str(tmp_path))
    assert r["kind"] == UNMEASURED and "нет" in r["reason"]


def test_real_capital_is_not_entered_while_execution_and_custody_are_off(tmp_path):
    _readiness(tmp_path)
    r = R.measure_real_capital(str(tmp_path))
    assert r["kind"] == "not_entered" and r["live_mode"] is False and r["custody_connected"] is False
    assert r["posture"] == "PAPER_SAFE" and r["ready_for_live"] is False


def test_real_capital_is_entered_only_with_both_live_mode_and_custody(tmp_path):
    _readiness(tmp_path, live=True, custody=False)
    assert R.measure_real_capital(str(tmp_path))["kind"] == "not_entered"
    _readiness(tmp_path, live=True, custody=True, ready=True)
    assert R.measure_real_capital(str(tmp_path))["kind"] == "entered"


def test_real_capital_without_any_of_the_three_fields_is_unmeasured_not_safe(tmp_path):
    (tmp_path / R.READINESS_FILE).write_text(json.dumps({"posture": "PAPER_SAFE"}), encoding="utf-8")
    r = R.measure_real_capital(str(tmp_path))
    assert r["kind"] == UNMEASURED and "live_mode" in r["reason"] and r["posture"] == "PAPER_SAFE"


# ───────────────────────────── ось C — объявление ─────────────────────────────

def _json(ddir: Path, name: str, doc) -> None:
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / name).write_text(json.dumps(doc), encoding="utf-8")


def test_declaration_is_unmeasured_without_the_directory_or_without_json(tmp_path):
    assert R.measure_declaration(str(tmp_path / "none"))["kind"] == UNMEASURED
    (tmp_path / "d").mkdir()
    d = R.measure_declaration(str(tmp_path / "d"))
    assert d["kind"] == UNMEASURED and d["files"] == 0


def test_declaration_counts_every_mode_vocabulary_and_is_not_declared_without_the_owner_words(tmp_path):
    _json(tmp_path, "a.json", {"mode": "SHADOW", "params": {"mode": "paper"}})
    _json(tmp_path, "b.json", {"execution_mode": "read_only_simulation", "posture": "PAPER_SAFE"})
    d = R.measure_declaration(str(tmp_path))
    assert d["kind"] == "not_declared" and d["files"] == 2 and d["fields"] == 4
    assert d["fields_by_vocabulary"] == {"paper": 1, "PAPER_SAFE": 1, "read_only_simulation": 1, "SHADOW": 1}


@pytest.mark.parametrize("value", ["Stage 3", "stage_1", "STAGE-0", "Shadow CIO", "limited auto-execution"])
def test_declaration_is_declared_by_a_stage_number_or_a_stage_name(tmp_path, value):
    _json(tmp_path, "cio.json", {"release_stage": value})
    d = R.measure_declaration(str(tmp_path))
    assert d["kind"] == "declared" and d["declaring"][0]["file"] == "cio.json"


def test_declaration_ignores_booleans_and_fields_deeper_than_the_scan_depth(tmp_path):
    _json(tmp_path, "a.json", {"live_mode": True, "l1": {"l2": {"l3": {"stage": "Stage 2"}}}})
    d = R.measure_declaration(str(tmp_path))
    assert d["kind"] == "not_declared" and d["fields"] == 0


def test_declaration_names_unreadable_and_oversized_files_and_skips_its_own_report(tmp_path, monkeypatch):
    _json(tmp_path, "ok.json", {"mode": "paper"})
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    _json(tmp_path, "big.json", {"mode": "x" * 64})
    monkeypatch.setattr(R, "SCAN_MAX_BYTES", 60)
    _json(tmp_path, os.path.basename(R.REPORT_REL), {"stage": "Stage 4"})
    d = R.measure_declaration(str(tmp_path))
    assert d["kind"] == "not_declared"
    assert d["files_unread"] == ["bad.json"] and d["files_too_big"] == ["big.json"] and d["files"] == 3


def test_declaration_lists_files_named_after_code_releases(tmp_path):
    _json(tmp_path, "active_release.json", {"service": "canary"})
    _json(tmp_path, "x.json", {"mode": "paper"})
    assert R.measure_declaration(str(tmp_path))["release_named_files"] == ["active_release.json"]


# ───────────────────────────── ось D — ярлык против поведения ─────────────────

def _books(armed: bool) -> dict:
    return {b: {"book": b, "armed": armed, "armed_adr": "ADR-324" if armed else None,
                "armed_at": "2026-09-11" if armed else None} for b in R.BOOKS}


def test_an_armed_book_labelled_shadow_contradicts_its_behaviour(tmp_path):
    for b in R.BOOKS:
        _rationale(tmp_path, b)
    labels = R.measure_labels(str(tmp_path), _books(True))
    assert all(lb["kind"] == "contradicts" for lb in labels.values())
    assert "РЕШАЕТ" in labels["conservative"]["detail"] and "ADVISORY" in labels["conservative"]["detail"]
    assert labels["balanced"]["file"] == "allocation_rationale_balanced.json"


def test_an_advisory_note_alone_is_a_contradiction_for_an_armed_book(tmp_path):
    _rationale(tmp_path, "conservative", mode="ARMED")
    lb = R.measure_labels(str(tmp_path), _books(True))["conservative"]
    assert lb["kind"] == "contradicts" and "ADVISORY" in lb["detail"]


def test_an_armed_book_labelled_armed_agrees_and_an_unarmed_shadow_label_agrees(tmp_path):
    _rationale(tmp_path, "conservative", mode="ARMED", note="вердикт решает ход")
    assert R.measure_labels(str(tmp_path), _books(True))["conservative"]["kind"] == "agrees"
    _rationale(tmp_path, "conservative")
    assert R.measure_labels(str(tmp_path), _books(False))["conservative"]["kind"] == "agrees"


def test_a_missing_or_fieldless_record_is_unmeasured_not_agreeing(tmp_path):
    labels = R.measure_labels(str(tmp_path), _books(True))
    assert labels["conservative"]["kind"] == UNMEASURED and "нет" in labels["conservative"]["reason"]
    _rationale(tmp_path, "conservative", mode=None, note=None)
    lb = R.measure_labels(str(tmp_path), _books(True))["conservative"]
    assert lb["kind"] == UNMEASURED and "ни mode, ни note" in lb["reason"]


def test_record_fields_are_absent_when_no_row_carries_a_stage_or_arming_field(tmp_path):
    rf = R.measure_record_fields(_journals(tmp_path, books=R.BOOKS))
    assert rf["kind"] == "absent" and rf["records"] == 15 and "неотличим" in rf["detail"]
    assert set(rf["by_field"]) == set(R.STAGE_RECORD_FIELDS) and sum(rf["by_field"].values()) == 0


def test_record_fields_are_carried_when_a_row_names_the_arming(tmp_path):
    rf = R.measure_record_fields(_journals(tmp_path, extra={"cio_armed": True}))
    assert rf["kind"] == "carried" and rf["by_field"]["cio_armed"] == 5


def test_record_fields_are_unmeasured_without_any_journal_and_name_missing_books(tmp_path):
    rf = R.measure_record_fields(R.load_journals(str(tmp_path)))
    assert rf["kind"] == UNMEASURED and "conservative" in rf["reason"]
    rf2 = R.measure_record_fields(_journals(tmp_path))
    assert rf2["kind"] == "absent" and len(rf2["journals_missing"]) == 2


# ───────────────────────────── ось E — двери ──────────────────────────────────

def test_stage2_door_is_unmeasured_without_the_telegram_package(tmp_path):
    s2 = R.measure_stage2_door(str(tmp_path), str(tmp_path))
    assert s2["kind"] == UNMEASURED and R.TELEGRAM_REL in s2["reason"]


def test_stage2_door_is_a_one_off_grant_when_no_verb_approves_a_move(tmp_path):
    _telegram(tmp_path)
    s2 = R.measure_stage2_door(str(tmp_path), str(tmp_path))
    assert s2["kind"] == "one_off_grant_only" and s2["act_verb_families"] == ["aa", "mute", "od"]
    assert s2["one_off_grant"]["adr"] == "ADR-334" and s2["one_off_grant"]["moves"] == 1
    assert s2["one_off_grant"]["spent"] == 0 and "нет" in s2["one_off_grant"]["spent_note"]


def test_stage2_door_is_a_general_channel_when_a_verb_approves_a_move(tmp_path):
    _telegram(tmp_path, verbs=("aa", "approve_move"))
    s2 = R.measure_stage2_door(str(tmp_path), str(tmp_path))
    assert s2["kind"] == "general_channel" and s2["rebalance_verbs"] == ["approve_move"]


def test_stage2_door_is_absent_without_a_grant_and_without_a_verb(tmp_path, monkeypatch):
    _telegram(tmp_path)
    monkeypatch.setattr(R.cio_trial, "TRIAL_GRANT", {"adr": "x", "moves": 0})
    assert R.measure_stage2_door(str(tmp_path), str(tmp_path))["kind"] == "absent"


def test_stage2_door_reads_the_spent_moves_from_the_trade_journal(tmp_path):
    _telegram(tmp_path)
    _json(tmp_path, "trades.json", {"trades": [{R.cio_trial.MARK: R.cio_trial.TRIAL_GRANT["adr"]}, {}]})
    assert R.measure_stage2_door(str(tmp_path), str(tmp_path))["one_off_grant"]["spent"] == 1


def test_stage2_scan_ignores_tests_and_scans_recursively(tmp_path):
    _telegram(tmp_path, verbs=("aa",))
    sub = tmp_path / R.TELEGRAM_REL / "sub"
    sub.mkdir()
    (sub / "deep.py").write_text('Y = "act:approve_move:"\n', encoding="utf-8")
    t = tmp_path / R.TELEGRAM_REL / "tests"
    t.mkdir()
    (t / "test_x.py").write_text('Z = "act:rebalance_now:"\n', encoding="utf-8")
    verbs, _ = R.act_verb_families(str(tmp_path))
    assert verbs == ["aa", "approve_move"]


def test_stage3_bands_are_unmeasured_without_the_limits_artifact_or_its_tally(tmp_path):
    assert R.measure_stage3_bands(str(tmp_path), None)["kind"] == UNMEASURED
    _json(tmp_path, R.LIMITS_FILE, {"generated_at": "x"})
    assert "tally" in R.measure_stage3_bands(str(tmp_path), None)["reason"]
    _json(tmp_path, R.LIMITS_FILE, {"limits_total": 12, "tally": {"LITERAL": 2}})
    assert R.measure_stage3_bands(str(tmp_path), None)["kind"] == UNMEASURED


@pytest.mark.parametrize("binding, kind", [(12, "all_binding"), (6, "partly_binding"), (0, "none_binding")])
def test_stage3_bands_kind_follows_the_binding_count(tmp_path, binding, kind):
    _limits_file(tmp_path, binding=binding, literal=0, absent=12 - binding)
    s3 = R.measure_stage3_bands(str(tmp_path), None)
    assert s3["kind"] == kind and s3["binding"] == binding and s3["total"] == 12


def test_stage3_bands_read_the_move_caps_of_the_last_record(tmp_path):
    _limits_file(tmp_path)
    rows = [_rec(0), _rec(1, extra={"admissible_trim": {"adr": "ADR-851", "caps": {"max_trade_usd": 9.0}}})]
    s3 = R.measure_stage3_bands(str(tmp_path), rows)
    assert s3["record_caps"] == {"max_trade_usd": 9.0} and s3["record_caps_adr"] == "ADR-851"
    assert R.measure_stage3_bands(str(tmp_path), None)["record_caps"] is None


def test_stage4_proof_is_unmeasured_without_the_arming_artifact_or_ready_to_arm(tmp_path):
    assert R.measure_stage4_proof(str(tmp_path))["kind"] == UNMEASURED
    _json(tmp_path, R.EVAL_FILE, {"status": "x"})
    assert "ready_to_arm" in R.measure_stage4_proof(str(tmp_path))["reason"]


def test_stage4_proof_not_given_names_the_criteria_and_the_blockade(tmp_path):
    _eval_file(tmp_path)
    s4 = R.measure_stage4_proof(str(tmp_path))
    assert s4["kind"] == "not_given" and [c["status"] for c in s4["criteria"]] == ["PASS", "PASS", "UNCHECKED"]
    assert s4["blockade_verdict"] == "UNREACHABLE_UNTIL_CHANGED" and s4["observation_days"] == 98


def test_stage4_proof_given_when_ready_to_arm_is_true(tmp_path):
    _eval_file(tmp_path, ready=True, statuses=("PASS", "PASS", "PASS"), blockade=None)
    s4 = R.measure_stage4_proof(str(tmp_path))
    assert s4["kind"] == "given" and s4["blockade_verdict"] is None


# ───────────────────────────── полный стенд ───────────────────────────────────

def test_run_on_a_live_like_stand_is_critical_and_names_every_defect(tmp_path):
    ddir = _stand(tmp_path)
    doc = _run(tmp_path, ddir)
    codes = [f["code"] for f in doc["findings"]]
    assert doc["overall"] == "CRITICAL"
    assert codes.count("label_contradicts_behaviour") == 3
    assert "release_stage_not_declared" in codes and "record_does_not_carry_the_stage" in codes
    assert "stage_2_door_is_a_one_off_grant" in codes and "stage_3_bands_partly_absent" in codes
    assert "armed_ahead_of_the_proof_gate" in codes
    assert doc["counts"]["unmeasured"] == 0 and doc["unmeasured"] == []
    assert all(b["behaviour"] == "auto_within_bands" for b in doc["books"].values())
    assert doc["real_capital"]["kind"] == "not_entered"


def test_run_on_a_stand_that_declares_and_agrees_is_ok(tmp_path):
    ddir = _stand(tmp_path, label_mode="ARMED", declare=True, stage_field=True, verbs=("aa", "approve_move"),
                  binding=12, ready=True)
    doc = _run(tmp_path, ddir)
    assert doc["overall"] == "OK", doc["findings"]
    assert doc["declaration"]["kind"] == "declared" and doc["record_fields"]["kind"] == "carried"
    assert all(lb["kind"] == "agrees" for lb in doc["labels"].values())


def test_run_without_any_input_is_unchecked_with_every_reason_named(tmp_path):
    (tmp_path / "data").mkdir()
    doc = R.run(root=str(tmp_path), data_dir=str(tmp_path / "data"), card_path=str(tmp_path / "none.md"), write=False, now=NOW)
    assert doc["overall"] == "UNCHECKED" and doc["findings"] == []
    joined = " ".join(doc["unmeasured"])
    for word in ("паритет", "conservative", "balanced", "aggressive", "реальный капитал", "объявление стадии",
                 "ярлык", "поля стадии", "дверь стадии 2", "дверь стадии 3", "дверь стадии 4"):
        assert word in joined, word


def test_a_drifted_card_is_a_critical_finding(tmp_path):
    ddir = _stand(tmp_path, label_mode="ARMED", declare=True, stage_field=True, verbs=("aa", "approve_move"), binding=12, ready=True)
    (tmp_path / R.CARD_REL).write_text(_good_card_text().replace("\nShadow CIO\n", "\nShadow mode\n"), encoding="utf-8")
    doc = _run(tmp_path, ddir)
    assert doc["overall"] == "CRITICAL" and doc["findings"][0]["code"] == "owner_section_drifted"


def test_an_unarmed_system_carries_no_arming_info_and_shadow_labels_agree(tmp_path, monkeypatch):
    monkeypatch.setattr(R.cio_arming, "ARMED_BOOKS", {})
    ddir = _stand(tmp_path)
    doc = R.run(root=str(tmp_path), data_dir=str(ddir), card_path=os.path.join(str(tmp_path), R.CARD_REL), write=False, now=NOW)
    codes = [f["code"] for f in doc["findings"]]
    assert "armed_ahead_of_the_proof_gate" not in codes and "label_contradicts_behaviour" not in codes
    assert all(b["behaviour"] == "recommendations_only" for b in doc["books"].values())


def test_write_false_leaves_the_tree_untouched_and_write_true_writes_the_report(tmp_path):
    ddir = _stand(tmp_path)
    before = sorted(p.name for p in ddir.iterdir())
    R.run(root=str(tmp_path), data_dir=str(ddir), card_path=os.path.join(str(tmp_path), R.CARD_REL), write=False, now=NOW)
    assert sorted(p.name for p in ddir.iterdir()) == before
    R.run(root=str(tmp_path), data_dir=str(ddir), card_path=os.path.join(str(tmp_path), R.CARD_REL), write=True, now=NOW)
    rep = json.loads((tmp_path / R.REPORT_REL).read_text(encoding="utf-8"))
    assert rep["schema"] == "release_stage_census/v1" and rep["applied"] is False and rep["generated_at"] == NOW.isoformat()


def test_declared_kinds_cover_every_kind_the_instrument_can_emit(tmp_path):
    ddir = _stand(tmp_path)
    doc = _run(tmp_path, ddir)
    d = doc["declared"]
    assert all(b["behaviour"] in d["behaviour_kinds"] for b in doc["books"].values())
    assert doc["real_capital"]["kind"] in d["real_kinds"] and doc["declaration"]["kind"] in d["declaration_kinds"]
    assert all(lb["kind"] in d["label_kinds"] for lb in doc["labels"].values())
    assert doc["stage2_door"]["kind"] in d["stage2_door_kinds"] and doc["stage4_proof"]["kind"] in d["proof_kinds"]
    assert set(d["behaviour_stage"]) == set(R.BEHAVIOUR_KINDS) and d["stages_declared"] == 5


def test_main_refuses_an_unparseable_now_with_code_2(capsys):
    assert R.main(["--now", "вчера", "--no-write"]) == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().out


def test_main_returns_1_on_a_critical_stand_and_prints_the_books(tmp_path, capsys):
    ddir = _stand(tmp_path)
    rc = R.main(["--root", str(tmp_path), "--data-dir", str(ddir), "--card", os.path.join(str(tmp_path), R.CARD_REL),
                 "--no-write", "--now", NOW.isoformat()])
    out = capsys.readouterr().out
    assert rc == 1 and "CRITICAL" in out and "книга conservative" in out and "label_contradicts_behaviour" in out


def test_main_returns_2_on_an_unchecked_tree(tmp_path):
    (tmp_path / "data").mkdir()
    assert R.main(["--root", str(tmp_path), "--data-dir", str(tmp_path / "data"), "--card", str(tmp_path / "none.md"),
                   "--no-write", "--now", NOW.isoformat()]) == 2


# ───────────────────────────── проба приёмки ──────────────────────────────────

def test_probe_is_registered_with_both_tree_inputs():
    assert PROBE in CA.PROBES
    assert set(CA.probe_tree_inputs(PROBE)) == {"repo_root", "data_dir"}


def test_probe_rejects_an_argument():
    status, why = CA.PROBES[PROBE]("x")
    assert status == CA.UNMEASURED and "аргумента" in why


def test_probe_is_unmeasured_on_a_tree_without_the_card(tmp_path):
    status, why = CA.run_probe(PROBE, repo_root=str(tmp_path), data_dir=str(tmp_path))
    assert status == CA.UNMEASURED and "паритет" in why


def test_probe_is_unmeasured_without_journals_and_names_the_books(tmp_path):
    ddir = _stand(tmp_path, journals=False)
    status, why = CA.run_probe(PROBE, repo_root=str(tmp_path), data_dir=str(ddir))
    assert status == CA.UNMEASURED and "книга conservative" in why and "поля стадии" in why


def test_probe_is_not_satisfied_on_a_live_like_stand_and_names_the_points(tmp_path):
    ddir = _stand(tmp_path)
    status, why = CA.run_probe(PROBE, repo_root=str(tmp_path), data_dir=str(ddir))
    assert status == CA.NOT_SATISFIED
    for word in ("объявление стадии", "ярлык conservative", "ярлык balanced", "ярлык aggressive", "поля стадии", "SHADOW"):
        assert word in why, word


def test_probe_is_satisfied_only_when_declared_agreeing_and_carried(tmp_path):
    ddir = _stand(tmp_path, label_mode="ARMED", declare=True, stage_field=True)
    status, why = CA.run_probe(PROBE, repo_root=str(tmp_path), data_dir=str(ddir))
    assert status == CA.SATISFIED, why
    assert "cio_stage.json:stage" in why and "3/4" in why


def test_probe_is_not_satisfied_when_only_the_declaration_is_missing(tmp_path):
    ddir = _stand(tmp_path, label_mode="ARMED", stage_field=True)
    status, why = CA.run_probe(PROBE, repo_root=str(tmp_path), data_dir=str(ddir))
    assert status == CA.NOT_SATISFIED and "объявление стадии" in why and "ярлык" not in why


def test_probe_is_not_satisfied_when_the_card_drifts(tmp_path):
    ddir = _stand(tmp_path, label_mode="ARMED", declare=True, stage_field=True)
    (tmp_path / R.CARD_REL).write_text(_good_card_text().replace("\nShadow CIO\n", "\nShadow mode\n"), encoding="utf-8")
    status, why = CA.run_probe(PROBE, repo_root=str(tmp_path), data_dir=str(ddir))
    assert status == CA.NOT_SATISFIED and "карточка" in why


def test_probe_does_not_judge_the_owner_decision_to_arm_ahead_of_the_proof(tmp_path):
    ddir = _stand(tmp_path, label_mode="ARMED", declare=True, stage_field=True, ready=False)
    status, _ = CA.run_probe(PROBE, repo_root=str(tmp_path), data_dir=str(ddir))
    assert status == CA.SATISFIED


def test_run_with_only_the_stage_2_and_3_doors_short_is_a_warning_not_ok(tmp_path):
    ddir = _stand(tmp_path, label_mode="ARMED", declare=True, stage_field=True, ready=True)
    doc = _run(tmp_path, ddir)
    assert doc["overall"] == "WARNING" and doc["counts"]["critical"] == 0
    assert {f["code"] for f in doc["findings"] if f["severity"] == "WARN"} == {"stage_2_door_is_a_one_off_grant",
                                                                                "stage_3_bands_partly_absent"}
