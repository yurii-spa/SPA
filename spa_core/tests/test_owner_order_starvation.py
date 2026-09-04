"""scripts/check_owner_order_starvation.py — «critical-приказ владельца голодает».

Дефект-класс (карточка `inbox-critical-kartochka-goloda-et-4-dnya-pri-40-tsiklah`, замер
26.08): `inbox-task-portfolio-cio-dynamic-capital-alloc` несла явное «УКАЗАНИЕ ВЛАДЕЛЬЦА
2026-08-22: ЗАПУСТИТЬ СЛЕДУЮЩИМ ЦИКЛОМ», приоритет `critical` — и простояла `status: new`
четвёртый день при 40+ прошедших циклах оркестратора. Шаг 0a (подъём осиротевшей работы) и
поток находок исполняются каждый цикл ПЕРЕД выбором из очереди — при постоянной смертности
сессий верх очереди в порядке приоритета не наступает никогда, и ни один сторож это не
называл. Этот сторож — узкий и детерминированный: сигналит только по явному маркеру приказа
владельца в теле critical-карточки, не по любой critical-карточке вообще (это отдельный,
гораздо более шумный вопрос очерёдности).

Все тесты — только в памяти (`Card` строится напрямую, без файлов на диске), детерминированы,
stdlib-only, без сети.
"""
import importlib.util
from datetime import datetime, timezone

# FROZEN-DATE-OK: injected-clock — часы здесь ВХОД, а не окружение: NOW передаётся в
# age_hours() и starving_owner_orders() каждым тестом, а даты в телах карточек — сам
# ПРЕДМЕТ проверки (сторож разбирает маркер «## УКАЗАНИЕ ВЛАДЕЛЬЦА <дата>» и считает
# возраст от него). Обе стороны закреплены одним якорем, календарь вердикт сдвинуть не
# может — это преференция #1 правила .claude/rules/deployment.md, а не глушение
# храповика. Решение и его основание записаны в docs/journal/2026-W35.md (цикл #391).
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load():
    path = ROOT / "scripts" / "check_owner_order_starvation.py"
    spec = importlib.util.spec_from_file_location("_test_owner_order_starvation", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load()


@pytest.fixture
def Card(guard):
    from spa_core.owner_queue.queue import Card as _Card
    return _Card


NOW = datetime(2026, 8, 26, 23, 0, 0, tzinfo=timezone.utc)


def _card(Card, *, path="inbox-x.md", priority="critical", status="new",
          body="## УКАЗАНИЕ ВЛАДЕЛЬЦА 2026-08-22 (cloud-сессия): ЗАПУСТИТЬ СЛЕДУЮЩИМ ЦИКЛОМ\n"):
    return Card(path=Path(path), tracker_type="inbox", title="т", status=status,
                priority=priority, body=body)


class TestFindOrderMarker:
    def test_finds_ukazanie_vladeltsa(self, guard):
        assert guard.find_order_marker(
            "## УКАЗАНИЕ ВЛАДЕЛЬЦА 2026-08-22 (cloud-сессия): текст"
        ) == "2026-08-22"

    def test_finds_prikaz_vladeltsa(self, guard):
        assert guard.find_order_marker("## ПРИКАЗ ВЛАДЕЛЬЦА 2026-08-01: текст") == "2026-08-01"

    def test_case_insensitive(self, guard):
        assert guard.find_order_marker("## указание владельца 2026-08-22: текст") == "2026-08-22"

    def test_no_marker_is_none(self, guard):
        assert guard.find_order_marker("обычный текст без приказа") is None

    def test_empty_body_is_none(self, guard):
        assert guard.find_order_marker("") is None
        assert guard.find_order_marker(None) is None


class TestAgeHours:
    def test_computes_hours_since_midnight_utc(self, guard):
        # 2026-08-22 00:00 UTC → 2026-08-26 23:00 UTC = 4 дня 23ч = 119ч
        assert guard.age_hours("2026-08-22", NOW) == pytest.approx(119.0, abs=0.01)

    def test_malformed_date_is_none(self, guard):
        assert guard.age_hours("не-дата", NOW) is None


class TestStarvingOwnerOrders:
    def test_critical_new_old_marker_is_a_finding(self, guard, Card):
        found = guard.starving_owner_orders([_card(Card)], NOW)
        assert len(found) == 1
        assert found[0]["path"] == "inbox-x.md"
        assert found[0]["age_hours"] > guard.DEFAULT_MIN_HOURS

    def test_fresh_marker_under_threshold_is_not_a_finding(self, guard, Card):
        c = _card(Card, body="## УКАЗАНИЕ ВЛАДЕЛЬЦА 2026-08-26: свежий приказ\n")
        assert guard.starving_owner_orders([c], NOW) == []

    def test_non_critical_priority_is_not_a_finding(self, guard, Card):
        c = _card(Card, priority="high")
        assert guard.starving_owner_orders([c], NOW) == []

    def test_status_in_progress_is_not_a_finding(self, guard, Card):
        # уже взята в работу — не голодает по смыслу карточки
        c = _card(Card, status="in-progress")
        assert guard.starving_owner_orders([c], NOW) == []

    def test_status_done_is_not_a_finding(self, guard, Card):
        c = _card(Card, status="done")
        assert guard.starving_owner_orders([c], NOW) == []

    def test_no_marker_is_not_a_finding_even_if_critical_and_stale(self, guard, Card):
        # critical + new без ЯВНОГО маркера приказа — не предмет этого сторожа (инв.: узкий сигнал)
        c = _card(Card, body="обычная critical-карточка без прямого приказа владельца\n")
        assert guard.starving_owner_orders([c], NOW) == []

    def test_sorted_oldest_first(self, guard, Card):
        old = _card(Card, path="a.md",
                    body="## УКАЗАНИЕ ВЛАДЕЛЬЦА 2026-08-01: старый\n")
        newer = _card(Card, path="b.md",
                      body="## УКАЗАНИЕ ВЛАДЕЛЬЦА 2026-08-20: новее\n")
        found = guard.starving_owner_orders([newer, old], NOW)
        assert [f["path"] for f in found] == ["a.md", "b.md"]

    def test_min_hours_is_configurable(self, guard, Card):
        c = _card(Card, body="## УКАЗАНИЕ ВЛАДЕЛЬЦА 2026-08-25: почти свежий\n")
        assert guard.starving_owner_orders([c], NOW, min_hours=48.0) == []
        assert guard.starving_owner_orders([c], NOW, min_hours=1.0) != []


class TestRender:
    def test_empty_findings_says_ok(self, guard):
        out = guard.render([], 24.0)
        assert "не найдено" in out

    def test_findings_render_actionable_line(self, guard):
        findings = [{"path": "inbox-x.md", "title": "заголовок", "status": "new",
                     "marker_date": "2026-08-22", "age_hours": 118.6}]
        out = guard.render(findings, 24.0)
        assert "ГОЛОДАЮЩИЙ ПРИКАЗ ВЛАДЕЛЬЦА" in out
        assert "заголовок" in out
        assert "118.6" in out
        assert "до шага 0a" in out


class TestMainExitCode:
    def test_exit_0_on_empty_tracker(self, guard, tmp_path):
        """Пустая очередь — код 0. ПРЕДПОСЫЛКА СТАЛА ЯВНОЙ (#484).

        НАМЕРЕННОЕ изменение теста (инв. #16), обоснование — здесь и в
        `docs/journal/2026-W36.md`. Раньше строка была
        `main(["--tracker-dir", tmp_path]) == 0` без флага `--ref`, и с появлением сверки
        с ref она стала спрашивать ДВЕ вещи разом: «пустая очередь ⇒ 0?» и «а можно ли
        вообще прочитать вторую копию очереди?». Во временном каталоге git-репозитория
        нет, вторая копия не читается — и ответ «0» означал бы «голода нет» там, где
        верно «искать было негде». Ровно этот fail-OPEN и чинит #484: сторож, читающий
        одну копию из двух, отвечает про КАТАЛОГ, а читается как ответ про ОЧЕРЕДЬ.

        Проверка не ослаблена, а РАЗДЕЛЕНА на два вопроса: здесь — «пустая очередь ⇒ 0»
        (сверка с ref явно выключена `--ref ""`), ниже — «ref не прочитан ⇒ 2, а не 0».
        """
        assert guard.main(["--tracker-dir", str(tmp_path), "--ref", ""]) == 0

    def test_exit_2_when_the_second_copy_of_the_queue_cannot_be_read(self, guard, tmp_path):
        """Вторая половина того же разделения: «не измерено» ≠ «голода нет».

        Каталог не в git-репозитории ⇒ очередь на ref не прочитана. Код 2 (fail-CLOSED,
        как у `check_undelivered_work` и `check_card_claim`), а не успокоительный 0.
        """
        assert guard.main(["--tracker-dir", str(tmp_path)]) == 2

    def test_exit_1_when_starving_card_on_disk(self, guard, tmp_path):
        (tmp_path / "inbox-x.md").write_text(
            "---\n"
            "trackerStatus:\n  type: inbox\n"
            "title: \"т\"\n"
            "status: new\n"
            "priority: critical\n"
            "created: 2026-08-13\n"
            "---\n"
            "## УКАЗАНИЕ ВЛАДЕЛЬЦА 2026-08-22 (cloud-сессия): ЗАПУСТИТЬ СЛЕДУЮЩИМ ЦИКЛОМ\n",
            encoding="utf-8",
        )
        assert guard.main(["--tracker-dir", str(tmp_path)]) == 1
