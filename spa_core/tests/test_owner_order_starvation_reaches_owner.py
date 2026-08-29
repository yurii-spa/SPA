"""У находки о голодающем приказе владельца есть путь, переживающий смерть сессии.

**Дефект-класс (замер цикла #422, карточка-заказчик
`inbox-critical-kartochka-goloda-et-4-dnya-pri-40-tsiklah`, пункт 2).** Сторож
`scripts/check_owner_order_starvation.py` был построен верно и говорил ровно одному
адресату — промпту той сессии, которая очередь и голодит (`agent_orchestrator.sh`
вклеивает вывод в начало промпта). Больше вердикт не попадал НИКУДА: ни файла, ни строки
владельцу. Сессии этого репозитория умирают регулярно — 29.08 подряд #419 и #421 сделали
работу и умерли до пуша, — а мёртвая сессия промпт не читает. То есть у сторожа,
поставленного против «находка не доезжает», единственный читатель сам был тем каналом,
который отказывает.

Здесь три утверждения, и они разные:

1. вердикт ЗАПИСЫВАЕТСЯ (`owner_order_starvation.json`) — и при находке, и без неё:
   пустой отчёт нужен не меньше, по его свежести читатель отличает «голода нет» от
   «измерять было некому»;
2. «N циклов мимо» ИЗМЕРЯЕТСЯ по журналу объявлений, а неизмеримость называется собой,
   а не нулём (ноль — самое успокоительное из значений, и подставлять его запрещено);
3. дневной дайджест — процесс с ДРУГИМ тактом и другой живучестью — несёт это владельцу,
   и молчит он только тогда, когда мерили и чисто.

Каждый тест помечен в коде как ПОЛОЖИТЕЛЬНЫЙ или ОБРАТНЫЙ контроль. Обратные написаны
так, чтобы на СТАРОМ коде быть зелёными: контроль, краснеющий из-за отсутствия атрибута,
о перегибе починки не говорит ничего.

Часы — ВХОД, а не окружение: `NOW` передаётся в каждую судящую функцию, а отметки журнала
строятся относительно него. Оставшиеся литеральные даты — сам предмет проверки (маркер
приказа в теле карточки и заголовок дайджеста); основание вынесено в маркер
`FROZEN-DATE-OK` ниже — это решение на протоколе, а не недосмотр.
"""
import importlib.util
import json

# FROZEN-DATE-OK: injected-clock — часы здесь ВХОД, а не окружение. `NOW` передаётся в
# каждую судящую функцию (`starving_owner_orders(now=)`, `cycles_since(..., now)`), а все
# отметки журнала строятся ОТНОСИТЕЛЬНО него (`NOW - timedelta(...)`). Обе стороны
# закреплены одним якорем, поэтому сдвиг календаря вердикт изменить не может. Оставшиеся
# литеральные даты — сам ПРЕДМЕТ проверки: сторож разбирает маркер
# «## УКАЗАНИЕ ВЛАДЕЛЬЦА <YYYY-MM-DD>» из тела карточки и считает возраст от него, а
# `date_str=` дайджеста — это заголовок сообщения, который тест сверяет дословно. Это
# преференция #1 правила `.claude/rules/deployment.md`, а не глушение храповика; решение
# и основание записаны в docs/journal/2026-W35.md (цикл #422).
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

NOW = datetime(2026, 8, 26, 23, 0, 0, tzinfo=timezone.utc)


def _load():
    path = ROOT / "scripts" / "check_owner_order_starvation.py"
    spec = importlib.util.spec_from_file_location(
        "_test_owner_order_starvation_reaches_owner", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load()


@pytest.fixture
def Card():
    from spa_core.owner_queue.queue import Card as _Card
    return _Card


def _card(Card, *, path="inbox-x.md", priority="critical", status="new", marker="2026-08-22"):
    body = f"## УКАЗАНИЕ ВЛАДЕЛЬЦА {marker} (cloud-сессия): ЗАПУСТИТЬ СЛЕДУЮЩИМ ЦИКЛОМ\n"
    return Card(path=Path(path), tracker_type="inbox", title="приказ по CIO", status=status,
                priority=priority, body=body)


def _announce(tmp_path, records) -> Path:
    p = tmp_path / "session_changes.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
                 encoding="utf-8")
    return p


def _rec(when, label):
    return {"ts": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "session": label, "summary": "x"}


# ---------------------------------------------------------------------------
# 1. Вердикт оставляет след
# ---------------------------------------------------------------------------

class TestVerdictLeavesATrace:
    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: на старом стороже записи не существовало вовсе.
    def test_finding_is_written_to_disk(self, guard, Card, tmp_path):
        findings = guard.starving_owner_orders([_card(Card)], now=NOW)
        written = guard.write_report(guard.build_report(findings, 24.0, NOW), tmp_path)
        assert written is not None, "вердикт не записан — у находки снова нет следа вне промпта"
        data = json.loads(Path(written).read_text(encoding="utf-8"))
        assert data["starving_count"] == 1
        assert data["findings"][0]["marker_date"] == "2026-08-22"

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: «голода нет» обязано быть ОТЛИЧИМО от «никто не мерил».
    def test_empty_verdict_is_written_too(self, guard, tmp_path):
        written = guard.write_report(guard.build_report([], 24.0, NOW), tmp_path)
        assert written is not None
        data = json.loads(Path(written).read_text(encoding="utf-8"))
        assert data["starving_count"] == 0
        assert data["generated_at"], (
            "у пустого отчёта нет отметки времени — по нему нельзя отличить свежее "
            "«чисто» от старого замера, а это и есть весь смысл пустого отчёта")

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: имя фиксировано — его знает читатель (дайджест).
    def test_report_name_is_the_one_the_digest_reads(self, guard):
        assert guard.REPORT_NAME == "owner_order_starvation.json"

    # ОБРАТНЫЙ КОНТРОЛЬ: сорванная запись НЕ имеет права изменить вердикт.
    def test_failed_write_returns_none_and_does_not_raise(self, guard, tmp_path):
        blocked = tmp_path / "file_not_a_dir"
        blocked.write_text("я файл, а не каталог", encoding="utf-8")
        assert guard.write_report(guard.build_report([], 24.0, NOW), blocked) is None


# ---------------------------------------------------------------------------
# 2. «N циклов мимо» — измерение, а не догадка
# ---------------------------------------------------------------------------

class TestCyclesPassed:
    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: величина, которую карточка просила дословно.
    def test_counts_distinct_sessions_since_the_order(self, guard, tmp_path):
        since = NOW - timedelta(hours=48)
        p = _announce(tmp_path, [
            _rec(since + timedelta(hours=1), "cycle-1"),
            _rec(since + timedelta(hours=2), "cycle-1"),   # тот же цикл — не второй
            _rec(since + timedelta(hours=3), "cycle-2"),
            _rec(since + timedelta(hours=4), "cycle-3"),
        ])
        assert guard.cycles_since(since.strftime("%Y-%m-%d"), NOW, p) == 3

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: объявления ДО приказа мимо него не проходили.
    def test_ignores_announcements_before_the_order(self, guard, tmp_path):
        marker = (NOW - timedelta(days=2)).strftime("%Y-%m-%d")
        p = _announce(tmp_path, [
            _rec(NOW - timedelta(days=9), "cycle-old"),
            _rec(NOW - timedelta(hours=5), "cycle-new"),
        ])
        assert guard.cycles_since(marker, NOW, p) == 1

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: НЕТ журнала ⇒ НЕ ИЗМЕРЕНО, и это не ноль.
    def test_missing_journal_is_unmeasured_not_zero(self, guard, tmp_path):
        got = guard.cycles_since("2026-08-22", NOW, tmp_path / "нет-такого.jsonl")
        assert got is None, (
            "неизмеримое выдано числом: ноль означает «мимо не прошёл никто» — самое "
            "успокоительное из значений, и подставлять его вместо замера запрещено")

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: битая строка занижает счёт, но не глушит весь журнал.
    def test_broken_line_does_not_blind_the_whole_journal(self, guard, tmp_path):
        p = tmp_path / "session_changes.jsonl"
        good = _rec(NOW - timedelta(hours=3), "cycle-живой")
        p.write_text("{это не json\n" + json.dumps(good, ensure_ascii=False) + "\n",
                     encoding="utf-8")
        assert guard.cycles_since((NOW - timedelta(days=1)).strftime("%Y-%m-%d"), NOW, p) == 1

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: величина доезжает до самой находки.
    def test_finding_carries_cycles_passed(self, guard, Card, tmp_path):
        marker = (NOW - timedelta(days=3)).strftime("%Y-%m-%d")
        p = _announce(tmp_path, [_rec(NOW - timedelta(hours=h), f"cycle-{h}")
                                 for h in (1, 2, 3)])
        out = guard.starving_owner_orders([_card(Card, marker=marker)], now=NOW,
                                          announce_path=p)
        assert out and out[0]["cycles_passed"] == 3

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: журнал не передан ⇒ поле есть и говорит «не измерено».
    def test_without_journal_field_is_present_and_none(self, guard, Card):
        out = guard.starving_owner_orders([_card(Card)], now=NOW)
        assert out and out[0]["cycles_passed"] is None

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: в человеческом выводе неизмеренное названо словами.
    def test_render_says_unmeasured_not_zero(self, guard, Card):
        text = guard.render(guard.starving_owner_orders([_card(Card)], now=NOW), 24.0)
        assert "НЕ ИЗМЕРЕНО" in text
        assert "мимо прошло циклов: 0" not in text

    # ОБРАТНЫЙ КОНТРОЛЬ: голода нет — сторож по-прежнему молчит и не выдумывает находок.
    def test_no_starvation_still_renders_clean(self, guard):
        assert "✅" in guard.render([], 24.0)


# ---------------------------------------------------------------------------
# 3. Дайджест — канал, который смерть сессии не выключает
# ---------------------------------------------------------------------------

def _digest(tmp_path):
    from spa_core.analytics.telegram_daily_digest import TelegramDailyDigest
    return TelegramDailyDigest(data_dir=str(tmp_path))


def _write_report(tmp_path, *, age_h=1.0, findings=()):
    when = datetime.now(tz=timezone.utc) - timedelta(hours=age_h)
    (tmp_path / "owner_order_starvation.json").write_text(json.dumps({
        "generated_at": when.isoformat(),
        "min_hours": 24.0,
        "starving_count": len(findings),
        "findings": list(findings),
    }, ensure_ascii=False), encoding="utf-8")


class TestDigestCarriesItToTheOwner:
    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: отчёта нет ⇒ «НЕ ИЗМЕРЕНО», а НЕ тишина.
    def test_missing_report_is_loud_not_silent(self, tmp_path):
        sec = _digest(tmp_path).build_starvation_section()
        assert sec.lines, "секция промолчала о том, что замера не было — это fail-OPEN"
        assert "НЕ ИЗМЕРЕНО" in " ".join(sec.lines)

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: протухший отчёт — тоже «не измерено», и срок назван.
    def test_stale_report_is_unmeasured(self, tmp_path):
        _write_report(tmp_path, age_h=200.0)
        line = " ".join(_digest(tmp_path).build_starvation_section().lines)
        assert "НЕ ИЗМЕРЕНО" in line and "устарел" in line

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: находка доходит до владельца дословной формулой карточки.
    def test_finding_reaches_the_owner(self, tmp_path):
        _write_report(tmp_path, findings=[{
            "title": "Portfolio CIO: динамическая аллокация",
            "path": "nimbalyst-local/tracker/inbox-task-portfolio-cio.md",
            "status": "new", "marker_date": "2026-08-22",
            "age_hours": 118.6, "cycles_passed": 40}])
        line = " ".join(_digest(tmp_path).build_starvation_section().lines)
        assert "⏳ голодает:" in line
        assert "Portfolio CIO" in line
        assert "40 циклов мимо" in line

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: неизмеренные циклы и здесь не превращаются в ноль.
    def test_unmeasured_cycles_are_named_not_zeroed(self, tmp_path):
        _write_report(tmp_path, findings=[{
            "title": "приказ", "age_hours": 50.0, "cycles_passed": None}])
        line = " ".join(_digest(tmp_path).build_starvation_section().lines)
        assert "циклов мимо: НЕ ИЗМЕРЕНО" in line
        assert "0 циклов мимо" not in line

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: секция реально ВКЛЕЕНА в сообщение.
    # Мутация «удалить вызов из build_digest» обязана краснить — проверка частей
    # без проверки проводки оставляет починку неподключённой.
    def test_section_is_actually_wired_into_the_message(self, tmp_path):
        _write_report(tmp_path, findings=[{
            "title": "приказ владельца по CIO", "age_hours": 99.0, "cycles_passed": 12}])
        msg = _digest(tmp_path).build_digest(date_str="2026-08-26")
        assert "голодает" in msg
        assert "Приказы владельца" in msg

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: текст уезжает в Telegram ЭКРАНИРОВАННЫМ.
    # Неэкранированный «118.6ч» / «(без имени)» ломает разбор MarkdownV2 — то есть
    # владелец не получил бы дайджест ЦЕЛИКОМ, а не только эту строку.
    def test_owner_facing_text_is_markdownv2_escaped(self, tmp_path):
        _write_report(tmp_path, findings=[{
            "title": "CIO (динамика)", "age_hours": 118.6, "cycles_passed": 40}])
        msg = _digest(tmp_path).build_digest(date_str="2026-08-26")
        assert "\\(динамика\\)" in msg
        assert "(динамика)" not in msg.replace("\\(динамика\\)", "")

    # ОБРАТНЫЙ КОНТРОЛЬ: свежий пустой отчёт — коротко и без тревоги.
    # Написано через отсутствие подстроки, чтобы на СТАРОМ коде тест был зелёным:
    # красный из-за AttributeError о перегибе починки не сказал бы ничего.
    def test_fresh_and_clean_does_not_cry_wolf(self, tmp_path):
        _write_report(tmp_path, age_h=2.0)
        d = _digest(tmp_path)
        line = " ".join(getattr(d, "build_starvation_section", lambda: type(
            "S", (), {"lines": []})())().lines)
        assert "⏳ голодает:" not in line
        assert "НЕ ИЗМЕРЕНО" not in line

    # ОБРАТНЫЙ КОНТРОЛЬ: битый отчёт не роняет дайджест целиком.
    def test_broken_report_does_not_break_the_whole_digest(self, tmp_path):
        (tmp_path / "owner_order_starvation.json").write_text("{не json",
                                                              encoding="utf-8")
        msg = _digest(tmp_path).build_digest(date_str="2026-08-26")
        assert "SPA Daily Digest" in msg
