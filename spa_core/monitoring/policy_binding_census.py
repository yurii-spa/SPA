#!/usr/bin/env python3
"""Какой потолок СВЯЗЫВАЛ каждое исполненное состояние книги — и определён ли ответ.

Критерий §49 `Risk` приказа владельца «Portfolio CIO»
(`inbox-task-portfolio-cio-dynamic-capital-alloc`), цикл #705.

Дословно критерий звучит так: **«Risk Policy невозможно обойти»**. До этого
прибора он был ПРОЗОЙ о коде: гейт детерминирован, `approved=False` никем не
переопределяется, на это есть тесты. Ни один из них не спрашивал того, что
спрашивает владелец, — **не нарушала ли объявленные потолки книга, которая
РЕАЛЬНО стояла**. «Модуль есть, тесты зелёные» ≠ «работает»
(`.claude/rules/acceptance.md`).

Что прибор меряет
------------------------------------------------------------------------------
Две разные вещи, и не смешивает их:

1. **Деньги.** Каждое состояние `to_allocation` из журнала ходов
   (`data/trades.json`) переигрывается против ОБЪЯВЛЕННЫХ порогов
   `spa_core.risk.policy.RiskConfig` — концентрация по тиру, суммарные T2/T3,
   минимальный кэш, потолок числа позиций. Вопрос: нарушала ли книга потолок,
   который на тот момент СУЩЕСТВОВАЛ.
2. **Ярлык.** Потолок выбирается ТИРОМ протокола, а тир живёт в НЕСКОЛЬКИХ
   копиях. Если копии спорят, ответ «нарушен ли потолок» не определён — и это
   отдельный исход, а не повод выбрать копию.

Почему «нельзя переопределить вердикт» ≠ «нельзя обойти»
------------------------------------------------------------------------------
Вердикт гейта действительно неоспорим. Но потолок на протокол выбирается его
ТИРОМ, и тир — это ВХОД гейта, а не его решение. Ярлык, сдвинувшийся в одной
копии из пяти, меняет связывающий потолок вдвое (T1 40 % → T2 20 %), не
затронув ни строки риск-логики и не породив ни одного `approved=False`.
Потолок обходят не доводом, а ЯРЛЫКОМ.

Замер, ради которого прибор написан (цикл #705, журнал 34 хода):
`morpho_steakhouse` стоял **40 % книги $100 000** в четырёх подряд исполненных
состояниях (T016–T019, 27.08) — ровно потолок T1 — при потолке T2 20 %;
суммарный T2 при этом стоял 75–78 % против потолка 50 %.
[ADR-173](../../docs/decisions/ADR-173-risk-axes-and-tier-drift-fixed-in-tandem.md) (30.08,
ответ владельца) закрепил тир T2 и назвал причину дефектом — «гейт верил адаптеру
на слово о его тире», — сославшись на
[ADR-070](../../docs/decisions/ADR-070-owner-decisions-2026-08-07-queue-clearance.md) §6
(07.08, риск-оценка равна `morpho_blue`). Починена была ОДНА копия ярлыка.
Население копий не мерил никто, и на день замера **две копии из пяти всё ещё
называют тир иначе, чем ADR владельца**.

Своих чисел у прибора нет ни одного
------------------------------------------------------------------------------
Все пороги читаются из `RiskConfig` (§22 приказа: «Все значения должны быть
config/policy. **Не hardcode**»). Второй копии порогов здесь нет, и
`RiskConfig` недоступен ⇒ **третий исход**, а не подставленное умолчание.

Дата рождения порога тоже ИЗМЕРЯЕТСЯ, а не вписывается
------------------------------------------------------------------------------
Судить состояние 20.06 потолком, появившимся 28.06, значило бы назвать
нарушением то, чего в тот день не существовало, — и первый черновик этого
прибора именно так и посчитал (8 «нарушений» вместо 4). Поэтому дата, с
которой порог ОБЪЯВЛЕН, берётся из истории `spa_core/risk/policy.py`
(`git log -S<имя поля>`), а не из памяти автора.

История репозитория — вход ХАРНЕССА, а не окружения: при `fetch-depth: 1`
(умолчание `actions/checkout`) её НЕТ, и тогда прибор говорит
`rule_birth_unmeasured` и состояния старше порога объявляет **НЕ ИЗМЕРЕННЫМИ**,
а не чистыми (`.claude/rules/deployment.md`, раздел про git-окружение).

Что прибор НЕ доказывает
------------------------------------------------------------------------------
Отсутствие нарушений в журнале НЕ доказывает, что политику обойти нельзя:
доказательство одностороннее, и сильная сторона у него отрицательная. Найденное
нарушение доказывает обход; ненайденное не доказывает ничего, и это сказано
вслух здесь, а не только в ADR.

Прибор ТОЛЬКО ЧИТАЕТ. Ни RiskPolicy, ни стоп-кран, ни аллокатор, ни ярлык тира,
ни живой трек он не трогает и ничего не чинит: расхождение ярлыка — предмет
владельца (тир меняется ADR-ом), и подправить копию «заодно» было бы ровно тем
молчаливым сдвигом ярлыка, который прибор ищет.

LLM запрещён. Только stdlib. Коды возврата: 0 — чисто · 1 — находка названа ·
2 — НЕ ИЗМЕРЕНО.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.utils.atomic import atomic_save
from spa_core.utils.observation import observed

ROOT = Path(__file__).resolve().parents[2]

ARTIFACT_NAME = "policy_binding_census.json"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Пороги, которые прибор переигрывает, и ИМЯ поля `RiskConfig`, из которого
#: читается значение. Имя же служит ключом к истории файла политики: дата
#: рождения порога измеряется по появлению этого имени, а не по памяти.
#: Значений здесь нет НИ ОДНОГО — только имена (§22: «Не hardcode»).
THRESHOLD_FIELDS: Tuple[str, ...] = (
    "max_concentration_t1",
    "max_concentration_t2",
    "max_total_t2_allocation",
    "max_total_t3_allocation",
    "min_cash_pct",
    "max_protocols",
)

#: Копии ярлыка тира. Порядок — порядок ОБЪЯВЛЕНИЯ, не приоритета: прибор не
#: выбирает копию, он их СВЕРЯЕТ. Приоритет есть у гейта
#: (`risk_gate.policy_tier`: снимок оркестратора, затем файл реестра), и он
#: назван в поле `gate_reads` отчёта, чтобы читатель видел, какая из спорящих
#: копий действительно связывает деньги.
LABEL_SOURCES: Tuple[str, ...] = (
    "orchestrator_snapshot",   # data/adapter_orchestrator_status.json
    "registry_file_live",      # data/adapter_registry.json (рабочее дерево)
    "registry_file_committed", # data/adapter_registry.json (канон git)
    "adapter_registry_code",   # spa_core/adapters/__init__.py :: ADAPTER_REGISTRY
    "adapter_metadata_code",   # spa_core/adapters/registry.py  :: ADAPTER_METADATA
)

#: Копии, которые читает САМ гейт (`spa_core/paper_trading/risk_gate.py`
#: :func:`policy_tier`), в его порядке. Остальные копии читают соседи — и
#: `.claude/rules/adapters.md` помнит, как `ADAPTER_METADATA` три месяца врал
#: `house_view_gap` именно потому, что был «тем же реестром» по имени.
GATE_READS: Tuple[str, ...] = ("orchestrator_snapshot", "registry_file_live")


class NotMeasured(RuntimeError):
    """Замер не состоялся. Причина обязана быть названа (инв. #17)."""


# ─── чтение входов ───────────────────────────────────────────────────────────


def _now(now: Optional[datetime] = None) -> datetime:
    return now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)


def _parse_day(raw: object) -> Optional[str]:
    """Календарный день ISO из отметки времени, либо ``None``."""
    text = str(raw or "").strip()
    return text[:10] if len(text) >= 10 and text[4] == "-" and text[7] == "-" else None


def _num(value: object) -> Optional[float]:
    """Число или ``None``. ``bool`` числом не является — «да» не сумма."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def load_thresholds(config: Any = None) -> Dict[str, float]:
    """Объявленные пороги из ``RiskConfig`` — по ИМЕНАМ, без второй копии чисел.

    Поле отсутствует или не число ⇒ :class:`NotMeasured`: политика, у которой
    прибор не нашёл объявленного порога, не судится подставленным.
    """
    if config is None:
        try:
            from spa_core.risk.policy import RiskConfig
        except Exception as exc:  # noqa: BLE001
            raise NotMeasured(f"RiskConfig не импортируется ({exc}) — порогов нет") from exc
        config = RiskConfig()
    out: Dict[str, float] = {}
    for field in THRESHOLD_FIELDS:
        value = _num(getattr(config, field, None))
        if value is None:
            raise NotMeasured(
                f"порог `{field}` не объявлен в RiskConfig (или не число) — "
                f"судить им нельзя")
        out[field] = value
    return out


def history_available(root: Path) -> Tuple[bool, Optional[str]]:
    """Есть ли у дерева ПОЛНАЯ история — и если нет, то почему.

    Вопрос отдельный и задаётся ПЕРВЫМ намеренно. Поверхностный клон
    (`fetch-depth: 1` у `actions/checkout`, `.git/shallow` на рабочем Маке)
    на `git log -S…` отвечает ДАТОЙ — датой границы обрезки, а не рождения
    порога. Замер 27.09 на прод-дереве: `rev-list --count HEAD` = 71, и все
    шесть порогов «родились» 2026-09-21, то есть прибор получил ответ и поверил
    ему. Это fail-OPEN той же породы, что `pyflakes`, вернувший 0: отсутствие
    инструмента обязано быть ТРЕТЬИМ исходом, а не числом
    (`.claude/rules/deployment.md`, раздел про git-окружение).
    """
    try:
        done = subprocess.run(["git", "rev-parse", "--is-shallow-repository"],
                              cwd=str(root), capture_output=True, text=True, timeout=30)
    except Exception as exc:  # noqa: BLE001
        return False, f"git не ответил ({type(exc).__name__}: {exc})"
    if done.returncode != 0:
        return False, (f"git rev-parse --is-shallow-repository — код "
                       f"{done.returncode} ({(done.stderr or '').strip()[:120]})")
    if (done.stdout or "").strip() == "true":
        return False, ("дерево — ПОВЕРХНОСТНЫЙ клон: `git log` вернёт дату "
                       "границы обрезки, а не рождения порога")
    return True, None


def threshold_birth(root: Path, fields: Tuple[str, ...] = THRESHOLD_FIELDS,
                    *, policy_path: str = "spa_core/risk/policy.py",
                    ) -> Tuple[Dict[str, Optional[str]], Optional[str]]:
    """День, когда имя порога ВПЕРВЫЕ появилось в файле политики.

    Возвращает ``(даты, причина-если-не-измерено)``. ``None`` у поля = не
    измерено: истории нет, git недоступен, имя не найдено. Отсутствие даты НЕ
    читается как «порог был всегда» и НЕ читается как «порога не было» —
    вызывающий обязан развести это третьим исходом.
    """
    full, reason = history_available(root)
    if not full:
        return {field: None for field in fields}, reason
    births: Dict[str, Optional[str]] = {}
    for field in fields:
        births[field] = None
        try:
            done = subprocess.run(
                ["git", "log", "--format=%ad", "--date=short", "--reverse",
                 f"-S{field}", "--", policy_path],
                cwd=str(root), capture_output=True, text=True, timeout=60,
            )
        except Exception:  # noqa: BLE001 — git нет / не ответил ⇒ не измерено
            continue
        if done.returncode != 0:
            continue
        lines = [ln.strip() for ln in (done.stdout or "").splitlines() if ln.strip()]
        if lines:
            births[field] = lines[0]
    return births, None


def read_journal(data_dir: Path) -> List[Dict[str, Any]]:
    """Исполненные состояния книги из журнала ходов. Пусто ⇒ :class:`NotMeasured`."""
    path = data_dir / "trades.json"
    if not path.is_file():
        raise NotMeasured(f"{path.name} не найден — исполненных состояний нет")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise NotMeasured(f"{path.name} не разобран ({exc})") from exc
    moves = doc if isinstance(doc, list) else (doc or {}).get("trades")
    if not isinstance(moves, list) or not moves:
        raise NotMeasured(f"{path.name} не несёт ни одного хода — переигрывать нечего")
    return [m for m in moves if isinstance(m, dict)]


def _tier(raw: object) -> Optional[str]:
    """Канонический разбор ярлыка — ОДИН, общий с гейтом (ADR-359)."""
    from spa_core.risk.policy import tier_from_registry
    return tier_from_registry(raw)


def _labels_from_snapshot(data_dir: Path) -> Dict[str, Optional[str]]:
    doc = json.loads((data_dir / "adapter_orchestrator_status.json").read_text("utf-8"))
    rows = doc.get("adapters") if isinstance(doc, dict) else None
    out: Dict[str, Optional[str]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        key = row.get("protocol") or row.get("key") or row.get("name")
        if isinstance(key, str) and key:
            out[key] = _tier(row.get("tier"))
    return out


def _labels_from_registry_doc(doc: object) -> Dict[str, Optional[str]]:
    adapters = doc.get("adapters") if isinstance(doc, dict) else None
    if not isinstance(adapters, dict):
        raise NotMeasured("в реестре нет словаря `adapters`")
    return {k: _tier(v.get("tier")) for k, v in adapters.items() if isinstance(v, dict)}


def read_label_sources(root: Path, data_dir: Path) -> Dict[str, Dict[str, Any]]:
    """Все копии ярлыка тира. Отказ КАЖДОЙ копии называется, а не глотается.

    Возвращает ``{имя копии: {"labels": {...}} | {"unreadable": "<причина>"}}``.
    Нечитаемая копия — не пустая копия: пустая молча согласилась бы со всеми.
    """
    out: Dict[str, Dict[str, Any]] = {}

    def attempt(name: str, fn) -> None:
        try:
            out[name] = {"labels": fn()}
        except Exception as exc:  # noqa: BLE001 — причина названа, не проглочена
            out[name] = {"unreadable": f"{type(exc).__name__}: {exc}"}

    attempt("orchestrator_snapshot", lambda: _labels_from_snapshot(data_dir))
    attempt("registry_file_live", lambda: _labels_from_registry_doc(
        json.loads((data_dir / "adapter_registry.json").read_text("utf-8"))))
    attempt("registry_file_committed", lambda: _labels_from_registry_doc(
        json.loads(_git_show(root, "data/adapter_registry.json"))))
    attempt("adapter_registry_code", _labels_from_adapter_registry)
    attempt("adapter_metadata_code", _labels_from_adapter_metadata)
    return out


def _git_show(root: Path, rel: str, ref: str = "HEAD") -> str:
    done = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=str(root),
                          capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        raise NotMeasured(f"git show {ref}:{rel} — код {done.returncode} "
                          f"({(done.stderr or '').strip()[:120]})")
    return done.stdout


def _labels_from_adapter_registry() -> Dict[str, Optional[str]]:
    """``ADAPTER_REGISTRY`` — список кортежей ``(ключ, тир, класс)``, 36 записей.

    Тир здесь ВТОРОЙ элемент кортежа, а не атрибут класса: черновик прибора
    спрашивал `getattr(cls, "TIER")` и получал `None` у всех 36 — то есть
    «копия со всеми согласна», хотя не прочитал её вовсе. Форму копии надо
    ЗНАТЬ, иначе нечитаемое выдаёт себя за согласное.
    """
    from spa_core.adapters import ADAPTER_REGISTRY
    out: Dict[str, Optional[str]] = {}
    for entry in ADAPTER_REGISTRY:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        key = entry[0]
        if isinstance(key, str) and key:
            out[key] = _tier(entry[1])
    if not out:
        raise NotMeasured("ADAPTER_REGISTRY не дал ни одного ключа")
    return out


def _labels_from_adapter_metadata() -> Dict[str, Optional[str]]:
    from spa_core.adapters.registry import ADAPTER_METADATA
    out = {k: _tier(v.get("tier")) for k, v in (ADAPTER_METADATA or {}).items()
           if isinstance(v, dict)}
    if not out:
        raise NotMeasured("ADAPTER_METADATA не дал ни одного ключа")
    return out


# ─── связывание ярлыка ───────────────────────────────────────────────────────


def bind_label(key: str, sources: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Тир протокола по ВСЕМ копиям: определён, спорен или неизвестен.

    * ``determined`` — все копии, у которых ключ ЕСТЬ, назвали один тир;
    * ``disagreement`` — копии назвали РАЗНОЕ; тир не выбирается прибором;
    * ``unknown`` — ни одна копия ключа не знает (или знает, но не тиром).

    Копия, у которой ключа нет вовсе, голоса не имеет: «не знаю» — не мнение.
    """
    votes: Dict[str, str] = {}
    for name in LABEL_SOURCES:
        entry = sources.get(name) or {}
        labels = entry.get("labels")
        if not isinstance(labels, dict) or key not in labels:
            continue
        tier = labels.get(key)
        if tier is not None:
            votes[name] = tier
    distinct = sorted(set(votes.values()))
    if not distinct:
        return {"key": key, "state": "unknown", "votes": votes, "tier": None}
    if len(distinct) == 1:
        return {"key": key, "state": "determined", "votes": votes, "tier": distinct[0]}
    gate_votes = sorted({t for n, t in votes.items() if n in GATE_READS})
    return {"key": key, "state": "disagreement", "votes": votes, "tier": None,
            "candidates": distinct,
            "gate_reads": {n: votes[n] for n in GATE_READS if n in votes},
            "gate_determined": len(gate_votes) == 1}


# ─── переигрывание состояния ─────────────────────────────────────────────────


def _positions(allocation: object) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for key, raw in (allocation or {}).items() if isinstance(allocation, dict) else ():
        value = _num(raw)
        if isinstance(key, str) and value is not None and round(value, 2) != 0.0:
            out[key] = round(value, 2)
    return out


def replay_state(positions: Dict[str, float], capital_usd: float,
                 tiers: Dict[str, Optional[str]],
                 thresholds: Dict[str, float]) -> Dict[str, Any]:
    """Нарушения ОБЪЯВЛЕННЫХ порогов в одном исполненном состоянии книги.

    Проверяются ВСЕ пороги, как они объявлены сегодня. Вопрос «существовал ли
    порог в тот день» здесь НЕ решается намеренно: он требует истории
    репозитория, а история — вход харнесса, которого может не быть. Смешать два
    вопроса значило бы тихо превратить «не знаю, был ли порог» в «порога не
    было» — ровно тот подлог, против которого написан инв. #17.

    Каждое нарушение несёт ИМЯ поля порога, чтобы вызывающий мог спросить
    историю именно о нём, а не обо всех шести.
    """
    violations: List[Dict[str, Any]] = []
    unpriced: List[str] = []
    no_per_protocol: Dict[str, List[str]] = {}
    deployed = sum(positions.values())
    cash_pct = (capital_usd - deployed) / capital_usd

    per_tier_total: Dict[str, float] = {}
    for key, usd in sorted(positions.items()):
        tier = tiers.get(key)
        share = usd / capital_usd
        if tier is not None:
            per_tier_total[tier] = per_tier_total.get(tier, 0.0) + share
        field = ("max_concentration_t1" if tier == "T1"
                 else "max_concentration_t2" if tier == "T2" else None)
        if tier is None:
            # Тир НЕ НАЗВАН ⇒ потолок на протокол выбрать нечем. Молча
            # пропустить такую позицию значило бы объявить книгу чистой, не
            # посмотрев на 40 % её денег: именно так первый прогон этого прибора
            # напечатал `violations: []` у состояния, которое ЧЕТЫРЕ копии
            # ярлыка из пяти называли двукратным превышением. Fail-OPEN тише
            # красного теста, поэтому и опаснее.
            unpriced.append(key)
        elif field is None:
            # Тир НАЗВАН, но персонального потолка у этого тира в `RiskConfig`
            # не объявлено (T3 живёт только суммарным `max_total_t3_allocation`).
            # Это НЕ «не измерено»: мерить нечего по построению политики, и
            # смешать два случая значило бы объявить исправный T3 слепым пятном.
            no_per_protocol.setdefault(tier, []).append(key)
        elif share > thresholds[field] + 1e-9:
            violations.append({"field": field, "text": (
                f"concentration:{key}[{tier}] {share:.2%} > "
                f"{thresholds[field]:.0%}"), "usd": round(usd, 2)})

    for tier, field in (("T2", "max_total_t2_allocation"),
                        ("T3", "max_total_t3_allocation")):
        total = per_tier_total.get(tier, 0.0)
        if total > thresholds[field] + 1e-9:
            violations.append({"field": field, "text": (
                f"{tier.lower()}_total {total:.2%} > {thresholds[field]:.0%}")})

    if cash_pct < thresholds["min_cash_pct"] - 1e-9:
        violations.append({"field": "min_cash_pct", "text": (
            f"cash {cash_pct:.2%} < {thresholds['min_cash_pct']:.0%}")})

    if len(positions) > thresholds["max_protocols"]:
        violations.append({"field": "max_protocols", "text": (
            f"protocols {len(positions)} > {int(thresholds['max_protocols'])}")})

    return {"violations": violations,
            "unpriced_keys": sorted(unpriced),
            "no_per_protocol_cap": {t: sorted(v) for t, v in sorted(no_per_protocol.items())},
            "unpriced_usd": round(sum(positions[k] for k in unpriced), 2),
            "deployed_usd": round(deployed, 2),
            "cash_pct": round(cash_pct, 6),
            "tier_totals": {t: round(v, 6) for t, v in sorted(per_tier_total.items())},
            "protocols": len(positions)}


def replay_by_label_source(positions: Dict[str, float], capital_usd: float,
                           sources: Dict[str, Dict[str, Any]],
                           consensus: Dict[str, Optional[str]],
                           thresholds: Dict[str, float]) -> Dict[str, Any]:
    """Переиграть состояние ОТДЕЛЬНО по каждой читаемой копии ярлыка.

    Отвечает на вопрос, которого не задаёт ни один существующий сторож:
    **зависит ли вердикт о ЭТИХ деньгах от того, какую копию ярлыка прочесть.**
    Спор копий сам по себе вердикта не меняет — `morpho_steakhouse` на 5 %
    книги проходит и как T1 (40 %), и как T2 (20 %). Поэтому `undetermined`
    ставится ТОЛЬКО там, где набор нарушений у копий РАЗНЫЙ; иначе спор остаётся
    находкой уровня ярлыка, а состояние судится по согласному вердикту.

    Ключ, которого копия не знает, берётся из ``consensus`` — иначе копия из 22
    записей объявляла бы «нарушений нет» просто потому, что не знает половины
    книги (это и есть fail-OPEN через незнание).
    """
    per_source: Dict[str, List[str]] = {}
    structured: Dict[str, List[Dict[str, Any]]] = {}
    for name in LABEL_SOURCES:
        labels = (sources.get(name) or {}).get("labels")
        if not isinstance(labels, dict):
            continue
        tiers = {k: (labels.get(k) if labels.get(k) is not None else consensus.get(k))
                 for k in positions}
        verdict = replay_state(positions, capital_usd, tiers, thresholds)
        structured[name] = list(verdict["violations"])
        if verdict["unpriced_keys"]:
            # Копия, не назвавшая тир держимого ключа, НЕ голосует «чисто»:
            # её ответ — «не измерено», и он отличим от обоих вердиктов.
            per_source[name] = ["НЕ ИЗМЕРЕНО: тир не назван ни этой копией, ни "
                               "согласием остальных — "
                               + ", ".join(verdict["unpriced_keys"])]
        else:
            per_source[name] = sorted(str(v["text"]) for v in verdict["violations"])
    distinct = {tuple(v) for v in per_source.values()}
    # Отдельно — вердикт по тем копиям, которые читает САМ гейт. Спор пяти копий
    # честно даёт «не определено», но на деньги связывает то, что прочёл гейт, и
    # умолчать об этом значило бы утопить деньги в оговорке: у T016–T019 обе
    # копии гейта согласно называют двукратное превышение, а пятая копия —
    # `ADAPTER_METADATA` — одна тянет вердикт в «не определено».
    gate = {n: per_source[n] for n in GATE_READS if n in per_source}
    gate_distinct = {tuple(v) for v in gate.values()}
    agreed = len(gate_distinct) == 1
    first_gate = next((n for n in GATE_READS if n in structured), None)
    return {"per_source": per_source, "label_dependent": len(distinct) > 1,
            "gate_sources": gate,
            "gate_agrees": agreed,
            "gate_violations": (sorted(next(iter(gate_distinct))) if agreed else None),
            "gate_violations_structured": (
                structured.get(first_gate) if agreed and first_gate else None)}


# ─── перепись ────────────────────────────────────────────────────────────────


def run_census(root: Path, data_dir: Path, now: Optional[datetime] = None,
               config: Any = None) -> Dict[str, Any]:
    """Полный замер. Любая неудача входа поднимает :class:`NotMeasured`."""
    stamp = _now(now)
    thresholds = load_thresholds(config)
    births, birth_reason = threshold_birth(root)
    moves = read_journal(data_dir)
    sources = read_label_sources(root, data_dir)

    readable = [n for n in LABEL_SOURCES if "labels" in (sources.get(n) or {})]
    if not readable:
        raise NotMeasured(
            "ни одна копия ярлыка тира не прочитана — потолок на протокол "
            "выбрать нечем: " + "; ".join(
                f"{n}: {(sources.get(n) or {}).get('unreadable')}" for n in LABEL_SOURCES))

    held_keys = sorted({k for m in moves for k in _positions(m.get("to_allocation"))})
    bindings = {k: bind_label(k, sources) for k in held_keys}
    disputed = sorted(k for k, b in bindings.items() if b["state"] == "disagreement")
    unknown = sorted(k for k, b in bindings.items() if b["state"] == "unknown")
    tiers = {k: b["tier"] for k, b in bindings.items()}

    states: List[Dict[str, Any]] = []
    for move in moves:
        positions = _positions(move.get("to_allocation"))
        capital = _num(move.get("capital"))
        day = _parse_day(move.get("ts"))
        record: Dict[str, Any] = {
            "trade_id": move.get("trade_id"),
            "day": day,
            "capital_usd": capital,
        }
        if capital is None or capital <= 0 or not positions or day is None:
            record.update(outcome="unmeasured", reason=(
                "у хода нет дня" if day is None else
                "у хода нет капитала" if capital is None or capital <= 0 else
                "состояние пусто"))
            states.append(record)
            continue

        verdict = replay_state(positions, capital, tiers, thresholds)
        record.update({k: v for k, v in verdict.items() if k != "violations"})
        # `violations` — ЗАМЕР, и при неназванном тире его нет. Пустой список
        # здесь читался бы как «посмотрели и чисто» (инв. #17: отсутствие
        # наблюдения обязано быть ОТДЕЛЬНЫМ значением, а не пустотой).
        if verdict["unpriced_keys"]:
            record["violations"] = None
            record["violations_unmeasured_reason"] = (
                "потолок на протокол не выбран — тир не назван согласием копий: "
                + ", ".join(verdict["unpriced_keys"])
                + f" (${verdict['unpriced_usd']:,.2f})")
        else:
            record["violations"] = [str(v["text"]) for v in verdict["violations"]]

        broken = sorted({str(v["field"]) for v in verdict["violations"]})
        record["broken_thresholds"] = broken
        record["thresholds_not_yet_declared"] = sorted(
            f for f in broken
            if births.get(f) is not None and str(births[f]) > day)
        record["threshold_birth_unmeasured"] = sorted(
            f for f in broken if births.get(f) is None)

        dependence = replay_by_label_source(positions, capital, sources, tiers, thresholds)
        record["label_dependent"] = dependence["label_dependent"]
        if dependence["label_dependent"]:
            record["verdict_by_label_source"] = dependence["per_source"]
        record["gate_agrees"] = dependence["gate_agrees"]
        record["gate_violations"] = dependence["gate_violations"]
        # Порог, которого в тот день ещё не существовало, обходом не является —
        # и у ответа ПРО ДЕНЬГИ то же правило, что у сводного вердикта. Первый
        # черновик печатал «нарушено в 8 состояниях», молча складывая 27.08
        # (потолок стоял с 14.06) с 20.06 (`max_protocols` родился 28.06).
        gate_fields = sorted({str(v.get("field")) for v in
                              (dependence["gate_violations_structured"] or [])})
        record["gate_broken_thresholds"] = gate_fields
        record["gate_broken_not_yet_declared"] = sorted(
            f for f in gate_fields
            if births.get(f) is not None and str(births[f]) > day)
        record["gate_broken_birth_unmeasured"] = sorted(
            f for f in gate_fields if births.get(f) is None)

        unknown_here = sorted(k for k in positions if bindings[k]["state"] == "unknown")
        record["unknown_tier_keys"] = unknown_here

        # Порядок ветвей — порядок СИЛЫ утверждения, и он не произволен.
        # Зависимость вердикта от копии ярлыка старше самого вердикта: пока не
        # решено, ЧЕМ судить, «нарушено» и «чисто» оба преждевременны.
        if dependence["label_dependent"]:
            record["outcome"] = "undetermined"
            record["reason"] = ("вердикт ЗАВИСИТ от того, какую копию ярлыка "
                                "тира прочесть — потолок не определён")
        elif unknown_here:
            record["outcome"] = "unmeasured"
            record["reason"] = ("тир неизвестен ни одной копии: "
                                + ", ".join(unknown_here))
        elif not broken:
            record["outcome"] = "clean"
        elif record["threshold_birth_unmeasured"]:
            record["outcome"] = "violation_rule_birth_unmeasured"
            record["reason"] = (
                "потолок нарушен, но существовал ли он в тот день — НЕ ИЗМЕРЕНО "
                f"({', '.join(record['threshold_birth_unmeasured'])}): "
                f"{birth_reason or 'история не прочитана'}")
        elif set(broken) == set(record["thresholds_not_yet_declared"]):
            record["outcome"] = "rule_postdates_state"
            record["reason"] = (
                "нарушены только те потолки, которых в тот день ещё не "
                f"существовало ({', '.join(record['thresholds_not_yet_declared'])}) "
                "— это не обход политики")
        else:
            record["outcome"] = "violation"
        states.append(record)

    counts: Dict[str, int] = {}
    for record in states:
        counts[record["outcome"]] = counts.get(record["outcome"], 0) + 1

    # Деньги отдельной строкой: сколько состояний нарушают потолок по ТЕМ копиям
    # ярлыка, которые читает гейт. Это и есть ответ про деньги; спор остальных
    # копий — ответ про реестр, и складывать их нельзя.
    def _gate_bucket(record: Dict[str, Any]) -> Optional[str]:
        fields = record.get("gate_broken_thresholds") or []
        if not fields:
            return None
        if record.get("gate_broken_birth_unmeasured"):
            return "birth_unmeasured"
        if set(fields) == set(record.get("gate_broken_not_yet_declared") or []):
            return "rule_postdates_state"
        return "violation"

    gate_violating = [r for r in states if _gate_bucket(r) == "violation"]
    gate_birth_unmeasured = [r for r in states if _gate_bucket(r) == "birth_unmeasured"]
    gate_postdates = [r for r in states if _gate_bucket(r) == "rule_postdates_state"]
    gate_unmeasured = [r for r in states if r.get("gate_agrees") is False]

    latest_violation = next((r for r in reversed(states)
                             if r["outcome"] == "violation"), None)
    present = states[-1] if states else None
    # Вердикт судит НАСТОЯЩЕЕ — состояние, в котором книга СТОИТ сейчас.
    # Сторож, красный от всей истории, красен навсегда и учит себя игнорировать
    # (урок ADR-480); поэтому история остаётся ЗАМЕРОМ в полях, а не статусом.
    present_bad = (present or {}).get("outcome") in (
        "violation", "undetermined", "violation_rule_birth_unmeasured")
    if present_bad:
        status = STATUS_CRITICAL
    elif (disputed or unknown or counts.get("violation")
          or counts.get("undetermined") or counts.get("unmeasured")
          or counts.get("violation_rule_birth_unmeasured")):
        status = STATUS_WARNING
    else:
        status = STATUS_OK

    return {
        "schema": "policy-binding-census-v1",
        "generated_at": stamp.isoformat(),
        "status": status,
        "measured": True,
        "criterion": ("§49 `Risk` приказа владельца «Portfolio CIO»: "
                      "Risk Policy невозможно обойти"),
        "journal": {"path": str(data_dir / "trades.json"), "moves": len(moves)},
        "thresholds": thresholds,
        "threshold_birth": births,
        "threshold_birth_unmeasured_reason": birth_reason,
        "label_sources": {
            name: ({"keys": len((sources[name] or {}).get("labels") or {})}
                   if "labels" in (sources.get(name) or {})
                   else {"unreadable": (sources.get(name) or {}).get("unreadable")})
            for name in LABEL_SOURCES},
        "gate_reads": list(GATE_READS),
        "held_keys": len(held_keys),
        "label_disagreement": {k: bindings[k] for k in disputed},
        "tier_unknown": unknown,
        "counts": counts,
        "gate_binding": {
            "sources": list(GATE_READS),
            "violating_states": [
                {"trade_id": r.get("trade_id"), "day": r.get("day"),
                 "violations": r.get("gate_violations")} for r in gate_violating],
            "violating_count": len(gate_violating),
            "birth_unmeasured_count": len(gate_birth_unmeasured),
            "rule_postdates_count": len(gate_postdates),
            "disagreeing_count": len(gate_unmeasured),
        },
        "states": states,
        "present": {"trade_id": (present or {}).get("trade_id"),
                    "day": (present or {}).get("day"),
                    "outcome": (present or {}).get("outcome")},
        "latest_violation": ({"trade_id": latest_violation["trade_id"],
                              "day": latest_violation["day"],
                              "violations": latest_violation["violations"]}
                             if latest_violation else None),
        "what_it_does_not_prove": (
            "Отсутствие нарушений в журнале НЕ доказывает, что политику обойти "
            "нельзя: доказательство одностороннее, сильная сторона — "
            "отрицательная. Прибор судит СОСТОЯНИЯ книги, а не пути кода, и о "
            "сделках вне журнала не знает ничего."),
    }


def _unmeasured(reason: str, now: datetime) -> Dict[str, Any]:
    return {
        "schema": "policy-binding-census-v1",
        "generated_at": now.isoformat(),
        "status": STATUS_UNMEASURED,
        "measured": False,
        "reason": reason,
        "criterion": ("§49 `Risk` приказа владельца «Portfolio CIO»: "
                      "Risk Policy невозможно обойти"),
    }


# ─── отрисовка ───────────────────────────────────────────────────────────────


def summary_line(report: Dict[str, Any]) -> str:
    if not report.get("measured"):
        return f"НЕ ИЗМЕРЕНО — {report.get('reason')}"
    # `counts` читается ЧЕСТНО: `.get(...) or {}` превратил бы отсутствие сводки
    # в шесть нулей, то есть «не измерено» стало бы «измерено и равно нулю»
    # (инв. #17). Отчёт, объявивший себя измеренным без сводки, — сломанный
    # артефакт, и об этом говорится, а не подставляются нули.
    counts = observed(report, "counts", kind=dict)
    if counts is None:
        return ("НЕ ИЗМЕРЕНО — отчёт объявлен измеренным, но сводки `counts` "
                "в нём нет: считать нечего")
    return ("нарушений {v} · нарушено-но-срок-не-измерен {b} · вердикт зависит "
            "от копии ярлыка {u} · порог младше состояния {p} · не измерено {n} "
            "· чисто {c} — из {t} исполненных состояний".format(
                v=counts.get("violation", 0),
                b=counts.get("violation_rule_birth_unmeasured", 0),
                u=counts.get("undetermined", 0),
                p=counts.get("rule_postdates_state", 0),
                n=counts.get("unmeasured", 0), c=counts.get("clean", 0),
                t=len(report.get("states") or [])))


def format_report(report: Dict[str, Any], limit: int = 8) -> List[str]:
    """Строки для шага 0-офис. Правило отрисовки живёт у ПРОИЗВОДИТЕЛЯ."""
    out: List[str] = []
    if not report.get("measured"):
        out.append(f"[НЕ ИЗМЕРЕНО] {report.get('reason')}")
        return out
    out.append(f"[ОТВЕТ] {summary_line(report)}")
    gate = report.get("gate_binding") or {}
    if gate:
        out.append(f"[ПО КОПИЯМ ГЕЙТА] потолок, СУЩЕСТВОВАВШИЙ в тот день, "
                   f"нарушен в {gate.get('violating_count')} исполненных "
                   f"состояниях · порог младше состояния "
                   f"{gate.get('rule_postdates_count')} · срок порога не измерен "
                   f"{gate.get('birth_unmeasured_count')} · копии гейта спорят "
                   f"{gate.get('disagreeing_count')} "
                   f"(копии risk_gate: {', '.join(gate.get('sources') or [])})")
        for row in (gate.get("violating_states") or [])[:limit]:
            out.append(f"   {row.get('trade_id')} {row.get('day')}: "
                       + "; ".join(row.get("violations") or []))
    for name, info in (report.get("label_sources") or {}).items():
        if "unreadable" in info:
            out.append(f"[КОПИЯ НЕ ПРОЧИТАНА] ярлык тира `{name}`: {info['unreadable']}")
    for key, binding in (report.get("label_disagreement") or {}).items():
        votes = " · ".join(f"{n}={t}" for n, t in (binding.get("votes") or {}).items())
        out.append(f"[ЯРЛЫК СПОРЕН] {key}: {votes} — потолок на протокол "
                   f"выбирается ТИРОМ, значит и потолок не определён")
        if binding.get("gate_determined") is False:
            out.append(f"[ЯРЛЫК СПОРЕН У ГЕЙТА] {key}: {binding.get('gate_reads')} — "
                       f"спорят те самые копии, которые читает risk_gate")
    for key in (report.get("tier_unknown") or []):
        out.append(f"[ТИР НЕИЗВЕСТЕН] {key}: ни одна копия не назвала тир — "
                   f"потолок не выбран (не подставлен)")
    if report.get("threshold_birth_unmeasured_reason"):
        out.append(f"[СРОК НЕ ИЗМЕРЕН] дата, с которой порог объявлен, не "
                   f"прочитана: {report['threshold_birth_unmeasured_reason']} — "
                   f"нарушение НАЗЫВАЕТСЯ, но не выдаётся ни за обход, ни за чистое")
    shown = 0
    for record in report.get("states") or []:
        if record.get("outcome") in ("clean", "rule_postdates_state"):
            continue
        if shown >= limit:
            out.append("… ещё состояния того же рода — полный перечень в артефакте")
            break
        shown += 1
        head = f"[{str(record.get('outcome')).upper()}] {record.get('trade_id')} {record.get('day')}"
        measured = record.get("violations")
        if measured:
            detail = "; ".join(measured)
        elif measured is None:
            detail = str(record.get("violations_unmeasured_reason") or "")
        else:
            detail = "нарушений нет"
        out.append(f"{head}: {detail}")
        if record.get("broken_thresholds"):
            out.append(f"   нарушены пороги: {', '.join(record['broken_thresholds'])}")
        reason = record.get("reason")
        if reason and reason != detail:
            out.append(f"   {reason}")
        if record.get("verdict_by_label_source"):
            for name, rows in record["verdict_by_label_source"].items():
                out.append(f"   по копии `{name}`: "
                           + ("; ".join(rows) if rows else "нарушений нет"))
    for record in report.get("states") or []:
        if record.get("outcome") == "rule_postdates_state":
            out.append(f"[ПОРОГ МЛАДШЕ СОСТОЯНИЯ] {record.get('trade_id')} "
                       f"{record.get('day')}: {record.get('reason')}")
    out.append(f"НЕ ДОКАЗЫВАЕТ: {report.get('what_it_does_not_prove')}")
    return out


def save_artifact(report: Dict[str, Any], data_dir: Path) -> Path:
    """Записать артефакт. ``atomic_save(data, path)`` — данные ПЕРВЫМ аргументом."""
    path = Path(data_dir) / ARTIFACT_NAME
    atomic_save(report, str(path))
    return path


def run(root: str = ".", now: Optional[datetime] = None,
        data_dir: Optional[str] = None) -> Dict[str, Any]:
    """Ступень моста: замерить, записать артефакт, вернуть ``{measured, doc}``."""
    base = Path(root).resolve()
    ddir = Path(data_dir) if data_dir else base / "data"
    stamp = _now(now)
    if not ddir.is_dir():
        return {"measured": False, "doc": _unmeasured(
            f"каталога данных нет ({ddir}) — в рабочем дереве это ШТАТНО", stamp)}
    try:
        report = run_census(base, ddir, now=stamp)
    except NotMeasured as exc:
        doc = _unmeasured(str(exc), stamp)
        try:
            save_artifact(doc, ddir)
        except Exception:  # noqa: BLE001 — отказ записи не превращает отказ в успех
            pass
        return {"measured": False, "doc": doc}
    save_artifact(report, ddir)
    return {"measured": True, "doc": report}


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--data-dir", default=os.environ.get("SPA_DATA_DIR"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = run(root=args.root, data_dir=args.data_dir)
    doc = result["doc"]
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2, default=str))
    else:
        for line in format_report(doc):
            print(line)
    if not result["measured"]:
        return 2
    counts = observed(doc, "counts", kind=dict)
    if counts is None:
        # Тот же случай, что в `summary_line`: сводки нет ⇒ вердикт не вынесен.
        # Ноль здесь читался бы как «чисто» — код возврата 0 на неизмеренном.
        print("[НЕ ИЗМЕРЕНО] отчёт без сводки `counts` — вердикт не вынесен")
        return 2
    finding = (counts.get("violation") or counts.get("undetermined")
               or counts.get("unmeasured")
               or counts.get("violation_rule_birth_unmeasured")
               or doc.get("label_disagreement") or doc.get("tier_unknown"))
    return 1 if finding else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
