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

    def __init__(self, safe_address: str, chain_id: int = 1) -> None:
        """
        Args:
            safe_address: Ethereum-адрес Safe контракта (checksum-формат).
            chain_id:     Chain ID. 1 = Mainnet, 11155111 = Sepolia.
        """
        self._safe_address = safe_address
        self._chain_id = chain_id
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

        if amount_usd <= 0:
            raise ValueError(f"amount_usd must be positive, got {amount_usd}")

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

        if amount_usd <= 0:
            raise ValueError(f"amount_usd must be positive, got {amount_usd}")

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
        }


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
) -> str:
    """
    ЗАГЛУШКА: возвращает placeholder calldata для allocate-транзакции.

    Реальный encode ABI-calldata требует:
    - ABI протокола (Aave V3 Pool, Compound V3 Comet, и т.д.)
    - eth_abi или web3.py (внешняя зависимость — не использовать в runtime)

    При go-live этот метод заменяется реальным ABI encode
    через отдельный execution-клиент (вне spa_core/execution/).

    Returns:
        str: HEX строка placeholder ("0x00" = пустые данные для stub).
    """
    logger.debug(
        "STUB encode_allocate: adapter=%s to=%s amount_raw=%d",
        adapter,
        protocol_address,
        amount_usdc_raw,
    )
    # TODO (go-live): реализовать реальный ABI encode для каждого адаптера
    # Пример для Aave V3 supply():
    #   function supply(address asset, uint256 amount, address onBehalfOf, uint16 referralCode)
    #   selector: 0x617ba037
    return "0x"  # stub


def _encode_withdraw_stub(
    protocol_address: str,
    amount_usdc_raw: int,
    adapter: str,
) -> str:
    """
    ЗАГЛУШКА: возвращает placeholder calldata для withdraw-транзакции.

    При go-live заменяется реальным ABI encode.

    Returns:
        str: HEX строка placeholder.
    """
    logger.debug(
        "STUB encode_withdraw: adapter=%s to=%s amount_raw=%d",
        adapter,
        protocol_address,
        amount_usdc_raw,
    )
    # TODO (go-live): реализовать реальный ABI encode для каждого адаптера
    # Пример для Aave V3 withdraw():
    #   function withdraw(address asset, uint256 amount, address to)
    #   selector: 0x69328dec
    return "0x"  # stub


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
