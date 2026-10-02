"""A significant removal must carry a change record (ADR-537) — positive controls replay the real case.

# LLM_FORBIDDEN

Every scene is a throw-away git repository created with ``git init -b main`` (the branch name is an
input of the scene, `.claude/rules/deployment.md`); nothing touches the live tree.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import check_change_evidence as CE  # noqa: E402

CALC_OLD = '<div><span id="calc-real">1</span></div>\n<div><span id="calc-agg">2</span></div>\n' \
           '<a data-track="hero_snapshot">x</a>\n<script>function loadPackages(){}</script>\n'
CALC_NEW = '<div><span id="calc-real">1</span></div>\n<a data-track="hero_snapshot">x</a>\n<script></script>\n'

RECORD = """# ADR-999

```change-record
id: CR-999-1
task: epic-three-portfolios · role: site
component: home calculator
purpose: let a visitor size the realized rate and see a research scenario
purpose_source: docs/spec.md
defect: target typed into the script; scenario at result size
decision: scenario restored as a secondary labelled block
alternative: keep two equal columns
preserved: realized line and the scenario capability
changed: the scenario's size, label and source of its rate
removes: id:calc-agg, fn:landing/src/pages/index.astro:loadPackages
consumers: home page readers
owner_approval: not required (presentation; numbers unchanged)
reversible: yes (git revert)
rollback: revert the commit
```
"""


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True).stdout


@pytest.fixture()
def scene(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "landing/src/pages").mkdir(parents=True)
    (repo / "landing/src/pages/index.astro").write_text(CALC_OLD)
    (repo / "landing/src/pages/other.astro").write_text("<p>other</p>\n")
    (repo / "spa_core/defi_engine").mkdir(parents=True)
    (repo / "spa_core/defi_engine/status.py").write_text("def keep():\n    return 1\n\ndef helper():\n    return 2\n")
    (repo / "spa_core/misc").mkdir(parents=True)
    (repo / "spa_core/misc/util.py").write_text("def a():\n    return 1\n")
    (repo / "spa_core/api").mkdir(parents=True)
    (repo / "spa_core/api/r.py").write_text('@router.get("/api/v1/x")\ndef x():\n    return 1\n')
    (repo / "docs").mkdir()
    (repo / "docs/spec.md").write_text("# spec\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD").strip()
    return repo, base


def _run(repo, base, files, message=""):
    return CE.run([str(repo / f) for f in files], message, base=base)


def test_the_real_case_a_removed_calculator_branch_without_a_record_is_refused(scene):
    repo, base = scene
    (repo / "landing/src/pages/index.astro").write_text(CALC_NEW)
    rc, text = _run(repo, base, ["landing/src/pages/index.astro"], "site: simplify")
    assert rc == 1
    assert "id:calc-agg" in text and "fn:landing/src/pages/index.astro:loadPackages" in text


def test_a_complete_record_listing_every_removal_lets_it_through(scene):
    repo, base = scene
    (repo / "landing/src/pages/index.astro").write_text(CALC_NEW)
    (repo / "docs/ADR-999.md").write_text(RECORD)
    rc, text = _run(repo, base, ["landing/src/pages/index.astro", "docs/ADR-999.md"],
                    "site: x\n\nChange-Record: docs/ADR-999.md#CR-999-1\n")
    assert rc == 0, text


def test_a_record_that_omits_a_removal_or_a_field_is_refused(scene):
    repo, base = scene
    (repo / "landing/src/pages/index.astro").write_text(CALC_NEW)
    (repo / "docs/ADR-999.md").write_text(RECORD.replace(", fn:landing/src/pages/index.astro:loadPackages", "")
                                          .replace("rollback: revert the commit\n", ""))
    rc, text = _run(repo, base, ["landing/src/pages/index.astro", "docs/ADR-999.md"],
                    "Change-Record: docs/ADR-999.md#CR-999-1")
    assert rc == 1 and "loadPackages" in text and "rollback" in text


def test_a_purpose_source_that_resolves_to_nothing_is_refused_and_unknown_needs_reversibility(scene):
    repo, base = scene
    (repo / "landing/src/pages/index.astro").write_text(CALC_NEW)
    msg = "Change-Record: docs/ADR-999.md#CR-999-1"
    (repo / "docs/ADR-999.md").write_text(RECORD.replace("docs/spec.md", "docs/nowhere.md"))
    rc, text = _run(repo, base, ["landing/src/pages/index.astro", "docs/ADR-999.md"], msg)
    assert rc == 1 and "resolves to no file" in text
    (repo / "docs/ADR-999.md").write_text(RECORD.replace("purpose_source: docs/spec.md", "purpose_source: UNKNOWN")
                                          .replace("reversible: yes (git revert)", "reversible: no (cleanup)"))
    rc, text = _run(repo, base, ["landing/src/pages/index.astro", "docs/ADR-999.md"], msg)
    assert rc == 1 and "UNKNOWN is not OBSOLETE" in text
    (repo / "docs/ADR-999.md").write_text(RECORD.replace("purpose_source: docs/spec.md", "purpose_source: UNKNOWN"))
    rc, _ = _run(repo, base, ["landing/src/pages/index.astro", "docs/ADR-999.md"], msg)
    assert rc == 0


def test_a_commit_sha_is_a_valid_purpose_source(scene):
    repo, base = scene
    (repo / "landing/src/pages/index.astro").write_text(CALC_NEW)
    (repo / "docs/ADR-999.md").write_text(RECORD.replace("docs/spec.md", base[:9]))
    rc, text = _run(repo, base, ["landing/src/pages/index.astro", "docs/ADR-999.md"],
                    "Change-Record: docs/ADR-999.md#CR-999-1")
    assert rc == 0, text


def test_a_move_and_a_cosmetic_edit_need_no_record(scene):
    repo, base = scene
    (repo / "landing/src/pages/index.astro").write_text(CALC_OLD.replace("x</a>", "y</a>").replace(
        '<div><span id="calc-agg">2</span></div>\n', ""))
    (repo / "landing/src/pages/other.astro").write_text('<p>other</p>\n<span id="calc-agg">2</span>\n')
    rc, text = _run(repo, base, ["landing/src/pages/index.astro", "landing/src/pages/other.astro"], "copy")
    assert rc == 0, text


def test_python_removal_counts_only_in_scoped_modules_and_routes_are_tracked(scene):
    repo, base = scene
    (repo / "spa_core/defi_engine/status.py").write_text("def keep():\n    return 1\n")
    (repo / "spa_core/misc/util.py").write_text("x = 1\n")
    (repo / "spa_core/api/r.py").write_text("def x():\n    return 1\n")
    rc, text = _run(repo, base, ["spa_core/defi_engine/status.py", "spa_core/misc/util.py", "spa_core/api/r.py"])
    assert rc == 1
    assert "py:spa_core/defi_engine/status.py:helper" in text and "route:GET /api/v1/x" in text
    assert "spa_core/misc/util.py" not in text


def test_a_deleted_file_in_scope_is_a_removal(scene):
    repo, base = scene
    (repo / "landing/src/pages/other.astro").unlink()
    rc, text = _run(repo, base, ["landing/src/pages/other.astro"])
    assert rc == 1 and "file:landing/src/pages/other.astro" in text


def test_outside_a_git_tree_it_is_not_measured_never_clean(tmp_path):
    f = tmp_path / "x.astro"
    f.write_text("<p/>")
    rc, text = CE.run([str(f)], "")
    assert rc == 2 and "NOT MEASURED" in text


def test_an_unknown_base_is_not_measured(scene):
    repo, _ = scene
    rc, _text = _run(repo, "0" * 40, ["landing/src/pages/index.astro"])
    assert rc == 2


def test_the_pusher_refuses_through_the_same_guard(scene):
    repo, base = scene
    sys.path.insert(0, str(ROOT))
    import push_to_github as P
    (repo / "landing/src/pages/index.astro").write_text(CALC_NEW)
    # the CLI the pusher runs, with the scene's base
    rc = subprocess.run([sys.executable, str(ROOT / "scripts/check_change_evidence.py"), "--base", base,
                         "--files", str(repo / "landing/src/pages/index.astro"), "--message", "x"]).returncode
    assert rc == 1
    with pytest.raises(P.ChangeEvidenceMissing):
        # origin/main does not exist in the scene ⇒ NOT MEASURED ⇒ fail-CLOSED without the explicit flag
        P.enforce_change_evidence([str(repo / "landing/src/pages/index.astro")], "x", runner_file=str(ROOT / "push_to_github.py"))
    assert P.enforce_change_evidence([str(repo / "landing/src/pages/index.astro")], "x", allow_unmeasured=True,
                                     runner_file=str(ROOT / "push_to_github.py")) is True
