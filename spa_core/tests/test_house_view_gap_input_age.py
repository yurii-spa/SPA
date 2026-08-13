"""Возраст входа — часть находки: `house_view_gap` больше не судит в НАСТОЯЩЕМ времени (циклы #212 → доставлено #222).

Авария, которую эти тесты воспроизводят (прод, шаг 0-офис, замерено 2026-08-13 08:0x UTC):

    [WARN] возможность moonwell_base 8.3346% (evidence L3) доступна книге, не держится
           и отказ НЕ назван — безымянный простой (дух ADR-055)

Строка звучит как «прямо сейчас», а сравнивались снимки РАЗНЫХ тактов:

    data/investment_os/chief_investment.json   2026-08-12T09:11:49Z   возраст 22.9 ч
    data/current_positions.json                2026-08-13T06:55:19Z   возраст  1.2 ч

Сверка пересчитывается РАЗ В 6 ЧАСОВ (`com.spa.decision_loop` → `findings_bridge --run`,
`StartInterval 21600`; в дневном цикле она НЕ дублируется), а house_view офиса пишется РАЗ В
СУТКИ (09:11 UTC), поэтому разрыв тактов доходит до 24 часов ШТАТНО. Перемерено #222 на живом
проде: постура 13.7 ч, книга 1.6 ч — «ежечасно» из отчёта мёртвой сессии не подтвердилось,
число взято из plist. Исходная жалоба
(карточка `inbox-storozh-rashozhdenii-sudit-po-staromu-sn`, замер #200) — тот же дефект в
худшем виде: гэп кричал «постура офиса CRITICAL, но книга развёрнута», когда офис уже два
часа как YELLOW. Класс #146–#211: сторож честно отвечает на СВОЙ вопрос («что было в 07:03»),
а читается как ответ на нужный («что происходит сейчас»).

Почему это не косметика: находки этого файла — вход `findings_bridge`, то есть путь к КАРТОЧКЕ.
Вердикт, построенный на суточном снимке и утверждённый в настоящем времени, доезжает до очереди
как сегодняшний факт.

Лечение и что здесь проверяется:
  • возраст КАЖДОГО входа назван в самой находке и лежит в отчёте (`inputs`) машинно;
  • старше потолка офиса (`investment_os.health.FRESH_AGE_S` = 48 ч) ⇒ сверка ОТКАЗЫВАЕТСЯ
    судить: запись в `unchecked` вместо WARN в настоящем времени;
  • «возраст не измерен» НАЗЫВАЕТСЯ и НЕ считается протухшим (иначе необратимое «не измерено»
    морит сверку насмерть);
  • потолок берётся у монитора здоровья САМОГО офиса — второй литерал разошёлся бы молча.

Каждый тест судит ЭФФЕКТ (какая находка родилась и что в ней написано), а не читает исходник.
Снятие починки красит поимённо: без наименования возраста падают `*_names_the_age_*`, без
отказа — `*_refuses_*`, возврат потолка литералом — `test_ceiling_is_the_office_own_definition`.

Время — ВХОД (`now=` + фиксированные отметки входов): обе стороны закреплены, календарь
на эти тесты не влияет. LLM_FORBIDDEN. Только stdlib.
"""
# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — «сейчас» подаётся ВХОДОМ (NOW → compute_gaps(..., now=) /
# run(now=)), а отметки входов фиксированы теми же литералами (CHIEF_STAMP/BOOK_STAMP,
# os.utime от NOW). Обе стороны закреплены, настенных часов в файле нет ни одного вызова ⇒
# календарь на этот тест не влияет. Это preference #1 правила .claude/rules/deployment.md,
# и маркер тут ПРАВДА, а не глушение: снимите инъекцию — и тест обязан покраснеть.
from __future__ import annotations

import datetime as dt
import json
import os

from spa_core.investment_os import health as OFFICE_HEALTH
from spa_core.monitoring import house_view_gap as H

#: Момент замера прода 13.08 — и «сейчас» для всех тестов. Обе стороны фиксированы.
NOW = dt.datetime(2026, 8, 13, 8, 5, tzinfo=dt.timezone.utc)

#: Реальные отметки входов того же замера (см. шапку).
CHIEF_STAMP = "2026-08-12T09:11:49.960417+00:00"   # 22.9 ч до NOW
BOOK_STAMP = "2026-08-13T06:55:19.716991+00:00"    # 1.2 ч до NOW

HOUR = 3600.0


def meta(input_name: str, age_h: float | None, stamp: str | None = None) -> dict:
    """Замер возраста входа в той форме, которую строит `snapshot_age`."""
    return {"input": input_name, "generated_at": stamp,
            "age_s": None if age_h is None else round(age_h * HOUR, 1),
            "age_source": None if age_h is None else "generated_at"}


def chief(posture: str = "YELLOW", opportunity: str | None = "moonwell_base") -> dict:
    opps = ([{"evidence_level": "L3", "source": "defillama",
              "value": {"protocol": opportunity, "apy_pct": 8.3346}}] if opportunity else [])
    return {"generated_at": CHIEF_STAMP,
            "house_view": {"overall_posture": posture, "top_opportunities": opps}}


def book() -> dict:
    """Книга прода 13.08: развёрнута, cash 10 % — та самая «книга не слышит»."""
    return {"generated_at": BOOK_STAMP, "capital_usd": 100000.0, "cash_usd": 10000.0,
            "positions": {"aave_v3": {"usd": 40000.0}, "pendle": {"usd": 20000.0},
                          "maple": {"usd": 20000.0}, "morpho_steakhouse": {"usd": 10000.0}}}


def gaps_of(report: dict, gap_type: str) -> list[dict]:
    return [g for g in report["gaps"] if g["type"] == gap_type]


def unchecked_inputs(report: dict) -> set[str]:
    return {u["input"] for u in report["unchecked"]}


def compute(chief_doc, ages, *, positions=None, analysts=None, registry=("moonwell_base",)):
    return H.compute_gaps(chief_doc, positions if positions is not None else book(),
                          {"below_median_cap": []}, set(registry or ()) or None,
                          analysts or {}, NOW, ages=ages)


FRESH_AGES = {"chief_investment": meta("chief_investment", 22.9, CHIEF_STAMP),
              "current_positions": meta("current_positions", 1.2, BOOK_STAMP)}


# ── 1. Авария 13.08 дословно: возраст ОБОИХ входов назван в находке ──────────────────

def test_opportunity_finding_names_the_age_of_both_snapshots() -> None:
    """Та самая строка прода — теперь с тактами: постура 22.9 ч, книга 1.2 ч."""
    report = compute(chief(), FRESH_AGES)
    found = gaps_of(report, "opportunity_unheld")
    assert len(found) == 1, report["gaps"]
    message = found[0]["message"]
    assert "безымянный простой" in message          # находка НЕ погашена
    assert "22.9 ч назад" in message, message       # постура названа
    assert "1.2 ч назад" in message, message        # книга названа


def test_posture_finding_names_the_age_of_both_snapshots() -> None:
    """«офис кричит, книга не слышит» обязано сказать, КОГДА кричал и КОГДА книга."""
    report = compute(chief(posture="RED"), FRESH_AGES)
    found = gaps_of(report, "posture_vs_book")
    assert len(found) == 1, report["gaps"]
    assert "22.9 ч назад" in found[0]["message"]
    assert "1.2 ч назад" in found[0]["message"]


def test_finding_carries_machine_readable_input_ages() -> None:
    """Возраст нужен не только глазами: мост и дашборд читают его полем, а не парсингом фразы."""
    found = gaps_of(compute(chief(posture="RED"), FRESH_AGES), "posture_vs_book")[0]
    assert found["input_ages"]["chief_investment"]["age_s"] == round(22.9 * HOUR, 1)
    assert found["input_ages"]["current_positions"]["age_s"] == round(1.2 * HOUR, 1)


# ── 2. Положительный контроль карточки: протухший CRITICAL находки НЕ даёт ───────────

def test_refuses_to_judge_a_posture_older_than_the_ceiling() -> None:
    """Жалоба #200 в чистом виде: снимок старше потолка ⇒ ОТКАЗ, а не WARN в настоящем времени."""
    stale = {"chief_investment": meta("chief_investment", 60.0, CHIEF_STAMP),
             "current_positions": meta("current_positions", 1.2, BOOK_STAMP)}
    report = compute(chief(posture="CRITICAL"), stale)
    assert gaps_of(report, "posture_vs_book") == []
    assert "chief_investment" in unchecked_inputs(report)
    reason = [u["reason"] for u in report["unchecked"] if u["input"] == "chief_investment"][0]
    assert "ОТКАЗЫВАЕТСЯ" in reason and "60.0 ч назад" in reason, reason


def test_stale_posture_also_silences_its_opportunities() -> None:
    """Возможности живут в ТОМ ЖЕ снимке: судить о них по протухшему нельзя тоже."""
    stale = {"chief_investment": meta("chief_investment", 60.0, CHIEF_STAMP),
             "current_positions": meta("current_positions", 1.2, BOOK_STAMP)}
    report = compute(chief(posture="CRITICAL"), stale)
    assert gaps_of(report, "opportunity_unheld") == []


def test_a_genuinely_fresh_critical_still_produces_the_finding() -> None:
    """Обратный контроль: отказ не должен съесть НАСТОЯЩУЮ тревогу — свежий CRITICAL звучит."""
    fresh = {"chief_investment": meta("chief_investment", 0.5, CHIEF_STAMP),
             "current_positions": meta("current_positions", 1.2, BOOK_STAMP)}
    found = gaps_of(compute(chief(posture="CRITICAL"), fresh), "posture_vs_book")
    assert len(found) == 1
    assert "CRITICAL" in found[0]["message"] and "0.5 ч назад" in found[0]["message"]


def test_fresh_yellow_posture_is_not_a_finding() -> None:
    """Второй обратный контроль карточки: YELLOW — не конфликт, сколько бы ни было кэша."""
    report = compute(chief(posture="YELLOW"), FRESH_AGES)
    assert gaps_of(report, "posture_vs_book") == []
    assert "chief_investment" not in unchecked_inputs(report)


# ── 3. «Не измерено» — называется, но сверку не убивает ──────────────────────────────

def test_unmeasured_age_is_named_not_assumed_fresh() -> None:
    """Пропуск замера читался бы как «свежо». Он обязан быть виден словами."""
    blind = {"chief_investment": meta("chief_investment", None),
             "current_positions": meta("current_positions", None)}
    found = gaps_of(compute(chief(posture="RED"), blind), "posture_vs_book")
    assert len(found) == 1
    assert H.AGE_UNMEASURED_RU in found[0]["message"], found[0]["message"]


def test_unmeasured_age_is_not_treated_as_stale() -> None:
    """Урок «необратимое не измерено морит очередь»: неизвестный возраст ≠ протухший."""
    assert H.is_too_old(meta("chief_investment", None)) is False
    assert H.is_too_old(None) is False
    assert H.is_too_old(meta("chief_investment", 60.0)) is True
    assert H.is_too_old(meta("chief_investment", 22.9)) is False


def test_legacy_caller_without_ages_still_judges_and_says_so() -> None:
    """Вызов без замера (старая сигнатура) не падает и не молчит — он ГОВОРИТ «не измерено»."""
    report = H.compute_gaps(chief(posture="RED"), book(), {"below_median_cap": []},
                            {"moonwell_base"}, {}, NOW)
    found = gaps_of(report, "posture_vs_book")
    assert len(found) == 1
    assert H.AGE_UNMEASURED_RU in found[0]["message"]


# ── 4. Аналитик: та же болезнь, тот же приём ─────────────────────────────────────────

def test_analyst_red_names_the_age_of_its_snapshot() -> None:
    """«аналитик red_team: CRITICAL» суточной давности читается как сегодняшняя разведка."""
    ages = dict(FRESH_AGES, **{"analyst:red_team": meta("red_team", 22.9, CHIEF_STAMP)})
    found = gaps_of(compute(chief(), ages, analysts={"red_team": {"status": "CRITICAL"}}),
                    "analyst_red")
    assert len(found) == 1
    assert "22.9 ч назад" in found[0]["message"], found[0]["message"]
    assert found[0]["key"] == "gap:analyst_red:red_team"   # ключ моста НЕ менялся


def test_analyst_red_older_than_the_ceiling_is_refused_not_announced() -> None:
    ages = dict(FRESH_AGES, **{"analyst:red_team": meta("red_team", 72.0, CHIEF_STAMP)})
    report = compute(chief(), ages, analysts={"red_team": {"status": "CRITICAL"}})
    assert gaps_of(report, "analyst_red") == []
    assert "analyst:red_team" in unchecked_inputs(report)


# ── 5. Замер возраста: чем меряем и в каком порядке ──────────────────────────────────

def test_snapshot_age_prefers_the_declared_stamp_over_mtime(tmp_path) -> None:
    """mtime молодит содержимое (перезапись без пересчёта, копирование дерева) — врёт в нашу
    пользу, поэтому первым читается ЗАЯВЛЕННЫЙ `generated_at`."""
    path = tmp_path / "chief_investment.json"
    doc = {"generated_at": CHIEF_STAMP}
    path.write_text(json.dumps(doc))
    os.utime(path, (NOW.timestamp(), NOW.timestamp()))    # «положен на диск только что»
    got = H.snapshot_age(doc, str(path), NOW)
    assert got["age_source"] == "generated_at"
    assert round(got["age_s"] / HOUR, 1) == 22.9


def test_snapshot_age_falls_back_to_mtime_when_no_stamp(tmp_path) -> None:
    path = tmp_path / "current_positions.json"
    path.write_text(json.dumps({"capital_usd": 1}))
    os.utime(path, ((NOW - dt.timedelta(hours=3)).timestamp(),) * 2)
    got = H.snapshot_age({"capital_usd": 1}, str(path), NOW)
    assert got["age_source"] == "mtime"
    assert round(got["age_s"] / HOUR, 1) == 3.0


def test_snapshot_age_of_a_missing_input_is_unmeasured_not_zero(tmp_path) -> None:
    got = H.snapshot_age(None, str(tmp_path / "nope.json"), NOW)
    assert got["age_s"] is None and got["age_source"] is None


def test_snapshot_age_ignores_an_unparsable_stamp(tmp_path) -> None:
    """Мусор в `generated_at` не имеет права стать возрастом — падаем на mtime, не на догадку."""
    path = tmp_path / "chief_investment.json"
    doc = {"generated_at": "вчера примерно"}
    path.write_text(json.dumps(doc))
    os.utime(path, ((NOW - dt.timedelta(hours=5)).timestamp(),) * 2)
    got = H.snapshot_age(doc, str(path), NOW)
    assert got["age_source"] == "mtime"
    assert round(got["age_s"] / HOUR, 1) == 5.0


# ── 6. Потолок — одно определение на репо ────────────────────────────────────────────

def test_ceiling_is_the_office_own_definition(monkeypatch) -> None:
    """Сверка не может быть увереннее в артефакте офиса, чем сторож здоровья офиса.

    Проверка равенства значений ЗДЕСЬ НЕДОСТАТОЧНА: скопированный литерал `2 * 86400` прошёл бы
    её и разошёлся бы с оригиналом молча в первый же день, когда офис подвинет свой потолок.
    Поэтому двигаем потолок ОФИСА и требуем, чтобы поехал потолок сверки.
    """
    import importlib

    assert H.MAX_INPUT_AGE_S == OFFICE_HEALTH.FRESH_AGE_S == 2 * 86400
    monkeypatch.setattr(OFFICE_HEALTH, "FRESH_AGE_S", 6 * 3600)
    try:
        assert importlib.reload(H).MAX_INPUT_AGE_S == 6 * 3600
    finally:
        monkeypatch.undo()
        importlib.reload(H)   # вернуть модуль остальным тестам нетронутым
    assert H.MAX_INPUT_AGE_S == 2 * 86400


# ── 7. Отчёт целиком: возраст входов доезжает до потребителя ─────────────────────────

def test_report_carries_every_input_age_and_the_ceiling() -> None:
    report = compute(chief(posture="RED"), FRESH_AGES)
    assert report["input_age_ceiling_s"] == OFFICE_HEALTH.FRESH_AGE_S
    assert set(report["inputs"]) == {"chief_investment", "current_positions"}


def test_run_measures_the_age_of_every_input_it_reads(tmp_path) -> None:
    """Прод-путь: `run()` обязан САМ замерить возраст — иначе наименование остаётся теорией."""
    root = tmp_path
    (root / "data" / "investment_os").mkdir(parents=True)
    (root / "data" / "investment_os" / "chief_investment.json").write_text(
        json.dumps(chief(posture="RED")))
    (root / "data" / "investment_os" / "red_team.json").write_text(
        json.dumps({"generated_at": CHIEF_STAMP, "status": "CRITICAL"}))
    (root / "data" / "current_positions.json").write_text(json.dumps(book()))
    report = H.run(root=str(root), now=NOW, write=False, receipts=False)
    assert report["inputs"]["chief_investment"]["age_s"] == 82_390.0     # 22.886 ч
    assert report["inputs"]["current_positions"]["age_s"] == 4_180.3     # 1.161 ч
    assert report["inputs"]["analyst:red_team"]["age_s"] == 82_390.0
    assert "22.9 ч назад" in gaps_of(report, "posture_vs_book")[0]["message"]
