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

Academy stage 6.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from spa_core.academy.onchain import rpc
from spa_core.academy.onchain.constants import (
    CHAIN_BASE,
    CHAIN_BASE_SEPOLIA,
    TOPIC_TRANSFER,
    USDC_BASE,
)

# Confirmations required before a tx is accepted as final proof.
MIN_CONFIRMATIONS = 5
# Advisory soft-cap: the course wallet limit is $150. A transfer above this is
# still accepted (verified) but flagged so the UI can warn — never a hard reject.
ADVISORY_USDC_CAP = 150_000_000  # 150 USDC at 6 decimals
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


# ── M4–M8 — stubs (delivered in stage 7) ─────────────────────────────────────


def _pending() -> VerifyResult:
    return VerifyResult("pending", "Проверка этого модуля появится на этапе 7.", {})


def verify_m4(db, user_id, lesson_id, *args, **kwargs) -> VerifyResult:
    """M4 (approvals/revoke) — stub, coming in stage 7."""
    return _pending()


def verify_m5(db, user_id, lesson_id, *args, **kwargs) -> VerifyResult:
    """M5 (Aave supply) — stub, coming in stage 7."""
    return _pending()


def verify_m6(db, user_id, lesson_id, *args, **kwargs) -> VerifyResult:
    """M6 (Aave withdraw) — stub, coming in stage 7."""
    return _pending()


def verify_m7(db, user_id, lesson_id, *args, **kwargs) -> VerifyResult:
    """M7 (incidents quiz ≥80%) — stub, coming in stage 7."""
    return _pending()


def verify_m8(db, user_id, lesson_id, *args, **kwargs) -> VerifyResult:
    """M8 (capstone) — stub, coming in stage 7."""
    return _pending()
