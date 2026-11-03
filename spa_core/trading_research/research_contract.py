"""Контракт исследования — одна форма записи для ДВУХ отдельных движков (STUDIO-AUTONOMY-01 S3, E6.1).

Движки: ``spa_trading_research`` (этот пакет; ledgers ``market.db`` + ``evidence.db``) и ``earn_defi``
(отдельный репозиторий; ledger ``earn_defi.db`` с hash-chain таблицами и ``config_versions``). Общего ledger
нет и не создаётся: контракт — неизменяемый JSON в git, который ССЫЛАЕТСЯ на записи ledgers своего движка
по id и хешу. Время регистрации — заявленное ``registered_at`` И коммит, внёсший файл (``git log``); результат
не может предшествовать регистрации. Investment Engine не является движком контракта и отвергается.

Попытки считаются в отдельном append-only журнале рядом с контрактом (``<id>.attempts.jsonl`` в git): так их
видит любая следующая сессия, а бюджет проверяется ДО прогона (``spend_attempt`` отказывает сверх бюджета).

Проверки (три исхода, инв. #17): ``validate`` — форма (список ошибок, пустой = годен); ``check_ledgers`` —
ссылки против снимка ledgers, только чтение: ``OK`` · ``MISMATCH`` (ссылка указывает не на то) ·
``INCOMPLETE`` (снимка или записи нет)."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

ENGINES = ("spa_trading_research", "earn_defi")
REQUIRED = ("contract_id", "engine", "hypothesis", "scope", "strategy", "data_source", "cost_model",
            "attempt_budget", "criteria", "registered_at", "ledger_refs")
SCOPE_KEYS = ("universe", "periods")
PERIOD_KEYS = ("train", "oos", "forward_from")
OK, MISMATCH, INCOMPLETE = "OK", "MISMATCH", "INCOMPLETE"


class AttemptBudgetExceeded(RuntimeError):
    """Новая попытка сверх объявленного бюджета — отказ, а не тихое продолжение."""


def contract_hash(contract: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(contract, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _iso(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def validate(c: Mapping[str, Any]) -> List[str]:
    errs = [f"нет поля {k}" for k in REQUIRED if c.get(k) in (None, "", [], {})]
    if errs:
        return errs
    if c["engine"] not in ENGINES:
        errs.append(f"движок {c['engine']!r} не из {ENGINES} (Investment Engine контракту не принадлежит)")
    if not isinstance(c["attempt_budget"], int) or c["attempt_budget"] < 1:
        errs.append("attempt_budget — целое ≥ 1")
    if _iso(c["registered_at"]) is None:
        errs.append("registered_at — не ISO-время")
    scope = c["scope"]
    errs += [f"scope: нет {k}" for k in SCOPE_KEYS if not scope.get(k)]
    per = scope.get("periods") or {}
    errs += [f"scope.periods: нет {k}" for k in PERIOD_KEYS if not per.get(k)]
    reg, fwd = _iso(c["registered_at"]), _iso(per.get("forward_from"))
    if reg is not None and fwd is not None and fwd < reg:
        errs.append("forward_from раньше регистрации — forward обязан начинаться ПОСЛЕ неё")
    configs = c["strategy"].get("configs") or []
    if not 1 <= len(configs) <= 6:
        errs.append("strategy.configs: от 1 до 6 конфигураций")
    controls = [x for x in configs if x.get("role") == "control"]
    if len(controls) != 1:
        errs.append("strategy.configs: ровно один неизменный контроль (role=control)")
    refs = c["ledger_refs"]
    if c["engine"] == "spa_trading_research" and not refs.get("candidates"):
        errs.append("ledger_refs.candidates: id+def_hash кандидатов в evidence.db")
    if c["engine"] == "earn_defi" and not refs.get("config_version"):
        errs.append("ledger_refs.config_version: версия конфига и её хеш в config_versions")
    return errs


def _ro(path: Path) -> sqlite3.Connection:
    from .read_model import open_ro   # одна дверь read-only (migrate_callsites)
    return open_ro(path)


def check_ledgers(c: Mapping[str, Any], ledgers: Mapping[str, Path]) -> Dict[str, Any]:
    """Сверить ссылки контракта с СНИМКОМ ledgers его движка (``{"evidence": путь}`` или ``{"db": путь}``)."""
    refs, out = c["ledger_refs"], {"engine": c["engine"], "checked": []}
    need = "evidence" if c["engine"] == "spa_trading_research" else "db"
    p = ledgers.get(need)
    if p is None or not Path(p).exists():
        return {**out, "status": INCOMPLETE, "why": f"снимка ledger {need!r} нет"}
    conn = _ro(Path(p))
    try:
        if c["engine"] == "spa_trading_research":
            for ref in refs["candidates"]:
                if ref.get("role") == "research_only":          # конфигурация, которой в forward-ledger нет по устройству
                    out["checked"].append({**ref, "status": "NOT_IN_LEDGER_BY_DESIGN"})
                    continue
                r = conn.execute("SELECT def_hash FROM candidates WHERE candidate_id=?", (ref["id"],)).fetchone()
                st = INCOMPLETE if r is None else (OK if r[0] == ref["def_hash"] else MISMATCH)
                out["checked"].append({**ref, "status": st, "ledger_def_hash": r[0] if r else None})
        else:
            v = refs["config_version"]
            r = conn.execute("SELECT config_hash FROM config_versions WHERE version=?", (v["version"],)).fetchone()
            st = INCOMPLETE if r is None else (OK if r[0] == v["hash"] else MISMATCH)
            out["checked"].append({**v, "status": st, "ledger_hash": r[0] if r else None})
    finally:
        conn.close()
    sts = {x["status"] for x in out["checked"]}
    if not sts & {OK, MISMATCH, INCOMPLETE}:          # все ссылки «вне ledger по устройству» — сверено НИЧЕГО
        return {**out, "status": INCOMPLETE, "why": "ни одной ссылки, которую можно сверить с ledger"}
    out["status"] = MISMATCH if MISMATCH in sts else INCOMPLETE if INCOMPLETE in sts else OK
    return out


def attempts_path(contract_path: Path) -> Path:
    return Path(contract_path).with_suffix(".attempts.jsonl")


def attempts(contract_path: Path) -> List[Dict[str, Any]]:
    p = attempts_path(contract_path)
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def spend_attempt(contract_path: Path, record: Mapping[str, Any]) -> int:
    """Записать попытку ДО прогона; сверх бюджета — ``AttemptBudgetExceeded``. Возвращает её номер (с 1)."""
    c = json.loads(Path(contract_path).read_text())
    done = attempts(contract_path)
    if len(done) >= c["attempt_budget"]:
        raise AttemptBudgetExceeded(f"{c['contract_id']}: попыток {len(done)} из {c['attempt_budget']} — бюджет исчерпан")
    n = len(done) + 1
    with attempts_path(contract_path).open("a", encoding="utf-8") as f:   # append-only журнал, не state-файл
        f.write(json.dumps({"n": n, "contract_hash": contract_hash(c), **record}, sort_keys=True,
                           ensure_ascii=False) + "\n")
    return n
