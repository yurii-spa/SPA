"""
SafeTxBuilder — строит Safe Transaction Service proposals для Gnosis Safe 2-of-3.

ВАЖНО: Этот модуль ТОЛЬКО строит proposal-структуры (dict).
Он НЕ отправляет транзакции, НЕ подписывает, НЕ хранит ключи.
Фактическая отправка через Safe Transaction Service API — в отдельном клиенте.

Режимы:
  - paper (default): все методы — no-op, возвращают пустой dict.
    SPA_EXECUTION_MODE != 'live' → is_paper_mode() = True.
  - live: строит proposal dict для proposeTx() Safe Transaction Service.

LLM ЗАПРЕЩЁН в этом модуле (LLM_FORBIDDEN_AGENTS: execution).
Только stdlib. Никаких внешних зависимостей.
Никаких приватных ключей, seed-фраз, токенов в коде или логах.

Связанные ADR:
  ADR-022: Gnosis Safe 2-of-3 Family Fund Governance
  ADR-010: Gnosis Safe Key Management (Zodiac Roles)
  ADR-002: Go-Live Transfer Rule

Refs:
  Safe Transaction Service API: https://safe-transaction-mainnet.safe.global/
  Safe SDK: https://docs.safe.global/
"""

import os
import json
import hashlib
import logging
from typing import Optional

from spa_core.safety.safeguard import live_trading_forbidden
from spa_core.utils.errors import SPAError, ValidationError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

# Threshold для автоматической vs ручной подписи (ADR-022 §2.2)
SINGLE_SIG_THRESHOLD_USD = 1_000.0

# USDC contract address (Ethereum Mainnet)
USDC_MAINNET = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
USDC_DECIMALS = 6

# Safe Transaction Service base URLs
SAFE_TX_SERVICE_URLS = {
    1: "https://safe-transaction-mainnet.safe.global",       # Ethereum Mainnet
    11155111: "https://safe-transaction-sepolia.safe.global",  # Sepolia testnet
    5: "https://safe-transaction-goerli.safe.global",        # Goerli (legacy)
}

# Список протоколов в whitelist (только адреса protоколов — НЕ ключи)
# Реальные адреса заполняются при деплое или через конфиг.
# Здесь — заглушки для документирования намерений.
PROTOCOL_WHITELIST: dict[str, str] = {
    # adapter_name → protocol contract address (Ethereum Mainnet)
    "aave_v3":    "",  # Aave V3 Pool: заполнить при деплое
    "compound_v3": "",  # Compound V3 Comet USDC: заполнить при деплое
    "morpho_blue": "",  # Morpho Blue: заполнить при деплое
    "yearn_v3":   "",  # Yearn V3 USDC vault: заполнить при деплое
    "euler_v2":   "",  # Euler V2: заполнить при деплое
}

# ---------------------------------------------------------------------------
# ABI Function Selectors (pre-computed keccak256 — stdlib has no keccak)
# Source: Ethereum ABI spec + official protocol docs.
# ---------------------------------------------------------------------------

# Aave V3 Pool — supply(address asset, uint256 amount, address onBehalfOf, uint16 referralCode)
_SELECTOR_AAVE_SUPPLY   = "617ba037"
# Aave V3 Pool — withdraw(address asset, uint256 amount, address to)
_SELECTOR_AAVE_WITHDRAW = "69328dec"
# Compound V3 Comet — supply(address asset, uint256 amount)
_SELECTOR_COMP_SUPPLY   = "f2b9fdb8"
# Compound V3 Comet — withdraw(address asset, uint256 amount)
_SELECTOR_COMP_WITHDRAW = "f3fef3a3"
# ERC-4626 standard — deposit(uint256 assets, address receiver)
_SELECTOR_ERC4626_DEPOSIT  = "6e553f65"
# ERC-4626 standard — redeem(uint256 shares, address receiver, address owner)
_SELECTOR_ERC4626_REDEEM   = "ba087652"

# Gas estimation table (conservative mainnet estimates, units per operation).
# Real gas should be estimated via eth_estimateGas before go-live.
_GAS_ESTIMATES: dict[str, dict[str, int]] = {
    "aave_v3":    {"allocate": 300_000, "withdraw": 320_000},
    "compound_v3": {"allocate": 250_000, "withdraw": 270_000},
    "morpho_blue": {"allocate": 350_000, "withdraw": 370_000},
    "yearn_v3":   {"allocate": 220_000, "withdraw": 240_000},
    "euler_v2":   {"allocate": 260_000, "withdraw": 280_000},
}
_DEFAULT_GAS = 350_000
_ESTIMATED_GAS_PRICE_GWEI = 20   # conservative; use oracle in production
_GWEI_TO_ETH = 1e-9
_ETH_PRICE_USD = 3_500           # placeholder; use live price feed in production

# Required fields in a Safe TX proposal (validation)
_REQUIRED_PROPOSAL_FIELDS = (
    "safe", "to", "value", "data", "operation",
    "nonce", "chain_id", "_spa_metadata",
)


# ---------------------------------------------------------------------------
# SafeTxBuilder
# ---------------------------------------------------------------------------

class SafeTxBuilder:
    """
    Строит Safe Transaction Service proposals для Gnosis Safe 2-of-3.

    В paper-режиме (is_paper_mode() == True) все методы — no-op.
    В live-режиме возвращает proposal dict для передачи в Safe TX Service API.

    Пример использования (live режим):

        builder = SafeTxBuilder(
            safe_address="0x<SAFE_ADDRESS>",
            chain_id=1
        )
        if not builder.is_paper_mode():
            proposal = builder.build_allocate_tx("aave_v3", 500.0)
            # Передать proposal в safe_tx_service_client.propose(proposal)

    НИКОГДА не используй этот класс для подписания транзакций.
    НИКОГДА не передавай приватные ключи в этот класс.
    """

    def __init__(
        self,
        safe_address: str,
        chain_id: int = 1,
        owners: Optional[list] = None,
        threshold: Optional[int] = None,
    ) -> None:
        """
        Args:
            safe_address: Ethereum-адрес Safe контракта (checksum-формат, 0x + 40 hex).
            chain_id:     Chain ID. 1 = Mainnet, 11155111 = Sepolia.
            owners:       Optional list of Safe owner addresses (the signer set).
                          When provided it is validated against *threshold* so an
                          UNSIGNABLE multisig config is refused at construction
                          (WS-3.3 — never build a tx that can't reach threshold).
            threshold:    Optional M of the M-of-N policy (e.g. 2 for 2-of-3).
                          Defaults to ADR-022 2-of-3 semantics when owners are
                          supplied without an explicit threshold.

        Raises:
            ValidationError: если safe_address имеет неправильный формат.
            ValidationError: если chain_id не является положительным целым числом.
            ValidationError: если owner-set/threshold не образуют подписываемую
                             конфигурацию (insufficient/missing signer set).
        """
        _validate_safe_address(safe_address)
        if not isinstance(chain_id, int) or chain_id <= 0:
            raise ValidationError("chain_id", chain_id, "must be a positive integer")
        self._safe_address = safe_address
        self._chain_id = chain_id
        # Signer-set policy. When owners are not supplied the builder stays in its
        # historical mode (proposal-only; the external client supplies signers) —
        # but if a caller DOES declare owners/threshold we enforce signability.
        self._owners, self._threshold = _validate_signer_set(owners, threshold)
        self._mode = os.environ.get("SPA_EXECUTION_MODE", "paper").lower()

        if not self.is_paper_mode():
            logger.warning(
                "SafeTxBuilder initialized in LIVE mode. "
                "safe=%s chain_id=%d. "
                "No transactions will be signed or sent by this class.",
                safe_address,
                chain_id,
            )
        else:
            logger.debug(
                "SafeTxBuilder initialized in paper mode (no-op). "
                "Set SPA_EXECUTION_MODE=live to enable proposal building."
            )

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def is_paper_mode(self) -> bool:
        """
        Возвращает True если SPA работает в paper trading режиме.

        В paper режиме все методы build_*_tx() возвращают {} без сетевых вызовов.
        Режим считается paper если SPA_EXECUTION_MODE != 'live'.

        Returns:
            True  — paper trading (Safe не задействован, no-op).
            False — live mode (Safe TX proposals строятся).
        """
        return self._mode != "live"

    def build_allocate_tx(
        self,
        adapter: str,
        amount_usd: float,
        nonce: Optional[int] = None,
    ) -> dict:
        """
        Строит Safe TX proposal для аллокации в DeFi-протокол.

        В paper режиме возвращает {} без сетевых вызовов.
        В live режиме возвращает proposal dict для Safe Transaction Service API.

        Транзакции < $1,000 помечаются single_sig_eligible=True (ADR-022 §2.2):
        они могут быть исполнены автоматически через Key-A (EXECUTOR роль, ADR-010).
        Транзакции >= $1,000 требуют manual confirmation от Owner (Key-B).

        Args:
            adapter:    Идентификатор адаптера (например, "aave_v3").
                        Должен быть в PROTOCOL_WHITELIST.
            amount_usd: Сумма в USD для аллокации. Конвертируется в USDC (6 decimals).
            nonce:      Safe nonce. Если None — должен быть получен из Safe API.
                        Передай актуальный nonce перед proposeTx().

        Returns:
            dict: Safe TX proposal (передай в safe_tx_service_client.propose()).
                  {} если paper mode или adapter не в whitelist.

        Raises:
            ValueError: если amount_usd <= 0 (в live режиме).
        """
        if self.is_paper_mode():
            return {}

        # WS-3.3: never build a tx the configured signer set can't sign.
        self.assert_signable()

        if amount_usd <= 0:
            raise ValidationError("amount_usd", amount_usd, "must be positive")

        if adapter not in PROTOCOL_WHITELIST:
            logger.error(
                "Adapter '%s' not in PROTOCOL_WHITELIST. Refusing to build tx.",
                adapter,
            )
            return {}

        protocol_address = PROTOCOL_WHITELIST[adapter]
        if not protocol_address:
            logger.error(
                "Adapter '%s' has empty protocol address. "
                "Fill PROTOCOL_WHITELIST before go-live.",
                adapter,
            )
            return {}

        amount_usdc_raw = _usd_to_usdc_raw(amount_usd)
        single_sig = amount_usd < SINGLE_SIG_THRESHOLD_USD

        # Encoded calldata для supply(asset, amount, onBehalfOf, referralCode)
        # ЗАГЛУШКА: реальный encode требует ABI — заполнить при go-live
        calldata = _encode_allocate_stub(protocol_address, amount_usdc_raw, adapter)

        proposal = _build_safe_tx_proposal(
            safe_address=self._safe_address,
            to=protocol_address,
            value=0,
            data=calldata,
            nonce=nonce,
            chain_id=self._chain_id,
            origin=f"SPA allocate {adapter} ${amount_usd:.2f}",
            metadata={
                "action": "allocate",
                "adapter": adapter,
                "amount_usd": amount_usd,
                "amount_usdc_raw": amount_usdc_raw,
                "single_sig_eligible": single_sig,
                "adr": "ADR-022",
            },
        )

        logger.info(
            "Built allocate proposal: adapter=%s amount_usd=%.2f single_sig=%s",
            adapter,
            amount_usd,
            single_sig,
        )
        return proposal

    def build_withdraw_tx(
        self,
        adapter: str,
        amount_usd: float,
        nonce: Optional[int] = None,
    ) -> dict:
        """
        Строит Safe TX proposal для вывода из DeFi-протокола.

        В paper режиме возвращает {} без сетевых вызовов.
        В live режиме строит withdraw proposal для Safe Transaction Service API.

        Аварийный вывод (kill-switch, drawdown ≥ 5%) передаётся с
        amount_usd = total_position_usd — весь баланс протокола.
        В этом случае single_sig_eligible=True (ADR-022 §7.3: kill-switch
        не требует 2 подписей для скорости).

        Args:
            adapter:    Идентификатор адаптера (например, "compound_v3").
            amount_usd: Сумма USD для вывода. Используй float("inf") или
                        специальный флаг для полного вывода (все средства).
            nonce:      Safe nonce.

        Returns:
            dict: Safe TX proposal или {} в paper режиме.

        Raises:
            ValueError: если amount_usd <= 0 (в live режиме).
        """
        if self.is_paper_mode():
            return {}

        # WS-3.3: never build a tx the configured signer set can't sign.
        self.assert_signable()

        if amount_usd <= 0:
            raise ValidationError("amount_usd", amount_usd, "must be positive")

        if adapter not in PROTOCOL_WHITELIST:
            logger.error(
                "Adapter '%s' not in PROTOCOL_WHITELIST. Refusing to build tx.",
                adapter,
            )
            return {}

        protocol_address = PROTOCOL_WHITELIST[adapter]
        if not protocol_address:
            logger.error(
                "Adapter '%s' has empty protocol address.",
                adapter,
            )
            return {}

        # Вывод всегда single_sig для скорости (kill-switch priority)
        # Для крупных выводов в штатном режиме — отдельное решение Owner
        single_sig = True  # withdraw приоритет скорости над порогом

        amount_usdc_raw = _usd_to_usdc_raw(amount_usd)

        # Encoded calldata для withdraw(asset, amount, to)
        # ЗАГЛУШКА: реальный encode требует ABI — заполнить при go-live
        calldata = _encode_withdraw_stub(protocol_address, amount_usdc_raw, adapter)

        proposal = _build_safe_tx_proposal(
            safe_address=self._safe_address,
            to=protocol_address,
            value=0,
            data=calldata,
            nonce=nonce,
            chain_id=self._chain_id,
            origin=f"SPA withdraw {adapter} ${amount_usd:.2f}",
            metadata={
                "action": "withdraw",
                "adapter": adapter,
                "amount_usd": amount_usd,
                "amount_usdc_raw": amount_usdc_raw,
                "single_sig_eligible": single_sig,
                "adr": "ADR-022",
            },
        )

        logger.info(
            "Built withdraw proposal: adapter=%s amount_usd=%.2f",
            adapter,
            amount_usd,
        )
        return proposal

    def get_safe_tx_service_url(self) -> str:
        """
        Возвращает base URL Safe Transaction Service для текущего chain_id.

        Returns:
            URL строка или пустая строка если chain_id неизвестен.
        """
        return SAFE_TX_SERVICE_URLS.get(self._chain_id, "")

    def get_safe_address(self) -> str:
        """Возвращает адрес Safe контракта."""
        return self._safe_address

    def get_chain_id(self) -> int:
        """Возвращает chain ID."""
        return self._chain_id

    def get_signer_set(self) -> tuple:
        """Возвращает (owners, threshold) — declared signer-set policy.

        ``owners`` is an empty tuple when no signer set was declared (historical
        proposal-only mode, signers supplied by the external client).
        """
        return (tuple(self._owners), self._threshold)

    def is_signable(self) -> bool:
        """True если объявленный signer-set может достичь threshold (или не объявлен)."""
        try:
            self.assert_signable()
            return True
        except ValidationError:
            return False

    def assert_signable(self) -> None:
        """Fail-CLOSED guard: refuse to proceed if the multisig is UNSIGNABLE.

        When a signer set is declared (``owners`` non-empty), it must contain at
        least ``threshold`` distinct owners — otherwise no valid M-of-N signature
        can ever be collected and any tx we build would be unsignable. When NO
        signer set is declared the builder stays in proposal-only mode (the
        external Safe client supplies signers) and this is a no-op.

        Raises:
            ValidationError: если signer-set недостаточен для threshold.
        """
        if not self._owners:
            return  # proposal-only mode — external client owns the signer set
        if len(self._owners) < self._threshold:
            raise ValidationError(
                "signer_set",
                f"{len(self._owners)} owners",
                f"insufficient signer set: {len(self._owners)} owners < threshold "
                f"{self._threshold} — UNSIGNABLE multisig, refusing to build tx",
            )

    def describe(self) -> dict:
        """
        Возвращает конфигурацию SafeTxBuilder (для логирования и диагностики).

        Не содержит ключей, токенов или чувствительных данных.
        """
        return {
            "safe_address": self._safe_address,
            "chain_id": self._chain_id,
            "mode": self._mode,
            "is_paper": self.is_paper_mode(),
            "tx_service_url": self.get_safe_tx_service_url(),
            "single_sig_threshold_usd": SINGLE_SIG_THRESHOLD_USD,
            "protocol_whitelist_keys": list(PROTOCOL_WHITELIST.keys()),
            "owner_count": len(self._owners),
            "threshold": self._threshold,
            "is_signable": self.is_signable(),
        }

    def validate_proposal(self, proposal: dict) -> list:
        """
        Валидирует proposal dict на наличие обязательных полей.

        Args:
            proposal: dict, возвращённый build_allocate_tx() или build_withdraw_tx().

        Returns:
            list: Список строк с ошибками валидации. Пустой список = валидный proposal.
        """
        errors = []
        if not isinstance(proposal, dict):
            return ["proposal must be a dict"]
        if not proposal:
            return ["proposal is empty (paper mode or whitelist miss)"]
        for field in _REQUIRED_PROPOSAL_FIELDS:
            if field not in proposal:
                errors.append(f"missing required field: '{field}'")
        # Проверяем структуру metadata
        meta = proposal.get("_spa_metadata")
        if meta is not None:
            for mf in ("action", "adapter", "amount_usd", "single_sig_eligible"):
                if mf not in meta:
                    errors.append(f"missing metadata field: '{mf}'")
        return errors

    def estimate_gas_dry_run(self, adapter: str, action: str = "allocate") -> dict:
        """
        Оценка газа для транзакции (DRY_RUN — исторические данные, не on-chain).

        В production при go-live использовать eth_estimateGas через RPC.
        Текущие значения — консервативные оценки на основе исторических данных mainnet.

        Args:
            adapter: Идентификатор адаптера (например, "aave_v3").
            action:  "allocate" или "withdraw".

        Returns:
            dict: {
                "adapter": str,
                "action": str,
                "gas_limit": int,
                "gas_price_gwei": int,
                "estimated_cost_eth": float,
                "estimated_cost_usd": float,
                "dry_run": True,
                "note": str,
            }
        """
        gas_table = _GAS_ESTIMATES.get(adapter, {})
        gas_limit = gas_table.get(action, _DEFAULT_GAS)
        cost_eth = gas_limit * _ESTIMATED_GAS_PRICE_GWEI * _GWEI_TO_ETH
        cost_usd = cost_eth * _ETH_PRICE_USD
        return {
            "adapter": adapter,
            "action": action,
            "gas_limit": gas_limit,
            "gas_price_gwei": _ESTIMATED_GAS_PRICE_GWEI,
            "estimated_cost_eth": round(cost_eth, 8),
            "estimated_cost_usd": round(cost_usd, 4),
            "dry_run": True,
            "note": (
                "DRY_RUN estimate from historical mainnet data. "
                "Use eth_estimateGas via RPC before go-live."
            ),
        }

    @live_trading_forbidden
    def submit_proposal(self, proposal: dict) -> dict:
        """
        НЕ РЕАЛИЗОВАН — требует активации LiveTradingGate.

        Этот метод НИКОГДА не будет вызван в paper period.
        При go-live будет отправлять proposal в Safe Transaction Service API
        через POST /api/v1/safes/{safe_address}/multisig-transactions/.

        Декорирован @live_trading_forbidden — всегда поднимает LiveTradingForbiddenError.
        Реальная реализация — в safe_tx_service_client (вне spa_core/execution/).

        Args:
            proposal: dict из build_allocate_tx() или build_withdraw_tx().

        Raises:
            LiveTradingForbiddenError: всегда (до активации LiveTradingGate).
        """
        # Тело недостижимо — @live_trading_forbidden всегда поднимает исключение.
        raise SPAError(
            "unreachable: @live_trading_forbidden must have raised",
            code="UNREACHABLE_SENTINEL",
        )


# ---------------------------------------------------------------------------
# Вспомогательные функции (private)
# ---------------------------------------------------------------------------

def _usd_to_usdc_raw(amount_usd: float) -> int:
    """Конвертирует USD сумму в raw USDC (6 decimals)."""
    return int(amount_usd * (10 ** USDC_DECIMALS))


def _build_safe_tx_proposal(
    safe_address: str,
    to: str,
    value: int,
    data: str,
    nonce: Optional[int],
    chain_id: int,
    origin: str,
    metadata: dict,
) -> dict:
    """
    Строит proposal dict для Safe Transaction Service API (POST multisig-transactions/).

    Возвращает proposal-структуру согласно Safe TX Service API spec.
    Поля contractTransactionHash и signature должны быть заполнены
    внешним компонентом (safe_tx_service_client) перед отправкой.

    Этот метод НЕ подписывает транзакцию.
    """
    # Stub-hash для идентификации proposal (реальный hash считается по EIP-712)
    stub_hash = hashlib.sha256(
        json.dumps(
            {"to": to, "value": value, "data": data, "nonce": nonce, "chain_id": chain_id},
            sort_keys=True,
        ).encode()
    ).hexdigest()

    return {
        # Safe TX Service API fields
        "safe": safe_address,
        "to": to,
        "value": str(value),
        "data": data,
        "operation": 0,               # 0 = CALL (не DELEGATECALL)
        "safeTxGas": 0,
        "baseGas": 0,
        "gasPrice": "0",
        "gasToken": "0x0000000000000000000000000000000000000000",
        "refundReceiver": "0x0000000000000000000000000000000000000000",
        "nonce": nonce,               # None = клиент должен запросить актуальный nonce
        # Поля для заполнения safe_tx_service_client (не здесь):
        "contractTransactionHash": None,  # EIP-712 hash — вычисляет клиент
        "sender": None,                   # Key-A address — устанавливает клиент
        "signature": None,                # Подпись Key-A — устанавливает клиент
        # Мета
        "origin": origin,
        "chain_id": chain_id,
        "_spa_metadata": metadata,
        "_safe_tx_builder_stub_hash": stub_hash,
        "_warning": (
            "This is a proposal stub. Fields contractTransactionHash, sender, "
            "signature must be populated by safe_tx_service_client before submission."
        ),
    }


def _encode_allocate_stub(
    protocol_address: str,
    amount_usdc_raw: int,
    adapter: str,
    on_behalf_of: str = "",
) -> str:
    """
    Строит ABI-calldata для supply/deposit-транзакции.

    Использует pre-computed function selectors и ручной ABI encode (stdlib only).
    Параметры кодируются согласно Ethereum ABI spec (v2):
      - address → 32 bytes, left-padded with zeros
      - uint256 → 32 bytes, big-endian
      - uint16  → 32 bytes, big-endian (ABI always pads to 32)

    Поддерживаемые адаптеры и функции:
      aave_v3:    supply(address asset, uint256 amount, address onBehalfOf, uint16 referralCode)
                  selector: 0x617ba037
      compound_v3: supply(address asset, uint256 amount)
                  selector: 0xf2b9fdb8
      morpho_blue: supply(...) — struct-based ABI; requires go-live client (DRY_RUN struct here)
      yearn_v3:   deposit(uint256 assets, address receiver) — ERC-4626
                  selector: 0x6e553f65
      euler_v2:   deposit(uint256 assets, address receiver) — ERC-4626
                  selector: 0x6e553f65

    Args:
        protocol_address: Contract address to call (from PROTOCOL_WHITELIST).
        amount_usdc_raw:  Amount in raw USDC units (6 decimals).
        adapter:          Adapter key (e.g. "aave_v3").
        on_behalf_of:     Beneficiary address (defaults to zero address if empty).

    Returns:
        str: 0x-prefixed hex calldata string.
             Marked with DRY_RUN comment in logs; validated via validate_proposal().
    """
    beneficiary = on_behalf_of if on_behalf_of else "0x" + "0" * 40
    asset_enc  = _abi_encode_address(USDC_MAINNET)
    amount_enc = _abi_encode_uint256(amount_usdc_raw)
    recv_enc   = _abi_encode_address(beneficiary)
    zero32     = "00" * 32   # uint16 referralCode=0 or padding

    logger.debug(
        "ABI encode_allocate: adapter=%s protocol=%s amount_raw=%d",
        adapter, protocol_address, amount_usdc_raw,
    )

    if adapter == "aave_v3":
        # supply(address asset, uint256 amount, address onBehalfOf, uint16 referralCode)
        return "0x" + _SELECTOR_AAVE_SUPPLY + asset_enc + amount_enc + recv_enc + zero32

    if adapter == "compound_v3":
        # supply(address asset, uint256 amount)
        return "0x" + _SELECTOR_COMP_SUPPLY + asset_enc + amount_enc

    if adapter in ("yearn_v3", "euler_v2"):
        # ERC-4626: deposit(uint256 assets, address receiver)
        return "0x" + _SELECTOR_ERC4626_DEPOSIT + amount_enc + recv_enc

    if adapter == "morpho_blue":
        # Morpho Blue supply uses MarketParams struct (tuple ABI type).
        # Full encode requires dynamic tuple encoding; defer to go-live client.
        # DRY_RUN: return selector + zero-padded placeholder (5 × 32 bytes for MarketParams).
        logger.warning(
            "morpho_blue ABI encode: MarketParams struct deferred to go-live client. "
            "Returning DRY_RUN placeholder selector."
        )
        placeholder = "00" * (32 * 5)   # MarketParams: 5 fields × 32 bytes
        return "0x" + "a99aad89" + placeholder  # selector for supply(MarketParams,...)

    # Unknown adapter — return zero-data stub (safe: will fail on-chain)
    logger.warning("encode_allocate: unknown adapter '%s', returning zero stub", adapter)
    return "0x"


def _encode_withdraw_stub(
    protocol_address: str,
    amount_usdc_raw: int,
    adapter: str,
    recipient: str = "",
) -> str:
    """
    Строит ABI-calldata для withdraw/redeem-транзакции.

    Использует pre-computed function selectors и ручной ABI encode (stdlib only).

    Поддерживаемые адаптеры и функции:
      aave_v3:    withdraw(address asset, uint256 amount, address to)
                  selector: 0x69328dec
      compound_v3: withdraw(address asset, uint256 amount)
                  selector: 0xf3fef3a3
      morpho_blue: withdraw(...) — struct-based, DRY_RUN placeholder
      yearn_v3:   redeem(uint256 shares, address receiver, address owner) — ERC-4626
                  selector: 0xba087652
      euler_v2:   redeem(uint256 shares, address receiver, address owner) — ERC-4626
                  selector: 0xba087652

    Args:
        protocol_address: Contract address to call.
        amount_usdc_raw:  Amount in raw USDC units (6 decimals).
        adapter:          Adapter key (e.g. "aave_v3").
        recipient:        Withdrawal recipient address (defaults to zero address).

    Returns:
        str: 0x-prefixed hex calldata string.
    """
    to_addr = recipient if recipient else "0x" + "0" * 40
    asset_enc  = _abi_encode_address(USDC_MAINNET)
    amount_enc = _abi_encode_uint256(amount_usdc_raw)
    recv_enc   = _abi_encode_address(to_addr)

    logger.debug(
        "ABI encode_withdraw: adapter=%s protocol=%s amount_raw=%d",
        adapter, protocol_address, amount_usdc_raw,
    )

    if adapter == "aave_v3":
        # withdraw(address asset, uint256 amount, address to)
        return "0x" + _SELECTOR_AAVE_WITHDRAW + asset_enc + amount_enc + recv_enc

    if adapter == "compound_v3":
        # withdraw(address asset, uint256 amount)
        return "0x" + _SELECTOR_COMP_WITHDRAW + asset_enc + amount_enc

    if adapter in ("yearn_v3", "euler_v2"):
        # ERC-4626: redeem(uint256 shares, address receiver, address owner)
        return "0x" + _SELECTOR_ERC4626_REDEEM + amount_enc + recv_enc + recv_enc

    if adapter == "morpho_blue":
        # Morpho Blue withdraw uses MarketParams struct; defer to go-live client.
        logger.warning(
            "morpho_blue ABI encode withdraw: MarketParams struct deferred to go-live client. "
            "Returning DRY_RUN placeholder selector."
        )
        placeholder = "00" * (32 * 5)
        return "0x" + "8069218f" + placeholder  # selector for withdraw(MarketParams,...)

    logger.warning("encode_withdraw: unknown adapter '%s', returning zero stub", adapter)
    return "0x"


# ---------------------------------------------------------------------------
# Вспомогательные функции: ABI encoding (stdlib only)
# ---------------------------------------------------------------------------

def _validate_signer_set(owners: Optional[list], threshold: Optional[int]) -> tuple:
    """Validate + normalise a declared (owners, threshold) signer-set policy.

    Returns ``(owners_tuple, threshold_int)``. When *owners* is None/empty the
    builder stays proposal-only and we return ``((), 1)`` (a no-op threshold).

    A declared signer set is checked fail-CLOSED at construction time:
      * every owner must be a well-formed 0x+40-hex address,
      * owners must be distinct (duplicate owners can't each contribute a sig),
      * threshold must be a positive int that does NOT exceed the owner count
        (an unreachable threshold = permanently unsignable Safe).

    Raises:
        ValidationError: on any malformed / unsignable configuration.
    """
    if owners is None:
        owners = []
    if not isinstance(owners, (list, tuple)):
        raise ValidationError("owners", type(owners).__name__, "must be a list of addresses")

    # No owners declared → proposal-only mode (default threshold 1, never used).
    if len(owners) == 0:
        if threshold not in (None, 0):
            raise ValidationError(
                "threshold", threshold,
                "threshold declared without an owner set — ambiguous, refusing",
            )
        return ((), 1)

    # Validate each owner address and reject duplicates (case-insensitive).
    seen: set[str] = set()
    normalised: list[str] = []
    for o in owners:
        _validate_safe_address(o)  # same 0x + 40 hex contract as the Safe address
        key = o.lower()
        if key in seen:
            raise ValidationError("owners", o, "duplicate owner address — each owner signs once")
        seen.add(key)
        normalised.append(o)

    # Default to ADR-022 2-of-3 semantics when threshold omitted, but clamp to a
    # sane value and ALWAYS verify it is reachable.
    if threshold is None:
        threshold = 2 if len(normalised) >= 2 else 1
    if isinstance(threshold, bool) or not isinstance(threshold, int):
        raise ValidationError("threshold", threshold, "must be a positive integer")
    if threshold < 1:
        raise ValidationError("threshold", threshold, "must be >= 1")
    if threshold > len(normalised):
        raise ValidationError(
            "threshold", threshold,
            f"threshold {threshold} exceeds owner count {len(normalised)} — "
            "UNSIGNABLE multisig (can never reach M-of-N)",
        )
    return (tuple(normalised), threshold)


def _validate_safe_address(addr: str) -> None:
    """
    Проверяет формат Ethereum-адреса Safe (0x + 40 hex chars).

    Args:
        addr: Адрес для валидации.

    Raises:
        ValueError: Если формат неверный.
    """
    if not isinstance(addr, str):
        raise ValidationError("safe_address", type(addr).__name__, "must be a string")
    if not addr.startswith("0x"):
        raise ValidationError("safe_address", addr, "must start with '0x'")
    hex_part = addr[2:]
    if len(hex_part) != 40:
        raise ValidationError("safe_address", addr, f"must be 0x + 40 hex chars (20 bytes); got length {len(hex_part)}")
    try:
        int(hex_part, 16)
    except ValueError:
        raise ValidationError("safe_address", addr, "contains non-hex characters")


def _abi_encode_address(addr: str) -> str:
    """
    Кодирует Ethereum адрес в ABI-формате (32 bytes, left-padded with zeros).

    EVM ABI: address занимает 32 bytes, выровнен вправо, ведущие нули слева.

    Args:
        addr: 0x-prefixed Ethereum address (40 hex chars).

    Returns:
        str: 64-char lowercase hex string (32 bytes).
    """
    clean = addr[2:].lower() if addr.startswith("0x") else addr.lower()
    return clean.zfill(64)   # left-pad to 64 chars (32 bytes)


def _abi_encode_uint256(value: int) -> str:
    """
    Кодирует uint256 в ABI-формате (32 bytes, big-endian).

    Args:
        value: Non-negative integer (uint256 range: 0 … 2**256-1).

    Returns:
        str: 64-char lowercase hex string (32 bytes).
    """
    if value < 0:
        raise ValidationError("value", value, "uint256 must be non-negative")
    return format(value, "064x")


# ---------------------------------------------------------------------------
# CLI / smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")

    print("SafeTxBuilder smoke test")
    print("=" * 50)

    # --- Paper mode test (default) ---
    builder_paper = SafeTxBuilder(safe_address="0x0000000000000000000000000000000000000001")
    print(f"\nPaper mode: is_paper_mode() = {builder_paper.is_paper_mode()}")
    alloc = builder_paper.build_allocate_tx("aave_v3", 500.0)
    print(f"build_allocate_tx (paper) = {alloc!r}  (должен быть {{}})")
    withdraw = builder_paper.build_withdraw_tx("compound_v3", 200.0)
    print(f"build_withdraw_tx (paper) = {withdraw!r}  (должен быть {{}})")

    # --- Live mode test (через env) ---
    os.environ["SPA_EXECUTION_MODE"] = "live"
    builder_live = SafeTxBuilder(
        safe_address="0x0000000000000000000000000000000000000001",
        chain_id=11155111,  # Sepolia
    )
    print(f"\nLive mode: is_paper_mode() = {builder_live.is_paper_mode()}")

    # small tx < $1000 → single_sig
    proposal_small = builder_live.build_allocate_tx("aave_v3", 500.0, nonce=42)
    if proposal_small:
        meta = proposal_small.get("_spa_metadata", {})
        print(f"Small alloc proposal: single_sig_eligible={meta.get('single_sig_eligible')}")
    else:
        print("Small alloc: empty (adapter whitelist not configured — expected)")

    print(f"\ndescribe(): {json.dumps(builder_live.describe(), indent=2)}")

    # Сброс env
    os.environ["SPA_EXECUTION_MODE"] = "paper"
    print("\nSmoke test complete. SPA_EXECUTION_MODE reset to 'paper'.")
    sys.exit(0)
