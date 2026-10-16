"""Сторож сайта читает разметку, ОДОБРЕННУЮ владельцем 07.10 (PRODUCT-UX-01), а не прежнюю.

Тревога после перезагрузки 15.10 (карточка `inbox-arb-razobrat-trevogu-telegram-posle-pere`):
`com.spa.site_freshness` выходил с кодом 1 по двум причинам, и обе — дефект СТОРОЖА, не сайта:

* `MISSING_ASOF: home page has no as-of label` — главная после PRODUCT-UX-01 печатает дату
  замера витрины словами «measured 2026-10-15» / «замер 2026-10-15» (`profile_view.js` →
  `measuredAt()`), а сторож искал только «as of …». Метка на странице ЕСТЬ.
* `COMPARISON_NOT_MEASURED` по `gates_passed` — все три объявленных источника (`m-gates`,
  `sl-gates`, `tr-gates-pass`) с 07.10 отсутствуют в разметке вовсе, а пара гейтов
  отрисована сервером на /status/ (`st-gates-pass` ← `snapshot_view.js` ← витрина). И слова
  находки врали: «страница дорисовывает клиентом» — при id, которого нет нигде.

Ничего в `landing/**` не меняется: ни текста, ни чисел (предмет №2 ADR-285 не задет).
Фикстуры — дословная форма живой разметки 16.10. Положительные контроли красные на origin
8f913113; обратные: без метки — MISSING_ASOF, расхождение на /status/ — SITE_BEHIND_SNAPSHOT.

# FROZEN-DATE-OK: injected-clock — NOW передаётся в evaluate(now=); даты разметки и витрины
# выводятся из него же через _day().
"""
import datetime
import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "site_freshness_monitor_ux01", _ROOT / "scripts" / "site_freshness_monitor.py")
mon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mon)

NOW = datetime.datetime(2026, 10, 16, 2, 0, 0, tzinfo=datetime.timezone.utc)
PIN = "c" * 64


def _day(days_ago=0):
    return (NOW - datetime.timedelta(days=days_ago)).date().isoformat()


def _home_ux01(d, *, label=True):
    """Главная 16.10: ни одного `m-*` id, дата — словом «measured»."""
    tail = f" · measured {d}" if label else ""
    ru_tail = f" · замер {d}" if label else ""
    return ('<dd> <span class="big" data-ru="+1,51 %">+1.51%</span>  '
            f'<span data-ru="за 115 дн. на бумаге, ACT/365 · просадка −0,04 %{ru_tail}">'
            f'over 115 days on paper, ACT/365 · drawdown −0.04%{tail}</span></dd>')


def _track_ux01(d, days=114):
    """/track-record 16.10: `tr-gates-pass` в разметке НЕТ (остался только в JS setText)."""
    return (f'<p id="tr-equity">$101,662.57</p><span id="tr-days-2">{days}</span>'
            f'<p id="tr-asof" data-ru="статичный снимок на {d}">static snapshot as of {d}</p>'
            "<script>setText('tr-gates-pass', pass);</script>")


def _status(passed=29):
    return (f'<span class="text-5xl font-bold text-warn" id="st-gates-pass">{passed}</span>'
            '<span id="st-gates-total">29</span>')


def _shelf(d, days=114, gates=29):
    return {"measured_at": d, "published_at": d, "cadence": "weekly",
            "next_publication": _day(-6),
            "headline": {"evidenced_days": {"value": days},
                         "gates": {"passed": gates, "total": 29}}}


def _ev(*, home=None, track=None, status=None, shelf=None):
    d = _day(0)
    return mon.evaluate(
        snapshot={"as_of": d, "real_track_days": 114, "gates_passed": 29},
        home_html=_home_ux01(d) if home is None else home,
        track_html=_track_ux01(d) if track is None else track,
        api={}, sitemap_statuses={"https://earn-defi.com/": 200},
        verifier_sha=PIN, pin_sha=PIN, now=NOW, prev_report=None,
        site_numbers=_shelf(d) if shelf is None else shelf, status_html=status)


def _codes(r):
    return [f["code"] for f in r["fails"]]


def test_measured_label_on_home_is_the_as_of():
    assert mon.parse_site_numbers(_home_ux01("2026-10-15"), page="home")["as_of"] == "2026-10-15"


def test_ux01_site_with_status_page_is_clean():
    r = _ev(status=_status())
    assert "MISSING_ASOF" not in _codes(r), r["fails"]
    assert "COMPARISON_NOT_MEASURED" not in _codes(r), r["fails"]
    assert r["number_legs"]["gates_passed"] == "measured:status#st-gates-pass=29"
    assert r["site_home"]["as_of"] == _day(0)


def test_gates_divergence_on_status_is_still_caught():
    r = _ev(status=_status(passed=28))
    assert any(f["code"] == "SITE_BEHIND_SNAPSHOT" and "st-gates-pass" in f["detail"]
               for f in r["fails"]), r["fails"]


def test_home_without_any_date_label_still_fails():
    r = _ev(home=_home_ux01(_day(0), label=False), status=_status())
    assert "MISSING_ASOF" in _codes(r)


def test_home_label_disagreeing_with_the_shelf_is_still_behind():
    r = _ev(home=_home_ux01(_day(7)), status=_status())
    assert any(f["code"] == "SITE_BEHIND_SNAPSHOT" and f["detail"].startswith("home as-of")
               for f in r["fails"]), r["fails"]


def test_absent_ids_everywhere_are_named_as_a_stale_registry_not_client_render():
    r = _ev(status=None)   # /status/ не получена — источник page_not_fetched
    detail = [f["detail"] for f in r["fails"] if f["code"] == "COMPARISON_NOT_MEASURED"]
    assert len(detail) == 1, r["fails"]
    assert "реестр SITE_NUMBER_SOURCES отстал от живой разметки" in detail[0]
    assert "дорисовывает его клиентом" not in detail[0]
    assert "status#st-gates-pass:unmeasured:page_not_fetched" in detail[0]


def test_placeholder_keeps_the_client_render_wording():
    track = _track_ux01(_day(0)) + '<span id="tr-gates-pass">&mdash;</span>'
    r = _ev(track=track, status=None)
    detail = [f["detail"] for f in r["fails"] if f["code"] == "COMPARISON_NOT_MEASURED"]
    assert detail and "дорисовывает его клиентом" in detail[0], r["fails"]
