"""Тесты Фазы 3 ADR-066: house_view_gap + мост «находка → карточка».

Приёмка карточки Фазы 3 закреплена здесь буквально:
`test_artificial_finding_full_loop` — искусственная находка проходит путь
находка → (гистерезис) → карточка → исчезновение → авто-закрытие БЕЗ РУК.

Каждое правило моста проверено в обе стороны (спам-защита и её пределы):
dedup, гистерезис (WARN ждёт 2-го прогона, CRITICAL — нет), rate-limit ≤5/сутки
с ГРОМКИМ deferred, авто-закрытие только нетронутой (new) карточки, эскалация
WARN→CRITICAL. Карточные операции инъектируются — тест НИКОГДА не трогает
живой tracker (мост, пишущий в прод из теста, = фальсификация очереди владельца).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest

from spa_core.monitoring import findings_bridge as fb
from spa_core.monitoring import house_view_gap as hvg

NOW = dt.datetime(2030, 3, 1, 12, 0, tzinfo=dt.timezone.utc)  # FROZEN-DATE-OK: injected-clock — часы инъектируются


# ── house_view_gap ───────────────────────────────────────────────────────────

def chief(posture="YELLOW", opportunities=()):
    return {"house_view": {"overall_posture": posture,
                           "top_opportunities": [
                               {"value": {"protocol": p, "apy_pct": 8.0},
                                "evidence_level": "L3"} for p in opportunities]}}


def positions(held=("pendle",), cash=15000.0, capital=100000.0):
    return {"positions": {p: 10000.0 for p in held},
            "cash_usd": cash, "capital_usd": capital}


class HouseViewGap(unittest.TestCase):
    def test_held_opportunity_is_not_a_gap(self):
        r = hvg.compute_gaps(chief(opportunities=("pendle",)), positions(),
                             {}, {"pendle"}, {}, NOW)
        self.assertEqual(r["gaps"], [])

    def test_available_unheld_unnamed_is_warn(self):
        """Ядро ADR-055: безымянный простой возможности."""
        r = hvg.compute_gaps(chief(opportunities=("maple",)), positions(),
                             {}, {"pendle", "maple"}, {}, NOW)
        self.assertEqual(r["counts"]["warn"], 1)
        self.assertIn("отказ НЕ назван", r["gaps"][0]["message"])

    def test_named_refusal_downgrades_to_info(self):
        rationale = {"below_median_cap": [{"protocol": "maple"}]}
        r = hvg.compute_gaps(chief(opportunities=("maple",)), positions(),
                             rationale, {"pendle", "maple"}, {}, NOW)
        self.assertEqual(r["counts"]["warn"], 0)
        self.assertIn("НАЗВАН", r["gaps"][0]["message"])

    def test_no_adapter_is_info_not_warn(self):
        r = hvg.compute_gaps(chief(opportunities=("aerodrome",)), positions(),
                             {}, {"pendle"}, {}, NOW)
        self.assertEqual(r["counts"]["warn"], 0)
        self.assertIn("вне реестра", r["gaps"][0]["message"])

    def test_registry_unavailable_never_fabricates_warn(self):
        r = hvg.compute_gaps(chief(opportunities=("maple",)), positions(),
                             {}, None, {}, NOW)
        self.assertEqual(r["counts"]["warn"], 0)
        self.assertIn("не измерима", r["gaps"][0]["message"])

    def test_red_posture_deployed_book_is_warn_yellow_is_not(self):
        red = hvg.compute_gaps(chief(posture="RED"), positions(), {}, set(), {}, NOW)
        self.assertEqual([g["key"] for g in red["gaps"]], ["gap:posture_vs_book"])
        yellow = hvg.compute_gaps(chief(posture="YELLOW"), positions(), {}, set(), {}, NOW)
        self.assertEqual(yellow["gaps"], [])

    def test_analyst_red_is_surfaced(self):
        r = hvg.compute_gaps(chief(), positions(), {}, set(),
                             {"red_team": {"posture": "RED"}}, NOW)
        self.assertEqual([g["type"] for g in r["gaps"]], ["analyst_red"])

    def test_missing_inputs_go_to_unchecked_not_gaps(self):
        r = hvg.compute_gaps(None, None, None, None, {}, NOW)
        self.assertEqual(r["gaps"], [])
        self.assertEqual({u["input"] for u in r["unchecked"]},
                         {"chief_investment", "current_positions", "allocation_rationale"})


# ── мост ─────────────────────────────────────────────────────────────────────

class FakeQueue:
    """Инъекция карточных операций: тест не смеет трогать живой tracker.

    Подделка обязана быть ПОХОЖЕЙ на очередь, иначе она прячет дефект вместо того,
    чтобы его ловить. До цикла #172 здесь любая карточка рождалась `status: new` —
    и ровно поэтому ни один тест не заметил, что CRITICAL в жизни рождается
    `needs-owner` и потому не закрывается никогда. Теперь тип карточки тот же,
    что у живого `create_card`, а решение «нетронута ли» берётся из БОЕВОГО
    `fb.card_is_untouched` — снятая починка краснит тесты, а не проходит мимо.
    """

    def __init__(self, tracker: str):
        self.tracker = tracker
        self.created: list[dict] = []
        self.notified: list[str] = []
        self.retracted: list[str] = []
        self.n = 0

    def create(self, root, finding):
        self.n += 1
        critical = finding["severity"] == "CRITICAL"
        kind = "owner-decision" if critical else "inbox"
        status = "needs-owner" if critical else "new"
        path = os.path.join(self.tracker, f"card-{self.n}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"---\ntrackerStatus:\n  type: {kind}\nstatus: {status}\n"
                    f"finding_key: \"{finding['key']}\"\n---\n{finding['message']}\n"
                    f"\n_finding_key: `{finding['key']}` · ADR-066_\n")
        self.created.append({"key": finding["key"], "severity": finding["severity"],
                             "path": path})
        return path

    def _close(self, root, path):
        if not fb.card_is_untouched(path):
            return False
        text = open(path, encoding="utf-8").read()
        for old in ("status: new", "status: needs-owner"):
            text = text.replace(old, "status: done")
        open(path, "w", encoding="utf-8").write(text)
        return True

    def notify(self, root, path):
        self.notified.append(path)
        return True

    def retract(self, root, path):
        self.retracted.append(path)
        return True

    def set_field(self, path: str, key: str, value: str) -> None:
        """Дописать поле во frontmatter — так его пишет живой `owner_answer`."""
        text = open(path, encoding="utf-8").read()
        head, sep, body = text.partition("\n---\n")
        open(path, "w", encoding="utf-8").write(f"{head}\n{key}: {value}{sep}{body}")


class Bridge(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = self.td.name
        os.makedirs(os.path.join(self.root, "data"))
        self.tracker = os.path.join(self.root, "tracker")
        os.makedirs(self.tracker)
        self.q = FakeQueue(self.tracker)

    def tearDown(self):
        self.td.cleanup()

    def put_conformance(self, findings):
        with open(os.path.join(self.root, "data", "architecture_conformance.json"),
                  "w", encoding="utf-8") as f:
            json.dump({"generated_at": NOW.isoformat(), "findings": findings}, f)
        with open(os.path.join(self.root, "data", "house_view_gap.json"),
                  "w", encoding="utf-8") as f:
            json.dump({"gaps": []}, f)
        with open(os.path.join(self.root, "data", "loop_retro.json"),
                  "w", encoding="utf-8") as f:
            json.dump({"findings": []}, f)

    def run_bridge(self, at=NOW):
        return fb.run_bridge(self.root, now=at, create=self.q.create,
                             close=self.q._close, notify=self.q.notify,
                             retract=self.q.retract)

    def critical(self, key="B1:zombie:com.spa.x", message="агент работает при intent=retired"):
        return {"key": key, "severity": "CRITICAL", "message": message}

    def warn(self, key="B1:reboot_unsafe:com.spa.x"):
        return {"key": key, "severity": "WARN", "message": f"находка {key}"}

    def test_artificial_finding_full_loop(self):
        """ПРИЁМКА ФАЗЫ 3: находка → карточка → исчезновение → авто-закрытие без рук."""
        self.put_conformance([self.warn()])
        r1 = self.run_bridge()                       # прогон 1: гистерезис — ждём
        self.assertEqual(r1["created"], [])
        self.assertEqual(r1["waiting_hysteresis"], ["B1:reboot_unsafe:com.spa.x"])
        r2 = self.run_bridge(NOW + dt.timedelta(hours=6))   # прогон 2: карточка
        self.assertEqual(len(r2["created"]), 1)
        card = r2["created"][0]["card"]
        self.assertEqual(fb.card_status(card), "new")
        r3 = self.run_bridge(NOW + dt.timedelta(hours=12))  # находка держится: дубля нет
        self.assertEqual(r3["created"], [])
        self.assertEqual(r3["open_cards"], 1)
        self.put_conformance([])                      # находка исчезла
        r4 = self.run_bridge(NOW + dt.timedelta(hours=18))
        self.assertEqual([c["card"] for c in r4["closed"]], [card])
        self.assertEqual(fb.card_status(card), "done")
        self.assertEqual(r4["open_cards"], 0)

    def test_critical_skips_hysteresis_and_notifies(self):
        self.put_conformance([{"key": "B1:dead:com.spa.a", "severity": "CRITICAL",
                               "message": "агент мёртв"}])
        r1 = self.run_bridge()
        self.assertEqual(len(r1["created"]), 1)
        self.assertEqual(len(self.q.notified), 1)

    def test_rate_limit_defers_loudly(self):
        many = [self.warn(f"B2:stale:f{i}") for i in range(8)]
        self.put_conformance(many)
        self.run_bridge()                            # регистрация (гистерезис)
        r = self.run_bridge(NOW + dt.timedelta(hours=6))
        self.assertEqual(len(r["created"]), fb.MAX_CARDS_PER_DAY)
        self.assertEqual(len(r["deferred"]), 8 - fb.MAX_CARDS_PER_DAY)
        nxt = self.run_bridge(NOW + dt.timedelta(days=1))  # новые сутки — добор
        self.assertEqual(len(nxt["created"]), 8 - fb.MAX_CARDS_PER_DAY)

    def test_taken_card_is_never_auto_closed(self):
        """Карточку, взятую в работу (in-progress), мост не смеет трогать."""
        self.put_conformance([self.warn()])
        self.run_bridge()
        r2 = self.run_bridge(NOW + dt.timedelta(hours=6))
        card = r2["created"][0]["card"]
        text = open(card, encoding="utf-8").read().replace("status: new", "status: in-progress")
        open(card, "w", encoding="utf-8").write(text)
        self.put_conformance([])
        r = self.run_bridge(NOW + dt.timedelta(hours=12))
        self.assertEqual(r["closed"], [])
        self.assertEqual(fb.card_status(card), "in-progress")

    def test_flapping_finding_never_becomes_card(self):
        self.put_conformance([self.warn()])
        self.run_bridge()
        self.put_conformance([])                      # мигнула и исчезла
        self.run_bridge(NOW + dt.timedelta(hours=6))
        self.put_conformance([self.warn()])           # вернулась — счёт заново
        r = self.run_bridge(NOW + dt.timedelta(hours=12))
        self.assertEqual(r["created"], [])

    def test_escalation_warn_to_critical_creates_owner_card(self):
        self.put_conformance([self.warn("B1:x")])
        self.run_bridge()
        self.run_bridge(NOW + dt.timedelta(hours=6))  # WARN-карточка создана
        self.put_conformance([{"key": "B1:x", "severity": "CRITICAL",
                               "message": "эскалация"}])
        r = self.run_bridge(NOW + dt.timedelta(hours=12))
        self.assertEqual(len(r["created"]), 1)
        self.assertEqual(r["escalated"], ["B1:x"])
        self.assertEqual(len(self.q.notified), 1)

    def test_closed_finding_reappearing_recards_and_counts_recurrence(self):
        """Рецидив: закрытая находка вернулась — мост ОБЯЗАН снова довести её до
        карточки (найденный при построении Фазы 4 молчаливый провал) и посчитать."""
        self.put_conformance([self.warn()])
        self.run_bridge()
        self.run_bridge(NOW + dt.timedelta(hours=6))          # карточка №1
        self.put_conformance([])
        self.run_bridge(NOW + dt.timedelta(hours=12))         # авто-закрытие
        self.put_conformance([self.warn()])                    # РЕЦИДИВ
        self.run_bridge(NOW + dt.timedelta(hours=18))          # гистерезис заново
        r = self.run_bridge(NOW + dt.timedelta(hours=24))
        self.assertEqual(len(r["created"]), 1)                 # карточка №2
        state = json.load(open(os.path.join(self.root, "data",
                                            "findings_bridge_state.json")))
        self.assertEqual(state["findings"]["B1:reboot_unsafe:com.spa.x"]["recurrences"], 1)

    def test_state_loss_reconciles_from_tracker_no_duplicate_cards(self):
        """Инцидент 2026-08-05 23:55: состояние моста исчезло между прогонами.
        Открытая карточка с finding_key на диске ⇒ восстановление carded-записи
        из реальности, ДУБЛЬ карточки не создаётся; авто-закрытие живо."""
        tdir = os.path.join(self.root, "nimbalyst-local", "tracker")
        os.makedirs(tdir)
        card = os.path.join(tdir, "inbox-nahodka-petli-x.md")
        with open(card, "w", encoding="utf-8") as f:
            f.write("---\nstatus: new\nfinding_key: B1:reboot_unsafe:com.spa.x\n---\nтело\n")
        self.put_conformance([self.warn()])           # состояние = пустое (потеряно)
        r1 = self.run_bridge()
        self.assertEqual(r1["reconciled_from_tracker"], 1)
        self.assertEqual(r1["created"], [])            # дубля НЕТ
        r2 = self.run_bridge(NOW + dt.timedelta(hours=6))
        self.assertEqual(r2["created"], [])
        self.assertEqual(r2["open_cards"], 1)
        self.put_conformance([])                       # находка исчезла
        r3 = self.run_bridge(NOW + dt.timedelta(hours=12))
        self.assertEqual([c["card"] for c in r3["closed"]], [card])  # авто-закрытие живо
        self.assertEqual(fb.card_status(card), "done")

    # ── цикл #172: вопрос владельца тоже обязан закрываться ──────────────────

    def test_critical_owner_card_is_auto_closed_when_finding_vanishes(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ дефекта 08.08: CRITICAL рождается `needs-owner`,
        а закрытие знало только `new` ⇒ ложная тревога оставалась вечным вопросом
        владельцу. Четыре такие карточки лежали в проде (`B1:zombie:*`)."""
        self.put_conformance([self.critical()])
        r1 = self.run_bridge()                                  # CRITICAL без гистерезиса
        card = r1["created"][0]["card"]
        self.assertEqual(fb.card_status(card), "needs-owner")   # именно вопрос владельцу
        self.put_conformance([])                                # находка оказалась ложной
        r2 = self.run_bridge(NOW + dt.timedelta(hours=6))
        self.assertEqual([c["card"] for c in r2["closed"]], [card])
        self.assertEqual(fb.card_status(card), "done")
        self.assertEqual(r2["open_cards"], 0)

    def test_card_the_owner_answered_is_never_auto_closed(self):
        """Обратный контроль: есть след владельца (кнопка ADR-069) ⇒ не трогаем.
        Вопрос, на который уже ответили, закрывать за владельца нельзя."""
        self.put_conformance([self.critical()])
        card = self.run_bridge()["created"][0]["card"]
        self.q.set_field(card, "owner_choice", "2")
        self.put_conformance([])
        r = self.run_bridge(NOW + dt.timedelta(hours=6))
        self.assertEqual(r["closed"], [])
        self.assertEqual(fb.card_status(card), "needs-owner")

    def test_owner_card_taken_into_work_is_never_auto_closed(self):
        """`ingested` — карточку уже разобрали; авто-закрытие к ней не применяется."""
        self.put_conformance([self.critical()])
        card = self.run_bridge()["created"][0]["card"]
        text = open(card, encoding="utf-8").read().replace("status: needs-owner",
                                                           "status: ingested")
        open(card, "w", encoding="utf-8").write(text)
        self.put_conformance([])
        r = self.run_bridge(NOW + dt.timedelta(hours=6))
        self.assertEqual(r["closed"], [])
        self.assertEqual(fb.card_status(card), "ingested")

    def test_closing_a_notified_question_sends_a_withdrawal(self):
        """Владельцу написали «нужно решение» — значит обязаны написать и «вопрос снят».
        Молчаливое снятие оставляет в чате требование, на которое нельзя ответить."""
        self.put_conformance([self.critical()])
        card = self.run_bridge()["created"][0]["card"]
        self.assertEqual(self.q.notified, [card])
        self.put_conformance([])
        r = self.run_bridge(NOW + dt.timedelta(hours=6))
        self.assertEqual(self.q.retracted, [card])
        self.assertEqual(r["withdrawn"], [{"key": "B1:zombie:com.spa.x",
                                           "card": card, "sent": True}])

    def test_warn_card_closes_without_bothering_the_owner(self):
        """WARN уведомления не порождал — значит и отзыва быть не должно."""
        self.put_conformance([self.warn()])
        self.run_bridge()
        self.run_bridge(NOW + dt.timedelta(hours=6))
        self.put_conformance([])
        r = self.run_bridge(NOW + dt.timedelta(hours=12))
        self.assertEqual(len(r["closed"]), 1)
        self.assertEqual(self.q.retracted, [])
        self.assertEqual(r["withdrawn"], [])

    def test_failed_withdrawal_is_named_not_silently_true(self):
        """Отзыв не ушёл — это находка, а не успех: карточка закрыта, вопрос висит."""
        self.put_conformance([self.critical()])
        card = self.run_bridge()["created"][0]["card"]
        self.put_conformance([])
        r = fb.run_bridge(self.root, now=NOW + dt.timedelta(hours=6),
                          create=self.q.create, close=self.q._close,
                          notify=self.q.notify, retract=lambda root, p: False)
        self.assertEqual(r["withdrawn"], [{"key": "B1:zombie:com.spa.x",
                                           "card": card, "sent": False}])

    def test_state_loss_does_not_duplicate_the_owner_question(self):
        """Зеркало того же дефекта: восстановление состояния из трекера не видело
        `needs-owner` ⇒ после потери состояния владелец получил бы ВТОРОЙ такой же
        вопрос. Карточка на диске есть — дубля быть не должно."""
        tdir = os.path.join(self.root, "nimbalyst-local", "tracker")
        os.makedirs(tdir)
        card = os.path.join(tdir, "owner-decision-kritichnaya-nahodka.md")
        with open(card, "w", encoding="utf-8") as f:
            f.write("---\ntrackerStatus:\n  type: owner-decision\nstatus: needs-owner\n"
                    "finding_key: \"B1:zombie:com.spa.x\"\n---\nтело\n")
        self.put_conformance([self.critical()])       # состояние моста = потеряно
        r1 = self.run_bridge()
        self.assertEqual(r1["reconciled_from_tracker"], 1)
        self.assertEqual(r1["created"], [])
        self.assertEqual(self.q.notified, [])         # и второго уведомления тоже нет

    def test_restored_owner_card_is_not_re_escalated_into_a_second_question(self):
        """Восстановленной записи нельзя приписывать тяжесть WARN: на следующем
        прогоне это сработало бы как эскалация WARN→CRITICAL и создало дубль."""
        tdir = os.path.join(self.root, "nimbalyst-local", "tracker")
        os.makedirs(tdir)
        with open(os.path.join(tdir, "owner-decision-x.md"), "w", encoding="utf-8") as f:
            f.write("---\ntrackerStatus:\n  type: owner-decision\nstatus: needs-owner\n"
                    "finding_key: \"B1:zombie:com.spa.x\"\n---\nтело\n")
        self.put_conformance([self.critical()])
        r1 = self.run_bridge()                       # эскалация сработала бы ЗДЕСЬ
        r2 = self.run_bridge(NOW + dt.timedelta(hours=6))
        self.assertEqual(r1["created"] + r2["created"], [])
        self.assertEqual(r1["escalated"] + r2["escalated"], [])

    def test_finding_key_in_the_body_is_not_read_as_frontmatter(self):
        """Живая карточка моста заканчивается строкой `_finding_key: ...` в ТЕЛЕ.
        Разбор ограничен оградой `---`, иначе тело подменяло бы поля."""
        path = os.path.join(self.tracker, "card-body.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("---\nstatus: needs-owner\n---\nтело\nowner_choice: 1\n")
        self.assertTrue(fb.card_is_untouched(path))   # след владельца в ТЕЛЕ — не след
        self.assertEqual(fb.card_status(path), "needs-owner")

    def test_unread_sources_are_loud_and_create_nothing(self):
        r = fb.run_bridge(self.root, now=NOW, create=self.q.create,
                          close=self.q._close, notify=self.q.notify)
        self.assertEqual(len(r["sources_unread"]), 3)
        self.assertEqual(r["created"], [])


if __name__ == "__main__":
    unittest.main()
