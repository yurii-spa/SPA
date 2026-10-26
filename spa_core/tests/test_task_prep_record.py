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
    assert p["state"] == "plan" and "предложение для разбора, работа не начата" in p["head"]
    assert p["outcome"] == "В пульте видно, прошёл ли ночной бэкап." and "Найти источник" in p["plan"]
    assert p["by"] == "тестовый адаптер (не модель)" and "не проверка прав" in p["authority"]
    assert row["technical"]["подготовка: код состояния"] == "current"
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
    assert row["state"] == "не взято в работу: проверка результата ещё не назначена; работа не начата"
    assert row["preparation"]["state"] == "plan" and "проба" not in row["state"]


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
    assert p["state"] == "stale" and "текст записи изменился" in p["why"] and "устарел" in p["head"]
    assert "plan" not in p                                            # устаревший план не показывается как план
    second = _prepare(scene, card, at="2026-10-26T10:00:00+00:00")
    assert second["action"] == "prepared" and second["run"] != first["run"]
    assert _tree(Path(first["run"])) == old and len(rv.preparation_runs(scene.prep, card.name)) == 2
    assert _row(scene, card)["preparation"]["state"] == "plan"


def test_a_changed_source_makes_the_plan_stale_by_an_independent_reread(scene):
    card = _submit(scene)
    _prepare(scene, card)
    h = scene.root / "docs/evidence/HANDOVER.md"
    h.write_text(h.read_text(encoding="utf-8") + "\nновая строка\n", encoding="utf-8")
    row = _row(scene, card)
    assert row["preparation"]["state"] == "stale" and "изменились документы" in row["preparation"]["why"]
    assert "docs/evidence/HANDOVER.md" in row["technical"]["подготовка: диагностика"]


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
    assert p["state"] == "incomplete" and "Подготовка не удалась" in p["head"]
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


# ── ARB 26.10 R1: идентичность и свежесть подготовки (воспроизведения ARB) ─────────────────────────────

def _extra(s, text="SOURCE VERSION A"):
    p = s.tmp / "extra.md"
    p.write_text(text, encoding="utf-8")
    return p


def _prepare_with(s, card, adapters, extra=(), at="2026-10-26T09:00:00+00:00"):
    return rv.prepare_record(s.root, card, s.prep, handover="docs/evidence/HANDOVER.md", verified_sha=s.verified,
                             provider="fixture_test_adapter", adapters=adapters, extra=extra, roadmap_item=17, at=at)


def _mutating_adapter(s, mutate):
    fx = ad.fixture({"*": _answer()})

    def run(req, **kw):
        s.calls.append(req.task_id)
        mutate()
        return fx(req, **kw)
    return {"fixture": run}


def test_r1a_a_source_changed_during_the_call_is_stale_not_current(scene):
    card = _submit(scene)
    extra = _extra(scene)
    res = _prepare_with(scene, card, _mutating_adapter(scene, lambda: extra.write_text("SOURCE VERSION B",
                                                                                       encoding="utf-8")),
                        extra=[extra])
    run = Path(res["run"])
    rec = json.loads((run / rv.PREP_RECORD_FILE).read_text(encoding="utf-8"))
    assert "SOURCE VERSION A" in (run / "context.md").read_text(encoding="utf-8")
    assert rec["sources_sha256"][rv._rel(scene.root, extra)] == hashlib.sha256(b"SOURCE VERSION A").hexdigest()
    assert res["state"]["state"] == "stale" and _row(scene, card)["preparation"]["state"] == "stale"


def test_r1b_a_new_source_on_repeat_is_a_new_preparation_not_unchanged(scene):
    card = _submit(scene)
    first = _prepare(scene, card)
    extra = _extra(scene, "NEW SOURCE ON REPEAT")
    again = _prepare_with(scene, card, _adapters(scene, _answer()), extra=[extra],
                          at="2026-10-26T09:05:00+00:00")
    assert again["action"] == "prepared" and again["run"] != first["run"] and len(scene.calls) == 2
    assert "NEW SOURCE ON REPEAT" in (Path(again["run"]) / "context.md").read_text(encoding="utf-8")
    same = _prepare_with(scene, card, _adapters(scene, _answer()), extra=[extra], at="2026-10-26T10:00:00+00:00")
    assert same["action"] == "unchanged" and len(scene.calls) == 2      # те же входы, другое время ⇒ повтор


@pytest.mark.parametrize("change", ["provider_config", "verified_revision"])
def test_r1b_other_identity_parts_are_not_ignored(scene, change):
    from spa_core.studio_os.model_roles import contract as c
    card = _submit(scene)
    _prepare(scene, card)
    if change == "provider_config":
        cfg = c.load_config()
        cfg["roles"]["architect"]["deadline_s"] = 299
        res = rv.prepare_record(scene.root, card, scene.prep, handover="docs/evidence/HANDOVER.md",
                                verified_sha=scene.verified, provider="fixture_test_adapter",
                                adapters=_adapters(scene, _answer()), config=cfg, roadmap_item=17,
                                at="2026-10-26T09:01:00+00:00")
    else:
        other = trp._g(scene.root, "rev-parse", "HEAD")
        assert other != scene.verified
        res = rv.prepare_record(scene.root, card, scene.prep, handover="docs/evidence/HANDOVER.md",
                                verified_sha=other, provider="fixture_test_adapter",
                                adapters=_adapters(scene, _answer()), roadmap_item=17, at="2026-10-26T09:01:00+00:00")
    assert res["action"] == "prepared" and len(scene.calls) == 2


def test_r1c_the_card_changed_during_the_call_is_stale_not_current(scene):
    card = _submit(scene)
    res = _prepare_with(scene, card, _mutating_adapter(scene, lambda: card.write_text(
        card.read_text(encoding="utf-8").replace(REQUEST, "Другое поручение."), encoding="utf-8")))
    assert res["state"]["state"] == "stale" and "the request text changed" in res["state"]["reasons"]


def test_the_cli_prepares_again_when_a_source_changed(scene, tmp_path):
    card = _submit(scene)
    extra = _extra(scene)
    fx = tmp_path / "fx.json"
    fx.write_text(json.dumps({"*": _answer()}), encoding="utf-8")
    from spa_core.studio_os.memory.__main__ import main as memory_cli
    base = ["prepare-record", "--root", str(scene.root), "--card", str(card), "--prep-root", str(scene.prep),
            "--handover", "docs/evidence/HANDOVER.md", "--verified-sha", scene.verified, "--provider",
            "fixture_test_adapter", "--fixture", str(fx), "--roadmap-item", "17", "--extra-context", str(extra)]
    assert memory_cli(base) == 0
    extra.write_text("changed after", encoding="utf-8")
    assert memory_cli(base) == 0                       # входы изменились ⇒ новая подготовка, свежая
    card.write_text(card.read_text(encoding="utf-8").replace(REQUEST, "x"), encoding="utf-8")
    assert len(rv.preparation_runs(scene.prep, card.name)) == 2


# ── ARB 26.10 R2: одновременные запуски разных ПРОЦЕССОВ и прерывание ────────────────────────────────────

_WORKER = r'''
import json, sys, time
from pathlib import Path
from spa_core.studio_os.memory import arch_review as rv
from spa_core.studio_os.model_roles import adapters as ad
a = json.loads(sys.argv[1])
fx = ad.fixture({"*": a["answer"]})
def slow(req, **kw):
    with open(a["calls"], "a") as f:
        f.write(req.task_id + "\n")
    Path(a["started"]).write_text("1")
    deadline = time.time() + 30
    while not Path(a["go"]).exists() and time.time() < deadline:
        time.sleep(0.05)
    return fx(req, **kw)
res = rv.prepare_record(Path(a["root"]), Path(a["card"]), Path(a["prep"]), handover="docs/evidence/HANDOVER.md",
                        verified_sha=a["verified"], provider="fixture_test_adapter", adapters={"fixture": slow},
                        roadmap_item=17, at="2026-10-26T09:00:00+00:00")
print(json.dumps({"action": res["action"], "run": res["run"]}))
'''


def _spawn(scene, card, tag):
    import subprocess
    import sys
    import os as _os
    args = {"answer": _answer(), "calls": str(scene.tmp / "calls.txt"), "started": str(scene.tmp / f"started-{tag}"),
            "go": str(scene.tmp / "go"), "root": str(scene.root), "card": str(card), "prep": str(scene.prep),
            "verified": scene.verified}
    return subprocess.Popen([sys.executable, "-c", _WORKER, json.dumps(args)], cwd=str(_REPO),
                            env=dict(_os.environ, PYTHONPATH=str(_REPO)), stdout=subprocess.PIPE, text=True)


def _wait(path, seconds=30.0):
    import time
    t0 = time.time()
    while not Path(path).exists():
        assert time.time() - t0 < seconds, f"{path} did not appear"
        time.sleep(0.05)


def test_r2_two_processes_call_the_provider_once_and_never_share_a_result(scene):
    card = _submit(scene)
    a = _spawn(scene, card, "a")
    _wait(scene.tmp / "started-a")
    b = _spawn(scene, card, "b")
    out_b = json.loads(b.communicate(timeout=60)[0])
    (scene.tmp / "go").write_text("1")
    out_a = json.loads(a.communicate(timeout=60)[0])
    calls = (scene.tmp / "calls.txt").read_text().splitlines()
    assert calls == [card.stem], calls
    assert out_a["action"] == "prepared" and out_b == {"action": "busy", "run": None}
    assert len(rv.preparation_runs(scene.prep, card.name)) == 1
    after = rv.prepare_record(scene.root, card, scene.prep, handover="docs/evidence/HANDOVER.md",
                              verified_sha=scene.verified, provider="fixture_test_adapter",
                              adapters=_adapters(scene, _answer()), roadmap_item=17, at="2026-10-26T09:00:00+00:00")
    assert after["action"] == "unchanged" and after["run"] == out_a["run"]


def test_r2_an_interrupted_run_stays_incomplete_is_kept_and_frees_the_record(scene):
    import signal
    card = _submit(scene)
    a = _spawn(scene, card, "a")
    _wait(scene.tmp / "started-a")
    a.send_signal(signal.SIGKILL)
    a.wait(timeout=30)
    store = scene.prep / card.stem
    partial = [d for d in store.iterdir() if d.is_dir()]
    assert len(partial) == 1 and not (partial[0] / rv.PREP_RECORD_FILE).exists()
    assert rv.preparation_runs(scene.prep, card.name) == []          # незавершённое не считается результатом
    assert _row(scene, card)["preparation"]["state"] == "none"
    res = _prepare(scene, card)                                       # захват освобождён смертью процесса
    assert res["action"] == "prepared" and Path(res["run"]) != partial[0] and partial[0].is_dir()


# ── ARB 26.10 U1: понятный блок — вопрос это вопрос, служебное — в технических подробностях ─────────────

_RAW = ("NO PLAN", "NEW CHECK NEEDED", "UNKNOWN", "subject:", "PROBES", "проба:", "current", "incomplete",
        "request text changed", "provider status")


def _visible(row):
    p = row.get("preparation") or {}
    return [row["state"], row.get("reason") or "", row.get("next_step") or ""] + [
        str(v) for k, v in p.items() if k not in ("technical", "state", "known", "alert") and isinstance(v, str)]


def test_a_clarification_is_shown_as_a_question_without_a_fictitious_plan(scene):
    card = _submit(scene)
    _prepare(scene, card, answer=_answer(plan=rv.NO_PLAN_MARK, question="Что именно улучшить: пульт или сайт?"))
    row = _row(scene, card)
    p = row["preparation"]
    assert p["state"] == "clarification" and p["head"] == "Нужно уточнение"
    assert "plan" not in p and "outcome" not in p and p["question"].endswith("пульт или сайт?")
    assert "План подготовлен" not in " ".join(_visible(row))


@pytest.mark.parametrize("answer,provider", [
    (_answer(), "fixture_test_adapter"),
    (_answer(plan=rv.NO_PLAN_MARK, question="UNKNOWN: где журнал.\nВопрос: какой журнал?"), "fixture_test_adapter"),
    ({"status": "quota"}, "fixture_test_adapter"),
])
def test_visible_text_carries_no_internal_markers_and_the_codes_stay_in_technical_details(scene, answer, provider):
    from spa_core.owner_queue import cockpit_dispatch as cd
    card = _submit(scene)
    oi.run_note_intake(NOW, tracker_dir=scene.tracker, repo_root=scene.tmp, notify=scene.sent.append,
                       history=lambda _b: {"verdict": "NEW", "response": ""}, ingest=False)
    cd.dispatch(executor="cycle-a", tracker_dir=scene.tracker, claim=lambda *a: None, now=NOW,
                outbox_path=scene.tmp / "obox.json", notify=scene.sent.append)
    _prepare(scene, card, answer=answer, provider=provider)
    row = _row(scene, card)
    for text in _visible(row):
        for raw in _RAW:
            assert raw not in text, (raw, text)
    tech = row["technical"]
    assert tech["подготовка: код состояния"] in ("current", "incomplete") and tech["подготовка: каталог"]
    assert tech["причина (служебная)"] and tech["следующий шаг (служебный)"]   # служебное не потеряно


def test_the_delivery_switch_is_off_unless_the_environment_names_a_store(monkeypatch, tmp_path):
    monkeypatch.delenv(mc.TASK_PREP_ROOT_ENV, raising=False)
    assert mc.MCInputs().task_prep_root is None
    monkeypatch.setenv(mc.TASK_PREP_ROOT_ENV, "  ")
    assert mc.MCInputs().task_prep_root is None
    monkeypatch.setenv(mc.TASK_PREP_ROOT_ENV, str(tmp_path / "store"))
    assert mc.MCInputs().task_prep_root == tmp_path / "store"


# ── ARB 26.10 R1 (остаток): версия кода — по СОДЕРЖИМОМУ, не по списку путей ───────────────────────────

def _commit(s, rel, text, msg):
    p = s.root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    trp._g(s.root, "add", rel)
    trp._g(s.root, "commit", "-q", "-m", msg)


def test_two_successive_commits_of_one_code_file_make_the_plan_stale_and_repreparation_new(scene):
    """Воспроизведение ARB: тот же verified_sha, те же документы, spa_core/x.py x=2 → x=3."""
    _commit(scene, "spa_core/x.py", "x = 2\n", "x=2")
    card = _submit(scene)
    first = _prepare(scene, card)
    assert first["state"]["state"] == "current"
    _commit(scene, "spa_core/x.py", "x = 3\n", "x=3")
    row = _row(scene, card)
    assert row["preparation"]["state"] == "stale" and "изменилась версия кода" in row["preparation"]["why"]
    again = _prepare(scene, card, at="2026-10-26T09:30:00+00:00")
    assert again["action"] == "prepared" and again["run"] != first["run"] and len(scene.calls) == 2
    assert _row(scene, card)["preparation"]["state"] == "plan"


@pytest.mark.parametrize("change", ["modified", "untracked", "staged"])
def test_an_uncommitted_code_change_makes_the_plan_stale(scene, change):
    _commit(scene, "spa_core/x.py", "x = 2\n", "x=2")
    card = _submit(scene)
    _prepare(scene, card)
    if change == "modified":
        (scene.root / "spa_core/x.py").write_text("x = 4\n", encoding="utf-8")
    elif change == "untracked":
        (scene.root / "spa_core/y.py").write_text("y = 1\n", encoding="utf-8")
    else:
        (scene.root / "spa_core/x.py").write_text("x = 5\n", encoding="utf-8")
        trp._g(scene.root, "add", "spa_core/x.py")
    assert _row(scene, card)["preparation"]["state"] == "stale"
    assert _prepare(scene, card, at="2026-10-26T09:31:00+00:00")["action"] == "prepared"


def test_a_documentation_only_commit_keeps_the_plan_current_and_reusable(scene):
    """Определено явно: docs/ — не код. Документы, из которых построен план, связаны своими байтами отдельно;
    коммит документа, НЕ входившего в контекст, план не делает устаревшим."""
    _commit(scene, "spa_core/x.py", "x = 2\n", "x=2")
    card = _submit(scene)
    first = _prepare(scene, card)
    _commit(scene, "docs/unrelated_note.md", "заметка\n", "docs only")
    assert _row(scene, card)["preparation"]["state"] == "plan"
    again = _prepare(scene, card, at="2026-10-26T11:00:00+00:00")       # другое время, те же входы
    assert again["action"] == "unchanged" and again["run"] == first["run"] and len(scene.calls) == 1


def test_a_documentation_commit_to_a_context_source_still_makes_it_stale(scene):
    card = _submit(scene)
    _prepare(scene, card)
    h = scene.root / "docs/evidence/HANDOVER.md"
    _commit(scene, "docs/evidence/HANDOVER.md", h.read_text(encoding="utf-8") + "\nдописано\n", "handover edit")
    assert _row(scene, card)["preparation"]["state"] == "stale"


def test_an_old_record_without_a_code_fingerprint_never_passes(scene):
    card = _submit(scene)
    run = Path(_prepare(scene, card)["run"])
    rec_path = run / rv.PREP_RECORD_FILE
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    rec["input_identity_parts"].pop("code_identity")                 # запись прежнего формата (только в сцене)
    rec_path.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    row = _row(scene, card)
    assert row["preparation"]["state"] == "stale" and "отпечатка версии кода" in row["preparation"]["why"]
    assert _prepare(scene, card, at="2026-10-26T09:32:00+00:00")["action"] == "prepared"


def test_code_identity_is_content_not_paths_and_none_when_unmeasurable(scene, tmp_path):
    _commit(scene, "spa_core/x.py", "x = 2\n", "x=2")
    a = rv.code_identity(scene.root)
    _commit(scene, "spa_core/x.py", "x = 3\n", "x=3")
    b = rv.code_identity(scene.root)
    assert a and b and a != b
    plain = tmp_path / "not_a_repo"
    plain.mkdir()
    assert rv.code_identity(plain) is None


def test_the_code_root_switch_names_the_pinned_snapshot(monkeypatch, tmp_path):
    monkeypatch.delenv(mc.TASK_PREP_CODE_ROOT_ENV, raising=False)
    assert mc.MCInputs().task_prep_code_root is None
    monkeypatch.setenv(mc.TASK_PREP_CODE_ROOT_ENV, str(tmp_path / "pin"))
    assert mc.MCInputs().task_prep_code_root == tmp_path / "pin"


def test_freshness_is_judged_against_the_root_the_plan_was_made_from(scene, tmp_path):
    """Подготовка из закреплённого снимка: свежесть по ТОМУ ЖЕ корню; чужое дерево — другая версия кода."""
    _commit(scene, "spa_core/x.py", "x = 2\n", "x=2")
    card = _submit(scene)
    _prepare(scene, card)
    other_root, _v = trp._scene(tmp_path / "other")
    rec = mc.cockpit_records(mc._cards(scene.tracker), NOW, source="t", task_prep_root=scene.prep, code_root=other_root)
    assert rec["items"][0]["preparation"]["state"] == "stale"
    assert "the code version changed" in rec["items"][0]["preparation"]["reasons"]
    rec = mc.cockpit_records(mc._cards(scene.tracker), NOW, source="t", task_prep_root=scene.prep, code_root=scene.root)
    assert rec["items"][0]["preparation"]["state"] == "current"


def test_code_identity_argv_paths_equal_the_code_scope():
    """Пути в argv git-вызовов code_identity — литералы (их должна разрешать перепись происхождения git-ссылок);
    этот тест держит их равными CODE_SCOPE, чтобы две копии не разошлись молча."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(rv.code_identity))
    want = list(rv.CODE_SCOPE)
    seen = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.List, ast.Call)):
            items = node.elts if isinstance(node, ast.List) else node.args
            vals = [e.value for e in items if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if "--" in vals:
                assert vals[vals.index("--") + 1:] == want, vals
                seen += 1
    assert seen == 3
