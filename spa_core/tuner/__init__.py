"""spa_core.tuner — Allocation Tuner (MP-207).

Модуль оптимизации аллокации на исторических данных.
Grid-search, pure Python stdlib, без внешних зависимостей.
"""
from spa_core.tuner.allocation_tuner import (
    AllocationTuner,
    TunerConstraints,
    TunerResult,
    run_allocation_tuner,
)

__all__ = [
    "AllocationTuner",
    "TunerConstraints",
    "TunerResult",
    "run_allocation_tuner",
]
