"""Пакет передачи работы (ADR-154 §2) и одобрение ТОЧНОЙ версии плана — звенья сквозного сценария.

Цепочка студии: поручение → подготовленный план (task-prep) → проверка полномочий → одобрение
конкретной версии → объявленная проверка результата → ограниченное исполнение → проверка → итог.
До 27.10 передача несла голую карточку (ADR-154: «без проверок, без источников, без явного
следующего шага»), а одобрения версии не существовало вовсе. Этот модуль — детерминированные
звенья; LLM здесь нет (инв. #3): ответ модели — ВХОД пакета, а не разрешение.

* :func:`build` — пакет из карточки и её подготовки: цель · входные факты · источники и ревизии ·
  выполненные проверки · результат · ограничения · следующий шаг · статус · ``version``.
  ``version`` — хеш входов подготовки (``input_identity``) И текста плана/итога/приёмки: любой
  сдвиг плана или его входов даёт ДРУГУЮ версию.
* :func:`authority` — кому решать. Предмет карточки объявляется полем ``owner_subject``
  (``none`` · ``money`` · ``public`` · ``irreversible``); не объявлен ⇒ ``UNKNOWN`` ⇒ решать
  владельцу (ADR-285: агент сам решает только вне трёх предметов, а «не знаю» — не «вне»).
* :func:`approve` — запись одобрения, привязанная к версии; устаревшая подготовка, чужая
  версия или роль ``model`` ⇒ отказ. Изменившийся план старого одобрения не наследует.
* :func:`bind_probe` — техническая привязка проверки результата ДО работы: имя обязано быть в
  реестре ``card_acceptance``; незнакомое ⇒ отказ с понятным текстом.
* :func:`ready` — можно ли исполнять: всё выше сошлось для ТЕКУЩЕЙ версии.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional

SCHEMA = "work-packet/1"
SUBJECTS_OWNER = ("money", "public", "irreversible")
SUBJECTS = SUBJECTS_OWNER + ("none",)
ROLES = ("owner", "agent")
CONSTRAINTS = (
    "реальный капитал $0; ставки, лимиты риска, публичные финансовые и юридические утверждения "
    "автоматически не меняются (ADR-285, предметы 1–3)",
    "ответ модели — предложение для разбора, а не разрешение",
    "ничего не удалять; не перезаписывать конкурентные изменения трекера",
    "«сделано» ставит только объявленная проверка результата, а не слово исполнителя",
)


class Refused(Exception):
    """Звено отказало; текст — понятная причина для человека."""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _frontmatter(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not text.startswith("---"):
        return out
    end = text.find("\n---", 3)
    for line in text[3:end if end > 0 else len(text)].splitlines():
        if ":" in line and not line.startswith((" ", "\t", "-")):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def build(card: Path, run_dir: Optional[Path], *, root: Path, code_now: Any = "measure") -> Dict[str, Any]:
    """Собрать пакет. Подготовки нет / не читается ⇒ пакет со статусом ``no_plan`` (не ошибка)."""
    from spa_core.studio_os.memory import arch_review as ar
    card = Path(card)
    text = card.read_text(encoding="utf-8")
    fm = _frontmatter(text)
    pkt: Dict[str, Any] = {
        "schema": SCHEMA, "task_id": card.stem, "goal": fm.get("title") or card.stem,
        "owner_subject": fm.get("owner_subject") or None, "constraints": list(CONSTRAINTS),
        "input_facts": None, "sources": None, "checks_done": [], "result": None,
        "next_step": None, "status": "no_plan", "version": None, "plan_run": None,
    }
    if run_dir is None:
        pkt["next_step"] = "подготовить план (prepare-record), затем разбор и одобрение версии"
        return pkt
    st = ar.preparation_state(Path(run_dir), card_text=text, root=Path(root), code_now=code_now)
    pkt["plan_run"] = str(run_dir)
    pkt["checks_done"].append({"check": "свежесть подготовки", "verdict": st.get("state"),
                               "reasons": st.get("reasons") or []})
    try:
        rec = json.loads((Path(run_dir) / ar.PREP_RECORD_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rec = {}
    pkt["input_facts"] = {"request_sha256": rec.get("request_sha256"),
                          "context_sha256": rec.get("context_sha256"),
                          "context_unknown": rec.get("context_unknown") or []}
    pkt["sources"] = {"revisions": rec.get("revisions"),
                      "files": sorted((rec.get("sources_sha256") or {}).keys())}
    pkt["result"] = {"form": st.get("form"), "outcome": st.get("outcome"), "plan": st.get("plan"),
                     "acceptance_text": st.get("acceptance_text")}
    ident = rec.get("input_identity") or ""
    body = "\n\x1e".join(str(x or "") for x in (st.get("plan"), st.get("outcome"),
                                                 st.get("acceptance_text")))
    pkt["version"] = _sha(f"{ident}\n\x1d{body}") if ident else None
    if st.get("state") != "current" or not pkt["version"]:
        pkt["status"] = "plan_not_current"
        pkt["next_step"] = "подготовить план заново: прежняя версия устарела или не полна"
    else:
        pkt["status"] = "awaiting_approval"
        who = authority(pkt)
        pkt["next_step"] = (f"одобрить ЭТУ версию плана ({pkt['version'][:12]}) — решает "
                            f"{'владелец' if who == 'owner' else 'агент'}")
    return pkt


def authority(pkt: Dict[str, Any]) -> str:
    """'owner' | 'agent'. Не объявленный предмет — владельцу (UNKNOWN не значит «вне трёх»)."""
    subj = pkt.get("owner_subject")
    if subj not in SUBJECTS or subj in SUBJECTS_OWNER:
        return "owner"
    return "agent"


def approve(pkt: Dict[str, Any], *, version: str, approver: str, role: str, at: str) -> Dict[str, Any]:
    if role not in ROLES:
        raise Refused(f"роль «{role}» не может одобрять: ответ модели — не разрешение")
    if pkt.get("status") != "awaiting_approval" or not pkt.get("version"):
        raise Refused("одобрять нечего: план не подготовлен или его версия устарела")
    if version != pkt["version"]:
        raise Refused("одобрение относится к ДРУГОЙ версии плана — изменившийся план нужно одобрить заново")
    if authority(pkt) == "owner" and role != "owner":
        why = ("предмет карточки не объявлен" if pkt.get("owner_subject") not in SUBJECTS
               else f"предмет «{pkt['owner_subject']}» — решение владельца")
        raise Refused(f"{why}: одобрить может только владелец")
    return {"task_id": pkt["task_id"], "version": version, "approver": approver, "role": role, "at": at}


def bind_probe(spec: str) -> str:
    from spa_core.monitoring import card_acceptance as ca
    name = (spec or "").partition(":")[0].strip()
    if not name:
        raise Refused("проверка результата не объявлена — без неё работа не начинается")
    if name not in ca.PROBES:
        raise Refused(f"проверка «{name}» неизвестна реестру — её нужно сначала написать и проверить")
    return spec.strip()


def ready(pkt: Dict[str, Any], approval: Optional[Dict[str, Any]], probe: Optional[str]) -> bool:
    return bool(pkt.get("status") == "awaiting_approval" and approval
                and approval.get("version") == pkt.get("version") and probe)


def render(pkt: Dict[str, Any]) -> str:
    """Короткая форма пакета для промпта исполнителя (поля ADR-154, без пересказа плана)."""
    res = pkt.get("result") or {}
    return (f"ПАКЕТ ПЕРЕДАЧИ ({SCHEMA}) · задача {pkt['task_id']} · цель: {pkt['goal']} · статус: "
            f"{pkt['status']} · версия плана: {(pkt.get('version') or '—')[:12]} · ожидаемый итог: "
            f"{(res.get('outcome') or 'не подготовлен')[:300]} · следующий шаг: {pkt.get('next_step')} · "
            f"ограничения: {'; '.join(pkt['constraints'])}. ")
