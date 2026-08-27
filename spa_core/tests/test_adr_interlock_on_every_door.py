"""Интерлок номеров ADR стоял на ОДНОЙ двери из двух — авария 2026-08-26 дословно.

Каждый тест здесь — положительный контроль настоящей аварии, а не украшение
(`.claude/rules/deployment.md`, «проверка сторожа сторожей»).

**Что было измерено (цикл #392, 2026-08-27).** `push_to_github.py::main()` держал интерлок
номеров ADR строками ВНУТРИ себя, а `push_to_github_batch.py::main()` — drop-in CLI на ту же
`batch_push`, под которым стоит `scripts/safe_site_push.py`, — этих строк не имел вовсе.
Сухой прогон, ОДИН и тот же набор из одного файла `docs/decisions/ADR-145-probe-collision.md`,
`origin/main` = `48c26e30f`:

| дверь | вердикт |
|---|---|
| `push_to_github.py --dry-run` | `ОТКАЗ (номера ADR, rc=1)`, код возврата **7** |
| `push_to_github_batch.py --dry-run` | `DRY OK: 1 файл(ов) попали бы в 1 коммит`, код **0** |

Через вторую дверь 26.08 и уехал ВТОРОЙ `ADR-145`: `ADR-145-pr-ci-liveness-guard` приземлился
в 20:35:47Z, `ADR-145-orchestrator-two-concurrent-cycles` — в 23:15:36Z, когда первый уже лежал
на `origin`. Интерлок обязан был отказать и отказал бы — его на этой двери не было. С этого
момента `main` был красным (`test_adr_number_allocator.py`, два падения), и никакой сторож не
назвал причину: `test_pusher_refuses_a_colliding_decision_end_to_end` проверяет ровно ту дверь,
которая и так была закрыта.

**Класс, а не случай.** `push_to_github_batch.py` в собственной шапке объясняет, что реализация
доставки у обоих CLI ОДНА, «поэтому x-бит, идемпотентность нельзя починить в одном пушере и
забыть в другом». Правило соблюдали для функций доставки и не соблюдали для ИНТЕРЛОКОВ: сверка
инструмента и owner-gate на обеих дверях были, интерлок номеров — только на одной. Поэтому ниже
не «тест на batch-CLI», а ПЕРЕПИСЬ дверей: любой модуль, способный доставить произвольный набор
файлов на ветку по умолчанию, обязан звать `enforce_adr_numbers` — либо быть исключённым
ИЗМЕРЕНИЕМ, и это измерение здесь же и утверждается.

Сети нет: интерлок стоит ДО чтения PAT и до первого запроса, поэтому отказ достижим сухим
прогоном (так же устроен соседний тест сверки инструмента доставки).
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: Имя, заведомо сталкивающееся по номеру: 067 занят на origin ДВУМЯ другими файлами
#: (живое решение + указатель), и таким он останется — это исторический след аварии
#: 2026-08-06/07, переписывать его назад нельзя. Файла с таким именем в дереве нет и не
#: нужно: сторож судит ИМЕНА набора, а не содержимое.
COLLIDING = "docs/decisions/ADR-067-a-parallel-session-decision.md"

#: Обе двери доставки. Третьей быть не должно — это стережёт перепись ниже.
DOORS = ("push_to_github.py", "push_to_github_batch.py")


def _run(script, *args):
    return subprocess.run(
        [sys.executable, str(ROOT / script), "--dry-run", "-m", "probe", *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300)


# ── АВАРИЯ 2026-08-26 ДОСЛОВНО ───────────────────────────────────────────────

def test_batch_door_refuses_a_colliding_decision_end_to_end():
    """Положительный контроль: до починки эта дверь печатала «DRY OK» и возвращала 0.

    Контроль ПРОВОДКИ, а не детали (урок #144): зовётся настоящий CLI целиком. На
    неисправленном `push_to_github_batch.py` тест краснеет — там интерлока нет ни строкой.
    """
    r = _run("push_to_github_batch.py", "--files", COLLIDING)
    out = r.stdout + r.stderr
    assert r.returncode == 7, (
        f"batch-дверь пропустила столкновение номеров: rc={r.returncode}\n{out}")
    # В чекауте без ref `origin/main` занятость честно НЕ измерена — это тоже отказ и тоже
    # правильный (fail-CLOSED). Принимаются обе причины, НЕ принимается тихий пропуск.
    assert ("уже занят" in out) or ("НЕ ИЗМЕРЕНО" in out), out


def test_both_doors_return_the_same_verdict_on_the_same_set():
    """Две двери — один вердикт. Иначе выбор двери становится выбором строгости.

    Сравниваются коды возврата, а не тексты: тексты у CLI разные по построению, а
    ВЕРДИКТ обязан совпадать, иначе сессия, которой отказали, просто зайдёт с другой
    стороны (так и вышло 26.08 — без злого умысла, batch — обычный способ послать
    набор одним коммитом).
    """
    codes = {door: _run(door, "--files", COLLIDING).returncode for door in DOORS}
    assert len(set(codes.values())) == 1, f"двери судят по-разному: {codes}"
    assert set(codes.values()) == {7}, codes


def test_batch_door_stays_silent_when_no_decision_is_delivered():
    """Обратная сторона: пуш без решений интерлок не трогает — иначе его снимут первым.

    Проверяется по ВЫВОДУ настоящего прогона, а не по коду возврата: без решений в
    наборе CLI идёт дальше, к сети, и код возврата про интерлок ничего не говорит.
    Сторож, краснеющий на посторонней работе, отключается раньше, чем ловит настоящее
    столкновение (`.claude/rules/deployment.md`).
    """
    r = _run("push_to_github_batch.py", "--files", "README.md")
    out = r.stdout + r.stderr
    assert "номера ADR" not in out, f"интерлок сработал на наборе без решений:\n{out}"


def test_batch_door_declares_the_conscious_bypass():
    """Осознанный обход есть и НАЗВАН — тем же флагом и той же переменной, что у корневой."""
    src = (ROOT / "push_to_github_batch.py").read_text(encoding="utf-8")
    assert "--allow-adr-collision" in src
    assert "SPA_PUSH_ALLOW_ADR_COLLISION" in src


def test_conscious_bypass_actually_passes_through_the_batch_door():
    """Обход не декоративен: с флагом та же доставка проходит интерлок.

    Без этого «обход объявлен» проверялось бы только по тексту исходника, а проводка
    флага к вызову осталась бы непроверенной — ровно та щель, из-за которой тесты на
    детали зеленеют при мёртвой проводке.
    """
    r = _run("push_to_github_batch.py", "--allow-adr-collision", "--files", COLLIDING)
    assert r.returncode != 7, (
        f"осознанный обход не работает на batch-двери: rc={r.returncode}\n"
        f"{r.stdout}\n{r.stderr}")


# ── ОДНА РЕАЛИЗАЦИЯ, А НЕ ДВЕ КОПИИ ──────────────────────────────────────────

def test_interlock_has_one_implementation_shared_by_both_doors():
    """Починка не должна стать второй копией блока: копия — это будущий разъезд.

    Именно копиями `repo_relative_path` цикл #40 разослал файлы в корень репо, и именно
    поэтому `push_to_github_batch.py` сегодня загружает канонический модуль по явному пути.
    """
    root_src = (ROOT / "push_to_github.py").read_text(encoding="utf-8")
    batch_src = (ROOT / "push_to_github_batch.py").read_text(encoding="utf-8")

    assert "def enforce_adr_numbers(" in root_src, (
        "реализация интерлока обязана жить в каноническом модуле")
    assert "def enforce_adr_numbers(" not in batch_src, (
        "в batch-CLI появилась ВТОРАЯ реализация интерлока — её и забудут починить")
    assert "_root_push.enforce_adr_numbers" in batch_src, (
        "batch-CLI не берёт интерлок из канонического модуля")

    for door, src in (("push_to_github.py", root_src),
                      ("push_to_github_batch.py", batch_src)):
        assert re.search(r"enforce_adr_numbers\(\s*all_files", src), (
            f"{door}: интерлок объявлен, но не вызван на наборе доставки — "
            f"проводка мертва, а тесты на детали останутся зелёными")


def test_root_door_no_longer_carries_the_inline_block():
    """Отрицательный контроль переноса: старый блок строками не остался рядом с функцией.

    Два кода одной проверки в одном `main()` — это два поведения, которые разойдутся;
    и именно по такой копии починку молча откатывают в одну строку.
    """
    root_src = (ROOT / "push_to_github.py").read_text(encoding="utf-8")
    assert '"scripts", "adr_number.py")' not in root_src.split("def main(")[-1], (
        "в main() снова собирается путь к сторожу вручную — интерлок обязан идти "
        "через enforce_adr_numbers()")


# ── ПЕРЕПИСЬ ДВЕРЕЙ: третья не должна появиться молча ────────────────────────

#: Модули, которые доставляют байты, но по ИЗМЕРЕНИЮ не могут увезти решение на ветку
#: по умолчанию. Значение — причина; сама причина проверяется тестом ниже, поэтому
#: список нельзя использовать как отговорку: сломается измерение — станет красным.
MEASURED_EXEMPT = {
    "spa_core/tools/github_pusher.py":
        "фиксированный манифест путей без единого docs/decisions — решение увезти нечем",
    "spa_core/devtools/auto_fixer.py":
        "ALLOWED_PREFIXES = spa_core/ + tests/, и доставка идёт через сам push_to_github.py",
    "scripts/checkpoint_deliver.py":
        "доставляет ТОЛЬКО в черновую ветку: main/master/trunk в PROTECTED_BRANCHES",
}


def _delivery_modules():
    """Файлы, вызывающие доставку (`batch_push(` / `push_file(`), кроме тестов."""
    out = []
    for p in sorted(ROOT.rglob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith((".git/", "spa_core/tests/", "tests/", "landing/")):
            continue
        if "/tests/" in rel or Path(rel).name.startswith("test_"):
            continue
        try:
            src = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "batch_push(" in src or "push_file(" in src:
            out.append((rel, src))
    return out


def test_every_delivery_door_carries_the_adr_interlock():
    """Третья дверь не появится молча: доставляешь — значит стоишь под интерлоком.

    Ровно этого измерения не было 26.08. Дверей было две, тест — один, и он проверял
    закрытую. Список исключений намеренно не «разрешение», а СЛЕПОК измерения: каждое
    исключение перепроверяется соседним тестом.
    """
    unguarded = []
    for rel, src in _delivery_modules():
        if "enforce_adr_numbers" in src or "_root_push.enforce_adr_numbers" in src:
            continue
        if rel in MEASURED_EXEMPT:
            continue
        unguarded.append(rel)
    assert not unguarded, (
        f"эти модули доставляют файлы, но не стоят под интерлоком номеров ADR: "
        f"{unguarded}. Либо позови enforce_adr_numbers(), либо докажи измерением, "
        f"что решение через них уехать не может, и внеси измерение в MEASURED_EXEMPT "
        f"вместе с проверкой в test_exemptions_are_measurements_not_permissions")


def test_exemptions_are_measurements_not_permissions():
    """Каждое исключение переписи — проверяемый факт. Сломается факт — станет красным.

    Без этого `MEASURED_EXEMPT` был бы обычным списком «этим можно», а такой список
    растёт ровно тогда, когда сторож мешает.
    """
    # 1. github_pusher: фиксированный манифест, ни одной строки docs/decisions.
    gp = (ROOT / "spa_core/tools/github_pusher.py").read_text(encoding="utf-8")
    assert "docs/decisions" not in gp, (
        "в манифест github_pusher.py попал путь решений — модуль стал дверью для ADR "
        "и обязан звать enforce_adr_numbers()")

    # 2. auto_fixer: разрешённые префиксы не включают docs/, а доставка — через сам пушер.
    af = (ROOT / "spa_core/devtools/auto_fixer.py").read_text(encoding="utf-8")
    m = re.search(r"ALLOWED_PREFIXES\s*=\s*\(([^)]*)\)", af, re.S)
    assert m, "ALLOWED_PREFIXES в auto_fixer.py не найден — измерение сломано"
    prefixes = re.findall(r'"([^"]+)"', m.group(1))
    assert prefixes == ["spa_core/", "tests/"], (
        f"auto_fixer расширил область правки до {prefixes} — проверь, не стало ли "
        f"docs/decisions/ достижимым")
    assert "str(PUSH_SCRIPT)" in af, (
        "auto_fixer больше не доставляет через push_to_github.py — своей доставке "
        "нужен свой интерлок")

    # 3. checkpoint_deliver: ветка по умолчанию для него запрещена.
    cd = (ROOT / "scripts/checkpoint_deliver.py").read_text(encoding="utf-8")
    m = re.search(r"PROTECTED_BRANCHES\s*=\s*frozenset\(\{([^}]*)\}\)", cd, re.S)
    assert m, "PROTECTED_BRANCHES в checkpoint_deliver.py не найден — измерение сломано"
    protected = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert {"main", "master"} <= protected, (
        f"checkpoint_deliver перестал защищать ветку по умолчанию ({protected}) — "
        f"он стал дверью на main и обязан звать enforce_adr_numbers()")


def test_the_census_actually_sees_the_known_doors():
    """Обратный контроль переписи: пустой или слепой сканер прошёл бы её насквозь.

    Перепись, ничего не находящая, зелёная всегда — это ровно тот «пустой glob», которым
    репозиторий уже платил (ADR-145, три случая одного класса за сутки).
    """
    found = {rel for rel, _ in _delivery_modules()}
    for door in DOORS:
        assert door in found, f"перепись не видит известную дверь {door}: сканер слеп"
    for exempt in MEASURED_EXEMPT:
        assert exempt in found, (
            f"{exempt} записан в исключения, но переписью НЕ найден — исключение "
            f"описывает то, чего нет, и молча стареет")
