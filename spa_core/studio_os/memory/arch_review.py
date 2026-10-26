"""One command: a SAFE architecture review of one task by the chosen provider (STUDIO-OS-MODELS-01, inc. 4).

Lives in ``memory`` (next to ``role_pack``), not in ``model_roles``: the dependency runs memory → model_roles
only — the transport layer never imports its callers (held by ``test_memory_answer_via_contract``).

# LLM_FORBIDDEN

    python -m spa_core.studio_os.memory arch-review --handover <repo-rel handover> --task-id ID \
        --task "<one task>" --verified-sha <40-hex> --provider <id> --out DIR \
        [--roadmap-item 17] [--extra-context FILE ...] [--fixture F.json]

What it does — and nothing else:

1. builds the context with the existing :mod:`spa_core.studio_os.memory.role_pack` (role ``architect``,
   the given verified revision), plus small EXPLICIT extra fragments (implementation snippets, links),
   each sanitized by the same credential sanitizer and fingerprinted;
2. calls role ``architect`` through the existing contract (:func:`contract.execute`) with the provider
   named explicitly (repository assignments stay null — no routing);
3. writes ``DIR/context.md`` (exactly what the model saw), ``DIR/review.json`` (task id, revisions, context
   hash, provider, status, time, reported usage, completeness, parsed sections) and
   ``DIR/recommendation.md`` (facts → unknowns → decision with reason → acceptance criteria → one
   copyable task block for the implementer).

It never edits the roadmap, cards, ADRs or permissions and never records an owner approval: the output
directory is the only thing it writes. A successful model call is NOT evidence that the context was
complete, and NOT an architecture acceptance — both are stated in every output.
Exit: 0 ok and structure complete · 1 provider outcome ≠ ok, or the answer lacks a required section ·
2 refused / not built.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from spa_core.studio_os.memory import role_pack
from spa_core.studio_os.model_roles import adapters as ad
from spa_core.studio_os.model_roles.contract import ConfigError, Request, execute, load_config

REVIEW_VERSION = "arch-review/1"
ROLE = "architect"
EXTRA_LIMIT_CHARS = 20000
#: Section headings the answer must carry, in this order (the parser is keyed on them).
SECTIONS = ("FACTS", "UNKNOWNS", "DECISION", "ACCEPTANCE CRITERIA", "CLAUDE TASK")
DISCLAIMER = ("PROPOSAL ONLY — not an owner approval, not an ARB acceptance, changes nothing by itself. "
              "A successful model call does not prove the context was complete.")

INSTRUCTION = """Architecture review of ONE task. Use ONLY the context below (project pack + fragments).
TASK: {task}

Reply in EXACTLY these five sections, with these headings, in this order:
## FACTS — what the context establishes, each with its source path.
## UNKNOWNS — what the context does NOT establish (say UNKNOWN; do not guess).
## DECISION — the recommended solution and WHY (alternatives you rejected, one line each).
## ACCEPTANCE CRITERIA — machine-checkable conditions (tests/commands), before the work starts.
## CLAUDE TASK — ONE fenced code block (```text … ```) the owner can copy to the implementer: scope,
files, constraints (no production, no main, no tracker), checks, and what NOT to do.
This is a proposal: do not claim approval or acceptance."""


#: ``--kind task-prep`` (ARB 25.10): the SAME seam turns ONE ordinary owner request into a reviewable
#: preparation — intended outcome, plan, an acceptance PROPOSAL, unknowns/question, required authority.
#: It prepares, it never executes: no card, no ``acceptance_probe``, no claim, no worker, nothing «done».
KIND_ARCH, KIND_PREP = "arch", "task-prep"
PREP_VERSION = "task-prep/1"
PREP_SECTIONS = ("OUTCOME", "PLAN", "ACCEPTANCE PROPOSAL", "UNKNOWNS AND QUESTION", "PERMISSIONS")
NEW_CHECK_MARK = "NEW CHECK NEEDED"
NO_PLAN_MARK = "NO PLAN"
SUBJECT_NONE = "NONE"
#: Forms a task-prep run may report as success (exit 0): a plan FOR REVIEW or a valid clarifying question.
#: Neither is permission to execute.
ACCEPTABLE_FORMS = ("plan", "clarification")
#: ARB 25.10: the subject is the MODEL's proposal; only its membership in the vocabulary is checked.
SUBJECT_NOTE = ("предмет полномочий предложен моделью; проверено только, что это значение словаря ADR-285. "
                "Это не независимая проверка прав и не разрешение исполнять — даже NONE")
PREP_DISCLAIMER = ("ПРЕДЛОЖЕНИЕ ДЛЯ РАЗБОРА — не задание к исполнению: карточка не меняется, проверка результата не "
                   "назначается, исполнитель не запускается, ничего не объявлено сделанным. Зарегистрированное имя "
                   "проверки не доказывает, что она меряет это поручение.")
#: Which provider wrote the answer changes what the answer can show — said in the disclaimer itself.
PREP_FIXTURE_NOTE = "Ответ тестового адаптера — не модель: показаны форма и сверка, качество модели не оценено."
PREP_REAL_NOTE = "Ответ настоящей модели — черновик: один ответ не доказывает пригодность модели."
PREP_INSTRUCTION = """Prepare ONE ordinary request of the owner for later work. Use ONLY the context below. Do NOT do the work.
The owner's request, verbatim (do not rewrite it):
<<<REQUEST
{task}
REQUEST>>>

Reply in plain Russian for the owner, in EXACTLY these five sections, with these headings, in this order:
## OUTCOME — what will exist when the request is fulfilled, in one or two sentences the owner can check.
## PLAN — 3–7 numbered steps of the work, each with its scope (what is touched, what is NOT touched).
If the request is too ambiguous to plan, write exactly "{no_plan}" here and ask in the next section.
## ACCEPTANCE PROPOSAL — how the RESULT will be checked by a machine, before the work starts. Either name an
existing check in backticks AND say why it measures THIS outcome, or write "{new_check}: <what the check must
measure, a positive and a negative control>". Never pick a check only because it exists.
## UNKNOWNS AND QUESTION — what the context does not establish (say UNKNOWN); if anything blocks planning,
ONE plain question to the owner ending with "?".
## PERMISSIONS — first line exactly "subject: <one of NONE, MONEY, PUBLIC_NUMBERS_NAMING_LEGAL, IRREVERSIBLE,
PHYSICAL_ACTION>" (the owner's three subjects of ADR-285, or an action only the owner can physically do);
then why. This is a proposal: do not claim approval, acceptance or completion."""

_IDENT = re.compile(r"`([A-Za-z][A-Za-z0-9_]{2,}(?::[A-Za-z0-9_.+\-]+)?)`")


class ReviewError(Exception):
    """The review cannot be built — refused before any model call."""


def refuse_if_credential(field: str, value: Optional[str]) -> None:
    """ARB 24.10: a credential-like value in ANY caller-supplied string is refused before the provider.

    The check is the memory sanitizer itself (one copy of the patterns). The reason names only the
    FIELD — never the value — so no report, refusal text or log can carry the secret onwards.
    """
    if value is None:
        return
    _clean, dropped = role_pack._clean_text(str(value))
    if dropped:
        raise ReviewError(f"{field} contains a credential-like value — refused before any provider call "
                          f"(the value is not repeated here)")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git(root: Path, *args: str) -> Optional[str]:
    try:
        p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def extra_fragments(paths: Sequence[Path]) -> tuple:
    """(markdown block, rows, unknown) — each fragment sanitized and fingerprinted; limit enforced."""
    rows: List[Dict[str, Any]] = []
    unknown: List[str] = []
    parts: List[str] = []
    total = 0
    for p in paths:
        refuse_if_credential("extra-context path", str(p))
        try:
            raw = Path(p).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            unknown.append(f"extra fragment {Path(p).name}: not readable ({type(exc).__name__})")
            continue
        clean, dropped = role_pack._clean_text(raw)
        if dropped:
            unknown.append(f"extra fragment {Path(p).name}: {dropped} credential-like line(s) dropped")
        total += len(clean)
        if total > EXTRA_LIMIT_CHARS:
            raise ReviewError(f"extra fragments exceed {EXTRA_LIMIT_CHARS} chars — give smaller fragments")
        rows.append({"name": Path(p).name, "sha256": _sha(clean), "chars": len(clean),
                     "credential_lines_dropped": dropped})
        parts.append(f"### Fragment: {Path(p).name}\n\n{clean.rstrip()}\n")
    return ("\n".join(parts), rows, unknown)


def parse_sections(text: str, sections: Sequence[str] = SECTIONS) -> Dict[str, Optional[str]]:
    """Body of each required ``## SECTION`` heading; ``None`` — the section is missing."""
    out: Dict[str, Optional[str]] = {s: None for s in sections}
    marks = []
    for s in sections:
        m = re.search(r"(?mi)^#{1,4}\s*" + re.escape(s) + r"\b.*$", text)
        if m:
            marks.append((m.start(), m.end(), s))
    marks.sort()
    for i, (_a, b, s) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        body = text[b:end].strip()
        out[s] = body or None
    return out


def claude_task_block(section: Optional[str]) -> Optional[str]:
    if not section:
        return None
    m = re.search(r"```[a-zA-Z]*\n(.*?)```", section, re.S)
    return m.group(1).strip() if m else None


def run_review(root: Path, *, handover: str, task_id: str, task: str, verified_sha: str,
               provider: Optional[str], out: Path, roadmap_item: Optional[int] = None,
               extra: Sequence[Path] = (), adapters: Optional[Dict] = None,
               config: Optional[Dict] = None, at: Optional[str] = None, kind: str = KIND_ARCH) -> Dict[str, Any]:
    if kind not in (KIND_ARCH, KIND_PREP):
        raise ReviewError(f"unknown review kind {kind!r}; known: {KIND_ARCH}, {KIND_PREP}")
    # Every caller-supplied string that reaches the prompt, review.json, recommendation.md or a reason.
    for field, value in (("task", task), ("task_id", task_id), ("handover", handover), ("provider", provider)):
        refuse_if_credential(field, value)
    for p in extra:
        refuse_if_credential("extra-context path", str(p))
    if not re.fullmatch(r"[0-9a-f]{40}", verified_sha or ""):
        raise ReviewError("--verified-sha must be a full 40-hex commit id (the EXACT verified revision)")
    if _git(root, "cat-file", "-e", f"{verified_sha}^{{commit}}") is None:
        raise ReviewError(f"verified revision {verified_sha[:12]} is not a commit in {root}")
    try:
        pack = role_pack.build(root, handover, roadmap_item, ROLE, at, verified_sha)
    except role_pack.PackError as exc:
        raise ReviewError(f"context pack not built: {exc}") from exc
    frag_md, frag_rows, frag_unknown = extra_fragments(extra)
    context = role_pack.render(pack) + ("\n## Task fragments (explicit, sanitized)\n\n" + frag_md if frag_md else "")
    unknown = list(pack["unknown"]) + frag_unknown
    names = PREP_SECTIONS if kind == KIND_PREP else SECTIONS
    instruction = (PREP_INSTRUCTION.format(task=task, no_plan=NO_PLAN_MARK, new_check=NEW_CHECK_MARK)
                   if kind == KIND_PREP else INSTRUCTION.format(task=task))
    req = Request(ROLE, task_id, instruction, context, "role-pack + fragments")
    res = execute(req, config=config or load_config(), provider_id=provider,
                  adapters=adapters if adapters is not None else {"claude_cli": ad.claude_cli()})
    sections = parse_sections(res.text, names) if res.status == "ok" else {s: None for s in names}
    block = claude_task_block(sections["CLAUDE TASK"]) if kind == KIND_ARCH else None
    missing = [s for s, v in sections.items() if v is None] + ([] if kind == KIND_PREP or block
                                                               or res.status != "ok" else ["CLAUDE TASK code block"])
    rev = pack["revision"]
    record = {
        "review_version": REVIEW_VERSION, "task_id": task_id, "task": task,
        "generated_at": at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "revisions": {"verified_code_sha": verified_sha, "head": rev.get("head"),
                      "server_branch_head": rev.get("server_branch_head"),
                      "head_code_is_verified": rev.get("head_code_is_verified"),
                      "code_changed_since_verified": rev.get("code_changed_since_verified"),
                      "branch": rev.get("branch")},
        "context_sha256": res.context_sha256, "context_chars": len(context),
        "context_complete": not unknown, "context_unknown": unknown, "fragments": frag_rows,
        "provider": res.provider_id, "real_provider": res.real_provider, "model": res.model,
        "status": res.status, "reason": res.reason, "attempts": res.attempts, "elapsed_s": res.elapsed_s,
        "usage": res.usage, "sections": sections, "claude_task": block,
        "structure_complete": res.status == "ok" and not missing, "missing_sections": missing,
        "disclaimer": DISCLAIMER, "writes": "only this output directory",
    }
    if kind == KIND_PREP:
        # Sources of the context by their OWN bytes (not the rendered context: that carries a generation time).
        # A later reader re-hashes these files itself — the stored values are never echoed back as «fresh».
        inputs = pack.get("inputs_sha256")
        sources = dict(inputs) if isinstance(inputs, dict) else {}
        for p in extra:
            try:
                sources[_rel(root, Path(p))] = hashlib.sha256(Path(p).read_bytes()).hexdigest()
            except OSError:
                sources[_rel(root, Path(p))] = None
        record.update(review_version=PREP_VERSION, kind=KIND_PREP, request_sha256=_sha(task),
                      sources_sha256=sources,
                      disclaimer=PREP_DISCLAIMER + " " + (PREP_REAL_NOTE if res.real_provider else PREP_FIXTURE_NOTE),
                      preparation=check_preparation(sections) if res.status == "ok" else None)
    out.mkdir(parents=True, exist_ok=True)
    from spa_core.utils.atomic import atomic_save, atomic_save_text
    atomic_save_text(context, str(out / "context.md"))
    atomic_save(record, str(out / "review.json"))
    render = render_preparation if kind == KIND_PREP else render_recommendation
    atomic_save_text(render(record), str(out / "recommendation.md"))
    return record


def _rel(root: Path, p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return str(Path(p).resolve())


# ── ARB 26.10: one cockpit record → its preparation, shown read-only in «Мои записи» ────────────────────────
#: Where the owner's words live in a cockpit card (``telegram.inbox_intake.save_inbox_task``).
_TASK_HEADING = re.compile(r"(?m)^## Задание \(из [^)]*\)\s*$")
PREP_STATES = ("current", "stale", "incomplete", "unreadable")
#: The record a preparation reader opens. Its OWN name, not ``review.json``: that name is shared by several
#: committed evidence files, and a reader of an ambiguous name cannot be told apart by the prior-run census.
PREP_RECORD_FILE = "task_prep_record.json"


def request_text_of(card_text: str) -> Optional[str]:
    """The owner's request inside a cockpit card: the body of «## Задание (из …)» up to the next heading or
    rule, without the «пометил как» line. Fields the intake/dispatcher add to the frontmatter do not change it.
    Not found ⇒ None (no request — nothing to prepare), never the whole card."""
    m = _TASK_HEADING.search(card_text or "")
    if not m:
        return None
    rest = card_text[m.end():]
    stop = re.search(r"(?m)^(## |---\s*$)", rest)
    body = rest[:stop.start()] if stop else rest
    lines = [ln for ln in body.splitlines() if not re.match(r"^_.*(пометил как|Пометка при отправке).*_$", ln.strip())]
    text = "\n".join(lines).strip()
    return text or None


def _stem_dir(prep_root: Path, card_name: str) -> Path:
    return Path(prep_root) / Path(card_name).stem


def preparation_runs(prep_root: Path, card_name: str) -> List[Path]:
    """Every stored preparation of one card, oldest first (directory names start with a UTC stamp)."""
    d = _stem_dir(prep_root, card_name)
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if (p / PREP_RECORD_FILE).is_file())


def preparation_state(run_dir: Path, *, card_text: Optional[str], root: Path) -> Dict[str, Any]:
    """Read ONE stored preparation and judge it against INDEPENDENTLY read current inputs: the request is
    re-extracted from the card as it is NOW, every source file is re-hashed NOW. Read-only; no model call.
    ``state``: current · stale (request or a source changed / vanished) · incomplete (provider not ok or
    preparation not acceptable) · unreadable. Never «ready»/«approved» — a preparation permits nothing."""
    try:
        rec = json.loads((Path(run_dir) / PREP_RECORD_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"state": "unreadable", "reasons": [f"{PREP_RECORD_FILE} not readable ({type(exc).__name__})"],
                "run": str(run_dir)}
    if not isinstance(rec, dict) or rec.get("kind") != KIND_PREP:
        return {"state": "unreadable", "reasons": ["not a task-prep record"], "run": str(run_dir)}
    reasons = []
    now_request = request_text_of(card_text) if card_text is not None else None
    if now_request is None:
        reasons.append("the card's request is not readable now")
    elif _sha(now_request) != rec.get("request_sha256"):
        reasons.append("the request text changed")
    recorded = rec.get("sources_sha256") if isinstance(rec.get("sources_sha256"), dict) else {}
    for rel, old in sorted(recorded.items()):
        p = Path(rel) if Path(rel).is_absolute() else Path(root) / rel
        try:
            now = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            now = None
        if old is None or now != old:
            reasons.append(f"source changed or missing: {rel}")
    if not recorded:
        reasons.append("no source fingerprints recorded — freshness cannot be established")
    p = rec.get("preparation") if isinstance(rec.get("preparation"), dict) else None
    sec = rec.get("sections") if isinstance(rec.get("sections"), dict) else {}
    if reasons:
        state = "stale"
    elif rec.get("status") != "ok" or p is None or p.get("acceptable") is not True:
        state = "incomplete"
        reasons.append(f"provider status {rec.get('status')}" if rec.get("status") != "ok"
                       else f"preparation {p.get('form') if p else 'not assessed'}")
    else:
        state = "current"
    return {"state": state, "reasons": reasons, "run": str(run_dir), "prepared_at": rec.get("generated_at"),
            "provider": rec.get("provider"), "real_provider": rec.get("real_provider"),
            "form": p.get("form") if p else None, "acceptance": p.get("acceptance") if p else None,
            "subject": p.get("subject") if p else None, "subject_note": SUBJECT_NOTE,
            "outcome": sec.get("OUTCOME"), "plan": sec.get("PLAN"), "question": sec.get("UNKNOWNS AND QUESTION"),
            "acceptance_text": sec.get("ACCEPTANCE PROPOSAL"), "request_sha256": rec.get("request_sha256")}


def prepare_record(root: Path, card: Path, prep_root: Path, *, handover: str, verified_sha: str,
                   provider: Optional[str], adapters: Optional[Dict] = None, config: Optional[Dict] = None,
                   extra: Sequence[Path] = (), roadmap_item: Optional[int] = None,
                   at: Optional[str] = None) -> Dict[str, Any]:
    """EXPLICIT preparation of one cockpit record (ARB 26.10). Reads the card, never writes it: no
    ``acceptance_probe``, no claim, no status. If the newest stored preparation is still current against
    independently re-read inputs, nothing is called and nothing is written (``unchanged``). Otherwise ONE new,
    uniquely named directory ``<prep_root>/<card-stem>/<UTC stamp>-<request sha8>`` — earlier ones are kept."""
    card = Path(card)
    try:
        text = card.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReviewError(f"record not readable: {card.name} ({type(exc).__name__})") from exc
    request = request_text_of(text)
    if request is None:
        raise ReviewError(f"{card.name}: no «## Задание» section — nothing to prepare")
    runs = preparation_runs(prep_root, card.name)
    if runs:
        last = preparation_state(runs[-1], card_text=text, root=root)
        if last["state"] == "current":
            return {"action": "unchanged", "run": str(runs[-1]), "state": last}
    stamp = (at or datetime.now(timezone.utc).isoformat(timespec="seconds")).replace(":", "").replace("-", "")
    out = _stem_dir(prep_root, card.name) / f"{stamp[:15]}Z-{_sha(request)[:8]}"
    if out.exists():
        raise ReviewError(f"{out} already exists — earlier evidence is never overwritten")
    rec = run_review(root, handover=handover, task_id=card.stem, task=request, verified_sha=verified_sha,
                     provider=provider, out=out, roadmap_item=roadmap_item, extra=extra, adapters=adapters,
                     config=config, at=at, kind=KIND_PREP)
    from spa_core.utils.atomic import atomic_save
    atomic_save(rec, str(out / PREP_RECORD_FILE))
    return {"action": "prepared", "run": str(out), "status": rec["status"],
            "state": preparation_state(out, card_text=text, root=root)}


def check_preparation(sections: Dict[str, Optional[str]], probes: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Deterministic reading of a task-prep answer — it VALIDATES, it never decides readiness.

    * every backticked identifier in ACCEPTANCE PROPOSAL is looked up in the probe registry: registered ⇒
      «relevance NOT established» (a registered name is not proof it measures THIS request); unregistered ⇒
      not a check at all; «NEW CHECK NEEDED» ⇒ a proposal to build one (not an installed check);
    * PERMISSIONS ``subject:`` must be a word of the ADR-285 vocabulary (``owner_queue.subject``) or NONE;
      anything else ⇒ UNKNOWN for the reviewer;
    * the owner-facing form: ``plan`` · ``clarification`` (no plan, a question) · ``incomplete``.
    There is deliberately NO «ready» / «approved» field: review and permission are not a schema flag."""
    from spa_core.owner_queue import subject as subj
    if probes is None:
        from spa_core.monitoring.card_acceptance import PROBES as _reg
        probes = list(_reg)
    acc = sections.get("ACCEPTANCE PROPOSAL") or ""
    named = []
    for ident in dict.fromkeys(m.group(1) for m in _IDENT.finditer(acc)):
        base = ident.split(":", 1)[0]
        if base in probes:
            named.append({"name": ident, "registered": True,
                          "relevance": "NOT ESTABLISHED — a registered name is not proof it measures this request"})
        elif "_" in base:
            named.append({"name": ident, "registered": False, "relevance": "not a registered check"})
    new_check = NEW_CHECK_MARK.lower() in acc.lower()
    perm = sections.get("PERMISSIONS") or ""
    m = re.search(r"(?im)^\s*subject\s*:\s*([A-Z_]+)\s*$", perm)
    declared = m.group(1) if m else None
    allowed = [x for x in subj.SUBJECTS if x != subj.UNKNOWN] + [SUBJECT_NONE]
    subject = declared if declared in allowed else subj.UNKNOWN
    plan = (sections.get("PLAN") or "").strip()
    question = sections.get("UNKNOWNS AND QUESTION") or ""
    has_question = "?" in question
    no_plan = not plan or plan.upper().startswith(NO_PLAN_MARK)
    acceptance = ("new_check_proposed" if new_check else
                  "registered_check_named_relevance_unproven" if any(n["registered"] for n in named) else
                  "none_usable")
    # ARB R1 (25.10): ONE assessment drives the record, the owner text and the CLI exit code. A missing or
    # empty required section is an incomplete preparation — provider status ``ok`` is not completeness.
    reasons = [f"required section {name} is missing or empty" for name in PREP_SECTIONS
               if not (sections.get(name) or "").strip()]
    if reasons:
        form = "incomplete"
    elif no_plan:
        form = "clarification" if has_question else "incomplete"
    elif acceptance == "none_usable" or subject == subj.UNKNOWN:
        form = "incomplete"           # a plan without a usable check or a vocabulary subject is not reviewable
    else:
        form = "plan"
    if no_plan and not has_question:
        reasons.append("no plan and no question to the owner")
    if not no_plan and acceptance == "none_usable":
        reasons.append("the acceptance proposal names no registered check and proposes no new one")
    if subject == subj.UNKNOWN:
        reasons.append(f"PERMISSIONS subject {declared!r} is not in the ADR-285 vocabulary — reviewer decides")
    return {"form": form, "acceptable": form in ACCEPTABLE_FORMS, "acceptance": acceptance, "probes_named": named,
            "new_check_proposed": new_check, "subject": subject, "subject_declared": declared,
            "subject_note": SUBJECT_NOTE, "question": has_question, "reasons": reasons}


def is_current(record: Dict[str, Any], *, request: str, context_sha256: str, verified_sha: str) -> Dict[str, Any]:
    """Freshness barrier for any later use: the preparation belongs to EXACTLY this request text, this context
    and this verified revision. Any difference ⇒ stale (re-prepare), never «close enough»."""
    reasons = []
    if record.get("request_sha256") != _sha(request):
        reasons.append("request text changed")
    if record.get("context_sha256") != context_sha256:
        reasons.append("context changed")
    if (record.get("revisions") or {}).get("verified_code_sha") != verified_sha:
        reasons.append("verified revision changed")
    return {"current": not reasons, "reasons": reasons}


_FORM_RU = {"plan": "план готов к разбору", "clarification": "нужно уточнение владельца",
            "incomplete": "подготовка неполная — разбор обязателен"}
_ACC_RU = {"new_check_proposed": "предложено подготовить новую проверку (её ещё нет)",
           "registered_check_named_relevance_unproven": "названа существующая проверка — относится ли она к "
                                                        "поручению, НЕ установлено, решает разбор",
           "none_usable": "пригодной проверки не предложено"}


def render_preparation(r: Dict[str, Any]) -> str:
    rv = r["revisions"]
    head = [f"# Подготовка поручения — {r['task_id']}", "", f"> {r['disclaimer']}", "",
            "## Поручение (дословно)", "", "> " + r["task"].replace("\n", "\n> "), "",
            f"- хеш поручения `{r['request_sha256']}` · контекст `{r['context_sha256']}` ({r['context_chars']} зн.)",
            f"- проверенный код `{rv['verified_code_sha']}` · HEAD `{rv['head']}`",
            f"- провайдер `{r['provider']}` (настоящий: {r['real_provider']}) · статус **{r['status']}** · попыток "
            f"{r['attempts']}"]
    if r["status"] != "ok":
        return "\n".join(head + ["", f"## Плана нет — {r['status']}", "", str(r["reason"]),
                                 "", f"Поручение сохранено выше дословно; вызовов: {r['attempts']} (политика роли, "
                                     "без запасного провайдера)."]) + "\n"
    p = r["preparation"]
    if not isinstance(p, dict):
        return "\n".join(head + ["", "## Сверка не выполнена — подготовка не читается как план"]) + "\n"
    titles = {"OUTCOME": "Что должно получиться", "PLAN": "План", "ACCEPTANCE PROPOSAL": "Как проверим результат",
              "UNKNOWNS AND QUESTION": "Что неизвестно / вопрос", "PERMISSIONS": "Полномочия"}
    body = ["", f"**Итог подготовки: {_FORM_RU.get(p.get('form'), p.get('form'))}.**"]
    for s in PREP_SECTIONS:
        body += ["", f"## {titles[s]}", "", r["sections"][s] or "НЕТ — ответ не содержал этот раздел"]
        if s == "ACCEPTANCE PROPOSAL":
            body += ["", f"_Сверка:_ {_ACC_RU.get(p.get('acceptance'), '')}."]
            for n in p.get("probes_named") or []:
                body.append(f"- `{n['name']}` — " + ("зарегистрирована; отношение к поручению не установлено"
                                                    if n["registered"] else "не зарегистрирована"))
        if s == "PERMISSIONS":
            body += ["", f"_Сверка предмета:_ `{p.get('subject')}`"
                     + ("" if p.get("subject") != "UNKNOWN" else " — не из словаря ADR-285, решает разбор")
                     + f". {SUBJECT_NOTE[0].upper()}{SUBJECT_NOTE[1:]}."]
    if p.get("reasons"):
        body += ["", "## Замечания сверки", ""] + [f"- {x}" for x in p["reasons"]]
    return "\n".join(head + body) + "\n"


def render_recommendation(r: Dict[str, Any]) -> str:
    rv = r["revisions"]
    head = [f"# Architecture review — {r['task_id']}", "",
            f"> {r['disclaimer']}", "",
            f"- task: {r['task']}",
            f"- verified code: `{rv['verified_code_sha']}` · HEAD `{rv['head']}` · HEAD code is verified: "
            f"{rv['head_code_is_verified']}",
            f"- provider: `{r['provider']}` (real provider: {r['real_provider']}) · model (as reported): {r['model']}",
            f"- status: **{r['status']}** · attempts {r['attempts']} · {r['elapsed_s']} s · usage: "
            f"{json.dumps(r['usage'], ensure_ascii=False)}",
            f"- context sha256 `{r['context_sha256']}` · {r['context_chars']} chars · complete: "
            f"**{r['context_complete']}**"]
    if r["context_unknown"]:
        head += ["", "## Context gaps (UNKNOWN)", ""] + [f"- {u}" for u in r["context_unknown"]]
    if r["status"] != "ok":
        return "\n".join(head + ["", f"## No recommendation — {r['status']}", "", str(r["reason"])]) + "\n"
    body = []
    for s in SECTIONS:
        body += ["", f"## {s.title()}", "", r["sections"][s] or "MISSING — the answer did not contain this section"]
    if r["missing_sections"]:
        body += ["", "## Structure incomplete", "", ", ".join(r["missing_sections"])]
    return "\n".join(head + body) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="spa_core.studio_os.memory arch-review")
    ap.add_argument("--root", type=Path, default=role_pack.CODE_REPO)
    ap.add_argument("--handover", required=True)
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--verified-sha", required=True)
    ap.add_argument("--provider", default=None, help="explicit provider id (no default routing)")
    ap.add_argument("--roadmap-item", type=int, default=None)
    ap.add_argument("--extra-context", type=Path, action="append", default=[])
    ap.add_argument("--fixture", type=Path, default=None, help="answers for the TEST adapter")
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--kind", choices=(KIND_ARCH, KIND_PREP), default=KIND_ARCH,
                    help="arch — architecture review (default); task-prep — prepare ONE ordinary owner request")
    a = ap.parse_args(argv)
    try:
        # Paths the CLI prints or quotes in diagnostics (out in the summary, config in its error).
        for field, value in (("--out", a.out), ("--config", a.config), ("--fixture", a.fixture),
                             ("--root", a.root)):
            refuse_if_credential(field, None if value is None else str(value))
    except ReviewError as exc:
        print(f"REVIEW NOT BUILT: {exc}")
        return 2
    adapters = {"claude_cli": ad.claude_cli()}
    if a.fixture:
        adapters["fixture"] = ad.fixture_from_file(a.fixture)
    try:
        cfg = load_config(a.config)
        rec = run_review(a.root, handover=a.handover, task_id=a.task_id, task=a.task,
                         verified_sha=a.verified_sha, provider=a.provider, out=a.out,
                         roadmap_item=a.roadmap_item, extra=a.extra_context, adapters=adapters, config=cfg,
                         kind=a.kind)
    except (ReviewError, ConfigError) as exc:
        print(f"REVIEW NOT BUILT: {exc}")
        return 2
    prep = rec.get("preparation") if rec.get("kind") == KIND_PREP else None
    form = prep.get("form") if isinstance(prep, dict) else "not assessed"
    print(f"{rec['status']} · structure complete {rec['structure_complete']} · context complete "
          f"{rec['context_complete']}" + (f" · preparation {form}" if rec.get("kind") == KIND_PREP else "")
          + f" → {a.out}/recommendation.md")
    if rec["status"] == "refused":
        return 2
    if rec.get("kind") == KIND_PREP:   # ARB R2: the exit follows the SAME assessment as the record and the text
        return 0 if rec["status"] == "ok" and isinstance(prep, dict) and prep.get("acceptable") is True else 1
    return 0 if rec["structure_complete"] else 1


def main_record(argv: Optional[List[str]] = None) -> int:
    """``python -m spa_core.studio_os.memory prepare-record`` — EXPLICIT task-prep of ONE cockpit record.
    Exit: 0 prepared and acceptable, or unchanged and current · 1 prepared but not acceptable · 2 refused."""
    ap = argparse.ArgumentParser(prog="spa_core.studio_os.memory prepare-record")
    ap.add_argument("--root", type=Path, default=role_pack.CODE_REPO)
    ap.add_argument("--card", type=Path, required=True)
    ap.add_argument("--prep-root", type=Path, required=True)
    ap.add_argument("--handover", required=True)
    ap.add_argument("--verified-sha", required=True)
    ap.add_argument("--provider", default=None, help="explicit provider id (no default routing)")
    ap.add_argument("--roadmap-item", type=int, default=None)
    ap.add_argument("--extra-context", type=Path, action="append", default=[])
    ap.add_argument("--fixture", type=Path, default=None, help="answers for the TEST adapter")
    ap.add_argument("--config", type=Path, default=None)
    a = ap.parse_args(argv)
    adapters = {"claude_cli": ad.claude_cli()}
    if a.fixture:
        adapters["fixture"] = ad.fixture_from_file(a.fixture)
    try:
        for field, value in (("--card", a.card), ("--prep-root", a.prep_root), ("--config", a.config),
                             ("--fixture", a.fixture), ("--root", a.root)):
            refuse_if_credential(field, None if value is None else str(value))
        res = prepare_record(a.root, a.card, a.prep_root, handover=a.handover, verified_sha=a.verified_sha,
                             provider=a.provider, adapters=adapters, config=load_config(a.config),
                             extra=a.extra_context, roadmap_item=a.roadmap_item)
    except (ReviewError, ConfigError) as exc:
        print(f"PREPARATION NOT BUILT: {exc}")
        return 2
    st = res["state"]
    print(f"{res['action']} · state {st['state']} · form {st.get('form')} → {res['run']}")
    return 0 if st["state"] == "current" else 1
