# LLM_FORBIDDEN
"""Проба «владелец может управлять системой через Telegram» (ADR-662, цикл #807).

Каждый тест — положительный контроль на КОНКРЕТНОЕ порванное звено, и звено
названо в имени теста. Обратная сторона проверяется тоже: на исправном маячке
проба говорит `satisfied`, а не молчит.

**Часы — ВХОД, а не окружение.** Проба принимает `now=`, и обе стороны сцены
(отметка маячка и «сейчас») закреплены одним якорем, выведенным ОТ этого
аргумента. Литеральной даты в файле нет вовсе: якорь сцены вычисляется из
`now`, который тест и задаёт, — поэтому прогон этого файла не зависит ни от
календаря, ни от длительности прогона.

Пометки `FROZEN-DATE-OK` здесь нет НАМЕРЕННО, и это не недосмотр: сторож
замороженных дат ищет маркер в КОММЕНТАРИИ и ловит датовые СТРОКИ, а здесь
даты-строки нет вовсе — якорь собран конструктором `datetime(...)` и целиком
выводится из аргумента `now`. Пометка, которую сторож не читает, выглядела бы
решением на протоколе, не будучи им.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.monitoring import card_acceptance as ca
from spa_core.telegram import alert_actions

#: Якорь сцены. Он не литеральная дата календаря, а произвольный момент, от
#: которого выводятся ВСЕ отметки сцены; проба получает его же аргументом.
NOW = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)


def _beacon(tmp: str, *, age_s: float = 30.0,
            capabilities=("alert_actions", "owner_decisions"),
            stamp: object = None, body: object = None) -> str:
    path = Path(tmp, "telegram_bot_capabilities.json")
    if body is not None:
        path.write_text(json.dumps(body) if not isinstance(body, str) else body)
        return str(path)
    doc = {"schema_version": 1, "source": "telegram_bot", "pid": 1,
           "capabilities": list(capabilities)}
    if stamp is not None:
        doc["updated_at"] = stamp
    else:
        doc["updated_at"] = (NOW - timedelta(seconds=age_s)).isoformat()
    path.write_text(json.dumps(doc))
    return str(path)


def _probe(path, arg=None, now=NOW):
    return ca._probe_owner_control_plane_reachable(arg, now=now, beacon_path=path)


class TheHealthyBeacon(unittest.TestCase):
    """Обратная сторона: на исправном контуре проба обязана отвечать, а не молчать."""

    def test_a_fresh_beacon_declaring_the_capability_is_satisfied(self):
        with tempfile.TemporaryDirectory() as tmp:
            verdict, why = _probe(_beacon(tmp))
            self.assertEqual(ca.SATISFIED, verdict, why)
            self.assertIn("может управлять", why)

    def test_a_named_capability_is_measured_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            verdict, _ = _probe(_beacon(tmp), arg="owner_decisions")
            self.assertEqual(ca.SATISFIED, verdict)


class TheThresholdIsTheBUTTONSOneNotTheWatchdogs(unittest.TestCase):
    """Порванное звено: сравнять порог кнопок с порогом живости сторожа.

    Ровно эта правка возвращала «⚠️ Кнопки сейчас недоступны» на КАЖДОМ
    перезапуске бота (ADR-400); порог кнопок — 6 ч, порог сторожа — 300 с, и это
    два разных вопроса.
    """

    def test_a_beacon_ten_minutes_old_is_still_satisfied(self):
        self.assertGreater(alert_actions.BEACON_MAX_AGE_S, 600,
                           "предпосылка сцены: окно кнопок шире десяти минут")
        with tempfile.TemporaryDirectory() as tmp:
            verdict, why = _probe(_beacon(tmp, age_s=600))
            self.assertEqual(ca.SATISFIED, verdict, why)

    def test_the_threshold_is_read_from_the_module_and_not_reprinted(self):
        """Проба обязана ехать за порогом модуля сама: перепечатанное число
        разошлось бы с ним МОЛЧА."""
        with tempfile.TemporaryDirectory() as tmp:
            path = _beacon(tmp, age_s=alert_actions.BEACON_MAX_AGE_S - 60)
            self.assertEqual(ca.SATISFIED, _probe(path)[0])
            path = _beacon(tmp, age_s=alert_actions.BEACON_MAX_AGE_S + 60)
            verdict, why = _probe(path)
            self.assertEqual(ca.NOT_SATISFIED, verdict)
            self.assertIn("порог кнопок", why)


class ThirdOutcomeIsNotZeroAndNotSuccess(unittest.TestCase):
    """«Не измерено» обязано быть отличимо и от «кнопки есть», и от «их нет»."""

    def test_a_missing_beacon_is_unmeasured(self):
        with tempfile.TemporaryDirectory() as tmp:
            verdict, why = _probe(str(Path(tmp, "nope.json")))
            self.assertEqual(ca.UNMEASURED, verdict)
            self.assertIn("не прочитан", why)

    def test_an_unparsable_beacon_is_unmeasured(self):
        with tempfile.TemporaryDirectory() as tmp:
            verdict, why = _probe(_beacon(tmp, body="{не json"))
            self.assertEqual(ca.UNMEASURED, verdict)

    def test_a_beacon_that_is_not_an_object_is_unmeasured(self):
        with tempfile.TemporaryDirectory() as tmp:
            verdict, why = _probe(_beacon(tmp, body=[1, 2]))
            self.assertEqual(ca.UNMEASURED, verdict)
            self.assertIn("не объект", why)

    def test_a_beacon_without_a_stamp_is_unmeasured_and_not_fresh(self):
        """Порванное звено: отсутствующая отметка, прочитанная как «свежо»."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "b.json")
            path.write_text(json.dumps({"capabilities": ["alert_actions"]}))
            verdict, why = _probe(str(path))
            self.assertEqual(ca.UNMEASURED, verdict)
            self.assertIn("НЕ ИЗМЕРЕН", why)

    def test_an_unparsable_stamp_is_unmeasured(self):
        with tempfile.TemporaryDirectory() as tmp:
            verdict, why = _probe(_beacon(tmp, stamp="вчера"))
            self.assertEqual(ca.UNMEASURED, verdict)
            self.assertIn("не разобрана", why)


class TheCapabilityIsComparedExactly(unittest.TestCase):
    """Порванное звено: суждение по ПОДСТРОКЕ (ADR-333)."""

    def test_a_prefix_of_a_declared_capability_does_not_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            verdict, why = _probe(_beacon(tmp), arg="alert_action")
            self.assertEqual(ca.NOT_SATISFIED, verdict)
            self.assertIn("НЕ объявлено", why)

    def test_an_empty_capability_list_is_not_satisfied_and_not_unmeasured(self):
        """Пустой список умений есть ОТВЕТ («кнопок не предложат»), а не
        отсутствие замера: маячок прочитан, отметка есть."""
        with tempfile.TemporaryDirectory() as tmp:
            verdict, why = _probe(_beacon(tmp, capabilities=()))
            self.assertEqual(ca.NOT_SATISFIED, verdict)

    def test_a_capability_field_of_the_wrong_TYPE_makes_the_probe_REFUSE(self):
        """НАСТОЯЩАЯ сцена расхождения — и попутная находка о гейте кнопок.

        Если `capabilities` окажется СТРОКОЙ, а не списком, то
        `alert_actions.handler_available` проверяет `c in declared` по
        ПОДСТРОКЕ и отвечает «кнопки есть»; проба нестроковый список читает как
        пустой и отвечает «нет». Два ответа противоречат друг другу, и выдать
        любой из них за замер нельзя ⇒ `unmeasured` с названной причиной.

        Это не умозрительная тонкость: форма есть fail-OPEN у гейта, который
        вешает кнопки владельцу. Сегодня писатель маячка всегда пишет список,
        поэтому ветка недостижима в проде — находка НАЗВАНА карточкой
        (`inbox-geit-knopok-sudit-po-podstroke-esli-umen`), а не починена прицепом
        к чужому предмету: смешать два разбора в одном пуше запрещено.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "b.json")
            path.write_text(json.dumps({
                "updated_at": NOW.isoformat(), "capabilities": "alert_actions"}))
            verdict, why = _probe(str(path))
            self.assertEqual(ca.UNMEASURED, verdict)
            self.assertIn("расходятся", why)
            self.assertTrue(alert_actions.handler_available(
                now=NOW, beacon_path=str(path)),
                "предпосылка находки: гейт кнопок на строке отвечает ДА")


class TheFutureStampIsNotFreshness(unittest.TestCase):
    """Отметка из БУДУЩЕГО — не «очень свежо»: окно двустороннее."""

    def test_a_stamp_far_in_the_future_is_not_satisfied(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _beacon(
                tmp, age_s=-(alert_actions.BEACON_FUTURE_TOLERANCE_S + 60))
            self.assertEqual(ca.NOT_SATISFIED, _probe(path)[0])

    def test_a_stamp_inside_the_future_tolerance_is_satisfied(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _beacon(
                tmp, age_s=-(alert_actions.BEACON_FUTURE_TOLERANCE_S - 1))
            self.assertEqual(ca.SATISFIED, _probe(path)[0])

    def test_a_naive_stamp_is_read_as_utc_and_not_as_local_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            naive = (NOW - timedelta(seconds=30)).replace(tzinfo=None)
            self.assertEqual(ca.SATISFIED,
                             _probe(_beacon(tmp, stamp=naive.isoformat()))[0])


class TheProbeAgreesWithTheGateThatHangsTheButtons(unittest.TestCase):
    """Проба мерит ИСХОД, а не свой пересчёт того же условия."""

    def test_the_verdict_matches_handler_available_on_a_healthy_beacon(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _beacon(tmp)
            self.assertTrue(alert_actions.handler_available(
                now=NOW, beacon_path=path))
            self.assertEqual(ca.SATISFIED, _probe(path)[0])

    def test_a_disagreement_with_the_gate_is_unmeasured_not_a_verdict(self):
        """Порванное звено: отдать СВОЙ ответ, когда гейт кнопок отвечает иначе.

        Сцена ломает ровно гейт (подменяя его на «кнопок нет») при исправном
        маячке — проба обязана сказать «не измерено», а не выдать свой ответ за
        замер исхода.
        """
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            path = _beacon(tmp)
            with mock.patch.object(alert_actions, "handler_available",
                                   return_value=False):
                verdict, why = _probe(path)
            self.assertEqual(ca.UNMEASURED, verdict)
            self.assertIn("расходятся", why)


class TheProbeIsRegistered(unittest.TestCase):
    """Проба, потерявшая регистрацию, измерять уже ничего не может."""

    def test_the_name_is_in_the_registry(self):
        self.assertIn("owner_control_plane_reachable", ca.PROBES)

    def test_the_dispatcher_reaches_it_and_offers_the_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            _beacon(tmp, age_s=30)
            # Через диспетчер часы не инъектируются по построению (он их не
            # предлагает), поэтому сцена ставит отметку «сейчас» настоящими
            # часами — предмет ЭТОГО теста есть ПРОВОДКА имени и `data_dir`,
            # а не окно свежести: его мерят тесты выше с инъекцией.
            Path(tmp, "telegram_bot_capabilities.json").write_text(json.dumps({
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "capabilities": ["alert_actions"]}))
            verdict, why = ca.run_probe("owner_control_plane_reachable",
                                        data_dir=tmp)
            self.assertEqual(ca.SATISFIED, verdict, why)

    def test_an_argument_that_is_not_a_key_is_refused_by_the_dispatcher(self):
        verdict, why = ca.run_probe("owner_control_plane_reachable:a b")
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("отвергнут", why)
