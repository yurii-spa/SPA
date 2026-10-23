# LLM_FORBIDDEN
"""Переносимый пакет роли (STUDIO-OS-MODELS-01, инкремент 1; ADR-OWN-2026-10-23) — контроли в обе стороны.

Сцена — одноразовое git-дерево с теми же файлами, что читает пакет: ARCHITECT_CONTEXT, ROADMAP,
state.json, хендовер задачи, ADR. Ревизия меряется git'ом: «после проверенного SHA — только docs»
и «после него менялся код» обязаны различаться. Секрет в хендовере в пакет не попадает. Отсутствующее
— UNKNOWN с причиной, а не пустота. Время — вход (`at`), сеть не нужна (сервера у сцены нет ⇒ UNKNOWN).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from spa_core.studio_os.memory import role_pack as rp

_REPO = Path(__file__).resolve().parents[2]
AT = "2026-10-23T21:00:00+00:00"  # FROZEN-DATE-OK: injected-clock — передаётся build(at=AT) явно
SECRET = "ghp_" + "A" * 36

CONTEXT = """# ARCHITECT_CONTEXT
## 3. Roles and authority
| Role | Responsibility | Authority limit | Source |
|---|---|---|---|
| **ChatGPT — Architecture Review Board (ARB)** | architecture, acceptance | never implements | ADR-610 |
| **Claude Code** | implementation worker | no owner subject | CLAUDE.md |
"""
ROADMAP = """# ROADMAP
> Latest owner directive: **2026-10-23** — model-independent workers, P1
> ([owner decision](decisions/ADR-OWN-2026-10-23-model-independent-studio.md)).
> Status words used below are kept apart.

## Order of the next epics

17. **STUDIO-OS-NEXT-01 · stabilisation** — candidate, NOT ARB-accepted (ADR-763).
18. **Later engines**
"""
STATE = {"header": {"generated_at": "2026-10-07T21:55:25Z", "repo_commit": "b" * 40,  # FROZEN-DATE-OK: injected-clock — отметка сцены, сравнивается как есть
                    "origin_commit": "c" * 40, "verdict_at_generation": "CONTEXT_FRESH",
                    "copy_role": "COMMITTED_SNAPSHOT", "latest_accepted_epic": "RM-TRUTH-01"}}


def _handover(verified: str, *, with_secret: bool = False, drop_next: bool = False) -> str:
    body = ["# Передача", "", "## 1. Цель и пункт ROADMAP", "", "Стабилизация, п. 17 (ADR-763).", "",
            "## 2. Ветка, SHA, чистота", "", f"| **проверенный код** | **`{verified}`** |", "",
            "## 3. Решения ARB", "", "Вариант А разрешён (ADR-OWN-2026-10-23-model-independent-studio).", "",
            "## 4. Полный CI", "", "RED, 3 failed.", ""]
    if not drop_next:
        body += ["## 5. Открытые блокеры и следующий пакет", "", "B-9; затем подключение §49.", ""]
    body += ["## 6. Разрешено / запрещено", "", "Без merge, без main.", ""]
    if with_secret:
        body.insert(5, f"token: {SECRET}")
    return "\n".join(body)


def _g(root: Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                          capture_output=True, text=True, check=True).stdout.strip()


def _scene(tmp: Path, **kw) -> tuple[Path, str]:
    root = tmp / "repo"
    files = {"docs/continuity/ARCHITECT_CONTEXT.md": CONTEXT, "docs/ROADMAP.md": ROADMAP,
             "docs/continuity/state.json": json.dumps(STATE),
             "docs/decisions/ADR-763-next.md": "# ADR-763 · next stage\n",
             "docs/decisions/ADR-OWN-2026-10-23-model-independent-studio.md": "# ADR-OWN · models\n",
             "spa_core/x.py": "x = 1\n"}
    for rel, body in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body, encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    _g(root, "add", "-A")
    _g(root, "commit", "-qm", "verified")
    verified = _g(root, "rev-parse", "HEAD")
    h = root / "docs/evidence/HANDOVER.md"
    h.parent.mkdir(parents=True)
    h.write_text(_handover(verified, **kw), encoding="utf-8")
    _g(root, "add", "-A")
    _g(root, "commit", "-qm", "docs only")
    return root, verified


def _build(root: Path, **kw):
    return rp.build(root, "docs/evidence/HANDOVER.md", 17, at=AT, **kw)


def test_the_pack_recovers_every_topic_from_existing_files(tmp_path):
    root, verified = _scene(tmp_path)
    p = _build(root)
    assert p["pack_version"] == rp.PACK_VERSION and p["generated_at"] == AT
    assert {k: v["heading"] for k, v in p["task"].items()} == {
        "goal": "1. Цель и пункт ROADMAP", "revision": "2. Ветка, SHA, чистота",
        "decisions": "3. Решения ARB", "verification": "4. Полный CI",
        "open_problems_and_next_step": "5. Открытые блокеры и следующий пакет",
        "constraints": "6. Разрешено / запрещено"}
    assert "STUDIO-OS-NEXT-01" in p["owner_intent"]["roadmap_text"]
    assert any("2026-10-23" in d for d in p["owner_intent"]["directives"])
    assert {a["id"]: a["path"] for a in p["decisions"]} == {
        "ADR-763": "docs/decisions/ADR-763-next.md",
        "ADR-OWN-2026-10-23-model-independent-studio":
            "docs/decisions/ADR-OWN-2026-10-23-model-independent-studio.md"}
    assert p["company_read_model"]["verdict_at_generation"] == "CONTEXT_FRESH"


def test_the_role_is_stable_and_the_participant_is_separate(tmp_path):
    root, _ = _scene(tmp_path)
    a = _build(root)["role"]
    w = _build(root, role="worker")["role"]
    assert a["role_id"] == "architect" and "Architecture Review Board" in a["authority_row"]
    assert a["current_participant"] == "ChatGPT" and "ChatGPT" not in a["role_id"]
    assert w["role_id"] == "worker" and "implementation worker" in w["authority_row"]
    with pytest.raises(rp.PackError):
        _build(root, role="router")


def test_docs_only_after_the_verified_sha_is_measured_as_verified_code(tmp_path):
    root, verified = _scene(tmp_path)
    r = _build(root)["revision"]
    assert r["verified_code_sha"] == verified and r["verified_is_ancestor_of_head"] is True
    assert r["changed_since_verified"] == ["docs/evidence/HANDOVER.md"]
    assert r["code_changed_since_verified"] == [] and r["head_code_is_verified"] is True


def test_a_code_change_after_the_verified_sha_is_named(tmp_path):
    root, _ = _scene(tmp_path)
    (root / "spa_core/x.py").write_text("x = 2\n", encoding="utf-8")
    _g(root, "commit", "-qam", "code")
    r = _build(root)["revision"]
    assert r["code_changed_since_verified"] == ["spa_core/x.py"] and r["head_code_is_verified"] is False


def test_a_dirty_tree_is_reported(tmp_path):
    root, _ = _scene(tmp_path)
    (root / "spa_core/new.py").write_text("y = 1\n", encoding="utf-8")
    assert _build(root)["revision"]["dirty"] == ["?? spa_core/new.py"]


def test_a_credential_line_never_reaches_the_pack(tmp_path):
    root, _ = _scene(tmp_path, with_secret=True)
    p = _build(root)
    assert p["credentials_dropped_lines"] == 1
    assert SECRET not in json.dumps(p, ensure_ascii=False) and SECRET not in rp.render(p)


def test_missing_inputs_are_unknown_with_a_reason_not_empty(tmp_path):
    root, _ = _scene(tmp_path, drop_next=True)
    (root / "docs/decisions/ADR-763-next.md").unlink()
    p = _build(root)
    assert p["task"]["open_problems_and_next_step"] == rp.UNKNOWN
    assert any(u.startswith("topic open_problems_and_next_step") for u in p["unknown"])
    assert any(u.startswith("ADR-763:") for u in p["unknown"])
    # Сервера у сцены нет — значение ветки у сервера не измерено, а не «совпало».
    assert p["revision"]["server_branch_head"] == rp.UNKNOWN
    assert p["revision"]["head_equals_server"] is None


def test_the_cli_refuses_without_a_tree_or_a_handover(tmp_path, capsys):
    assert rp.main(["--root", str(tmp_path), "--handover", "x.md"]) == 2
    root, _ = _scene(tmp_path)
    assert rp.main(["--root", str(root), "--handover", "nope.md"]) == 2
    assert "NOT BUILT" in capsys.readouterr().out


def test_the_cli_writes_pack_and_reports_unknown_by_exit_code(tmp_path):
    root, _ = _scene(tmp_path)
    out = tmp_path / "pack"
    code = rp.main(["--root", str(root), "--handover", "docs/evidence/HANDOVER.md",
                    "--roadmap-item", "17", "--at", AT, "--out", str(out)])
    assert code == 1  # сервер ветки не измерен ⇒ UNKNOWN ⇒ 1, не 0
    doc = json.loads((out / "pack.json").read_text(encoding="utf-8"))
    assert doc["pack_version"] == rp.PACK_VERSION and (out / "pack.md").read_text().startswith("# Role")


def test_the_pack_builds_on_the_real_repository_files():
    """Смоук на настоящих файлах: роль найдена в §3, ROADMAP-пункт 17 найден, хендовер разобран."""
    p = rp.build(_REPO, "docs/evidence/studio-os-next-01-2026-10-16/HANDOVER_2026-10-23_STAGE8.md", 17,
                 at=AT)
    assert "Architecture Review Board" in p["role"]["authority_row"]
    assert "STUDIO-OS-NEXT-01" in p["owner_intent"]["roadmap_text"]
    assert all(isinstance(v, dict) for v in p["task"].values()), p["unknown"]
