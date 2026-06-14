"""Agent mandates — письменный мандат per-агент (SPA-V421 / MP-301).

Каркас агентного слоя (MASTER_PLAN §2, Phase 3): у каждого агента есть
ДЕКЛАРАТИВНЫЙ письменный мандат — роль, расписание, токен-бюджеты,
forbidden-list действий, белый список выходных файлов и режим деградации
при недоступности LLM. Мандаты хранятся как JSON-файлы (по одному на
агента) в ``spa_core/agent_runtime/mandates/``.

Конституционный инвариант проекта (см. ``spa_core/ci/llm_forbidden_lint.py``):
``LLM_FORBIDDEN_AGENTS = {risk, execution, monitoring}`` — детерминированные
домены, которым LLM ЗАПРЕЩЁН на пути принятия капитальных решений. Попытка
создать мандат с ``requires_llm=True`` для такого имени → ``ValueError``
прямо в конструкторе: запрет невозможно обойти, не упав.

STRICTLY READ-ONLY (SPA-BL-011): модуль не импортирует LLM SDK, web3 или
сетевые библиотеки — pure stdlib. Единственный side effect — атомарная
запись мандат-файла в :func:`save_mandate` (tmp + ``os.replace``).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Union

log = logging.getLogger("spa.agent_runtime.mandate")

# Конституция проекта: детерминированные агенты, которым LLM запрещён.
# Зеркалит spa_core/ci/llm_forbidden_lint.py (risk/execution/allocator dirs);
# "monitoring" — feed-health/мониторинг (SPA-BL-011 freeze).
LLM_FORBIDDEN_AGENTS = frozenset({"risk", "execution", "monitoring"})

VALID_DEGRADATION_MODES = frozenset({"skip", "deterministic-only"})

DEFAULT_MANDATES_DIR = Path(__file__).resolve().parent / "mandates"

SCHEMA_VERSION = 1


@dataclass
class AgentMandate:
    """Письменный мандат одного агента. Валидируется при создании."""

    name: str
    role: str
    schedule: str                       # "weekly" | "daily" | "per-cycle" | "on-demand" | ...
    token_budget_per_run: int
    token_budget_daily: int
    forbidden_actions: List[str] = field(default_factory=list)
    allowed_outputs: List[str] = field(default_factory=list)
    requires_llm: bool = False
    degradation_mode: str = "skip"      # "skip" | "deterministic-only"

    def __post_init__(self) -> None:
        problems: List[str] = []

        if not isinstance(self.name, str) or not self.name.strip():
            problems.append("name: must be a non-empty string")
        if not isinstance(self.role, str) or not self.role.strip():
            problems.append("role: must be a non-empty string")
        if not isinstance(self.schedule, str) or not self.schedule.strip():
            problems.append("schedule: must be a non-empty string")

        if not isinstance(self.token_budget_per_run, int) or isinstance(self.token_budget_per_run, bool) \
                or self.token_budget_per_run <= 0:
            problems.append("token_budget_per_run: must be a positive int")
        if not isinstance(self.token_budget_daily, int) or isinstance(self.token_budget_daily, bool) \
                or self.token_budget_daily <= 0:
            problems.append("token_budget_daily: must be a positive int")
        if (isinstance(self.token_budget_per_run, int) and isinstance(self.token_budget_daily, int)
                and not isinstance(self.token_budget_per_run, bool)
                and self.token_budget_per_run > 0 and self.token_budget_daily > 0
                and self.token_budget_per_run > self.token_budget_daily):
            problems.append("token_budget_per_run: must not exceed token_budget_daily")

        if not isinstance(self.forbidden_actions, list) \
                or not all(isinstance(a, str) and a.strip() for a in self.forbidden_actions):
            problems.append("forbidden_actions: must be a list of non-empty strings")
        if not isinstance(self.allowed_outputs, list) \
                or not all(isinstance(a, str) and a.strip() for a in self.allowed_outputs):
            problems.append("allowed_outputs: must be a list of non-empty strings")

        if not isinstance(self.requires_llm, bool):
            problems.append("requires_llm: must be a bool")
        if self.degradation_mode not in VALID_DEGRADATION_MODES:
            problems.append(
                f"degradation_mode: {self.degradation_mode!r} not in "
                f"{sorted(VALID_DEGRADATION_MODES)}"
            )

        # ЖЁСТКИЙ ИНВАРИАНТ: детерминированным агентам LLM запрещён.
        if isinstance(self.name, str) and self.name.strip().lower() in LLM_FORBIDDEN_AGENTS \
                and self.requires_llm is True:
            problems.append(
                f"name: agent {self.name!r} is in LLM_FORBIDDEN_AGENTS "
                f"({sorted(LLM_FORBIDDEN_AGENTS)}) and must NEVER have "
                "requires_llm=True (project constitution, see "
                "spa_core/ci/llm_forbidden_lint.py)"
            )

        if problems:
            raise ValueError(
                "invalid AgentMandate: " + "; ".join(problems)
            )

    # ── (де)сериализация ──────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["schema_version"] = SCHEMA_VERSION
        return d

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "AgentMandate":
        if not isinstance(raw, dict):
            raise ValueError("invalid AgentMandate: payload must be a JSON object")
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in raw.items() if k in known}
        missing = {"name", "role", "schedule", "token_budget_per_run",
                   "token_budget_daily"} - set(kwargs)
        if missing:
            raise ValueError(
                f"invalid AgentMandate: missing required fields {sorted(missing)}"
            )
        return cls(**kwargs)


# ─── Загрузка / сохранение мандат-файлов ─────────────────────────────────────


def load_mandate_file(path: Union[str, Path]) -> AgentMandate:
    """Прочитать один ``*.json`` мандат. ValueError при битом JSON/схеме."""
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load mandate {p.name}: {exc}") from exc
    return AgentMandate.from_dict(raw)


def load_all_mandates(
    mandates_dir: Union[str, Path] = DEFAULT_MANDATES_DIR,
) -> Dict[str, AgentMandate]:
    """Загрузить все мандаты из директории → ``{name: AgentMandate}``.

    Битый файл НЕ валит остальные — логируется и пропускается (повреждённый
    мандат эквивалентен отсутствию мандата: агент просто не получит допуск).
    Дубликат имени в двух файлах → ValueError (двусмысленный мандат опаснее
    отсутствующего).
    """
    root = Path(mandates_dir)
    mandates: Dict[str, AgentMandate] = {}
    if not root.is_dir():
        return mandates
    for path in sorted(root.glob("*.json")):
        try:
            mandate = load_mandate_file(path)
        except ValueError as exc:
            log.warning("skipping broken mandate %s: %s", path.name, exc)
            continue
        if mandate.name in mandates:
            raise ValueError(
                f"duplicate mandate for agent {mandate.name!r} in {path.name}"
            )
        mandates[mandate.name] = mandate
    return mandates


def save_mandate(
    mandate: AgentMandate,
    mandates_dir: Union[str, Path] = DEFAULT_MANDATES_DIR,
) -> Path:
    """Атомарно сохранить мандат в ``<dir>/<name>.json`` (tmp + os.replace)."""
    root = Path(mandates_dir)
    root.mkdir(parents=True, exist_ok=True)
    out = root / f"{mandate.name}.json"
    tmp = out.with_name(f".{mandate.name}_{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps(mandate.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, out)
    finally:
        if tmp.exists():
            tmp.unlink()
    return out
