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

ARB 27.10 (R2): прежний ``ready`` сверял только статус, строку версии и НЕПУСТУЮ строку пробы —
одобрение чужой задачи ролью agent на предмет money проходило; ``record_outcome`` писал
``satisfied`` со слов вызывающего о пробе, которой нет в реестре и которую никто не запускал.
Теперь (ADR-839):

* одобрение привязано к задаче, версии, ПРЕДМЕТУ и ТОЧНОЙ пробе (:func:`approve` требует пробу из
  реестра); :func:`readiness` перепроверяет всю связку и называет каждый разрыв;
* итог (:func:`record_outcome`) вердикта ОТ ВЫЗЫВАЮЩЕГО не принимает: он сам запускает
  ``card_acceptance.run_probe`` для одобренной пробы и пишет запись запуска (кто мерил, чем, с
  какими входами, хеш одобрения, ``run_id``) — и только при ``satisfied``;
* «проверено» в пульте ставит :func:`decisions_for` (``execution.verified``), а не наличие файла;
* :func:`entry_gate` — граница ДО исполнения у диспетчера пульта: карточка с ОБЪЯВЛЕННЫМ предметом
  владельца без годного одобрения не берётся. Текст пакета в промпте — не граница.
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


APPROVAL_FILE = "approval.json"
OUTCOME_FILE = "outcome.json"


def _write_once(path: Path, doc: Dict[str, Any]) -> None:
    """Записать документ ОДИН раз: файл уже есть ⇒ отказ (одобрение и итог не переписываются)."""
    import os
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise Refused(f"{path.name} уже записан — запись не переписывается")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)


def _read(path: Path) -> Optional[Dict[str, Any]]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def record_approval(run_dir: Path, approval: Dict[str, Any]) -> Path:
    """Зафиксировать одобрение (результат :func:`approve`) рядом с подготовкой; один раз."""
    p = Path(run_dir) / APPROVAL_FILE
    _write_once(p, {"schema": SCHEMA, **approval})
    return p


EXECUTION_SCHEMA = "work-packet-execution/1"
RUNNER = "spa_core.monitoring.card_acceptance.run_probe"
#: Источник одобрения. Доверенного машинного канала одобрения (кнопка бота с chat_id) у пакета пока
#: НЕТ: одобрение, перенесённое агентом из сессии, — импорт оператора, и так и называется (ARB R1/R2).
SOURCE_OPERATOR_IMPORT = "operator-import"
SOURCES = (SOURCE_OPERATOR_IMPORT,)


def _canon(doc: Dict[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _runner_sha() -> Optional[str]:
    from spa_core.monitoring import card_acceptance as ca
    try:
        return hashlib.sha256(Path(ca.__file__).read_bytes()).hexdigest()
    except OSError:
        return None


def _run_id(doc: Dict[str, Any]) -> str:
    return _sha(_canon({k: v for k, v in doc.items() if k != "run_id"}))


def record_outcome(run_dir: Path, pkt: Dict[str, Any], *, at: str, repo_root: Optional[str] = None,
                   data_dir: Optional[str] = None, tracker_dir: Optional[str] = None) -> Path:
    """Итог исполнения = запись ФАКТИЧЕСКОГО запуска одобренной пробы; один раз.

    Вердикта у вызывающего не спрашивают: проба одобрения запускается здесь
    (``card_acceptance.run_probe``). Нет годной связки (:func:`readiness`) ⇒ отказ, проба не
    запускается. Проба ответила не ``satisfied`` ⇒ отказ с её вердиктом и пояснением, файл не
    пишется (повторить можно после исправления). Подставленные входы (``data_dir`` и др.)
    записываются, и такой итог пульт «проверенным» НЕ называет.
    """
    from spa_core.monitoring import card_acceptance as ca
    run_dir = Path(run_dir)
    ap_path = run_dir / APPROVAL_FILE
    ap = _read(ap_path)
    why = readiness(pkt, ap, (ap or {}).get("probe"))
    if why:
        raise Refused("итог не записывается: " + "; ".join(why))
    probe = ap["probe"]
    verdict, detail = ca.run_probe(probe, repo_root=repo_root, data_dir=data_dir, tracker_dir=tracker_dir)
    if verdict != ca.SATISFIED:
        raise Refused(f"проба «{probe}» не подтвердила результат ({verdict}): {detail} — итог не записан")
    doc: Dict[str, Any] = {
        "schema": EXECUTION_SCHEMA, "task_id": pkt["task_id"], "version": pkt["version"],
        "subject": pkt.get("owner_subject"), "probe": probe, "verdict": verdict, "detail": detail,
        "at": at, "runner": RUNNER, "runner_sha256": _runner_sha(),
        "inputs": {"repo_root": repo_root, "data_dir": data_dir, "tracker_dir": tracker_dir},
        "approval_sha256": hashlib.sha256(ap_path.read_bytes()).hexdigest(),
    }
    doc["run_id"] = _run_id(doc)
    p = run_dir / OUTCOME_FILE
    _write_once(p, doc)
    return p


def _bound(ap: Dict[str, Any]) -> bool:
    """Одобрение несёт полную связку (задача · версия · предмет · проба) — запись после ADR-839."""
    return all(k in ap for k in ("task_id", "version", "subject", "probe"))


def _execution_verified(oc: Dict[str, Any], ap: Optional[Dict[str, Any]], ap_raw: Optional[bytes],
                        version: Optional[str], ap_valid: bool) -> Optional[str]:
    """None — итог подтверждён запуском пробы для ТЕКУЩЕЙ одобренной версии; иначе причина."""
    if oc.get("schema") != EXECUTION_SCHEMA or not oc.get("run_id"):
        return "итог записан вручную (до ADR-839), запуск проверки к нему не привязан"
    if oc.get("run_id") != _run_id(oc):
        return "запись запуска не сходится со своим run_id"
    if oc.get("runner") != RUNNER:
        return f"итог дал не реестр проверок ({oc.get('runner')})"
    if oc.get("verdict") != "satisfied":
        return f"проверка ответила {oc.get('verdict')}"
    if any((oc.get("inputs") or {}).values()):
        return "проверка запускалась на подставленных входах, не на рабочих данных"
    if not ap or not _bound(ap) or not ap_valid:
        return "нет годного одобрения ТЕКУЩЕЙ версии с привязанной проверкой"
    if oc.get("version") != version or oc.get("task_id") != ap.get("task_id") or oc.get("probe") != ap.get("probe"):
        return "итог относится к другой версии, задаче или проверке"
    if ap_raw is None or oc.get("approval_sha256") != hashlib.sha256(ap_raw).hexdigest():
        return "одобрение изменилось после запуска проверки"
    return None


def decisions_for(run_dir: Path, plan_state: Dict[str, Any]) -> Dict[str, Any]:
    """Одобрение и итог подготовки — для пульта. Одобрение ДРУГОЙ версии ⇒ ``valid: False``;
    итог без подтверждённого запуска одобренной пробы ⇒ ``execution.verified: False`` с причиной."""
    from spa_core.studio_os.memory import arch_review as ar
    rec = _read(Path(run_dir) / ar.PREP_RECORD_FILE) or {}
    ident = rec.get("input_identity") or ""
    body = "\n\x1e".join(str(x or "") for x in (plan_state.get("plan"), plan_state.get("outcome"),
                                                 plan_state.get("acceptance_text")))
    version = _sha(f"{ident}\n\x1d{body}") if ident else None
    ap_path = Path(run_dir) / APPROVAL_FILE
    ap = _read(ap_path)
    try:
        ap_raw = ap_path.read_bytes() if ap else None
    except OSError:
        ap_raw = None
    oc = _read(Path(run_dir) / OUTCOME_FILE)
    out: Dict[str, Any] = {"version": version}
    ap_valid = False
    if ap:
        ap_valid = bool(version and ap.get("version") == version and plan_state.get("state") == "current")
        out["approval"] = {k: ap.get(k) for k in ("approver", "role", "at", "version", "probe", "source")}
        out["approval"]["valid"] = ap_valid
        out["approval"]["bound"] = _bound(ap)
    if oc:
        # Ключ `execution`, а не `outcome`: `outcome` в блоке подготовки — ТЕКСТ ожидаемого итога
        # из плана (preparation_state), и одно имя затёрло бы другое в пульте.
        out["execution"] = {k: oc.get(k) for k in ("probe", "verdict", "detail", "at", "version", "run_id")}
        why = _execution_verified(oc, ap, ap_raw, version, ap_valid)
        out["execution"]["verified"] = why is None
        if why:
            out["execution"]["not_verified_because"] = why
    return out


def authority(pkt: Dict[str, Any]) -> str:
    """'owner' | 'agent'. Не объявленный предмет — владельцу (UNKNOWN не значит «вне трёх»)."""
    subj = pkt.get("owner_subject")
    if subj not in SUBJECTS or subj in SUBJECTS_OWNER:
        return "owner"
    return "agent"


def approve(pkt: Dict[str, Any], *, version: str, approver: str, role: str, at: str, probe: str,
            source: str = SOURCE_OPERATOR_IMPORT) -> Dict[str, Any]:
    """Одобрение ТЕКУЩЕЙ версии с привязкой задачи, предмета и точной пробы (ADR-839)."""
    if role not in ROLES:
        raise Refused(f"роль «{role}» не может одобрять: ответ модели — не разрешение")
    if source not in SOURCES:
        raise Refused(f"источник одобрения «{source}» не известен — подтверждённого канала нет")
    if pkt.get("status") != "awaiting_approval" or not pkt.get("version"):
        raise Refused("одобрять нечего: план не подготовлен или его версия устарела")
    if version != pkt["version"]:
        raise Refused("одобрение относится к ДРУГОЙ версии плана — изменившийся план нужно одобрить заново")
    if authority(pkt) == "owner" and role != "owner":
        why = ("предмет карточки не объявлен" if pkt.get("owner_subject") not in SUBJECTS
               else f"предмет «{pkt['owner_subject']}» — решение владельца")
        raise Refused(f"{why}: одобрить может только владелец")
    bound = bind_probe(probe)
    return {"task_id": pkt["task_id"], "version": version, "subject": pkt.get("owner_subject"),
            "authority": authority(pkt), "probe": bound, "approver": approver, "role": role,
            "source": source, "at": at}


def bind_probe(spec: str) -> str:
    from spa_core.monitoring import card_acceptance as ca
    spec = (spec or "").strip()
    name = spec.partition(":")[0].strip()
    if not name:
        raise Refused("проверка результата не объявлена — без неё работа не начинается")
    if name not in ca.PROBES:
        raise Refused(f"проверка «{name}» неизвестна реестру — её нужно сначала написать и проверить")
    why = ca.validate_spec(spec)
    if why:
        raise Refused(f"проверка «{spec}» не годится: {why}")
    return spec


def readiness(pkt: Dict[str, Any], approval: Optional[Dict[str, Any]], probe: Optional[str]) -> list:
    """Почему исполнять НЕЛЬЗЯ (пустой список — можно). Перепроверяет всю связку одобрения."""
    why = []
    if pkt.get("status") != "awaiting_approval" or not pkt.get("version"):
        why.append("план не подготовлен или его версия устарела")
    if not isinstance(approval, dict):
        return why + ["нет одобрения ЭТОЙ версии плана"]
    if approval.get("task_id") != pkt.get("task_id"):
        why.append(f"одобрение другой задачи ({approval.get('task_id')})")
    if approval.get("version") != pkt.get("version"):
        why.append("одобрение другой версии плана")
    if "subject" not in approval or (approval.get("subject") or None) != (pkt.get("owner_subject") or None):
        why.append("предмет карточки не тот, что был одобрен")
    if approval.get("role") not in ROLES:
        why.append(f"роль «{approval.get('role')}» не одобряет")
    elif authority(pkt) == "owner" and approval.get("role") != "owner":
        why.append("предмет карточки — решение владельца, а одобрил не владелец")
    try:
        bound = bind_probe(probe or "")
    except Refused as exc:
        why.append(str(exc))
    else:
        if (approval.get("probe") or "").strip() != bound:
            why.append(f"проверка «{bound}» не та, что была одобрена ({approval.get('probe')})")
    return why


def ready(pkt: Dict[str, Any], approval: Optional[Dict[str, Any]], probe: Optional[str]) -> bool:
    return not readiness(pkt, approval, probe)


def entry_gate(card: Path, run_dir: Optional[Path], *, root: Path, probe: str,
               code_now: Any = "measure") -> Optional[str]:
    """Граница ДО исполнения (диспетчер пульта). None — брать можно; иначе причина отказа.

    Карточка с ОБЪЯВЛЕННЫМ предметом владельца (money · public · irreversible) берётся только при
    годном одобрении текущей версии с той же пробой, что объявлена к исполнению. Предмет ``none`` и
    не объявленный предмет записи пульта — прежний путь (запись пульта пишет сам владелец); это
    названный предел границы (ADR-839), а не её отсутствие.
    """
    fm = _frontmatter(Path(card).read_text(encoding="utf-8"))
    if (fm.get("owner_subject") or None) not in SUBJECTS_OWNER:
        return None
    if run_dir is None:
        return f"предмет «{fm.get('owner_subject')}» — нужен подготовленный и одобренный владельцем план"
    pkt = build(Path(card), Path(run_dir), root=Path(root), code_now=code_now)
    why = readiness(pkt, _read(Path(run_dir) / APPROVAL_FILE), probe)
    return "; ".join(why) if why else None


def render(pkt: Dict[str, Any]) -> str:
    """Короткая форма пакета для промпта исполнителя (поля ADR-154, без пересказа плана)."""
    res = pkt.get("result") or {}
    return (f"ПАКЕТ ПЕРЕДАЧИ ({SCHEMA}) · задача {pkt['task_id']} · цель: {pkt['goal']} · статус: "
            f"{pkt['status']} · версия плана: {(pkt.get('version') or '—')[:12]} · ожидаемый итог: "
            f"{(res.get('outcome') or 'не подготовлен')[:300]} · следующий шаг: {pkt.get('next_step')} · "
            f"ограничения: {'; '.join(pkt['constraints'])}. ")
