"""Проба `named_cards_closed_at_origin` — зелёная на целом контуре, красная на КАЖДОМ звене.

Порядок — `.claude/rules/acceptance.md` п. 3 и ADR-333: проба меряет ИСХОД, у неё есть
контроль в обе стороны с НАЗВАННЫМ порванным звеном, и подстрокой она не проходит.

Предмет (ADR-544, цикл #757). Находка «N ответов владельца не доехали до канона»
закрывается вопросом к ИСТОЧНИКУ ПРАВДЫ — git, — по каждому названному имени, а не
перечитыванием прод-трекера, куда инжест не возвращается НИКОГДА (ADR-152). Живой замер
03.10 по `inbox-dvenadtsat-otvetov-vladeltsa-stoyat-v-ow`: все 12 названных карточек на
`origin/main` — `ingested`, то есть находка ложна.

Сцена одноразовая: настоящий маленький репозиторий, живой трекер не тронут.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.monitoring.card_acceptance import (  # noqa: E402
    NOT_SATISFIED, PROBES, SATISFIED, TRACKER_REL, UNMEASURED,
)

PROBE = PROBES["named_cards_closed_at_origin"]
REF = "main"


def _run(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


def _decision(status: str) -> str:
    return (f"---\ntrackerStatus:\n  type: owner-decision\ntitle: \"р\"\n"
            f"status: {status}\n---\n\nтело\n")


def _finding(names: list[str], quoted: bool = True) -> str:
    rows = "\n".join((f"| `{n}` | owner-done |" if quoted else f"| {n} | owner-done |")
                     for n in names)
    return ("---\ntrackerStatus:\n  type: inbox\ntitle: \"находка\"\nstatus: new\n"
            "---\n\n## Находка\n\n" + rows + "\n")


@pytest.fixture()
def scene(tmp_path):
    """Репозиторий, где origin — ветка `main`, а дерево может от неё отличаться."""
    root = tmp_path / "repo"
    tracker = root / TRACKER_REL
    tracker.mkdir(parents=True)
    # `-b` обязателен: без него имя ветки берёт хост (`.claude/rules/deployment.md`).
    _run(root.parent, "init", "-q", "-b", REF, str(root))
    _run(root, "config", "user.email", "t@example.com")
    _run(root, "config", "user.name", "test")
    return root, tracker


def _commit(root, msg="c"):
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", msg)


def _probe(tracker, card="inbox-f"):
    return PROBE(card, tracker_dir=str(tracker), ref=REF)


# =========================================================================================
# ЦЕЛЫЙ КОНТУР
# =========================================================================================

def test_whole_circuit_every_named_card_is_closed_at_origin(scene):
    root, tracker = scene
    (tracker / "owner-decision-a.md").write_text(_decision("ingested"), encoding="utf-8")
    (tracker / "owner-decision-b.md").write_text(_decision("done"), encoding="utf-8")
    (tracker / "inbox-f.md").write_text(
        _finding(["owner-decision-a", "owner-decision-b"]), encoding="utf-8")
    _commit(root)
    verdict, why = _probe(tracker)
    assert verdict == SATISFIED, why
    assert "2" in why


# =========================================================================================
# ПОРВАННЫЕ ЗВЕНЬЯ — каждое со своим именем
# =========================================================================================

def test_broken_link_one_named_card_is_still_open_at_origin(scene):
    root, tracker = scene
    (tracker / "owner-decision-a.md").write_text(_decision("ingested"), encoding="utf-8")
    (tracker / "owner-decision-b.md").write_text(_decision("owner-done"), encoding="utf-8")
    (tracker / "inbox-f.md").write_text(
        _finding(["owner-decision-a", "owner-decision-b"]), encoding="utf-8")
    _commit(root)
    verdict, why = _probe(tracker)
    assert verdict == NOT_SATISFIED
    assert "owner-decision-b" in why, "отказ обязан НАЗВАТЬ незакрытую карточку"
    assert "owner-decision-a" not in why


def test_broken_link_a_named_card_is_absent_from_origin(scene):
    """Карточки нет на origin вовсе — это НЕ «закрыта», это находка."""
    root, tracker = scene
    (tracker / "owner-decision-a.md").write_text(_decision("ingested"), encoding="utf-8")
    (tracker / "inbox-f.md").write_text(
        _finding(["owner-decision-a", "owner-decision-missing"]), encoding="utf-8")
    _commit(root)
    verdict, why = _probe(tracker)
    assert verdict == NOT_SATISFIED
    assert "owner-decision-missing" in why and "файла нет" in why


def test_broken_link_tree_closure_does_not_count_only_origin_does(scene):
    """Закрытие, поставленное ТОЛЬКО в дереве, пробу не зеленит — иначе проба мерила бы себя."""
    root, tracker = scene
    (tracker / "owner-decision-a.md").write_text(_decision("owner-done"), encoding="utf-8")
    (tracker / "inbox-f.md").write_text(_finding(["owner-decision-a"]), encoding="utf-8")
    _commit(root)
    (tracker / "owner-decision-a.md").write_text(_decision("ingested"), encoding="utf-8")  # только дерево
    verdict, why = _probe(tracker)
    assert verdict == NOT_SATISFIED, why


# =========================================================================================
# ТРЕТИЙ ИСХОД — и он не «чисто»
# =========================================================================================

def test_no_named_cards_is_unmeasured_never_satisfied(scene):
    """Пустое множество обошло бы пробу «вакуумно зелёной» — инв. #17."""
    root, tracker = scene
    (tracker / "inbox-f.md").write_text(_finding([]), encoding="utf-8")
    _commit(root)
    verdict, why = _probe(tracker)
    assert verdict == UNMEASURED
    assert "не названо ни одной" in why


def test_the_probe_does_not_match_by_substring(scene):
    """Имя, упомянутое БЕЗ обратных кавычек, именем не считается (ADR-333).

    Контроль в нужную сторону: проба обязана ответить «не измерено», а не собрать имена
    из вольного текста и зазеленеть на том, чего она не разбирала.
    """
    root, tracker = scene
    (tracker / "owner-decision-a.md").write_text(_decision("owner-done"), encoding="utf-8")
    (tracker / "inbox-f.md").write_text(
        _finding(["owner-decision-a"], quoted=False), encoding="utf-8")
    _commit(root)
    verdict, why = _probe(tracker)
    assert verdict == UNMEASURED, why
    assert "не названо ни одной" in why


def test_missing_finding_card_is_unmeasured(scene):
    root, tracker = scene
    (tracker / "inbox-other.md").write_text(_finding(["owner-decision-a"]), encoding="utf-8")
    _commit(root)
    verdict, why = _probe(tracker)
    assert verdict == UNMEASURED
    assert "нет в дереве" in why


def test_no_repository_is_unmeasured(tmp_path):
    tracker = tmp_path / TRACKER_REL
    tracker.mkdir(parents=True)
    (tracker / "inbox-f.md").write_text(_finding(["owner-decision-a"]), encoding="utf-8")
    verdict, why = PROBE("inbox-f", tracker_dir=str(tracker), ref=REF)
    assert verdict == UNMEASURED
    assert "нет репозитория" in why


def test_missing_argument_is_unmeasured():
    verdict, why = PROBE(None)
    assert verdict == UNMEASURED
    assert "named_cards_closed_at_origin" in why
