"""
SPA — /protocols Telegram Command Reporter (MP-659 / v6.59)

Loads adapter_status.json + current_positions.json, formats a rich
per-protocol status message, and can send it via the Telegram Bot API.

Pure stdlib only. No external dependencies.
SECRETS POLICY: No tokens/keys ever written to this file or any artifact.
Credentials resolved at call time via: explicit arg → env var → macOS Keychain.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from spa_core.adapters.status_reader import observed_apy_pct_from_block
from spa_core.utils.errors import ConfigError

__all__ = [
    "format_protocols_message",
    "protocols_report_parts",
    "split_message",
    "send_protocols_report",
    "load_adapter_data",
    "unparsed_adapter_entries",
]

log = logging.getLogger("spa.telegram_protocols_reporter")

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_TELEGRAM_MAX_LEN = 4096

# ──────────────────────────── tier ordering ────────────────────────────────

_TIER_ORDER = ["T1", "T1-conditional", "T2-conditional", "T2", "T3-SPEC", "T3"]

_TIER_LABEL: dict[str, str] = {
    "T1": "T1 — Anchor Protocols",
    "T1-conditional": "T1 (Conditional)",
    "T2-conditional": "T2 (Conditional)",
    "T2": "T2 Protocols",
    "T3-SPEC": "T3-SPEC (Speculative / Advisory Only)",
    "T3": "T3 Protocols",
}

# Top-level keys in adapter_status.json that are NOT adapter entries
_SKIP_KEYS = frozenset(
    {
        "generated_at",
        "schema_version",
        "execution_mode",
        "live_apy_enabled",
        "mev_protection",
        "adapters",
        "morpho_steakhouse",
        "base_gas_monitor",
        "positions_data",  # injected by load_adapter_data()
    }
)


# ──────────────────────────── IO helpers ───────────────────────────────────


def _read_json(path: Path, default: Any = None) -> Any:
    """Read JSON gracefully — missing or corrupt file returns *default*."""
    try:
        p = Path(path)
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("Could not read %s: %s", path, exc)
        return default


# ──────────────────────────── pure helpers ─────────────────────────────────


def _get_best_apy(adapter: dict) -> Optional[float]:
    """
    Return the best APY (float) for an adapter, preferring USDC on any chain.
    Returns None when no numeric APY is found.
    """
    if not isinstance(adapter, dict):
        return None

    # Flat fields take priority (already resolved)
    for key in ("apy_pct", "apy"):
        v = adapter.get(key)
        if isinstance(v, (int, float)):
            return float(v)

    # mock_apy: {chain: {asset: float}}
    mock = adapter.get("mock_apy")
    if not isinstance(mock, dict):
        return None

    best: Optional[float] = None
    # Pass 1 — prefer USDC
    for chain_data in mock.values():
        if not isinstance(chain_data, dict):
            continue
        v = chain_data.get("USDC")
        if isinstance(v, (int, float)):
            candidate = float(v)
            if best is None or candidate > best:
                best = candidate
    if best is not None:
        return best

    # Pass 2 — any asset
    for chain_data in mock.values():
        if not isinstance(chain_data, dict):
            continue
        for v in chain_data.values():
            if isinstance(v, (int, float)):
                return float(v)

    return None


def _get_apy_str(adapter: dict) -> Optional[str]:
    """APY словами — и РОД числа рядом, когда это не наблюдение (ADR-709).

    Сестра :func:`_get_tvl_str` (ADR-708) на СОСЕДНЕЙ оси и у ТОГО ЖЕ читателя.
    ADR-708 назвал эту ось остатком вслух (заказ G708 п. 4): ``_get_best_apy``
    читает ``apy_pct`` / ``apy`` / ``mock_apy`` и рода не спрашивает НИ ОДНИМ
    полем, поэтому число печаталось одинаково, пришло ли оно из фида или из
    литерала ``fallback_apy`` в коде производителя.

    **Правило «что есть наблюдение» здесь НЕ ВЫВОДИТСЯ ЗАНОВО.** Оно живёт одной
    копией в :func:`spa_core.adapters.status_reader.observed_apy_pct_from_block`
    (контракт ADR-063): у современной записи ``adapters[<p>]`` наблюдение
    доказывает ТОЛЬКО поле ``live_apy``, а соседнее ``apy`` при ненаблюдении
    эхом повторяет ``fallback_apy`` и отличить замер от литерала не способно.
    Второй вывод того же рода и был бы ровно тем дефектом, которым ADR-063
    разошёлся по дереву.

    Три исхода РАЗЛИЧИМЫ (инв. #17), и различает их род, а не величина:

      * наблюдение (``live_apy``)            ⇒ «4.4%»
      * род объявлен и это НЕ наблюдение     ⇒ «8.0% (оценка)» — сюда же
        попадает число, которое производитель САМ объявил эхом литерала
        (напечатанное значение совпало с его ``fallback_apy``), и объявленный
        ADR-707 ``apy_source`` со значением вне наблюдённых;
      * рода нет вовсе                       ⇒ «3.1% (род не объявлен)» —
        ТРЕТИЙ исход, а не молчание: «род не объявлен» и «объявлен литералом»
        суть разные факты, и склеить их значило бы повторить дефект ADR-708.

    ЗАМЕР на живом ``data/adapter_status.json`` (2026-10-12), ради которого
    правка и сделана: из 34 современных записей с напечатанным числом **23**
    несут ``live_apy`` (наблюдение), а **11** его не несут И печатают ровно свой
    ``fallback_apy`` — то есть литерал. Владелец читал «APY: 14.0%» у
    ``pendle_yt_susde`` и «12.0%» у ``ethena_susde`` неотличимо от замера.

    ЦЕНА ОДНОСТОРОННОСТИ, названная замером, а не выведенная: у ЛЕГАСИ-записи
    верхнего уровня (теневой блок) поля ``live_apy`` нет по построению, и
    ``status_reader`` в своей легаси-ветке считает чтением её собственное
    ``apy``. Этот читатель секции не различает и потому назовёт такую запись
    «род не объявлен» даже тогда, когда число есть замер (``aave_arbitrum``
    3.1293 — ``read_live_apy_pct`` отдаёт его как наблюдение). Ошибка идёт в
    сторону ЗАНИЖЕНИЯ доверия и НИКОГДА в сторону выдуманного наблюдения;
    обратное направление было бы ровно закрываемым дефектом. Чинить это здесь
    значило бы завести ВТОРУЮ копию контракта ADR-063 у читателя, который кормит
    гейт, — остаток назван заказом, а не погашен молча.

    Число НЕ гасится: отчёт о протоколах — обзорная сводка, а не гейт, и
    спрятать число значило бы ответить владельцу молчанием. Гейт отказывает сам
    и отдельно (``status_reader.read_live_apy_pct`` ⇒ ``None``).
    """
    if not isinstance(adapter, dict):
        return None
    apy = _get_best_apy(adapter)
    if apy is None:
        return None
    shown = f"{apy:.1f}%"

    # Наблюдение — единственная копия правила, контракт ADR-063.
    if observed_apy_pct_from_block(adapter) is not None:
        return shown

    # Род объявлен полем ADR-707 и это не наблюдение.
    source = adapter.get("apy_source")
    if isinstance(source, str) and source.strip():
        return f"{shown} (оценка)"

    # Производитель САМ объявил, что печатает эхо литерала: напечатанное
    # значение совпало с его ``fallback_apy``. Это объявление рода, а не догадка.
    fallback = adapter.get("fallback_apy")
    if (
        isinstance(fallback, (int, float))
        and not isinstance(fallback, bool)
        and abs(float(fallback) - apy) < 1e-9
    ):
        return f"{shown} (оценка)"

    return f"{shown} (род не объявлен)"


def _adapter_section_records(
    data: dict,
) -> tuple[list[tuple[Optional[str], dict]], Optional[int]]:
    """Записи раздела ``adapters`` в ОДНОЙ форме — и цена молчания рядом (ADR-710).

    **Одна копия правила формы.** До сегодня форму раздела читали ДВА места и
    читали по-разному: :func:`_get_all_adapters` обходил его как СПИСОК, а
    :func:`unparsed_adapter_entries` — как СЛОВАРЬ. Живой артефакт несёт словарь,
    поэтому первый ронял все записи, а второй их исправно считал: сторож честно
    отвечал на свой вопрос («сколько уронено»), и ровно поэтому никто не отвечал
    на нужный («почему уронено ВСЁ»). Два читателя одного контракта расходятся —
    это класс, а не случай, и лечится он выносом правила в одну функцию, которую
    зовут оба.

    Принимаются ОБЕ формы, потому что обе встречаются в дереве: современный
    производитель (`adapter_orchestrator`) пишет словарь «ключ → запись», а
    тесты и часть legacy-читателей — список записей. Форма артефакта не есть
    вопрос отчёта: отчёт спрашивает «какие протоколы есть», а не «каким типом
    они упакованы».

    Возвращает пару ``(записи, уронено)``:

    * ``записи`` — список пар ``(ключ раздела или None, запись)``. Ключ нужен как
      ПОСЛЕДНЯЯ личность записи: замер 2026-10-13 на живом артефакте — ни у одной
      из 34 записей раздела нет ни ``protocol_key``, ни ``adapter_id``, ни
      ``name``, поэтому без ключа раздела дедупликация с теневым легаси-блоком
      верхнего уровня не срабатывает вовсе (``str(id(a))`` уникален у каждого
      объекта), и владелец читал бы `aave_arbitrum` ДВАЖДЫ — один раз замером,
      один раз его же устаревшей тенью.
    * ``уронено`` — ТРЕТИЙ исход у населения (инв. #17): число, когда раздел
      разобран (ноль есть ИЗМЕРЕННЫЙ ноль), и ``None``, когда раздела нет вовсе
      или он не той формы — тогда вопрос НЕ ИЗМЕРЕН, и выдать здесь ноль значило
      бы объявить спокойным день, которого никто не мерил.
    """
    if not isinstance(data, dict):
        return [], None
    section = data.get("adapters")
    if isinstance(section, dict):
        items: list[tuple[Optional[str], Any]] = list(section.items())
    elif isinstance(section, list):
        items = [(None, v) for v in section]
    else:
        # Раздела нет или он не той формы ВОВСЕ — это не «уронено ноль».
        return [], None
    records = [(k, v) for k, v in items if isinstance(v, dict)]
    return records, len(items) - len(records)


def unparsed_adapter_entries(data: dict) -> Optional[int]:
    """Сколько записей раздела ``adapters`` читатель НЕ РАЗОБРАЛ (ADR-709/710).

    Третий исход у ПОПУЛЯЦИИ отчёта, а не у числа (инв. #17): у «разобрано N»
    обязана быть отличимая изнутри пара «не разобрано M», иначе пустой отчёт
    неотличим от спокойного дня.

    ЗАМЕР 2026-10-12 (ADR-709), ради которого функция и появилась:
    :func:`_get_all_adapters` обходил ``data["adapters"]`` КАК СПИСОК, а живой
    ``adapter_status.json`` несёт этот раздел СЛОВАРЁМ. Обход словаря отдаёт
    КЛЮЧИ (строки), ``isinstance(a, dict)`` на строке ложен — и все **34**
    современные записи отбрасывались МОЛЧА. Владелец читал «Total adapters: 2» и
    видел ДВЕ легаси-записи верхнего уровня из 36.

    ЗАМЕР 2026-10-13 (ADR-710), после которого функция считает другое: читатель
    принимает обе формы, уронённых записей на живом артефакте **ноль**, и это
    ИЗМЕРЕННЫЙ ноль, а не отсутствие вопроса. Считается она теперь ТЕМ ЖЕ кодом,
    который записи и разбирает (:func:`_adapter_section_records`) — прежние два
    читателя формы разошлись именно потому, что считали порознь.

    Возвращает ``None``, когда вопрос НЕ ИЗМЕРЕН (раздела нет, он не той формы
    вовсе), и число — когда измерен.
    """
    return _adapter_section_records(data)[1]


def _compute_health(adapter: dict) -> tuple[str, str]:
    """Return (emoji, label) for protocol health derived from adapter fields."""
    if not isinstance(adapter, dict):
        return "✅", "SAFE"

    status = str(adapter.get("status", "active")).lower()
    risk_score = adapter.get("risk_score")
    write_state = str(adapter.get("write_state", "")).lower()

    if status == "suspended":
        return "🚨", "DANGER"
    if status == "research":
        return "🔬", "RESEARCH"
    if status == "monitoring":
        return "⚠️", "MONITOR"

    if isinstance(risk_score, (int, float)):
        if float(risk_score) >= 0.6:
            return "⚠️", "CAUTION"
        if float(risk_score) >= 0.4:
            return "⚠️", "CAUTION"

    _ = write_state  # write_state alone doesn't downgrade health in paper mode
    return "✅", "SAFE"


def _get_tvl_str(adapter: dict) -> Optional[str]:
    """TVL словами — и РОД числа рядом, когда это не наблюдение (ADR-708).

    Порог TVL есть ГЕЙТ: RiskPolicy допускает пул от $5 млн, и ADR-053 разрешает
    мерить его ТОЛЬКО живым TVL (``tvl_source == "live"``, который производитель
    ставит лишь на пул, прибитый UUID). Литерал не наблюдение, чем бы он ни был
    подписан.

    Эта строка идёт ВЛАДЕЛЬЦУ, и до ADR-708 она рода не читала вовсе: число
    печаталось одинаково, пришло ли оно из фида или из константы
    ``_TVL_ESTIMATES`` в коде производителя. При сбое фида владелец читал
    «TVL: $1.2B» у `aave_arbitrum` — оценку в коде, неотличимую от замера
    (`aave_arbitrum` и `pendle_pt` не попали в ``_SKIP_KEYS``, поэтому их
    теневые блоки отчёт видит как протоколы).

    Три исхода РАЗЛИЧИМЫ (инв. #17), и различает их род, а не величина:
      * ``tvl_source == "live"``    ⇒ «$21M»            — наблюдение;
      * род есть, но не ``live``    ⇒ «$1.2B (оценка)»  — постоянная, названная;
      * рода нет вовсе              ⇒ «$1.2B (род не объявлен)» — и это ТРЕТИЙ
        исход, а не молчание: «не объявлен» и «объявлен литералом» — разные
        факты, и склеивать их значило бы повторить ровно тот дефект, который
        ADR-708 и закрывает.

    Числа здесь НЕ гасятся: отчёт о протоколах — обзорная сводка, а не гейт, и
    спрятать число значило бы ответить на вопрос владельца молчанием. Гейт
    отказывает сам и отдельно (`status_reader.tvl_floor_verdict`).
    """
    if not isinstance(adapter, dict):
        return None
    tvl = adapter.get("tvl_usd")
    if not isinstance(tvl, (int, float)) or isinstance(tvl, bool):
        return None
    tvl_f = float(tvl)
    if tvl_f >= 1_000_000_000:
        shown = f"${tvl_f / 1_000_000_000:.1f}B"
    elif tvl_f >= 1_000_000:
        shown = f"${tvl_f / 1_000_000:.0f}M"
    elif tvl_f >= 1_000:
        shown = f"${tvl_f / 1_000:.0f}K"
    else:
        shown = f"${tvl_f:.0f}"

    source = adapter.get("tvl_source")
    if source == "live":
        return shown
    if isinstance(source, str) and source:
        return f"{shown} (оценка)"
    return f"{shown} (род не объявлен)"


def _format_adapter_line(adapter: dict) -> str:
    """Format one adapter as a single Markdown bullet line."""
    if not isinstance(adapter, dict):
        return "• (invalid adapter entry)"

    name = (
        adapter.get("name")
        or adapter.get("display_name")
        or adapter.get("protocol")
        or adapter.get("protocol_key")
        or adapter.get("adapter_id")
        or "Unknown"
    )

    apy_str = _get_apy_str(adapter) or "n/a"

    tvl_str = _get_tvl_str(adapter)
    health_emoji, health_label = _compute_health(adapter)

    parts: list[str] = [f"APY: {apy_str}"]

    if tvl_str:
        parts.append(f"TVL: {tvl_str}")

    risk_score = adapter.get("risk_score")
    if isinstance(risk_score, (int, float)):
        parts.append(f"Risk: {float(risk_score):.2f}")

    # Show write state only when it diverges from the paper-mode default
    write_state = adapter.get("write_state")
    if write_state and str(write_state).upper() not in ("BLOCKED", ""):
        parts.append(f"State: {write_state}")

    if adapter.get("quick_win"):
        bps = adapter.get("bps_gain", 0)
        parts.append(f"+{bps}bps")

    gsm = adapter.get("gsm_hours")
    if isinstance(gsm, (int, float)):
        parts.append(f"GSM: {int(gsm)}h/48h ⏳")

    health_str = f"{health_emoji} {health_label}"
    parts.append(health_str)

    return f"• *{name}* — " + " | ".join(parts)


def _group_by_tier(adapters: list[dict]) -> dict[str, list[dict]]:
    """Group adapter dicts by tier string."""
    groups: dict[str, list[dict]] = {}
    for adapter in adapters:
        if not isinstance(adapter, dict):
            continue
        tier = str(adapter.get("tier", "T2"))
        groups.setdefault(tier, []).append(adapter)
    return groups


def _dedup_identity(raw: object) -> str:
    """Личность записи для ДЕДУПЛИКАЦИИ — без разделителя и регистра (ADR-710).

    Теневой легаси-блок верхнего уровня и современная запись раздела — это ОДИН
    протокол, записанный дважды, и дедупликация обязана их свести. Замер
    2026-10-13 на живом артефакте: у `pendle_pt` ключ раздела несёт
    ПОДЧЁРКИВАНИЕ, а `protocol_key` его же тени — ДЕФИС (``pendle-pt``), поэтому
    посимвольное сравнение их не сводило, и владелец читал Pendle ДВАЖДЫ: один
    раз современной записью, второй — её устаревшей тенью со ставкой 8.0, про
    которую ADR-709 измерил, что это эхо ``fallback_apy``. Две строки про один
    протокол с двумя разными родами хуже одной.

    ЦЕНА ОДНОСТОРОННОСТИ, измеренная, а не выведенная: ошибка нечувствительной
    личности идёт в сторону СЛИЯНИЯ, то есть прячет строку, — поэтому вопрос
    «а нет ли двух РАЗНЫХ протоколов, различимых только разделителем?» обязан
    быть замером. Замер того же дня: во всём артефакте столкновений ровно ДВА
    (`aave_arbitrum`, `pendle_pt`), и оба — настоящие близнецы «тень ↔
    современная запись». Сторож этого замера — батарея
    `test_protocols_report_population.py`; появится третье столкновение не-близнецов,
    и его обязан назвать замер, а не это рассуждение.

    На ОТОБРАЖЕНИЕ не влияет: имя протокола владельцу печатает
    :func:`_format_adapter_line` из полей записи, и оно остаётся дословным.
    """
    return str(raw).strip().lower().replace("-", "_")


def _get_all_adapters(data: dict) -> list[dict]:
    """
    Extract all unique adapter dicts from the combined data blob.

    Primary source: data['adapters'] list (structured entries with mock_apy).
    Supplemental: top-level dict keys that look like flat adapter entries
    (must have 'tier' or 'apy'/'apy_pct' and not be a known metadata key).
    Deduplicates by protocol_key / adapter_id.
    """
    if not isinstance(data, dict):
        return []

    seen: set[str] = set()
    result: list[dict] = []

    # Primary: раздел `adapters` в ЛЮБОЙ из двух форм (словарь или список).
    # Форму читает ОДНА функция, та же, что считает уронённые записи — два
    # читателя одного контракта расходятся по построению (ADR-710).
    for section_key, a in _adapter_section_records(data)[0]:
        key = _dedup_identity(
            a.get("protocol_key")
            or a.get("adapter_id")
            or a.get("name")
            or section_key
            or id(a)
        )
        if key not in seen:
            seen.add(key)
            result.append(a)

    # Supplemental: flat top-level adapter blobs
    for k, v in data.items():
        if k in _SKIP_KEYS or not isinstance(v, dict):
            continue
        if "tier" not in v and "apy" not in v and "apy_pct" not in v:
            continue
        key = _dedup_identity(v.get("adapter_id") or v.get("protocol_key") or k)
        if key in seen:
            continue
        seen.add(key)
        result.append(v)

    return result


# ──────────────────────────── public: message formatting ───────────────────


def format_protocols_message(data: dict) -> str:
    """
    Format the /protocols status message from adapter data.

    Parameters
    ----------
    data : dict — typically loaded from data/adapter_status.json with
           positions data merged under key ``'positions_data'``.

    Returns
    -------
    str — Telegram Markdown-compatible message.  May exceed 4096 chars;
          call :func:`split_message` before sending.
    """
    if not isinstance(data, dict):
        data = {}

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    adapters = _get_all_adapters(data)
    total_adapters = len(adapters)
    grouped = _group_by_tier(adapters)

    lines: list[str] = [
        f"📊 *SPA Protocol Status* — {now_str}",
        "",
    ]

    # Tiers in canonical order
    rendered_tiers: set[str] = set()
    for tier in _TIER_ORDER:
        tier_adapters = grouped.get(tier)
        if not tier_adapters:
            continue
        rendered_tiers.add(tier)
        label = _TIER_LABEL.get(tier, tier)
        lines.append(f"*{label}*")
        for adapter in tier_adapters:
            lines.append(_format_adapter_line(adapter))
        lines.append("")

    # Any leftover tiers not in the canonical list
    for tier, tier_adapters in grouped.items():
        if tier in rendered_tiers:
            continue
        lines.append(f"*{tier}*")
        for adapter in tier_adapters:
            lines.append(_format_adapter_line(adapter))
        lines.append("")

    # ── System summary ──────────────────────────────────────────────────
    positions_data = data.get("positions_data") or {}
    if not isinstance(positions_data, dict):
        positions_data = {}

    capital = (
        positions_data.get("capital_usd")
        or data.get("capital_usd")
        or 100_000
    )
    deployed = positions_data.get("deployed_usd")
    cash = positions_data.get("cash_usd")
    positions = positions_data.get("positions") or {}
    active_count = sum(
        1
        for v in positions.values()
        if isinstance(v, (int, float)) and v > 0
    )

    mev = data.get("mev_protection") or {}
    coverage = mev.get("coverage") if isinstance(mev, dict) else None
    cov_pct = (
        coverage.get("coverage_pct")
        if isinstance(coverage, dict)
        else None
    )

    sys_parts: list[str] = [f"Capital: ${float(capital):,.0f}"]
    if isinstance(deployed, (int, float)):
        sys_parts.append(f"Deployed: ${float(deployed):,.0f}")
    if isinstance(cash, (int, float)):
        sys_parts.append(f"Cash: ${float(cash):,.0f}")
    sys_parts.append(f"Total adapters: {total_adapters}")
    # Третий исход у ПОПУЛЯЦИИ: «не разобрано» обязано быть отличимо от
    # спокойного дня (инв. #17, ADR-709). Причина НЕ называется литералом:
    # прежняя строка печатала «раздел пришёл словарём», и с ADR-710 это стало
    # неправдой — читатель принимает обе формы, а уронить запись теперь может
    # только то, что она не запись. Пережившая правку прозаическая причина врёт
    # владельцу тише, чем молчание.
    unparsed = unparsed_adapter_entries(data)
    if isinstance(unparsed, int) and unparsed > 0:
        sys_parts.append(
            f"НЕ РАЗОБРАНО записей раздела `adapters`: {unparsed} "
            f"(член раздела не является записью)"
        )
    if active_count:
        sys_parts.append(f"Active positions: {active_count}")
    if isinstance(cov_pct, (int, float)):
        sys_parts.append(f"MEV coverage: {float(cov_pct):.0f}%")

    lines.append("*System*")
    lines.append(" | ".join(sys_parts))

    return "\n".join(lines)


# ──────────────────────────── public: message splitting ────────────────────


def split_message(text: str, max_len: int = _TELEGRAM_MAX_LEN,
                  *, measure=len) -> list[str]:
    """
    Split a Telegram message into parts each ≤ *max_len* units of *measure*.

    Splits on newlines to avoid breaking mid-line.  A single line that
    itself exceeds *max_len* is hard-split at the character boundary.

    Parameters
    ----------
    text    : the full message string.
    max_len : maximum units per chunk (default: 4096).
    measure : чем мерить длину. По умолчанию — КОДОВЫЕ ТОЧКИ (``len``), и для
        прежних звателей ничего не меняется.

        **Зачем ручка вообще.** Telegram считает длину в единицах UTF-16, а Python —
        в кодовых точках, и у отчёта о протоколах в каждой строке эмодзи: «📊» стоит
        ДВЕ единицы при одной кодовой точке. Поэтому кусок, влезающий в 4096 по
        ``len``, может перешагнуть 4096 у Bot API — и тогда ступень, которая режет
        текст перед отправкой (``bot._fit_telegram``), усекает его С ХВОСТА, то есть
        убивает блок ``*System*`` первым. Дверь обязана делить ТОЙ ЖЕ мерой, которой
        судит режущая ступень; две меры одного контракта расходятся молча. Дефект
        найден пробой ``owner_protocols_report_reaches_the_owner`` на раздутом входе
        в том же цикле, что и сама дверь (ADR-711): на живом населении он латентен,
        потому что сегодняшний отчёт в одно сообщение влезает.

    Returns
    -------
    list[str] — one or more chunks, each ≤ max_len units of *measure*.
    """
    if not text:
        return [text]
    if measure(text) <= max_len:
        return [text]

    chunks: list[str] = []
    current_lines: list[str] = []
    current_len = 0

    for line in text.split("\n"):
        line_cost = measure(line) + 1  # +1 for the joining newline

        if line_cost > max_len:
            # Flush current buffer first
            if current_lines:
                chunks.append("\n".join(current_lines))
                current_lines = []
                current_len = 0
            # Hard-split the overlong line
            for i in range(0, len(line), max_len):
                chunks.append(line[i : i + max_len])
            continue

        if current_len + line_cost > max_len and current_lines:
            chunks.append("\n".join(current_lines))
            current_lines = []
            current_len = 0

        current_lines.append(line)
        current_len += line_cost

    if current_lines:
        chunks.append("\n".join(current_lines))

    return chunks or [text[:max_len]]


def protocols_report_parts(data: dict, *, max_len: int = _TELEGRAM_MAX_LEN,
                           measure=len, render=None) -> list[str]:
    """Куски, которыми отчёт доезжает до владельца — ОДНО правило деления (ADR-711).

    Правило «как этот отчёт переходит предел одного сообщения Telegram» обязано
    жить в одном месте. До сегодня его знал только :func:`send_protocols_report`
    (отставленный пуш), а у новой двери бота оно было бы ВТОРОЙ копией — ровно тот
    класс, который ADR-710 вылечил у формы раздела ``adapters``: два читателя
    одного контракта расходятся по построению, и расходятся МОЛЧА.

    Блок ``*System*`` стоит в сообщении ПОСЛЕДНИМ, а в нём ``Capital``/``Deployed``/
    ``Cash``/``Total adapters`` и строка «НЕ РАЗОБРАНО», которой ADR-709 сделал
    молчание отличимым (инв. #17). Поэтому любое усечение С ХВОСТА убивает сводку
    ПЕРВОЙ, и деление — не косметика: это единственная форма доставки, при которой
    третий исход доживает до владельца при ЛЮБОМ населении отчёта.

    Предел и МЕРА длины — вход, а не константа этого модуля: делить обязано тем же,
    чем судит режущая ступень двери (см. ``split_message``, параметр ``measure``).

    ``render`` — перевод разметки, если дверь говорит не на Markdown производителя.
    Он применяется ДО деления, и это не порядок ради порядка: экранирование ТОЛЬКО
    удлиняет текст (``&`` → ``&amp;``, плюс теги ``<b>``), поэтому кусок, нарезанный
    до перевода, может перешагнуть предел ПОСЛЕ него — и режущая ступень снимет
    хвост, то есть сводку. Дефект найден пробой на раздутом входе уже ПОСЛЕ того,
    как мера длины была сведена к одной (ADR-711): первая правка вылечила одну из
    двух причин одного усечения, и вторая нашлась только потому, что проба мерит
    ИСХОД у двери, а не согласие двух констант.
    """
    message = format_protocols_message(data)
    if render is not None:
        message = render(message)
    return split_message(message, max_len, measure=measure)


# ──────────────────────────── public: data loading ─────────────────────────


def load_adapter_data(data_dir: Optional[Path] = None) -> dict:
    """
    Load and merge ``adapter_status.json`` and ``current_positions.json``.

    The positions dict is stored under key ``'positions_data'`` in the
    returned dict.  Never raises — missing/corrupt files degrade gracefully.
    """
    if data_dir is None:
        data_dir = _DEFAULT_DATA_DIR
    data_dir = Path(data_dir)

    adapter_data = _read_json(data_dir / "adapter_status.json", default={})
    if not isinstance(adapter_data, dict):
        adapter_data = {}

    positions_data = _read_json(data_dir / "current_positions.json", default={})
    if not isinstance(positions_data, dict):
        positions_data = {}

    adapter_data["positions_data"] = positions_data
    return adapter_data


# ──────────────────────────── credentials ──────────────────────────────────


def _get_keychain_secret(key: str) -> str:
    """Read a secret from macOS Keychain via the `security` CLI."""
    result = subprocess.run(
        ["security", "find-generic-password", "-s", key, "-w"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise ConfigError(
            key,
            f"Keychain lookup failed: {result.stderr.strip()}",
        )
    return result.stdout.strip()


def _resolve_credentials(
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> tuple[str, str]:
    """
    Resolve Telegram credentials.

    Fallback chain (per credential):
        1. Explicit argument
        2. Environment variables (TELEGRAM_BOT_TOKEN_SPA or TELEGRAM_BOT_TOKEN,
           TELEGRAM_CHAT_ID_SPA or TELEGRAM_CHAT_ID)
        3. macOS Keychain (TELEGRAM_BOT_TOKEN_SPA / TELEGRAM_CHAT_ID_SPA)
    """
    token = bot_token
    if not token:
        token = os.environ.get("TELEGRAM_BOT_TOKEN_SPA") or os.environ.get(
            "TELEGRAM_BOT_TOKEN"
        )
    if not token:
        token = _get_keychain_secret("TELEGRAM_BOT_TOKEN_SPA")

    cid = chat_id
    if not cid:
        cid = os.environ.get("TELEGRAM_CHAT_ID_SPA") or os.environ.get(
            "TELEGRAM_CHAT_ID"
        )
    if not cid:
        cid = _get_keychain_secret("TELEGRAM_CHAT_ID_SPA")

    return token, cid  # type: ignore[return-value]


# ──────────────────────────── HTTP transport ───────────────────────────────


def _post_message(token: str, chat_id: str, text: str) -> dict:
    """RETIRED as a Telegram push (Phase-1 Telegram rebuild).

    The /protocols report is on-demand (a bot pull-view), not an unsolicited
    push. This no longer routes to the transport; the composed text is dropped
    to the digest queue. The ``token``/``chat_id`` args are kept for signature
    compatibility. Returns an API-shaped ``{"ok": False}``. Never raises.
    """
    try:
        from spa_core.telegram import push_policy
        push_policy._enqueue_digest(
            push_policy._tg_dir(),
            {
                "ts": push_policy._now_iso(),
                "event_key": "protocols_report",
                "severity": "INFO",
                "title": "Protocols report",
                "body": (text or "")[:500],
                "reason": "protocols_reporter_retired_push",
            },
        )
    except Exception:  # noqa: BLE001
        pass
    return {"ok": False}


# ──────────────────────────── public: send ─────────────────────────────────


def send_protocols_report(
    chat_id: Optional[str] = None,
    bot_token: Optional[str] = None,
    *,
    data_dir: Optional[Path] = None,
    data: Optional[dict] = None,
) -> dict:
    """
    Load adapter data, format the /protocols message, and send via Telegram.

    Parameters
    ----------
    chat_id   : Telegram chat ID. Falls back to env var → Keychain.
    bot_token : Telegram bot token. Falls back to env var → Keychain.
    data_dir  : Path to the ``data/`` directory (default: ``<repo>/data``).
    data      : Pre-loaded data dict. When provided, skips file loading
                (useful for tests and offline formatting).

    Returns
    -------
    dict with:
        ok        — True when all chunks sent without error.
        sent      — number of message parts successfully sent.
        responses — list of Telegram API response dicts.
        errors    — list of error strings (empty on success).
    """
    token, cid = _resolve_credentials(bot_token, chat_id)

    if data is None:
        data = load_adapter_data(data_dir)

    # Правило деления — ОДНА копия на обе двери (ADR-711). До сегодня эта
    # функция знала его сама, и у новой двери бота оно стало бы вторым: ровно тот
    # класс, который ADR-710 вылечил у формы раздела `adapters`.
    parts = protocols_report_parts(data)

    responses: list[dict] = []
    errors: list[str] = []

    for part in parts:
        try:
            resp = _post_message(token, cid, part)
            responses.append(resp)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            errors.append(str(exc))
            log.error("Telegram send failed: %s", exc)

    return {
        "ok": len(errors) == 0,
        "sent": len(responses),
        "responses": responses,
        "errors": errors,
    }


# ──────────────────────────── CLI ──────────────────────────────────────────


def main() -> None:
    """CLI: print (and optionally send) the /protocols report."""
    import argparse

    parser = argparse.ArgumentParser(
        description="SPA /protocols Telegram reporter (MP-659)"
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Actually send to Telegram (default: print only)",
    )
    parser.add_argument("--chat-id", default=None, help="Override Telegram chat ID")
    parser.add_argument(
        "--bot-token", default=None, help="Override Telegram bot token"
    )
    parser.add_argument(
        "--data-dir", default=None, help="Path to data/ directory"
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir) if args.data_dir else None
    data = load_adapter_data(data_dir)
    message = format_protocols_message(data)

    print(message)
    parts = split_message(message)
    print(f"\n[{len(message)} chars, {len(parts)} part(s)]")

    if args.send:
        result = send_protocols_report(
            chat_id=args.chat_id,
            bot_token=args.bot_token,
            data_dir=data_dir,
            data=data,
        )
        if result["ok"]:
            print(f"✅ Sent {result['sent']} part(s) to Telegram.")
        else:
            print(f"❌ Errors: {result['errors']}")


if __name__ == "__main__":
    main()
