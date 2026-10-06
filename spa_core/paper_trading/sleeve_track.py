"""spa_core/paper_trading/sleeve_track.py — the ONE read model of a sleeve book's
paper track (Balanced=hy, Aggressive=lp), extracted from
``scripts/generate_track_snapshot.py::_sleeve_paper_track`` (RM-TRUTH-01 W5, ADR-580
C1/C2).

Before this module the v2-only / current-experiment / maturity-gated view of a
sleeve's realized rate existed in exactly ONE place: a private, underscore-named
function inside a `scripts/` build-time tool. Two other owner-facing producers
(``spa_core/reporting/books_summary.py`` → Telegram "📚 Пакеты" + ``/admin/
portfolio-summary``, and ``spa_core/api/routers/live.py`` → ``/api/live/books``)
re-derived the SAME number with a DIFFERENT, simpler formula — linear, whole book
life, v1-rows included, no maturity gate — which is how Balanced/Aggressive ended
up publicly showing a NEGATIVE/near-zero rate below Conservative's (RM-TRUTH-01
``docs/rm_truth/A3_product.md`` §2, D1). This module is the fix for the ROOT CAUSE
(one formula, not three): it is imported by ``books_summary.py``, ``live.py`` AND
(as a thin wrapper, to keep its existing signature/tests unchanged) by
``scripts/generate_track_snapshot.py`` itself.

Decision mirrored (not re-decided) here: ADR-531 (sleeve-econ-v2 only, variant A —
old and new economics never blended into one continuous history) and ADR-533 (a
strategy-version change opens a new experiment; only the CURRENT experiment's rows
are published).

Pure stdlib, no file I/O (the caller loads the book's JSON and passes the dict in).
LLM forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import Any

from spa_core.reporting.compound_apy import compound_annualized_pct


def _post_fix_track(honest: list) -> dict:
    """Те же честные бары, но только посчитанные моделью v2 (ADR-531). <2 баров ⇒ apy None.

    АУДИТОРСКАЯ цифра, а не публикуемая (ни одна страница её не читает — замер RM-TRUTH-01
    W4): аудитору нужна сырая v2-ставка и до зрелости. Поэтому порог здесь не нулит число,
    а ТИПИЗИРУЕТ его (ADR-580 C2): ``reportable`` / ``reportable_after`` рядом, чтобы сырая
    ставка ниже порога никогда не читалась как зрелая."""
    from spa_core.paper_trading.sleeve_book import ECONOMICS_MODEL
    from spa_core.defi_engine.package_status import REPORTABLE_AFTER

    v2 = [h for h in honest if h.get("economics_model") == ECONOMICS_MODEL]
    apy = None
    if len(v2) >= 2:
        a, b = float(v2[0].get("equity") or 0), float(v2[-1].get("equity") or 0)
        apy = compound_annualized_pct(a, b, len(v2))
        apy = round(apy, 2) if apy is not None else None
    return {
        "model": ECONOMICS_MODEL, "days": len(v2),
        "first_date": v2[0].get("date") if v2 else None, "apy_pct": apy,
        "reportable": len(v2) >= REPORTABLE_AFTER, "reportable_after": REPORTABLE_AFTER,
        "pre_fix_days": len(honest) - len(v2),
    }


def sleeve_track_view(st: Any, book: str = "") -> dict:
    """Paper-трек рукава (Balanced=hy, Aggressive=lp) для карточки тира — ЧЕСТНЫЙ.

    Решение владельца 2026-10-01 (ADR-531, пункт 9 пакета P0-4, вариант A): публикуются
    ТОЛЬКО дни, посчитанные исправленной моделью издержек ``sleeve-econ-v2``. Строки
    модели v1 искажены выявленным дефектом учёта (газ за дрейф начисления), они НЕ
    удаляются и НЕ переписываются, в число НЕ входят и показываются отдельной пометкой
    без числа (``pre_fix_period``). Старое и новое в одну непрерывную историю не
    сводятся: дни, ставка и просадка — только по v2.

    Прежние правила остаются: «идёт paper-тест» — только при ``positions_count > 0``
    (решение владельца 19.08); ставка — по честным барам и только с порога зрелости
    ``REPORTABLE_AFTER`` (канон ``spa_core.defi_engine.package_status``, ADR-580 C2: до
    правки ставка публиковалась с ДВУХ баров, пока страница сама гасила её до 30 — два
    гейта на одно число), иначе ``None`` с явным ``reportable=False`` → «—». ``st`` не словарь / без ``daily_history`` → all-None (вызывающий честно
    молчит). ADR-103.

    *st* is the ALREADY-LOADED JSON document (``hy_paper_trading.json`` /
    ``lp_paper_trading.json`` shape) — this function does no file I/O.
    """
    from spa_core.paper_trading.sleeve_book import ECONOMICS_MODEL
    from spa_core.defi_engine.package_status import REPORTABLE_AFTER

    st = st if isinstance(st, dict) else {}
    hist = [h for h in (st.get("daily_history") or []) if isinstance(h, dict)]
    v2_all = [h for h in hist if h.get("economics_model") == ECONOMICS_MODEL]
    # ADR-533: a change of strategy version opens a new experiment; the published
    # figures are the CURRENT experiment's rows only — an earlier version's statistics
    # are never carried over.
    _active = next((e for e in reversed(st.get("experiments") or []) if e.get("status") == "active"), None)
    v2 = (
        [h for h in v2_all if h.get("experiment_id") == _active.get("experiment_id")]
        if _active else v2_all
    )
    earlier_version_rows = len(v2_all) - len(v2)
    funded = [h for h in v2 if float(h.get("equity", 0) or 0) > 0]
    honest = [h for h in funded if int(h.get("positions_count", 0) or 0) > 0]
    pre_fix_days = len(hist) - len(v2_all)  # rows of the distorted v1 cost model only

    reportable = len(honest) >= REPORTABLE_AFTER
    apy = None
    if reportable:
        first_eq = float(honest[0].get("equity") or 0)
        last_eq = float(honest[-1].get("equity") or 0)
        apy = compound_annualized_pct(first_eq, last_eq, len(honest))
        apy = round(apy, 2) if apy is not None else None

    # Просадка — от пика ТОЛЬКО v2-ряда: поле строки меряет от пика всей книги,
    # включая искажённый период, и смешало бы два режима в одном числе.
    dd = None
    if honest:
        peak, worst = 0.0, 0.0
        for h in honest:
            eq = float(h.get("equity") or 0)
            peak = max(peak, eq)
            if peak > 0:
                worst = min(worst, eq / peak - 1.0)
        dd = round(worst * 100.0, 2)

    last = funded[-1] if funded else {}
    if honest:
        status = "paper_test_running"
    elif funded:
        status = "accrual_only_no_positions"  # v2-начисление без позиций — не трек (19.08)
    elif pre_fix_days:
        status = "restarted_on_corrected_model"  # граница пройдена, исправленных дней ещё нет
    else:
        status = "not_started"
    boundary = st.get("economics_model_boundary")
    return {
        "status": status,  # факт, не аванс
        "days_with_positions": len(honest),
        "days_funded": len(funded),
        "apy_pct": apy,  # только v2, честные бары, НЕ НИЖЕ порога зрелости, иначе None
        "reportable": reportable,  # C2 (ADR-580): явная зрелость ставки, а не только None
        "reportable_after": REPORTABLE_AFTER,  # канон — spa_core.defi_engine.package_status
        "dd_pct": dd,
        # NAV книги несёт итог искажённого периода — при наличии v1-строк не
        # публикуется (вариант A: старое с новым не смешивается); без них — текущий
        # equity.
        "nav_usd": (None if pre_fix_days else (round(float(st.get("equity") or 0.0), 2) or None)),
        "positions_count": int(last.get("positions_count", 0) or 0) if last else None,
        "evidence": "paper",  # это paper-тест, не live (инв. #8)
        # Все v2-дни начислены по НАБЛЮДЁННЫМ ставкам: дата — первый день v2.
        "observed_accrual_since": (v2[0].get("date") if v2 else None),
        "economics_model": ECONOMICS_MODEL,
        "economics_model_boundary": boundary,
        "pre_fix_period": (
            {"days": pre_fix_days, "status": "distorted",
             "label_en": "earlier period distorted by the identified accounting defect "
                         "— retained for audit, not shown",
             "label_ru": "прежний период искажён выявленным дефектом учёта — "
                         "сохранён для аудита, не показывается"}
            if pre_fix_days else None
        ),
        "post_fix": dict(_post_fix_track(honest), pre_fix_days=pre_fix_days),
        # rows of an EARLIER strategy version under the corrected model — kept, not
        # counted, not "distorted"
        "earlier_version_rows": earlier_version_rows,
        "experiment_id": (_active or {}).get("experiment_id"),
    }
