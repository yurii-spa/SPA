"""Пять воспроизведений ARB 27.10 (R1/R2) — на ИСПРАВЛЕННОМ коде, без подмены функций.

Те же пять сцен, что `reproduce_boundaries.py` ARB, но звенья вызываются целиком (писатель
карточки не подменён регистратором), и сверяется, что отказ ничего не записал. Всё — во временном
каталоге; трекер, данные и сеть не трогаются. Запуск: `python3 <этот файл>` из корня дерева.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from spa_core.owner_queue import owner_answer as oa  # noqa: E402
from spa_core.studio_os import work_packet as wp  # noqa: E402

res = {"source_sha256": {}, "cases": []}
for rel in ("spa_core/owner_queue/owner_answer.py", "spa_core/studio_os/work_packet.py"):
    res["source_sha256"][rel] = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()

with tempfile.TemporaryDirectory(prefix="arb-after-fix-") as tmp:
    tmp = Path(tmp)
    card = tmp / "owner-decision-review-example.md"
    card.write_text("---\nstatus: needs-owner\n---\nExample\n", encoding="utf-8")
    qv = oa.question_version(card.read_text(encoding="utf-8"))

    def register(name, cardname, choice):
        p = tmp / name
        p.write_text(json.dumps({"schema": oa.SESSION_REGISTER_SCHEMA, "adr": "ADR-999",
                                 "trust": oa.TRUST_OPERATOR_IMPORT, "channel": oa.SESSION_VIA,
                                 "answers": [{"card": cardname, "choice": choice, "label": "reject",
                                              "owner_text": "Reject", "event": "toolu_x#1",
                                              "question_sha256": qv}]}), encoding="utf-8")
        return p

    mention = tmp / "ADR-999-example.md"
    mention.write_text("# Notes\n" + card.stem, encoding="utf-8")
    for name, reg in [
        ("ADR_mentions_card_without_any_answer", mention),
        ("ADR_says_option_1_but_caller_submits_option_2", register("r2.json", card.stem, "1")),
        ("ADR_names_a_different_card_with_matching_prefix", register("r3.json", card.stem + "-other", "2")),
    ]:
        before = card.read_bytes()
        try:
            oa.record_session_answer(card, register_path=reg, choice_num="2")
            res["cases"].append({"case": name, "writer_reached": True})
        except oa.SessionAnswerRefused as exc:
            res["cases"].append({"case": name, "writer_reached": False, "refusal": str(exc),
                                 "card_untouched": card.read_bytes() == before})

    pkt = {"task_id": "task-a", "status": "awaiting_approval", "version": "example-plan-v1",
           "owner_subject": "money"}
    wrong = {"task_id": "task-b", "version": pkt["version"], "role": "agent"}
    res["cases"].append({"case": "ready_accepts_wrong_task_and_insufficient_role",
                         "accepted": wp.ready(pkt, wrong, "unregistered_probe:x"),
                         "refusals": wp.readiness(pkt, wrong, "unregistered_probe:x")})

    case = {"case": "record_outcome_accepts_unregistered_unrun_probe"}
    case["record_outcome_takes_a_verdict"] = "verdict" in inspect.signature(wp.record_outcome).parameters
    try:
        wp.approve(pkt, version=pkt["version"], approver="owner-test", role="owner", at="t",
                   probe="unregistered_probe:x")
        case["approve_with_unregistered_probe"] = "accepted"
    except wp.Refused as exc:
        case["approve_with_unregistered_probe"] = f"refused: {exc}"
    (tmp / wp.APPROVAL_FILE).write_text(json.dumps({**{k: pkt[k] for k in ("task_id", "version")},
                                                     "subject": "money", "role": "owner",
                                                     "probe": "unregistered_probe:x"}), encoding="utf-8")
    try:
        wp.record_outcome(tmp, pkt, at="t")
        case["hand_written_approval_outcome"] = "written"
    except wp.Refused as exc:
        case["hand_written_approval_outcome"] = f"refused: {exc}"
    case["written"] = (tmp / wp.OUTCOME_FILE).exists()
    res["cases"].append(case)

out = Path(__file__).with_name("reproduction_results_after_fix.json")
out.write_text(json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(res, ensure_ascii=False, indent=2))
