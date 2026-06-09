"""Модели аллокации капитала (SPA-V388 — Strategy Allocator).

Три детерминированные advisory-модели, которые превращают список адаптеров в
веса портфеля. Всё read-only / dry-run: ни один вызов не трогает execution и не
двигает реальные деньги — это только рекомендации.

Контракт каждой модели:
    вход  — ``list[dict]`` с ключами
            ``{"protocol": str, "apy_pct": float, "tvl_usd": float, "tier": str}``
    выход — ``dict[str, float]`` ``{protocol: weight_fraction}`` с суммой == 1.0
            (для непустого входа). На пустом входе возвращается ``{}``.

Кап'ы по тирам (T1 ≤ 40%, T2 ≤ 20%) применяются НЕ здесь, а в
:class:`spa_core.allocator.allocator.StrategyAllocator`, чтобы модели оставались
чистыми «сырыми» распределениями.
"""
from __future__ import annotations

_EPS = 1e-12


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    """Нормализует веса так, чтобы сумма == 1.0. Пустой/нулевой вход → как есть."""
    total = sum(weights.values())
    if total <= _EPS:
        return dict(weights)
    return {p: w / total for p, w in weights.items()}


def equal_weight(adapters: list[dict]) -> dict[str, float]:
    """Равные веса между всеми активными адаптерами.

    n адаптеров → каждый получает 1/n. Пустой список → ``{}``.
    """
    if not adapters:
        return {}
    n = len(adapters)
    share = 1.0 / n
    return {a["protocol"]: share for a in adapters}


def best_apy_weight(adapters: list[dict], top_n: int = 3) -> dict[str, float]:
    """Концентрация в top-N протоколах по APY, остальные — 0.

    Выбираются ``top_n`` адаптеров с наибольшим ``apy_pct`` и делятся поровну.
    Если адаптеров меньше ``top_n`` — берутся все. Пустой список → ``{}``.
    """
    if not adapters or top_n <= 0:
        return {}
    ranked = sorted(adapters, key=lambda a: a.get("apy_pct", 0.0), reverse=True)
    chosen = ranked[:top_n]
    share = 1.0 / len(chosen)
    return {a["protocol"]: share for a in chosen}


def risk_parity_weight(adapters: list[dict]) -> dict[str, float]:
    """Risk-parity: веса обратно пропорциональны риску.

    Если у адаптеров есть оценка волатильности APY (ключ ``apy_vol`` или
    ``volatility``) — вес ∝ 1/vol. Иначе используется TVL-proxy: больший TVL
    трактуется как меньший риск, поэтому вес ∝ TVL. Если TVL недоступен или
    у всех нулевой (типично для paper-данных) — честный fallback на равные веса,
    чтобы НИКОГДА не делить на ноль.
    """
    if not adapters:
        return {}

    def _vol(a: dict) -> float | None:
        for key in ("apy_vol", "volatility", "vol"):
            if key in a and a[key] is not None:
                return float(a[key])
        return None

    vols = [_vol(a) for a in adapters]
    if all(v is not None and v > _EPS for v in vols):
        inv = {a["protocol"]: 1.0 / v for a, v in zip(adapters, vols)}
        return _normalize(inv)

    # TVL-proxy: вес ∝ TVL (низкий TVL ⇒ выше риск ⇒ меньше вес).
    tvls = {a["protocol"]: max(float(a.get("tvl_usd", 0.0)), 0.0) for a in adapters}
    if sum(tvls.values()) > _EPS:
        return _normalize(tvls)

    # Fallback: ни волатильности, ни TVL — равные веса.
    return equal_weight(adapters)
