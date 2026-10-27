"""ARB read-only source review. All writes stay in a temporary directory.

The session-answer guard is executed unchanged from its AST, with the final
writer replaced by a recorder. Work-packet functions run from a byte copy.
No production imports, tracker writes, model calls or network requests.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

ROOT = Path('/Users/yuriikulieshov/Documents/SPA_Claude')
HERE = Path(__file__).resolve().parent
sources = {
    'owner_answer': ROOT / 'spa_core/owner_queue/owner_answer.py',
    'work_packet': ROOT / 'spa_core/studio_os/work_packet.py',
}
result = {'source_sha256': {}, 'cases': []}
for name, path in sources.items():
    raw = path.read_bytes()
    result['source_sha256'][str(path)] = hashlib.sha256(raw).hexdigest()
    (HERE / (name + '_reviewed.py')).write_bytes(raw)

tree = ast.parse(sources['owner_answer'].read_text())
guard = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name == 'record_session_answer')
module = ast.Module(body=[ast.ImportFrom(module='__future__',
    names=[ast.alias(name='annotations')], level=0), guard], type_ignores=[])
ast.fix_missing_locations(module)

class NotTheOwner(PermissionError):
    pass

ns = {'Path': Path, 'KIND_OPTION': 'option', 'SESSION_VIA': 'claude-code-session',
      'NotTheOwner': NotTheOwner, '_write_answer': lambda *a, **kw: kw}
exec(compile(module, str(sources['owner_answer']), 'exec'), ns)

spec = importlib.util.spec_from_file_location('arb_review_wp', HERE / 'work_packet_reviewed.py')
wp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wp)

with tempfile.TemporaryDirectory(prefix='arb-boundary-review-') as tmp:
    tmp = Path(tmp)
    card = tmp / 'owner-decision-review-example.md'
    card.write_text('---\nstatus: needs-owner\n---\nExample\n')
    for name, text in [
        ('ADR_mentions_card_without_any_answer', '# Notes\n' + card.stem),
        ('ADR_says_option_1_but_caller_submits_option_2',
         '# Recorded answer\n| ' + card.stem + ' | 1 | reject |'),
        ('ADR_names_a_different_card_with_matching_prefix', '# Notes\n' + card.stem + '-other'),
    ]:
        adr = tmp / 'ADR-999-example.md'
        adr.write_text(text)
        try:
            forwarded = ns['record_session_answer'](card, choice_num='2',
                choice_label='a different answer', adr_path=adr)
            result['cases'].append({'case': name, 'writer_reached': True,
                                    'choice_forwarded': forwarded['choice_num']})
        except NotTheOwner:
            result['cases'].append({'case': name, 'writer_reached': False})

    pkt = {'task_id': 'task-a', 'status': 'awaiting_approval',
           'version': 'example-plan-v1', 'owner_subject': 'money'}
    wrong_task = {'task_id': 'task-b', 'version': pkt['version'], 'role': 'agent'}
    result['cases'].append({'case': 'ready_accepts_wrong_task_and_insufficient_role',
                           'accepted': wp.ready(pkt, wrong_task, 'unregistered_probe:x')})
    ap = wp.approve(pkt, version=pkt['version'], approver='owner-test', role='owner', at='test-time')
    wp.record_approval(tmp, ap)
    out = wp.record_outcome(tmp, pkt, probe='unregistered_probe:x',
                            verdict='satisfied', detail='no probe was run', at='test-time')
    result['cases'].append({'case': 'record_outcome_accepts_unregistered_unrun_probe',
                           'written': out.exists(), 'outcome': json.loads(out.read_text())})

(HERE / 'reproduction_results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(result, ensure_ascii=False, indent=2))
