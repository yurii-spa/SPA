"""Alpha Agent — еженедельный скан кандидатов на whitelist (MP-304).

ИСТОЧНИКИ:
  data/candidate_registry.json — кандидаты от discovery (adapter_sdk/discovery.py);
    нечитаемый/отсутствующий реестр = measured=False, а НЕ «кандидатов ноль»
    (в проде файла НЕТ — см. candidates_measured в артефакте)
  канон покрытия — protocol_research_agent.known_protocols() (реестр адаптеров +
    манифесты SDK); отвечает на «это уже наше?»
  data/adapter_orchestrator_status.json — что оркестратор ОПРОСИЛ (другой вопрос,
    отдельное поле); нечитаемый артефакт = measured=False, а НЕ «активных ноль»
  data/analytics_summary.json — текущая аналитика портфеля

СКОРИНГ КАНДИДАТОВ (детерминированный, без LLM):
AlphaScore = dataclass(protocol_id, name, score, rationale, risk_flags, suggested_tier)

score = взвешенная сумма (0-100):
  tvl_score: TVL >$100M → 30, >$50M → 20, >$10M → 10, else 0
  apy_score: 5-10% → 20, 3-5% → 10, >10% → 5 (sanity cap), else 0
  exit_score: instant (0h) → 20, <24h → 15, <168h → 5, else 0
  tier_bonus: T2 → 15, T3 → 10 (diversity)
  diversification_bonus: если протокол не пересекается с множеством покрытия → 15;
    при НЕ измеренном множестве покрытия → 0 (fail-CLOSED: «не смогли посмотреть»
    не оплачивается баллами в пользу дубля), основание видно в
    diversification_basis, а СИЛА совпадения — в diversification_match
    (MATCH_EXACT / MATCH_TOKEN / MATCH_SUBSTR, цикл #283)

risk_flags:
  "credit_risk" если "credit" в имени протокола
  "peg_risk" если "peg" в имени протокола или символе
  "low_liquidity" если TVL < $10M
  "high_exit_latency" если exit > 72h

Топ-5 кандидатов по score → data/alpha_candidates.json (атомарно).

LLM-enhanced rationale (опционально):
generate_rationale_with_llm(candidate: dict, llm_fn=None) -> str
  При llm_fn=None → детерминированный шаблон:
  "Protocol {name} scored {score}/100. TVL: ${tvl}M. APY: {apy}%. Risks: {flags}."

Stdlib only. Atomic writes (tmp + os.replace). No imports from execution/risk agents.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from spa_core.utils.atomic import atomic_save
# Канон «что мы уже охватываем» живёт ОДИН раз — у соседнего исследовательского
# агента (цикл #276). Здесь его только читают: пятое определение того же
# множества и есть та авария, из-за которой это исправление понадобилось.
from spa_core.agents.protocol_research_agent import known_protocols

log = logging.getLogger("spa.agents.alpha_agent")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

# Output file
ALPHA_CANDIDATES_FILENAME = "alpha_candidates.json"
TOP_N_DEFAULT = 5

# Score component weights / thresholds
_TVL_TIER1 = 100_000_000.0   # $100M → 30
_TVL_TIER2 = 50_000_000.0    # $50M  → 20
_TVL_TIER3 = 10_000_000.0    # $10M  → 10

_APY_HIGH_LOW = 5.0           # 5% lower bound of "good APY" band
_APY_HIGH_HIGH = 10.0         # 10% upper bound of "good APY" band
_APY_MEDIUM_LOW = 3.0         # 3% lower bound of "medium APY" band
_APY_SANITY_CAP = 30.0        # >30% is suspicious (already filtered by discovery)

_EXIT_INSTANT = 0.0           # 0h  → instant → 20
_EXIT_DAY = 24.0              # <24h → 15
_EXIT_WEEK = 168.0            # <168h (7 days) → 5
_EXIT_HIGH_RISK = 72.0        # >72h → high_exit_latency flag


# ─── AlphaScore dataclass ─────────────────────────────────────────────────────


@dataclass
class AlphaScore:
    """Scoring result for a single candidate protocol."""

    protocol_id: str
    name: str
    score: int                              # 0–100 total
    tvl_score: int = 0
    apy_score: int = 0
    exit_score: int = 0
    tier_bonus: int = 0
    diversification_bonus: int = 0
    # Почему бонус за диверсификацию именно такой: "" — пересечений нет (бонус
    # начислен) · имя из множества покрытия — совпало с ним (бонус снят) ·
    # "не измерено: <причина>" — множество покрытия не прочитано, бонус снят
    # fail-CLOSED. Без этого поля ложное совпадение по подстроке невидимо.
    diversification_basis: str = ""
    # ВИД совпадения (цикл #283): "" — не совпало либо не измерено ·
    # MATCH_EXACT — нормализованные имена совпали целиком ·
    # MATCH_TOKEN — одно имя есть непрерывный ряд токенов другого
    # (``aave_v3`` ⊂ ``aave_v3_base``) · MATCH_SUBSTR — совпало ТОЛЬКО как
    # подстрока, границы токенов НЕ совпали (``frax`` ⊂ ``sfrax``).
    # Замер на каноне (56 имён): из 17 пар 15 — MATCH_TOKEN, 2 — MATCH_SUBSTR;
    # последний класс самый слабый. Отдельным полем, потому что basis отвечает
    # «с чем совпало», а этот — «насколько этому совпадению можно верить».
    diversification_match: str = ""
    rationale: str = ""
    risk_flags: list[str] = field(default_factory=list)
    suggested_tier: str = "candidate"       # always "candidate" — never T1/T2/T3

    # Raw data (for rationale generation)
    tvl_usd: float = 0.0
    apy_pct: float = 0.0
    exit_latency_hours: Optional[float] = None
    chain: str = ""
    symbol: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ─── IO helpers ───────────────────────────────────────────────────────────────


def _read_json(path: Path, default: Any) -> Any:
    """Read JSON defensively. Missing/corrupt file → default (never raises)."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("_read_json %s unreadable (%s) — using default", path.name, exc)
        return default


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))


# ─── «Это уже наше?» — множество покрытия вместе с честностью замера ───────────
#
# У вопроса «охватываем ли мы уже этот протокол» в репозитории жили ЧЕТЫРЕ
# разных ответа: канон реестра (36) · ``ADAPTER_METADATA`` (22) · опрошенное
# оркестратором (8) · манифесты (21). Здесь читался САМЫЙ УЗКИЙ из них —
# артефакт последнего опроса, — и выдавался за «вот всё, что у нас есть».
# Пятого определения не заводим: канон берём у соседа
# (``protocol_research_agent.known_protocols``, цикл #276), опрос читаем сами и
# держим ОТДЕЛЬНЫМ полем, потому что это ответ на другой вопрос («что реально
# опрашивается»), а не на «не изобретаем ли мы уже имеющееся».
#
# Главное: «не смогли посмотреть» ≠ «активных ноль». Раньше пустой список
# означал оба состояния сразу, а бонус за диверсификацию платит за него +15
# баллов из 100 — то есть непрочитанный артефакт СИСТЕМАТИЧЕСКИ поднимал в
# ранге кандидатов, которых мы уже держим. Теперь при ``measured=False`` бонус
# не начисляется вовсе.


def _norm(s: str) -> str:
    """Нормализация имени протокола: регистр, дефисы/пробелы → подчёркивания."""
    return str(s).strip().lower().replace("-", "_").replace(" ", "_")


# ─── Сличение имён: КАК именно совпало ────────────────────────────────────────
#
# Сличение идёт подстрокой в обе стороны, и цикл #277, подняв множество канона
# с 8 имён до 56, завёл карточку: «ложный отказ в бонусе стал в семь раз
# вероятнее». Величину замерили (цикл #283, тест
# ``test_alpha_name_matching.py``), и она оказалась не той, что ожидалась:
#
#   на каноне из 56 имён подстрока даёт 17 пар, из которых 15 совпадают и по
#   ГРАНИЦАМ ТОКЕНОВ (``aave_v3`` ⊂ ``aave_v3_base``, ``susde`` ⊂
#   ``ethena_susde``), и лишь 2 — только как подстрока (``frax`` ⊂ ``fraxlend``,
#   ``frax`` ⊂ ``sfrax``). Обе «только подстрочные» пары — РОДНЯ по существу
#   (Frax и его же продукты), то есть совпадение верное.
#
# Отсюда решение НЕ менять форму сличения (подробности и цена — в карточке
# ``inbox-slichenie-imen-protokolov-podstrokoi-vyr`` и журнале W34): на
# измеренном множестве переход к границам токенов ломает 2 ВЕРНЫХ совпадения и
# не чинит ни одного ложного. Единственная ложная пара канона —
# ``pendle_pt_susde`` ↔ ``susde`` (PT-токен Pendle на sUSDE ≠ сам sUSDE) — по
# ФОРМЕ ИМЕНИ неотличима от верной ``ethena_susde`` ↔ ``susde``: обе суть
# ``X_susde ⊃ susde``. Никакое синтаксическое правило их не разделит; разделяет
# только личность пула (UUID) — это отдельная задача.
#
# Поэтому здесь не правило, а ВИДИМОСТЬ: вид совпадения кладётся в артефакт
# рядом с именем, и самый слабый класс (``MATCH_SUBSTR``) можно отобрать
# запросом, а не перечитыванием кода.

MATCH_EXACT = "точное совпадение"
MATCH_TOKEN = "граница токенов"
MATCH_SUBSTR = "подстрока (границы токенов не совпали)"


def _tokens(s: str) -> list[str]:
    """Имя протокола → список токенов (``aave_v3`` → ``['aave', 'v3']``)."""
    return [t for t in _norm(s).split("_") if t]


def _token_run(short: list[str], long_: list[str]) -> bool:
    """Является ли ``short`` непрерывным рядом токенов внутри ``long_``."""
    n = len(short)
    if not n or n > len(long_):
        return False
    return any(long_[i:i + n] == short for i in range(len(long_) - n + 1))


def match_names(a: str, b: str) -> str:
    """Как совпали два имени протокола: ``MATCH_*`` либо ``""`` (не совпали).

    Порядок ответов — от сильного к слабому; критерий совпадения тот же, что и
    был (подстрока в обе стороны), меняется только то, что вид совпадения
    теперь НАЗЫВАЕТСЯ.
    """
    an, bn = _norm(a), _norm(b)
    if not an or not bn:
        return ""
    if an == bn:
        return MATCH_EXACT
    if not (an in bn or bn in an):
        return ""
    ta, tb = _tokens(an), _tokens(bn)
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return MATCH_TOKEN if _token_run(short, long_) else MATCH_SUBSTR


def coverage_match(protocol: str, names: Any) -> tuple[str, str]:
    """Первое совпадение имени с множеством покрытия: ``(имя, вид)``.

    Не совпало ни с чем → ``("", "")``. Порядок обхода — как задан вызывающим
    (у :func:`coverage_set` он отсортирован), чтобы ответ был детерминирован.
    """
    for active in names or []:
        kind = match_names(protocol, active)
        if kind:
            return str(active), kind
    return "", ""


def polled_protocols(data_dir: str | os.PathLike | None = None) -> dict:
    """Что оркестратор ОПРОСИЛ в последний раз — вместе с честностью замера.

    Ключи
    -----
    ``ids``      — имена протоколов из артефакта опроса;
    ``measured`` — False, если артефакт не прочитан (нет файла / нечитаем /
                   не та форма). Это НЕ «активных ноль»;
    ``reason``   — почему не измерен, словами (пусто при ``measured=True``).

    Присутствующий артефакт с пустым списком адаптеров — ИЗМЕРЕННЫЙ ноль
    (``measured=True``, ``ids=[]``), и это другое состояние.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    path = ddir / "adapter_orchestrator_status.json"

    if not path.exists():
        return {"ids": [], "measured": False,
                "reason": f"артефакт опроса не найден ({path.name})"}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return {"ids": [], "measured": False,
                "reason": f"артефакт опроса нечитаем ({path.name}: {type(exc).__name__})"}
    if not isinstance(doc, dict):
        return {"ids": [], "measured": False,
                "reason": f"артефакт опроса не объект ({path.name}: {type(doc).__name__})"}

    adapters = doc.get("adapters")
    if adapters is None:
        return {"ids": [], "measured": False,
                "reason": f"в артефакте опроса нет ключа adapters ({path.name})"}
    if not isinstance(adapters, list):
        return {"ids": [], "measured": False,
                "reason": (f"ключ adapters не список ({path.name}: "
                           f"{type(adapters).__name__})")}

    ids = [str(a["protocol"]) for a in adapters
           if isinstance(a, dict) and a.get("protocol")]
    return {"ids": ids, "measured": True, "reason": ""}


def coverage_set(data_dir: str | os.PathLike | None = None) -> dict:
    """Ответ на «это уже наше?»: КАНОН покрытия ∪ опрошенное, с честностью замера.

    Канон (реестр адаптеров + манифесты SDK) — правильный ответ на вопрос «не
    изобретаем ли мы то, что уже есть»; опрошенное оркестратором отвечает на
    другой вопрос и лежит здесь отдельным полем, а не вместо канона.

    Ключи
    -----
    ``ids``      — нормализованное объединение;
    ``measured`` — False, если хотя бы одна половина НЕ измерена;
    ``reason``   — какая именно половина и почему, словами;
    ``canon_ids`` / ``polled_ids`` — сырые списки либо ``None`` (не измерено).

    Потребитель ОБЯЗАН читать ``measured``: при False фильтр «это уже наше»
    ненадёжен, и уже охваченный протокол приедет как новый кандидат.
    """
    canon = known_protocols()
    polled = polled_protocols(data_dir)

    reasons: list[str] = []
    if not canon.get("measured", False):
        reasons.append("канон покрытия: " + (canon.get("reason") or "причина не названа"))
    if not polled["measured"]:
        reasons.append("опрос оркестратора: " + polled["reason"])

    canon_ids = list(canon.get("ids") or [])
    ids = sorted({_norm(i) for i in canon_ids + polled["ids"] if str(i).strip()})
    return {
        "ids": ids,
        "measured": not reasons,
        "reason": " · ".join(reasons),
        "canon_ids": canon_ids if canon.get("measured", False) else None,
        "polled_ids": polled["ids"] if polled["measured"] else None,
        "canon_count": len(canon_ids) if canon.get("measured", False) else None,
        "polled_count": len(polled["ids"]) if polled["measured"] else None,
    }
def _score_tvl(tvl_usd: float) -> int:
    """TVL score component (0–30)."""
    if tvl_usd > _TVL_TIER1:
        return 30
    if tvl_usd > _TVL_TIER2:
        return 20
    if tvl_usd > _TVL_TIER3:
        return 10
    return 0


def _score_apy(apy_pct: float) -> int:
    """APY score component (0–20). Sanity cap at >10% returns only 5."""
    if _APY_HIGH_LOW <= apy_pct <= _APY_HIGH_HIGH:
        return 20
    if _APY_MEDIUM_LOW <= apy_pct < _APY_HIGH_LOW:
        return 10
    if apy_pct > _APY_HIGH_HIGH:
        return 5  # sanity cap — suspiciously high
    return 0


def _score_exit(exit_latency_hours: Optional[float]) -> int:
    """Exit latency score component (0–20)."""
    if exit_latency_hours is None:
        return 0  # unknown → 0 (conservative)
    if exit_latency_hours <= _EXIT_INSTANT:
        return 20   # instant
    if exit_latency_hours < _EXIT_DAY:
        return 15   # <24h
    if exit_latency_hours < _EXIT_WEEK:
        return 5    # <168h (7 days)
    return 0


def _score_tier_bonus(suggested_tier: str) -> int:
    """Tier diversity bonus (0–15)."""
    t = str(suggested_tier).strip().upper()
    if t == "T2":
        return 15
    if t == "T3":
        return 10
    # "candidate" means unknown tier → small bonus for diversity potential
    return 10


def diversification(protocol: str, coverage: Any) -> tuple[int, str, str]:
    """Бонус за диверсификацию (0–15), основание и ВИД совпадения.

    ``coverage`` — либо словарь замера (:func:`coverage_set`), либо готовый
    список имён (тогда он считается измеренным: множество задал сам вызывающий).

    Возврат: ``(бонус, основание, вид)``. Основание — "" (пересечений нет), имя
    из множества покрытия (совпало) либо "не измерено: <причина>". Вид — одна
    из констант ``MATCH_*`` либо "" (не совпало / не измерено).

    При ``measured=False`` бонус НЕ начисляется: «не смогли посмотреть» не
    должно оплачиваться баллами в пользу дубля (fail-CLOSED).
    """
    if isinstance(coverage, dict):
        if not coverage.get("measured", False):
            reason = coverage.get("reason") or "причина не названа"
            return 0, "не измерено: " + reason, ""
        names = coverage.get("ids") or []
    else:
        names = coverage or []

    matched, kind = coverage_match(protocol, names)
    if matched:
        return 0, matched, kind
    return 15, "", ""


def _diversification(protocol: str, coverage: Any) -> tuple[int, str]:
    """Совместимая обёртка над :func:`diversification`: бонус и основание.

    Вид совпадения (``MATCH_*``) здесь теряется — кому он нужен, зовёт
    :func:`diversification`.
    """
    bonus, basis, _kind = diversification(protocol, coverage)
    return bonus, basis


def _score_diversification(protocol: str, active_protocols: list[str]) -> int:
    """Diversification bonus if protocol not in active protocols (0–15).

    Normalises dashes/underscores so "morpho-blue" == "morpho_blue",
    then uses substring match to handle prefix slugs ("spark" ⊆ "sparklend").

    Совместимая обёртка над :func:`_diversification`: отдаёт только число.
    Кто должен знать, ИЗМЕРЕНО ли множество покрытия, обязан передавать словарь
    замера — иначе «не смогли посмотреть» снова станет неотличимо от «ноль».
    """
    return _diversification(protocol, active_protocols)[0]


def _compute_risk_flags(
    protocol: str,
    symbol: str,
    tvl_usd: float,
    exit_latency_hours: Optional[float],
) -> list[str]:
    """Determine risk flags from candidate properties."""
    flags: list[str] = []
    protocol_lower = str(protocol).strip().lower()
    symbol_lower = str(symbol).strip().lower()

    if "credit" in protocol_lower:
        flags.append("credit_risk")
    if "peg" in protocol_lower or "peg" in symbol_lower:
        flags.append("peg_risk")
    if tvl_usd < _TVL_TIER3:
        flags.append("low_liquidity")
    if exit_latency_hours is not None and exit_latency_hours > _EXIT_HIGH_RISK:
        flags.append("high_exit_latency")

    return flags


# ─── LLM-enhanced rationale (optional; deterministic fallback) ────────────────


def generate_rationale_with_llm(
    candidate: dict,
    llm_fn: Optional[Callable[[dict], str]] = None,
) -> str:
    """Generate a rationale string for a candidate.

    Parameters
    ----------
    candidate : dict — candidate dict (from AlphaScore.to_dict() or raw).
    llm_fn    : optional callable(candidate_dict) → str. When None (default),
                falls back to a deterministic template. LLM_FORBIDDEN in risk/
                execution/monitoring components — this function must NOT be called
                from those domains.

    Returns
    -------
    str — human-readable rationale.
    """
    if llm_fn is not None:
        try:
            return str(llm_fn(candidate))
        except Exception as exc:
            log.warning("llm_fn failed (%s) — falling back to deterministic template", exc)

    # Deterministic template (fallback / default)
    name = candidate.get("name") or candidate.get("protocol_id") or "?"
    score = candidate.get("score", 0)
    tvl_usd = float(candidate.get("tvl_usd") or 0.0)
    apy_pct = float(candidate.get("apy_pct") or 0.0)
    flags = candidate.get("risk_flags") or []
    flags_str = ", ".join(flags) if flags else "none"
    tvl_m = tvl_usd / 1_000_000.0
    return (
        f"Protocol {name} scored {score}/100. "
        f"TVL: ${tvl_m:.1f}M. APY: {apy_pct:.2f}%. "
        f"Risks: {flags_str}."
    )


# ─── Core scoring function ─────────────────────────────────────────────────────


def score_candidate(candidate: dict, active_protocols: Any) -> AlphaScore:
    """Score a single candidate dict → AlphaScore.

    Parameters
    ----------
    candidate        : dict from candidate_registry.json (discovery output).
    active_protocols : множество покрытия — либо словарь замера
                       (:func:`coverage_set`, тогда читается ``measured``),
                       либо готовый список имён (тогда он считается измеренным:
                       его задал сам вызывающий).

    Returns
    -------
    AlphaScore — fully computed score with components and risk flags.
    """
    protocol = str(candidate.get("protocol") or candidate.get("protocol_id") or "")
    name = protocol  # display name; use protocol slug
    symbol = str(candidate.get("symbol") or "")
    chain = str(candidate.get("chain") or "")
    tvl_usd = float(candidate.get("tvl_usd") or 0.0)
    apy_pct = float(candidate.get("apy_pct") or 0.0)
    exit_latency_hours: Optional[float] = None
    if candidate.get("exit_latency_hours") is not None:
        try:
            exit_latency_hours = float(candidate["exit_latency_hours"])
        except (TypeError, ValueError):
            pass

    # Use discovery's suggested_tier if provided
    raw_tier = str(candidate.get("suggested_tier") or "candidate").strip()

    # Score components
    tvl_score = _score_tvl(tvl_usd)
    apy_score = _score_apy(apy_pct)
    exit_score = _score_exit(exit_latency_hours)
    tier_bonus = _score_tier_bonus(raw_tier)
    div_bonus, div_basis, div_match = diversification(protocol, active_protocols)

    total = tvl_score + apy_score + exit_score + tier_bonus + div_bonus
    # Clamp to 0–100
    total = max(0, min(100, total))

    risk_flags = _compute_risk_flags(protocol, symbol, tvl_usd, exit_latency_hours)

    alpha = AlphaScore(
        protocol_id=protocol,
        name=name,
        score=total,
        tvl_score=tvl_score,
        apy_score=apy_score,
        exit_score=exit_score,
        tier_bonus=tier_bonus,
        diversification_bonus=div_bonus,
        diversification_basis=div_basis,
        diversification_match=div_match,
        risk_flags=risk_flags,
        suggested_tier="candidate",  # always candidate — never promote directly
        tvl_usd=tvl_usd,
        apy_pct=apy_pct,
        exit_latency_hours=exit_latency_hours,
        chain=chain,
        symbol=symbol,
    )
    alpha.rationale = generate_rationale_with_llm(alpha.to_dict())
    return alpha


# ─── Data loading helpers ──────────────────────────────────────────────────────


def candidate_set(data_dir: str | os.PathLike | None = None) -> dict:
    """Кандидаты от discovery ВМЕСТЕ с честностью замера.

    Пятая прядь той же ниточки, что #276 (активные адаптеры) и #277 (множество
    покрытия): у обоих множеств «не смогли посмотреть» уже отделено от
    измеренного нуля, а у САМИХ КАНДИДАТОВ — нет. Между тем в проде
    ``data/candidate_registry.json`` не существует вовсе (discovery запускают
    вручную), и артефакт ``alpha_candidates.json`` печатает ``"candidates": []``
    — то есть «посмотрели и не нашли ничего достойного», хотя верное чтение
    «мы не смотрели ни разу». Читатель отличить это не может ничем.

    Ключи
    -----
    ``items``    — список кандидатов-словарей;
    ``measured`` — False, если реестр не прочитан (нет файла / нечитаем /
                   не та форма). Это НЕ «кандидатов ноль»;
    ``reason``   — почему не измерен, словами (пусто при ``measured=True``).

    Присутствующий реестр с пустым списком — ИЗМЕРЕННЫЙ ноль
    (``measured=True``, ``items=[]``), и это другое состояние.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    path = ddir / "candidate_registry.json"

    if not path.exists():
        return {"items": [], "measured": False,
                "reason": f"реестр кандидатов не найден ({path.name}) — "
                          "discovery ни разу не отработал в этом дереве"}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return {"items": [], "measured": False,
                "reason": f"реестр кандидатов нечитаем ({path.name}: {type(exc).__name__})"}

    if isinstance(doc, list):
        return {"items": [c for c in doc if isinstance(c, dict)],
                "measured": True, "reason": ""}
    if not isinstance(doc, dict):
        return {"items": [], "measured": False,
                "reason": (f"реестр кандидатов не объект и не список "
                           f"({path.name}: {type(doc).__name__})")}

    raw = doc.get("candidates")
    if raw is None:
        return {"items": [], "measured": False,
                "reason": f"в реестре кандидатов нет ключа candidates ({path.name})"}
    if not isinstance(raw, list):
        return {"items": [], "measured": False,
                "reason": (f"ключ candidates не список ({path.name}: "
                           f"{type(raw).__name__})")}
    return {"items": [c for c in raw if isinstance(c, dict)],
            "measured": True, "reason": ""}


def _load_candidates(data_dir: Path) -> list[dict]:
    """Совместимая обёртка над :func:`candidate_set`: отдаёт только список.

    Здесь пустой список по-прежнему означает и «кандидатов ноль», и «реестр не
    прочитан»; кто должен их различать, обязан звать :func:`candidate_set`.
    """
    return candidate_set(data_dir)["items"]


def _load_active_protocols(data_dir: Path) -> list[str]:
    """Load adapter_orchestrator_status.json → list of active protocol keys.

    Совместимая обёртка: отдаёт только имена опрошенного. Кто должен знать,
    ИЗМЕРЕНО ли множество, обязан звать :func:`polled_protocols` /
    :func:`coverage_set` — здесь пустой список по-прежнему означает и «опросили
    ноль», и «артефакт не прочитан», и различить их нечем.
    """
    return polled_protocols(data_dir)["ids"]


def _load_analytics(data_dir: Path) -> dict:
    """Load analytics_summary.json. Fail-safe."""
    doc = _read_json(data_dir / "analytics_summary.json", {})
    return doc if isinstance(doc, dict) else {}


# ─── Public API ───────────────────────────────────────────────────────────────


def run_alpha_scan(
    data_dir: str | os.PathLike | None = None,
    top_n: int = TOP_N_DEFAULT,
) -> dict:
    """Full alpha scan: load sources → score candidates → write alpha_candidates.json.

    Fail-safe: any individual source failure returns empty data, never crashes.
    The output file is written atomically (tmp + os.replace).

    Returns
    -------
    dict — the alpha_candidates.json document.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR

    candidates = candidate_set(ddir)
    candidates_raw = candidates["items"]
    coverage = coverage_set(ddir)

    scored: list[AlphaScore] = []
    for raw in candidates_raw:
        try:
            s = score_candidate(raw, coverage)
            scored.append(s)
        except Exception as exc:
            log.warning("score_candidate failed for %s (%s) — skipped", raw, exc)

    # Sort by score desc, then protocol_id for deterministic tie-breaking
    scored.sort(key=lambda s: (-s.score, s.protocol_id))
    top = scored[:top_n]

    if not coverage["measured"]:
        log.warning(
            "множество покрытия НЕ измерено (%s) — бонус за диверсификацию не "
            "начисляется никому (fail-CLOSED)", coverage["reason"],
        )
    if not candidates["measured"]:
        log.warning(
            "реестр кандидатов НЕ измерен (%s) — пустой список НЕ означает "
            "«кандидатов нет»", candidates["reason"],
        )

    now_ts = datetime.now(timezone.utc).isoformat()
    doc: dict = {
        "generated_at": now_ts,
        "scan_basis": (
            "candidate_registry + канон покрытия (адаптеры+манифесты) "
            "+ опрос оркестратора"
        ),
        "candidates": [s.to_dict() for s in top],
        # None = НЕ ИЗМЕРЕНО (артефакт опроса не прочитан), [] = опросили ноль.
        # Раньше здесь стояли оба состояния сразу, и восемь опрошенных имён
        # читались как «вот всё, что у нас есть».
        "already_active": coverage["polled_ids"],
        "already_active_note": (
            "опрошенное оркестратором в последний раз; на вопрос «это уже наше?» "
            "отвечает coverage.ids (канон покрытия), а не это поле"
        ),
        "coverage": coverage,
        # Честность замера САМИХ кандидатов (цикл #283). Без этих двух полей
        # `"candidates": []` читается как «посмотрели, ничего не нашли», тогда
        # как в проде реестра нет вовсе и верное чтение — «не смотрели».
        "candidates_measured": candidates["measured"],
        "candidates_reason": candidates["reason"],
        "note": (
            "candidates require ADR/human review before whitelisting — "
            "do not auto-promote"
        ),
        "total_candidates_scanned": len(candidates_raw),
        "total_scored": len(scored),
    }

    try:
        _atomic_write_json(ddir / ALPHA_CANDIDATES_FILENAME, doc)
        log.info(
            "Alpha scan complete: %d candidates scored, top %d written to %s",
            len(scored),
            len(top),
            ALPHA_CANDIDATES_FILENAME,
        )
    except Exception as exc:
        log.warning("alpha_candidates.json write failed (%s) — scan result in memory only", exc)

    return doc


def get_top_candidates(
    n: int = TOP_N_DEFAULT,
    data_dir: str | os.PathLike | None = None,
) -> list[AlphaScore]:
    """Run a scan and return the top-N AlphaScore objects.

    Parameters
    ----------
    n         : number of top candidates to return (default: 5).
    data_dir  : data directory (default: <repo>/data).

    Returns
    -------
    list[AlphaScore] — sorted by score descending.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    candidates_raw = _load_candidates(ddir)
    coverage = coverage_set(ddir)

    scored: list[AlphaScore] = []
    for raw in candidates_raw:
        try:
            s = score_candidate(raw, coverage)
            scored.append(s)
        except Exception as exc:
            log.warning("score_candidate failed for %s (%s) — skipped", raw, exc)

    scored.sort(key=lambda s: (-s.score, s.protocol_id))
    return scored[:n]
