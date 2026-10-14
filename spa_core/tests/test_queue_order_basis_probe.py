"""Проба `queue_reader_names_which_order_axis_spoke` — контроль В ОБЕ СТОРОНЫ (ADR-719).

Проба меряет ИСХОД У ЧИТАТЕЛЯ очереди (шаг 1 протокола): под ОДНИМ вердиктом порядка
`unmeasured` обязаны быть РАЗЛИЧИМЫ «обе оси решили и РАСХОДЯТСЯ» (тревога fail-CLOSED,
ADR-544) и «не решила ни одна» (штатная тишина). Правило `.claude/rules/acceptance.md`
п. 3: новая проба регистрируется только с тестом, где она зелена на целом контуре и
красна на КАЖДОМ порванном звене — с названным звеном, — и где она НЕ проходит
подстрокой (ADR-333).

ДИСКРИМИНАЦИЯ НА ДВУХ ДЕРЕВЬЯХ — отдельный тест ниже: на чистом `origin/main` проба
обязана дать `not_satisfied` (там базиса не производит никто), на правленом —
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

PROBE = "queue_reader_names_which_order_axis_spoke"

#: Файлы контура, которые проба читает: читатель очереди и прибор расхождения. Ломается
#: РОВНО ОДНО звено за тест, остальные едут дословно — иначе красный тест не говорит, от
#: чего он красный.
_CONTOUR = ("orchestrator_queue.py", "check_tracker_drift.py")


def _run(repo_root: str | Path) -> tuple[str, str]:
    return ca.PROBES[PROBE](None, repo_root=str(repo_root))


def _tree_with(tmp_path: Path, patches: dict[str, list[tuple[str, str]]]) -> Path:
    """Копия контура, где порвано РОВНО названное звено (якорь обязан быть единственным)."""
    root = tmp_path / "tree"
    (root / "scripts").mkdir(parents=True)
    for name in _CONTOUR:
        src = REPO_ROOT / "scripts" / name
        text = src.read_text(encoding="utf-8")
        for old, new in patches.get(name, []):
            assert text.count(old) == 1, (
                f"якорь мутации не единственен в {name}: {old!r} встречается "
                f"{text.count(old)} раз — красный тест не назвал бы звено")
            text = text.replace(old, new)
        (root / "scripts" / name).write_text(text, encoding="utf-8")
    return root


def _tree_renaming(tmp_path: Path, old: str, new: str) -> Path:
    """Копия контура, где ИМЯ переименовано СОГЛАСОВАННО во всех файлах контура.

    Нужна для звена «вокабуляра не производит никто»: порвать только определение
    значило бы получить `AttributeError` у читателя, то есть НЕ ИЗМЕРЕНО вместо
    «не выполнено» — а это разные исходы (инв. #17).
    """
    root = tmp_path / "tree"
    (root / "scripts").mkdir(parents=True)
    for name in _CONTOUR:
        text = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8")
        (root / "scripts" / name).write_text(text.replace(old, new), encoding="utf-8")
    return root


# ── звено 0: проба объявлена ───────────────────────────────────────────────────────

def test_link0_probe_is_registered() -> None:
    """Звено 0: проба есть в реестре — иначе объявить её у карточки нельзя."""
    assert PROBE in ca.PROBES


# ── звено 1: целый контур ──────────────────────────────────────────────────────────

def test_link1_probe_is_satisfied_on_the_whole_contour() -> None:
    """Звено 1: на своём дереве проба ЗЕЛЕНА, и причина называет оба базиса и дверь."""
    verdict, why = _run(REPO_ROOT)
    assert verdict == ca.SATISFIED, f"{verdict}: {why}"
    assert "базисы РАЗНЫЕ" in why, why
    assert "слово ЧИТАТЕЛЯ" in why, why
    assert "только там, где оно есть" in why, why


# ── звенья 2–3: третий исход отличим от «не выполнено» (инв. #17) ──────────────────

def test_link2_missing_reader_is_unmeasured_not_a_verdict(tmp_path: Path) -> None:
    """Звено 2: нет `scripts/orchestrator_queue.py` ⇒ `unmeasured` с причиной."""
    verdict, why = _run(tmp_path)
    assert verdict == ca.UNMEASURED, f"{verdict}: {why}"
    assert "orchestrator_queue.py" in why, why


def test_link3_unimportable_reader_is_unmeasured(tmp_path: Path) -> None:
    """Звено 3: читатель есть, но не ввозится ⇒ `unmeasured`, не `not_satisfied`.

    Прибор в сцене НАСТОЯЩИЙ намеренно: без него проба отказала бы раньше и по ДРУГОЙ
    причине («прибора нет»), то есть звено про читателя осталось бы неизмеренным — та
    же ловушка адреса двери, что нашлась в самой пробе.
    """
    root = _tree_with(tmp_path, {})
    (root / "scripts" / "orchestrator_queue.py").write_text(
        "this is not python(((\n", encoding="utf-8")
    verdict, why = _run(root)
    assert verdict == ca.UNMEASURED, f"{verdict}: {why}"
    assert "читатель очереди не ввезён" in why, why


def test_link3b_missing_instrument_is_unmeasured_and_says_so(tmp_path: Path) -> None:
    """Звено 3б: прибора нет вовсе ⇒ `unmeasured` со СВОЕЙ причиной, не про читателя.

    Два отсутствующих файла контура — две разные причины, и различать их обязана сама
    проба: «не измерено» без указания, ЧЕГО не хватило, неразбираемо (инв. #17).
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "orchestrator_queue.py").write_text(
        (REPO_ROOT / "scripts" / "orchestrator_queue.py").read_text(encoding="utf-8"),
        encoding="utf-8")
    verdict, why = _run(tmp_path)
    assert verdict == ca.UNMEASURED, f"{verdict}: {why}"
    assert "прибор расхождения НЕ ИЗМЕРИТЬ" in why, why


# ── звено 4: базиса НЕ ПРОИЗВОДИТ НИКТО — состояние ДО правки ─────────────────────

def test_link4_instrument_without_a_basis_vocabulary_is_not_satisfied(tmp_path: Path) -> None:
    """Звено 4: у прибора нет `BASIS_*` ⇒ проба НЕ выполнена, и это замер до ADR-719.

    Переименование согласованное: иначе читатель упал бы на `AttributeError`, и проба
    честно ответила бы «НЕ ИЗМЕРЕНО» — верный ответ на ДРУГОЙ вопрос.
    """
    root = _tree_renaming(tmp_path, "BASIS_", "KBASIS_")
    verdict, why = _run(root)
    assert verdict == ca.NOT_SATISFIED, f"{verdict}: {why}"
    assert "НЕТ вокабуляра базиса" in why, why


# ── звено 5: базис не доехал до читателя ──────────────────────────────────────────

def test_link5_reader_not_carrying_the_basis_is_not_satisfied(tmp_path: Path) -> None:
    """Звено 5: читатель, не перекладывающий базис в вердикт, пробу НЕ проходит."""
    root = _tree_with(tmp_path, {"orchestrator_queue.py": [(
        '            verdict["origin_order_basis"] = f.order_basis',
        '            pass  # мутант: базис до вердикта не доезжает')]})
    verdict, why = _run(root)
    assert verdict == ca.NOT_SATISFIED, f"{verdict}: {why}"
    assert "НЕТ поля `origin_order_basis`" in why, why


def test_link6_reader_dropping_the_per_axis_fields_is_not_satisfied(tmp_path: Path) -> None:
    """Звено 6: базис есть, а вердикта КАЖДОЙ оси нет ⇒ проба НЕ выполнена.

    Отдельно от звена 5 намеренно: базис отвечает «как добыт вердикт», пара осей — «что
    сказала каждая», и потерять можно именно второе.
    """
    root = _tree_with(tmp_path, {"orchestrator_queue.py": [(
        '            verdict["origin_order_mark"] = f.order_mark',
        '            pass  # мутант: вердикт самой оси не доезжает')]})
    verdict, why = _run(root)
    assert verdict == ca.NOT_SATISFIED, f"{verdict}: {why}"
    assert "origin_order_mark" in why, why


# ── звено 7: базис СХЛОПНУТ в одно значение — поле есть, ответа нет ───────────────

def test_link7_a_collapsed_basis_is_not_satisfied(tmp_path: Path) -> None:
    """Звено 7: один базис на расхождение осей и на их молчание пробу НЕ проходит.

    Ровно то, чем дефект мог бы «починиться» на вид: поле появилось, а два состояния
    по-прежнему под одним именем.
    """
    root = _tree_with(tmp_path, {"check_tracker_drift.py": [(
        "    if time_said and trail_said:\n"
        "        return BASIS_BOTH_AGREE if by_time == by_trail else BASIS_AXES_DISAGREE",
        "    if time_said and trail_said:\n"
        "        return BASIS_NEITHER_DECIDED  # мутант: тревога схлопнута в тишину")]})
    verdict, why = _run(root)
    assert verdict == ca.NOT_SATISFIED, f"{verdict}: {why}"
    assert "ОДИН И ТОТ ЖЕ" in why, why


# ── звенья 8–9: ДВЕРЬ ОТКАЗА — слово читателя, а не имя прибора ───────────────────

def test_link8_door_without_a_basis_is_not_satisfied(tmp_path: Path) -> None:
    """Звено 8: за дверью отказа базиса нет вовсе ⇒ проба НЕ выполнена (ADR-718)."""
    root = _tree_with(tmp_path, {"orchestrator_queue.py": [(
        '                   "origin_order_basis": BASIS_NOT_ASKED,\n',
        '')]})
    verdict, why = _run(root)
    assert verdict == ca.NOT_SATISFIED, f"{verdict}: {why}"
    assert "базиса нет вовсе" in why, why


def test_link9_door_borrowing_the_instruments_word_is_not_satisfied(tmp_path: Path) -> None:
    """Звено 9: подстановка базиса ПРИБОРА за дверью отказа пробу НЕ проходит.

    `neither_decided` занят состоянием «обе оси спросили и ни одна не решила». Напечатав
    его там, где не спрашивали ни одну, читатель снова печатает два разных состояния
    одинаково — дефект на уровень ниже, тот же приём, что снял ADR-718.
    """
    root = _tree_with(tmp_path, {"orchestrator_queue.py": [(
        'BASIS_NOT_ASKED = "not_asked"',
        'import check_tracker_drift as _d_for_mutant\n'
        'BASIS_NOT_ASKED = _d_for_mutant.BASIS_NEITHER_DECIDED')]})
    verdict, why = _run(root)
    assert verdict == ca.NOT_SATISFIED, f"{verdict}: {why}"
    assert "базис ПРИБОРА" in why, why


# ── звенья 10–11: два выхода читателя — в обе стороны ────────────────────────────

def test_link10_silent_stderr_is_not_satisfied(tmp_path: Path) -> None:
    """Звено 10: тревога есть в JSON, но не названа человеку ⇒ проба НЕ выполнена."""
    root = _tree_with(tmp_path, {"orchestrator_queue.py": [(
        '        clash = by_basis.get(drift.BASIS_AXES_DISAGREE)',
        '        clash = None  # мутант: человеку тревогу не говорят')]})
    verdict, why = _run(root)
    assert verdict == ca.NOT_SATISFIED, f"{verdict}: {why}"
    assert "человек у терминала его не видит" in why, why


def test_link11_always_shouting_stderr_is_not_satisfied(tmp_path: Path) -> None:
    """Звено 11: строка тревоги печатается ВСЕГДА ⇒ проба НЕ выполнена (урок #243).

    Обратная сторона звена 10. Сторож, кричащий на каждой находке, выключают — и тогда
    он молчит и в тот раз, когда тревога настоящая.
    """
    root = _tree_with(tmp_path, {"orchestrator_queue.py": [(
        '        clash = by_basis.get(drift.BASIS_AXES_DISAGREE)',
        '        clash = sorted(f.card_id for f in diverged)  # мутант: кричит всегда')]})
    verdict, why = _run(root)
    assert verdict == ca.NOT_SATISFIED, f"{verdict}: {why}"
    assert "печатается и там, где оси не расходятся" in why, why


# ── звено 12: ПОДСТРОКОЙ проба не проходит (ADR-333) ─────────────────────────────

def test_link12_a_basis_living_in_the_prose_is_not_satisfied(tmp_path: Path) -> None:
    """Звено 12: базис, читаемый как подстрока прозы, пробу НЕ проходит.

    Если бы носителем ответа осталась проза, «машинно читается» было бы неправдой, и
    проба обязана это назвать, а не зазеленеть на совпадении слов.
    """
    root = _tree_with(tmp_path, {"check_tracker_drift.py": [(
        '            f"по отметкам — {by_time}: {time_why}. по следу переходов — {by_trail}: {trail_why}")',
        '            f"по отметкам — {by_time}: {time_why}. по следу переходов — '
        '{by_trail}: {trail_why}. базис: {basis}")')]})
    verdict, why = _run(root)
    assert verdict == ca.NOT_SATISFIED, f"{verdict}: {why}"
    assert "подстрока прозы" in why, why


# ── звено 13: ДИСКРИМИНАЦИЯ на двух деревьях ИЗ ИСТОРИИ git ──────────────────────

#: Базовый коммит — `origin/main` на начало цикла #863, РОДИТЕЛЬ этой правки.
_BASE = "55eb3db5c3f3a8a02b69e5e68b4428c3ed5843c2"


def test_link13_probe_discriminates_between_two_real_trees(tmp_path: Path) -> None:
    """Звено 13: на базовом коммите проба `not_satisfied`, на правленом — `satisfied`.

    Пара деревьев берётся из ИСТОРИИ git, а не из фикстуры: «зелена на моей копии» и
    «зелена на дереве, где правки нет» — разные утверждения. Истории нет (CI клонирует
    на глубину 1) ⇒ ГРОМКИЙ отказ, а не скип: «не измерено», выданное за «прошло», и
    есть тот самый класс (урок #465).

    ОБА файла контура берутся с базы. Взять оттуда только читателя значило бы оставить
    прибор правленым — вокабуляр базиса нашёлся бы, и проба покраснела бы по ДРУГОЙ
    причине, то есть измерила бы не то, что заявлено.
    """
    before = tmp_path / "before"
    (before / "scripts").mkdir(parents=True)
    for name in _CONTOUR:
        rel = f"scripts/{name}"
        r = subprocess.run(["git", "-C", str(REPO_ROOT), "cat-file", "-e", f"{_BASE}:{rel}"],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            pytest.fail(
                f"ПРЕДПОСЫЛКА НЕ ОБЕСПЕЧЕНА: блоба {_BASE[:9]}:{rel} в этом репозитории "
                f"нет ({r.stderr.strip()}) — дискриминация пробы НЕ ИЗМЕРЕНА. "
                f"Это не «прошло»")
        old = subprocess.run(["git", "-C", str(REPO_ROOT), "show", f"{_BASE}:{rel}"],
                             capture_output=True, text=True, timeout=120)
        assert old.returncode == 0, old.stderr
        (before / "scripts" / name).write_text(old.stdout, encoding="utf-8")

    before_verdict, before_why = _run(before)
    after_verdict, after_why = _run(REPO_ROOT)
    assert before_verdict == ca.NOT_SATISFIED, (
        f"проба НЕ ДИСКРИМИНИРУЕТ: на коммите {_BASE[:9]} (до правки) она дала "
        f"{before_verdict}: {before_why}")
    assert after_verdict == ca.SATISFIED, f"{after_verdict}: {after_why}"


# ── звено 14: базис ВНЕ вокабуляра пробу не проходит ────────────────────────────

def test_link14_an_off_vocabulary_basis_is_not_satisfied(tmp_path: Path) -> None:
    """Звено 14: читатель, выдающий базис ВНЕ вокабуляра прибора, пробу НЕ проходит.

    Звено добавлено ПО НАХОДКЕ МУТАЦИИ: мутант, снимавший у пробы саму эту проверку
    (`if card["origin_order_basis"] not in bases:` → `if False:`), ВЫЖИЛ — ни один тест
    не подавал базис вне вокабуляра, и требование «значение объявлено» ничем не держалось.
    Необъявленное значение машинно читать нельзя: потребитель не знает его множества.
    """
    root = _tree_with(tmp_path, {"orchestrator_queue.py": [(
        '            verdict["origin_order_basis"] = f.order_basis',
        '            verdict["origin_order_basis"] = "выдуманное_слово"')]})
    verdict, why = _run(root)
    assert verdict == ca.NOT_SATISFIED, f"{verdict}: {why}"
    assert "не входит в вокабуляр" in why, why
