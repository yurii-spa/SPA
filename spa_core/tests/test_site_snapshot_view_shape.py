#!/usr/bin/env python3
"""Переходник обязан НАКРЫВАТЬ форму снимка — иначе страница печатает «undefined».

ADR-373. Двадцать четыре страницы перестали читать дневной снимок и читают витрину через
`landing/src/lib/snapshot_view.js`. Переходник объявляет себя «снимком в прежней форме»,
и вся правка держится на этом обещании.

**Почему обещания мало.** В JavaScript обращение к отсутствующему полю — не ошибка, а
``undefined``: страница печатает слово «undefined» и собирается зелёной. Так и вышло при
переводе: `positions_count` в переходник не попал, и страница пакетов напечатала
«позиций: undefined». Поймал это дифференциал СОБРАННОГО HTML (сборка до и после), а не
сборщик и не глаза.

**Первая редакция этой проверки была УКРАШЕНИЕМ, и это стоит записать.** Она сверяла
списки имён регулярками: какие поля страницы спрашивают (`snap.поле`) против того, какие
переходник объявляет на верхнем уровне. Настоящая авария была ВЛОЖЕННОЙ
(`paper_tracks.balanced.positions_count`) — ни одна из двух регулярок её не видела.
Контроль, который я к ней написал, брал ВЫДУМАННОЕ имя и потому проходил всегда;
проверка снятием настоящего поля показала: сторож не краснеет. Отсюда нынешняя форма —
**поведенческая**: переходник загружается по-настоящему, и его форма сверяется с формой
снимка.

**Третий исход (инв. #17).** Нет `node` — «НЕ ИЗМЕРЕНО» с названной причиной, а не
молчаливый зелёный: отсутствие инструмента не есть отсутствие дефекта.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEW = ROOT / "landing" / "src" / "lib" / "snapshot_view.js"
SNAPSHOT = ROOT / "landing" / "src" / "data" / "track_snapshot.json"
SHELF = ROOT / "landing" / "src" / "data" / "site_numbers.json"

#: Пути снимка, которых в переходнике нет НАМЕРЕННО. База может только уменьшаться;
#: дописывать сюда путь, чтобы погасить падение, запрещено — у каждой строки причина.
NOT_IN_VIEW = {
    "/note": "текст для человека, не число",
    "/generator": "имя генератора снимка — провенанс, не показатель",
    "/generated_from": "перечень источников снимка — провенанс, не показатель",
    "/total_return_pct": "ни одна страница не читает его из снимка; кокпит-компоненты "
                         "берут это поле из API в рантайме (замер 13.09)",
    "/paper_tracks/conservative/days_funded": "не читает ни одна страница (замер 13.09)",
    "/paper_tracks/balanced/days_funded": "не читает ни одна страница (замер 13.09)",
    "/paper_tracks/aggressive/days_funded": "не читает ни одна страница (замер 13.09)",
    "/paper_tracks/balanced/observed_accrual_since": "заменено на evidence_split.observed_since",
    "/paper_tracks/aggressive/observed_accrual_since": "заменено на evidence_split.observed_since",
}

_DUMP = """
import { readFileSync } from 'node:fs';
import path from 'node:path';
const root = process.argv[2];
const src = readFileSync(path.join(root, 'landing/src/lib/snapshot_view.js'), 'utf8');
const NUMBERS = JSON.parse(readFileSync(path.join(root, 'landing/src/data/site_numbers.json'), 'utf8'));
const RAW = JSON.parse(readFileSync(path.join(root, 'landing/src/data/track_snapshot.json'), 'utf8'));
const body = src.split('\\n').filter((l) => !/^\\s*import\\s/.test(l)).join('\\n')
  .replace(/export\\s+default\\s+/, 'return ');
console.log(JSON.stringify(new Function('NUMBERS', 'RAW', body)(NUMBERS, RAW)));
"""


class NotMeasured(RuntimeError):
    """Замер не состоялся; причина названа."""


def load_view(root: Path = ROOT) -> dict:
    node = shutil.which("node")
    if node is None:
        raise NotMeasured("`node` не найден — форму переходника нечем снять")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "dump.mjs"
        script.write_text(_DUMP, encoding="utf-8")
        try:
            out = subprocess.run([node, str(script), str(root)], capture_output=True,
                                 text=True, timeout=60)
        except Exception as exc:  # noqa: BLE001
            raise NotMeasured(f"node не запустился ({exc})") from exc
    if out.returncode != 0:
        raise NotMeasured(f"переходник не загрузился: {out.stderr.strip()[:200]}")
    try:
        return json.loads(out.stdout)
    except ValueError as exc:
        raise NotMeasured(f"вывод переходника не разобран ({exc})") from exc


def paths(obj, prefix: str = "") -> set:
    out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(f"{prefix}/{k}")
            if isinstance(v, dict):
                out |= paths(v, f"{prefix}/{k}")
    return out


class TheViewCoversTheSnapshotShape(unittest.TestCase):
    def setUp(self):
        if not VIEW.is_file() or not SNAPSHOT.is_file() or not SHELF.is_file():
            self.skipTest("сайт не развёрнут в этом дереве")
        try:
            self.view = load_view()
        except NotMeasured as exc:
            self.fail(f"НЕ ИЗМЕРЕНО — {exc}")

    def test_every_snapshot_field_is_covered_or_declared(self):
        snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        missing = sorted(paths(snap) - paths(self.view) - set(NOT_IN_VIEW))
        self.assertEqual(missing, [], (
            f"переходник не отдаёт поля снимка: {missing}. В JavaScript это не ошибка, "
            "а `undefined` — страница напечатает слово «undefined» молча. Либо добавить "
            "поле в переходник, либо объявить его в NOT_IN_VIEW С ПРИЧИНОЙ."))

    def test_the_declared_exclusions_are_real(self):
        """База может только уменьшаться: путь, которого в снимке уже нет, — мусор."""
        snap_paths = paths(json.loads(SNAPSHOT.read_text(encoding="utf-8")))
        stale = sorted(p for p in NOT_IN_VIEW if p not in snap_paths)
        self.assertEqual(stale, [], f"в базе исключений пути, которых нет в снимке: {stale}")

    def test_every_exclusion_carries_a_reason(self):
        empty = sorted(k for k, v in NOT_IN_VIEW.items() if not str(v).strip())
        self.assertEqual(empty, [], f"исключение без причины: {empty}")

    def test_the_guard_reddens_when_a_nested_field_disappears(self):
        """Положительный контроль ФОРМОЙ НАСТОЯЩЕЙ АВАРИИ, а не выдуманным именем.

        Первая редакция проверки брала несуществующее имя и проходила всегда — то есть
        была украшением. Здесь снимается тот самый вложенный ключ, который и пропал.
        """
        crippled = json.loads(json.dumps(self.view))
        for book in (crippled.get("paper_tracks") or {}).values():
            book.pop("positions_count", None)
        snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        missing = sorted(paths(snap) - paths(crippled) - set(NOT_IN_VIEW))
        self.assertTrue(any("positions_count" in m for m in missing),
                        "снятие вложенного поля не замечено — сторож слеп на аварию, "
                        "ради которой написан")


if __name__ == "__main__":
    unittest.main()
