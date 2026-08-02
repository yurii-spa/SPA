#!/usr/bin/env python3
"""Гейт против КЛАССА «тест ловит стенные часы на импорте, а сверяет на ассерте».

Зачем этот файл существует
==========================
`SPA Tests` на `main` покраснел на самом свежем коммите (`d995a9573`, цикл #78),
run **30723870323**, job `test (3.11)`:

    FAILED spa_core/tests/test_protocol_scorecard.py::TestScoreAge::test_half_min_days_gives_approx_half
      - AssertionError: 0.505556 != 0.5 within 3 places

Причина не в продукт-коде. Тест-модуль считал константу **на импорте**::

    _HALF_MIN_DATE = (date.today() - timedelta(days=90)).isoformat()

а `score_age()` читает `date.today()` **в момент вызова**. Прогон пересёк полночь
UTC (сбор тестов 2026-08-01T23:43:50Z, этот ассерт 2026-08-02T00:06:15Z), функция
увидела на день больше ⇒ 91/180 = 0.505556.

Класс опасен ровно тем же, чем «молча выключенный тест»: он **не воспроизводится**
на машине разработчика (там импорт и ассерт всегда в одном дне), выглядит
«платформенной флаки» и провоцирует лечение симптома — ослабление ассерта
(`places=3` → `places=2`), что запрещено инвариантом #16. Настоящее лечение —
снять зависимость от стенных часов (см. `setUpModule` в `test_protocol_scorecard.py`).
Прогон `spa_core/tests/` длится ~16 минут ⇒ окно поломки ~1% суток: попасть в него
может ЛЮБОЙ ночной автономный цикл, и каждый раз это будет выглядеть загадкой.

Что проверяется (детерминированно, без сети, только чтение файлов репозитория)
=============================================================================
1. Ни один тест-файл не присваивает **во время импорта** значение, вычисленное из
   стенных часов (`date.today()`, `datetime.now()`, `datetime.utcnow()`,
   `time.time()` …), кроме файлов из явного реестра `_REVIEWED` — с записанным
   обоснованием, почему там это безопасно.
   «Время импорта» — это не только верхний уровень файла: тело класса и ветки
   `if`/`try` на верхнем уровне исполняются тем же импортом (сегодня таких
   захватов в репозитории ноль — проверено; граница проведена заранее, чтобы
   гейт не имел слепого пятна, о котором сам молчит).
2. Реестр не протухает: запись без соответствующего захвата в файле ⇒ КРАСНЫЙ
   (иначе реестр со временем превращается в список разрешений «на всякий случай»).
3. `test_protocol_scorecard.py` — точечный пин того, что уже починено.
4. **fail-CLOSED**: если сканер не нашёл ни одного тест-файла, или файл не
   разбирается — это КРАСНЫЙ, а не «нарушений не найдено». Гейт, который молча
   ничего не проверил, — ровно тот класс fail-OPEN, который циклы #29–#40/#75–#78
   ловили в сторожах.

Чего гейт НЕ запрещает: читать часы **внутри теста** (там окно — микросекунды, и
это нормальная практика), а также фикстуры с относительными окнами в часы —
такие файлы перечислены в `_REVIEWED` с замеренным запасом.
"""
from __future__ import annotations

import ast
import unittest
import warnings
from pathlib import Path
from typing import Iterator, NamedTuple

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SELF_NAME = Path(__file__).name

# Каталоги тестов, которые реально гоняет CI (см. ci.yml / test.yml).
_TEST_DIRS = (
    _REPO_ROOT / "spa_core" / "tests",
    _REPO_ROOT / "tests",
    _REPO_ROOT / "scripts" / "tests",
)

# Вызовы, возвращающие «сейчас» по стенным часам. Ключ — (владелец, атрибут):
# ловим и `date.today()`, и `datetime.date.today()` (владелец берётся последним
# сегментом цепочки), но НЕ ловим `SomeFake.today()` у собственных заглушек —
# у них другое имя владельца.
_CLOCK_CALLS: frozenset[tuple[str, str]] = frozenset(
    {
        ("date", "today"),
        ("datetime", "today"),
        ("datetime", "now"),
        ("datetime", "utcnow"),
        ("time", "time"),
        ("time", "time_ns"),
        ("time", "monotonic"),
    }
)

# Файлы, где захват часов на импорте разобран вручную и признан безопасным.
# Ключ — путь ОТ КОРНЯ репозитория, а не имя файла: одноимённые тесты в разных
# каталогах (`tests/` vs `spa_core/tests/`) в этом репозитории уже встречались,
# и разрешение по basename молча распространилось бы на однофамильца.
# Значение — обоснование (оно печатается в тексте падения, чтобы следующий цикл
# видел, ПОЧЕМУ так, а не «кто-то когда-то разрешил»). Разобрано в цикле #79.
_REVIEWED: dict[str, str] = {
    # Обе фикстуры — «дата заведомо в будущем» (+90 дней) для рынков Pendle.
    # Сдвиг на сутки оставляет её в будущем; точных сравнений с этой датой нет.
    # Литералом заменить нельзя: срок должен оставаться будущим относительно
    # РЕАЛЬНЫХ часов адаптера, иначе константа протухнет и станет бомбой.
    "spa_core/tests/test_pendle_pt_adapter.py": (
        "FUTURE_EXPIRY = today+90d — используется только как «ещё не истёк»; "
        "фиксированный литерал протух бы со временем"
    ),
    "spa_core/tests/test_pendle_pt_adapter_v2.py": (
        "побайтовый дубль test_pendle_pt_adapter.py (см. цикл #39)"
    ),
    # NOW — якорь для СТАРОГО таймстампа (NOW - 10 часов) против порога свежести
    # в часах. Прогон сюиты ~16 минут ⇒ запас на два порядка больше дрейфа.
    "spa_core/tests/test_monitor.py": (
        "NOW - 10ч против порога свежести в часах; запас ≫ длительности прогона"
    ),
    # _NOW — якорь окна китовых сделок (offset_secs по умолчанию 3600).
    "spa_core/tests/test_smart_money_flow_detector.py": (
        "_NOW - offset в секундах, окна порядка часа"
    ),
    # _NOW — «свежий» last_updated_iso; проверяется свежесть, а не точное равенство.
    "spa_core/tests/test_yield_aggregation_engine.py": (
        "_NOW как «свежая» метка, точных сравнений нет"
    ),
}


class _Capture(NamedTuple):
    file: str          # имя файла (без пути)
    rel: str           # путь относительно корня репозитория
    lineno: int
    target: str        # имя константы
    calls: str         # какие именно часы прочитаны


def _clock_calls_in(node: ast.AST) -> list[str]:
    """Все вызовы стенных часов внутри выражения (на любой глубине)."""
    found: list[str] = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if not isinstance(func, ast.Attribute):
            continue
        owner = func.value
        if isinstance(owner, ast.Attribute):
            owner_name = owner.attr          # datetime.date.today() → "date"
        elif isinstance(owner, ast.Name):
            owner_name = owner.id            # date.today() → "date"
        else:
            continue
        if (owner_name, func.attr) in _CLOCK_CALLS:
            found.append(f"{owner_name}.{func.attr}()")
    return sorted(set(found))


def _import_time_statements(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    """Инструкции, которые исполняются В МОМЕНТ ИМПОРТА модуля.

    Это НЕ только верхний уровень файла: тело класса, ветки `if`/`try`/`with`/циклы
    на верхнем уровне тоже исполняются при импорте, и константа, посчитанная там,
    ровно так же протухает к моменту ассерта. Спуск прекращается на границе
    функции — там чтение часов законно (окно микросекунды).
    """
    for stmt in body:
        yield stmt
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue  # тело функции исполнится позже — это не время импорта
        if isinstance(stmt, ast.ClassDef):
            yield from _import_time_statements(stmt.body)
        elif isinstance(stmt, (ast.If, ast.For, ast.While, ast.With, ast.AsyncWith)):
            yield from _import_time_statements(stmt.body)
            yield from _import_time_statements(getattr(stmt, "orelse", []))
        elif isinstance(stmt, ast.Try):
            yield from _import_time_statements(stmt.body)
            for handler in stmt.handlers:
                yield from _import_time_statements(handler.body)
            yield from _import_time_statements(stmt.orelse)
            yield from _import_time_statements(stmt.finalbody)


def _iter_test_files() -> Iterator[Path]:
    for directory in _TEST_DIRS:
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("test_*.py")):
            if path.name != _SELF_NAME:
                yield path


def _scan() -> tuple[list[_Capture], list[str], int]:
    """→ (захваты, файлы-которые-не-разобрались, сколько файлов просмотрено)."""
    captures: list[_Capture] = []
    unparsed: list[str] = []
    seen = 0

    for path in _iter_test_files():
        seen += 1
        rel = path.relative_to(_REPO_ROOT).as_posix()
        try:
            # Чужие SyntaxWarning (напр. «invalid escape sequence») — забота их
            # собственных тестов; здесь они только зашумили бы лог CI.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as exc:  # не разобрался — это находка, а не «чисто»
            unparsed.append(f"{rel}: {exc}")
            continue

        for stmt in _import_time_statements(tree.body):
            target_node: ast.AST | None
            value: ast.expr | None
            if isinstance(stmt, ast.Assign):
                target_node = stmt.targets[0] if stmt.targets else None
                value = stmt.value
            elif isinstance(stmt, ast.AnnAssign):
                target_node, value = stmt.target, stmt.value
            else:
                continue
            if value is None:
                continue
            calls = _clock_calls_in(value)
            if calls:
                captures.append(
                    _Capture(
                        file=path.name,
                        rel=rel,
                        lineno=stmt.lineno,
                        target=getattr(target_node, "id", "<expr>"),
                        calls=", ".join(calls),
                    )
                )

    return captures, unparsed, seen


class TestNoImportTimeClockInTests(unittest.TestCase):

    captures: list[_Capture]
    unparsed: list[str]
    seen: int

    @classmethod
    def setUpClass(cls) -> None:
        cls.captures, cls.unparsed, cls.seen = _scan()

    # ── fail-CLOSED ──────────────────────────────────────────────────────────

    def test_scanner_actually_scanned_something(self):
        """Сканер без единого просмотренного файла — КРАСНЫЙ, а не «чисто»."""
        self.assertGreater(
            self.seen, 0,
            "гейт не нашёл ни одного файла test_*.py — проверять было нечего, "
            f"искали в: {[str(d) for d in _TEST_DIRS]}",
        )

    def test_every_test_file_parses(self):
        """Неразобранный файл — находка: его содержимое НЕ проверено."""
        self.assertEqual(
            [], self.unparsed,
            "эти тест-файлы не разбираются, значит гейт их не проверял:\n  "
            + "\n  ".join(self.unparsed),
        )

    # ── собственно правило ───────────────────────────────────────────────────

    def test_no_unreviewed_import_time_clock(self):
        unreviewed = [c for c in self.captures if c.rel not in _REVIEWED]
        self.assertEqual(
            [], unreviewed,
            "стенные часы прочитаны на УРОВНЕ МОДУЛЯ (то есть на импорте) — "
            "прогон, пересёкший полночь, сравнит их с часами момента ассерта "
            "и покраснеет неповторимо (run 30723870323):\n  "
            + "\n  ".join(
                f"{c.rel}:{c.lineno}  {c.target} = … {c.calls}" for c in unreviewed
            )
            + "\n\nЧинить снятием зависимости от часов (фиксировать «сегодня», см. "
              "setUpModule в spa_core/tests/test_protocol_scorecard.py), а НЕ "
              "ослаблением ассерта (инвариант #16). Если захват действительно "
              "безопасен — внести файл в _REVIEWED с обоснованием.",
        )

    def test_registry_has_no_stale_entries(self):
        """Запись без захвата в файле — реестр протух, разрешение висит зря."""
        with_capture = {c.rel for c in self.captures}
        stale = sorted(set(_REVIEWED) - with_capture)
        self.assertEqual(
            [], stale,
            "в _REVIEWED есть файлы, где захвата часов на импорте больше НЕТ — "
            f"уберите записи, иначе реестр разрешает на будущее: {stale}",
        )

    def test_every_reviewed_entry_has_a_justification(self):
        empty = sorted(name for name, why in _REVIEWED.items() if not why.strip())
        self.assertEqual([], empty, f"обоснование обязательно: {empty}")

    # ── точечный пин уже починенного ─────────────────────────────────────────

    def test_protocol_scorecard_no_longer_captures_the_clock(self):
        """Регресс run 30723870323 — именно этот файл ронял CI на main."""
        offenders = [
            f"{c.rel}:{c.lineno} {c.target} = … {c.calls}"
            for c in self.captures
            if c.rel == "spa_core/tests/test_protocol_scorecard.py"
        ]
        self.assertEqual(
            [], offenders,
            "test_protocol_scorecard.py снова читает часы на импорте — "
            "падение 0.505556 != 0.5 вернётся при первом же ночном прогоне:\n  "
            + "\n  ".join(offenders),
        )


# ── положительные контроли разбора ───────────────────────────────────────────
# Без них «нарушений не найдено» может означать «сканер ничего не умеет».


class TestScannerActuallyDetects(unittest.TestCase):

    def _captures_of(self, source: str) -> list[str]:
        tree = ast.parse(source)
        out: list[str] = []
        for stmt in _import_time_statements(tree.body):
            value: ast.expr | None
            if isinstance(stmt, ast.Assign):
                value = stmt.value
            elif isinstance(stmt, ast.AnnAssign):
                value = stmt.value
            else:
                continue
            if value is not None:
                out.extend(_clock_calls_in(value))
        return sorted(set(out))

    def test_detects_plain_date_today(self):
        self.assertEqual(["date.today()"], self._captures_of("X = date.today()"))

    def test_detects_nested_in_expression(self):
        self.assertEqual(
            ["date.today()"],
            self._captures_of("X = (date.today() - timedelta(days=90)).isoformat()"),
        )

    def test_detects_dotted_owner(self):
        self.assertEqual(
            ["date.today()"], self._captures_of("X = datetime.date.today()")
        )

    def test_detects_annotated_assignment(self):
        self.assertEqual(["time.time()"], self._captures_of("X: float = time.time()"))

    def test_detects_datetime_now_and_utcnow(self):
        self.assertEqual(
            ["datetime.now()"], self._captures_of("X = datetime.now(timezone.utc)")
        )
        self.assertEqual(["datetime.utcnow()"], self._captures_of("X = datetime.utcnow()"))

    def test_ignores_clock_read_inside_a_function(self):
        """Чтение часов ВНУТРИ теста — законно, окно микросекунды."""
        self.assertEqual(
            [],
            self._captures_of("def test_x():\n    d = date.today()\n    assert d\n"),
        )

    def test_ignores_clock_read_inside_a_method(self):
        """Метод класса — тоже функция: исполнится при вызове, не при импорте."""
        self.assertEqual(
            [],
            self._captures_of(
                "class T:\n    def helper(self):\n        return date.today()\n"
            ),
        )

    def test_detects_clock_in_a_class_body(self):
        """Тело класса исполняется ИМПОРТОМ — тот же дефект, не сегодняшний, но тот же."""
        self.assertEqual(
            ["datetime.now()"],
            self._captures_of("class T:\n    NOW = datetime.now()\n"),
        )

    def test_detects_clock_in_a_top_level_try(self):
        """`try/except` на верхнем уровне — тоже время импорта."""
        self.assertEqual(
            ["time.time()"],
            self._captures_of("try:\n    X = time.time()\nexcept Exception:\n    X = 0\n"),
        )

    def test_detects_clock_in_a_top_level_if(self):
        self.assertEqual(
            ["date.today()"],
            self._captures_of("if True:\n    X = date.today()\n"),
        )

    def test_ignores_lookalike_owner(self):
        """Собственная заглушка `_PinnedDate.today()` — не стенные часы."""
        self.assertEqual([], self._captures_of("X = _PinnedDate.today()"))

    def test_ignores_assignment_without_clock(self):
        self.assertEqual([], self._captures_of("X = date(2026, 6, 15)"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
