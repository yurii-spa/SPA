"""Protocol Research Agent — еженедельный поиск НОВЫХ DeFi-протоколов (MP-307).

Дополняет Alpha Agent (MP-304): тот скорит уже известных кандидатов из
candidate_registry.json; этот ИЩЕТ кандидатов, которых ещё нет в active
adapters или manifests, и формирует structured research notes.

Источники (все fail-safe):
  data/candidate_registry.json  — кандидаты от discovery (adapter_sdk/discovery.py)
  spa_core/adapter_sdk/manifests/  — уже охваченные протоколы (YAML/JSON)
  spa_core/adapters/__init__.py  — реестр активных адаптеров ADAPTER_REGISTRY

КОНСТИТУЦИОННЫЙ ИНВАРИАНТ:
  LLM SDK ЗАПРЕЩЁН (stdlib only).
  LLM injectable через research_fn=None (деградирует на детерминированный шаблон).
  LLM_FORBIDDEN_AGENTS = {risk, execution, monitoring} — данный модуль
  НЕ входит в запрещённые домены, но сам избегает LLM-зависимости.

SECURITY_SCORE формула (детерминированная, 0–100):
  audit_count * 20  (capped 60)
  age_days / 365 * 20  (capped 20)
  open_source → +10
  bug_bounty  → +10

Вывод:
  data/protocol_research.json       — top-10 исследованных протоколов (атомарно)
  data/protocol_research_status.json — статус последнего цикла (атомарно)

Stdlib only. Atomic writes (tmpfile + os.replace). No imports from execution/risk/monitoring.
"""
from __future__ import annotations

import ast
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional
from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.agents.protocol_research_agent")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
_MANIFESTS_DIR = _REPO_ROOT / "spa_core" / "adapter_sdk" / "manifests"
_ADAPTERS_INIT = _REPO_ROOT / "spa_core" / "adapters" / "__init__.py"

RESEARCH_FILENAME = "protocol_research.json"
RESEARCH_STATUS_FILENAME = "protocol_research_status.json"
TOP_N = 10

# Security score thresholds
_AUDIT_SCORE_PER_AUDIT = 20
_AUDIT_SCORE_CAP = 60
_AGE_SCORE_CAP = 20
_OPEN_SOURCE_BONUS = 10
_BUG_BOUNTY_BONUS = 10

# TVL thresholds for tier assignment
_TVL_T1 = 100_000_000.0   # $100M → T1
_TVL_T2 = 20_000_000.0    # $20M  → T2
_TVL_VALID = 5_000_000.0  # $5M  → defi_llama_validated

# Security score thresholds for tier
_SCORE_T1 = 80
_SCORE_T2 = 60


# ─── IO helpers ───────────────────────────────────────────────────────────────


def _read_json(path: Path, default: Any) -> Any:
    """Read JSON defensively. Missing/corrupt → default (never raises)."""
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
def _normalise(name: str) -> str:
    """Normalise protocol name/id for deduplication: lowercase, dashes→underscores."""
    return str(name).strip().lower().replace("-", "_").replace(" ", "_")


# ─── Active adapters discovery ────────────────────────────────────────────────
#
# Здесь «ничего не нашли» и «не смогли посмотреть» — РАЗНЫЕ ответы, и путать их
# нельзя. Прежний разбор был текстовым и требовал `{` в строке определения, то
# есть был написан под dict-форму реестра, а нацелен на файл, где реестр —
# СПИСОК кортежей: `in_registry` не становился True никогда, функция молча
# отдавала `[]`, и потребитель читал это как «активных адаптеров нет»
# (замер 2026-08-17: 0 вместо 36, `aave_v3` — крупнейшая позиция книги — терялся).
# Отсюда два правила этого блока:
#   1) форму читает AST, а не регулярка (список кортежей / список строк / dict);
#   2) НЕ ИЗМЕРЕНО возвращается как None и НАЗЫВАЕТСЯ вслух, а `[]` означает
#      ровно одно: файл прочитан, реестр разобран и он действительно пуст.
# Путь/каталог — ВХОД функции (по умолчанию реальные), чтобы тест закреплял обе
# стороны и не зависел от окружения.


def _names_from_registry_literal(node: ast.AST) -> tuple[Optional[list[str]], str]:
    """Извлечь имена протоколов из литерала реестра. None = НЕ ИЗМЕРЕНО.

    Поддержанные формы (все три живут в репозитории под похожими именами):
      * список/кортеж кортежей — имя это первый элемент: ``[("aave_v3", ...), ...]``
      * список/кортеж строк — имя это сам элемент: ``["aave_v3", ...]``
      * dict — имена это ключи: ``{"aave_usdc": {...}, ...}``
    """
    if isinstance(node, ast.Dict):
        names = [k.value for k in node.keys
                 if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        if not node.keys:
            return [], ""
        if not names:
            return None, f"dict-реестр из {len(node.keys)} записей не дал ни одного строкового ключа"
        return names, ""

    if isinstance(node, (ast.List, ast.Tuple)):
        if not node.elts:
            return [], ""
        names = []
        for elt in node.elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                names.append(elt.value)
            elif isinstance(elt, (ast.Tuple, ast.List)) and elt.elts:
                first = elt.elts[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    names.append(first.value)
        if not names:
            return None, (
                f"списочный реестр из {len(node.elts)} записей не дал ни одного имени "
                "(ни строк, ни кортежей со строкой первым элементом)"
            )
        return names, ""

    return None, f"форма реестра не список/кортеж/dict, а {type(node).__name__}"


def _registry_names_from_source(
    source: str, var: str = "ADAPTER_REGISTRY"
) -> tuple[Optional[list[str]], str]:
    """Имена протоколов из исходника по AST. None = НЕ ИЗМЕРЕНО + причина словами.

    Считается присваивание на уровне модуля ПЛЮС последующие мутации того же
    имени (``.append(...)`` / ``.extend([...])`` / ``+= [...]``), в том числе
    внутри ``if``/``try``: восемь адаптеров (`moonwell_base`, `aerodrome_base`,
    `silo_arbitrum`, …) добавляются в реестр именно так, под условием успешного
    импорта. Чтение ОДНОГО литерала дало бы 28 имён из 36 — ту же аварию в новой
    одежде: «нашли 28» читалось бы как «всего 28», и уже охваченный протокол
    приехал бы новым кандидатом.

    Упоминание имени в докстринге или комментарии определением НЕ является
    (класс #227 — «упоминание засчитано за проводку»).

    Остаток названного, но не покрытого: если однажды имена начнут собираться
    циклом или из переменной, AST их не увидит — на это стоит тест-паритет
    ``AST ⊇ импортированный ADAPTER_REGISTRY``, он покраснеет, а не промолчит.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return None, f"исходник не разбирается как Python ({exc})"

    value: Optional[ast.AST] = None
    for stmt in tree.body:  # уровень модуля, не вложенные области
        targets: list[ast.AST] = []
        if isinstance(stmt, ast.Assign):
            targets = list(stmt.targets)
        elif isinstance(stmt, ast.AnnAssign):
            targets = [stmt.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id == var:
                value = stmt.value  # последнее присваивание побеждает, как в Python
    if value is None:
        return None, f"присваивания {var} на уровне модуля нет"

    names, reason = _names_from_registry_literal(value)
    if names is None:
        return None, reason
    return list(names) + _names_from_registry_mutations(tree, var), ""


def _names_from_registry_mutations(tree: ast.AST, var: str) -> list[str]:
    """Имена, доехавшие до реестра мутацией имени (``append``/``extend``/``+=``).

    Обходится всё дерево: такие строки живут под ``if``/``try``, то есть вне
    ``tree.body``. Нестроковые/вычисляемые аргументы молча пропускаются — их
    ловит тест-паритет с импортированным реестром, а не догадка здесь.
    """
    extra: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if not (isinstance(owner, ast.Name) and owner.id == var):
                continue
            if node.func.attr == "append" and node.args:
                got, _ = _names_from_registry_literal(ast.List(elts=[node.args[0]], ctx=ast.Load()))
                extra.extend(got or [])
            elif node.func.attr == "extend" and node.args:
                got, _ = _names_from_registry_literal(node.args[0])
                extra.extend(got or [])
        elif isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Add):
            if isinstance(node.target, ast.Name) and node.target.id == var:
                got, _ = _names_from_registry_literal(node.value)
                extra.extend(got or [])
    return extra


def _read_active_adapters_from_init(path: Optional[Path] = None) -> Optional[list[str]]:
    """Имена активных адаптеров из ``spa_core/adapters/__init__.py`` (AST, без импорта).

    Возвращает список имён; **None означает НЕ ИЗМЕРЕНО** (файла нет, не читается,
    не разбирается, присваивания нет, форма незнакома) — и это НЕ то же самое, что
    пустой реестр. Никогда не поднимает исключение. Импорт модуля по-прежнему
    не делается намеренно (побочные эффекты), AST его и не требует.
    """
    init_path = Path(path) if path is not None else _ADAPTERS_INIT
    if not init_path.exists():
        log.warning(
            "активные адаптеры НЕ ИЗМЕРЕНЫ: файла %s нет (не путать с «адаптеров нет»)",
            init_path,
        )
        return None
    try:
        source = init_path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("активные адаптеры НЕ ИЗМЕРЕНЫ: %s не читается (%s)", init_path, exc)
        return None
    names, reason = _registry_names_from_source(source)
    if names is None:
        log.warning("активные адаптеры НЕ ИЗМЕРЕНЫ по %s: %s", init_path.name, reason)
        return None
    return [str(n) for n in names]


def _read_manifest_protocols(directory: Optional[Path] = None) -> Optional[list[str]]:
    """Имена протоколов из ``spa_core/adapter_sdk/manifests/`` (по именам файлов).

    Имя = stem файла (``aave_v3.yaml`` → ``aave_v3``). **None = НЕ ИЗМЕРЕНО**
    (каталога нет или он не читается); ``[]`` = каталог прочитан и манифестов в
    нём нет. Никогда не поднимает исключение.
    """
    manifests_dir = Path(directory) if directory is not None else _MANIFESTS_DIR
    if not manifests_dir.exists():
        log.warning(
            "манифесты НЕ ИЗМЕРЕНЫ: каталога %s нет (не путать с «манифестов нет»)",
            manifests_dir,
        )
        return None
    try:
        return [
            f.stem for f in manifests_dir.iterdir()
            if f.suffix in (".yaml", ".yml", ".json")
        ]
    except OSError as exc:
        log.warning("манифесты НЕ ИЗМЕРЕНЫ: %s не читается (%s)", manifests_dir, exc)
        return None


def known_protocols(
    *, init_path: Optional[Path] = None, manifests_dir: Optional[Path] = None
) -> dict:
    """Множество уже охваченных протоколов ВМЕСТЕ с честностью замера.

    Ключи
    -----
    ``ids``        — нормализованные имена (объединение измеренных источников);
    ``measured``   — False, если хотя бы один источник НЕ ИЗМЕРЕН;
    ``reason``     — почему не измерен, словами (пусто при ``measured=True``);
    ``adapters`` / ``manifests`` — сырые списки либо None (не измерено).

    Потребитель ОБЯЗАН читать ``measured``: при False фильтр «это уже наше»
    ненадёжен, и уже охваченный протокол может приехать как новый кандидат.
    """
    adapters = _read_active_adapters_from_init(init_path)
    manifests = _read_manifest_protocols(manifests_dir)

    reasons: list[str] = []
    if adapters is None:
        reasons.append("активные адаптеры не измерены")
    if manifests is None:
        reasons.append("манифесты не измерены")

    ids = sorted({_normalise(i) for i in (adapters or []) + (manifests or []) if str(i).strip()})
    return {
        "ids": ids,
        "measured": not reasons,
        "reason": " · ".join(reasons),
        "adapters": adapters,
        "manifests": manifests,
        "adapters_count": None if adapters is None else len(adapters),
        "manifests_count": None if manifests is None else len(manifests),
    }


def _existing_protocol_ids() -> list[str]:
    """Combined list of protocol ids already covered (adapters + manifests).

    Совместимая обёртка: отдаёт только имена. Кто должен знать, ИЗМЕРЕНО ли
    множество, обязан звать :func:`known_protocols` — иначе «не смогли
    посмотреть» снова станет неотличимо от «ничего нет».
    """
    return known_protocols()["ids"]


# ─── Core public functions ────────────────────────────────────────────────────


def fetch_defi_candidates(data_dir: Path) -> list[dict]:
    """Read candidate_registry.json and return candidates not yet in active adapters.

    Reads from:
      - data/candidate_registry.json → candidates from discovery
      - spa_core/adapters/__init__.py + spa_core/adapter_sdk/manifests/ → known

    Returns list of candidate dicts still NOT in active adapters.
    Fail-safe: missing files → empty list.
    """
    data_dir = Path(data_dir)
    doc = _read_json(data_dir / "candidate_registry.json", {})
    if isinstance(doc, dict):
        candidates = doc.get("candidates") or []
    elif isinstance(doc, list):
        candidates = doc
    else:
        candidates = []

    raw: list[dict] = [c for c in candidates if isinstance(c, dict)]
    return raw


def filter_new_protocols(candidates: list[dict], existing_adapters: list[str]) -> list[dict]:
    """Remove candidates already covered by active adapters or manifests.

    Deduplication uses normalised protocol_id and name comparison.
    existing_adapters: list of normalised protocol id strings.

    Returns only NEW candidates not matching any existing adapter/manifest.
    """
    normed_existing = {_normalise(p) for p in existing_adapters}
    result: list[dict] = []
    for c in candidates:
        pid = str(c.get("protocol") or c.get("protocol_id") or "")
        name = str(c.get("name") or c.get("protocol") or "")
        pid_n = _normalise(pid)
        name_n = _normalise(name)
        # Match if normalised id or name is a substring of any existing (or vice versa)
        already = False
        for ex in normed_existing:
            if pid_n and (pid_n in ex or ex in pid_n):
                already = True
                break
            if name_n and (name_n in ex or ex in name_n):
                already = True
                break
        if not already:
            result.append(c)
    return result


def _compute_security_score(protocol: dict) -> int:
    """Deterministic security score 0–100.

    Formula:
      audit_count * 20  (capped at 60)
      age_days / 365 * 20  (capped at 20)
      open_source → +10
      bug_bounty  → +10
    """
    audit_count = int(protocol.get("audit_count") or 0)
    audit_score = min(audit_count * _AUDIT_SCORE_PER_AUDIT, _AUDIT_SCORE_CAP)

    age_days = 0
    if protocol.get("age_days") is not None:
        try:
            age_days = int(float(protocol["age_days"]))
        except (TypeError, ValueError):
            age_days = 0
    age_score = min(int(age_days / 365.0 * _AGE_SCORE_CAP), _AGE_SCORE_CAP)

    open_source_bonus = _OPEN_SOURCE_BONUS if protocol.get("open_source") else 0
    bug_bounty_bonus = _BUG_BOUNTY_BONUS if protocol.get("bug_bounty") else 0

    total = audit_score + age_score + open_source_bonus + bug_bounty_bonus
    return max(0, min(100, total))


def _compute_risk_flags(protocol: dict, security_score: int) -> list[str]:
    """Derive risk_flags from protocol properties."""
    flags: list[str] = []
    audit_count = int(protocol.get("audit_count") or 0)
    if audit_count == 0:
        flags.append("unaudited")
    tvl = float(protocol.get("tvl_usd") or 0.0)
    if tvl < _TVL_VALID:
        flags.append("low_tvl")
    age_days = 0
    if protocol.get("age_days") is not None:
        try:
            age_days = int(float(protocol["age_days"]))
        except (TypeError, ValueError):
            age_days = 0
    if age_days < 180:
        flags.append("new_protocol")
    if not protocol.get("bug_bounty"):
        flags.append("no_bug_bounty")
    exit_h = protocol.get("exit_latency_hours")
    if exit_h is not None:
        try:
            if float(exit_h) > 72:
                flags.append("high_exit_latency")
        except (TypeError, ValueError):
            pass
    return flags


def _suggested_tier(security_score: int, tvl_usd: float) -> str:
    """Determine suggested tier from security score and TVL."""
    if security_score >= _SCORE_T1 and tvl_usd >= _TVL_T1:
        return "T1"
    if security_score >= _SCORE_T2 and tvl_usd >= _TVL_T2:
        return "T2"
    return "T3"


def _deterministic_notes(protocol: dict, security_score: int, tier: str) -> str:
    """Build deterministic research notes string."""
    name = str(protocol.get("name") or protocol.get("protocol") or protocol.get("protocol_id") or "?")
    tvl = float(protocol.get("tvl_usd") or 0.0)
    tvl_m = tvl / 1_000_000.0
    audit_count = int(protocol.get("audit_count") or 0)
    return (
        f"Protocol {name}. "
        f"Security: {security_score}/100. "
        f"TVL: ${tvl_m:.1f}M. "
        f"Tier: {tier}. "
        f"Audits: {audit_count}."
    )


def _recommendation(security_score: int, risk_flags: list[str]) -> str:
    """Recommendation string based on score and flags."""
    blocking_flags = {"unaudited", "low_tvl"}
    has_blocking = bool(set(risk_flags) & blocking_flags)
    if security_score >= _SCORE_T2 and not has_blocking:
        return "add_to_whitelist_candidate"
    if security_score >= 30 and not has_blocking:
        return "monitor"
    return "skip"


def research_protocol(protocol: dict, research_fn: Optional[Callable[[dict], str]] = None) -> dict:
    """Deterministic deep-research of a single protocol candidate.

    Parameters
    ----------
    protocol    : raw candidate dict (from candidate_registry or manual).
    research_fn : optional callable(protocol_dict) → str for enhanced notes.
                  Degrade to deterministic template on error or None.

    Returns
    -------
    dict — research result with security_score, defi_llama_validated,
           suggested_tier, research_notes, risk_flags, recommendation,
           tvl_usd, apy_pct, protocol_id, name.
    """
    pid = str(protocol.get("protocol") or protocol.get("protocol_id") or "")
    name = str(protocol.get("name") or pid or "?")
    tvl_usd = float(protocol.get("tvl_usd") or 0.0)
    apy_pct = float(protocol.get("apy_pct") or 0.0)

    security_score = _compute_security_score(protocol)
    defi_llama_validated = tvl_usd >= _TVL_VALID
    tier = _suggested_tier(security_score, tvl_usd)
    risk_flags = _compute_risk_flags(protocol, security_score)
    recommendation = _recommendation(security_score, risk_flags)

    # Research notes: try research_fn, degrade on failure
    notes_str = _deterministic_notes(protocol, security_score, tier)
    if research_fn is not None:
        try:
            enhanced = str(research_fn(protocol))
            if enhanced:
                notes_str = enhanced
        except Exception as exc:
            log.warning("research_fn failed (%s) — using deterministic notes", exc)

    return {
        "protocol_id": pid,
        "name": name,
        "security_score": security_score,
        "defi_llama_validated": defi_llama_validated,
        "suggested_tier": tier,
        "research_notes": notes_str,
        "risk_flags": risk_flags,
        "recommendation": recommendation,
        "tvl_usd": tvl_usd,
        "apy_pct": apy_pct,
    }


def run_research_cycle(
    data_dir: Optional[Path] = None,
    research_fn: Optional[Callable[[dict], str]] = None,
) -> dict:
    """Main entry point — runs the weekly protocol research cycle.

    Steps:
      1. fetch_defi_candidates() from data/candidate_registry.json
      2. filter_new_protocols() against existing adapters + manifests
      3. research_protocol() for each candidate
      4. Sort by security_score desc (protocol_id for tie-breaking)
      5. Write data/protocol_research.json (atomic, top-10)
      6. Write data/protocol_research_status.json (atomic)

    Scheduled: weekday==0 (Monday), consistent with Alpha Agent.

    Returns
    -------
    dict — {researched_count, new_candidates, top_protocol, status}
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    now_ts = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        # Step 1: fetch candidates
        all_candidates = fetch_defi_candidates(ddir)

        # Step 2: filter out already-known protocols.
        # Множество известного берётся ВМЕСТЕ с честностью замера: если источник
        # не измерен, фильтр ненадёжен, и молчать об этом нельзя — уже охваченный
        # протокол приедет как «новый кандидат» (fail-OPEN, класс #274/#276).
        known = known_protocols()
        existing = known["ids"]
        if not known["measured"]:
            log.warning(
                "множество известных протоколов НЕ ИЗМЕРЕНО (%s) — фильтр «это уже наше» "
                "НЕНАДЁЖЕН: уже охваченный протокол может приехать как новый кандидат",
                known["reason"],
            )
        new_candidates = filter_new_protocols(all_candidates, existing)

        # Step 3: research each candidate
        researched: list[dict] = []
        for cand in new_candidates:
            try:
                result = research_protocol(cand, research_fn=research_fn)
                researched.append(result)
            except Exception as exc:
                pid = cand.get("protocol") or cand.get("protocol_id") or "?"
                log.warning("research_protocol failed for %s (%s) — skipped", pid, exc)

        # Step 4: sort by security_score desc, protocol_id for tie-break
        researched.sort(key=lambda r: (-r["security_score"], r["protocol_id"]))
        top = researched[:TOP_N]

        # Build output lists
        whitelist_candidates = [
            r["protocol_id"] for r in top if r["recommendation"] == "add_to_whitelist_candidate"
        ]
        monitor_list = [
            r["protocol_id"] for r in top if r["recommendation"] == "monitor"
        ]
        skip_list = [
            r["protocol_id"] for r in top if r["recommendation"] == "skip"
        ]
        top_protocol = top[0]["protocol_id"] if top else None

        # Step 5: write data/protocol_research.json (atomic)
        research_doc: dict = {
            "generated_at": now_ts,
            "cycle_date": today,
            "researched_count": len(researched),
            "protocols": top,
            "add_to_whitelist_candidates": whitelist_candidates,
            "monitor_list": monitor_list,
            "skip_list": skip_list,
        }
        try:
            _atomic_write_json(ddir / RESEARCH_FILENAME, research_doc)
        except Exception as exc:
            log.warning("protocol_research.json write failed (%s)", exc)

        # Step 6: write data/protocol_research_status.json (atomic)
        status_doc: dict = {
            "generated_at": now_ts,
            "cycle_date": today,
            "status": "ok",
            "researched_count": len(researched),
            "new_candidates_found": len(new_candidates),
            "top_protocol": top_protocol,
            "whitelist_candidates_count": len(whitelist_candidates),
            "existing_adapters_skipped": len(existing),
            "total_candidates_in_registry": len(all_candidates),
            # Честность замера множества известного — машинно, не только в логе:
            # measured=False означает «фильтру верить нельзя», а не «всё чисто».
            "known_set": {
                "measured": known["measured"],
                "reason": known["reason"],
                "adapters_count": known["adapters_count"],
                "manifests_count": known["manifests_count"],
                "total": len(existing),
            },
        }
        try:
            _atomic_write_json(ddir / RESEARCH_STATUS_FILENAME, status_doc)
        except Exception as exc:
            log.warning("protocol_research_status.json write failed (%s)", exc)

        log.info(
            "Protocol research cycle: %d new candidates researched, top=%s",
            len(researched),
            top_protocol,
        )
        return {
            "researched_count": len(researched),
            "new_candidates": len(new_candidates),
            "top_protocol": top_protocol,
            "status": "ok",
        }

    except Exception as exc:  # cycle must never raise
        log.warning("run_research_cycle failed (%s) — returning error status", exc)
        err_status: dict = {
            "generated_at": now_ts,
            "cycle_date": today,
            "status": f"error: {type(exc).__name__}: {exc}",
            "researched_count": 0,
            "new_candidates_found": 0,
            "top_protocol": None,
        }
        try:
            _atomic_write_json(ddir / RESEARCH_STATUS_FILENAME, err_status)
        except Exception:
            pass
        return {
            "researched_count": 0,
            "new_candidates": 0,
            "top_protocol": None,
            "status": f"error: {type(exc).__name__}: {exc}",
        }
