"""Проба `queue_reader_names_unmeasured_memory` — контроль В ОБЕ СТОРОНЫ (ADR-717).

Проба меряет ИСХОД У ЧИТАТЕЛЯ очереди (шаг 1 протокола): при ОТКАЗЕ сверки с `origin`
ось памяти копий обязана назвать третий исход СВОЕЙ причиной, а не молчать так же, как
молчит у карточки без второй копии. Правило `.claude/rules/acceptance.md` п. 3: новая
проба регистрируется только с тестом, где она зелена на целом контуре и красна на
КАЖДОМ порванном звене — с названным звеном, — и где она НЕ проходит подстрокой
(ADR-333).

ДИСКРИМИНАЦИЯ НА ДВУХ ДЕРЕВЬЯХ — отдельный тест ниже: на чистом `origin/main` проба
обязана дать `not_satisfied` (там читатель при отказе сверки молчит), на правленом —
`satisfied`. Источник пары деревьев НАЗВАН: история git, а не фикстура, — зелёный на
фикстуре не читается как зелёный на настоящем дереве.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from spa_core.monitoring import card_acceptance as ca   # noqa: E402

PROBE = "queue_reader_names_unmeasured_memory"


def _run(repo_root: str | Path) -> tuple[str, str]:
    return ca.PROBES[PROBE](None, repo_root=str(repo_root))


# ── звено 0: проба вообще объявлена ────────────────────────────────────────────────

def test_link0_probe_is_registered() -> None:
    """Звено 0: проба есть в реестре — иначе объявить её у карточки нельзя."""
    assert PROBE in ca.PROBES


# ── звено 1: целый контур ─────────────────────────────────────────────────────────

def test_link1_probe_is_satisfied_on_the_whole_contour() -> None:
    """Звено 1: на своём дереве проба ЗЕЛЕНА, и её причина называет оба исхода."""
    verdict, why = _run(REPO_ROOT)
    assert verdict == ca.SATISFIED, f"{verdict}: {why}"
    assert "НЕ ИЗМЕРЕНО" in why or "не измерено" in why, why
    assert "различимы" in why, why


# ── звено 2: читателя нет / не ввезён ⇒ ТРЕТИЙ ИСХОД, а не «не выполнено» ─────────

def test_link2_missing_reader_is_unmeasured_not_a_verdict(tmp_path: Path) -> None:
    """Звено 2: нет `scripts/orchestrator_queue.py` ⇒ `unmeasured` с причиной."""
    verdict, why = _run(tmp_path)
    assert verdict == ca.UNMEASURED, f"{verdict}: {why}"
    assert "orchestrator_queue.py" in why


def test_link3_unimportable_reader_is_unmeasured(tmp_path: Path) -> None:
    """Звено 3: читатель есть, но не ввозится ⇒ `unmeasured`, не `not_satisfied`."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "orchestrator_queue.py").write_text(
        "this is not python(((\n", encoding="utf-8")
    verdict, why = _run(tmp_path)
    assert verdict == ca.UNMEASURED, f"{verdict}: {why}"
    assert "не ввезён" in why


# ── звено 4: читатель МОЛЧИТ при отказе — ровно починенный дефект ─────────────────

def _tree_with_patched_reader(tmp_path: Path, replacements: list[tuple[str, str]]) -> Path:
    """Копия дерева, где у читателя порвано ОДНО названное звено."""
    root = tmp_path / "tree"
    (root / "scripts").mkdir(parents=True)
    text = (REPO_ROOT / "scripts" / "orchestrator_queue.py").read_text(encoding="utf-8")
    for old, new in replacements:
        assert text.count(old) == 1, f"якорь мутации не единственен: {old!r}"
        text = text.replace(old, new)
    (root / "scripts" / "orchestrator_queue.py").write_text(text, encoding="utf-8")
    for name in ("check_tracker_drift.py", "push_to_github.py"):
        src = REPO_ROOT / "scripts" / name
        if not src.exists():
            src = REPO_ROOT / name
        if src.exists():
            (root / "scripts" / name).write_text(src.read_text(encoding="utf-8"),
                                                 encoding="utf-8")
    return root


def test_link4_silent_reader_is_not_satisfied(tmp_path: Path) -> None:
    """Звено 4: читатель, не ставящий ось памяти при отказе сверки, пробу НЕ проходит."""
    root = _tree_with_patched_reader(tmp_path, [(
        '    return _memory_unmeasured_rows(cards, drift.MEMORY_UNMEASURED, detail)',
        '    return {c.id: {"origin_check": VERDICT_UNMEASURED} for c in cards}')])
    verdict, why = _run(root)
    assert verdict == ca.NOT_SATISFIED, f"{verdict}: {why}"
    assert "НЕТ оси памяти" in why, why


def test_link5_reason_without_its_own_subject_is_not_satisfied(tmp_path: Path) -> None:
    """Звено 5: причина, пересказывающая соседа, пробу НЕ проходит.

    Это и есть предмет заказа G716 п. 3: «не измерено» у оси обязано иметь СВОЮ
    причину, а не наследоваться от вердикта о составе списка.
    """
    whole = (
        '    detail = (f"ось памяти НЕ СПРОШЕНА У ПРИБОРА, хотя спрашивать было у кого: сверка с "\n'
        '              f"{ref} не состоялась ({reason}). Сколько ЗАПИСЕЙ ЦИКЛА не хватает этой "\n'
        '              f"копии — НЕ ИЗМЕРЕНО; дописывать запись в копию вслепую значит закрепить "\n'
        '              f"возможную потерю (ADR-714/716). Это не «записи совпали» и не «ось не "\n'
        '              f"спрашивают»")')
    root = _tree_with_patched_reader(tmp_path, [(whole, "    detail = reason")])
    verdict, why = _run(root)
    assert verdict == ca.NOT_SATISFIED, f"{verdict}: {why}"
    assert "СВОЕЙ причины" in why, why


def test_link6_verdict_in_json_but_not_in_stderr_is_not_satisfied(tmp_path: Path) -> None:
    """Звено 6: два выхода читателя разъехались ⇒ проба НЕ проходит."""
    root = _tree_with_patched_reader(tmp_path, [(
        '    print(f"❓ ось ПАМЯТИ копий (ЗАПИСИ ЦИКЛА) НЕ ИЗМЕРЕНА, и причина у неё СВОЯ: {detail}",\n'
        '          file=sys.stderr)',
        '    pass  # строку для человека убрали')])
    verdict, why = _run(root)
    assert verdict == ca.NOT_SATISFIED, f"{verdict}: {why}"
    assert "два выхода" in why, why


def test_link7_reader_stamping_unmeasured_on_everything_is_not_satisfied(
    tmp_path: Path,
) -> None:
    """Звено 7: КОНТРОЛЬ В ОБРАТНУЮ СТОРОНУ — «не измерено» на всём тоже не годится.

    Сторож, отвечающий третьим исходом и на СОСТОЯВШУЮСЯ сверку, снова делает отказ
    неотличимым от замера — только с другой стороны. Без этого звена пробу
    удовлетворил бы читатель, который просто перестал мерить.
    """
    root = _tree_with_patched_reader(tmp_path, [(
        '    note = _memory_note(f.memory, f.memory_detail, drift)',
        '    out["origin_memory"] = drift.MEMORY_UNMEASURED  # штамп на всё\n'
        '    note = _memory_note(f.memory, f.memory_detail, drift)')])
    verdict, why = _run(root)
    assert verdict == ca.NOT_SATISFIED, f"{verdict}: {why}"
    assert "на СОСТОЯВШЕЙСЯ сверке" in why, why


# ── звено 8: подстрокой проба НЕ проходит (ADR-333) ──────────────────────────────

def test_link8_probe_does_not_pass_on_a_phrase(tmp_path: Path) -> None:
    """Звено 8: напечатать нужные слова и не поставить поле — пробу не удовлетворяет."""
    root = _tree_with_patched_reader(tmp_path, [(
        '    return _memory_unmeasured_rows(cards, drift.MEMORY_UNMEASURED, detail)',
        '    print("ось ПАМЯТИ копий (ЗАПИСИ ЦИКЛА) НЕ ИЗМЕРЕНО", file=sys.stderr)\n'
        '    return {c.id: {"origin_check": VERDICT_UNMEASURED} for c in cards}')])
    verdict, why = _run(root)
    assert verdict == ca.NOT_SATISFIED, f"{verdict}: {why}"


# ── звено 9: ДИСКРИМИНАЦИЯ НА ДВУХ ДЕРЕВЬЯХ, источник пары — история git ─────────

def test_link9_probe_discriminates_between_two_real_trees(tmp_path: Path) -> None:
    """Звено 9: на базовом коммите проба `not_satisfied`, на правленом — `satisfied`.

    Пара деревьев берётся из ИСТОРИИ, а не из фикстуры: «зелена на моей копии» и
    «зелена на дереве, где правки нет» — разные утверждения. Истории нет (CI клонирует
    на глубину 1) ⇒ ГРОМКИЙ отказ, а не скип: «не измерено», выданное за «прошло», и
    есть тот самый класс (урок #465).
    """
    base = "c9a2ec02a0f7d622c60b550618564c3f4f174a83"      # ADR-716, цикл #860
    probe_rel = "scripts/orchestrator_queue.py"
    r = subprocess.run(["git", "-C", str(REPO_ROOT), "cat-file", "-e", f"{base}:{probe_rel}"],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        pytest.fail(
            f"ПРЕДПОСЫЛКА НЕ ОБЕСПЕЧЕНА: блоба {base}:{probe_rel} в этом репозитории нет "
            f"({r.stderr.strip()}) — дискриминация пробы НЕ ИЗМЕРЕНА. Это не «прошло»")
    old = subprocess.run(["git", "-C", str(REPO_ROOT), "show", f"{base}:{probe_rel}"],
                         capture_output=True, text=True, timeout=120)
    assert old.returncode == 0, old.stderr

    root = tmp_path / "before"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "orchestrator_queue.py").write_text(old.stdout, encoding="utf-8")
    for name in ("check_tracker_drift.py", "push_to_github.py"):
        src = REPO_ROOT / "scripts" / name
        if not src.exists():
            src = REPO_ROOT / name
        if src.exists():
            (root / "scripts" / name).write_text(src.read_text(encoding="utf-8"),
                                                 encoding="utf-8")
    before_verdict, before_why = _run(root)
    after_verdict, after_why = _run(REPO_ROOT)
    assert before_verdict == ca.NOT_SATISFIED, (
        f"проба НЕ ДИСКРИМИНИРУЕТ: на коммите {base[:9]} (до правки) она дала "
        f"{before_verdict}: {before_why}")
    assert after_verdict == ca.SATISFIED, f"{after_verdict}: {after_why}"
