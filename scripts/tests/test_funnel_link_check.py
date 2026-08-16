#!/usr/bin/env python3
"""Тесты для scripts/funnel_link_check.py — сторож ссылок воронки.

Каждый тест — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на реальную аварию 2026-08-16 (карточка
`inbox-ves-poddomen-checkup-earn-defi-com-otdae`): весь поддомен `checkup.earn-defi.com`
отдавал 404 (`x-railway-fallback: true` — сервис не привязан к домену вовсе), с главной
публично вели битые ссылки, а job `site-freshness` краснел каждые 6 часов ВСЕГДА и потому
перестал быть сигналом — при том, что ADR-YL-011 опирается на него как на второй канал
тревоги, когда в Телеграм слать нельзя.

Сторож после починки обязан различать ДВА разных утверждения, и оба закреплены здесь:
  1. «снятый домен больше не объявлен частью воронки» — сама по себе недоступность
     `checkup.earn-defi.com` находкой НЕ является (иначе красный навсегда);
  2. «ссылка на снятый домен со страницы воронки — по-прежнему находка» — публичный 404
     остаётся публичным 404, и код возврата остаётся 1 (fail-CLOSED не ослаблен).

Сеть НЕ трогается: `_fetch` подменяется словарём-фикстурой. Pure stdlib.
Запуск: python3 -m pytest scripts/tests/test_funnel_link_check.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SCRIPTS_DIR.parent))

from scripts import funnel_link_check as flc  # noqa: E402

LANDING = flc.LANDING
CHECKUP = flc.CHECKUP

_OK_PAGE = "<html><head><title>SPA — a page</title></head><body></body></html>"


def _page(*hrefs: str) -> str:
    body = "".join(f'<a href="{h}">x</a>' for h in hrefs)
    return f"<html><head><title>SPA — a page</title></head><body>{body}</body></html>"


def _fake_fetch(responses: dict):
    """`_fetch`-двойник: URL → (код, тело). Незаявленный URL = 200 и пустая страница."""
    def _f(url: str, timeout: int = 15):
        return responses.get(url, (200, _OK_PAGE))
    return _f


class DecommissionedHostIsBroken(unittest.TestCase):
    """Ссылка на снятый хост — находка, и она НАЗЫВАЕТ причину, а не оставляет голый код."""

    def test_link_from_a_funnel_page_to_the_dead_checkup_is_a_finding(self):
        # Дословная авария 14–16.08: главная эмитит ссылку на checkup.earn-defi.com.
        responses = {f"{LANDING}/": (200, _page(f"{CHECKUP}/check"))}
        with patch.object(flc, "_fetch", _fake_fetch(responses)):
            res = flc.run()
        urls = [b["url"] for b in res["broken"]]
        self.assertIn(f"{CHECKUP}/check/", urls, f"мёртвая ссылка не попала в находки: {res}")
        self.assertFalse(res["all_resolve"])

    def test_the_finding_names_the_cause_instead_of_a_bare_status(self):
        responses = {f"{LANDING}/": (200, _page(f"{CHECKUP}/sample-report"))}
        with patch.object(flc, "_fetch", _fake_fetch(responses)):
            res = flc.run()
        gone = [b for b in res["broken"] if b.get("decommissioned")]
        self.assertEqual(len(gone), 1, f"ожидалась одна находка о снятом хосте: {res['broken']}")
        self.assertIn("not deployed", gone[0]["reason"])
        self.assertEqual(gone[0]["from"], f"{LANDING}/", "находка обязана назвать страницу-источник")

    def test_exit_code_stays_1_for_a_link_into_a_decommissioned_host(self):
        # fail-CLOSED не ослаблен: снятие домена из воронки не открыло путь к «✅ всё цело».
        responses = {f"{LANDING}/": (200, _page(f"{CHECKUP}/check"))}
        with patch.object(flc, "_fetch", _fake_fetch(responses)), \
                patch.object(sys, "argv", ["funnel_link_check.py"]):
            self.assertEqual(flc.main(), 1)

    def test_a_dead_host_is_judged_without_asking_the_network(self):
        # Ответ известен заранее: сторож не обязан ждать таймаута мёртвого домена, а сетевая
        # ошибка на нём не имеет права превратиться в «транзиент» (то есть в тишину).
        asked: list[str] = []

        def _spy(url: str, timeout: int = 15):
            asked.append(url)
            if url == f"{LANDING}/":
                return 200, _page(f"{CHECKUP}/check")
            if url.startswith(CHECKUP):
                return None, ""  # мёртвый хост: сеть молчит (сюда обращаться не должны вовсе)
            return 200, _OK_PAGE

        with patch.object(flc, "_fetch", _spy):
            res = flc.run()
        self.assertNotIn(f"{CHECKUP}/check/", asked, "снятый хост не должен опрашиваться по сети")
        self.assertEqual(res["network_errors"], [], "мёртвый хост не должен уходить в транзиенты")
        self.assertTrue([b for b in res["broken"] if b.get("decommissioned")])


class DecommissionedHostIsNotAFunnelSurface(unittest.TestCase):
    """Вторая половина: снятый домен больше НЕ объявлен воронкой (иначе красный навсегда)."""

    def test_checkup_is_not_crawled_as_a_funnel_page(self):
        self.assertNotIn(f"{CHECKUP}/", flc.FUNNEL_PAGES)

    def test_checkup_is_not_asserted_as_a_critical_route(self):
        self.assertNotIn(f"{CHECKUP}/check", flc.CRITICAL_ROUTES)

    def test_clean_site_with_no_links_to_the_dead_host_passes(self):
        # Ровно то состояние, ради которого чинилась воронка: ни одна страница на снятый домен
        # не ссылается ⇒ exit 0, и красный job снова что-то значит.
        with patch.object(flc, "_fetch", _fake_fetch({})), \
                patch.object(sys, "argv", ["funnel_link_check.py"]):
            self.assertEqual(flc.main(), 0)


class OrdinaryBreakageStillRed(unittest.TestCase):
    """Обратные контроли: снятие домена из воронки НЕ должно было ослабить остальное."""

    def test_a_plain_404_on_an_internal_link_is_still_a_finding(self):
        responses = {
            f"{LANDING}/": (200, _page("/packages", "/nowhere")),
            f"{LANDING}/nowhere/": (404, ""),
        }
        with patch.object(flc, "_fetch", _fake_fetch(responses)):
            res = flc.run()
        self.assertIn(f"{LANDING}/nowhere/", [b["url"] for b in res["broken"]])
        self.assertFalse(res["all_resolve"])

    def test_soft_404_is_still_a_finding(self):
        home_title = f"<html><head><title>SPA — {flc._HOME_TITLE_MARK}</title></head><body></body></html>"
        responses = {
            f"{LANDING}/": (200, _page("/ghost")),
            f"{LANDING}/ghost/": (200, home_title),
        }
        with patch.object(flc, "_fetch", _fake_fetch(responses)):
            res = flc.run()
        soft = [b for b in res["broken"] if b.get("soft_404")]
        self.assertEqual([b["url"] for b in soft], [f"{LANDING}/ghost/"])

    def test_network_error_is_reported_separately_from_a_broken_link(self):
        responses = {f"{LANDING}/": (200, _page("/packages")), f"{LANDING}/packages/": (None, "")}
        with patch.object(flc, "_fetch", _fake_fetch(responses)):
            res = flc.run()
        self.assertEqual([e["url"] for e in res["network_errors"]], [f"{LANDING}/packages/"])
        self.assertEqual(res["broken"], [], "транзиент не имеет права стать битой ссылкой")

    def test_unreachable_funnel_page_gives_exit_2_not_0(self):
        responses = {p: (None, "") for p in flc.FUNNEL_PAGES}
        with patch.object(flc, "_fetch", _fake_fetch(responses)), \
                patch.object(sys, "argv", ["funnel_link_check.py"]):
            self.assertEqual(flc.main(), 2)


class LandingHasNoLinksToTheDeadHost(unittest.TestCase):
    """Замер по ИСХОДНИКАМ сайта, а не по live-URL: сторож проверяет опубликованное, а этот
    тест — то, что уедет в публикацию следующим билдом (авария была видна в исходниках 14.08,
    а красный job молчал о причине)."""

    def test_no_source_file_under_landing_links_to_a_decommissioned_host(self):
        repo = Path(__file__).resolve().parents[2]
        landing_src = repo / "landing" / "src"
        if not landing_src.is_dir():  # пакет мог быть выложен без сайта
            self.skipTest("landing/src отсутствует в этом дереве")
        hosts = [h.split("//", 1)[1] for h in flc.DECOMMISSIONED_HOSTS]
        offenders = []
        for path in landing_src.rglob("*"):
            if not path.is_file() or path.suffix not in {".astro", ".jsx", ".ts", ".js", ".md", ".json"}:
                continue
            text = path.read_text("utf-8", "replace")
            for host in hosts:
                if f'href="https://{host}' in text or f"'https://{host}" in text or f'"https://{host}' in text:
                    offenders.append(f"{path.relative_to(repo)} → {host}")
        self.assertEqual(offenders, [], "исходники сайта снова ведут на снятый хост: " + "; ".join(offenders))


if __name__ == "__main__":
    unittest.main()
