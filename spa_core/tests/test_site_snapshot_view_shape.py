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

import importlib.util
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

# ───────────────────────── ADR-1117: причина ИЗМЕРЕНА, а не придумана ─────────────────────
# Шестьдесят один путь ниже объявлен по ЗАМЕРУ СПРОСА, а не словами «не нужно» (инв. #16).
# Прибор — `scripts/snapshot_view_field_demand.py`: он идёт по ДОРОГЕ значения (ввоз
# переходника → привязка → цепочка обращений, до четырёх хопов через псевдоним, разбор и
# помощника), раскрывает вычисляемый ключ во ВСЕХ соседей (fail-CLOSED) и даёт три исхода.
# Замер 2026-11-26 на `origin/main` 9611f1697: поверхность 228 файлов `landing/src/**`,
# корневых привязок 26, читают через переходник 42 пути, напрямую из снимка 3, НЕ ЧИТАЕТ
# НИКТО 323, дорог без вердикта 9 (названы поимённо прибором). Все 61 путь ниже попали
# РОВНО в «не читает никто», и это ПЕРЕМЕРЯЕТСЯ тестом
# `test_the_measured_exclusions_are_still_unread` — то есть строка живёт, пока замер её
# подтверждает, а не пока её никто не перечитывал.
#
# Где страница берёт это число ВМЕСТО снимка — тоже замер, а не предположение:
#   `track_period/*`  → витрина, `headline.period` (`lib/realized_rate.js`, одно
#                       определение: `spa_core/paper_trading/track_period_return.py`);
#   `book_exposure/*` → витрина, блок `exposure` (`lib/book_exposure.js`);
#   `*/reportable*`   → каноническая карточка, `p.history.reportable_after`
#                       (`lib/package_card.js`), а не книга снимка;
#   `paper_start_date`→ витрина, `track.paper_start_date`.
R_PERIOD = ("период трека страница берёт с ВИТРИНЫ (`headline.period` через "
            "`lib/realized_rate.js`); из снимка его не читает ни одна — замер "
            "`scripts/snapshot_view_field_demand.py` 26.11, читателей 0")
R_EXPOSURE = ("состав книги страница берёт с ВИТРИНЫ (блок `exposure` через "
              "`lib/book_exposure.js`); из снимка это поле не читает ни одна — замер "
              "`scripts/snapshot_view_field_demand.py` 26.11, читателей 0")
R_REPORTABLE = ("порог зрелости ставки страница читает из канонической карточки "
                "(`p.history.reportable_after`, `lib/package_card.js`), а не из книги "
                "снимка — замер `scripts/snapshot_view_field_demand.py` 26.11, читателей 0")
R_UNREAD = ("не читает ни одна страница `landing/src/**` — замер "
            "`scripts/snapshot_view_field_demand.py` 26.11 (поверхность 228 файлов, "
            "ни одного обращения ни по одной из четырёх дорог)")

NOT_IN_VIEW = {
    # ADR-533: аудит-провенанс текущего эксперимента; страница показывает его из package_status
    "/paper_tracks/balanced/earlier_version_rows": "аудит: строки прошлой версии стратегии, страница не печатает",
    "/paper_tracks/aggressive/earlier_version_rows": "аудит: строки прошлой версии стратегии, страница не печатает",
    "/paper_tracks/balanced/experiment_id": "идентификатор эксперимента — страница берёт его из package_status",
    "/paper_tracks/aggressive/experiment_id": "идентификатор эксперимента — страница берёт его из package_status",
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

    # ── ADR-1117: 61 путь, объявленный ЗАМЕРОМ СПРОСА (перемеряется ниже) ───────────
    "/anchor_equity": R_UNREAD,
    "/book_exposure": R_EXPOSURE,
    "/book_exposure/as_of": R_EXPOSURE,
    "/book_exposure/base": R_EXPOSURE,
    "/book_exposure/base_usd": R_EXPOSURE,
    "/book_exposure/cash_share_pct": R_EXPOSURE,
    "/book_exposure/cash_usd": R_EXPOSURE,
    "/book_exposure/rows": R_EXPOSURE,
    "/book_exposure/source": R_EXPOSURE,
    "/book_exposure/state": R_EXPOSURE,
    "/paper_start_date": R_UNREAD,
    "/paper_tracks/aggressive/post_fix/reportable": R_REPORTABLE,
    "/paper_tracks/aggressive/post_fix/reportable_after": R_REPORTABLE,
    "/paper_tracks/aggressive/reportable": R_REPORTABLE,
    "/paper_tracks/aggressive/reportable_after": R_REPORTABLE,
    "/paper_tracks/balanced/post_fix/reportable": R_REPORTABLE,
    "/paper_tracks/balanced/post_fix/reportable_after": R_REPORTABLE,
    "/paper_tracks/balanced/reportable": R_REPORTABLE,
    "/paper_tracks/balanced/reportable_after": R_REPORTABLE,
    "/track_end_date": R_UNREAD,
    "/track_period": R_PERIOD,
    "/track_period/annualised_approval_required": R_PERIOD,
    "/track_period/annualised_equivalent_pct": R_PERIOD,
    "/track_period/annualised_formula": R_PERIOD,
    "/track_period/continuity_repaired": R_PERIOD,
    "/track_period/costs_basis": R_PERIOD,
    "/track_period/costs_paid_usd": R_PERIOD,
    "/track_period/flows": R_PERIOD,
    "/track_period/flows/basis": R_PERIOD,
    "/track_period/flows/count": R_PERIOD,
    "/track_period/flows/items": R_PERIOD,
    "/track_period/flows/state": R_PERIOD,
    "/track_period/flows/unchecked_bars": R_PERIOD,
    "/track_period/gaps": R_PERIOD,
    "/track_period/gaps/missing_dates": R_PERIOD,
    "/track_period/gaps/nav_continuous_across_missing": R_PERIOD,
    "/track_period/gaps/zero_yield_dates": R_PERIOD,
    "/track_period/method": R_PERIOD,
    "/track_period/mwr_pct": R_PERIOD,
    "/track_period/nav_end": R_PERIOD,
    "/track_period/nav_start": R_PERIOD,
    "/track_period/nav_start_basis": R_PERIOD,
    "/track_period/period": R_PERIOD,
    "/track_period/period/accrual_bars": R_PERIOD,
    "/track_period/period/convention": R_PERIOD,
    "/track_period/period/days_act": R_PERIOD,
    "/track_period/period/end_date": R_PERIOD,
    "/track_period/period/end_ts": R_PERIOD,
    "/track_period/period/evidenced_bars": R_PERIOD,
    "/track_period/period/start_date": R_PERIOD,
    "/track_period/period/start_ts": R_PERIOD,
    "/track_period/period/start_ts_reason": R_PERIOD,
    "/track_period/period_return_pct": R_PERIOD,
    "/track_period/provenance": R_PERIOD,
    "/track_period/provenance/cycle_unlabelled": R_PERIOD,
    "/track_period/provenance/fallback_rate": R_PERIOD,
    "/track_period/provenance/live_rates": R_PERIOD,
    "/track_period/provenance/restored_from_cycle_log": R_PERIOD,
    "/track_period/state": R_PERIOD,
    "/track_period/twr_pct": R_PERIOD,
    "/track_return_pct": R_UNREAD,
}

# The ADR-531 boundary record grows sub-fields once a book has corrected-model rows — the same audit
# provenance as its parent, never printed by a page.
for _b in ("balanced", "aggressive"):
    for _f in ("adr", "defect", "defect_found_at", "first_v2_date", "v1_classification", "v1_last_date",
               "v1_model", "v1_rows", "v2_activated_at", "v2_model"):
        NOT_IN_VIEW[f"/paper_tracks/{_b}/economics_model_boundary/{_f}"] = R_MODEL

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

    def test_the_measured_exclusions_are_still_unread(self):
        """Причина «не читает никто» ПЕРЕМЕРЯЕТСЯ, а не хранится как обещание (ADR-1117).

        Шестьдесят один путь объявлен не словами, а замером спроса. Замер устаревает в
        один коммит: стóит странице начать читать поле, которого переходник не несёт, —
        и она напечатает «undefined» молча, а строка исключения будет этому прикрытием.
        Поэтому строка живёт, пока прибор её подтверждает.

        Третий исход (инв. #17): прибор не ввезён или замер не состоялся ⇒ НЕ ИЗМЕРЕНО с
        названной причиной, а не молчаливый зелёный.
        """
        try:
            demand = _demand_tool()
        except NotMeasured as exc:
            self.fail(f"НЕ ИЗМЕРЕНО — {exc}")
        try:
            # Форму переходника здесь снимать НЕ надо: её уже снял setUp, и второй зов
            # `node` удвоил бы цену теста, отвечая на тот же вопрос.
            unread = demand.not_read_paths(ROOT, want_view_shape=False)
        except demand.NotMeasured as exc:
            self.fail(f"НЕ ИЗМЕРЕНО — замер спроса не состоялся: {exc}")
        claimed = sorted(p for p, why in NOT_IN_VIEW.items()
                         if "snapshot_view_field_demand" in str(why))
        self.assertTrue(claimed, "ни одна строка исключений не ссылается на замер спроса — "
                                 "проверка перестала отвечать на свой вопрос")
        broken = sorted(p for p in claimed if p not in unread)
        self.assertEqual(broken, [], (
            f"причина исключения БОЛЬШЕ НЕ ВЕРНА — поле читают, а переходник его не несёт: "
            f"{broken}. Либо добавить поле в переходник, либо перемерить причину прибором "
            f"`scripts/snapshot_view_field_demand.py`; снимать строку «чтобы стало зелено» "
            f"запрещено (инв. #16)."))


def _demand_tool():
    """Ввезти прибор замера спроса из ТОГО ЖЕ дерева; нет его — третий исход."""
    tool = ROOT / "scripts" / "snapshot_view_field_demand.py"
    if not tool.is_file():
        raise NotMeasured(f"прибора замера спроса нет в дереве: {tool}")
    spec = importlib.util.spec_from_file_location("snapshot_view_field_demand", tool)
    if spec is None or spec.loader is None:
        raise NotMeasured(f"прибор не ввозится: {tool}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "not_read_paths"):
        raise NotMeasured("у прибора нет двери `not_read_paths` — спрос спрашивать нечем")
    return mod


if __name__ == "__main__":
    unittest.main()
