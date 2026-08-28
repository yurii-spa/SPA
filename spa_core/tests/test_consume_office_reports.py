"""Шаг 0-офис обязан печатать ТО, ЧТО В ФАЙЛАХ (ADR-066, Фаза 2).

`scripts/consume_office_reports.py` — обязательный вход протокола оркестратора:
он кладёт продукты инвест-офиса и отчёты сторожей в контекст сессии. Если ветка
выжимки читает поля, которых производитель не пишет, шаг честно отвечает на свой
вопрос («что лежит в полях, которые я читаю») и молчит утвердительно о нужном
(«что лежит в файле»). Это fail-OPEN, и в ЭТОМ файле он рецидивировал трижды:

  * `findings_bridge` — читала несуществующий файл и `counts.opened/pending`;
  * `house_view_gap` — читала `overall`/`counts.critical`/`findings`, а
    производитель пишет `gaps`/`counts.warn|info|unchecked`: обязательный шаг
    печатал «вердикт: None» при ДВУХ реальных расхождениях (замер цикла #176,
    воспроизведён обязательным прогоном того же цикла);
  * `_health` — читала `stale`/`failing`/`unknown` на верхнем уровне, где их
    нет: протухший аналитик не был бы назван вовсе.

Каждый тест ниже — положительный контроль: он краснеет на неисправленном файле
и воспроизводит настоящую аварию, а не воображаемую. Артефакты в фикстурах —
СНИМКИ ПРОДА (`data/house_view_gap.json`, `data/investment_os/_health.json` на
2026-08-09), а не выдуманная схема: тест, написанный по той же памяти, что и
дефект, повторил бы дефект.
"""
# FROZEN-DATE-OK: injected-clock — часы инъектируются (`now=NOW`) вместе с
# фиксированными отметками, взятыми из тех же снимков прода: обе стороны
# закреплены, тест бессмертен к календарю (преференция #1 в
# `.claude/rules/deployment.md`), и число возраста можно проверять точно.
from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
import os
import contextlib
from pathlib import Path

import pytest

from spa_core.tests._freshness import at

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "consume_office_reports.py"


def _load():
    spec = importlib.util.spec_from_file_location("_consume_office_reports", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _load()

# Инъектируемые часы: якорь и все отметки ниже взяты из одного снимка прода.
NOW = at("2026-08-09T05:44:00+00:00")

# ── снимки прода (verbatim, сокращены по длине списков) ──────────────────────

# data/house_view_gap.json, 2026-08-09T01:02:56Z — ДВА реальных расхождения.
HOUSE_VIEW_GAP_REAL = {
    "generated_at": "2026-08-09T01:02:56.583791+00:00",
    "adr": "ADR-066",
    "gaps": [
        {"key": "gap:opportunity_no_adapter:aerodrome_usdc_lp",
         "type": "opportunity_unheld", "severity": "INFO",
         "message": "возможность aerodrome_usdc_lp 8.5% (evidence L3) вне реестра адаптеров "
                    "— входа технически нет (адаптер + промоушен)",
         "protocol": "aerodrome_usdc_lp", "apy_pct": 8.5, "evidence_level": "L3"},
        {"key": "gap:opportunity_no_adapter:pendle-pt",
         "type": "opportunity_unheld", "severity": "INFO",
         "message": "возможность pendle-pt 8.0% (evidence L3) вне реестра адаптеров "
                    "— входа технически нет (адаптер + промоушен)",
         "protocol": "pendle-pt", "apy_pct": 8.0, "evidence_level": "L3"},
    ],
    "unchecked": [],
    "counts": {"warn": 0, "info": 2, "unchecked": 0},
}

# data/investment_os/_health.json, 2026-08-08T19:00:07Z (список аналитиков урезан).
HEALTH_REAL = {
    "model": "investment_os_health", "is_advisory": True,
    "generated_at": "2026-08-08T19:00:07.228317+00:00",
    "overall": "HEALTHY",
    "counts": {"total": 11, "healthy": 11, "stale": 0, "missing": 0,
               "unknown_or_corrupt": 0},
    "analysts": [
        {"agent": "stablecoin_yield", "present": True, "fresh": True,
         "status": "ok", "age_s": 69420},
        {"agent": "market_regime", "present": True, "fresh": True,
         "status": "ok", "age_s": 69240},
    ],
}

# data/investment_os/chief_investment.json, 2026-08-08T09:11:47Z — 19.4 ч на момент
# замера: артефакт, который ехал в контекст БЕЗ единого признака возраста.
CHIEF_REAL = {
    "agent": "chief_investment", "status": "ok", "is_advisory": True,
    "generated_at": "2026-08-08T09:11:47.733075+00:00",
    "house_view": {
        "overall_posture": "YELLOW",
        "conflicts": ["regime=YELLOW vs threat=NO_THREAT_OBSERVED diverge — "
                      "surfaced, not averaged"],
        "top_opportunities": [
            {"evidence_level": "L3",
             "value": {"protocol": "aerodrome_usdc_lp", "apy_pct": 8.5}},
        ],
    },
}


def _text(lines) -> str:
    return "\n".join(lines)


# ── 1. house_view_gap: расхождения ВИДНЫ, `None` не печатается ───────────────

def test_house_view_gap_prints_the_real_gaps_not_none() -> None:
    """Авария #176 дословно: два реальных расхождения печатались как «None».

    Мутация «вернуть чтение `findings`» обязана красить этот тест: у настоящего
    артефакта поля `findings` нет вовсе, и цикл по нему даёт пустой вывод.
    """
    out = _text(MOD._summarize_json("data/house_view_gap.json",
                                    HOUSE_VIEW_GAP_REAL, now=NOW))
    assert "aerodrome_usdc_lp" in out, out
    assert "pendle-pt" in out, out
    assert "расхождений house_view↔факт: 2" in out, out
    assert "None" not in out, (
        "«None» в выводе читается глазом как «пусто, всё в порядке» — "
        "это ровно тот fail-OPEN, который чинили:\n" + out)


def test_house_view_gap_counts_come_from_the_real_keys() -> None:
    """Счётчики производителя — warn/info/unchecked, а не critical/warn/aged."""
    out = _text(MOD._summarize_json("data/house_view_gap.json",
                                    HOUSE_VIEW_GAP_REAL, now=NOW))
    assert "warn=0" in out and "info=2" in out and "unchecked=0" in out, out


def test_missing_counter_is_named_unmeasured_never_none() -> None:
    """Отсутствующий счётчик — НЕ ноль и не `None`, а «НЕ ИЗМЕРЕНО» (fail-CLOSED)."""
    broken = dict(HOUSE_VIEW_GAP_REAL, counts={"warn": 0})  # info/unchecked пропали
    out = _text(MOD._summarize_json("data/house_view_gap.json", broken, now=NOW))
    assert "info=НЕ ИЗМЕРЕНО" in out, out
    assert "unchecked=НЕ ИЗМЕРЕНО" in out, out
    assert "None" not in out, out


# ── 2. возраст — у КАЖДОГО артефакта ─────────────────────────────────────────

def test_chief_investment_carries_its_age() -> None:
    """house_view ехал в контекст без возраста; замер #176 — 19.4 ч.

    Часы и отметка закреплены обе, поэтому число проверяется точно.
    """
    out = _text(MOD._summarize_json("data/investment_os/chief_investment.json",
                                    CHIEF_REAL, now=NOW))
    assert "возраст 20.5ч" in out, out
    assert "старше суток" not in out, out
    assert "постура: YELLOW" in out, out


def test_age_marker_speaks_when_older_than_a_day() -> None:
    """Возраст должен ГОВОРИТЬ, а не только печататься: сутки — порог метки."""
    old = dict(CHIEF_REAL, generated_at="2026-08-07T05:00:00+00:00")
    out = _text(MOD._summarize_json("data/investment_os/chief_investment.json",
                                    old, now=NOW))
    assert "старше суток" in out, out


def test_missing_generated_at_is_named_not_silent() -> None:
    """Нет отметки времени ⇒ так и сказать; молчание тут неотличимо от свежести."""
    noden = {k: v for k, v in HOUSE_VIEW_GAP_REAL.items() if k != "generated_at"}
    out = _text(MOD._summarize_json("data/house_view_gap.json", noden, now=NOW))
    assert "возраст НЕ ИЗМЕРЕН" in out, out


def test_unparseable_generated_at_is_named_not_crashed() -> None:
    """Мусор в отметке — находка, а не исключение посреди обязательного шага."""
    bad = dict(HOUSE_VIEW_GAP_REAL, generated_at="вчера")
    out = _text(MOD._summarize_json("data/house_view_gap.json", bad, now=NOW))
    assert "возраст НЕ ИЗМЕРЕН" in out, out


# ── 3. _health: протухший аналитик обязан быть НАЗВАН ────────────────────────

def test_health_counters_come_from_counts_not_top_level() -> None:
    """Прежняя ветка читала stale/failing/unknown на верхнем уровне — их там нет."""
    out = _text(MOD._summarize_json("data/investment_os/_health.json",
                                    HEALTH_REAL, now=NOW))
    assert "статус офиса: HEALTHY" in out, out
    assert "всего 11" in out and "здоровы 11" in out and "протухли 0" in out, out


def test_health_names_a_stale_analyst() -> None:
    """Настоящая авария: протухший аналитик не был назван шагом 0-офис ВООБЩЕ."""
    degraded = json.loads(json.dumps(HEALTH_REAL))
    degraded["overall"] = "STALE"
    degraded["counts"]["healthy"] = 10
    degraded["counts"]["stale"] = 1
    degraded["analysts"][1] = {"agent": "market_regime", "present": True,
                               "fresh": False, "status": "ok", "age_s": 999999}
    out = _text(MOD._summarize_json("data/investment_os/_health.json",
                                    degraded, now=NOW))
    assert "market_regime" in out, out
    assert "протухли 1" in out, out


# ── 4. сторож сторожа: расхождение схемы измеряется, а не выглядывается ──────

def test_schema_drift_is_measured_and_spoken(tmp_path) -> None:
    """Класс проверяется не веткой, а ФАЙЛОМ: ушло поле — сказано вслух.

    Именно этого не было три раза подряд: производитель уезжал, ветка молча
    печатала пустоту, и находили это глазами месяцы спустя.

    ИЗМЕНЁН НАМЕРЕННО, цикл #248 (инв. #16; обоснование здесь и в журнале W33):
    утверждения оставлены ДОСЛОВНО, изменён только СЦЕНАРИЙ — производитель
    теперь настоящий участник проверки и объявлен явно. Раньше сценарий был
    двусмысленным: у фикстуры отметка 2026-08-09, а сравнивать её было не с чем,
    поэтому «поля нет в снимке» и «производитель уехал» были одним и тем же
    выводом. Теперь обе стороны — вход теста (файл производителя + его время
    правки), тест бессмертен к календарю, а проверяет он ровно то, ради чего
    заведён: производитель `gaps` не пишет ⇒ сказано вслух.
    """
    src = _tree_with_producer(tmp_path, 'REPORT = {"counts": {"warn": 0}}\n',
                              rel="spa_core/monitoring/house_view_gap.py")
    _stamp(src, "2026-08-09T00:00:00+00:00")
    drifted = {k: v for k, v in HOUSE_VIEW_GAP_REAL.items() if k != "gaps"}
    out = _text(MOD._summarize_json("data/house_view_gap.json", drifted,
                                    now=NOW, root=str(tmp_path)))
    assert "СХЕМА РАЗОШЛАСЬ" in out, out
    assert "gaps" in out, out


def test_schema_drift_sees_nested_fields(tmp_path) -> None:
    """У house_view всё интересное на втором уровне — проверка верхнего слепа.

    ИЗМЕНЁН НАМЕРЕННО, цикл #248 — по той же причине и тем же способом, что и
    тест выше. Проверяемое свойство усилено, а не ослаблено: производитель
    ПИШЕТ `house_view` и `overall_posture` и не пишет `top_opportunities`, то
    есть проверка обязана дойти до ВТОРОГО уровня, чтобы вообще что-то найти —
    ровно тот дрейф (#176), ради которого вложенные пути и заведены.
    """
    src = _tree_with_producer(
        tmp_path,
        'REPORT = {"house_view": {"overall_posture": "GREEN", "conflicts": []}}\n',
        rel="spa_core/investment_os/agents/chief_investment.py")
    _stamp(src, "2026-08-08T00:00:00+00:00")
    drifted = json.loads(json.dumps(CHIEF_REAL))
    del drifted["house_view"]["top_opportunities"]
    out = _text(MOD._summarize_json("data/investment_os/chief_investment.json",
                                    drifted, now=NOW, root=str(tmp_path)))
    assert "СХЕМА РАЗОШЛАСЬ" in out, out
    assert "house_view.top_opportunities" in out, out


def test_no_schema_drift_on_the_real_artifacts() -> None:
    """На НАСТОЯЩИХ снимках прода тревоги быть не должно — иначе это волк."""
    for rel, doc in (("data/house_view_gap.json", HOUSE_VIEW_GAP_REAL),
                     ("data/investment_os/_health.json", HEALTH_REAL),
                     ("data/investment_os/chief_investment.json", CHIEF_REAL)):
        out = _text(MOD._summarize_json(rel, doc, now=NOW))
        assert "СХЕМА РАЗОШЛАСЬ" not in out, f"{rel}:\n{out}"


@pytest.mark.parametrize("name", sorted(MOD._READ_SCHEMA))
def test_declared_schema_matches_the_live_producer(name: str) -> None:
    """Объявленная схема сверяется с ИСХОДНИКОМ производителя — как и обещает имя.

    ИЗМЕНЁН НАМЕРЕННО, цикл #248 (инвариант #16, обоснование здесь и в журнале
    W33). Тест назывался «matches_the_live_producer», а сверялся с ЖИВЫМ
    АРТЕФАКТОМ на диске — это разные утверждения, и разошлись они не в теории:
    15.08 в прод-дереве он краснел на ПОЛНОСТЬЮ здоровом контуре, потому что
    `owner_answer_delivery` приехал с ADR-086 в 16:0xZ, а отчёт моста на диске
    был произведён в 13:03Z — кодом, который ключа ещё не знал. Артефакт,
    произведённый до доставки ключа, не может его содержать.

    Проверка при этом СТАЛА СИЛЬНЕЕ, а не слабее, и это главное:
      * раньше на CI (Linux) тест не выполнялся ВООБЩЕ — `data/` вне git, файла
        нет, всякий раз `skip`; настоящее расхождение производителя ловилось бы
        только на Маке и только через протухший артефакт;
      * теперь исходник производителя есть в любом дереве, и расхождение
        «потребитель читает ключ, которого производитель не пишет» краснеет
        в CI сразу, до всякого артефакта;
      * живой артефакт из проверки НЕ выброшен — он остаётся доказательством,
        но только когда произведён ПОЗЖЕ кода производителя (иначе он говорит
        о прошлом, а не о схеме).
    Ни одно утверждение не ослаблено: «выжимка читает поле, которого нет у
    производителя» по-прежнему красит тест.
    """
    rel = MOD._PRODUCER.get(name)
    assert rel, (f"у {name} не объявлен производитель в _PRODUCER — отличить "
                 f"«отчёт старого образца» от расхождения схемы будет нечем")
    src = _REPO / rel
    assert src.is_file(), f"объявленный производитель {rel} не найден в дереве"
    keys = MOD._source_keys(str(src))
    assert keys is not None, f"исходник производителя {rel} не разобран"
    missing = [p for p in MOD._READ_SCHEMA[name]
               if p.split(".")[-1] not in keys]
    assert not missing, (
        f"выжимка шага 0-офис читает поля, которых производитель {rel} не "
        f"пишет: {missing} — ветка мертва, как уже бывало трижды")

    # Живой артефакт — доказательство, но только если он НОВЕЕ кода.
    data_dir = _REPO / "data"
    live = next((p for p in sorted(data_dir.rglob(name)) if p.is_file()), None) \
        if data_dir.is_dir() else None
    if live is None:
        return
    try:
        doc = json.loads(live.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"{live} не разобран как JSON ({e}) — не предмет этого теста")
    art_ts = MOD._parse_ts(doc.get("generated_at"))
    prod_mtime = dt.datetime.fromtimestamp(src.stat().st_mtime, dt.timezone.utc)
    if art_ts is None or art_ts < prod_mtime:
        return  # отчёт старого образца — он о прошлом, а не о схеме
    absent = [p for p in MOD._READ_SCHEMA[name] if not MOD._has_path(doc, p)]
    assert not absent, (
        f"{live} произведён ПОЗЖЕ кода производителя ({art_ts} > {prod_mtime}), "
        f"а полей {absent} в нём нет — производитель их не написал")


# ── 4b. отчёт СТАРОГО ОБРАЗЦА ≠ расхождение схемы (авария 15.08, цикл #248) ──
#
# Каждый тест ниже воспроизводит живой замер обязательного шага 0-офис
# 2026-08-15 17:0xZ: `owner_answer_delivery` приехал в 16:0xZ вместе с ADR-086,
# отчёт моста на диске — от 13:03Z, и шаг напечатал «СХЕМА РАЗОШЛАСЬ …
# читаем НЕ ТОТ файл. Это находка (карточка)» о здоровом контуре.

_BRIDGE_KEYS = ("created", "closed", "deferred", "waiting_hysteresis",
                "escalated", "sources_unread", "open_cards", "delivery")

# Снимок прода data/findings_bridge_report.json, 2026-08-15T13:03:30Z: все
# ключи ДО ADR-086 на месте, `owner_answer_delivery` нет — его не мог написать
# код, которого в тот момент не существовало.
BRIDGE_OLD_SAMPLE = dict({k: 0 for k in _BRIDGE_KEYS},
                         generated_at="2026-08-15T13:03:30.164070+00:00",
                         delivery={"status": "IDLE"})


def _tree_with_producer(root: Path, body: str, *, rel: str) -> Path:
    src = root / rel
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(body, encoding="utf-8")
    return src


def _stamp(path: Path, iso: str) -> None:
    """Время правки исходника — ВХОД проверки, поэтому задаётся явно."""
    ts = at(iso).timestamp()
    os.utime(path, (ts, ts))


def test_old_sample_report_is_not_called_schema_drift(tmp_path) -> None:
    """Авария 15.08 дословно: отчёт 13:03Z + код 16:0xZ = НЕ находка.

    Краснеет на неисправленном файле: там любое отсутствующее поле печаталось
    как «СХЕМА РАЗОШЛАСЬ … Это находка (карточка)», и следующая сессия честно
    заводила карточку на исправное состояние.
    """
    src = _tree_with_producer(
        tmp_path, 'REPORT = {"owner_answer_delivery": {}}\n',
        rel="spa_core/monitoring/findings_bridge.py")
    _stamp(src, "2026-08-15T16:06:00+00:00")

    out = _text(MOD._schema_drift("findings_bridge_report.json",
                                  BRIDGE_OLD_SAMPLE, root=str(tmp_path)))
    assert "СХЕМА РАЗОШЛАСЬ" not in out, out
    assert "СТАРОГО ОБРАЗЦА" in out, out
    assert "owner_answer_delivery" in out, out
    # Обе стороны сравнения названы в самой строке (#222).
    assert "13:03" in out and "16:06" in out, out


def test_producer_without_the_key_is_still_a_finding(tmp_path) -> None:
    """Обратный контроль: производитель ключа не пишет ⇒ находка, как и была."""
    src = _tree_with_producer(
        tmp_path, 'REPORT = {"created": 0}\n',
        rel="spa_core/monitoring/findings_bridge.py")
    _stamp(src, "2026-08-15T16:06:00+00:00")

    out = _text(MOD._schema_drift("findings_bridge_report.json",
                                  BRIDGE_OLD_SAMPLE, root=str(tmp_path)))
    assert "СХЕМА РАЗОШЛАСЬ" in out, out
    assert "owner_answer_delivery" in out, out


def test_report_newer_than_the_code_is_a_finding(tmp_path) -> None:
    """Новый случай, которого раньше не было ВОВСЕ: код умеет, отчёт молчит.

    До #248 он не отличался от «старого образца» ничем — оба выглядели как
    отсутствие поля, и оба печатались одинаково.
    """
    src = _tree_with_producer(
        tmp_path, 'REPORT = {"owner_answer_delivery": {}}\n',
        rel="spa_core/monitoring/findings_bridge.py")
    _stamp(src, "2026-08-15T10:00:00+00:00")          # код СТАРШЕ отчёта

    out = _text(MOD._schema_drift("findings_bridge_report.json",
                                  BRIDGE_OLD_SAMPLE, root=str(tmp_path)))
    assert "СХЕМА РАЗОШЛАСЬ" in out, out
    assert "СТАРОГО ОБРАЗЦА" not in out, out


def test_key_only_described_never_written_does_not_count(tmp_path) -> None:
    """Капкан #227: описание ключа — не его запись.

    ИЗМЕРЕНО, а не предположено (мутация M1): фразу «Пишет блок
    owner_answer_delivery …» в докстринге проверка не зачла бы и БЕЗ отдельного
    исключения — литералы сверяются ЦЕЛИКОМ, а не подстрокой, и предложение
    ключом не является. Поэтому тест бьёт в единственную щель, которая
    исключение и оправдывает: голая строка-выражение, равная ключу ДОСЛОВНО.
    Такой «производитель» ничего не пишет, а сканер без исключения зачёл бы его
    — и находка погасла бы текстом, ровно как в #227.
    """
    src = _tree_with_producer(
        tmp_path,
        '"""owner_answer_delivery"""\n'
        'REPORT = {"created": 0}\n',
        rel="spa_core/monitoring/findings_bridge.py")
    _stamp(src, "2026-08-15T16:06:00+00:00")

    out = _text(MOD._schema_drift("findings_bridge_report.json",
                                  BRIDGE_OLD_SAMPLE, root=str(tmp_path)))
    assert "СХЕМА РАЗОШЛАСЬ" in out, out


def test_prose_mention_of_the_key_is_not_a_write_either(tmp_path) -> None:
    """Вторая сторона того же: литерал сверяется целиком, не подстрокой."""
    src = _tree_with_producer(
        tmp_path,
        'HELP = "мост пишет блок owner_answer_delivery в отчёт"\n'
        'REPORT = {"created": 0}\n',
        rel="spa_core/monitoring/findings_bridge.py")
    _stamp(src, "2026-08-15T16:06:00+00:00")

    out = _text(MOD._schema_drift("findings_bridge_report.json",
                                  BRIDGE_OLD_SAMPLE, root=str(tmp_path)))
    assert "СХЕМА РАЗОШЛАСЬ" in out, out


def test_missing_producer_file_is_unmeasured_not_silence(tmp_path) -> None:
    """Производителя нет на диске ⇒ громкое «НЕ ИЗМЕРЕНО», не тишина."""
    out = _text(MOD._schema_drift("findings_bridge_report.json",
                                  BRIDGE_OLD_SAMPLE, root=str(tmp_path)))
    assert MOD._UNMEASURED in out, out
    assert "owner_answer_delivery" in out, out


def test_unparsable_producer_is_unmeasured(tmp_path) -> None:
    """Исходник не разобрался ⇒ «не измерено», а не «в порядке» (fail-CLOSED)."""
    src = _tree_with_producer(tmp_path, "def (((\n",
                              rel="spa_core/monitoring/findings_bridge.py")
    _stamp(src, "2026-08-15T16:06:00+00:00")
    out = _text(MOD._schema_drift("findings_bridge_report.json",
                                  BRIDGE_OLD_SAMPLE, root=str(tmp_path)))
    assert MOD._UNMEASURED in out, out
    assert "не разобран" in out, out


def test_report_without_generated_at_is_unmeasured(tmp_path) -> None:
    """Нечем сравнить возраст ⇒ «не измерено»: угадывать в пользу тишины нельзя."""
    src = _tree_with_producer(
        tmp_path, 'REPORT = {"owner_answer_delivery": {}}\n',
        rel="spa_core/monitoring/findings_bridge.py")
    _stamp(src, "2026-08-15T16:06:00+00:00")
    doc = {k: 0 for k in _BRIDGE_KEYS}                # без generated_at
    doc["delivery"] = {}
    out = _text(MOD._schema_drift("findings_bridge_report.json", doc,
                                  root=str(tmp_path)))
    assert MOD._UNMEASURED in out, out


def test_undeclared_producer_keeps_the_loud_answer(monkeypatch, tmp_path) -> None:
    """Артефакт без объявленного производителя не становится тихим.

    Молчание здесь было бы худшим исходом правки #248: новый артефакт в
    `_READ_SCHEMA` без строки в `_PRODUCER` перестал бы проверяться вовсе.
    """
    monkeypatch.setitem(MOD._READ_SCHEMA, "brand_new.json", ("must_be_here",))
    out = _text(MOD._schema_drift("brand_new.json",
                                  {"generated_at": "2026-08-15T13:03:30+00:00"},
                                  root=str(tmp_path)))
    assert MOD._UNMEASURED in out, out
    assert "не объявлен" in out, out


def test_every_declared_reader_has_a_declared_producer() -> None:
    """Храповик: у каждой строки `_READ_SCHEMA` есть производитель в `_PRODUCER`."""
    orphan = sorted(set(MOD._READ_SCHEMA) - set(MOD._PRODUCER))
    assert not orphan, (
        f"артефакты без объявленного производителя: {orphan} — «отчёт старого "
        f"образца» будет неотличим от расхождения схемы")


# ── 5. проводка целиком: не деталь, а весь обязательный шаг ──────────────────

def test_main_end_to_end_prints_ages_and_real_gaps(tmp_path) -> None:
    """Мутировать проводку, а не только детали: гоняем main() над манифестом.

    Проверка ветки в отрыве уже была зелёной при мёртвой проводке (урок #144),
    поэтому обязательный шаг проверяется тем же путём, каким его зовёт протокол.
    """
    root = tmp_path
    (root / "architecture").mkdir()
    (root / "data" / "investment_os").mkdir(parents=True)
    (root / "architecture" / "manifest.json").write_text(json.dumps({"artifacts": [
        {"path": "data/house_view_gap.json", "status": "active",
         "consumers": ["orchestrator_protocol"]},
        {"path": "data/investment_os/chief_investment.json", "status": "active",
         "consumers": ["orchestrator_protocol"]},
        {"path": "data/investment_os/_health.json", "status": "active",
         "consumers": ["orchestrator_protocol"]},
    ]}), encoding="utf-8")
    (root / "data" / "house_view_gap.json").write_text(
        json.dumps(HOUSE_VIEW_GAP_REAL), encoding="utf-8")
    (root / "data" / "investment_os" / "chief_investment.json").write_text(
        json.dumps(CHIEF_REAL), encoding="utf-8")
    (root / "data" / "investment_os" / "_health.json").write_text(
        json.dumps(HEALTH_REAL), encoding="utf-8")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = MOD.main(["--root", str(root), "--no-receipts"], now=NOW)
    out = buf.getvalue()

    assert rc == 0, out
    assert "прочитано 3, не прочитано 0" in out, out
    assert "aerodrome_usdc_lp" in out, out          # расхождения видны
    assert out.count("возраст ") >= 3, out          # возраст у КАЖДОГО
    assert "None" not in out, out                   # ни одного молчаливого None


def test_main_still_names_a_missing_file(tmp_path) -> None:
    """Fail-CLOSED осталась fail-CLOSED: файла нет ⇒ «НЕ ПРОЧИТАН», не тишина.

    ИЗМЕНЁН ОСОЗНАННО в цикле #236 (инв. #16: обоснование здесь + запись в
    `docs/journal/2026-W33.md`). Прежняя редакция держала в манифесте РОВНО ОДИН
    артефакт под `data/` и не создавала его. После правки «двадцать ложных
    находок из worktree» этот вход попадает в ветку «в дереве нет НИ ОДНОГО
    артефакта офиса» и честно отвечает «офис НЕ ИЗМЕРЕН» (rc 3) — потому что
    единственный отсутствующий артефакт неотличим от запуска не из того дерева.

    Проверяемое НАМЕРЕНИЕ («настоящая пропажа названа, а не проглочена») не
    ослаблено, а усилено: теперь у пропавшего артефакта есть присутствующий
    сосед, то есть дерево ЗАВЕДОМО производящее — ровно тот случай, ради
    которого тест заведён, и в прежней редакции он как раз НЕ проверялся.
    Вырожденный вход («артефактов офиса нет вовсе») закреплён отдельно —
    `test_office_absent_wholesale_is_ONE_finding_not_twenty`, а обратный
    контроль — `test_missing_artifact_among_present_siblings_is_STILL_named`.
    Покрытие строго выросло: один вход был, стало три.
    """
    root = tmp_path
    (root / "architecture").mkdir()
    (root / "architecture" / "manifest.json").write_text(json.dumps({"artifacts": [
        {"path": "data/house_view_gap.json", "status": "active",
         "consumers": ["orchestrator_protocol"]},
        {"path": "data/investment_os/_health.json", "status": "active",
         "consumers": ["orchestrator_protocol"]},
    ]}), encoding="utf-8")
    # Сосед НА МЕСТЕ ⇒ дерево производящее, и пропажа второго — настоящая находка.
    (root / "data" / "investment_os").mkdir(parents=True)
    (root / "data" / "investment_os" / "_health.json").write_text(
        json.dumps(HEALTH_REAL), encoding="utf-8")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = MOD.main(["--root", str(root), "--no-receipts"], now=NOW)
    out = buf.getvalue()
    assert rc == 0, out
    assert "НЕ ПРОЧИТАН" in out, out
    assert "house_view_gap.json" in out, out
    assert "прочитано 1, не прочитано 1" in out, out


def test_old_positional_call_still_works() -> None:
    """Соседний тест (`test_card_delivery`) зовёт выжимку двумя аргументами."""
    out = _text(MOD._summarize_json("data/findings_bridge_report.json", {
        "generated_at": "2026-08-09T01:02:56.598582+00:00",
        "created": [], "closed": [], "deferred": [], "waiting_hysteresis": [],
        "escalated": [], "sources_unread": [], "open_cards": 0,
        "delivery": {"status": "IDLE", "delivered": []},
    }))
    assert "мост находка→карточка" in out, out
    assert "доставка карточек: IDLE" in out, out


def test_cards_already_on_origin_are_named_not_swallowed() -> None:
    """#268: «везти было нечего» и «всё уже там» — разные утверждения.

    17.08 доставка объявляла НЕПОГАСИМЫЙ долг о закрытии, которое на origin уже
    лежало (сойтись копии не могли: прод-дерево не синкает `nimbalyst-local/`).
    Долг чинится в самой доставке, но исход обязан быть СЛЫШЕН и здесь — иначе
    доказанное покрытие неотличимо от прогона, которому нечего было везти.
    """
    out = _text(MOD._summarize_json("data/findings_bridge_report.json", {
        "generated_at": "2026-08-17T01:03:50.692720+00:00",
        "created": [], "closed": [], "deferred": [], "waiting_hysteresis": [],
        "escalated": [], "sources_unread": [], "open_cards": 0,
        "delivery": {"status": "IDLE", "delivered": [], "covered_by_origin": [
            {"path": "nimbalyst-local/tracker/inbox-nahodka.md", "reason": "…"}]},
    }))
    assert "origin ушёл вперёд: 1" in out, out


def test_a_run_with_nothing_to_carry_gains_no_extra_words() -> None:
    """ОБРАТНЫЙ КОНТРОЛЬ: без покрытия строка остаётся прежней."""
    out = _text(MOD._summarize_json("data/findings_bridge_report.json", {
        "generated_at": "2026-08-17T01:03:50.692720+00:00",
        "created": [], "closed": [], "deferred": [], "waiting_hysteresis": [],
        "escalated": [], "sources_unread": [], "open_cards": 0,
        "delivery": {"status": "IDLE", "delivered": [], "covered_by_origin": []},
    }))
    assert "доставка карточек: IDLE (0 на origin)" in out, out
    assert "origin ушёл вперёд" not in out, out


# ── долг доставки виден там, где оркестратор обязан смотреть (ADR-081) ────────
#
# Авария 12.08: прогон 13:03Z оставил три карточки не на origin (`FAILED`,
# rc 4). Все три уже помечены `closed` в состоянии моста, поэтому следующий
# прогон 19:03Z вёз бы пустой список, `deliver([])` вернул бы `IDLE`, и ЭТОТ
# шаг напечатал бы зелёную строку «доставка карточек: IDLE (0 на origin)» —
# при трёх недоставленных. Статус про ОДИН прогон и долг про «чего нет на
# origin до сих пор» — разные вопросы, и схлопывание их в один и есть потеря.

def _bridge(delivery: dict, owner_answers: dict | None = None) -> str:
    # ИЗМЕНЕНО НАМЕРЕННО (цикл #247, ADR-086, инвариант #16 — обоснование здесь и
    # в `docs/journal/2026-W33.md`): производитель (`findings_bridge.run_bridge`)
    # получил ещё один БЕЗУСЛОВНЫЙ ключ `owner_answer_delivery`, и фикстура без
    # него — отчёт, которого не пишет никто. Приводится к форме ПРОИЗВОДИТЕЛЯ,
    # как уже делалось для блока `debt` в #204. Ни одно утверждение тестов ниже
    # не тронуто; отсутствие блока по-прежнему обязано быть СЛЫШНО, и это
    # проверяется отдельно (`test_owner_answer_delivery.py::OfficeStepReaderTest`),
    # то есть здешняя правка ничего не заглушает.
    return _text(MOD._summarize_json("data/findings_bridge_report.json", {
        "generated_at": "2026-08-12T19:03:13.159157+00:00",
        "created": [], "closed": [], "deferred": [], "waiting_hysteresis": [],
        "escalated": [], "sources_unread": [], "open_cards": 0,
        "delivery": delivery,
        "owner_answer_delivery": owner_answers if owner_answers is not None else {
            "status": "IDLE", "delivered": [], "already_on_origin": [],
            "pending": [], "conflicts": [], "unmeasured": []},
    }))


def test_idle_run_with_open_debt_is_not_a_green_line() -> None:
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ аварии: раньше здесь было только «IDLE (0 на origin)»."""
    out = _bridge({"status": "IDLE", "delivered": [], "attempted": [],
                   "debt": {"count": 3, "oldest_hours": 6.0, "stale": [],
                            "stale_after": 5, "dropped": [],
                            "paths": ["nimbalyst-local/tracker/inbox-nahodka-petli-"
                                      "data-investment-os-health.md"]}})
    assert "ДОЛГ ДОСТАВКИ: 3" in out, out
    assert "старшему 6.0ч" in out, out


def test_zero_debt_leaves_the_line_clean() -> None:
    """Контроль в обратную сторону: измеренный ноль не смеет краснить прогон."""
    out = _bridge({"status": "DELIVERED", "delivered": ["a"], "attempted": ["a"],
                   "debt": {"count": 0, "oldest_hours": None, "stale": [],
                            "stale_after": 5, "dropped": [], "paths": []}})
    assert "ДОЛГ ДОСТАВКИ" not in out, out
    assert "НЕ ИЗМЕРЕН" not in out, out


def test_receipt_without_debt_block_says_unmeasured_not_zero() -> None:
    """Квитанция старого образца — «НЕ ИЗМЕРЕН», а не молчаливое «долга нет»."""
    out = _bridge({"status": "IDLE", "delivered": [], "attempted": []})
    assert "долг доставки НЕ ИЗМЕРЕН" in out, out


def test_debt_that_repeats_forever_asks_for_a_human() -> None:
    """Повтор лечит сеть, но не отказ переноса: застрявшее обязано быть названо."""
    out = _bridge({"status": "DEBT", "delivered": [], "attempted": [],
                   "reason": "везти за прогон было нечего, но НЕ ДОСТАВЛЕНО 1",
                   "debt": {"count": 1, "oldest_hours": 72.0, "stale_after": 5,
                            "stale": ["nimbalyst-local/tracker/own-33.md"],
                            "dropped": [{"path": "nimbalyst-local/tracker/x.md",
                                         "reason": "снят с долга — файла нет на диске"}],
                            "paths": ["nimbalyst-local/tracker/own-33.md"]}})
    assert "не рассасывается повтором (≥5 попыток)" in out, out
    assert "own-33.md" in out, out
    assert "снято с долга" in out, out


# ── 6. «шаг 0-офис из worktree» — двадцать ложных находок вместо одной ────────
#
# Авария (цикл #207, воспроизведена циклом #236 первым же прогоном): запуск
# обязательного шага из git-worktree давал «прочитано 1, не прочитано 20» —
# двадцать строк «❌ НЕ ПРОЧИТАН · файла нет на диске» под подписью «красные
# строки выше = действовать (карточки), это не декорация». Инвест-офис при этом
# полностью здоров: артефакты пишет живой флот в ПРОД-дерево, они в
# `.gitignore`, и в worktree их нет ПО ПОСТРОЕНИЮ.
#
# Дороже всего здесь ФОРМА: вывод неотличим от настоящей находки и прямо требует
# действия, а протокол (шаг 0-офис) вторит — «строки „❌ НЕ ПРОЧИТАН“ тоже
# находка, не пропускать». Добросовестная сессия, работающая по §3.4 в
# изолированном worktree, заводит двадцать карточек о мёртвом офисе, которого
# нет. Класс — «инструмент подталкивает читателя к ложному выводу тем самым
# текстом, который написан против замалчивания».
#
# Причину карточка называла неточно («`data/` в .gitignore, его нет вовсе»);
# ИЗМЕРЕНО иначе: каталог `data/` в worktree ЕСТЬ (326 файлов, git-tracked), нет
# именно рантайм-артефактов офиса. Поэтому разделяющий признак — «ни один из
# целевых артефактов под data/ не существует», а не «нет каталога data/».

def _tree_with_manifest(root: Path, artifacts: list[str]) -> None:
    (root / "architecture").mkdir(parents=True, exist_ok=True)
    (root / "architecture" / "manifest.json").write_text(json.dumps({"artifacts": [
        {"path": p, "status": "active", "consumers": ["orchestrator_protocol"]}
        for p in artifacts
    ]}), encoding="utf-8")


def _run(argv, *, now=NOW):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = MOD.main(argv, now=now)
    return rc, buf.getvalue()


def test_office_absent_wholesale_is_ONE_finding_not_twenty(tmp_path) -> None:
    """Положительный контроль аварии #207: worktree без артефактов офиса.

    На НЕИСПРАВЛЕННОМ файле тест краснеет: там двадцать «НЕ ПРОЧИТАН» и rc 0.
    """
    root = tmp_path / "wt"
    twenty = [f"data/investment_os/a{i}.json" for i in range(20)]
    _tree_with_manifest(root, twenty)

    rc, out = _run(["--root", str(root), "--no-receipts"])

    assert rc == 3, out                     # НЕ 0: «всё хорошо» здесь запрещено
    assert "ОФИС НЕ ИЗМЕРЕН" in out, out
    assert out.count("НЕ ПРОЧИТАН") == 0, out
    # Ровно то, что делала бы добросовестная сессия по прежнему выводу:
    assert "заводить НЕЛЬЗЯ" in out, out
    assert "не измерен" in out, out


def test_missing_artifact_among_present_siblings_is_STILL_named(tmp_path) -> None:
    """Обратный контроль: настоящая пропажа НЕ проглочена новой веткой.

    Дерево производящее (соседи на месте) ⇒ отсутствие одного артефакта это
    находка по-прежнему. Тест зелёный и до правки — он и заведён затем, чтобы
    правка не купила тишину ценой слепоты (fail-OPEN был бы хуже исходного шума).
    """
    root = tmp_path / "prod"
    _tree_with_manifest(root, ["data/house_view_gap.json",
                               "data/investment_os/_health.json",
                               "data/investment_os/chief_investment.json"])
    (root / "data" / "investment_os").mkdir(parents=True)
    (root / "data" / "house_view_gap.json").write_text(
        json.dumps(HOUSE_VIEW_GAP_REAL), encoding="utf-8")
    (root / "data" / "investment_os" / "_health.json").write_text(
        json.dumps(HEALTH_REAL), encoding="utf-8")
    # chief_investment.json НЕ создан — настоящая пропажа у живого производителя.

    rc, out = _run(["--root", str(root), "--no-receipts"])

    assert rc == 0, out
    assert "ОФИС НЕ ИЗМЕРЕН" not in out, out
    assert "НЕ ПРОЧИТАН" in out, out
    assert "chief_investment.json" in out, out
    assert "прочитано 2, не прочитано 1" in out, out


def test_advice_never_fabricates_the_prod_path(tmp_path, monkeypatch) -> None:
    """Подсказка не смеет выдумывать путь к прод-дереву.

    Пойман своим же замером в цикле #236: первая редакция подставляла в совет
    `REPO_ROOT`, который вычисляется от расположения СКРИПТА, то есть из
    worktree указывает на сам worktree — выходило «гоняйте из прод-дерева
    (<этот же worktree>)». Совет, ведущий обратно в неисправное дерево, хуже
    отсутствия совета: он выглядит как разрешение проблемы.
    """
    root = tmp_path / "wt"
    _tree_with_manifest(root, ["data/investment_os/_health.json"])

    # git недоступен / это не репозиторий ⇒ главное дерево НЕ измерено
    monkeypatch.setattr(MOD, "_main_worktree", lambda _root: None)
    rc, out = _run(["--root", str(root), "--no-receipts"])
    assert rc == 3, out
    assert str(root) not in out.split("Что сделать:", 1)[1], out
    assert "НЕ измерено" in out, out

    # главное дерево измерено ⇒ называем ЕГО, а не то, откуда запущены
    monkeypatch.setattr(MOD, "_main_worktree", lambda _root: "/Users/o/SPA_Claude")
    rc, out = _run(["--root", str(root), "--no-receipts"])
    assert rc == 3, out
    advice = out.split("Что сделать:", 1)[1]
    assert "/Users/o/SPA_Claude" in advice, out
    assert str(root) not in advice, out


def test_data_dir_reads_the_foreign_tree_and_names_whose(tmp_path) -> None:
    """`--data-dir`: читать офис прод-дерева из worktree, НАЗЫВАЯ чей он.

    На неисправленном файле краснеет иначе — флага нет вовсе, argparse
    завершает процесс (SystemExit 2).
    """
    prod = tmp_path / "prod"
    _tree_with_manifest(prod, ["data/house_view_gap.json"])
    (prod / "data").mkdir(parents=True)
    (prod / "data" / "house_view_gap.json").write_text(
        json.dumps(HOUSE_VIEW_GAP_REAL), encoding="utf-8")

    wt = tmp_path / "wt"
    _tree_with_manifest(wt, ["data/house_view_gap.json"])   # артефактов НЕТ

    rc, out = _run(["--root", str(wt), "--no-receipts",
                    "--data-dir", str(prod / "data")])

    assert rc == 0, out
    assert "прочитано 1, не прочитано 0" in out, out
    assert "ИЗ ЧУЖОГО ДЕРЕВА" in out, out          # чьи артефакты — вслух
    assert str(prod / "data") in out, out
    assert "aerodrome_usdc_lp" in out, out          # содержимое реально прочитано


def test_data_dir_takes_the_briefing_from_the_SAME_tree(tmp_path) -> None:
    """Смешанная свежесть под одним итогом запрещена.

    Замер цикла #236 по первой редакции: из worktree с `--data-dir` выходило
    «прочитано 21, не прочитано 0», где 20 артефактов свежие (прод), а
    `docs/SYSTEM_BRIEFING.md` — git-копия возрастом 1047.7 ч. Одно слагаемое
    из одного дерева, другое из другого, итог общий — тот же дефект, что
    чинится, только тише.
    """
    prod = tmp_path / "prod"
    _tree_with_manifest(prod, ["data/house_view_gap.json", "docs/SYSTEM_BRIEFING.md"])
    (prod / "data").mkdir(parents=True)
    (prod / "data" / "house_view_gap.json").write_text(
        json.dumps(HOUSE_VIEW_GAP_REAL), encoding="utf-8")
    (prod / "docs").mkdir(parents=True)
    (prod / "docs" / "SYSTEM_BRIEFING.md").write_text(
        "# SPA System Briefing\n> Auto-updated: **2026-08-09 05:30 UTC**\nсвежий\n",
        encoding="utf-8")

    wt = tmp_path / "wt"
    _tree_with_manifest(wt, ["data/house_view_gap.json", "docs/SYSTEM_BRIEFING.md"])
    (wt / "docs").mkdir(parents=True)
    (wt / "docs" / "SYSTEM_BRIEFING.md").write_text(
        "# SPA System Briefing\n> Auto-updated: **2026-07-02 09:49 UTC**\nПРОТУХШАЯ КОПИЯ\n",
        encoding="utf-8")

    rc, out = _run(["--root", str(wt), "--no-receipts",
                    "--data-dir", str(prod / "data")])

    assert rc == 0, out
    assert "ПРОТУХШАЯ КОПИЯ" not in out, out
    assert "свежий" in out, out
    assert "возраст 0.2ч" in out, out               # 05:30 → 05:44 = 0.23ч


def test_data_dir_routes_receipts_to_the_foreign_tree(tmp_path) -> None:
    """Квитанция обязана лечь в дерево, чей офис прочитан.

    Квитанции отвечают на вопрос «офис ЧИТАЮТ?» (B3). Квитанция о прод-офисе,
    осевшая в одноразовом worktree, исчезнет вместе с ним — и сторож честно
    доложит «не читают» про прочитанное.
    """
    prod = tmp_path / "prod"
    _tree_with_manifest(prod, ["data/house_view_gap.json"])
    (prod / "data").mkdir(parents=True)
    (prod / "data" / "house_view_gap.json").write_text(
        json.dumps(HOUSE_VIEW_GAP_REAL), encoding="utf-8")

    wt = tmp_path / "wt"
    _tree_with_manifest(wt, ["data/house_view_gap.json"])

    rc, out = _run(["--root", str(wt), "--data-dir", str(prod / "data")])
    assert rc == 0, out

    from spa_core.monitoring.consumption_receipts import receipts_path

    in_prod = Path(receipts_path(str(prod)))
    in_wt = Path(receipts_path(str(wt)))
    assert in_prod.exists(), f"квитанция не легла в прод-дерево: {in_prod}\n{out}"
    assert "house_view_gap.json" in in_prod.read_text(encoding="utf-8")
    assert not in_wt.exists(), f"квитанция осела в одноразовом worktree: {in_wt}"


# ── 11. срок годности дом-вью: ПРОИСХОЖДЕНИЕ названо, когда оно не конституция ──
#
# Живой замер 22.08 (цикл #340). Шаг 0-офис печатал
#   `дом-вью (chief_investment): FRESH · возраст 12.4ч при сроке годности 30ч`
# про артефакт, которому конституция флота после решения владельца ADR-104 (21.08)
# объявила срок годности 1ч. Число 30ч было списано рукой 16.08 и связи с источником
# не имело. Число без источника нечем оспорить, поэтому источник теперь в строке —
# но ТОЛЬКО когда он не конституция: иначе шум в каждом цикле.

_HV_ROW = {"agent": "chief_investment", "status": "STALE", "fresh": False,
           "present": True, "age_s": 44640, "max_age_s": 3600}


def _health_with_house_view(**hv) -> dict:
    doc = json.loads(json.dumps(HEALTH_REAL))
    doc["house_view"] = dict(_HV_ROW, **hv)
    return doc


def test_house_view_budget_read_from_the_constitution_is_not_narrated() -> None:
    """Обратный контроль: замеренный срок — норма, о ней не говорят."""
    out = _text(MOD._summarize_json(
        "data/investment_os/_health.json",
        _health_with_house_view(budget_source="manifest_slo",
                                budget_why="architecture/manifest.json: slo_hours=1"),
        now=NOW))
    assert "дом-вью (chief_investment): STALE" in out, out
    assert "при сроке годности 1ч" in out, out
    assert "НЕ из конституции" not in out, out


def test_house_view_budget_fallen_back_to_a_literal_says_so() -> None:
    """Откат на литерал обязан быть СЛЫШЕН: иначе он неотличим от замера."""
    out = _text(MOD._summarize_json(
        "data/investment_os/_health.json",
        _health_with_house_view(status="FRESH", fresh=True, max_age_s=108000,
                                budget_source="fallback",
                                budget_why="manifest.json not read (FileNotFoundError)"),
        now=NOW))
    assert "срок НЕ из конституции" in out, out
    assert "fallback" in out, out
    assert "FileNotFoundError" in out, out


def test_old_health_report_without_the_source_still_prints() -> None:
    """Отчёт СТАРОГО образца (поля нет вовсе) не должен рвать шаг 0-офис."""
    out = _text(MOD._summarize_json("data/investment_os/_health.json",
                                    _health_with_house_view(), now=NOW))
    assert "дом-вью (chief_investment): STALE" in out, out
    assert "НЕ из конституции" not in out, out


# ── 6. loop_health: пульс петли ADR-066 доходил до сессии как «(пусто)» ──────
#
# Четвёртый рецидив ОДНОГО класса в этом файле (#170 findings_bridge · #176
# house_view_gap · #248 _health · и ветка loop_retro, заведённая со словами «до
# неё ретро печаталось как (пусто)»). Здесь он повторился на СИБЛИНГЕ того
# самого файла: `data/loop_health.json` пишет тот же контур ADR-066, объявлен в
# конституции с потребителем `orchestrator` (то есть читать его ОБЯЗАНЫ), но
# ветки у него не было — а generic-ветка ищет `status`/`overall`/`posture`/
# `reason`/`summary`, и loop_health не пишет НИ ОДНОГО из них.
#
# Снимок ниже — verbatim прод (`data/loop_health.json`, 2026-08-27T23:30:46Z),
# ровно те байты, о которых обязательный шаг цикла #407 напечатал «(пусто)» и
# засчитал их в «прочитано 22, не прочитано 0». Тест, написанный по памяти,
# повторил бы дефект.
LOOP_HEALTH_PROD = {
    "generated_at": "2026-08-27T23:30:46.133076+00:00",
    "adr": "ADR-066",
    "open_cards": 0,
    "latency_finding_to_card": {"median_h": 6.0, "max_h": 6.01, "n": 27},
    "latency_card_to_close": {"median_h": 12.02, "max_h": 66.01, "n": 22},
    "recurrences_total": 3,
    "cards_fate": {"new": 0, "in_progress": 0, "done_by_human": 1,
                   "auto_closed": 22, "unreadable": 4},
    "note": "",
}

# Часы инъектируются вместе с отметкой снимка — обе стороны закреплены.
NOW_LH = at("2026-08-28T03:30:00+00:00")


def _lh(**over) -> dict:
    doc = json.loads(json.dumps(LOOP_HEALTH_PROD))
    doc.update(over)
    return doc


def test_loop_health_prod_snapshot_is_no_longer_rendered_as_empty() -> None:
    """Положительный контроль: ТЕ ЖЕ байты, что дали «(пусто)» 28.08."""
    out = _text(MOD._summarize_json("data/loop_health.json", LOOP_HEALTH_PROD,
                                    now=NOW_LH))
    assert "(пусто)" not in out, out
    assert "петля ADR-066" in out, out


def test_loop_health_recurrences_reach_the_session_context() -> None:
    """Рецидив — СИСТЕМНАЯ причина по словам самого производителя.

    Три находки вернулись после закрытия, и обязательный шаг молчал об этом.
    """
    out = _text(MOD._summarize_json("data/loop_health.json", LOOP_HEALTH_PROD,
                                    now=NOW_LH))
    assert "🔴 РЕЦИДИВ: 3" in out, out


def test_loop_health_unreadable_cards_are_named_unmeasured_not_summed() -> None:
    """`unreadable` — ТРЕТИЙ исход: ни «взята», ни «лежит».

    Сложить его с любой из двух долей значит выдать неизмеренное за
    благополучие — ровно тот fail-OPEN, ради которого заведён весь файл.
    """
    out = _text(MOD._summarize_json("data/loop_health.json", LOOP_HEALTH_PROD,
                                    now=NOW_LH))
    assert "статус 4 карточк(и) моста НЕ ИЗМЕРЕНО" in out, out
    assert "не взято 0" in out, out


def test_loop_health_latency_tail_is_printed_not_just_the_median() -> None:
    """Максимум 66ч — это хвост, ради которого метрику и завели."""
    out = _text(MOD._summarize_json("data/loop_health.json", LOOP_HEALTH_PROD,
                                    now=NOW_LH))
    assert "латентность карточка→закрытие: медиана 12.02ч · максимум 66.01ч" in out, out
    assert "латентность находка→карточка: медиана 6.0ч · максимум 6.01ч" in out, out


def test_loop_health_producer_caveat_is_not_swallowed() -> None:
    """Оговорка «медианы по n<5 не интерпретировать» — часть показания.

    Без неё числа читаются увереннее, чем их написал автор.
    """
    out = _text(MOD._summarize_json(
        "data/loop_health.json",
        _lh(note="мало истории — медианы по n<5 не интерпретировать",
            latency_finding_to_card={"median_h": 6.0, "max_h": 6.0, "n": 2}),
        now=NOW_LH))
    assert "оговорка производителя: мало истории" in out, out


def test_loop_health_quiet_loop_is_not_narrated_as_alarm() -> None:
    """Обратный контроль: здоровая петля не должна печатать ни 🔴, ни НЕ ИЗМЕРЕНО."""
    out = _text(MOD._summarize_json(
        "data/loop_health.json",
        _lh(recurrences_total=0,
            cards_fate={"new": 0, "in_progress": 1, "done_by_human": 1,
                        "auto_closed": 3, "unreadable": 0}),
        now=NOW_LH))
    assert "(пусто)" not in out, out
    assert "🔴" not in out, out
    assert "НЕ ИЗМЕРЕНО" not in out, out
    assert "петля ADR-066" in out, out


def test_loop_health_old_report_without_cards_fate_says_unmeasured() -> None:
    """Отчёт СТАРОГО образца обязан читаться как «не измерено», а не как ноль."""
    doc = _lh()
    doc.pop("cards_fate")
    doc.pop("recurrences_total")
    out = _text(MOD._summarize_json("data/loop_health.json", doc, now=NOW_LH))
    assert "судьба карточек петли НЕ ИЗМЕРЕНО" in out, out
    assert "рецидивы НЕ ИЗМЕРЕНО" in out, out
    assert "(пусто)" not in out, out


def test_loop_health_empty_latency_says_nothing_to_measure() -> None:
    """n=0 — «измерять нечего», а не «мгновенно»: ноль ≠ отсутствие."""
    out = _text(MOD._summarize_json(
        "data/loop_health.json",
        _lh(latency_card_to_close={"median_h": None, "max_h": None, "n": 0}),
        now=NOW_LH))
    assert "латентность карточка→закрытие: измерять нечего (n=0)" in out, out
    assert "медиана None" not in out, out


# ── 7. «(пусто)» ЗАСЧИТЫВАЛОСЬ В «ПРОЧИТАНО» — и писало квитанцию ────────────
#
# Разбор находки цикла #408. Ветку `loop_health` (раздел 6) можно было чинить
# бесконечно по одному артефакту: класс жив, пока пустой разбор неотличим от
# успешного чтения. 28.08 обязательный шаг напечатал про `data/loop_health.json`
# «(пусто)», ЗАСЧИТАЛ его в «прочитано 22, не прочитано 0» и написал за него
# КВИТАНЦИЮ ПОТРЕБЛЕНИЯ — при том, что в артефакте лежали 3 рецидива и 4
# карточки со статусом «не измерено».
#
# Квитанция — не оформление: на ней стоит проверка B3 сторожа архитектуры
# («офис читают?»), и правило самого модуля квитанций сказано прямо — «ресит
# пишется ТОЛЬКО после фактического успешного чтения, иначе B3 превращается в
# театр». Пустой разбор эту норму нарушал: доказательством чтения становилось
# эхо собственного молчания. Отсюда ТРЕТИЙ исход — «прочитан вхолостую»: не
# «прочитан» и не «не прочитан», квитанции нет, в итоге отдельное число.
#
# Артефакт-образец ниже — сиблинг с формой, которой у шага нет ветки: ровно то
# положение, в котором `loop_health` прожил незамеченным (у него не было ни
# `status`, ни `overall`, ни `posture`, ни `reason`, ни `summary`).
UNKNOWN_SHAPE = {
    "generated_at": "2026-08-27T23:30:46.133076+00:00",
    "adr": "ADR-066",
    "open_cards": 0,
    "recurrences_total": 3,
    "cards_fate": {"new": 0, "unreadable": 4},
}


def _tree_with(root, artifacts: dict, *, extra_manifest=()) -> None:
    """Дерево из одного манифеста и его артефактов (пути относительные)."""
    (root / "architecture").mkdir(exist_ok=True)
    rows = [{"path": rel, "status": "active",
             "consumers": ["orchestrator_protocol"]} for rel in artifacts]
    rows.extend(extra_manifest)
    (root / "architecture" / "manifest.json").write_text(
        json.dumps({"artifacts": rows}), encoding="utf-8")
    for rel, doc in artifacts.items():
        full = root / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(json.dumps(doc), encoding="utf-8")


def test_unparseable_shape_is_named_hollow_not_empty() -> None:
    """«(пусто)» читается глазом как «в файле ничего нет». Это другое.

    Файл разобран НЕ БЫЛ — и обязан сказать об этом словами, а не пробелом.
    """
    out = _text(MOD._summarize_json("data/loop_pulse_v2.json", UNKNOWN_SHAPE,
                                    now=NOW_LH))
    assert "РАЗОБРАТЬ НЕЧЕМ" in out, out
    assert "(пусто)" not in out, out


def test_hollow_artifact_writes_no_consumption_receipt(tmp_path) -> None:
    """Главное утверждение: квитанция — это «я прочитал», и её быть не должно.

    Положительный контроль к аварии 28.08: на неисправленном шаге ЭТОТ ЖЕ вход
    даёт строку квитанции, то есть B3 получает доказательство чтения того, что
    прочитано не было.
    """
    _tree_with(tmp_path, {"data/loop_pulse_v2.json": UNKNOWN_SHAPE,
                          "data/investment_os/_health.json": HEALTH_REAL})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = MOD.main(["--root", str(tmp_path)], now=NOW)
    out = buf.getvalue()
    assert rc == 0, out

    receipts = tmp_path / "data" / "consumption_receipts.jsonl"
    written = [json.loads(ln) for ln in
               receipts.read_text(encoding="utf-8").splitlines() if ln.strip()]
    artifacts = {r["artifact"] for r in written}
    assert "data/investment_os/_health.json" in artifacts, written
    assert "data/loop_pulse_v2.json" not in artifacts, (
        "за разбор, из которого не прочитано ничего, написана квитанция — "
        "проверка B3 «офис читают?» кормится собственным эхом")


def test_hollow_is_counted_apart_from_read_and_unread(tmp_path) -> None:
    """Третий исход обязан быть ЧИСЛОМ в итоге, а не тоном строки выше."""
    _tree_with(tmp_path, {"data/loop_pulse_v2.json": UNKNOWN_SHAPE,
                          "data/investment_os/_health.json": HEALTH_REAL})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        MOD.main(["--root", str(tmp_path), "--no-receipts"], now=NOW)
    out = buf.getvalue()
    assert "ПРОЧИТАН ВХОЛОСТУЮ" in out, out
    assert "ВХОЛОСТУЮ 1" in out, out
    assert "прочитано 1" in out, out
    assert "прочитано 2" not in out, (
        "вхолостую сложено с прочитанным — итог снова утверждает больше, "
        f"чем измерено:\n{out}")


def test_healthy_tally_line_is_unchanged(tmp_path) -> None:
    """Обратный контроль: без вхолостую итог ДОСЛОВНО прежний.

    Новый счётчик не имеет права переписывать строку, которую сверяют соседние
    тесты, — иначе «починка» оплачивается ослаблением чужой проверки (инв. #16).
    """
    _tree_with(tmp_path, {"data/house_view_gap.json": HOUSE_VIEW_GAP_REAL,
                          "data/investment_os/_health.json": HEALTH_REAL})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        MOD.main(["--root", str(tmp_path), "--no-receipts"], now=NOW)
    out = buf.getvalue()
    assert "— итог: прочитано 2, не прочитано 0." in out, out
    assert "ВХОЛОСТУЮ" not in out, out


def test_missing_file_is_still_unread_not_hollow(tmp_path) -> None:
    """Два исхода не сливаются: «файла нет» ≠ «файл есть, разобрать нечем».

    Первое — авария производителя, второе — дыра в читателе. Одно число на оба
    стёрло бы адресата починки.
    """
    _tree_with(tmp_path, {"data/investment_os/_health.json": HEALTH_REAL},
               extra_manifest=[{"path": "data/house_view_gap.json",
                                "status": "active",
                                "consumers": ["orchestrator_protocol"]}])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        MOD.main(["--root", str(tmp_path), "--no-receipts"], now=NOW)
    out = buf.getvalue()
    assert "❌ НЕ ПРОЧИТАН" in out, out
    assert "прочитано 1, не прочитано 1" in out, out
    assert "ВХОЛОСТУЮ" not in out, out


def test_loop_health_today_is_read_for_real_not_hollow(tmp_path) -> None:
    """Сшивка разделов 6 и 7 на ТЕХ САМЫХ байтах 28.08.

    Раздел 6 научил шаг читать `loop_health`; раздел 7 отнимает у пустого
    разбора право называться чтением. Здесь проверяется, что первое не
    держится на втором: артефакт читается ПО-НАСТОЯЩЕМУ — квитанция есть,
    вхолостую нет, рецидивы названы.
    """
    _tree_with(tmp_path, {"data/loop_health.json": LOOP_HEALTH_PROD})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        MOD.main(["--root", str(tmp_path)], now=NOW_LH)
    out = buf.getvalue()
    assert "🔴 РЕЦИДИВ: 3" in out, out
    assert "ВХОЛОСТУЮ" not in out, out
    receipts = (tmp_path / "data" / "consumption_receipts.jsonl").read_text(encoding="utf-8")
    assert "data/loop_health.json" in receipts, receipts


# ── 8. храповик: объявленный читатель нельзя снять молча ─────────────────────
#
# Найдено мутацией в цикле #408 и записано как измеренный факт, а не как
# подозрение: снятие строки из `_READ_SCHEMA` НЕ КРАСИТ НИЧЕГО. Причина —
# `test_declared_schema_matches_the_live_producer` параметризован ПО САМОМУ
# `_READ_SCHEMA`, то есть проверка живёт внутри того, что проверяет: убрал
# объявление — убрал и его проверку. Это тот же класс, что весь ADR-157
# (доказательством служило эхо собственного молчания), только этажом ниже.
#
# Правдоподобный сценарий, ради которого храповик и заводится: производитель
# сменил форму, `test_declared_schema_matches_the_live_producer[X]` покраснел,
# и «починка» — снять строку X. CI зелёный, артефакт снова читается generic-
# веткой, и мы возвращаемся ровно в то состояние, из которого `loop_health`
# выбирался четыре рецидива подряд. Инвариант #16 запрещает такое ослабление
# молча — храповик делает его громким.
#
# База ТОЛЬКО РАСТЁТ (как `frozen_date_baseline.json` — только вниз): новую
# ветку добавлять свободно, снимать существующую — осознанно и с записью в
# журнал. Порога «у каждого артефакта конституции обязана быть ветка» здесь
# НЕТ и намеренно: активных артефактов с потребителем `orchestrator_protocol`
# 22, персональная ветка есть у 8, остальным 14 generic-ветка печатает
# осмысленное. Запрет в лоб покрасил бы 14 живых строк и был бы отключён.
SCHEMA_BASELINE = frozenset({
    "_health.json",
    "adapter_feed_divergence.json",
    "architecture_conformance.json",
    "chief_investment.json",
    "findings_bridge_report.json",
    "house_view_gap.json",
    "loop_health.json",
    "loop_retro.json",
})


def test_declared_readers_ratchet_only_grows() -> None:
    """Снять артефакт из `_READ_SCHEMA` = снять его проверку. Только осознанно."""
    lost = sorted(SCHEMA_BASELINE - set(MOD._READ_SCHEMA))
    assert not lost, (
        f"из `_READ_SCHEMA` пропали объявленные читатели: {lost}. Вместе с "
        "каждым пропала и его проверка формы производителя "
        "(`test_declared_schema_matches_the_live_producer` параметризован по "
        "`_READ_SCHEMA`), а артефакт вернулся на generic-ветку. Если снятие "
        "намеренно — обосновать в теле изменения и записать в "
        "`docs/journal/<неделя>.md` (инв. #16), затем опустить базу здесь.")


def test_ratchet_baseline_is_not_stale() -> None:
    """Обратный контроль: база — про ЭТОТ модуль, а не про его прошлое.

    База, в которой завёлся артефакт, уже снятый из `_READ_SCHEMA`, молча
    краснела бы навсегда; база, отставшая от кода, — усыпляла бы. Обе стороны
    закреплены: всё из базы есть в модуле (тест выше) и всё из базы объявлено
    в конституции (здесь).
    """
    manifest = json.loads((_REPO / "architecture" / "manifest.json").read_text(encoding="utf-8"))
    declared = {a["path"].split("/")[-1] for a in manifest.get("artifacts", [])}
    orphan = sorted(SCHEMA_BASELINE - declared)
    assert not orphan, (
        f"в базе храповика есть имена, которых нет в конституции: {orphan} — "
        "храповик стережёт то, чего система уже не производит")


# ── 4c. гистерезис ЗАКРЫТИЯ обязан быть СЛЫШЕН на шаге 0-офис (ADR-161, #417) ──
#
# ADR-161 научил мост не закрывать карточку по одному молчаливому прогону. Но
# сам шаг 0-офис про это ждание молчал: «создано 0 · закрыто 0» неотличимо от
# «мост ничего не сделал». Это ровно та болезнь, которую ADR-161 лечит ВНУТРИ
# моста, воспроизведённая одним уровнем выше.

def _bridge_report_c417(**extra):
    return dict({"generated_at": "2026-08-28T17:31:40.867625+00:00",
                 "created": [], "closed": [], "deferred": [], "waiting_hysteresis": [],
                 "escalated": [], "sources_unread": [], "open_cards": 1,
                 "delivery": {"status": "IDLE", "delivered": []}}, **extra)


def test_closing_hysteresis_is_named_with_the_card_and_the_streak() -> None:
    """Ждущая закрытия карточка НАЗВАНА, и назван счёт прогонов подряд."""
    out = _text(MOD._summarize_json("data/findings_bridge_report.json", _bridge_report_c417(
        closing_hysteresis=[{"key": "gap:opportunity_unnamed:spark_susds",
                             "card": "nimbalyst-local/tracker/inbox-spark.md",
                             "absent_count": 1, "required": 2}])))
    assert "ждут ЗАКРЫТИЯ по гистерезису: 1" in out, out
    assert "inbox-spark.md" in out, out
    assert "1/2" in out, out


def test_report_written_before_adr_161_raises_no_schema_alarm() -> None:
    """Обратный контроль: ключа нет — это НЕ расхождение схемы.

    Отчёты, написанные до ADR-161, законно не имеют `closing_hysteresis`.
    Внести его в `_READ_SCHEMA` значило бы поднять «СХЕМА РАЗОШЛАСЬ» на
    собственной доставке — класс «сторож краснеет на нашей же правке»."""
    out = _text(MOD._summarize_json("data/findings_bridge_report.json", _bridge_report_c417()))
    assert "СХЕМА РАЗОШЛАСЬ" not in out, out
    assert "ждут ЗАКРЫТИЯ" not in out, out


def test_empty_closing_list_stays_silent() -> None:
    """Пустой список — измеренный ноль, а не повод печатать строку ожидания."""
    out = _text(MOD._summarize_json("data/findings_bridge_report.json",
                                    _bridge_report_c417(closing_hysteresis=[])))
    assert "ждут ЗАКРЫТИЯ" not in out, out
