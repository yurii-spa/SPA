# LLM_FORBIDDEN
"""Подготовка обычного поручения владельца через СУЩЕСТВУЮЩИЙ `memory arch-review` (`--kind task-prep`, ARB 25.10).

Сцена — одноразовое git-дерево `test_role_pack._scene`; адаптер — тестовый (фикстура). Модель не вызывается:
успех фикстуры НЕ оценивает качество реальной модели. Проверяется: поручение сохранено дословно и привязано к
своему хешу, хешу контекста и ревизии; план читается владельцем; зарегистрированное, но не относящееся к делу
имя проверки готовности не даёт (готовности в записи нет вовсе); неоднозначность — вопрос; нет проверки —
предложение её подготовить; предмет полномочий — из словаря ADR-285; изменённый вход/контекст — устарело;
отказ/квота провайдера не теряет поручение и не повторяет вызов; пишется только каталог результата.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from spa_core.monitoring import card_acceptance as ca
from spa_core.studio_os.memory import arch_review as rv
from spa_core.studio_os.memory.__main__ import main as memory_cli
from spa_core.studio_os.model_roles import adapters as ad
from spa_core.tests import test_role_pack as trp
from spa_core.tests.test_s49_variant_a_connection import _fingerprint

REQUEST = "Хочу каждое утро видеть в пульте, прошёл ли ночной бэкап, и чтобы мне не приходилось лезть в логи."
PROBE = "contract_manifest_parity_agrees"          # зарегистрирована, но к бэкапу отношения не имеет


def _answer(*, plan="1. Найти, где пульт берёт состояние бэкапа (только чтение).\n"
                    "2. Показать строку «бэкап: прошёл / не прошёл / не измерено» с временем.\n"
                    "3. Не трогать сам бэкап, расписание и production.",
            acceptance=f"{rv.NEW_CHECK_MARK}: строка пульта совпадает с последним журналом бэкапа; "
                       "положительный контроль — свежий успешный журнал, отрицательный — журнала нет ⇒ «не измерено».",
            question="UNKNOWN: где хранится журнал ночного бэкапа на Mac.",
            subject="NONE"):
    return (f"## OUTCOME\nВ пульте каждое утро видно, прошёл ли ночной бэкап, с временем замера.\n"
            f"## PLAN\n{plan}\n## ACCEPTANCE PROPOSAL\n{acceptance}\n"
            f"## UNKNOWNS AND QUESTION\n{question}\n## PERMISSIONS\nsubject: {subject}\nТолько отображение.\n")


def _run(tmp_path, answer=None, request=REQUEST, adapters=None, out="out", calls=None):
    root, verified = trp._scene(tmp_path)
    fx = ad.fixture({"*": answer if answer is not None else _answer()})

    def spy(req, **kw):
        if calls is not None:
            calls.append(req.task_id)
        return fx(req, **kw)
    rec = rv.run_review(root, handover="docs/evidence/HANDOVER.md", task_id="owner-request-1", task=request,
                        verified_sha=verified, provider="fixture_test_adapter", out=tmp_path / out,
                        roadmap_item=17, adapters=adapters or {"fixture": spy}, at=trp.AT, kind=rv.KIND_PREP)
    return rec, tmp_path / out, root, verified


def test_an_ordinary_request_becomes_a_plan_bound_to_its_text_context_and_revision(tmp_path):
    rec, out, _, verified = _run(tmp_path)
    p = rec["preparation"]
    assert rec["status"] == "ok" and rec["kind"] == rv.KIND_PREP and rec["task"] == REQUEST
    assert rec["request_sha256"] == rv._sha(REQUEST) and len(rec["context_sha256"]) == 64
    assert rec["revisions"]["verified_code_sha"] == verified
    assert p["form"] == "plan" and p["acceptance"] == "new_check_proposed" and p["subject"] == "NONE"
    ctx = (out / "context.md").read_text(encoding="utf-8")
    assert rv._sha(ctx) == rec["context_sha256"]
    md = (out / "recommendation.md").read_text(encoding="utf-8")
    for heading in ("Поручение (дословно)", "Что должно получиться", "План", "Как проверим результат",
                    "Что неизвестно / вопрос", "Полномочия"):
        assert f"## {heading}" in md
    assert REQUEST in md and "предложено подготовить новую проверку (её ещё нет)" in md
    assert "не задание к исполнению" in md


def test_the_request_is_quoted_verbatim_in_the_instruction(tmp_path):
    seen = []
    fx = ad.fixture({"*": _answer()})

    def spy(req, **kw):
        seen.append(req.instruction)
        return fx(req, **kw)
    _run(tmp_path, adapters={"fixture": spy})
    assert REQUEST in seen[0] and "Do NOT do the work" in seen[0]


def test_a_registered_but_unrelated_check_never_makes_the_task_ready(tmp_path):
    rec, out, *_ = _run(tmp_path, answer=_answer(acceptance=f"`{PROBE}` — она зелёная, значит подойдёт."))
    p = rec["preparation"]
    assert PROBE in ca.PROBES
    assert p["acceptance"] == "registered_check_named_relevance_unproven"
    assert p["probes_named"] == [{"name": PROBE, "registered": True,
                                  "relevance": "NOT ESTABLISHED — a registered name is not proof it measures this request"}]
    flat = json.dumps(rec, ensure_ascii=False).lower()
    for flag in ('"ready"', '"approved"', '"execution_ready"', '"acceptance_probe"'):
        assert flag not in flat                       # готовность/одобрение не бывают полем схемы
    assert "отношение к поручению не установлено" in (out / "recommendation.md").read_text(encoding="utf-8")


def test_an_unregistered_check_name_is_not_a_check(tmp_path):
    rec, *_ = _run(tmp_path, answer=_answer(acceptance="`backup_line_matches_log` проверит строку."))
    p = rec["preparation"]
    assert p["probes_named"][0]["registered"] is False and p["acceptance"] == "none_usable"
    assert p["form"] == "incomplete" and any("no registered check" in r for r in p["reasons"])


def test_an_ambiguous_request_yields_a_plain_question_not_a_plan(tmp_path):
    rec, out, *_ = _run(tmp_path, request="Сделай, чтобы было лучше.",
                        answer=_answer(plan=rv.NO_PLAN_MARK, acceptance=f"{rv.NEW_CHECK_MARK}: после уточнения.",
                                       question="Что именно должно стать лучше: пульт, бэкап или сайт?"))
    assert rec["preparation"]["form"] == "clarification" and rec["preparation"]["question"] is True
    assert "нужно уточнение владельца" in (out / "recommendation.md").read_text(encoding="utf-8")


def test_no_plan_and_no_question_is_incomplete_not_silent(tmp_path):
    rec, *_ = _run(tmp_path, answer=_answer(plan=rv.NO_PLAN_MARK, question="UNKNOWN: всё."))
    assert rec["preparation"]["form"] == "incomplete"
    assert "no plan and no question to the owner" in rec["preparation"]["reasons"]


@pytest.mark.parametrize("subject,expected", [("MONEY", "MONEY"), ("IRREVERSIBLE", "IRREVERSIBLE"),
                                              ("OWNER_APPROVED", "UNKNOWN"), ("money", "UNKNOWN")])
def test_the_authority_subject_is_read_from_the_adr285_vocabulary_only(tmp_path, subject, expected):
    rec, *_ = _run(tmp_path, request="Переведи реальные деньги в новый пул.", answer=_answer(subject=subject))
    p = rec["preparation"]
    assert p["subject"] == expected and p["subject_declared"] == subject
    if expected == "UNKNOWN":
        assert any("ADR-285" in r for r in p["reasons"])


def test_a_changed_request_or_context_or_revision_makes_the_preparation_stale(tmp_path):
    rec, *_ = _run(tmp_path)
    ok = dict(request=REQUEST, context_sha256=rec["context_sha256"],
              verified_sha=rec["revisions"]["verified_code_sha"])
    assert rv.is_current(rec, **ok) == {"current": True, "reasons": []}
    assert rv.is_current(rec, **dict(ok, request=REQUEST + " ")) == {"current": False,
                                                                       "reasons": ["request text changed"]}
    assert rv.is_current(rec, **dict(ok, context_sha256="0" * 64))["reasons"] == ["context changed"]
    assert rv.is_current(rec, **dict(ok, verified_sha="1" * 40))["reasons"] == ["verified revision changed"]


@pytest.mark.parametrize("status,attempts", [("quota", 1), ("malformed", 1), ("ownership_unresolved", 1),
                                             ("timeout", 2), ("error", 2)])
def test_a_provider_failure_keeps_the_request_and_follows_the_role_retry_policy(tmp_path, status, attempts):
    """Квота/нераспознанный ответ/незакрытое владение — ровно один вызов; timeout/error — политика роли
    `architect` (max_attempts 2 в каноне), ни больше. Поручение не теряется ни в одном исходе."""
    calls = []
    rec, out, *_ = _run(tmp_path, answer={"status": status, "detail": "fixture"}, calls=calls)
    assert rec["status"] == status and rec["preparation"] is None and rec["task"] == REQUEST
    assert rec["request_sha256"] == rv._sha(REQUEST) and len(calls) == attempts
    md = (out / "recommendation.md").read_text(encoding="utf-8")
    assert REQUEST in md and f"Плана нет — {status}" in md and f"вызовов: {attempts}" in md


def test_no_provider_named_is_refused_and_keeps_the_request(tmp_path):
    root, verified = trp._scene(tmp_path)
    rec = rv.run_review(root, handover="docs/evidence/HANDOVER.md", task_id="t", task=REQUEST, verified_sha=verified,
                        provider=None, out=tmp_path / "o", roadmap_item=17, adapters={}, at=trp.AT, kind=rv.KIND_PREP)
    assert rec["status"] == "refused" and rec["preparation"] is None and rec["task"] == REQUEST
    assert "Плана нет — refused" in (tmp_path / "o" / "recommendation.md").read_text(encoding="utf-8")


def test_quota_is_called_exactly_once(tmp_path):
    calls = []
    _run(tmp_path, answer={"status": "quota"}, calls=calls)
    assert calls == ["owner-request-1"]


def test_preparation_writes_only_its_output_directory_and_no_card(tmp_path):
    root, verified = trp._scene(tmp_path)
    before = _fingerprint(root / ".git"), trp._g(root, "status", "--porcelain"), sorted(p.name for p in root.rglob("*"))
    rv.run_review(root, handover="docs/evidence/HANDOVER.md", task_id="t", task=REQUEST, verified_sha=verified,
                  provider="fixture_test_adapter", out=tmp_path / "o", roadmap_item=17,
                  adapters={"fixture": ad.fixture({"*": _answer()})}, at=trp.AT, kind=rv.KIND_PREP)
    after = _fingerprint(root / ".git"), trp._g(root, "status", "--porcelain"), sorted(p.name for p in root.rglob("*"))
    assert before == after


def test_the_cli_kind_task_prep_and_the_default_arch_kind(tmp_path):
    root, verified = trp._scene(tmp_path)
    fx = tmp_path / "fx.json"
    fx.write_text(json.dumps({"*": _answer()}), encoding="utf-8")
    base = ["arch-review", "--root", str(root), "--handover", "docs/evidence/HANDOVER.md", "--task-id", "t",
            "--task", REQUEST, "--verified-sha", verified, "--provider", "fixture_test_adapter",
            "--fixture", str(fx)]
    assert memory_cli(base + ["--kind", "task-prep", "--out", str(tmp_path / "p")]) == 0
    rec = json.loads((tmp_path / "p" / "review.json").read_text(encoding="utf-8"))
    assert rec["kind"] == "task-prep" and rec["preparation"]["form"] == "plan"
    assert memory_cli(base + ["--out", str(tmp_path / "a")]) == 1        # прежний вид: нет секций arch
    assert "kind" not in json.loads((tmp_path / "a" / "review.json").read_text(encoding="utf-8"))
    assert subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True,
                          text=True).stdout == ""


def test_an_unknown_kind_is_refused_before_the_provider(tmp_path):
    root, verified = trp._scene(tmp_path)
    with pytest.raises(rv.ReviewError):
        rv.run_review(root, handover="docs/evidence/HANDOVER.md", task_id="t", task="x", verified_sha=verified,
                      provider="fixture_test_adapter", out=tmp_path / "o", adapters={}, kind="execute")


# ── ARB R1/R2 (25.10): одна оценка → запись, текст владельцу, код выхода ───────────────────────────────

def _drop(answer: str, section: str, empty: bool = False) -> str:
    """Убрать раздел целиком (или оставить заголовок с пустым телом)."""
    parts = answer.split("## ")
    keep = []
    for part in parts:
        if part.startswith(section + "\n"):
            if empty:
                keep.append(section + "\n\n")
            continue
        keep.append(part)
    return "## ".join(keep)


@pytest.mark.parametrize("section", rv.PREP_SECTIONS)
@pytest.mark.parametrize("empty", [False, True])
def test_a_missing_or_empty_required_section_is_incomplete_everywhere(tmp_path, section, empty):
    rec, out, *_ = _run(tmp_path, answer=_drop(_answer(), section, empty=empty))
    p = rec["preparation"]
    assert rec["status"] == "ok" and p["form"] == "incomplete" and p["acceptable"] is False
    assert any(section in r for r in p["reasons"])
    md = (out / "recommendation.md").read_text(encoding="utf-8")
    assert "подготовка неполная" in md and "план готов к разбору" not in md


def _cli(tmp_path, answer, name):
    root, verified = trp._scene(tmp_path / name)
    fx = tmp_path / f"{name}.json"
    fx.write_text(json.dumps({"*": answer}), encoding="utf-8")
    rc = memory_cli(["arch-review", "--kind", "task-prep", "--root", str(root), "--handover",
                     "docs/evidence/HANDOVER.md", "--task-id", "t", "--task", REQUEST, "--verified-sha", verified,
                     "--provider", "fixture_test_adapter", "--fixture", str(fx), "--out", str(tmp_path / name / "o")])
    rec = json.loads((tmp_path / name / "o" / "review.json").read_text(encoding="utf-8"))
    return rc, rec


@pytest.mark.parametrize("name,answer,form,rc", [
    ("plan", _answer(), "plan", 0),
    ("question", _answer(plan=rv.NO_PLAN_MARK, question="Что именно улучшить: пульт или сайт?"), "clarification", 0),
    # ARB R2 дословно: все заголовки на месте, PLAN=NO PLAN, вопроса нет ⇒ incomplete ⇒ НЕ успех
    ("arb_r2", _answer(plan=rv.NO_PLAN_MARK, question="UNKNOWN: нет данных."), "incomplete", 1),
    ("no_check", _answer(acceptance="Посмотрим глазами."), "incomplete", 1),
    ("missing", _drop(_answer(), "OUTCOME"), "incomplete", 1),
    ("bad_subject", _answer(subject="OWNER_OK"), "incomplete", 1),
], ids=["plan", "question", "arb_r2", "no_check", "missing", "bad_subject"])
def test_the_cli_exit_follows_the_same_assessment_as_the_record(tmp_path, name, answer, form, rc):
    got_rc, rec = _cli(tmp_path, answer, name)
    assert rec["preparation"]["form"] == form and got_rc == rc
    assert rec["preparation"]["acceptable"] is (rc == 0)


def test_a_clarification_with_an_unknown_subject_is_still_a_valid_question(tmp_path):
    rec, *_ = _run(tmp_path, answer=_answer(plan=rv.NO_PLAN_MARK, question="Что именно?", subject="UNKNOWN_YET"))
    assert rec["preparation"]["form"] == "clarification" and rec["preparation"]["subject"] == "UNKNOWN"


def test_the_arch_kind_keeps_its_exit_contract(tmp_path):
    """Прежний вид: 0 ⇔ структура полна; task-prep-оценка на него не влияет."""
    from spa_core.tests.test_model_roles_review import GOOD
    root, verified = trp._scene(tmp_path)
    fx = tmp_path / "fx.json"
    base = ["arch-review", "--root", str(root), "--handover", "docs/evidence/HANDOVER.md", "--task-id", "t",
            "--task", "x", "--verified-sha", verified, "--provider", "fixture_test_adapter", "--fixture", str(fx)]
    fx.write_text(json.dumps({"*": GOOD}), encoding="utf-8")
    assert memory_cli(base + ["--out", str(tmp_path / "a")]) == 0
    fx.write_text(json.dumps({"*": GOOD.split("## CLAUDE TASK")[0]}), encoding="utf-8")
    assert memory_cli(base + ["--out", str(tmp_path / "b")]) == 1


@pytest.mark.parametrize("subject", ["NONE", "MONEY"])
def test_the_subject_is_shown_as_a_model_proposal_not_a_permission(tmp_path, subject):
    rec, out, *_ = _run(tmp_path, answer=_answer(subject=subject))
    assert rec["preparation"]["subject_note"] == rv.SUBJECT_NOTE
    md = (out / "recommendation.md").read_text(encoding="utf-8")
    assert "предложен моделью" in md and "не разрешение исполнять" in md and "даже NONE" in md
