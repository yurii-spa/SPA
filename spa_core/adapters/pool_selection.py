"""Отбор пула из фида: наблюдение либо ОТКАЗ С НАЗВАННОЙ ПРИЧИНОЙ. Никогда ноль.

Почему этот модуль существует
-----------------------------
Карточка `inbox-ozhivit-fidy-vne-ethereum-put-k-snyatiyu` (решение владельца
08.08) сообщала про `morpho_blue_base` и `silo_arbitrum` «аномальный APY 0.00 %».
Разбор показал, что 0.00 % — это НЕ выход адаптера, а строка его собственного
лога: `_find_best_usdc_pool` отвергал пул с нулевой доходностью и возвращал
голый ``None``. Снаружи этот ``None`` неотличим от «фид не ответил» — то есть
отказ БЫЛ, но НЕ БЫЛ ОБЪЯВЛЕН, и никто не шёл смотреть.

Второй дефект того же класса лежал рядом строкой ниже: ``float(best.get("apy",
0.0))``. Сегодня он недостижим (кандидат уже проверен санитарным диапазоном),
но это ловушка на будущее ровно того класса, который проект чинит: поле, которого
нет, превращается в **число 0.0**, а ноль — это утверждение о доходности, а не
признание отсутствия наблюдения.

Правила (`.claude/rules/adapters.md`, инвариант 2 CLAUDE.md): нет наблюдения ⇒
``None``, никаких fake-fallback, fail-CLOSED. Здесь к этому добавляется одно
требование: **отказ обязан назвать себя словами.**

Только stdlib. Read-only домен: ничего не пишет, ничего не импортирует из
``spa_core/execution/``.
"""
from __future__ import annotations

from typing import Optional

__all__ = ["pool_apy_pct", "SelectionTally"]


def pool_apy_pct(pool: dict) -> Optional[float]:
    """APY (%) записи фида, или ``None`` — если наблюдения нет.

    Отсутствующее, нечисловое, NaN-ное или булево поле ``apy`` — это ОТСУТСТВИЕ
    наблюдения, а не ноль. Подстановки по умолчанию здесь нет намеренно:
    ``pool.get("apy", 0.0)`` — это и есть тот дефект, ради которого написан модуль.

    ``0.0`` возвращается как ``0.0`` (это настоящее наблюдение «пул платит ноль»);
    решение «ноль ниже санитарной границы ⇒ кандидат отвергнут» принимает
    вызывающий и ОБЪЯВЛЯЕТ его через :class:`SelectionTally`.
    """
    if not isinstance(pool, dict):
        return None
    raw = pool.get("apy")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return value


class SelectionTally:
    """Счётчик причин, по которым кандидаты отсеяны, — чтобы отказ был назван.

    Адаптер зовёт ``reject_*`` на каждом отброшенном пуле и, если победитель не
    найден, отдаёт наружу :meth:`reason` — строку, из которой видно, ЧТО именно
    произошло: фид пуст, ни один пул не совпал по сети/проекту/символу, или
    совпавшие отвергнуты по нулевой доходности / тонкому TVL.

    Никаких чисел «на глаз»: строка собирается из фактически посчитанного.
    """

    __slots__ = ("scanned", "matched", "bad_apy", "anomalous_apy",
                 "thin_tvl", "no_tvl", "_worst_apy")

    def __init__(self) -> None:
        self.scanned = 0        # всего записей фида просмотрено
        self.matched = 0        # совпало по сети/проекту/символу
        self.bad_apy = 0        # поле apy отсутствует / нечисловое
        self.anomalous_apy = 0  # apy вне санитарного диапазона (сюда попадает 0.00 %)
        self.thin_tvl = 0       # tvlUsd ниже минимального
        self.no_tvl = 0         # поле tvlUsd отсутствует / нечисловое
        self._worst_apy: Optional[float] = None

    # ── учёт ──────────────────────────────────────────────────────────────
    def reject_anomalous_apy(self, apy: float) -> None:
        self.anomalous_apy += 1
        # Запоминаем ПЕРВОЕ аномальное значение — именно оно попадает в текст
        # причины («0.00 %» в карточке владельца было именно им).
        if self._worst_apy is None:
            self._worst_apy = float(apy)

    # ── вывод ─────────────────────────────────────────────────────────────
    def reason(self, what: str) -> str:
        """Человекочитаемая причина отказа. ``what`` — что искали."""
        if self.matched == 0:
            return (
                f"{what}: ни один из {self.scanned} пулов фида не совпал по "
                f"сети/проекту/символу — наблюдения нет (не ноль)"
            )
        parts: list[str] = []
        if self.anomalous_apy:
            shown = (
                f" (первое: {self._worst_apy:.2f}%)"
                if self._worst_apy is not None else ""
            )
            parts.append(
                f"{self.anomalous_apy} с APY вне санитарного диапазона{shown}"
            )
        if self.bad_apy:
            parts.append(f"{self.bad_apy} без числового поля apy")
        if self.thin_tvl:
            parts.append(f"{self.thin_tvl} ниже минимального TVL пула")
        if self.no_tvl:
            parts.append(f"{self.no_tvl} без числового поля tvlUsd")
        detail = "; ".join(parts) if parts else "причина не классифицирована"
        return (
            f"{what}: {self.matched} совпавших пул(ов) отвергнуты — {detail}. "
            f"Наблюдения нет ⇒ отказ (не ноль)"
        )
