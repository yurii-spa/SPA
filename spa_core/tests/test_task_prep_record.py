# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — NOW и строки at= передаются аргументами now=/at= в submit, приём, prepare_record и cockpit_records; стенные часы не читаются
"""Обычная запись пульта → её подготовка в существующих «Моих записях» (ARB 26.10) — на временных данных.

Связь: `mission_intake.submit` (запись) → ЯВНЫЙ `arch_review.prepare_record` (тестовый адаптер, не модель) →
`mission_control.cockpit_records(task_prep_root=…)` → `owner_view.my_records` → UI. Читающее представление
ничего не готовит, никого не зовёт и ничего не пишет; подготовка не назначает пробу, не захватывает карточку и
не меняет статус. Свежесть — по НЕЗАВИСИМО перечитанной карточке и источникам, не по сохранённым хешам.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import card_acceptance as ca
from spa_core.owner_queue import intake as oi
from spa_core.studio_os import mission_control as mc
from spa_core.studio_os import mission_intake as mi
from spa_core.studio_os import owner_view as ov
from spa_core.studio_os.memory import arch_review as rv
from spa_core.studio_os.model_roles import adapters as ad
from spa_core.tests import test_role_pack as trp

NOW = datetime(2026, 10, 26, 9, 0, 0, tzinfo=timezone.utc)
REQUEST = "Хочу каждое утро видеть в пульте, прошёл ли ночной бэкап."
_REPO = Path(__file__).resolve().parents[2]


def _answer(plan="1. Найти источник состояния бэкапа (только чтение).\n2. Показать одну строку в пульте.",
            question="UNKNOWN: где журнал бэкапа.", acceptance=f"{rv.NEW_CHECK_MARK}: строка совпадает с журналом."):
    return (f"## OUTCOME\nВ пульте видно, прошёл ли ночной бэкап.\n## PLAN\n{plan}\n"
            f"## ACCEPTANCE PROPOSAL\n{acceptance}\n## UNKNOWNS AND QUESTION\n{question}\n"
            "## PERMISSIONS\nsubject: NONE\nТолько отображение.\n")


@pytest.fixture(autouse=True)
def _no_real_classifier(monkeypatch, tmp_path):
    from spa_core.telegram import ask_router
    monkeypatch.setattr(ask_router, "_CLAUDE", str(tmp_path / "no-real-claude-in-tests"))


@pytest.fixture
def scene(tmp_path):
    root, verified = trp._scene(tmp_path / "code")
    tracker = tmp_path / "tracker"
    tracker.mkdir()

    class S:
        pass
    s = S()
    s.root, s.verified, s.tracker, s.prep = root, verified, tracker, tmp_path / "prep"
    s.calls, s.sent, s.tmp = [], [], tmp_path
    return s


def _submit(s, text=REQUEST, sid="prep-record-0001"):
    prov = mi.provenance_for("public", verified_email="owner@example.org", owner_emails=("owner@example.org",))
    body = {"text": text, "transcript": text, "kind": "task", "submission_id": sid}
    res = mi.submit(json.dumps(body).encode("utf-8"), actor="local", tracker_dir=s.tracker, now=NOW, provenance=prov)
    return s.tracker / res["card"]


def _adapters(s, answer):
    fx = ad.fixture({"*": answer})

    def spy(req, **kw):
        s.calls.append(req.task_id)
        return fx(req, **kw)
    return {"fixture": spy}


def _prepare(s, card, answer=None, provider="fixture_test_adapter", at="2026-10-26T09:00:00+00:00"):
    return rv.prepare_record(s.root, card, s.prep, handover="docs/evidence/HANDOVER.md", verified_sha=s.verified,
                             provider=provider, adapters=_adapters(s, answer if answer is not None else _answer()),
                             roadmap_item=17, at=at)


def _row(s, card):
    rec = mc.cockpit_records(mc._cards(s.tracker), NOW, source="tracker", task_prep_root=s.prep, code_root=s.root)
    view = ov.my_records({"intake": {"my_records": rec}}, None)
    return next(r for r in view["rows"] if r["technical"]["карточка"] == Path(card).name)


def _tree(d: Path) -> dict:
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(d.rglob("*")) if p.is_file()} if d.exists() else {}


def _fm(p):
    return ca.parse_frontmatter(Path(p).read_text(encoding="utf-8"))


def test_an_ordinary_record_without_a_probe_gets_a_visible_plan_and_an_honest_execution_state(scene):
    card = _submit(scene)
    oi.run_note_intake(NOW, tracker_dir=scene.tracker, repo_root=scene.tmp, notify=scene.sent.append,
                       history=lambda _b: {"verdict": "NEW", "response": ""}, ingest=False)
    before = card.read_bytes()
    res = _prepare(scene, card)
    assert res["action"] == "prepared" and res["state"]["state"] == "current"
    assert card.read_bytes() == before                                  # подготовка карточку не пишет
    fm = _fm(card)
    assert fm["status"] == "new" and "acceptance_probe" not in fm and "claimed_by" not in fm
    row = _row(scene, card)
    p = row["preparation"]
    assert p["state"] == "current" and "предложение для разбора, не начало работы" in p["state_ru"]
    assert p["outcome"] == "В пульте видно, прошёл ли ночной бэкап." and "Найти источник" in p["plan"]
    assert p["by"] == "тестовый адаптер (не модель)" and "даже NONE" in p["authority"]
    assert row["state"] == "принято, ждёт исполнителя"                  # исполнение — отдельно и честно


def test_preparation_does_not_assign_a_probe_so_the_dispatcher_still_refuses(scene):
    from spa_core.owner_queue import cockpit_dispatch as cd
    card = _submit(scene)
    oi.run_note_intake(NOW, tracker_dir=scene.tracker, repo_root=scene.tmp, notify=scene.sent.append,
                       history=lambda _b: {"verdict": "NEW", "response": ""}, ingest=False)
    _prepare(scene, card, answer=_answer(acceptance="`contract_manifest_parity_agrees` подойдёт."))
    res = cd.dispatch(executor="cycle-a", tracker_dir=scene.tracker, claim=lambda *a: None, now=NOW,
                      outbox_path=scene.tmp / "obox.json", notify=scene.sent.append)
    assert res["taken"] is None and res["no_probe"] == [card.name]
    assert _fm(card)["status"] == "new" and "acceptance_probe" not in _fm(card)
    row = _row(scene, card)
    assert row["state"].startswith("не взято в работу") and row["preparation"]["state"] == "current"


def test_repeated_processing_creates_no_duplicates_and_ignores_incidental_timestamps(scene):
    card = _submit(scene)
    first = _prepare(scene, card)
    again = _prepare(scene, card, at="2026-10-26T11:30:00+00:00")       # другое время, те же входы
    assert again["action"] == "unchanged" and again["run"] == first["run"]
    assert scene.calls == [card.stem] and len(rv.preparation_runs(scene.prep, card.name)) == 1
    dup = _submit(scene)                                                # повторная отправка того же id
    assert dup == card and len(list(scene.tracker.glob("inbox-*.md"))) == 1


def test_a_changed_request_makes_the_shown_plan_stale_and_keeps_the_old_evidence(scene):
    card = _submit(scene)
    first = _prepare(scene, card)
    old = _tree(Path(first["run"]))
    card.write_text(card.read_text(encoding="utf-8").replace(REQUEST, REQUEST + " И за прошлую неделю."),
                    encoding="utf-8")
    p = _row(scene, card)["preparation"]
    assert p["state"] == "stale" and "request text changed" in p["why"] and "устарел" in p["state_ru"]
    second = _prepare(scene, card, at="2026-10-26T10:00:00+00:00")
    assert second["action"] == "prepared" and second["run"] != first["run"]
    assert _tree(Path(first["run"])) == old and len(rv.preparation_runs(scene.prep, card.name)) == 2
    assert _row(scene, card)["preparation"]["state"] == "current"


def test_a_changed_source_makes_the_plan_stale_by_an_independent_reread(scene):
    card = _submit(scene)
    _prepare(scene, card)
    h = scene.root / "docs/evidence/HANDOVER.md"
    h.write_text(h.read_text(encoding="utf-8") + "\nновая строка\n", encoding="utf-8")
    p = _row(scene, card)["preparation"]
    assert p["state"] == "stale" and "docs/evidence/HANDOVER.md" in p["why"]


def test_echoing_stored_hashes_is_not_a_freshness_check(scene):
    """Сохранённый хеш поручения подменён на хеш ТЕКУЩЕГО текста при изменённой карточке не той стороной:
    состояние считает читатель по карточке, а не по записи — подменить запись мало."""
    card = _submit(scene)
    run = Path(_prepare(scene, card)["run"])
    card.write_text(card.read_text(encoding="utf-8").replace(REQUEST, "Совсем другое поручение."), encoding="utf-8")
    st = rv.preparation_state(run, card_text=card.read_text(encoding="utf-8"), root=scene.root)
    assert st["state"] == "stale"


@pytest.mark.parametrize("answer,provider", [
    (_answer(plan=rv.NO_PLAN_MARK, question="UNKNOWN: нет данных."), "fixture_test_adapter"),   # incomplete
    ({"status": "quota"}, "fixture_test_adapter"),
    (_answer(), None),                                                                          # refused
])
def test_an_incomplete_or_refused_preparation_never_looks_ready(scene, answer, provider):
    card = _submit(scene)
    _prepare(scene, card, answer=answer, provider=provider)
    p = _row(scene, card)["preparation"]
    assert p["state"] == "incomplete" and "плана для разбора нет" in p["state_ru"]
    assert "plan" not in p and "outcome" not in p


def test_the_read_model_prepares_nothing_writes_nothing_and_calls_no_one(scene):
    card = _submit(scene)
    _prepare(scene, card)
    calls = list(scene.calls)
    before = (_tree(scene.prep), _tree(scene.tracker))
    for _ in range(2):
        _row(scene, card)
    assert (_tree(scene.prep), _tree(scene.tracker)) == before and scene.calls == calls


def test_no_preparation_and_production_default_are_distinct(scene):
    card = _submit(scene)
    assert _row(scene, card)["preparation"]["state"] == "none"
    rec = mc.cockpit_records(mc._cards(scene.tracker), NOW, source="tracker")          # task_prep_root=None
    assert "preparation" not in rec["items"][0]
    view = ov.my_records({"intake": {"my_records": rec}}, None)
    assert "preparation" not in view["rows"][0]


def test_model_text_is_carried_as_text_and_the_ui_never_parses_html(scene):
    evil = '<script>alert(1)</script><img src=x onerror=alert(2)>'
    card = _submit(scene)
    _prepare(scene, card, answer=_answer(plan=f"1. {evil}"))
    p = _row(scene, card)["preparation"]
    assert evil in p["plan"]                                          # дословно как строка, не вырезано и не HTML
    js = (_REPO / "spa_core/studio_os/mission_ui/app.js").read_text(encoding="utf-8")
    body = js[js.index("function renderRecordPreparation"):js.index("function renderWorkArea")]
    # names of HTML/code sinks checked for ABSENCE in the UI source — nothing here is evaluated
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
        assert sink not in body and sink not in js
    assert "h(\"p\"" in body                                           # только текстовые узлы через h()


def test_a_record_without_a_task_section_is_refused_before_any_call(scene):
    bad = scene.tracker / "inbox-no-task.md"
    bad.write_text("---\nstatus: new\nsource: cockpit\n---\nпросто текст\n", encoding="utf-8")
    with pytest.raises(rv.ReviewError):
        _prepare(scene, bad)
    assert scene.calls == []


def test_request_text_extraction_ignores_intake_fields_and_the_kind_line(scene):
    card = _submit(scene)
    assert rv.request_text_of(card.read_text(encoding="utf-8")) == REQUEST
