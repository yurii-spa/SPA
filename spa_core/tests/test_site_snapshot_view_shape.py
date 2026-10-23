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

**С 2026-10-23 — классификация по замеру, а не по списку** (решение ARB). Путь снимка вне
переходника допустим, только если замер доводит его до страницы через витрину (подмена значения
всплывает в витрине настоящим сборщиком И этот путь витрины кто-то читает — сам переходник не в
счёт), либо он объявлен С ДОКАЗАТЕЛЬСТВОМ (таблицы ниже; ложное и лишнее объявление — красные).
Чтения самих страниц проверяет `test_site_projection_chain.py`.

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
# ADR-531, вариант A владельца 01.10: опубликованное число книги (apy_pct/dd_pct/days) уже
# посчитано ТОЛЬКО по v2-строкам, а искажённый период идёт меткой pre_fix_period (в переходнике).
R_MODEL = "провенанс модели издержек для аудита; страница показывает метку pre_fix_period (ADR-531)"
R_POST = ("дубль опубликованного v2-числа для аудита: при варианте A apy_pct сам считается только "
          "по v2-строкам, страница читает его (ADR-531)")

NOT_IN_VIEW = {
    # ADR-533: аудит-провенанс текущего эксперимента; страница показывает его из package_status
    "/paper_tracks/balanced/earlier_version_rows": "аудит: строки прошлой версии стратегии, страница не печатает",
    "/paper_tracks/aggressive/earlier_version_rows": "аудит: строки прошлой версии стратегии, страница не печатает",
    "/paper_tracks/balanced/experiment_id": "идентификатор эксперимента — страница берёт его из package_status",
    "/paper_tracks/aggressive/experiment_id": "идентификатор эксперимента — страница берёт его из package_status",
    "/note": "текст для человека, не число",
    "/generator": "имя генератора снимка — провенанс, не показатель",
    "/generated_from": "перечень источников снимка — провенанс, не показатель",
    "/paper_tracks/conservative/days_funded": "не читает ни одна страница (замер 13.09)",
    "/paper_tracks/balanced/days_funded": "не читает ни одна страница (замер 13.09)",
    "/paper_tracks/aggressive/days_funded": "не читает ни одна страница (замер 13.09)",
    "/paper_tracks/balanced/economics_model": R_MODEL,
    "/paper_tracks/balanced/economics_model_boundary": R_MODEL,
    "/paper_tracks/balanced/post_fix": R_POST,
    "/paper_tracks/balanced/post_fix/apy_pct": R_POST,
    "/paper_tracks/balanced/post_fix/days": R_POST,
    "/paper_tracks/balanced/post_fix/first_date": R_POST,
    "/paper_tracks/balanced/post_fix/model": R_POST,
    "/paper_tracks/balanced/post_fix/pre_fix_days": R_POST,
    "/paper_tracks/aggressive/economics_model": R_MODEL,
    "/paper_tracks/aggressive/economics_model_boundary": R_MODEL,
    "/paper_tracks/aggressive/post_fix": R_POST,
    "/paper_tracks/aggressive/post_fix/apy_pct": R_POST,
    "/paper_tracks/aggressive/post_fix/days": R_POST,
    "/paper_tracks/aggressive/post_fix/first_date": R_POST,
    "/paper_tracks/aggressive/post_fix/model": R_POST,
    "/paper_tracks/aggressive/post_fix/pre_fix_days": R_POST,
}

# The ADR-531 boundary record grows sub-fields once a book has corrected-model rows — the same audit
# provenance as its parent, never printed by a page.
for _b in ("balanced", "aggressive"):
    for _f in ("adr", "defect", "defect_found_at", "first_v2_date", "v1_classification", "v1_last_date",
               "v1_model", "v1_rows", "v2_activated_at", "v2_model"):
        NOT_IN_VIEW[f"/paper_tracks/{_b}/economics_model_boundary/{_f}"] = R_MODEL

# ── С 2026-10-23 база NOT_IN_VIEW не текст, а утверждение, которое МЕРЯЕТСЯ ────────────────────
# (`_site_projection.classify_snapshot_paths`). Каждая запись этой и трёх таблиц ниже принимается
# только с доказательством, а запись, которую замер делает лишней, — сама находка:
#   NOT_IN_VIEW / UNPUBLISHED — подмена значения пути не меняет НИЧЕГО в витрине, и снимок по этому
#                               пути напрямую не читает ни один модуль сайта;
#   NOT_IN_VIEW / SHELF_ONLY  — подмена всплывает в витрине, но ни одна страница и ни один модуль,
#                               кроме самого переходника, этот путь витрины не читают;
#   DUPLICATE_OF              — значение равно (с названным округлением) пути, который до страницы
#                               ДОХОДИТ, а сам путь не читает никто.
# Пути, которые доходят до страницы через витрину (подмена всплывает в витрине И этот путь витрины
# читают), классифицируются замером и записи не требуют — так ушли из базы `/total_return_pct` и
# оба `observed_accrual_since` (их читают `realized_rate.totalReturnSinceStart` и /packages).

R_PERIOD_AUDIT = ("доказательство периода для аудита (track_period_return.py, P1 Wave 2): витрина несёт "
                  "его рядом с доходностью за период, страница печатает саму доходность, NAV, даты, дни "
                  "и потоки — `realized_rate.periodReturn`")

SHELF_ONLY = {
    "/track_period/annualised_formula": R_PERIOD_AUDIT,
    "/track_period/continuity_repaired": R_PERIOD_AUDIT,
    "/track_period/costs_basis": R_PERIOD_AUDIT,
    "/track_period/nav_start_basis": R_PERIOD_AUDIT,
    "/track_period/flows/basis": R_PERIOD_AUDIT,
    "/track_period/flows/items": R_PERIOD_AUDIT + "; при нуле потоков страница печатает «внешних потоков нет» по flows.count",
    "/track_period/flows/unchecked_bars": R_PERIOD_AUDIT,
    "/track_period/gaps": R_PERIOD_AUDIT + "; пропуски дней страница выводит из самих баров (track-record)",
    "/track_period/provenance": R_PERIOD_AUDIT + "; происхождение ставок по барам",
    "/track_period/period/accrual_bars": R_PERIOD_AUDIT,
    "/track_period/period/start_ts": R_PERIOD_AUDIT + "; время начальной оценки не записано — страница говорит это словами",
    "/track_period/period/start_ts_reason": R_PERIOD_AUDIT,
    "/track_period/period/end_ts": R_PERIOD_AUDIT,
    "/track_period/twr_pct": "сверка метода: при нуле внешних потоков TWR = MWR = доходности за период; "
                             "страница печатает headline.period.return",
    "/track_period/mwr_pct": "сверка метода: при нуле внешних потоков TWR = MWR = доходности за период; "
                             "страница печатает headline.period.return",
    "/book_exposure/base": "словесное определение базы долей; страница печатает саму базу в USD (base_usd)",
}

UNPUBLISHED = {
    "/book_exposure/source": "провенанс снимка (имена входов), не показатель; у каждого числа витрины свой source",
    "/track_period/annualised_approval_required": "витрина объявляет approval_required сама "
                                                  "(ANNUALISED_DISPLAY в build_site_numbers.py), снимок — для аудита",
}

#: путь → (путь, который доходит до страницы; знаков округления или None — точное равенство)
DUPLICATE_OF = {
    "/anchor_equity": ("/track_period/nav_start", None),
    "/track_end_date": ("/track_period/period/end_date", None),
    "/track_return_pct": ("/track_period/period_return_pct", 4),
    "/track_period/annualised_equivalent_pct": ("/paper_apy_pct", 4),
    "/paper_tracks/balanced/post_fix/reportable": ("/paper_tracks/balanced/reportable", None),
    "/paper_tracks/balanced/post_fix/reportable_after": ("/paper_tracks/balanced/reportable_after", None),
    "/paper_tracks/aggressive/post_fix/reportable": ("/paper_tracks/aggressive/reportable", None),
    "/paper_tracks/aggressive/post_fix/reportable_after": ("/paper_tracks/aggressive/reportable_after", None),
}

DECLARATIONS = (("NOT_IN_VIEW", NOT_IN_VIEW), ("SHELF_ONLY", SHELF_ONLY), ("UNPUBLISHED", UNPUBLISHED),
                ("DUPLICATE_OF", DUPLICATE_OF))

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


def _classify(view=None, decl=None):
    """Classification of every snapshot path against the MEASURED chain (``_site_projection``)."""
    from spa_core.tests import _site_projection as sp
    m = sp.measure()
    tables = dict(DECLARATIONS if decl is None else decl)
    return sp.classify_snapshot_paths(
        m.today_snap, m.scenes[0].out["view"] if view is None else view, m.pmap, m.reads,
        tables["NOT_IN_VIEW"], tables["SHELF_ONLY"], tables["UNPUBLISHED"], tables["DUPLICATE_OF"])


class TheViewCoversTheSnapshotShape(unittest.TestCase):
    def setUp(self):
        if not VIEW.is_file() or not SNAPSHOT.is_file() or not SHELF.is_file():
            self.skipTest("сайт не развёрнут в этом дереве")
        try:
            self.view = load_view()
            from spa_core.tests import _site_projection as sp
            self.m = sp.measure()
        except (NotMeasured, RuntimeError) as exc:
            self.fail(f"НЕ ИЗМЕРЕНО — {exc}")

    def test_the_harness_view_is_the_view(self):
        """The chain is measured on the view the harness built under recording proxies; it must be
        the same object the plain loader gives — otherwise the classification measures something else."""
        self.assertEqual(self.m.scenes[0].out["view"], self.view)

    def test_every_snapshot_field_is_covered_or_declared(self):
        """Каждый путь снимка: в переходнике · витрина + её читатель · объявлен С ДОКАЗАТЕЛЬСТВОМ."""
        cls, problems = _classify()
        self.assertEqual(problems, [], (
            "пути снимка без машинной классификации: " + "\n".join(problems) + "\nВ JavaScript отсутствие "
            "поля — не ошибка, а `undefined`. Либо вернуть поле в переходник, либо объявить его в одной из "
            "таблиц — и объявление будет ПРОВЕРЕНО (подменой значения и перечнем чтений), а не принято на слово."))
        self.assertTrue(all(c is not None for c in cls.values()))

    def test_the_declared_exclusions_are_real(self):
        """База может только уменьшаться: путь, которого в снимке уже нет, — мусор."""
        snap_paths = paths(json.loads(SNAPSHOT.read_text(encoding="utf-8")))
        for name, table in DECLARATIONS:
            stale = sorted(p for p in table if p not in snap_paths)
            self.assertEqual(stale, [], f"в {name} пути, которых нет в снимке: {stale}")

    def test_every_exclusion_carries_a_reason(self):
        for name, table in DECLARATIONS:
            empty = sorted(k for k, v in table.items() if not str(v[0] if isinstance(v, tuple) else v).strip())
            self.assertEqual(empty, [], f"{name}: исключение без причины: {empty}")

    def test_the_guard_reddens_when_a_nested_field_disappears(self):
        """Положительный контроль ФОРМОЙ НАСТОЯЩЕЙ АВАРИИ, а не выдуманным именем.

        Первая редакция проверки брала несуществующее имя и проходила всегда — то есть
        была украшением. Здесь снимается тот самый вложенный ключ, который и пропал.
        Витрина его по-прежнему несёт (``books.*.positions``) — и это НЕ спасает: сам переходник
        не считается читателем, а другого читателя у этого числа нет.
        """
        crippled = json.loads(json.dumps(self.view))
        for book in (crippled.get("paper_tracks") or {}).values():
            book.pop("positions_count", None)
        _, problems = _classify(view=crippled)
        self.assertTrue(any("positions_count" in p for p in problems),
                        "снятие вложенного поля не замечено — сторож слеп на аварию, ради которой написан")

    def test_the_guard_reddens_when_the_view_source_drops_positions_count(self):
        """Тот же контроль на ИСХОДНИКЕ переходника: строка `positions_count` убрана из
        snapshot_view.js, модуль исполнен заново — классификация краснеет."""
        from spa_core.tests import _site_projection as sp
        src = VIEW.read_text(encoding="utf-8")
        line = [ln for ln in src.splitlines(True) if ln.strip().startswith("positions_count:")]
        self.assertEqual(len(line), 1, "предпосылка контроля: в переходнике ровно одна строка positions_count")
        out = sp.run_harness(self.m.shelf, self.m.today_snap, [], [], overrides={
            str(VIEW.resolve()): src.replace(line[0], "")})
        _, problems = _classify(view=out["view"])
        self.assertTrue(any(p.startswith("/paper_tracks/balanced/positions_count") for p in problems), problems)

    def test_a_false_declaration_is_red(self):
        """Объявление проверяется, а не принимается: путь, который доходит до страницы, нельзя
        объявить «не публикуется»; неверный дубль — красный; лишняя запись — красная."""
        decl = {k: dict(v) for k, v in DECLARATIONS}
        decl["UNPUBLISHED"]["/track_period/period/start_date"] = "ложь: страница его печатает"
        decl["DUPLICATE_OF"]["/track_period/nav_end"] = ("/track_period/nav_start", None)
        decl["SHELF_ONLY"]["/track_period/flows/count"] = "ложь: его читает realized_rate"
        decl["NOT_IN_VIEW"]["/total_return_pct"] = "лишнее: замер доводит его до страницы"
        _, problems = _classify(decl=tuple(decl.items()))
        for needle in ("/track_period/period/start_date", "/track_period/nav_end",
                       "/track_period/flows/count", "/total_return_pct"):
            self.assertTrue(any(p.startswith(needle) for p in problems), f"{needle}: {problems}")
        decl = {k: dict(v) for k, v in DECLARATIONS}
        decl["SHELF_ONLY"].pop("/track_period/twr_pct")
        _, problems = _classify(decl=tuple(decl.items()))
        self.assertTrue(any(p.startswith("/track_period/twr_pct") for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
