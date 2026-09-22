"""Tier-1 P0: контракт Архитектора, задел исследований системы, разбор очереди владельца.

Каждый класс проверяет ОБЕ стороны: что верное принимается и что неверное отвергается.
Проверка одной стороны сделала бы зелёной константу.
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'cartographer'))

import architect_contract as ac      # noqa: E402
import owner_decisions as od         # noqa: E402
import system_rnd as sr              # noqa: E402

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)
E = ac.evidence_item


def sandbox():
    """Одноразовое дерево: проверки улик не имеют права зависеть от живого прода."""
    root = Path(tempfile.mkdtemp(prefix='architect-'))
    (root / 'data').mkdir()
    (root / 'exists.txt').write_text('x', encoding='utf-8')
    (root / 'data' / 'doc.json').write_text(
        json.dumps({'flag': False, 'nested': {'value': 7}}), encoding='utf-8')
    return root


def proposal(**over):
    base = {
        'problem': 'нечто не работает',
        'current_state_evidence': [E('FILE', claim='файл есть', locator='exists.txt')],
        'architecture': 'как будет устроено',
        'alternatives': [{'name': 'A', 'rejected_because': 'дороже'},
                         {'name': 'B', 'rejected_because': 'создаёт второе место'}],
        'selected_recommendation': 'вариант C',
        'risks': ['можно сделать хуже'],
        'acceptance_criteria': [{'check': 'проба краснеет на подделанном входе'}],
        'implementation_tasks': ['сделать'],
        'permission_zone': {'may_write': ['spa_core/monitoring/']},
        'owner_decisions_required': [],
        'owner_decisions_none_basis': 'ни один из трёх предметов не затронут',
        'implementation_package': {'entry': 'x.py'},
    }
    base.update(over)
    return base


class EvidenceVerification(unittest.TestCase):
    """Улика текущего состояния проверяется машинно — в этом весь смысл контракта."""

    def setUp(self):
        self.root = sandbox()

    def test_existing_file_is_verified(self):
        r = ac.verify_evidence(E('FILE', claim='c', locator='exists.txt'),
                               production_root=self.root)
        self.assertEqual(r['state'], 'VERIFIED')

    def test_missing_file_is_refuted(self):
        r = ac.verify_evidence(E('FILE', claim='c', locator='nope.txt'),
                               production_root=self.root)
        self.assertEqual(r['state'], 'REFUTED')

    def test_absence_is_a_first_class_evidence_kind(self):
        # «Такого файла нет» — измерение, а не отговорка.
        self.assertEqual(ac.verify_evidence(
            E('ABSENCE', claim='нет', locator='nope.txt'),
            production_root=self.root)['state'], 'VERIFIED')

    def test_false_absence_is_refuted(self):
        self.assertEqual(ac.verify_evidence(
            E('ABSENCE', claim='нет', locator='exists.txt'),
            production_root=self.root)['state'], 'REFUTED')

    def test_field_value_must_match(self):
        ok = ac.verify_evidence(E('FIELD', claim='c', locator='data/doc.json:flag',
                                  value=False), production_root=self.root)
        bad = ac.verify_evidence(E('FIELD', claim='c', locator='data/doc.json:flag',
                                   value=True), production_root=self.root)
        self.assertEqual(ok['state'], 'VERIFIED')
        self.assertEqual(bad['state'], 'REFUTED')

    def test_nested_field_path_works(self):
        self.assertEqual(ac.verify_evidence(
            E('FIELD', claim='c', locator='data/doc.json:nested.value', value=7),
            production_root=self.root)['state'], 'VERIFIED')

    def test_absent_field_is_refuted(self):
        self.assertEqual(ac.verify_evidence(
            E('FIELD', claim='c', locator='data/doc.json:nothere'),
            production_root=self.root)['state'], 'REFUTED')

    def test_measurement_is_checked_against_the_projection(self):
        proj = {'facts': [{'metric': 'm', 'value': 1.5}]}
        ok = ac.verify_evidence(E('MEASUREMENT', claim='c', locator='m', value=1.5),
                                production_root=self.root, projection=proj)
        bad = ac.verify_evidence(E('MEASUREMENT', claim='c', locator='m', value=9.9),
                                 production_root=self.root, projection=proj)
        missing = ac.verify_evidence(E('MEASUREMENT', claim='c', locator='нетакой'),
                                     production_root=self.root, projection=proj)
        self.assertEqual(ok['state'], 'VERIFIED')
        self.assertEqual(bad['state'], 'REFUTED')
        self.assertEqual(missing['state'], 'REFUTED')

    def test_measurement_without_a_projection_is_not_measured(self):
        self.assertEqual(ac.verify_evidence(
            E('MEASUREMENT', claim='c', locator='m'),
            production_root=self.root)['state'], ac.verify_evidence(
            E('MEASUREMENT', claim='c', locator='m'),
            production_root=self.root)['state'])
        self.assertEqual(ac.verify_evidence(
            E('MEASUREMENT', claim='c', locator='m'),
            production_root=self.root)['state'], 'NOT_MEASURED')

    def test_command_evidence_is_never_executed(self):
        # Проверка вывода не имеет права ничего запускать.
        r = ac.verify_evidence(E('COMMAND', claim='c', locator='rm -rf /'),
                               production_root=self.root)
        self.assertEqual(r['state'], 'NOT_MEASURED')

    def test_evidence_without_a_locator_is_refused(self):
        with self.assertRaises(ValueError):
            E('FILE', claim='c', locator='')

    def test_unknown_evidence_kind_is_refused(self):
        with self.assertRaises(ValueError):
            E('ПОВЕРЬТЕ_НА_СЛОВО', claim='c', locator='x')


class ArchitectContract(unittest.TestCase):
    def setUp(self):
        self.root = sandbox()

    def _ok(self, **over):
        return ac.validate_output(proposal(**over), production_root=self.root)

    def _refused(self, **over):
        with self.assertRaises(ac.ContractError) as cm:
            ac.validate_output(proposal(**over), production_root=self.root)
        return cm.exception.reasons

    def test_complete_proposal_is_accepted(self):
        r = self._ok()
        self.assertEqual(r['state'], 'ACCEPTED_BY_CONTRACT')
        self.assertEqual(r['evidence_counts']['REFUTED'], 0)

    def test_every_required_section_is_required(self):
        for section in ac.REQUIRED_SECTIONS:
            doc = proposal()
            doc.pop(section)
            with self.assertRaises(ac.ContractError, msg=f'раздел {section} не обязателен'):
                ac.validate_output(doc, production_root=self.root)

    def test_single_alternative_is_not_an_analysis(self):
        self.assertTrue(any('меньше двух' in r for r in
                            self._refused(alternatives=[{'name': 'A',
                                                         'rejected_because': 'x'}])))

    def test_alternative_without_a_reason_is_refused(self):
        self._refused(alternatives=[{'name': 'A'}, {'name': 'B', 'rejected_because': 'x'}])

    def test_unbounded_permission_zone_is_refused(self):
        for bad in ('.', '/', '*', '**'):
            self._refused(permission_zone={'may_write': [bad]})

    def test_empty_permission_zone_is_refused(self):
        self._refused(permission_zone={'may_write': []})

    def test_unverifiable_acceptance_criterion_is_refused(self):
        self._refused(acceptance_criteria=[{'check': 'будет реализовано'}])

    def test_empty_owner_list_needs_a_basis(self):
        self._refused(owner_decisions_none_basis=None)

    def test_owner_decision_must_name_a_subject(self):
        self._refused(owner_decisions_required=[{'what': 'нечто'}])
        r = self._ok(owner_decisions_required=[{'what': 'нечто', 'subject': '1'}])
        self.assertEqual(r['state'], 'ACCEPTED_BY_CONTRACT')

    def test_refuted_evidence_blocks_the_whole_output(self):
        reasons = self._refused(current_state_evidence=[
            E('FILE', claim='есть', locator='nope.txt')])
        self.assertTrue(any('ОПРОВЕРГНУТА' in r for r in reasons))

    def test_state_claim_in_prose_is_warned_about(self):
        r = self._ok(architecture='это уже работает')
        self.assertTrue(r['warnings'])

    def test_contract_acceptance_is_not_arb_acceptance(self):
        r = self._ok()
        self.assertIn('не на вопрос', r['contract_note'])

    def test_arb_input_keeps_the_roles_apart(self):
        r = self._ok()
        inp = ac.arb_input(r, proposal=proposal())
        self.assertEqual(inp['verdict_vocabulary'], list(ac.ARB_VERDICTS))
        self.assertIn('предложивший', inp['separation_note'])


class SystemRnd(unittest.TestCase):
    """Задел выводится из улик. Вопрос без улики собрать нельзя."""

    def test_question_without_evidence_is_refused(self):
        with self.assertRaises(ValueError):
            sr._q('AUTONOMY_STOP', 'почему?', evidence='')

    def test_unknown_trigger_is_refused(self):
        with self.assertRaises(ValueError):
            sr._q('ПРЕДЧУВСТВИЕ', 'почему?', evidence='улика')

    def test_no_evidence_gives_an_empty_backlog_not_invented_questions(self):
        m = sr.build_system_rnd(now=NOW)
        self.assertEqual(m['question_count'], 0)
        self.assertEqual(m['state'], 'NOT_MEASURED')

    def test_mass_unmeasured_health_raises_an_architecture_question(self):
        health = {'counts': {'total': 10, 'health_not_measured': 10,
                             'producing_not_measured': 0},
                  'health_contract_note': 'контракта нет', 'by_kind': {}}
        m = sr.build_system_rnd(service_health=health, now=NOW)
        self.assertTrue(any(q['trigger'] == 'MASS_NOT_MEASURED' for q in m['questions']))

    def test_partially_unmeasured_health_does_not(self):
        health = {'counts': {'total': 10, 'health_not_measured': 3,
                             'producing_not_measured': 1},
                  'health_contract_note': '', 'by_kind': {}}
        m = sr.build_system_rnd(service_health=health, now=NOW)
        self.assertFalse(any(q['trigger'] == 'MASS_NOT_MEASURED' for q in m['questions']))

    def test_one_recurring_failure_is_an_incident_three_are_a_class(self):
        one = {'findings': [{'status': 'ACTIVE_CONFIRMED', 'category': 'X'}]}
        three = {'findings': [{'status': 'ACTIVE_CONFIRMED', 'category': 'X'}] * 3}
        self.assertEqual(len(sr.from_reliability(one)), 0)
        self.assertEqual(len(sr.from_reliability(three)), 1)

    def test_autonomy_stop_names_the_next_stage_in_words(self):
        pipeline = {'autonomy_breaks_at': {'title': 'Приём', 'hand_off_to': 'CLASSIFICATION',
                                           'reason': 'мало', 'evidence_carrier': 'карточки'},
                    'stages': [{'stage': 'CLASSIFICATION', 'title': 'Разбор по предмету'}]}
        q = sr.from_pipeline(pipeline)[0]
        self.assertIn('Разбор по предмету', q['question'])
        self.assertNotIn('CLASSIFICATION', q['question'])

    def test_research_never_declares_a_production_change(self):
        health = {'counts': {'total': 5, 'health_not_measured': 5,
                             'producing_not_measured': 0},
                  'health_contract_note': 'x', 'by_kind': {'UNKNOWN': 2}}
        m = sr.build_system_rnd(service_health=health, now=NOW)
        for q in m['questions']:
            self.assertFalse(q['changes_production'])

    def test_backlog_is_honest_about_not_being_a_running_loop(self):
        health = {'counts': {'total': 5, 'health_not_measured': 5,
                             'producing_not_measured': 0},
                  'health_contract_note': 'x', 'by_kind': {}}
        m = sr.build_system_rnd(service_health=health, now=NOW)
        self.assertEqual(m['loop_stage_reached'], sr.STAGE_OBSERVED)
        self.assertIn('ЗАДЕЛ', m['running_note'])


class OwnerQueueClassification(unittest.TestCase):
    def test_subject_none_is_the_systems_work(self):
        cls, basis = od.classify_item({'subject': 'NONE', 'age_days': 1})
        self.assertEqual(cls, od.CLASS_SYSTEM)
        self.assertIn('работа агента', basis)

    def test_fresh_owner_subject_is_a_real_decision(self):
        cls, _ = od.classify_item({'subject': '1', 'age_days': 5})
        self.assertEqual(cls, od.CLASS_OWNER)

    def test_old_owner_subject_becomes_stale_not_dismissed(self):
        cls, basis = od.classify_item({'subject': '1', 'age_days': 400})
        self.assertEqual(cls, od.CLASS_STALE)
        self.assertIn('перемерить', basis)

    def test_undeclared_age_does_not_make_an_item_stale(self):
        # Отсутствие возраста — не повод объявить вопрос просроченным.
        cls, _ = od.classify_item({'subject': '1', 'age_days': None})
        self.assertEqual(cls, od.CLASS_OWNER)

    def test_unknown_subject_is_its_own_class(self):
        cls, _ = od.classify_item({'subject': None, 'age_days': 1})
        self.assertEqual(cls, od.CLASS_UNKNOWN)

    def test_classes_do_not_overlap(self):
        seen = set()
        for subject in ('1', '2', '3', 'NONE', None):
            for age in (None, 1.0, 999.0):
                cls, _ = od.classify_item({'subject': subject, 'age_days': age})
                self.assertIn(cls, od.ITEM_CLASSES)
                seen.add(cls)
        self.assertEqual(seen, set(od.ITEM_CLASSES) - {od.CLASS_UNKNOWN} | {od.CLASS_UNKNOWN})


if __name__ == '__main__':
    unittest.main()
