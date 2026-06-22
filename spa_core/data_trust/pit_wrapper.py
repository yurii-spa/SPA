"""
PIT (Point-In-Time) Wrapper — гарантирует no look-ahead в расчётах.
LLM_FORBIDDEN. fail-closed: PIT нарушение → raise/block.

Паттерн использования:
    with PITContext("2026-06-10") as pit:
        data = pit.filter(raw_data, date_field="date")
        # Все данные автоматически >= 2026-06-10 — исключены
"""
# LLM_FORBIDDEN
from datetime import datetime
from typing import List, Dict, Callable
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

PIT_VERSION = "pit_v1.0"

# Реестр нарушений PIT (для аудита)
_PIT_VIOLATIONS: List[Dict] = []


class PITViolationError(Exception):
    """Нарушение PIT — использование данных из будущего."""
    pass


class PITContext:
    """
    Контекстный менеджер для PIT-строгих расчётов.

    Обязательно:
    - Все данные после as_of_date отфильтровываются
    - Нарушения (попытки получить данные после as_of) → raise PITViolationError

    LLM_FORBIDDEN. fail-closed.
    """

    def __init__(
        self,
        as_of: str,             # "YYYY-MM-DD" или ISO datetime
        strict: bool = True,    # True → raise, False → warn
        context_name: str = "unnamed",
    ):
        # LLM_FORBIDDEN
        self.as_of_str = as_of
        self.strict = strict
        self.context_name = context_name
        self._violations: List[Dict] = []

        # Парсим as_of
        try:
            if "T" in as_of:
                self.as_of_dt = datetime.fromisoformat(as_of.rstrip("Z"))
            else:
                self.as_of_dt = datetime.fromisoformat(as_of + "T23:59:59")
        except ValueError as e:
            raise PITViolationError(f"Invalid as_of format: {as_of!r} — {e}")

    def __enter__(self) -> "PITContext":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._violations:
            violation_count = len(self._violations)
            _PIT_VIOLATIONS.extend(self._violations)
            if self.strict and exc_type is None:
                raise PITViolationError(
                    f"PITContext '{self.context_name}': {violation_count} violations detected. "
                    f"First: {self._violations[0]}"
                )
        return False

    def filter(
        self,
        records: List[Dict],
        date_field: str = "date",
        strict_missing: bool = True,
    ) -> List[Dict]:
        """
        Фильтрует список записей: оставляет только те, где date_field <= as_of.

        LLM_FORBIDDEN. fail-closed:
        - Записи без date_field → исключаются (если strict_missing=True)
        - Записи после as_of → исключаются + violation logged

        Args:
            records: список dict с датами
            date_field: поле с датой
            strict_missing: True → исключать записи без date_field

        Returns:
            Отфильтрованный список (только <= as_of)
        """
        # LLM_FORBIDDEN
        filtered = []
        excluded_count = 0
        future_count = 0

        for record in records:
            date_val = record.get(date_field)

            if date_val is None:
                if strict_missing:
                    excluded_count += 1
                    continue  # нет даты → исключаем (fail-closed)
                else:
                    filtered.append(record)
                    continue

            try:
                if "T" in str(date_val):
                    rec_dt = datetime.fromisoformat(str(date_val).rstrip("Z"))
                else:
                    rec_dt = datetime.fromisoformat(str(date_val) + "T23:59:59")
            except ValueError:
                excluded_count += 1
                continue  # неверный формат → исключаем

            if rec_dt > self.as_of_dt:
                # Future data — нарушение PIT
                future_count += 1
                violation = {
                    "as_of": self.as_of_str,
                    "record_date": str(date_val),
                    "context": self.context_name,
                }
                self._violations.append(violation)
                # НЕ включаем в результат
                continue

            filtered.append(record)

        return filtered

    def assert_no_future(self, date_str: str, label: str = "") -> None:
        """
        Проверяет что дата не в будущем относительно as_of.
        LLM_FORBIDDEN. fail-closed: нарушение → PITViolationError.
        """
        # LLM_FORBIDDEN
        try:
            if "T" in date_str:
                dt = datetime.fromisoformat(date_str.rstrip("Z"))
            else:
                dt = datetime.fromisoformat(date_str + "T23:59:59")
        except ValueError:
            raise PITViolationError(f"PIT: cannot parse date {date_str!r}")

        if dt > self.as_of_dt:
            violation = {
                "as_of": self.as_of_str,
                "attempted_date": date_str,
                "label": label,
                "context": self.context_name,
            }
            self._violations.append(violation)
            if self.strict:
                raise PITViolationError(
                    f"PIT VIOLATION: {label!r} date {date_str!r} > as_of {self.as_of_str!r}"
                )

    @property
    def violations(self) -> List[Dict]:
        return list(self._violations)


def pit_filter(
    records: List[Dict],
    as_of: str,
    date_field: str = "date",
    context_name: str = "unnamed",
) -> List[Dict]:
    """
    Функциональный интерфейс — PIT фильтрация без контекстного менеджера.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    with PITContext(as_of, strict=False, context_name=context_name) as pit:
        return pit.filter(records, date_field=date_field)


def wrap_time_series(
    fetch_func: Callable[[], List[Dict]],
    as_of: str,
    date_field: str = "date",
) -> Callable[[], List[Dict]]:
    """
    Декоратор-обёртка для функций, возвращающих time series.
    Автоматически применяет PIT фильтрацию к результату.

    LLM_FORBIDDEN.

    Usage:
        @wrap_time_series(as_of="2026-06-10", date_field="date")
        def load_history():
            return json.loads(path.read_text())["daily_history"]
    """
    # LLM_FORBIDDEN
    def wrapper() -> List[Dict]:
        raw = fetch_func()
        return pit_filter(raw, as_of=as_of, date_field=date_field)
    return wrapper


def get_pit_violations() -> List[Dict]:
    """Возвращает все зафиксированные PIT нарушения."""
    return list(_PIT_VIOLATIONS)


def clear_pit_violations() -> None:
    """Сбрасывает список нарушений (для тестов)."""
    _PIT_VIOLATIONS.clear()
