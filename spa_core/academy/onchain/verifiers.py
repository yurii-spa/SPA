"""
spa_core/academy/onchain/verifiers.py

On-chain practice verifiers for Academy modules M0–M8.

INVARIANTS (do NOT weaken):
  - Deterministic, read-only, NO private keys, NO state-changing RPC.
  - fail-CLOSED: any RPC outage → VerifyResult(status="unavailable"); a
    verifier NEVER returns "verified" when it could not actually read the chain.
  - A tx counts ONLY if the block that mined it is strictly newer than the
    lesson's ``started_at`` (block.timestamp > started_at, both UTC-Unix) — this
    stops a user replaying an old, pre-course transaction as fresh proof.
  - used_tx_hashes (PK tx_hash+chain) prevents cross-user / cross-lesson replay.
  - address comparisons are always lower-cased; log topics are bytes32-padded.
  - LLM FORBIDDEN in this module.

Academy stage 6 (M0–M3); stage 7 (M4–M8 + gas accumulator).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from spa_core.academy.onchain import rpc
from spa_core.academy.onchain.constants import (
    AAVE_POOL_BASE,
    CHAIN_BASE,
    CHAIN_BASE_SEPOLIA,
    TOPIC_APPROVAL,
    TOPIC_SUPPLY,
    TOPIC_TRANSFER,
    TOPIC_WITHDRAW,
    USDC_BASE,
)

# Confirmations required before a tx is accepted as final proof.
MIN_CONFIRMATIONS = 5
# Advisory soft-cap: the course wallet limit is $150. A transfer above this is
# still accepted (verified) but flagged so the UI can warn — never a hard reject.
ADVISORY_USDC_CAP = 150_000_000  # 150 USDC at 6 decimals
# Fixed ETH→USD rate for gas cost estimates. Deliberately NOT a live API call:
# the gas figure is an educational "what you spent" estimate, not an execution
# input, so a deterministic constant keeps verifiers pure and offline-testable.
GAS_USD_RATE = 2500.0
# Human map from chain id to the DB's ``chain`` column value.
_CHAIN_NAME = {CHAIN_BASE: "base", CHAIN_BASE_SEPOLIA: "base_sepolia"}


@dataclass
class VerifyResult:
    status: str  # "verified" | "failed" | "unavailable" | "pending"
    message: str  # user-facing, Russian
    evidence: dict = field(default_factory=dict)


# ── small helpers ────────────────────────────────────────────────────────────


def is_tx_hash(value: str) -> bool:
    """True iff *value* is a 0x-prefixed 32-byte (64 hex char) hash."""
    if not isinstance(value, str):
        return False
    v = value.strip()
    if not v.startswith("0x") or len(v) != 66:
        return False
    try:
        int(v, 16)
    except ValueError:
        return False
    return True


def _topic_for_address(address: str) -> str:
    """Left-pad a 20-byte address into a 32-byte log topic (lower-cased)."""
    a = address.strip().lower()
    if a.startswith("0x"):
        a = a[2:]
    return "0x" + ("0" * (64 - len(a))) + a


def _hexint(value) -> Optional[int]:
    """Parse a 0x-hex (or int) into int; None on failure."""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 16)
        except ValueError:
            return None
    return None


def _started_at_unix(started_at_iso: Optional[str]) -> Optional[int]:
    """Parse an ISO / SQLite-datetime string into a UTC Unix timestamp.

    Accepts both ``2026-07-04T12:00:00Z`` and SQLite's ``2026-07-04 12:00:00``
    (naive → treated as UTC). Returns None if unparseable.
    """
    if not started_at_iso:
        return None
    raw = str(started_at_iso).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    raw = raw.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.astimezone(timezone.utc).timestamp())


def _tx_already_used(db, tx_hash: str, chain_name: str) -> bool:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM used_tx_hashes WHERE tx_hash = ? AND chain = ?",
            (tx_hash, chain_name),
        ).fetchone()
    return row is not None


def _record_tx(db, tx_hash: str, chain_name: str, user_id: int, lesson_id: int) -> bool:
    """Insert into used_tx_hashes. Returns False if it was already recorded
    (replay lost the race), True on a fresh insert."""
    try:
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO used_tx_hashes(tx_hash, chain, user_id, lesson_id) "
                "VALUES (?, ?, ?, ?)",
                (tx_hash, chain_name, user_id, lesson_id),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def _verified_wallet(db, user_id: int, chain_name: str) -> Optional[str]:
    """Return one verified wallet address (checksummed) for the user, or None."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT address FROM wallets "
            "WHERE user_id = ? AND chain = ? AND verified_at IS NOT NULL "
            "ORDER BY id LIMIT 1",
            (user_id, chain_name),
        ).fetchone()
    return row["address"] if row else None


def _receipt_common(chain: int, tx_hash: str, started_unix: Optional[int]):
    """Shared M0/M3 checks: receipt success, confirmations, freshness.

    Returns (receipt, block, VerifyResult|None). If the third element is not
    None it is a terminal result (failed/unavailable) the caller should return.
    """
    try:
        receipt = rpc.eth_get_transaction_receipt(chain, tx_hash)
        if receipt is None:
            return None, None, VerifyResult(
                "failed", "Транзакция не найдена в сети (ещё не подтверждена?).", {"tx_hash": tx_hash}
            )
        if receipt.get("status") != "0x1":
            return receipt, None, VerifyResult(
                "failed", "Транзакция завершилась ошибкой (reverted).", {"tx_hash": tx_hash}
            )
        block_number = _hexint(receipt.get("blockNumber"))
        if block_number is None:
            return receipt, None, VerifyResult(
                "failed", "Транзакция ещё не включена в блок.", {"tx_hash": tx_hash}
            )
        latest = rpc.eth_block_number(chain)
        confirmations = latest - block_number
        if confirmations < MIN_CONFIRMATIONS:
            return receipt, None, VerifyResult(
                "failed",
                f"Недостаточно подтверждений: {max(confirmations, 0)}/{MIN_CONFIRMATIONS}. "
                "Подождите несколько блоков и попробуйте снова.",
                {"tx_hash": tx_hash},
            )
        block = rpc.eth_get_block_by_number(chain, block_number)
        if block is None:
            return receipt, None, VerifyResult(
                "unavailable", "Сеть временно недоступна. Попробуйте позже.", {"tx_hash": tx_hash}
            )
        block_ts = _hexint(block.get("timestamp"))
        if started_unix is not None and block_ts is not None and block_ts <= started_unix:
            return receipt, block, VerifyResult(
                "failed",
                "Эта транзакция была совершена до начала урока — нужна новая. "
                "Отправьте свежую транзакцию и проверьте её.",
                {"tx_hash": tx_hash},
            )
        return receipt, block, None
    except rpc.RPCError:
        return None, None, VerifyResult(
            "unavailable", "Сеть временно недоступна. Попробуйте позже.", {"tx_hash": tx_hash}
        )


# ── log / value / gas helpers (M4–M8) ────────────────────────────────────────


def _find_log(receipt, address, topic0, topic1=None, topic2=None, topic3=None):
    """Return the first receipt log matching *address* + the given topics.

    Any of ``topic1..topic3`` left as None is treated as a wildcard. All
    comparisons are lower-cased. Returns the raw log dict, or None.
    """
    addr = address.strip().lower()
    t0 = topic0.strip().lower()
    wants = [topic1, topic2, topic3]
    for lg in receipt.get("logs") or []:
        if (lg.get("address") or "").lower() != addr:
            continue
        topics = [str(t).lower() for t in (lg.get("topics") or [])]
        if not topics or topics[0] != t0:
            continue
        ok = True
        for i, want in enumerate(wants, start=1):
            if want is None:
                continue
            if len(topics) <= i or topics[i] != want.strip().lower():
                ok = False
                break
        if ok:
            return lg
    return None


def _log_value_uint(data) -> int:
    """Decode a single-uint256 log ``data`` field to int. ``0x`` / empty → 0."""
    if data is None:
        return 0
    s = str(data).strip().lower()
    if s in ("", "0x", "0x0"):
        return 0
    value = _hexint(s)
    return value if value is not None else 0


def _decode_supply_amount(data) -> int:
    """Decode the ``amount`` from an Aave v3 Supply log's non-indexed data.

    Supply's non-indexed args are ``(address user, uint256 amount)`` → the data
    blob is 2×32 bytes; ``amount`` is the second word. Falls back to decoding the
    whole blob as one uint if it is a single word.
    """
    if data is None:
        return 0
    h = str(data).strip().lower()
    if h.startswith("0x"):
        h = h[2:]
    if len(h) >= 128:
        try:
            return int(h[64:128], 16)
        except ValueError:
            return 0
    if h:
        try:
            return int(h, 16)
        except ValueError:
            return 0
    return 0


def _compute_gas_wei(chain: int, receipt: dict, tx_hash: str) -> int:
    """gasUsed × effectiveGasPrice (wei). Falls back to the tx's gasPrice."""
    gas_used = _hexint(receipt.get("gasUsed"))
    price = _hexint(receipt.get("effectiveGasPrice"))
    if price is None:
        try:
            tx = rpc.eth_get_transaction_by_hash(chain, tx_hash)
        except rpc.RPCError:
            tx = None
        if tx:
            price = _hexint(tx.get("gasPrice"))
    if gas_used is None or price is None:
        return 0
    return gas_used * price


def _progress_row(db, user_id: int, lesson_id: int):
    """Return the (status, evidence_json) progress row, or None."""
    with db.connect() as conn:
        return conn.execute(
            "SELECT status, evidence_json FROM progress "
            "WHERE user_id = ? AND lesson_id = ?",
            (user_id, lesson_id),
        ).fetchone()


def _verified_evidence(db, user_id: int, lesson_id: int) -> Optional[dict]:
    """Return the parsed evidence for a *verified* lesson, else None."""
    row = _progress_row(db, user_id, lesson_id)
    if row is None or row["status"] != "verified" or not row["evidence_json"]:
        return None
    try:
        return json.loads(row["evidence_json"])
    except (ValueError, TypeError):
        return None


def get_gas_summary(db, user_id) -> dict:
    """Sum ``gas_wei`` across every verified lesson's evidence for *user_id*.

    Returns ``{total_gas_wei, total_gas_eth, total_gas_usd_est}``. Missing /
    malformed evidence is skipped (never raises). Used by M8 and the certificate.
    """
    total = 0
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT evidence_json FROM progress "
            "WHERE user_id = ? AND status = 'verified'",
            (user_id,),
        ).fetchall()
    for r in rows:
        raw = r["evidence_json"]
        if not raw:
            continue
        try:
            ev = json.loads(raw)
        except (ValueError, TypeError):
            continue
        g = ev.get("gas_wei")
        if isinstance(g, bool):
            continue
        if isinstance(g, int):
            total += g
        elif isinstance(g, str):
            try:
                total += int(g)
            except ValueError:
                pass
    eth = total / 1e18
    return {
        "total_gas_wei": total,
        "total_gas_eth": round(eth, 8),
        "total_gas_usd_est": round(eth * GAS_USD_RATE, 4),
    }


# ── M0 — testnet tx on Base Sepolia ──────────────────────────────────────────


def verify_m0(db, user_id, lesson_id, tx_hash, started_at_iso) -> VerifyResult:
    """M0: a successful, confirmed, fresh tx on Base Sepolia."""
    if not is_tx_hash(tx_hash):
        return VerifyResult("failed", "Некорректный формат tx hash (нужно 0x + 64 hex).", {})
    tx_hash = tx_hash.strip().lower()
    chain_name = _CHAIN_NAME[CHAIN_BASE_SEPOLIA]
    if _tx_already_used(db, tx_hash, chain_name):
        return VerifyResult("failed", "Этот tx hash уже был засчитан ранее.", {"tx_hash": tx_hash})

    started_unix = _started_at_unix(started_at_iso)
    receipt, block, terminal = _receipt_common(CHAIN_BASE_SEPOLIA, tx_hash, started_unix)
    if terminal is not None:
        return terminal

    if not _record_tx(db, tx_hash, chain_name, user_id, lesson_id):
        return VerifyResult("failed", "Этот tx hash уже был засчитан ранее.", {"tx_hash": tx_hash})

    evidence = {
        "tx_hash": tx_hash,
        "chain": "base_sepolia",
        "block": _hexint(receipt.get("blockNumber")),
        "kind": "onchain_tx",
    }
    return VerifyResult("verified", "Тестовая транзакция подтверждена. Отличный первый шаг!", evidence)


# ── M1 — SIWE wallet binding was completed ───────────────────────────────────


def verify_m1(db, user_id, lesson_id, siwe_verified: bool = True) -> VerifyResult:
    """M1: the user has a verified wallet binding (SIWE completed)."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT address, chain FROM wallets "
            "WHERE user_id = ? AND verified_at IS NOT NULL "
            "AND chain IN ('base','base_sepolia') ORDER BY id LIMIT 1",
            (user_id,),
        ).fetchone()
    if row is None:
        return VerifyResult(
            "failed",
            "Кошелёк ещё не привязан. Пройдите вход через SIWE-подпись в модуле кошелька.",
            {},
        )
    return VerifyResult(
        "verified",
        "Владение кошельком подтверждено подписью — без движения средств.",
        {"kind": "siwe", "chain": row["chain"]},
    )


# ── M2 — non-zero ETH balance on Base ────────────────────────────────────────


def verify_m2(db, user_id, lesson_id, started_at_iso=None) -> VerifyResult:
    """M2: the user's verified Base wallet holds some ETH for gas."""
    address = _verified_wallet(db, user_id, "base")
    if address is None:
        return VerifyResult(
            "failed", "Сначала привяжите кошелёк на сети Base (модуль кошелька).", {}
        )
    try:
        balance = rpc.eth_get_balance(CHAIN_BASE, address)
    except rpc.RPCError:
        return VerifyResult("unavailable", "Сеть временно недоступна. Попробуйте позже.", {})
    if balance <= 0:
        return VerifyResult(
            "failed",
            "На кошельке нет ETH на газ. Заведите небольшую сумму (в пределах лимита) и повторите.",
            {},
        )
    return VerifyResult(
        "verified",
        "На кошельке есть ETH на газ — можно оплачивать транзакции на Base.",
        {"kind": "balance", "chain": "base", "wei": str(balance)},
    )


# ── M3 — outgoing USDC transfer on Base ──────────────────────────────────────


def verify_m3(db, user_id, lesson_id, tx_hash, started_at_iso) -> VerifyResult:
    """M3: a fresh, confirmed outgoing USDC Transfer FROM the user's Base wallet."""
    if not is_tx_hash(tx_hash):
        return VerifyResult("failed", "Некорректный формат tx hash (нужно 0x + 64 hex).", {})
    tx_hash = tx_hash.strip().lower()
    chain_name = _CHAIN_NAME[CHAIN_BASE]

    address = _verified_wallet(db, user_id, "base")
    if address is None:
        return VerifyResult(
            "failed", "Сначала привяжите кошелёк на сети Base (модуль кошелька).", {}
        )
    if _tx_already_used(db, tx_hash, chain_name):
        return VerifyResult("failed", "Этот tx hash уже был засчитан ранее.", {"tx_hash": tx_hash})

    started_unix = _started_at_unix(started_at_iso)
    receipt, block, terminal = _receipt_common(CHAIN_BASE, tx_hash, started_unix)
    if terminal is not None:
        return terminal

    from_topic = _topic_for_address(address)
    usdc = USDC_BASE.lower()
    logs = receipt.get("logs") or []
    matched = None
    for lg in logs:
        if (lg.get("address") or "").lower() != usdc:
            continue
        topics = [str(t).lower() for t in (lg.get("topics") or [])]
        if len(topics) < 3:
            continue
        if topics[0] != TOPIC_TRANSFER.lower():
            continue
        if topics[1] != from_topic:
            continue
        matched = lg
        break

    if matched is None:
        return VerifyResult(
            "failed",
            "В транзакции нет исходящего перевода USDC с вашего адреса. "
            "Убедитесь, что отправляли USDC на Base со своего привязанного кошелька.",
            {"tx_hash": tx_hash},
        )

    amount_raw = _hexint(matched.get("data")) or 0
    to_topic = matched.get("topics", [None, None, None])[2]
    to_addr = "0x" + str(to_topic)[-40:] if to_topic else None

    if not _record_tx(db, tx_hash, chain_name, user_id, lesson_id):
        return VerifyResult("failed", "Этот tx hash уже был засчитан ранее.", {"tx_hash": tx_hash})

    evidence = {
        "tx_hash": tx_hash,
        "chain": "base",
        "from": address.lower(),
        "to": to_addr,
        "amount_usdc": round(amount_raw / 1_000_000, 6),
        "block": _hexint(receipt.get("blockNumber")),
        "kind": "usdc_transfer",
    }
    message = "Перевод USDC на Base подтверждён — доказательство в explorer по tx hash."
    if amount_raw > ADVISORY_USDC_CAP:
        message += (
            " ⚠️ Сумма превышает учебный лимит $150 — засчитано, но впредь "
            "держитесь в пределах лимита."
        )
        evidence["advisory_over_limit"] = True
    return VerifyResult("verified", message, evidence)


# ── M4 — USDC approve + revoke to the Aave Pool on Base ──────────────────────


def verify_m4(db, user_id, lesson_id, approve_tx, revoke_tx, started_at_iso) -> VerifyResult:
    """M4: a bounded USDC approval to the Aave Pool, then its revoke (→ 0).

    Both txs must be fresh, confirmed, distinct and unused. The approve carries a
    non-zero Approval(owner=user, spender=Pool) log; the revoke carries the same
    log with value 0, in a strictly later block.
    """
    if not is_tx_hash(approve_tx) or not is_tx_hash(revoke_tx):
        return VerifyResult("failed", "Некорректный формат tx hash (нужно 0x + 64 hex).", {})
    approve_tx = approve_tx.strip().lower()
    revoke_tx = revoke_tx.strip().lower()
    if approve_tx == revoke_tx:
        return VerifyResult(
            "failed", "approve и revoke должны быть разными транзакциями.", {}
        )

    address = _verified_wallet(db, user_id, "base")
    if address is None:
        return VerifyResult(
            "failed", "Сначала привяжите кошелёк на сети Base (модуль кошелька).", {}
        )
    chain_name = _CHAIN_NAME[CHAIN_BASE]
    if _tx_already_used(db, approve_tx, chain_name) or _tx_already_used(db, revoke_tx, chain_name):
        return VerifyResult("failed", "Один из tx hash уже был засчитан ранее.", {})

    started_unix = _started_at_unix(started_at_iso)
    owner_topic = _topic_for_address(address)
    spender_topic = _topic_for_address(AAVE_POOL_BASE)
    usdc = USDC_BASE

    # --- approve leg ---
    receipt_a, block_a, terminal = _receipt_common(CHAIN_BASE, approve_tx, started_unix)
    if terminal is not None:
        return terminal
    approve_log = _find_log(receipt_a, usdc, TOPIC_APPROVAL, owner_topic, spender_topic)
    if approve_log is None or _log_value_uint(approve_log.get("data")) <= 0:
        return VerifyResult(
            "failed",
            "В approve-транзакции нет разрешения USDC для контракта Aave с "
            "ненулевым лимитом. Одобрите конкретную сумму на Aave Pool.",
            {"approve_tx": approve_tx},
        )
    block_approve = _hexint(receipt_a.get("blockNumber"))

    # --- revoke leg ---
    receipt_r, block_r, terminal = _receipt_common(CHAIN_BASE, revoke_tx, started_unix)
    if terminal is not None:
        return terminal
    revoke_log = _find_log(receipt_r, usdc, TOPIC_APPROVAL, owner_topic, spender_topic)
    if revoke_log is None or _log_value_uint(revoke_log.get("data")) != 0:
        return VerifyResult(
            "failed",
            "В revoke-транзакции нет отзыва разрешения (approval со значением 0) "
            "для Aave Pool. Отзовите ранее выданный approval.",
            {"revoke_tx": revoke_tx},
        )
    block_revoke = _hexint(receipt_r.get("blockNumber"))

    if block_approve is None or block_revoke is None or block_revoke <= block_approve:
        return VerifyResult(
            "failed",
            "revoke должен быть после approve (в более позднем блоке). "
            "Сначала выдайте approval, затем отдельной транзакцией отзовите его.",
            {"approve_tx": approve_tx, "revoke_tx": revoke_tx},
        )

    if not _record_tx(db, approve_tx, chain_name, user_id, lesson_id) or not _record_tx(
        db, revoke_tx, chain_name, user_id, lesson_id
    ):
        return VerifyResult("failed", "Один из tx hash уже был засчитан ранее.", {})

    evidence = {
        "approve_tx": approve_tx,
        "revoke_tx": revoke_tx,
        "chain": "base",
        "block_approve": block_approve,
        "block_revoke": block_revoke,
        "kind": "approve_revoke",
    }
    return VerifyResult(
        "verified",
        "Approval выдан и затем отозван — вы управляете разрешениями осознанно. "
        "Именно так минимизируют риск: доступ ровно на время нужды.",
        evidence,
    )


# ── M5 — Supply USDC into Aave v3 on Base ────────────────────────────────────


def verify_m5(db, user_id, lesson_id, tx_hash, started_at_iso) -> VerifyResult:
    """M5: a fresh Aave v3 ``Supply`` of USDC on behalf of the user's wallet.

    Counts by the Pool's ``Supply`` event (reserve=USDC, onBehalfOf=user), NOT by
    an aToken balance read (owner-approved). Amount over $150 → advisory, not a
    reject.
    """
    if not is_tx_hash(tx_hash):
        return VerifyResult("failed", "Некорректный формат tx hash (нужно 0x + 64 hex).", {})
    tx_hash = tx_hash.strip().lower()
    chain_name = _CHAIN_NAME[CHAIN_BASE]

    address = _verified_wallet(db, user_id, "base")
    if address is None:
        return VerifyResult(
            "failed", "Сначала привяжите кошелёк на сети Base (модуль кошелька).", {}
        )
    if _tx_already_used(db, tx_hash, chain_name):
        return VerifyResult("failed", "Этот tx hash уже был засчитан ранее.", {"tx_hash": tx_hash})

    started_unix = _started_at_unix(started_at_iso)
    receipt, block, terminal = _receipt_common(CHAIN_BASE, tx_hash, started_unix)
    if terminal is not None:
        return terminal

    reserve_topic = _topic_for_address(USDC_BASE)
    behalf_topic = _topic_for_address(address)
    supply_log = _find_log(receipt, AAVE_POOL_BASE, TOPIC_SUPPLY, reserve_topic, behalf_topic)
    if supply_log is None:
        return VerifyResult(
            "failed",
            "В транзакции нет депозита USDC в Aave на ваш адрес. Убедитесь, что "
            "выполнили Supply USDC в официальном контракте Aave на Base.",
            {"tx_hash": tx_hash},
        )

    amount_raw = _decode_supply_amount(supply_log.get("data"))
    block_ts = _hexint(block.get("timestamp")) if block else None

    if not _record_tx(db, tx_hash, chain_name, user_id, lesson_id):
        return VerifyResult("failed", "Этот tx hash уже был засчитан ранее.", {"tx_hash": tx_hash})

    evidence = {
        "tx_hash": tx_hash,
        "chain": "base",
        "address": AAVE_POOL_BASE.lower(),
        "amount_usdc": round(amount_raw / 1_000_000, 6),
        "block": _hexint(receipt.get("blockNumber")),
        "timestamp": block_ts,
        "kind": "aave_supply",
    }
    message = "Депозит USDC в Aave подтверждён — теперь позиция приносит доходность."
    if amount_raw > ADVISORY_USDC_CAP:
        message += (
            " ⚠️ Сумма превышает учебный лимит $150 — засчитано, но впредь "
            "держитесь в пределах лимита."
        )
        evidence["advisory_over_limit"] = True
    return VerifyResult("verified", message, evidence)


# ── M6 — Withdraw from Aave v3 on Base ───────────────────────────────────────


def verify_m6(db, user_id, lesson_id, tx_hash, started_at_iso) -> VerifyResult:
    """M6: a fresh Aave v3 ``Withdraw`` of USDC involving the user's wallet.

    Withdraw(reserve, user, to, amount) is fully indexed → the user may appear as
    ``user`` (topic2) OR ``to`` (topic3). Records gas spent for the accumulator.
    """
    if not is_tx_hash(tx_hash):
        return VerifyResult("failed", "Некорректный формат tx hash (нужно 0x + 64 hex).", {})
    tx_hash = tx_hash.strip().lower()
    chain_name = _CHAIN_NAME[CHAIN_BASE]

    address = _verified_wallet(db, user_id, "base")
    if address is None:
        return VerifyResult(
            "failed", "Сначала привяжите кошелёк на сети Base (модуль кошелька).", {}
        )
    if _tx_already_used(db, tx_hash, chain_name):
        return VerifyResult("failed", "Этот tx hash уже был засчитан ранее.", {"tx_hash": tx_hash})

    started_unix = _started_at_unix(started_at_iso)
    receipt, block, terminal = _receipt_common(CHAIN_BASE, tx_hash, started_unix)
    if terminal is not None:
        return terminal

    reserve_topic = _topic_for_address(USDC_BASE)
    user_topic = _topic_for_address(address)
    # user may be topic2 (user) or topic3 (to) — accept either.
    withdraw_log = _find_log(
        receipt, AAVE_POOL_BASE, TOPIC_WITHDRAW, reserve_topic, user_topic
    ) or _find_log(
        receipt, AAVE_POOL_BASE, TOPIC_WITHDRAW, reserve_topic, None, user_topic
    )
    if withdraw_log is None:
        return VerifyResult(
            "failed",
            "В транзакции нет вывода USDC из Aave на ваш адрес. Убедитесь, что "
            "выполнили Withdraw USDC из официального контракта Aave на Base.",
            {"tx_hash": tx_hash},
        )

    amount_raw = _log_value_uint(withdraw_log.get("data"))
    block_ts = _hexint(block.get("timestamp")) if block else None
    block_num = _hexint(receipt.get("blockNumber"))
    gas_wei = _compute_gas_wei(CHAIN_BASE, receipt, tx_hash)

    # Advisory ordering check against a prior verified M5 (not a reject).
    advisory_order = False
    m5_ev = _verified_evidence(db, user_id, 5)
    if m5_ev is not None:
        m5_block = m5_ev.get("block")
        if isinstance(m5_block, int) and isinstance(block_num, int) and block_num <= m5_block:
            advisory_order = True

    if not _record_tx(db, tx_hash, chain_name, user_id, lesson_id):
        return VerifyResult("failed", "Этот tx hash уже был засчитан ранее.", {"tx_hash": tx_hash})

    evidence = {
        "tx_hash": tx_hash,
        "chain": "base",
        "address": AAVE_POOL_BASE.lower(),
        "amount_usdc": round(amount_raw / 1_000_000, 6),
        "block": block_num,
        "timestamp": block_ts,
        "gas_wei": gas_wei,
        "kind": "aave_withdraw",
    }
    message = "Вывод из Aave подтверждён — депозит с процентами вернулся на кошелёк."
    if advisory_order:
        message += (
            " ⚠️ Похоже, вывод в том же/более раннем блоке, что и депозит — "
            "проверьте порядок действий."
        )
        evidence["advisory_order"] = True
    return VerifyResult("verified", message, evidence)


# ── M7 — incidents quiz (≥80%) ───────────────────────────────────────────────


def verify_m7(db, user_id, lesson_id) -> VerifyResult:
    """M7: best quiz score for lesson 7 is ≥80% (no on-chain component)."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT MAX(score) AS best, COUNT(*) AS n "
            "FROM quiz_results WHERE user_id = ? AND lesson_id = 7",
            (user_id,),
        ).fetchone()
    best = row["best"] if row else None
    attempts = row["n"] if row else 0
    if best is None:
        return VerifyResult(
            "failed",
            "Пройдите квиз с результатом ≥80%. Пока ни одной попытки не найдено.",
            {},
        )
    if best < 80:
        return VerifyResult(
            "failed",
            f"Пройдите квиз с результатом ≥80% (лучший результат — {round(best)}%).",
            {"best_score": best, "attempt_count": attempts},
        )
    return VerifyResult(
        "verified",
        "Квиз по инцидентам сдан — вы распознаёте фишинг и drainer-подписи.",
        {"best_score": best, "attempt_count": attempts},
    )


# ── M8 — capstone (fresh supply+withdraw after start + reflection) ───────────


def verify_m8(db, user_id, lesson_id, started_at_iso) -> VerifyResult:
    """M8: a full fresh cycle — Supply then Withdraw after the capstone started —
    plus a non-empty reflection note. Reports total gas spent across the course."""
    started_unix = _started_at_unix(started_at_iso)
    failures: list[str] = []

    m5_ev = _verified_evidence(db, user_id, 5)
    if m5_ev is None:
        failures.append("модуль M5 (Supply) ещё не пройден")
    else:
        m5_ts = m5_ev.get("timestamp")
        if started_unix is not None and isinstance(m5_ts, int) and m5_ts <= started_unix:
            failures.append("Supply нужно выполнить в рамках капстоуна (после его начала)")

    m6_ev = _verified_evidence(db, user_id, 6)
    if m6_ev is None:
        failures.append("модуль M6 (Withdraw) ещё не пройден")
    elif m5_ev is not None:
        m5_block = m5_ev.get("block")
        m6_block = m6_ev.get("block")
        if isinstance(m5_block, int) and isinstance(m6_block, int) and m6_block <= m5_block:
            failures.append("Withdraw должен быть в более позднем блоке, чем Supply")

    with db.connect() as conn:
        note_row = conn.execute(
            "SELECT text FROM notes WHERE user_id = ? AND lesson_id = 8",
            (user_id,),
        ).fetchone()
    note_text = (note_row["text"] if note_row and note_row["text"] else "").strip()
    if not note_text:
        failures.append("добавьте рефлексию в заметки этого модуля")

    if failures:
        return VerifyResult(
            "failed",
            "Капстоун ещё не завершён: " + "; ".join(failures) + ".",
            {},
        )

    gas = get_gas_summary(db, user_id)
    evidence = {
        "m5_evidence": m5_ev,
        "m6_evidence": m6_ev,
        "notes_length": len(note_text),
        "gas_total_wei": gas["total_gas_wei"],
        "gas_total_usd_est": gas["total_gas_usd_est"],
        "kind": "capstone",
    }
    return VerifyResult(
        "verified",
        "Капстоун пройден: полный цикл на Base выполнен и отрефлексирован. "
        f"Суммарный газ за курс ≈ ${gas['total_gas_usd_est']}. "
        "Вы владеете механикой и дисциплиной — именно этого и добивался курс.",
        evidence,
    )
