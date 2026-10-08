"""The site's percentage formatter (`site_numbers.js::fmtPct2`) and the Python one
(`spa_core.utils.presentation.fmt_pct`) print the SAME string for the same number (ADR-660).

Measured by OUTCOME: real `node` runs the real module file and prints. Two copies of one
rounding rule drift at the first edit; this is the instrument that says so.

`node` not found ⇒ НЕ ИЗМЕРЕНО as a loud failure, not a skip (lesson `pyflakes`, cycle #465).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from spa_core.utils.presentation import fmt_pct

_LIB = Path(__file__).resolve().parents[2] / "landing" / "src" / "lib"
_JSON_IMPORT = "import NUMBERS from '../data/site_numbers.json';"
_JSON_IMPORT_NODE = "import NUMBERS from '../data/site_numbers.json' with { type: 'json' };"

TIES = [4.8943, 4.895, 4.8999, 6, -1.225, 2.675, -2.675, 1.005, -0.005, 0.125, -0.125,
        0, 0.004, -0.004, 1e-7, -3.5e-9, 1234.565, 0.015, 99.995, -99.995]


def _node() -> str:
    found = shutil.which("node")
    if not found:
        pytest.fail("НЕ ИЗМЕРЕНО: `node` не найден — исход JS не наблюдён")
    return found


def _js_print(tmp_path: Path, values: list) -> list:
    lib = tmp_path / "src" / "lib"
    data = tmp_path / "src" / "data"
    lib.mkdir(parents=True)
    data.mkdir(parents=True)
    text = (_LIB / "site_numbers.js").read_text(encoding="utf-8").replace(_JSON_IMPORT, _JSON_IMPORT_NODE)
    assert _JSON_IMPORT_NODE in text, "the shelf import line changed — scene no longer loads the real module"
    (lib / "site_numbers.js").write_text(text, encoding="utf-8")
    (data / "site_numbers.json").write_text("{}", encoding="utf-8")
    (lib / "ask.mjs").write_text(
        "import { fmtPct2 } from './site_numbers.js';\n"
        f"const vs = {json.dumps(values)};\n"
        "console.log(JSON.stringify(vs.map(v => [fmtPct2(v, true), fmtPct2(v, false), fmtPct2(v, false, true)])));\n",
        encoding="utf-8")
    out = subprocess.run([_node(), str(lib / "ask.mjs")], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_js_and_python_agree_on_ties_and_random_values(tmp_path):
    rng = random.Random(660)
    values = TIES + [round(rng.uniform(-50, 50), rng.randint(0, 6)) for _ in range(400)]
    got = _js_print(tmp_path, values)
    want = [[fmt_pct(v, "ru"), fmt_pct(v, "en"), fmt_pct(v, "en", signed=True)] for v in values]
    mismatches = [(v, g, w) for v, g, w in zip(values, got, want) if g != w]
    assert not mismatches, mismatches[:10]


def test_js_absence_is_null_not_zero(tmp_path):
    lib = tmp_path / "s"
    got = _js_print(lib, [None, "4.8"])
    assert got == [[None, None, None], [None, None, None]]


def test_js_positive_control_toFixed_disagrees(tmp_path):
    """The same ties through the old `toFixed(2)` differ — so the agreement above is not vacuous."""
    _node()
    out = subprocess.run([_node(), "-e", "console.log(JSON.stringify([2.675,1.005,-0.005].map(v=>v.toFixed(2))))"],
                         capture_output=True, text=True, timeout=30)
    assert json.loads(out.stdout) != ["2.68", "1.01", "-0.01"]
