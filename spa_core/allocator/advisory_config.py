"""AdvisoryConfig — read-only сопоставление текущих риск-лимитов с рекомендацией
оптимизатора (Kelly / grid search → ``data/optimized_params.json``).

НАЗНАЧЕНИЕ
==========
Модуль показывает, *что бы порекомендовал* оптимизатор по сравнению с текущими
живыми лимитами RiskConfig — и **только показывает**. Он НЕ изменяет RiskConfig,
НЕ трогает аллокатор/execution, не открывает позиции. Любое изменение риск-
параметров проходит исключительно через ADR + Owner approval (см. RULES.md и
governance-блок в ``spa_core/risk/policy.py``).

Поэтому ``safe_to_apply`` означает узкую вещь: «попадают ли рекомендованные
значения внутрь УЖЕ действующих риск-границ» (т.е. их можно было бы применить
без ослабления политики). Если рекомендация *ослабляет* лимит (поднимает cap
концентрации или снижает кэш-буфер) — ``safe_to_apply=False``, нужен ADR.

КОНТРАКТ ДОМЕНА
==============
* read-only / advisory — никаких записей в state-файлы;
* pure stdlib, offline;
* LLM не используется;
* ``approved=False`` от RiskPolicy не может быть переопределён этим модулем.

CLI
===
    python3 -m spa_core.allocator.advisory_config            # печатает сравнение (JSON)
    python3 -m spa_core.allocator.advisory_config --params <path>
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from spa_core.risk.policy import RiskConfig

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_PARAMS_PATH = _REPO_ROOT / "data" / "optimized_params.json"


class AdvisoryConfig:
    """Read-only сравнение «текущая политика vs рекомендация оптимизатора».

    Текущие значения берутся из :class:`spa_core.risk.policy.RiskConfig`
    (единый источник истины для лимитов). Оптимальные — из
    ``data/optimized_params.json`` (вывод parameter_optimizer / Kelly grid).
    """

    def __init__(
        self,
        optimized_params_path: str | os.PathLike | None = None,
        config: Optional[RiskConfig] = None,
    ) -> None:
        self.params_path = (
            Path(optimized_params_path)
            if optimized_params_path
            else _DEFAULT_PARAMS_PATH
        )
        # RiskConfig() — текущая живая политика (v1.0).
        self.config = config or RiskConfig()

    # ── загрузка вывода оптимизатора ──────────────────────────────────────
    def _load_optimized(self) -> dict:
        """Читает ``optimized_params.json`` и возвращает нормализованный dict.

        Любая ошибка (нет файла, битый JSON, нет ``best_params``) → ``{}`` без
        исключения: вызывающий код получает ``loaded=False`` и сравнение без
        оптимальных значений (модуль остаётся read-only и не валится).
        """
        if not self.params_path.exists():
            return {}
        try:
            raw = json.loads(self.params_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        best = raw.get("best_params")
        if not isinstance(best, dict):
            return {}
        detail = raw.get("best_detail")
        out: dict = {"best_params": best}
        if isinstance(detail, dict):
            out["best_detail"] = detail
        return out

    # ── текущая живая конфигурация ────────────────────────────────────────
    def current(self) -> dict:
        """Текущие риск-лимиты, релевантные оптимизатору (из RiskConfig)."""
        return {
            "t1_cap": self.config.max_concentration_t1,   # per-protocol T1
            "t2_cap": self.config.max_concentration_t2,   # per-protocol T2
            "cash_buffer": self.config.min_cash_pct,      # минимальный кэш-буфер
            "policy_version": self.config.version,
        }

    # ── проверка «внутри ли действующих границ» ───────────────────────────
    def _evaluate_safety(self, optimal: dict) -> tuple[bool, list[str]]:
        """Решает, можно ли применить рекомендацию без ослабления политики.

        Правила (ослабление → небезопасно, требует ADR):
          * ``t1_cap``      должен быть ≤ текущего T1-cap (повышение = ослабление);
          * ``t2_cap``      должен быть ≤ текущего T2-cap (повышение = ослабление);
          * ``cash_buffer`` должен быть ≥ текущего min_cash_pct (снижение =
            ослабление защитного буфера).

        Возвращает ``(safe, reasons)`` — ``reasons`` перечисляет, какие именно
        параметры выходят за действующие границы.
        """
        cur = self.current()
        reasons: list[str] = []

        opt_t1 = optimal.get("t1_cap")
        if isinstance(opt_t1, (int, float)) and opt_t1 > cur["t1_cap"] + 1e-9:
            reasons.append(
                f"t1_cap {opt_t1:.0%} > текущего T1-cap {cur['t1_cap']:.0%} "
                "(повышение концентрации — ослабление лимита)"
            )

        opt_t2 = optimal.get("t2_cap")
        if isinstance(opt_t2, (int, float)) and opt_t2 > cur["t2_cap"] + 1e-9:
            reasons.append(
                f"t2_cap {opt_t2:.0%} > текущего T2-cap {cur['t2_cap']:.0%} "
                "(повышение концентрации — ослабление лимита, ADR-019 territory)"
            )

        opt_cash = optimal.get("cash_buffer")
        if isinstance(opt_cash, (int, float)) and opt_cash < cur["cash_buffer"] - 1e-9:
            reasons.append(
                f"cash_buffer {opt_cash:.0%} < текущего min_cash_pct "
                f"{cur['cash_buffer']:.0%} (снижение защитного буфера — ослабление)"
            )

        return (len(reasons) == 0), reasons

    # ── основной API ──────────────────────────────────────────────────────
    def get_comparison(self) -> dict:
        """Сводное сравнение текущей политики и рекомендации оптимизатора.

        Структура результата стабильна (ключи присутствуют всегда), чтобы
        дашборд/тесты могли на неё опираться даже при отсутствии файла
        оптимизатора (тогда ``optimal == {}`` и ``optimizer_loaded=False``).
        """
        cur = self.current()
        loaded_obj = self._load_optimized()
        optimizer_loaded = bool(loaded_obj)
        optimal = dict(loaded_obj.get("best_params", {})) if optimizer_loaded else {}
        detail = loaded_obj.get("best_detail", {}) if optimizer_loaded else {}

        # current — только те поля, что есть у оптимизатора, плюс мета.
        current_block = {
            "t1_cap": cur["t1_cap"],
            "t2_cap": cur["t2_cap"],
            "cash_buffer": cur["cash_buffer"],
            "policy_version": cur["policy_version"],
        }

        safe, reasons = self._evaluate_safety(optimal) if optimal else (False, [])

        # Оценка прироста APY: expected_apy(optimal) − приближённый APY текущей
        # конфигурации, взятый из all_results по совпадению с текущими границами,
        # если доступен; иначе из явного поля detail.
        improvement_pct = self._estimate_apy_improvement(loaded_obj, cur)
        if improvement_pct is not None:
            improvement_str = f"+{improvement_pct:.2f}% APY if optimal applied"
        else:
            improvement_str = "n/a (optimizer output unavailable)"

        return {
            "current": current_block,
            "optimal": optimal,
            "optimizer_loaded": optimizer_loaded,
            "optimizer_expected_apy_pct": detail.get("expected_apy_pct"),
            "change_required": (
                "ADR required to change caps per governance policy "
                "(RULES.md + spa_core/risk/policy.py governance block)"
            ),
            "estimated_apy_improvement": improvement_str,
            "safe_to_apply": safe,
            "safe_to_apply_reasons": reasons,
            "mode": "ADVISORY",  # read-only — этот модуль ничего не применяет
            "note": (
                "Read-only advisory. Does NOT modify RiskConfig or the allocator. "
                "See ADR-048 for the pending decision."
            ),
        }

    def _estimate_apy_improvement(
        self, loaded_obj: dict, cur: dict
    ) -> float | None:
        """Прирост APY = expected_apy(optimal) − expected_apy(текущие границы).

        Текущая конфигурация ищется в ``all_results`` по совпадению t1/t2/cash.
        Если ряд не найден, прирост не оценивается (``None``) — без выдумывания.
        """
        detail = loaded_obj.get("best_detail") or {}
        opt_apy = detail.get("expected_apy_pct")
        if not isinstance(opt_apy, (int, float)):
            return None

        # Полный список переборов оптимизатора лежит в исходном файле; перечитаем
        # его, чтобы найти строку с текущими границами (best_detail его не несёт).
        try:
            raw = json.loads(self.params_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, ValueError):
            return None
        results = raw.get("all_results")
        if not isinstance(results, list):
            return None

        def _match(p: dict) -> bool:
            return (
                abs(float(p.get("t1_cap", -1)) - cur["t1_cap"]) < 1e-9
                and abs(float(p.get("t2_cap", -1)) - cur["t2_cap"]) < 1e-9
                and abs(float(p.get("cash_buffer", -1)) - cur["cash_buffer"]) < 1e-9
            )

        cur_apys = [
            r["expected_apy_pct"]
            for r in results
            if isinstance(r, dict)
            and isinstance(r.get("params"), dict)
            and _match(r["params"])
            and isinstance(r.get("expected_apy_pct"), (int, float))
        ]
        if not cur_apys:
            return None
        # Берём максимум среди строк с текущими cap'ами (разные rebalance_threshold).
        cur_apy = max(cur_apys)
        return round(float(opt_apy) - float(cur_apy), 4)


def main() -> None:
    """CLI: печатает сравнение в JSON (ничего не пишет на диск)."""
    import argparse

    parser = argparse.ArgumentParser(
        description="AdvisoryConfig — read-only сравнение risk caps vs optimizer"
    )
    parser.add_argument(
        "--params",
        default=str(_DEFAULT_PARAMS_PATH),
        help="Путь к optimized_params.json",
    )
    args = parser.parse_args()

    advisory = AdvisoryConfig(optimized_params_path=args.params)
    print(json.dumps(advisory.get_comparison(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
