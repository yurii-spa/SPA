"""ADR-760 hardening (audit 16.10) — the cockpit voice/text intake, measured by OUTCOME.

Each test is a positive control for one gap the audit named; every one of them is red on the code
before this change (verified against an origin copy):

  (a) idempotency — one ``submission_id`` is ONE card: a retry with edited text, a retry after the
      card was closed, eight concurrent retries — all return the same card (``duplicate: true``);
  (b) whisper outcomes are NOT collapsed into «не удалось разобрать речь» (inv. #17): timeout ⇒ 504,
      process failure ⇒ 503, nothing heard ⇒ 422, a second transcription while one runs ⇒ 429;
  (c) the page keeps the draft, the audio and the submission id; times out with its own words;
      names a non-JSON answer; retries a rotated CSRF key once — static checks of app.js;
  (d) every cockpit card carries the author and the ADR-285 authority line; Telegram cards do not;
  (e) «Мои записи»: the owner sees what became of their records (prod tracker), «не измерено» when
      the tracker is unreadable;
  (f) index.html declares ``composer-root`` once;
  (6) the intake router honours the owner's own label (idea/task) without calling the classifier.

No whisper and no live server are run: transcribers are injected, the tracker is a tmp dir.
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.studio_os import mission_control as mc
from spa_core.studio_os import mission_intake as mi
from spa_core.studio_os import owner_view as ov
from spa_core.telegram import inbox_intake as ii

UI = Path(__file__).resolve().parents[1] / "studio_os" / "mission_ui"
NOW = datetime(2026, 10, 16, 7, 30, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock — passed as now= to submit/cockpit_records/my_records
SID = "0f1e2d3c-4b5a-4968-8776-655443322110"


def _body(text, kind="task", sid=SID, **extra):
    doc = {"text": text, "kind": kind, **extra}
    if sid is not None:
        doc["submission_id"] = sid
    return json.dumps(doc).encode("utf-8")


def _cards(d: Path):
    return sorted(p for p in d.glob("inbox-*.md"))


# ── (a) idempotency ────────────────────────────────────────────────────────────────────────────────
def test_same_submission_id_with_edited_text_is_one_card(tmp_path):
    first = mi.submit(_body("Проверить сводку по пакетам"), actor="local", tracker_dir=tmp_path, now=NOW)
    second = mi.submit(_body("Проверить сводку по пакетам!"), actor="local", tracker_dir=tmp_path, now=NOW)
    assert first["duplicate"] is False and second["duplicate"] is True
    assert second["card"] == first["card"]
    cards = _cards(tmp_path)
    assert len(cards) == 1
    text = cards[0].read_text(encoding="utf-8")
    assert f"submission_id: {SID}" in text
    assert "Проверить сводку по пакетам!" not in text      # the retry did not rewrite the card


def test_same_submission_id_after_the_card_is_closed_is_still_one_card(tmp_path):
    first = mi.submit(_body("Записать идею про отчёт"), actor="local", tracker_dir=tmp_path, now=NOW)
    p = tmp_path / first["card"]
    p.write_text(p.read_text(encoding="utf-8").replace("status: new", "status: done"), encoding="utf-8")
    second = mi.submit(_body("Записать идею про отчёт"), actor="local", tracker_dir=tmp_path, now=NOW)
    assert second["duplicate"] is True and second["card"] == first["card"]
    assert len(_cards(tmp_path)) == 1


def test_concurrent_retries_with_one_submission_id_make_one_card(tmp_path):
    results, errors = [], []
    start = threading.Barrier(8)

    def go(i):
        try:
            start.wait()
            results.append(mi.submit(_body(f"Параллельная отправка {i}"), actor="local",
                                     tracker_dir=tmp_path, now=NOW))
        except Exception as exc:  # noqa: BLE001 — collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not errors, errors
    assert len(_cards(tmp_path)) == 1
    assert sorted(r["duplicate"] for r in results) == [False] + [True] * 7
    assert len({r["card"] for r in results}) == 1


def test_different_submission_ids_are_different_cards(tmp_path):
    mi.submit(_body("Первая запись про отчёт", sid="aaaaaaaa-1111"), actor="local", tracker_dir=tmp_path, now=NOW)
    mi.submit(_body("Вторая запись про отчёт", sid="bbbbbbbb-2222"), actor="local", tracker_dir=tmp_path, now=NOW)
    assert len(_cards(tmp_path)) == 2


@pytest.mark.parametrize("bad", ["short", "x" * 65, "../../etc/passwd", "id with space", 12345678, ["a" * 10]])
def test_malformed_submission_id_is_refused_and_writes_nothing(tmp_path, bad):
    with pytest.raises(mi.IntakeRefused) as ei:
        mi.submit(_body("Текст записи", sid=bad), actor="local", tracker_dir=tmp_path, now=NOW)
    assert ei.value.status == 400 and ei.value.code == "BAD_SUBMISSION_ID"
    assert list(tmp_path.iterdir()) == []


def test_idempotency_writes_no_marker_file_into_the_tracker(tmp_path):
    mi.submit(_body("Одна запись"), actor="local", tracker_dir=tmp_path, now=NOW)
    mi.submit(_body("Одна запись"), actor="local", tracker_dir=tmp_path, now=NOW)
    assert [p.name for p in tmp_path.iterdir()] == [_cards(tmp_path)[0].name]


# ── (b) whisper outcomes ───────────────────────────────────────────────────────────────────────────
def _raiser(exc):
    def f(_p):
        raise exc
    return f


@pytest.mark.parametrize("transcriber, status, code", [
    (_raiser(subprocess.TimeoutExpired(cmd="whisper", timeout=90)), 504, "WHISPER_TIMEOUT"),
    (_raiser(subprocess.CalledProcessError(1, "whisper")), 503, "WHISPER_FAILED"),
    (_raiser(OSError("exec format error")), 503, "WHISPER_FAILED"),
    (lambda _p: None, 422, "EMPTY_TRANSCRIPT"),
    (lambda _p: "   ", 422, "EMPTY_TRANSCRIPT"),
])
def test_whisper_outcomes_are_distinct_refusals(transcriber, status, code):
    with pytest.raises(mi.IntakeRefused) as ei:
        mi.transcribe(b"fake-audio", "audio/mp4", transcriber=transcriber)
    assert (ei.value.status, ei.value.code) == (status, code)
    assert ei.value.message_ru and not re.search(r"[A-Za-z]{4,}_[A-Za-z]", ei.value.message_ru)


def test_timeout_and_failure_messages_differ_from_the_empty_one():
    msgs = set()
    for tr in (_raiser(subprocess.TimeoutExpired("w", 1)), _raiser(OSError("x")), lambda _p: None):
        with pytest.raises(mi.IntakeRefused) as ei:
            mi.transcribe(b"a", "audio/mp4", transcriber=tr)
        msgs.add(ei.value.message_ru)
    assert len(msgs) == 3


def test_default_path_maps_the_bot_whisper_outcome(monkeypatch):
    monkeypatch.setattr(mi, "whisper_status", lambda: {"whisper_present": True})
    monkeypatch.setattr(ii, "transcribe_voice_detailed", lambda p, timeout=300, language=None: (ii.TRANSCRIBE_TIMEOUT, None))
    with pytest.raises(mi.IntakeRefused) as ei:
        mi.transcribe(b"a", "audio/mp4")
    assert ei.value.code == "WHISPER_TIMEOUT"


def test_second_transcription_while_one_runs_is_429_busy():
    entered, release = threading.Event(), threading.Event()
    out = {}

    def slow(_p):
        entered.set()
        release.wait(10)
        return "готово"

    th = threading.Thread(target=lambda: out.setdefault("r", mi.transcribe(b"a", "audio/mp4", transcriber=slow)))
    th.start()
    try:
        assert entered.wait(10)
        with pytest.raises(mi.IntakeRefused) as ei:
            mi.transcribe(b"b", "audio/mp4", transcriber=lambda _p: "второй")
        assert (ei.value.status, ei.value.code) == (429, "WHISPER_BUSY")
        assert "подождите" in ei.value.message_ru
    finally:
        release.set()
        th.join(10)
    assert out["r"]["text"] == "готово"
    # the slot is free again afterwards
    assert mi.transcribe(b"c", "audio/mp4", transcriber=lambda _p: "третий")["text"] == "третий"


def test_the_slot_is_released_after_a_refusal():
    with pytest.raises(mi.IntakeRefused):
        mi.transcribe(b"a", "audio/mp4", transcriber=_raiser(OSError("x")))
    assert mi.transcribe(b"a", "audio/mp4", transcriber=lambda _p: "ок")["text"] == "ок"


class _Proc:
    def __init__(self, rc, stderr=""):
        self.returncode, self.stderr, self.stdout = rc, stderr, ""


def test_bot_whisper_call_names_each_outcome_and_keeps_its_old_contract(tmp_path, monkeypatch):
    audio = tmp_path / "v.m4a"
    audio.write_bytes(b"x")

    def run_timeout(*a, **k):
        raise subprocess.TimeoutExpired("whisper", 1)

    cases = [(run_timeout, ii.TRANSCRIBE_TIMEOUT), (lambda *a, **k: _Proc(1, "boom"), ii.TRANSCRIBE_FAILED),
             (lambda *a, **k: _Proc(0), ii.TRANSCRIBE_EMPTY)]
    for fake, expected in cases:
        monkeypatch.setattr(ii.subprocess, "run", fake)
        assert ii.transcribe_voice_detailed(audio)[0] == expected
        assert ii.transcribe_voice(audio) is None            # Telegram contract unchanged
    assert ii.transcribe_voice_detailed(tmp_path / "absent.m4a") == (ii.TRANSCRIBE_FAILED, None)

    def run_ok(cmd, **k):
        out_dir = Path(cmd[cmd.index("--output_dir") + 1])
        (out_dir / "v.txt").write_text("  привет  ", encoding="utf-8")
        return _Proc(0)
    monkeypatch.setattr(ii.subprocess, "run", run_ok)
    assert ii.transcribe_voice_detailed(audio) == (ii.TRANSCRIBE_OK, "привет")
    assert ii.transcribe_voice(audio) == "привет"


# ── (d) author + authority boundary ────────────────────────────────────────────────────────────────
def test_every_cockpit_card_carries_actor_and_the_authority_line(tmp_path):
    mi.submit(_body("Текстовая запись", sid="cccccccc-0001"), actor="owner@example.com", tracker_dir=tmp_path, now=NOW)
    mi.submit(_body("Голосовая запись", sid="cccccccc-0002", transcript="Голосовая запись"), actor="local",
              tracker_dir=tmp_path, now=NOW)
    mi.submit(_body("Запись старой страницы", sid=None, kind="idea"), actor="local", tracker_dir=tmp_path, now=NOW)
    cards = _cards(tmp_path)
    assert len(cards) == 3
    for p in cards:
        text = p.read_text(encoding="utf-8")
        assert mi.AUTHORITY_NOTE in text, p.name
        assert re.search(r"^actor: ", text, re.M), p.name
        assert re.search(r'^submitted_at: "?2026-10-16T07:30:00Z"?$', text, re.M), p.name
    assert 'actor: "owner@example.com"' in "".join(p.read_text(encoding="utf-8") for p in cards)


def test_telegram_cards_are_unchanged(tmp_path):
    path, _title = ii.save_inbox_task("Задание из Телеграма", source="telegram", tracker_dir=tmp_path)
    text = Path(path).read_text(encoding="utf-8")
    assert mi.AUTHORITY_NOTE not in text and "ADR-285" not in text
    for key in ("actor:", "submission_id:", "submitted_at:"):
        assert key not in text
    assert "## Задание (из Telegram)" in text


# ── (e) «Мои записи» ───────────────────────────────────────────────────────────────────────────────
def _tracker_with_records(d: Path):
    a = mi.submit(_body("Новая задача из пульта", sid="dddddddd-0001"), actor="local", tracker_dir=d,
                  now=NOW - timedelta(hours=3))
    b = mi.submit(_body("Задача уже в работе", sid="dddddddd-0002"), actor="local", tracker_dir=d,
                  now=NOW - timedelta(hours=2))
    c = mi.submit(_body("Сделанная задача", sid="dddddddd-0003", kind="note"), actor="local", tracker_dir=d,
                  now=NOW - timedelta(hours=1))
    e = mi.submit(_body("Идея про отчёт", sid="dddddddd-0004", kind="idea", transcript="Идея про отчёт"),
                  actor="local", tracker_dir=d, now=NOW)
    for res, st, extra in ((b, "in-progress", ""), (c, "done", ""),
                           (e, "done", "carried_to: docs/ideas/2026-10-16-ideya-pro-otchet.md\n")):
        p = d / res["card"]
        p.write_text(p.read_text(encoding="utf-8").replace("status: new\n", f"status: {st}\n{extra}"), encoding="utf-8")
    ii.save_inbox_task("Телеграм не попадает в мои записи", source="telegram", tracker_dir=d)
    return a, b, c, e


def test_my_records_lists_cockpit_cards_newest_first_with_plain_statuses(tmp_path):
    a, b, c, e = _tracker_with_records(tmp_path)
    rec = mc.cockpit_records(mc._cards(tmp_path), NOW, source="tracker")
    assert rec["state"] == "MEASURED" and rec["total"] == 4
    assert [r["card"] for r in rec["items"]] == [e["card"], c["card"], b["card"], a["card"]]
    view = ov.my_records({"generated_at": "2026-10-16T07:30:00Z", "intake": {"my_records": rec}}, "2026-10-16T07:30:00Z")
    states = [r["state"] for r in view["rows"]]
    assert states[0].startswith("перенесено: ")
    # ИЗМЕНЕНО 16.10 (ADR-763, инв. #16, запись в docs/journal/2026-W42.md): предмет тот же — статус
    # записи простыми словами, — сменилось ожидаемое. Закрытая БЕЗ пробы карточка больше не читается
    # как «сделано» (владелец принимал это за проверенный результат), а взятая без пробы — как
    # «в работе — не принято» с причиной и следующим шагом. Проверенное «сделано» — только из
    # verified_by_probe (test_cockpit_loop.py).
    assert states[1] == "закрыто без проверки результата — не считается проверенным"
    assert states[2].startswith("в работе — не принято: ") and "; следующий шаг: " in states[2]
    assert states[3] == "записано, ещё не разобрано"
    assert [r["state_kind"] for r in view["rows"]] == ["carried", "done_unverified", "not_accepted", "new"]
    assert [r["kind"] for r in view["rows"]] == ["идея", "замечание", "задача", "задача"]
    assert view["rows"][0]["at_ru"] == "2026-10-16 09:30 Мадрид (CEST)"
    assert view["rows"][0]["voice"] is True
    s = view["summary"]
    assert s["confidence"] == ov.MEASURED and s["source"] == "tracker" and s["measured_at"] == "2026-10-16T07:30:00Z"
    assert not [t for _p, t in ov.main_texts(view) if ov.jargon_hits(t)]


def test_my_records_is_limited_to_ten(tmp_path):
    for i in range(12):
        mi.submit(_body(f"Запись номер {i}", sid=f"eeeeeeee-{i:04d}"), actor="local", tracker_dir=tmp_path,
                  now=NOW + timedelta(minutes=i))
    rec = mc.cockpit_records(mc._cards(tmp_path), NOW, source="tracker")
    assert rec["total"] == 12 and len(rec["items"]) == 10
    view = ov.my_records({"intake": {"my_records": rec}}, None)
    assert view["summary"]["text"] == "Записей из пульта: 12; ниже последние 10"


def test_my_records_unreadable_tracker_is_not_measured_not_empty(tmp_path):
    rec = mc.cockpit_records(mc._cards(tmp_path / "absent"), NOW, source="tracker")
    assert rec["state"] == "NOT_MEASURED" and rec["items"] is None
    view = ov.my_records({"intake": {"my_records": rec}}, None)
    assert view["summary"]["confidence"] == ov.NOT_MEASURED
    assert view["summary"]["text"].startswith("Не измерено")
    assert view["rows"] == [] and view["empty"] is None


def test_my_records_measured_empty_is_said_in_words(tmp_path):
    rec = mc.cockpit_records(mc._cards(tmp_path), NOW, source="tracker")
    view = ov.my_records({"intake": {"my_records": rec}}, None)
    assert rec["total"] == 0 and view["summary"]["text"] == "Записей из пульта пока нет"


def test_unknown_record_status_is_named_not_success():
    rec = {"state": "MEASURED", "items": [{"card": "inbox-x.md", "title": "x", "created_at": None, "kind": "task",
                                           "status": "weird"}], "total": 1, "source": "t", "measured_at": None}
    row = ov.my_records({"intake": {"my_records": rec}}, None)["rows"][0]
    assert row["state_known"] is False and "не распознано" in row["state"]


def test_mission_model_carries_my_records_from_the_production_tree(tmp_path):
    from spa_core.tests import test_mission_control_contract as C
    s = C._scene(tmp_path)
    ptr = s.repo / "nimbalyst-local" / "tracker"
    res = mi.submit(_body("Запись из пульта в проде", sid="ffffffff-0001"), actor="local", tracker_dir=ptr, now=C.NOW)
    model = C._build(s)
    rec = model["intake"]["my_records"]
    assert rec["state"] == "MEASURED" and [r["card"] for r in rec["items"]] == [res["card"]]
    work = model["owner_view"]["sections"]["work"]
    assert work["my_records"]["rows"][0]["state"] == "записано, ещё не разобрано"


# ── (6) the intake router honours the owner's own label ───────────────────────────────────────────
def _wire_router(monkeypatch, tmp_path, card):
    from spa_core.owner_queue import history_check as H
    from spa_core.owner_queue import intake as I
    from spa_core.owner_queue import queue as Q
    from spa_core.telegram import ask_router
    calls = []
    monkeypatch.setattr(I, "_REPO", tmp_path)
    monkeypatch.setattr(Q, "TRACKER_DIR", tmp_path / "tracker")
    monkeypatch.setattr(I, "_notify", lambda text, *a, **k: None)
    monkeypatch.setattr(Q, "ingest_notes", lambda *a, **k: None)
    monkeypatch.setattr(Q, "list_cards", lambda **k: [card])
    monkeypatch.setattr(H, "history_check", lambda body: {"verdict": "NEW", "response": ""})

    def classify(body):
        calls.append(body)
        return ("unclear", "Уточни")
    monkeypatch.setattr(ask_router, "classify_and_answer", classify)
    return I, Q, calls


def test_cockpit_idea_goes_to_ideas_without_the_classifier(tmp_path, monkeypatch):
    from spa_core.owner_queue import queue as Q
    res = mi.submit(_body("Идея: сводка по пакетам", sid="abababab-0001", kind="idea"), actor="local",
                    tracker_dir=tmp_path / "tracker", now=NOW)
    card = Q.load_card(tmp_path / "tracker" / res["card"])
    I, Q, calls = _wire_router(monkeypatch, tmp_path, card)
    out = I.run_note_intake(now=NOW)
    assert calls == [] and card.id in out["processed"]
    assert list((tmp_path / "docs" / "ideas").glob("*.md"))
    assert Q.load_card(card.path).status == "done"


def test_cockpit_task_stays_new_without_the_classifier(tmp_path, monkeypatch):
    from spa_core.owner_queue import queue as Q
    res = mi.submit(_body("Задача: починить отчёт", sid="abababab-0002", kind="task"), actor="local",
                    tracker_dir=tmp_path / "tracker", now=NOW)
    card = Q.load_card(tmp_path / "tracker" / res["card"])
    I, Q, calls = _wire_router(monkeypatch, tmp_path, card)
    out = I.run_note_intake(now=NOW)
    assert calls == [] and card.id in out["processed"]
    assert Q.load_card(card.path).status == "new"
    assert not (tmp_path / "docs" / "ideas").exists()


def test_cockpit_note_and_telegram_cards_still_go_through_the_classifier(tmp_path, monkeypatch):
    from spa_core.owner_queue import queue as Q
    res = mi.submit(_body("Замечание про цвет", sid="abababab-0003", kind="note"), actor="local",
                    tracker_dir=tmp_path / "tracker", now=NOW)
    card = Q.load_card(tmp_path / "tracker" / res["card"])
    I, _Q, calls = _wire_router(monkeypatch, tmp_path, card)
    I.run_note_intake(now=NOW)
    assert len(calls) == 1
    # a Telegram card labelled idea by someone else is NOT trusted as the owner's own label
    p, _t = ii.save_inbox_task("Телеграм-идея", source="telegram", kind="idea", tracker_dir=tmp_path / "tg")
    card2 = Q.load_card(p)
    I, _Q, calls2 = _wire_router(monkeypatch, tmp_path, card2)
    I.run_note_intake(now=NOW)
    assert len(calls2) == 1


# ── (c) + (f) the page — static, the browser is not run in CI ─────────────────────────────────────
def _js():
    return (UI / "app.js").read_text(encoding="utf-8")


def _span(js, name):
    start = js.index("function " + name)
    depth, i = 0, js.index("{", start)
    while True:
        ch = js[i]
        depth += ch == "{"
        depth -= ch == "}"
        i += 1
        if depth == 0:
            return js[start:i]


def test_index_declares_one_composer_root():
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert html.count('id="composer-root"') == 1


def test_draft_is_persisted_and_every_storage_access_is_guarded():
    js = _js()
    for fn in ("loadDraft", "saveDraft", "clearDraft"):
        body = _span(js, fn)
        for m in re.finditer(r"localStorage\.\w+", body):
            assert body.rfind("try {", 0, m.start()) >= 0, (fn, m.group(0))
    assert "saveDraft();" in _span(js, "openComposer")          # on input / kind
    sub = _span(js, "submitComposer")
    assert sub.index("clearDraft()") > sub.index("res.d.ok")    # cleared only after success


def test_backdrop_and_escape_do_not_close_a_non_empty_composer():
    js = _js()
    oc = _span(js, "openComposer")
    assert 'backdrop.addEventListener("click", softClose)' in oc
    assert 'if (e.key === "Escape") softClose();' in oc
    sc = _span(js, "softClose")
    assert "composer.text.value.trim()" in sc and 't("intake.unsaved_hint")' in sc


def test_submission_id_is_made_once_and_sent_with_every_submit():
    js = _js()
    assert "crypto.randomUUID" in _span(js, "newSubmissionId")
    oc = _span(js, "openComposer")
    assert "submissionId:" in oc and "draft.submission_id" in oc
    sub = _span(js, "submitComposer")
    assert "submission_id: composer.submissionId" in sub
    assert "res.d.duplicate" in sub and '"intake.duplicate"' in sub


def test_audio_is_kept_and_can_be_retried():
    js = _js()
    assert "composer.lastAudio = { blob: blob, type: sentType }" in js
    tr = _span(js, "transcribeAudio")
    ok_branch, fail_branch = tr.split("} else {", 1)
    assert "composer.lastAudio = null" in ok_branch and "composer.lastAudio = null" not in fail_branch
    assert 't("intake.retry_transcribe")' in _span(js, "openComposer")


def test_requests_time_out_and_name_non_json_and_retry_csrf_once():
    js = _js()
    wt = _span(js, "withTimeout")
    assert "AbortController" in wt and "AbortError" in wt
    assert "JSON.parse" in _span(js, "readIntakeResponse") and '"not_json"' in _span(js, "readIntakeResponse")
    et = _span(js, "intakeErrorText")
    assert 't("intake.err_timeout")' in et and 't("intake.err_not_json")' in et
    cr = _span(js, "withCsrfRetry")
    assert 'res.d.code === "CSRF"' in cr and cr.count("send()") == 2   # one send + ONE retry
    assert "withCsrfRetry(" in _span(js, "submitComposer") and "withCsrfRetry(" in _span(js, "transcribeAudio")


def test_new_messages_exist_in_both_languages_and_name_the_owner_words():
    i18n = (UI / "i18n.js").read_text(encoding="utf-8")
    for key in ("intake.duplicate", "intake.retry_transcribe", "intake.err_timeout", "intake.err_not_json",
                "intake.unsaved_hint", "intake.draft_restored"):
        assert i18n.count(f'"{key}"') == 2, key
    assert "Сервер не ответил вовремя" in i18n
    assert "Нужно заново войти в пульт (Cloudflare Access) или сервер недоступен" in i18n
    assert "Повторить расшифровку" in i18n and "Уже записано" in i18n


# ── over the real socket: a retried POST (same id) answers duplicate, the page sees one card ───────
def test_http_retry_with_same_submission_id_answers_duplicate(tmp_path):
    from spa_core.tests.test_mission_intake import _Srv, _json_headers
    root, tracker = tmp_path / "serve", tmp_path / "tracker"
    root.mkdir()
    tracker.mkdir()
    s = _Srv(root, tracker, transcriber=lambda p: "x")
    try:
        tok = s.token()
        st1, d1 = s.req("POST", mi.SUBMIT_PATH, _body("Запись через сокет"), _json_headers(s, tok))
        st2, d2 = s.req("POST", mi.SUBMIT_PATH, _body("Запись через сокет (повтор)"), _json_headers(s, tok))
        assert (st1, st2) == (200, 200)
        assert d1["duplicate"] is False and d2["duplicate"] is True and d1["card"] == d2["card"]
        assert "audit" not in d2
        assert len(_cards(tracker)) == 1
        assert "actor: local" in (tracker / d1["card"]).read_text(encoding="utf-8")
    finally:
        s.close()


# ── submit semantics (16.10): retry ≠ new note. A retry (same id) is one card; a NEW composer session
# (new id) with IDENTICAL text is a deliberate second note — the open-twin merge of create_card used to
# swallow it silently (red on origin 8f913113). Without an id (old page) the twin guard stays. ──────────
def test_same_id_twice_identical_text_is_one_card(tmp_path):
    a = mi.submit(_body("Проверить отчёт по пакетам", sid="cccccccc-3333"), actor="local", tracker_dir=tmp_path, now=NOW)
    b = mi.submit(_body("Проверить отчёт по пакетам", sid="cccccccc-3333"), actor="local", tracker_dir=tmp_path, now=NOW)
    assert a["duplicate"] is False and b["duplicate"] is True and a["card"] == b["card"]
    assert len(_cards(tmp_path)) == 1


def test_two_ids_identical_text_are_two_cards(tmp_path):
    a = mi.submit(_body("Проверить отчёт по пакетам", sid="dddddddd-4444"), actor="local", tracker_dir=tmp_path, now=NOW)
    b = mi.submit(_body("Проверить отчёт по пакетам", sid="eeeeeeee-5555"), actor="local", tracker_dir=tmp_path, now=NOW)
    assert a["duplicate"] is False and b["duplicate"] is False
    assert a["card"] != b["card"], "a deliberate second identical note was folded into the first card"
    cards = _cards(tmp_path)
    assert len(cards) == 2
    ids = sorted(ln for c in cards for ln in c.read_text(encoding="utf-8").splitlines()
                 if ln.startswith("submission_id:"))
    assert ids == ["submission_id: dddddddd-4444", "submission_id: eeeeeeee-5555"]


def test_no_id_identical_text_keeps_the_open_twin_guard(tmp_path):
    a = mi.submit(_body("Проверить отчёт по пакетам", sid=None), actor="local", tracker_dir=tmp_path, now=NOW)
    b = mi.submit(_body("Проверить отчёт по пакетам", sid=None), actor="local", tracker_dir=tmp_path, now=NOW)
    assert a["card"] == b["card"]
    assert len(_cards(tmp_path)) == 1


def test_telegram_path_keeps_the_open_twin_guard(tmp_path):
    p1, _ = ii.save_inbox_task("Купить зонт", source="telegram", tracker_dir=tmp_path)
    p2, _ = ii.save_inbox_task("Купить зонт", source="telegram", tracker_dir=tmp_path)
    assert p1 == p2 and len(_cards(tmp_path)) == 1


# ── ARB 16.10: a cockpit card must wake the intake (it ran only on Obsidian notes in inbox/) ──

def test_submit_wakes_intake_via_inbox_dir_change(tmp_path):
    import json as _json
    from spa_core.studio_os import mission_intake as mi
    notes = tmp_path / "inbox"
    body = _json.dumps({"text": "проверить будильник приёма", "kind": "task",
                        "submission_id": "wake-0001-abcd"}).encode()
    res = mi.submit(body, actor="owner@example", tracker_dir=tmp_path / "tracker", wake_dir=notes)
    assert res["ok"] and res["intake_woken"] is True
    wake = notes / mi.WAKE_FILE
    assert wake.exists() and not list(notes.glob("*.md")) and not list(notes.glob("*.txt"))
    first = wake.stat().st_ino
    body2 = _json.dumps({"text": "вторая запись", "kind": "task", "submission_id": "wake-0002-abcd"}).encode()
    mi.submit(body2, actor="owner@example", tracker_dir=tmp_path / "tracker", wake_dir=notes)
    assert wake.stat().st_ino != first, "each submit must CHANGE the directory (atomic rename), not just touch"


def test_wake_marker_is_not_ingested_as_a_note(tmp_path):
    from spa_core.owner_queue import queue as Q
    from spa_core.studio_os import mission_intake as mi
    notes = tmp_path / "inbox"
    assert mi.wake_intake(notes) is True
    assert Q.ingest_notes(notes_dir=notes, tracker_dir=tmp_path / "tracker") in ([], None, 0)
    assert not (tmp_path / "tracker").exists() or not list((tmp_path / "tracker").glob("*.md"))


def test_test_submits_without_wake_dir_do_not_touch_the_real_inbox(tmp_path):
    import json as _json
    from spa_core.studio_os import mission_intake as mi
    body = _json.dumps({"text": "без будильника", "kind": "note", "submission_id": "wake-0003-abcd"}).encode()
    res = mi.submit(body, actor="t", tracker_dir=tmp_path / "tracker")
    assert res["intake_woken"] is None
