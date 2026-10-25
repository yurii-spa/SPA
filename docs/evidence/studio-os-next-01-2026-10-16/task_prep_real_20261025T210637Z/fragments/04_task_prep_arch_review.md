# Excerpt: spa_core/studio_os/memory/arch_review.py lines 1-24 and 66-103 — task-prep (at 9a07f8998, committed, unchanged)

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
...
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
                   "проверки не доказывает, что она меряет это поручение. Тестовый ответ не оценивает реальную модель.")
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
