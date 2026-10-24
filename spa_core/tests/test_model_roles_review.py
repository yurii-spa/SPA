# LLM_FORBIDDEN
"""Команда архитектурного разбора (STUDIO-OS-MODELS-01, инкремент 4) — контроли без вызова модели.

Сцена — одноразовое git-дерево `test_role_pack._scene`; адаптер — тестовый (фикстура) или подменённый
запуск Claude. Проверяется: пакет и результат сохранены с task_id, ревизиями, хешем контекста, провайдером,
статусом, временем и usage; рекомендация в нужной форме; неполнота названа; сбой не становится
рекомендацией; запись ТОЛЬКО в каталог результата; секрет из фрагмента не уходит.
"""
from __future__ import annotations

import hashlib
import json
import subprocess

import pytest

from spa_core.studio_os.model_roles import adapters as ad
from spa_core.studio_os.memory import arch_review as rv
from spa_core.studio_os.memory.__main__ import main as memory_cli
from spa_core.studio_os.model_roles.__main__ import main as cli
from spa_core.tests import test_role_pack as trp
from spa_core.tests.test_s49_variant_a_connection import _fingerprint

GOOD = """## FACTS
- empty ledger ⇒ generated_at None [docs/x.md]
## UNKNOWNS
- UNKNOWN: bot copy
## DECISION
Show NOT_MEASURED; rejected: counters with zeros.
## ACCEPTANCE CRITERIA
- pytest spa_core/tests/test_x.py
## CLAUDE TASK
```text
Fix B-12 in spa_core/telegram/views/capital.py; no production; no main.
```
"""


def _scene(tmp_path, **kw):
    root, verified = trp._scene(tmp_path, **kw)
    return root, verified


def _run(root, verified, tmp_path, answer=GOOD, provider="fixture_test_adapter", extra=(), adapters=None):
    out = tmp_path / "out"
    rec = rv.run_review(root, handover="docs/evidence/HANDOVER.md", task_id="B-12-review",
                        task="What must the bot show for an empty ledger?", verified_sha=verified,
                        provider=provider, out=out, roadmap_item=17, extra=extra,
                        adapters=adapters if adapters is not None else {"fixture": ad.fixture({"*": answer})},
                        at=trp.AT)
    return rec, out


def test_the_review_saves_pack_and_result_with_every_identity(tmp_path):
    root, verified = _scene(tmp_path)
    rec, out = _run(root, verified, tmp_path)
    doc = json.loads((out / "review.json").read_text(encoding="utf-8"))
    context = (out / "context.md").read_text(encoding="utf-8")
    assert doc["task_id"] == "B-12-review" and doc["revisions"]["verified_code_sha"] == verified
    assert doc["revisions"]["head"] == trp._g(root, "rev-parse", "HEAD")
    assert doc["context_sha256"] == hashlib.sha256(context.encode("utf-8")).hexdigest()
    assert doc["provider"] == "fixture_test_adapter" and doc["real_provider"] is False
    assert doc["status"] == "ok" and doc["attempts"] == 1 and doc["elapsed_s"] is not None
    assert set(doc["usage"].values()) == {"UNKNOWN"}
    assert doc["structure_complete"] is True and "Fix B-12" in doc["claude_task"]
    assert "Role context pack" in context and doc["disclaimer"] == rv.DISCLAIMER


def test_the_recommendation_reads_facts_unknowns_decision_criteria_task_in_order(tmp_path):
    root, verified = _scene(tmp_path)
    _rec, out = _run(root, verified, tmp_path)
    md = (out / "recommendation.md").read_text(encoding="utf-8")
    pos = [md.index(f"## {s.title()}") for s in rv.SECTIONS]
    assert pos == sorted(pos) and "PROPOSAL ONLY" in md and "not an ARB acceptance" in md


def test_incomplete_context_is_named_not_hidden(tmp_path):
    root, verified = _scene(tmp_path, drop_next=True)
    rec, out = _run(root, verified, tmp_path)
    assert rec["context_complete"] is False
    assert any(u.startswith("topic open_problems_and_next_step") for u in rec["context_unknown"])
    assert "Context gaps (UNKNOWN)" in (out / "recommendation.md").read_text(encoding="utf-8")


def test_a_missing_section_marks_the_structure_incomplete(tmp_path):
    root, verified = _scene(tmp_path)
    rec, out = _run(root, verified, tmp_path, answer=GOOD.split("## CLAUDE TASK")[0])
    assert rec["structure_complete"] is False and "CLAUDE TASK" in rec["missing_sections"]
    assert "MISSING" in (out / "recommendation.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("provider,status", [(None, "refused"), ("some_local_model", "refused")])
def test_a_refusal_is_recorded_and_is_not_a_recommendation(tmp_path, provider, status):
    root, verified = _scene(tmp_path)
    rec, out = _run(root, verified, tmp_path, provider=provider)
    assert rec["status"] == status and rec["structure_complete"] is False and rec["claude_task"] is None
    assert "No recommendation" in (out / "recommendation.md").read_text(encoding="utf-8")


def test_a_failed_claude_call_is_not_a_recommendation(tmp_path):
    root, verified = _scene(tmp_path)

    def runner(cmd, timeout_s, log_path, out_path, cwd=None):
        # текст сбоя сам похож на ответ — секции из него извлекаться НЕ должны
        log_path.write_text("Claude AI usage limit reached\n## DECISION\nship it\n## FACTS\nall good",
                            encoding="utf-8")
        return 1
    rec, _out = _run(root, verified, tmp_path, provider="claude_subscription_cli",
                     adapters={"claude_cli": ad.claude_cli(binary="/nonexistent/claude", runner=runner)})
    assert rec["status"] == "quota" and all(v is None for v in rec["sections"].values())
    assert rec["structure_complete"] is False and rec["claude_task"] is None


def test_the_review_writes_only_its_output_directory(tmp_path):
    root, verified = _scene(tmp_path)
    before = _fingerprint(root / ".git"), trp._g(root, "status", "--porcelain"), \
        (root / "docs/ROADMAP.md").read_bytes()
    _run(root, verified, tmp_path)
    after = _fingerprint(root / ".git"), trp._g(root, "status", "--porcelain"), \
        (root / "docs/ROADMAP.md").read_bytes()
    assert before == after


def test_a_fragment_is_sanitized_fingerprinted_and_bounded(tmp_path):
    root, verified = _scene(tmp_path)
    frag = tmp_path / "snippet.py"
    frag.write_text(f"def f():\n    pass\ntoken = '{trp.SECRET}'\n", encoding="utf-8")
    rec, out = _run(root, verified, tmp_path, extra=[frag])
    assert trp.SECRET not in (out / "context.md").read_text() + (out / "review.json").read_text()
    assert rec["fragments"][0]["credential_lines_dropped"] == 1
    assert any("snippet.py" in u for u in rec["context_unknown"])
    big = tmp_path / "big.txt"
    big.write_text("x" * (rv.EXTRA_LIMIT_CHARS + 1), encoding="utf-8")
    with pytest.raises(rv.ReviewError):
        _run(root, verified, tmp_path, extra=[big])


@pytest.mark.parametrize("sha", ["3c40ed137", "f" * 40])
def test_the_verified_revision_must_be_an_exact_existing_commit(tmp_path, sha):
    root, _ = _scene(tmp_path)
    with pytest.raises(rv.ReviewError):
        _run(root, sha, tmp_path)


def test_the_cli_runs_the_review_and_keeps_the_context_mode(tmp_path):
    root, verified = _scene(tmp_path)
    fx = tmp_path / "fx.json"
    fx.write_text(json.dumps({"*": GOOD}), encoding="utf-8")
    base = ["arch-review", "--root", str(root), "--handover", "docs/evidence/HANDOVER.md", "--task-id", "t",
            "--task", "x", "--verified-sha", verified, "--out", str(tmp_path / "o")]
    assert memory_cli(base + ["--provider", "fixture_test_adapter", "--fixture", str(fx)]) == 0
    assert memory_cli(base) == 2                    # no provider ⇒ refused (no routing)
    assert memory_cli(base[:-2] + ["--verified-sha", "abc", "--out", str(tmp_path / "o2")]) == 2
    ctx = tmp_path / "pack.md"
    ctx.write_text("ctx", encoding="utf-8")
    assert cli(["--role", "architect", "--provider", "fixture_test_adapter", "--fixture", str(fx),
                "--context", str(ctx), "--task-id", "t", "--instruction", "i"]) == 0
    assert subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True,
                          text=True).stdout == ""
