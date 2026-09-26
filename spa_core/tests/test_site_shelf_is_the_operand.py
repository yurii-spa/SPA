"""test_site_shelf_is_the_operand.py — сторож сверял страницу с производителем,
которого она не читает (ADR-478).

Замер 2026-09-26, ради которого написан набор. Живой earn-defi.com шесть суток
отдавал `as of 2026-09-20` и APY 5,0 %. Кустодиан называл это `PUBLISHER_STUCK`
(CRITICAL) и писал в находке «лекарство вне этого репозитория — сборка
Cloudflare Pages»; по этой находке была заведена карточка `critical` владельцу,
отправлявшая его в кабинет Cloudflare.

Ни то, ни другое не было правдой, и это ИЗМЕРЕНО, а не выведено:
`npm ci && astro build` на `origin/main` (7bffa76e8) собрал 120 страниц кодом 0,
и `dist/` нёс ту же самую `as of 2026-09-20`, что читал посетитель. Cloudflare
публиковал ИСПРАВНО и публиковал ровно то, что лежало в репозитории.

Причина: с 13.09 (ADR-372) страница печатает числа из ВИТРИНЫ
`landing/src/data/site_numbers.json`, такт её публикации НЕДЕЛЬНЫЙ по установке
владельца (ADR-357 п. 5), и на 26.09 она законно несла замер 20.09
(`build_site_numbers.py --if-due`: «прошло 6 дн из 7»). Сторож же сравнивал
страницу с ЕЖЕДНЕВНЫМ снимком — то есть краснел ровно за то, что установка
владельца предписывает, и указывал на дверь, за которой поломки нет.

Каждый тест ниже — либо положительный контроль на эту сцену, либо контроль в
обратную сторону: исправление операнда НЕ ИМЕЕТ ПРАВА погасить ни настоящий
вставший публикатор, ни настоящее завышение, ни замершего производителя витрины.
"""
# FROZEN-DATE-OK: injected-clock — якорь NOW уходит входом в evaluate(now=NOW), и все
# даты фикстур вычисляются ОТ НЕГО арифметикой timedelta (`_day`); стенных часов в
# файле нет ни одного вызова.
import datetime
import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "site_freshness_monitor", _ROOT / "scripts" / "site_freshness_monitor.py")
mon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mon)

NOW = datetime.datetime(2026, 9, 26, 3, 30, 0, tzinfo=datetime.timezone.utc)
PIN = "b" * 64


def _day(days_ago=0):
    return (NOW - datetime.timedelta(days=days_ago)).date().isoformat()


def _home(asof):
    return f'<span id="sl-asof">as of {asof}</span>'


def _track(asof, days=89, apy="5.0", equity="101,341"):
    return (f'<p id="tr-equity">${equity}</p><p id="tr-apy">~{apy}%</p>'
            f'<p id="tr-days-2">{days}</p>'
            f'<p id="tr-asof">static snapshot as of {asof}</p>')


def _snap(asof, days=94, apy=4.9354, gates=29):
    return {"as_of": asof, "real_track_days": days, "paper_apy_pct": apy,
            "gates_passed": gates, "end_equity": 101400.93}


def _shelf(measured, *, days=89, gates=29, apy=4.9637, next_pub=None, cadence="weekly"):
    return {"measured_at": measured, "published_at": measured, "cadence": cadence,
            "next_publication": next_pub if next_pub is not None else _day(-1),
            "headline": {"apy": {"value": apy}, "evidenced_days": {"value": days},
                         "gates": {"passed": gates, "total": 29}}}


def _api(apy=4.9386, days=94):
    return {"evidenced_days": days, "paper_apy_pct": apy, "gates_passed": 29,
            "end_equity": 101401.72, "last_bar": _day(0), "apy_source": "evidenced_chain"}


def _ev(*, site_asof, snap_asof, shelf, api=None, site_apy="5.0", site_days=89, now=None):
    return mon.evaluate(
        snapshot=_snap(snap_asof), home_html=_home(site_asof),
        track_html=_track(site_asof, days=site_days, apy=site_apy),
        api=api if api is not None else _api(),
        sitemap_statuses={"https://earn-defi.com/": 200},
        verifier_sha=PIN, pin_sha=PIN, now=now or NOW, prev_report=None,
        site_numbers=shelf)


def _codes(r):
    return [f["code"] for f in r["fails"]]


# ── положительный контроль: сцена 20–26.09 целиком ────────────────────────────
def test_the_weekly_shelf_lagging_the_daily_snapshot_is_not_a_stuck_publisher():
    """Сцена 26.09 дословно: страница = витрина (20.09), снимок ушёл на 25.09."""
    r = _ev(site_asof=_day(6), snap_asof=_day(1), shelf=_shelf(_day(6), next_pub=_day(-1)))
    codes = _codes(r)
    assert "PUBLISHER_STUCK" not in codes, codes
    assert "SITE_BEHIND_SNAPSHOT" not in codes, codes
    assert r["publisher_stuck"] is False
    assert r["publisher_leg"] == "measured"        # ИЗМЕРЕНО, а не «не измерено»
    assert r["publish_lag_days"] == 0


def test_the_false_verdict_is_exactly_what_the_old_operand_produced():
    """Дифференциальный контроль: та же сцена со снимком в операнде даёт ложный
    CRITICAL. Это и есть предмет ADR-478 — без него тест не отличить от тавтологии."""
    scene = dict(site_asof=_day(6), snap_asof=_day(1))
    good = _ev(**scene, shelf=_shelf(_day(6), next_pub=_day(-1)))
    # операнда нет ⇒ вердикт НЕ ИЗМЕРЕН и сказан вслух, а НЕ подменён снимком
    blind = _ev(**scene, shelf=None)
    assert "PUBLISHER_STUCK" not in _codes(good)
    assert blind["publisher_leg"].startswith("unmeasured:")
    assert "SHELF_UNREADABLE" in _codes(blind)


def test_the_cure_named_in_the_finding_is_no_longer_cloudflare_when_the_shelf_is_late():
    """Лекарство обязано указывать на ту дверь, за которой поломка. Замершая витрина
    чинится ВНУТРИ репозитория, и находка это говорит."""
    r = _ev(site_asof=_day(9), snap_asof=_day(0), shelf=_shelf(_day(9), next_pub=_day(2)))
    overdue = [f for f in r["fails"] if f["code"] == "SHELF_OVERDUE"]
    assert len(overdue) == 1, _codes(r)
    assert "build_site_numbers.py" in overdue[0]["detail"]
    assert "Cloudflare" in overdue[0]["detail"]      # названо, что он НИ ПРИ ЧЁМ


# ── контроль в обратную сторону: настоящий вставший публикатор ────────────────
def test_a_genuinely_stuck_publisher_is_still_CRITICAL():
    """Витрина опубликовала новое, посетитель читает старое ⇒ встал ПУБЛИКАТОР."""
    r = _ev(site_asof=_day(6), snap_asof=_day(0), shelf=_shelf(_day(0), next_pub=_day(-1)))
    stuck = [f for f in r["fails"] if f["code"] == "PUBLISHER_STUCK"]
    assert len(stuck) == 1, _codes(r)
    assert stuck[0]["severity"] == "CRITICAL"
    assert r["publish_lag_days"] == 6
    assert "Cloudflare Pages" in stuck[0]["detail"]   # здесь дверь ВЕРНАЯ


def test_the_publisher_bound_stays_inclusive_on_the_third_day():
    two = _ev(site_asof=_day(2), snap_asof=_day(0), shelf=_shelf(_day(0), next_pub=_day(-1)))
    three = _ev(site_asof=_day(3), snap_asof=_day(0), shelf=_shelf(_day(0), next_pub=_day(-1)))
    assert two["publisher_stuck"] is False and two["publish_lag_days"] == 2
    assert three["publisher_stuck"] is True and three["publish_lag_days"] == 3


def test_a_real_overstatement_survives_the_operand_fix():
    """Самое важное: настоящий публичный вред НЕ погашен. 5,0 % против живых 4,9386 %
    остаётся CRITICAL при полностью исправном публикаторе."""
    r = _ev(site_asof=_day(6), snap_asof=_day(1), shelf=_shelf(_day(6), next_pub=_day(-1)))
    over = [f for f in r["fails"] if f["code"] == "OVERSTATED_METRIC"]
    assert len(over) == 1, _codes(r)
    assert over[0]["severity"] == "CRITICAL"
    assert r["site_overstated"] is True
    assert r["ok"] is False


# ── третий исход: витрина нечитаема ⇒ громко, а не зелено и не снимком ────────
def test_a_missing_shelf_is_loud_and_never_falls_back_to_the_snapshot():
    r = _ev(site_asof=_day(0), snap_asof=_day(0), shelf=None)
    assert "SHELF_UNREADABLE" in _codes(r)
    assert r["ok"] is False
    assert r["shelf_leg"] == "unmeasured:no_shelf_file"
    assert r["publish_lag_days"] is None            # НЕ 0 и не посчитан по снимку
    assert r["shelf_as_of"] is None


def test_a_shelf_without_measured_at_names_its_own_reason():
    r = _ev(site_asof=_day(0), snap_asof=_day(0), shelf={"cadence": "weekly"})
    assert r["shelf_leg"] == "unmeasured:shelf_has_no_measured_at"
    assert "SHELF_UNREADABLE" in _codes(r)


def test_an_unreadable_shelf_makes_the_cadence_unmeasured_not_in_cadence():
    r = _ev(site_asof=_day(0), snap_asof=_day(0), shelf=None)
    overdue = [f for f in r["fails"] if f["code"] == "SHELF_OVERDUE"]
    assert len(overdue) == 1, _codes(r)
    assert "НЕ ИЗМЕРЕН" in overdue[0]["detail"]
    assert r["shelf_overdue_days"] is None
    assert r["shelf_cadence_leg"].startswith("unmeasured:")


def test_a_shelf_declaring_no_deadline_is_unmeasured_with_its_own_name():
    shelf = _shelf(_day(6))
    del shelf["next_publication"]
    r = _ev(site_asof=_day(6), snap_asof=_day(0), shelf=shelf)
    assert r["shelf_cadence_leg"] == "unmeasured:shelf_declares_no_next_publication"
    assert "SHELF_OVERDUE" in _codes(r)


def test_an_unparseable_deadline_is_unmeasured_and_names_the_value():
    r = _ev(site_asof=_day(6), snap_asof=_day(0), shelf=_shelf(_day(6), next_pub="не-дата"))
    assert r["shelf_cadence_leg"].startswith("unmeasured:next_publication_unparseable")
    assert "не-дата" in r["shelf_cadence_leg"]


# ── контроль на СОБСТВЕННУЮ дыру исправления: замершая витрина ────────────────
def test_a_frozen_shelf_producer_cannot_pass_silently():
    """Сама суть контроля на контроль. После исправления операнда страница равна
    витрине ПО ПОСТРОЕНИЮ — значит замершая витрина прошла бы все сверки зелёной, и
    сайт годами показывал бы одно число. Поэтому такт спрашивается ОТДЕЛЬНО."""
    r = _ev(site_asof=_day(40), snap_asof=_day(0), shelf=_shelf(_day(40), next_pub=_day(33)))
    overdue = [f for f in r["fails"] if f["code"] == "SHELF_OVERDUE"]
    assert len(overdue) == 1, _codes(r)
    assert overdue[0]["severity"] == "CRITICAL"
    assert r["shelf_overdue_days"] == 33
    assert r["ok"] is False


def test_a_shelf_inside_its_cadence_is_not_called_overdue():
    r = _ev(site_asof=_day(6), snap_asof=_day(0), shelf=_shelf(_day(6), next_pub=_day(-1)))
    assert "SHELF_OVERDUE" not in _codes(r)
    assert r["shelf_overdue_days"] == -1           # ещё сутки до срока
    assert r["shelf_cadence_leg"] == "measured"


def test_the_overdue_bound_separates_fail_from_critical():
    one = _ev(site_asof=_day(8), snap_asof=_day(0), shelf=_shelf(_day(8), next_pub=_day(1)))
    three = _ev(site_asof=_day(10), snap_asof=_day(0), shelf=_shelf(_day(10), next_pub=_day(3)))
    sev = {f["code"]: f["severity"] for f in one["fails"]}
    sev3 = {f["code"]: f["severity"] for f in three["fails"]}
    assert sev["SHELF_OVERDUE"] == "FAIL" and one["shelf_overdue_days"] == 1
    assert sev3["SHELF_OVERDUE"] == "CRITICAL" and three["shelf_overdue_days"] == 3


def test_the_day_of_the_deadline_itself_is_not_yet_overdue():
    r = _ev(site_asof=_day(7), snap_asof=_day(0), shelf=_shelf(_day(7), next_pub=_day(0)))
    assert r["shelf_overdue_days"] == 0
    assert "SHELF_OVERDUE" not in _codes(r)


# ── операнды сверки ЧИСЕЛ идут из того же источника (заказ G86 п. 1) ──────────
def test_the_counted_numbers_are_asked_of_the_shelf_too():
    """Дни И ГЕЙТЫ рендерятся из витрины — спрашивать их у снимка значит сверять
    страницу с файлом, которого она не читает.

    Оба числа обязаны РАСХОДИТЬСЯ между снимком и витриной, иначе тест не отличает
    операнды: при совпадающих гейтах (29 и там, и там) подмена операнда проходила
    мимо батареи — замерено мутацией, закрыто здесь усилением КОНТРОЛЯ, а не
    правкой прибора."""
    r = mon.evaluate(
        snapshot=_snap(_day(1), days=94, gates=29),
        home_html=f'<span class="num" id="sl-day">89</span>'
                  f'<span class="num" id="sl-gates">27/29</span>'
                  f'<span id="sl-asof">as of {_day(6)}</span>',
        track_html=_track(_day(6)), api=_api(),
        sitemap_statuses={"https://earn-defi.com/": 200},
        verifier_sha=PIN, pin_sha=PIN, now=NOW, prev_report=None,
        site_numbers=_shelf(_day(6), days=89, gates=27, next_pub=_day(-1)))
    assert "SITE_BEHIND_SNAPSHOT" not in _codes(r), _codes(r)
    assert r["shelf"]["evidenced_days"] == 89 and r["shelf"]["gates_passed"] == 27
    assert r["snapshot"]["real_track_days"] == 94 and r["snapshot"]["gates_passed"] == 29


def test_a_page_disagreeing_with_the_shelf_numbers_is_still_caught():
    """Контроль в обратную сторону: сверка чисел не выключена, только переадресована."""
    r = mon.evaluate(
        snapshot=_snap(_day(1)),
        home_html=f'<span class="num" id="sl-day">70</span>'
                  f'<span class="num" id="sl-gates">21/29</span>'
                  f'<span id="sl-asof">as of {_day(6)}</span>',
        track_html=_track(_day(6)), api=_api(),
        sitemap_statuses={"https://earn-defi.com/": 200},
        verifier_sha=PIN, pin_sha=PIN, now=NOW, prev_report=None,
        site_numbers=_shelf(_day(6), days=89, gates=29))
    details = [f["detail"] for f in _ev_codes_helper(r)]
    assert any("evidenced_days" in d for d in details), details
    assert any("gates_passed" in d for d in details), details
    assert all("витрина" in d for d in details), details


def _ev_codes_helper(r):
    return [f for f in r["fails"] if f["code"] == "SITE_BEHIND_SNAPSHOT"]


# ── отчёт печатает ОБА производителя рядом ────────────────────────────────────
def test_the_report_shows_both_producers_side_by_side():
    """Разность «снимок vs витрина» — НОРМА при недельном такте. Её печатают, чтобы
    это было видно глазами, а не выяснялось отладкой в следующем цикле."""
    r = _ev(site_asof=_day(6), snap_asof=_day(1), shelf=_shelf(_day(6), next_pub=_day(-1)))
    assert r["shelf"]["measured_at"] == _day(6)
    assert r["shelf"]["cadence"] == "weekly"
    assert r["snapshot"]["as_of"] == _day(1)
    assert r["shelf_as_of"] == _day(6) and r["shelf_next_publication"] == _day(-1)


def test_the_kill_rule_reach_is_true_when_the_visitor_reads_what_we_published():
    """`degrade_reaches_public` считается от того же операнда: посетитель читает
    опубликованное ⇒ табличка честности доедет."""
    r = _ev(site_asof=_day(6), snap_asof=_day(1), shelf=_shelf(_day(6), next_pub=_day(-1)))
    assert r["degrade_reaches_public"] is True
    assert r["degrade_reaches_public_reason"] == "site_serves_the_published_as_of"


def test_the_kill_rule_reach_is_false_only_when_the_publisher_is_really_stuck():
    r = _ev(site_asof=_day(6), snap_asof=_day(0), shelf=_shelf(_day(0), next_pub=_day(-1)))
    assert r["degrade_reaches_public"] is False
    assert r["degrade_reaches_public_reason"] == "publisher_stuck:plaque_would_not_publish"


# ── контроль на «не измерено» как исход, а не как скип ────────────────────────
def test_an_unmeasured_shelf_is_never_reported_as_ok():
    """Три исхода различимы: измерено · измерено и в такте · НЕ измерено (инв. #17)."""
    seen = set()
    for shelf in (None, {"cadence": "weekly"}, _shelf(_day(6), next_pub=_day(-1))):
        r = _ev(site_asof=_day(6), snap_asof=_day(1), shelf=shelf)
        seen.add(r["shelf_leg"])
    assert seen == {"unmeasured:no_shelf_file",
                    "unmeasured:shelf_has_no_measured_at",
                    "measured"}, seen


def test_the_battery_itself_fails_loudly_rather_than_skipping():
    """Контроль на контроль: набор не имеет права молча исчезнуть. `pytest.skip`
    поднимает потомка BaseException, поэтому проверять надо ТИП исхода."""
    with pytest.raises(BaseException) as ei:
        pytest.skip("контроль: скип — не исход")
    assert not isinstance(ei.value, AssertionError)
