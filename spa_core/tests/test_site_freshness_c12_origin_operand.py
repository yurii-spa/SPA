"""C12 (ADR-580, RM-TRUTH-01): операнд сверки «отстал ли посетитель» — ORIGIN, не
прод-локальный файл.

Замер, по которому написан набор: `docs/rm_truth/A3_product.md` §4 / `REVIEW_1.md`
claim 4. `site_freshness_monitor` до этой правки читал `landing/src/data/site_numbers.json`
из РАБОЧЕГО ДЕРЕВА (прод-копия, 04.10) и сравнивал с ней живую страницу — хотя у origin
(01.10) СВОЙ такт, и именно ИЗ origin Cloudflare строит то, что видит посетитель.
Прод-локальная полка — артефакт сборки, не операнд сторожа (C12).

Каждый тест ниже — либо положительный контроль на этот класс (операнд ДОЛЖЕН быть
origin), либо контроль в обратную сторону (беда без доставки — другая беда, не
«Cloudflare Pages», и получает СВОЙ код).
"""
from __future__ import annotations

import datetime
import importlib.util
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "site_freshness_monitor_c12", _ROOT / "scripts" / "site_freshness_monitor.py")
mon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mon)

# FROZEN-DATE-OK: injected-clock — every staleness comparison goes through
# mon.evaluate(..., now=NOW) / mon._publisher_stuck_push(..., now=NOW), and every
# fixture date is _day(N) (NOW ± N days) or a NOW-derived strftime, so both sides
# of every comparison share the same anchor. The three bare "2026-10-05T12:00:00Z"
# literals (report["ts"] in the _alert()-only fixtures) are never read by `_alert`
# for any age/staleness decision — grepped: `_alert`'s body has no reference to
# the "ts" key at all — so they cannot flip this test when the calendar moves.
NOW = datetime.datetime(2026, 10, 5, 12, 0, 0, tzinfo=datetime.timezone.utc)
PIN = "a" * 64


def _day(days_ago=0):
    return (NOW - datetime.timedelta(days=days_ago)).date().isoformat()


def _home(asof):
    return f'<span id="sl-asof">as of {asof}</span>'


def _track(asof, days=104, apy="4.9"):
    return (f'<p id="tr-equity">$101,000</p><p id="tr-apy">~{apy}%</p>'
            f'<p id="tr-days-2">{days}</p>'
            f'<p id="tr-asof">static snapshot as of {asof}</p>')


def _snap(asof, days=104, apy=4.9032):
    return {"as_of": asof, "real_track_days": days, "paper_apy_pct": apy,
            "gates_passed": 29, "end_equity": 101000.0}


def _api(days=104, apy=4.9032):
    return {"evidenced_days": days, "paper_apy_pct": apy, "gates_passed": 29,
            "end_equity": 101000.0, "last_bar": _day(0), "apy_source": "evidenced_chain"}


def _shelf(asof, next_pub=None, apy=4.9032, days=104):
    return {"measured_at": asof, "published_at": asof, "cadence": "weekly",
            "next_publication": next_pub if next_pub is not None else _day(-7),
            "headline": {"apy": {"value": apy}, "evidenced_days": {"value": days},
                         "gates": {"passed": 29, "total": 29}}}


def _codes(report):
    return [f["code"] for f in report["fails"]]


def _ev(*, site_asof, origin_shelf=None, shelf_fetch_leg=None, local_shelf=None,
        snap_asof=None, prev=None):
    snap_asof = snap_asof or site_asof
    return mon.evaluate(
        snapshot=_snap(snap_asof), home_html=_home(site_asof), track_html=_track(site_asof),
        api=_api(), sitemap_statuses={"https://earn-defi.com/": 200},
        verifier_sha=PIN, pin_sha=PIN, now=NOW, prev_report=prev,
        site_numbers=origin_shelf, shelf_fetch_leg=shelf_fetch_leg,
        local_site_numbers=local_shelf)


class TheOperandIsOriginNotTheWorkingTree(unittest.TestCase):
    """Положительный контроль C12: прод-локальная полка НЕ операнд сверки с посетителем."""

    def test_a_fresher_local_shelf_never_creates_a_mismatch_against_origin(self):
        """Было бы дефектом (пред-C12): сравнить посетителя с ПРОД-ЛОКАЛЬНОЙ полкой
        04.10, когда origin и посетитель оба честно на 01.10 — и закричать зря.

        Посетитель читает ровно то, что опубликовал origin (01.10) — значит лаг
        НОЛЬ, и это измерено. Более свежая НЕДОСТАВЛЕННАЯ прод-локальная копия
        (04.10) не имеет права участвовать в этом вопросе вовсе.
        """
        origin = _shelf(_day(4), next_pub=_day(-3))        # то, что видел посетитель
        local = _shelf(_day(0), next_pub=_day(3))          # свежее, но НЕ доставлено
        r = _ev(site_asof=_day(4), origin_shelf=origin, local_shelf=local)
        self.assertNotIn("PUBLISHER_STUCK", _codes(r), r["fails"])
        self.assertEqual(r["publisher_leg"], "measured")
        self.assertEqual(r["publish_lag_days"], 0)
        # Прод-локальная свежесть НЕ просочилась в operand сверки с посетителем —
        # `shelf_as_of` в отчёте обязан быть ORIGIN'ным, не прод-локальным.
        self.assertEqual(r["shelf_as_of"], _day(4))

    def test_publisher_stuck_fires_from_the_origin_lag_not_the_local_one(self):
        """Origin сам отстал от посетителя — ЭТО и есть PUBLISHER_STUCK, вне
        зависимости от того, что лежит в прод-локальном дереве."""
        origin = _shelf(_day(0), next_pub=_day(-7))        # origin УЖЕ свежий
        local = _shelf(_day(0), next_pub=_day(-7))         # не важно для этого вопроса
        r = _ev(site_asof=_day(5), origin_shelf=origin, local_shelf=local, snap_asof=_day(0),
               prev={"ts": (NOW - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "stale_48h": False})
        self.assertIn("PUBLISHER_STUCK", _codes(r), r["fails"])
        self.assertEqual(r["publish_lag_days"], 5)


class ShelfNeverDeliveredIsItsOwnDiagnosis(unittest.TestCase):
    """C12: «на origin вообще нет» — другая беда, чем «публикатор встал», и
    НИКОГДА не называет Cloudflare виновным."""

    def test_shelf_not_on_origin_with_local_data_ready_is_a_named_delivery_gap(self):
        local = _shelf(_day(0), next_pub=_day(7))
        r = _ev(site_asof=_day(0), origin_shelf=None, shelf_fetch_leg="not_on_origin",
               local_shelf=local)
        codes = _codes(r)
        self.assertIn("SHELF_NOT_ON_ORIGIN", codes, codes)
        found = next(f for f in r["fails"] if f["code"] == "SHELF_NOT_ON_ORIGIN")
        self.assertEqual(found["severity"], "CRITICAL")
        # Cloudflare НАЗВАН — но чтобы ЕГО ЖЕ СНЯТЬ с подозреваемых, не обвинить:
        # лекарство ВНУТРИ репозитория (завести доставку), CF Pages тут ни при чём.
        self.assertIn("ВНУТРИ репозитория", found["detail"])
        self.assertIn("ни при чём", found["detail"])
        self.assertIn("доставк", found["detail"].lower())
        # PUBLISHER_STUCK не имеет права сработать вовсе — операнда для лага нет.
        self.assertNotIn("PUBLISHER_STUCK", codes, codes)

    def test_git_unavailable_is_unmeasured_not_a_delivery_verdict(self):
        """git/сеть недоступны — третий исход (инв. #17), а не «не доставлена»."""
        r = _ev(site_asof=_day(0), origin_shelf=None,
               shelf_fetch_leg="unmeasured:git_unavailable:TimeoutExpired",
               local_shelf=_shelf(_day(0)))
        codes = _codes(r)
        self.assertNotIn("SHELF_NOT_ON_ORIGIN", codes, codes)
        self.assertNotIn("PUBLISHER_STUCK", codes, codes)
        self.assertTrue(r["shelf_leg"].startswith("unmeasured:"))
        self.assertNotIn("unmeasured:unmeasured:", r["shelf_leg"], "причина продублирована")

    def test_not_on_origin_without_local_data_either_still_names_itself(self):
        """Ничего не посчитано НИ ГДЕ — находка остаётся, но ДРУГИМ текстом: не
        «producer готов, доставки нет», а «начинать ещё нечем» (третий исход,
        инв. #17, а не растворение в молчании)."""
        r = _ev(site_asof=_day(0), origin_shelf=None, shelf_fetch_leg="not_on_origin",
               local_shelf=None)
        codes = _codes(r)
        self.assertIn("SHELF_NOT_ON_ORIGIN", codes, codes)
        found = next(f for f in r["fails"] if f["code"] == "SHELF_NOT_ON_ORIGIN")
        self.assertIn("ни локально", found["detail"])


class PublisherStuckRemedyNamesTheConfirmedCause(unittest.TestCase):
    """Когда PUBLISHER_STUCK реально срабатывает, origin ПО ОПРЕДЕЛЕНИЮ прочитан
    (`shelf_leg == "measured"`) — значит доставка состоялась, и текст обязан это
    сказать, а не просто кивнуть на Cloudflare по привычке."""

    def test_remedy_states_delivery_happened_before_blaming_the_build(self):
        origin = _shelf(_day(0), next_pub=_day(-7))
        r = _ev(site_asof=_day(5), origin_shelf=origin, local_shelf=origin, snap_asof=_day(0),
               prev={"ts": (NOW - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "stale_48h": False})
        found = next(f for f in r["fails"] if f["code"] == "PUBLISHER_STUCK")
        self.assertIn("Cloudflare Pages", found["detail"])
        self.assertIn("СОСТОЯЛАСЬ", found["detail"])


class PublisherStuckPushIsEdgeTriggered(unittest.TestCase):
    """C12 / REVIEW_1 remediation item 4: ОДНА карточка на инцидент, не сообщение
    каждые 6 часов. Дедуп делегирован `push_policy` (не изобретён заново)."""

    def _report(self, *, stuck, site_asof=None, shelf_asof=None, publisher_leg="measured"):
        return {"publisher_stuck": stuck, "site_as_of": site_asof or _day(5),
                "shelf_as_of": shelf_asof or _day(0), "publisher_leg": publisher_leg,
                "fails": [{"code": "PUBLISHER_STUCK", "severity": "CRITICAL",
                          "detail": "x"}] if stuck else []}

    def test_a_stuck_report_calls_push_critical_with_the_whitelisted_key(self):
        fake = mock.Mock()
        fake.push_critical.return_value = True
        with mock.patch.object(mon, "_push_policy", return_value=fake):
            out = mon._publisher_stuck_push(self._report(stuck=True), now=NOW)
        self.assertTrue(out["routed"])
        self.assertEqual(fake.push_critical.call_args.args[0], "site_publisher_stuck")
        self.assertEqual(fake.push_critical.call_args.args[1], "CRITICAL")
        self.assertIn("dedup_key", fake.push_critical.call_args.kwargs)

    def test_two_runs_of_the_same_incident_share_one_dedup_key(self):
        """ТА ЖЕ пара дат — push_policy увидит ОДИН и тот же `dedup_key` и промолчит
        сам (его собственный edge-trigger, не переизобретённый здесь)."""
        fake = mock.Mock()
        fake.push_critical.return_value = True
        with mock.patch.object(mon, "_push_policy", return_value=fake):
            mon._publisher_stuck_push(self._report(stuck=True), now=NOW)
            mon._publisher_stuck_push(self._report(stuck=True), now=NOW)
        k1 = fake.push_critical.call_args_list[0].kwargs["dedup_key"]
        k2 = fake.push_critical.call_args_list[1].kwargs["dedup_key"]
        self.assertEqual(k1, k2)

    def test_a_different_incident_gets_a_different_dedup_key(self):
        fake = mock.Mock()
        fake.push_critical.return_value = True
        with mock.patch.object(mon, "_push_policy", return_value=fake):
            mon._publisher_stuck_push(self._report(stuck=True, site_asof=_day(5)), now=NOW)
            mon._publisher_stuck_push(self._report(stuck=True, site_asof=_day(9)), now=NOW)
        k1 = fake.push_critical.call_args_list[0].kwargs["dedup_key"]
        k2 = fake.push_critical.call_args_list[1].kwargs["dedup_key"]
        self.assertNotEqual(k1, k2)

    def test_a_resolved_report_calls_resolve_not_push_critical(self):
        fake = mock.Mock()
        fake.resolve.return_value = False
        with mock.patch.object(mon, "_push_policy", return_value=fake):
            out = mon._publisher_stuck_push(self._report(stuck=False), now=NOW)
        fake.resolve.assert_called_once()
        self.assertEqual(fake.resolve.call_args.args[0], "site_publisher_stuck")
        fake.push_critical.assert_not_called()
        self.assertTrue(out["routed"])

    def test_push_policy_unavailable_is_named_not_silently_dropped(self):
        with mock.patch.object(mon, "_push_policy", return_value=None):
            out = mon._publisher_stuck_push(self._report(stuck=True), now=NOW)
        self.assertFalse(out["routed"])
        self.assertEqual(out["reason"], "push_policy_unavailable")

    def test_a_push_policy_exception_never_crashes_the_run(self):
        fake = mock.Mock()
        fake.push_critical.side_effect = RuntimeError("boom")
        with mock.patch.object(mon, "_push_policy", return_value=fake):
            out = mon._publisher_stuck_push(self._report(stuck=True), now=NOW)
        self.assertFalse(out["routed"])
        self.assertIn("boom", out["error"])

    def test_site_publisher_stuck_is_on_the_tier1_whitelist(self):
        """Иначе `push_critical` демотировал бы КАЖДОЕ событие в дайджест молча —
        владелец не увидел бы PUBLISHER_STUCK вовсе ни одним каналом."""
        fake_path = _ROOT / "spa_core" / "telegram" / "push_policy.py"
        pp_spec = importlib.util.spec_from_file_location("pp_c12", fake_path)
        pp = importlib.util.module_from_spec(pp_spec)
        pp_spec.loader.exec_module(pp)
        self.assertIn("site_publisher_stuck", pp.TIER1_WHITELIST)


class RawChannelDoesNotDuplicateARoutedPublisherStuck(unittest.TestCase):
    """`_alert` не повторяет PUBLISHER_STUCK сырым каналом, когда push_policy его
    уже принял в ЭТОМ прогоне — иначе владелец получил бы беду ДВА РАЗА."""

    def test_a_routed_publisher_stuck_alone_sends_nothing_raw(self):
        report = {"ok": False, "n_fails": 1, "ts": "2026-10-05T12:00:00Z",
                  "fails": [{"code": "PUBLISHER_STUCK", "severity": "CRITICAL", "detail": "x"}],
                  "publisher_stuck_push": {"routed": True, "sent": True},
                  "degrade_triggered": False, "degrade_reaches_public": True}
        out = mon._alert(report)
        self.assertFalse(out["attempted"])
        self.assertEqual(out["reason"], "handled_via_edge_trigger")

    def test_an_unrouted_publisher_stuck_still_uses_the_raw_channel(self):
        """push_policy недоступен в этом прогоне ⇒ доставка важнее дедупа: алерт
        идёт сырым каналом ровно как до этой правки."""
        sent = []

        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def read(self_inner):
                import json as _json
                return _json.dumps({"ok": True, "result": {"message_id": 1}}).encode()

        def _urlopen(req, *a, **kw):
            sent.append(req)
            return _Resp()

        report = {"ok": False, "n_fails": 1, "ts": "2026-10-05T12:00:00Z",
                  "fails": [{"code": "PUBLISHER_STUCK", "severity": "CRITICAL", "detail": "x"}],
                  "publisher_stuck_push": {"routed": False, "reason": "push_policy_unavailable"},
                  "degrade_triggered": False, "degrade_reaches_public": True}
        with mock.patch("spa_core.alerts.telegram_client.guard_outbound", return_value=None), \
             mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN_SPA": "t",
                                            "TELEGRAM_CHAT_ID_SPA": "c",
                                            "SPA_LIVE_ROOT": str(_ROOT)}), \
             mock.patch.object(mon.urllib.request, "urlopen", _urlopen):
            out = mon._alert(report)
        self.assertTrue(out["sent"], "недоступный push_policy не имеет права молчать совсем")
        self.assertEqual(len(sent), 1)

    def test_a_routed_publisher_stuck_alongside_another_fail_still_reports_the_other(self):
        """Дедуп касается ТОЛЬКО PUBLISHER_STUCK — соседняя беда обязана дойти."""
        sent = []

        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def read(self_inner):
                import json as _json
                return _json.dumps({"ok": True, "result": {"message_id": 1}}).encode()

        def _urlopen(req, *a, **kw):
            import json as _json
            sent.append(_json.loads(req.data.decode())["text"])
            return _Resp()

        report = {"ok": False, "n_fails": 2, "ts": "2026-10-05T12:00:00Z",
                  "fails": [{"code": "PUBLISHER_STUCK", "severity": "CRITICAL", "detail": "x"},
                           {"code": "STALE_API", "severity": "FAIL", "detail": "y"}],
                  "publisher_stuck_push": {"routed": True, "sent": True},
                  "degrade_triggered": False, "degrade_reaches_public": True}
        with mock.patch("spa_core.alerts.telegram_client.guard_outbound", return_value=None), \
             mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN_SPA": "t",
                                            "TELEGRAM_CHAT_ID_SPA": "c",
                                            "SPA_LIVE_ROOT": str(_ROOT)}), \
             mock.patch.object(mon.urllib.request, "urlopen", _urlopen):
            out = mon._alert(report)
        self.assertTrue(out["sent"])
        # `_alert` переводит тело на простой русский (`_humanize_body`) — литеральный
        # код STALE_API в сообщении не остаётся, остаётся его перевод.
        self.assertIn("данные API устарели", sent[0])
        self.assertNotIn("PUBLISHER_STUCK", sent[0], "уже сказано edge-triggered каналом")


if __name__ == "__main__":
    unittest.main()
