"""test_site_publisher_stuck.py — «сборка ещё едет» и «публикатор ВСТАЛ» это ДВЕ беды (ADR-475).

Замер 2026-09-25, ради которого написан набор: живой earn-defi.com отдавал
`as of 2026-09-20` и APY **5.0 %** при живой ставке **4.9386 %**, а репозиторий
исправно коммитил свежий снимок ~4 раза в сутки (`as_of 2026-09-25`). Сторож
кустодиана краснел **17 прогонов подряд** — и ровно тем же кодом
`SITE_BEHIND_SNAPSHOT`, которым он краснеет, когда сборка ещё в пути и доедет
сама через десять минут. Одно имя на две беды: у первой лекарство «подождать»,
у второй — человек у Cloudflare Pages.

Каждый тест ниже — либо положительный контроль на эту аварию, либо контроль в
ОБРАТНУЮ сторону (беда без публикатора не имеет права называться его виной).

Часы приходят ВХОДОМ, и все даты фикстур вычислены от якоря `NOW`, который
передаётся `evaluate(now=...)`: набор не может покраснеть от того, что сдвинулся
календарь.
"""
# FROZEN-DATE-OK: injected-clock — якорь NOW уходит входом в evaluate(now=NOW), а все
# даты фикстур вычисляются ОТ НЕГО арифметикой timedelta (`_day(days_ago)`); стенных
# часов в файле нет ни одного вызова.
import datetime
import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "site_freshness_monitor", _ROOT / "scripts" / "site_freshness_monitor.py")
mon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mon)

NOW = datetime.datetime(2026, 9, 25, 17, 6, 45, tzinfo=datetime.timezone.utc)
PIN = "a" * 64


def _day(days_ago=0):
    """Дата в форме `YYYY-MM-DD`, вычисленная ОТ ЯКОРЯ, а не выписанная."""
    return (NOW - datetime.timedelta(days=days_ago)).date().isoformat()


# ── фикстуры формы, в которой авария 25.09 наблюдалась НА ЖИВОМ САЙТЕ ──────────
# На главной разбирается только `as of` (остальные числа на ней рендерятся
# клиентом), на /track-record — дни, APY и капитал. Именно такую тройку
# наблюдений дал отчёт прогона 36165025624, и набор воспроизводит её, а не
# удобную выдумку.
def _home(asof):
    return f'<span id="sl-asof">as of {asof}</span>'


def _track(asof, days=89, apy="5.0", equity="101,341"):
    return (f'<p id="tr-equity">${equity}</p><p id="tr-apy">~{apy}%</p>'
            f'<p id="tr-days-2">{days}</p>'
            f'<p id="tr-asof">static snapshot as of {asof}</p>')


def _snap(asof, days=94, apy=4.9386, gates=29, equity=101401.72):
    return {"as_of": asof, "real_track_days": days, "paper_apy_pct": apy,
            "gates_passed": gates, "end_equity": equity}


def _api(days=94, apy=4.9386, equity=101401.72, last=None):
    return {"evidenced_days": days, "paper_apy_pct": apy, "gates_passed": 29,
            "end_equity": equity, "last_bar": last or _day(0),
            "apy_source": "evidenced_chain"}


def _fossil_prev(days_ago=83):
    """Отчёт, который в CI лежит на месте «предыдущего прогона» (git-tracked, 4 июля)."""
    return {"ts": (NOW - datetime.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stale_48h": False}


def _ev(*, site_asof, snap_asof, api=None, prev=None, site_apy="5.0", site_days=89,
        home_asof=None):
    return mon.evaluate(
        snapshot=_snap(snap_asof),
        home_html=_home(home_asof if home_asof is not None else site_asof),
        track_html=_track(site_asof, days=site_days, apy=site_apy),
        api=api if api is not None else _api(),
        sitemap_statuses={"https://earn-defi.com/": 200},
        verifier_sha=PIN, pin_sha=PIN, now=NOW, prev_report=prev)


def _codes(report):
    return [f["code"] for f in report["fails"]]


# ── положительный контроль: авария 25.09 целиком ──────────────────────────────
def test_the_2026_09_25_frozen_publisher_is_named_as_its_own_harm():
    r = _ev(site_asof=_day(5), snap_asof=_day(0), prev=_fossil_prev())
    stuck = [f for f in r["fails"] if f["code"] == "PUBLISHER_STUCK"]
    assert len(stuck) == 1, _codes(r)
    assert stuck[0]["severity"] == "CRITICAL"
    assert r["publisher_stuck"] is True
    assert r["publish_lag_days"] == 5
    assert r["publisher_leg"] == "measured"
    # лекарство названо в самом тексте: чинить не здесь
    assert "Cloudflare Pages" in stuck[0]["detail"]
    assert _day(5) in stuck[0]["detail"] and _day(0) in stuck[0]["detail"]


def test_the_old_harm_keeps_its_old_name_and_nothing_is_weakened():
    """Новый код ДОБАВЛЯЕТСЯ к прежним находкам, а не заменяет их (инв. #16)."""
    r = _ev(site_asof=_day(5), snap_asof=_day(0), prev=_fossil_prev())
    codes = _codes(r)
    # Ровно те три находки, что дал живой прогон 36165025624: as-of на двух страницах
    # и завышенный APY. Дни при этом НЕ сравнивались ни разу: сверка дней читает
    # главную (`sl-day`), а главная их рендерит клиентом — на /track-record (`tr-days-2`)
    # число есть, но его этот сторож не смотрит. Замерено, названо, отдельная находка.
    assert codes.count("SITE_BEHIND_SNAPSHOT") == 2   # home as-of, track as-of
    assert "OVERSTATED_METRIC" in codes               # 5.0 % против живых 4.9386 %
    assert r["ok"] is False and r["site_overstated"] is True
    # прежняя политика стоп-крана НЕ изменилась: верный снимок не деградируется
    assert r["degrade_triggered"] is False and r["snapshot_overstated"] is False


def test_the_kill_rule_says_out_loud_that_it_could_not_reach_the_public():
    """Табличка честности едет ТЕМ ЖЕ публикатором — в этом режиме она инертна."""
    r = _ev(site_asof=_day(5), snap_asof=_day(0), prev=_fossil_prev())
    assert r["degrade_reaches_public"] is False
    assert r["degrade_reaches_public_reason"] == "publisher_stuck:plaque_would_not_publish"


def test_the_alert_text_carries_the_inert_kill_rule_line():
    """Сказано не в поле отчёта, а в ТЕКСТЕ, который читает владелец."""
    r = _ev(site_asof=_day(5), snap_asof=_day(0), prev=_fossil_prev())
    text = "\n".join(mon.alert_lines(r))
    assert "KILL-RULE INERT" in text
    assert "publisher_stuck:plaque_would_not_publish" in text
    assert "PUBLISHER_STUCK" in text                   # и сама находка тоже в тексте


def test_the_inert_line_is_absent_when_the_road_works():
    """Контроль в обратную сторону: строка не приклеивается к каждой тревоге."""
    r = _ev(site_asof=_day(0), snap_asof=_day(0), site_apy="9.9", site_days=94)
    assert r["ok"] is False                            # тревога есть (завышен APY)
    assert r["degrade_reaches_public"] is True
    assert "KILL-RULE INERT" not in "\n".join(mon.alert_lines(r))


def test_the_inert_line_is_absent_when_reach_is_merely_unmeasured():
    """`None` — не `False`: «неизвестно, доедет ли» не выдаётся за «не доедет»."""
    r = mon.evaluate(snapshot=_snap(_day(0)), home_html="<p>no label</p>",
                     track_html="<p>no label</p>", api=_api(),
                     sitemap_statuses={"https://earn-defi.com/": 200},
                     verifier_sha=PIN, pin_sha=PIN, now=NOW, prev_report=None)
    assert r["degrade_reaches_public"] is None
    assert "KILL-RULE INERT" not in "\n".join(mon.alert_lines(r))


# ── контроли в ОБРАТНУЮ сторону ───────────────────────────────────────────────
def test_a_transient_deploy_lag_is_not_called_a_stuck_publisher():
    """Одна проехавшая публикация — это «ещё едет», и имя у неё прежнее."""
    r = _ev(site_asof=_day(1), snap_asof=_day(0), prev=_fossil_prev())
    assert "PUBLISHER_STUCK" not in _codes(r)
    assert r["publisher_stuck"] is False
    assert r["publish_lag_days"] == 1
    assert "SITE_BEHIND_SNAPSHOT" in _codes(r)        # беда названа, но ДРУГИМ именем


def test_two_missed_publications_are_still_below_the_bound():
    r = _ev(site_asof=_day(2), snap_asof=_day(0), prev=_fossil_prev())
    assert r["publish_lag_days"] == 2 and r["publisher_stuck"] is False


def test_the_bound_itself_is_inclusive_and_fires_on_the_third_day():
    r = _ev(site_asof=_day(3), snap_asof=_day(0), prev=_fossil_prev())
    assert r["publish_lag_days"] == mon.PUBLISH_LAG_DAYS
    assert r["publisher_stuck"] is True


def test_a_stale_producer_is_not_the_publishers_fault():
    """Снимок протух САМ: публиковать нечего, значит публикатор не виноват.

    Это то условие, без которого сторож называл бы вставшим публикатора,
    которому не дали чего публиковать.
    """
    old = _day(6)
    r = _ev(site_asof=old, snap_asof=old, api=_api(last=old))
    codes = _codes(r)
    assert "PUBLISHER_STUCK" not in codes
    assert r["publisher_stuck"] is False and r["publish_lag_days"] == 0
    assert "STALE_SNAPSHOT" in codes                  # виноват производитель, и он назван
    assert r["snapshot_newer_than_site"] is False


def test_a_site_ahead_of_the_snapshot_is_not_stuck_either():
    """Отрицательный лаг (сайт новее нашего снимка) — не вина публикатора."""
    r = _ev(site_asof=_day(0), snap_asof=_day(4))
    assert r["publish_lag_days"] == -4 and r["publisher_stuck"] is False
    assert "PUBLISHER_STUCK" not in _codes(r)


def test_a_lag_below_the_bound_does_not_prove_the_road_works_either():
    """«Доедет ли табличка» при отставании на день — НЕ ИЗМЕРЕНО, а не «да».

    Слабость найдена мутацией собственной батареи: снятие условия «сайт отдаёт
    опубликованную дату» оставляло набор зелёным, то есть заявку «дорога работает»
    никто не проверял на сцене, где сайт всё-таки отстал. Доказательством рабочей
    дороги является только ДОСТАВЛЕННЫЙ снимок.
    """
    r = _ev(site_asof=_day(1), snap_asof=_day(0))
    assert r["publisher_stuck"] is False
    assert r["degrade_reaches_public"] is None
    assert r["degrade_reaches_public_reason"] == "unmeasured:lag_below_the_publisher_bound"


def test_a_caught_up_site_proves_the_road_works():
    r = _ev(site_asof=_day(0), snap_asof=_day(0), site_apy="4.9", site_days=94)
    assert r["publish_lag_days"] == 0 and r["publisher_stuck"] is False
    assert r["degrade_reaches_public"] is True
    assert r["degrade_reaches_public_reason"] == "site_serves_the_published_as_of"


# ── третий исход: не измерено ≠ чисто и ≠ встал ───────────────────────────────
def test_a_page_without_an_as_of_label_is_unmeasured_not_a_verdict():
    r = mon.evaluate(snapshot=_snap(_day(0)), home_html="<p>no label</p>",
                     track_html="<p>no label</p>", api=_api(),
                     sitemap_statuses={"https://earn-defi.com/": 200},
                     verifier_sha=PIN, pin_sha=PIN, now=NOW, prev_report=None)
    assert r["publisher_leg"] == "unmeasured:no_as_of_label_on_the_live_page"
    assert r["publisher_stuck"] is False              # не измерено — НЕ обвинение
    assert r["publish_lag_days"] is None              # и НЕ нуль
    assert "MISSING_ASOF" in _codes(r)                # и НЕ тишина
    assert r["degrade_reaches_public"] is None        # доедет ли табличка — неизвестно
    assert r["degrade_reaches_public_reason"].startswith("unmeasured:")


def test_a_snapshot_without_an_as_of_is_its_own_unmeasured_reason():
    r = mon.evaluate(snapshot={"real_track_days": 94, "paper_apy_pct": 4.9386},
                     home_html=_home(_day(5)), track_html=_track(_day(5)), api=_api(),
                     sitemap_statuses={"https://earn-defi.com/": 200},
                     verifier_sha=PIN, pin_sha=PIN, now=NOW, prev_report=None)
    assert r["publisher_leg"] == "unmeasured:snapshot_has_no_as_of"
    assert r["publisher_stuck"] is False and r["publish_lag_days"] is None


def test_an_unparseable_site_date_names_both_operands():
    r = mon.evaluate(snapshot=_snap(_day(0)), home_html=_home("не-дата"),
                     track_html=_track("не-дата"), api=_api(),
                     sitemap_statuses={"https://earn-defi.com/": 200},
                     verifier_sha=PIN, pin_sha=PIN, now=NOW, prev_report=None)
    # `as of не-дата` разбору страницы не подходит вовсе ⇒ метки нет
    assert r["publisher_leg"].startswith("unmeasured:")
    assert r["publisher_stuck"] is False


def test_the_oldest_of_the_two_pages_decides():
    """Одна страница обновилась, вторая нет — судим по ТОЙ, что отстала сильнее."""
    r = _ev(site_asof=_day(5), snap_asof=_day(0), home_asof=_day(0))
    assert r["site_as_of"] == _day(5) and r["publish_lag_days"] == 5
    assert r["publisher_stuck"] is True


# ── фоссил вместо предыдущего прогона ─────────────────────────────────────────
def test_the_previous_report_is_named_a_fossil_instead_of_read_as_fresh():
    """«Протухло на ДВУХ прогонах подряд» читало вторым операндом отчёт из 4 июля.

    В CI `data/site_freshness_report.json` берётся из репозитория (job имеет
    `contents: read` и обратно его не коммитит), поэтому это НЕ предыдущий прогон.
    Поведение стоп-крана не менялось; изменилось то, что фоссил теперь НАЗВАН.
    """
    r = _ev(site_asof=_day(5), snap_asof=_day(0), prev=_fossil_prev(days_ago=83))
    assert r["prev_run_leg"].startswith("unmeasured:previous_report_is_a_fossil:")
    assert r["prev_report_age_h"] is not None and r["prev_report_age_h"] > 24


def test_a_genuinely_previous_report_is_measured():
    prev = {"ts": (NOW - datetime.timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stale_48h": False}
    r = _ev(site_asof=_day(1), snap_asof=_day(0), prev=prev)
    assert r["prev_run_leg"] == "measured"
    assert 5.0 < r["prev_report_age_h"] < 7.0


def test_a_two_hour_old_report_across_midnight_is_still_the_previous_run():
    """Возраст отчёта меряется ВРЕМЕНЕМ, а не датой.

    Огрубление до даты (`[:10]`, как в `_hours_since`) объявило бы фоссилом прогон,
    прошедший два часа назад по ту сторону полуночи, — то есть назвало бы честный
    операнд негодным. Ошибка в сторону «не измерено» тоже ошибка: она снимает
    вторую половину стоп-крана там, где та работает.
    """
    midnight_ish = NOW.replace(hour=0, minute=30)
    prev = {"ts": (midnight_ish - datetime.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stale_48h": False}
    r = mon.evaluate(snapshot=_snap(midnight_ish.date().isoformat()),
                     home_html=_home(midnight_ish.date().isoformat()),
                     track_html=_track(midnight_ish.date().isoformat(), days=94, apy="4.9"),
                     api=_api(last=midnight_ish.date().isoformat()),
                     sitemap_statuses={"https://earn-defi.com/": 200},
                     verifier_sha=PIN, pin_sha=PIN, now=midnight_ish, prev_report=prev)
    assert r["prev_run_leg"] == "measured", r["prev_run_leg"]
    assert 1.5 < r["prev_report_age_h"] < 2.5


def test_no_previous_report_is_its_own_reason_not_a_fossil_and_not_measured():
    r = _ev(site_asof=_day(1), snap_asof=_day(0), prev=None)
    assert r["prev_run_leg"] == "unmeasured:no_previous_report"
    assert r["prev_report_age_h"] is None


def test_an_unparseable_previous_ts_is_unmeasured_with_its_own_name():
    r = _ev(site_asof=_day(1), snap_asof=_day(0), prev={"ts": "вчера", "stale_48h": False})
    assert r["prev_run_leg"] == "unmeasured:previous_report_ts_unparseable"
    assert r["prev_report_age_h"] is None


def test_the_two_run_kill_rule_behaviour_is_unchanged_by_this_work():
    """Инв. #16: ветка «48 ч на двух прогонах» работает ровно как до правки."""
    old = _day(4)
    prev = {"ts": (NOW - datetime.timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stale_48h": True}
    r = _ev(site_asof=old, snap_asof=old, api=_api(last=old), prev=prev)
    assert r["stale_48h"] is True
    assert r["degrade_triggered"] is True and r["degrade_reason"] == "STALE_48H_TWO_RUNS"


# ── контроль на контроль: мера обязана быть в ДНЯХ, а не в часах ──────────────
def test_the_same_one_day_lag_reads_the_same_at_any_hour_of_the_day():
    """Часовой порог переходил бы один и тот же лаг по времени суток — дни не переходят."""
    for hour in (1, 9, 17, 23):
        now = NOW.replace(hour=hour)
        r = mon.evaluate(snapshot=_snap((now - datetime.timedelta(days=0)).date().isoformat()),
                         home_html=_home((now - datetime.timedelta(days=1)).date().isoformat()),
                         track_html=_track((now - datetime.timedelta(days=1)).date().isoformat()),
                         api=_api(last=now.date().isoformat()),
                         sitemap_statuses={"https://earn-defi.com/": 200},
                         verifier_sha=PIN, pin_sha=PIN, now=now, prev_report=None)
        assert r["publish_lag_days"] == 1, hour
        assert r["publisher_stuck"] is False, hour
        # часы РЯДОМ и меняются — именно поэтому вердикт строится не на них
        assert r["site_as_of_age_h"] is not None


def test_the_visitor_facing_age_is_reported_in_hours_as_well():
    r = _ev(site_asof=_day(5), snap_asof=_day(0))
    assert r["site_as_of_age_h"] is not None
    assert 120 <= r["site_as_of_age_h"] <= 144      # пять суток плюс время суток
    assert r["site_as_of"] == _day(5)
