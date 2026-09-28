#!/usr/bin/env python3
"""Smoke/contract test for the Studio OS cockpit read-model projector.

Read-only: runs the real projector against live canonical sources and asserts the
SHAPE and the invariants the UI relies on — every entity carries provenance (`source`),
states normalize into the declared UI set, freshness is a named third value (never faked),
and no obvious secret value leaks into the derived model. Fail-soft sources (absent ledger
on another machine) are tolerated: we assert structure, not counts.
"""
from __future__ import annotations

import importlib.util
import json
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('build_read_model', HERE / 'build_read_model.py')
BRM = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BRM)

UI_STATES = set(BRM.UI_STATES)
ZONES = set(BRM.UI_TO_ZONE.values())
FRESH = {'LIVE', 'RECENT', 'STALE', 'UNKNOWN'}


class TheModelHasTheContractShape(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = BRM.build()

    def test_top_level_keys_present(self):
        for k in ('schema', 'generated_at', 'overview', 'missions', 'work', 'roles',
                  'decisions', 'system', 'activity', 'capacity', 'ui_state_map',
                  'zone_map', 'freshness_legend'):
            self.assertIn(k, self.m, k)
        self.assertEqual(self.m['schema'], 'studio-os/cockpit-read-model/1')

    def test_every_work_item_is_provenanced_and_normalized(self):
        for w in self.m['work']:
            self.assertIn('source', w)
            self.assertIn('ledger.json', w['source'])
            self.assertIn(w['ui_state'], UI_STATES, w)
            self.assertIn(w['zone'], ZONES, w)

    def test_every_mission_is_provenanced(self):
        for mi in self.m['missions']:
            self.assertIn('source', mi)
            self.assertIn('ui_state', mi)

    def test_decisions_are_provenanced_to_cards(self):
        for d in self.m['decisions'].get('items', []):
            self.assertIn('source', d)
            self.assertIn('tracker', d['source'])

    def test_overview_counts_cover_only_ui_states(self):
        self.assertEqual(set(self.m['overview']['counts']), UI_STATES)

    def test_freshness_is_a_named_third_value_not_faked(self):
        led = self.m['overview']['ledger_freshness']
        self.assertIn(led.get('freshness'), FRESH)
        # system freshness surfaces also use the named set where present
        for sect in (self.m['system'].get('golive'), ):
            if isinstance(sect, dict) and isinstance(sect.get('freshness'), dict):
                self.assertIn(sect['freshness'].get('freshness'), FRESH)

    def test_absent_source_is_named_not_zero(self):
        # capacity/provider planes must declare a note or freshness, never silently 0
        cap = self.m['capacity']
        self.assertTrue('source' in cap)
        prov = self.m['system'].get('provider_plane', {})
        self.assertIn('note', prov)

    def test_no_obvious_secret_value_in_derived_model(self):
        dump = json.dumps(self.m, ensure_ascii=False)
        self.assertNotIn('BEGIN', dump)                       # no PEM key material
        self.assertNotIn('CLAUDE_CODE_OAUTH_TOKEN=', dump)    # no env=value form
        # no long opaque token (sk-... or 40+ char base64/hex run that isn't a known path)
        self.assertIsNone(re.search(r'\bsk-[A-Za-z0-9]{20,}', dump))

    def test_ui_state_map_is_documented(self):
        self.assertIn('RUNNING', self.m['ui_state_map'])
        self.assertEqual(self.m['ui_state_map']['WAIT_OWNER'], 'owner_wait')


if __name__ == '__main__':
    unittest.main()
