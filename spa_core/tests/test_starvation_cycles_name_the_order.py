"""«Циклов мимо» обязано считать ПРИКАЗ, а не календарь (ADR-874, цикл #992).

**Авария, которую воспроизводят эти тесты.** Шаг 0a-ГОЛОД печатал в самой верхней строке
промпта каждого цикла:

    приказ от 2026-08-22, стоит in-progress уже 1680.0ч, мимо прошло циклов: 880

Величину давал `cycles_since`: РАЗЛИЧИМЫЕ ярлыки сессий, объявлявших ЛЮБУЮ работу с даты
приказа. То есть прибор честно отвечал на свой вопрос («сколько циклов вообще было») и
выдавал ответ за нужный («сколько проигнорировало приказ»). Замер 31.10 по прод-журналу
`data/session_changes.jsonl` с 22.08: сессий **880**, а карточку приказа «Portfolio CIO»
назвали полем `card` **455** из них (51.7 %) — и она оказалась САМОЙ называемой карточкой
всего журнала, следующая 50. Самый обслуженный приказ проекта предъявлялся каждому циклу —
и владельцу в дайджесте — как полностью брошенный, с завышением «мимо» в 2.07 раза.

Три оси обязаны быть различимы (инв. #17): объявляли работу · называли карточку · прошли
мимо (разность). Четвёртое состояние — «карточка измерителю не названа» — обязано быть
`None`, а не разностью: подстановка `announced` вернула бы дефект через умолчание.

Контроль идёт в ОБЕ стороны. Положительные сцены краснеют на прежнем коде; обратные
написаны так, чтобы на прежнем коде быть ЗЕЛЁНЫМИ — иначе они говорят не о перегибе
починки, а об отсутствии атрибута.

Часы — ВХОД, а не окружение: `NOW` передаётся в каждую судящую функцию, а все отметки
журнала строятся относительно него.
"""
import importlib.util
import json

# FROZEN-DATE-OK: injected-clock — часы здесь ВХОД. `NOW` передаётся в `cycles_measure(…,
# now)` и `starving_owner_orders(now=)`, а отметки журнала строятся ОТНОСИТЕЛЬНО него
# (`NOW - timedelta(...)`), поэтому обе стороны сравнения закреплены одним якорем и сдвиг
# календаря вердикт изменить не может. Литерал даты маркера приказа — сам ПРЕДМЕТ проверки
# (сторож разбирает «## УКАЗАНИЕ ВЛАДЕЛЬЦА <YYYY-MM-DD>» из тела карточки), и он тоже
# производный от `NOW`. Решение и основание записаны в docs/journal/2026-W44.md (цикл #992).
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

NOW = datetime(2026, 10, 31, 0, 0, 0, tzinfo=timezone.utc)

#: Карточка приказа — та самая, на которой авария и измерена.
ORDER = "inbox-task-portfolio-cio-dynamic-capital-alloc"
ORDER_PATH = f"nimbalyst-local/tracker/{ORDER}.md"


def _load():
    path = ROOT / "scripts" / "check_owner_order_starvation.py"
    spec = importlib.util.spec_from_file_location(
        "_test_starvation_cycles_name_the_order", path)
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


MARKER = (NOW - timedelta(days=4)).strftime("%Y-%m-%d")


def _card(Card, *, path=ORDER_PATH, status="new"):
    body = f"## УКАЗАНИЕ ВЛАДЕЛЬЦА {MARKER} (cloud-сессия): ЗАПУСТИТЬ СЛЕДУЮЩИМ ЦИКЛОМ\n"
    return Card(path=Path(path), tracker_type="inbox", title="приказ по CIO",
                status=status, priority="critical", body=body)


def _announce(tmp_path, records) -> Path:
    p = tmp_path / "session_changes.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
                 encoding="utf-8")
    return p


def _rec(hours_ago, label, card=None):
    rec = {"ts": (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "session": label, "summary": "работа"}
    if card is not None:
        rec["card"] = card
    return rec


def _digest(tmp_path):
    from spa_core.analytics.telegram_daily_digest import TelegramDailyDigest
    return TelegramDailyDigest(data_dir=str(tmp_path))


def _digest_report(tmp_path, finding: dict) -> None:
    """Свежий отчёт сторожа на диске — вход секции дайджеста.

    `generated_at` строится от НАСТОЯЩИХ часов: у секции свой порог свежести
    (`STARVATION_REPORT_MAX_AGE_H`) и своих инъектируемых часов нет, поэтому литеральная
    отметка протухла бы от одного сдвига календаря.
    """
    when = datetime.now(tz=timezone.utc) - timedelta(hours=1)
    (tmp_path / "owner_order_starvation.json").write_text(json.dumps({
        "generated_at": when.isoformat(), "min_hours": 24.0,
        "starving_count": 1, "repeat_groups": [], "findings": [finding],
    }, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. «Мимо» — это РАЗНОСТЬ, и её слагаемые названы
# ---------------------------------------------------------------------------

class TestPassedByIsADifference:
    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: авария в миниатюре. Прежний код сказал бы «мимо 2».
    def test_a_session_that_named_the_card_did_not_pass_it_by(self, guard, tmp_path):
        p = _announce(tmp_path, [_rec(3, "cycle-назвал", card=ORDER),
                                 _rec(2, "cycle-мимо")])
        m = guard.cycles_measure(MARKER, NOW, p, ORDER_PATH)
        assert m["announced"] == 2
        assert m["named_the_card"] == 1
        assert m["passed_by"] == 1, (
            "сессия, объявившая работу ПО ЭТОЙ карточке, зачтена как прошедшая мимо — "
            "ровно то завышение, из-за которого самый обслуженный приказ проекта "
            "показывался брошенным")

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: все назвали ⇒ мимо НОЛЬ, и это измеренный ноль.
    def test_everyone_named_the_card_so_nobody_passed_by(self, guard, tmp_path):
        p = _announce(tmp_path, [_rec(5, "cycle-a", card=ORDER),
                                 _rec(4, "cycle-b", card=ORDER_PATH)])
        m = guard.cycles_measure(MARKER, NOW, p, ORDER)
        assert (m["announced"], m["named_the_card"], m["passed_by"]) == (2, 2, 0)

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: ОДНА сессия, назвавшая карточку дважды, остаётся одной.
    def test_the_same_session_is_counted_once_on_both_axes(self, guard, tmp_path):
        p = _announce(tmp_path, [_rec(6, "cycle-один", card=ORDER),
                                 _rec(5, "cycle-один", card=ORDER),
                                 _rec(4, "cycle-один")])
        m = guard.cycles_measure(MARKER, NOW, p, ORDER)
        assert (m["announced"], m["named_the_card"], m["passed_by"]) == (1, 1, 0), (
            "ярлык, назвавший карточку хотя бы раз, обязан быть НАЗВАВШИМ целиком: "
            "иначе одна сессия попадёт в оба набора и разность уйдёт в минус"
        )

    # ОБРАТНЫЙ КОНТРОЛЬ: никто не назвал ⇒ мимо прошли ВСЕ. Починка не имеет права
    # обнулять «мимо» вообще — это был бы тот же дефект с другой стороны.
    def test_nobody_named_the_card_so_all_passed_by(self, guard, tmp_path):
        p = _announce(tmp_path, [_rec(3, "cycle-a"), _rec(2, "cycle-b"),
                                 _rec(1, "cycle-c", card="inbox-совсем-другая")])
        m = guard.cycles_measure(MARKER, NOW, p, ORDER)
        assert (m["announced"], m["named_the_card"], m["passed_by"]) == (3, 0, 3)

    # ОБРАТНЫЙ КОНТРОЛЬ: СОСЕДНЯЯ карточка, чьё имя СОДЕРЖИТ имя нашей, названной не
    # является. Подстрока прошла бы (ADR-333), равенство — нет.
    def test_a_neighbour_card_whose_name_contains_ours_is_not_ours(self, guard, tmp_path):
        p = _announce(tmp_path, [_rec(3, "cycle-сосед", card=f"{ORDER}-vtoraya-chast")])
        m = guard.cycles_measure(MARKER, NOW, p, ORDER)
        assert m["named_the_card"] == 0, (
            "имя соседней карточки зачтено как наше: сверка подстрокой превратила бы "
            "работу по ДРУГОЙ карточке в работу по приказу")

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: путь и идентификатор — ОДНА форма для измерителя.
    def test_path_and_bare_id_are_the_same_card(self, guard, tmp_path):
        p = _announce(tmp_path, [_rec(3, "cycle-путь", card=ORDER_PATH)])
        by_path = guard.cycles_measure(MARKER, NOW, p, ORDER_PATH)
        by_id = guard.cycles_measure(MARKER, NOW, p, ORDER)
        assert by_path == by_id == {"announced": 1, "named_the_card": 1, "passed_by": 0}


# ---------------------------------------------------------------------------
# 2. Третий исход: «не спрашивали» ≠ «ни одна»
# ---------------------------------------------------------------------------

class TestUnmeasuredIsNotZero:
    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: карточка измерителю не названа ⇒ разности НЕТ.
    def test_without_a_card_id_the_difference_is_unmeasured(self, guard, tmp_path):
        p = _announce(tmp_path, [_rec(3, "cycle-a"), _rec(2, "cycle-b")])
        m = guard.cycles_measure(MARKER, NOW, p)
        assert m["announced"] == 2, "ось «объявляли работу» измерима и без имени карточки"
        assert m["named_the_card"] is None
        assert m["passed_by"] is None, (
            "«карточку не спрашивали» выдано за «ни одна не назвала»: подстановка "
            "числа объявлявших в разность и ЕСТЬ прежний дефект, вернувшийся умолчанием")

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: журнала нет ⇒ НЕ ИЗМЕРЕНО целиком, а не нули.
    def test_missing_journal_is_unmeasured_not_zeroes(self, guard, tmp_path):
        assert guard.cycles_measure(MARKER, NOW, tmp_path / "нет.jsonl", ORDER) is None

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: дата приказа не разбирается ⇒ то же самое.
    def test_unparseable_marker_is_unmeasured(self, guard, tmp_path):
        p = _announce(tmp_path, [_rec(3, "cycle-a", card=ORDER)])
        assert guard.cycles_measure("не-дата", NOW, p, ORDER) is None

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: битая строка занижает счёт, но не глушит журнал целиком.
    def test_broken_line_does_not_blind_the_journal(self, guard, tmp_path):
        p = tmp_path / "session_changes.jsonl"
        p.write_text("{это не json\n"
                     + json.dumps(_rec(3, "cycle-живой", card=ORDER), ensure_ascii=False)
                     + "\n", encoding="utf-8")
        m = guard.cycles_measure(MARKER, NOW, p, ORDER)
        assert (m["announced"], m["named_the_card"], m["passed_by"]) == (1, 1, 0)

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: объявления ДО приказа не считаются ни одной осью.
    def test_announcements_before_the_order_count_nowhere(self, guard, tmp_path):
        p = _announce(tmp_path, [_rec(24 * 9, "cycle-старый", card=ORDER),
                                 _rec(2, "cycle-новый")])
        m = guard.cycles_measure(MARKER, NOW, p, ORDER)
        assert (m["announced"], m["named_the_card"], m["passed_by"]) == (1, 0, 1)


# ---------------------------------------------------------------------------
# 3. Проводка: три оси доезжают до находки, печати и владельца
# ---------------------------------------------------------------------------

class TestTheAxesReachTheReaders:
    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: находка несёт все три оси.
    def test_finding_carries_three_axes(self, guard, Card, tmp_path):
        p = _announce(tmp_path, [_rec(3, "cycle-назвал", card=ORDER),
                                 _rec(2, "cycle-мимо")])
        out = guard.starving_owner_orders([_card(Card)], now=NOW, announce_path=p)
        assert out
        assert out[0]["cycles_passed"] == 1
        assert out[0]["cycles_announced"] == 2
        assert out[0]["cycles_named_the_card"] == 1

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: журнала не дали ⇒ ВСЕ три оси «не измерено», не нули.
    def test_without_journal_all_three_axes_are_none(self, guard, Card):
        out = guard.starving_owner_orders([_card(Card)], now=NOW)
        assert out
        for key in ("cycles_passed", "cycles_announced", "cycles_named_the_card"):
            assert out[0][key] is None, key

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: печать шага 0a называет соседнюю ось РЯДОМ с «мимо».
    def test_render_prints_the_neighbouring_axis(self, guard, Card, tmp_path):
        p = _announce(tmp_path, [_rec(3, "cycle-назвал", card=ORDER),
                                 _rec(2, "cycle-мимо")])
        text = guard.render(
            guard.starving_owner_orders([_card(Card)], now=NOW, announce_path=p), 24.0)
        assert "мимо прошло циклов: 1" in text
        assert "объявляли работу 2" in text
        assert "карточку называли 1" in text

    # ОБРАТНЫЙ КОНТРОЛЬ: на неизмеренном печать по-прежнему говорит это словами.
    def test_render_still_says_unmeasured(self, guard, Card):
        text = guard.render(guard.starving_owner_orders([_card(Card)], now=NOW), 24.0)
        assert "НЕ ИЗМЕРЕНО" in text
        assert "мимо прошло циклов: 0" not in text

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: ВЛАДЕЛЬЦУ в дайджесте уезжает та же пара чисел.
    #
    # Отметка отчёта здесь ОТНОСИТЕЛЬНАЯ (преференция №2 правила, `.claude/rules/
    # deployment.md`): у секции дайджеста свой порог свежести и СВОИ часы, которые
    # инъектировать нечем, — поэтому якорь берётся от настоящих часов, а не литералом.
    def test_digest_tells_the_owner_both_numbers(self, tmp_path):
        _digest_report(tmp_path, {"path": ORDER_PATH, "title": "приказ по CIO",
                                  "age_hours": 1680.0, "cycles_passed": 425,
                                  "cycles_announced": 880,
                                  "cycles_named_the_card": 455})
        lines = " ".join(_digest(tmp_path).build_starvation_section().lines)
        assert "425 циклов мимо" in lines
        assert "карточку называли 455" in lines, (
            "владельцу уехало одно число без соседнего: именно так ему и показывали "
            "«880 циклов мимо» про карточку, которую назвали 455 из тех же 880 сессий")

    # ОБРАТНЫЙ КОНТРОЛЬ: отчёт ПРЕЖНЕГО сторожа (соседней оси в нём нет) не ломает
    # дайджест и не выдумывает число — ключа нет, значит и приписки нет.
    def test_digest_survives_an_old_report_without_the_axis(self, tmp_path):
        _digest_report(tmp_path, {"path": ORDER_PATH, "title": "приказ по CIO",
                                  "age_hours": 1680.0, "cycles_passed": 880})
        lines = " ".join(_digest(tmp_path).build_starvation_section().lines)
        assert "880 циклов мимо" in lines
        assert "карточку называли" not in lines


# ---------------------------------------------------------------------------
# 4. Проба приёмки: зелёная на целом контуре, красная на КАЖДОМ рваном звене
# ---------------------------------------------------------------------------

def _probe():
    from spa_core.monitoring.card_acceptance import PROBES
    return PROBES["starvation_cycles_name_the_order"]


def _fake_repo(tmp_path, patch=None) -> Path:
    """Одноразовый корень репозитория со СВОЕЙ копией двери шага 0a.

    Нужен именно корень, а не подмена функции: проба поднимает дверь ПОДПРОЦЕССОМ
    (иначе она мерила бы не то, что исполняется в проде), и внутрипроцессный патч до
    подпроцесса не доезжает. `spa_core` подкладывается ссылкой — без него копия умрёт на
    своём импорте и исход будет «НЕ ИЗМЕРЕНО», то есть контроль ничего не проверит.
    """
    root = tmp_path / "fake_repo"
    (root / "scripts").mkdir(parents=True)
    src = (ROOT / "scripts" / "check_owner_order_starvation.py").read_text(encoding="utf-8")
    if patch is not None:
        before, after = patch
        assert before in src, f"якорь подмены не найден: {before!r}"
        src = src.replace(before, after, 1)
    (root / "scripts" / "check_owner_order_starvation.py").write_text(src, encoding="utf-8")
    (root / "spa_core").symlink_to(ROOT / "spa_core", target_is_directory=True)
    return root


@pytest.fixture
def probe_on(monkeypatch):
    """Прогнать пробу против одноразового корня."""
    def run(root: Path):
        from spa_core.monitoring import card_acceptance as ca
        monkeypatch.setattr(ca, "REPO_ROOT", str(root))
        return _probe()(None)
    return run


class TestTheProbeHasControlBothWays:
    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: на целом контуре (копия БЕЗ подмены) проба зелена.
    def test_probe_is_green_on_the_whole_loop(self, tmp_path, probe_on):
        verdict, why = probe_on(_fake_repo(tmp_path))
        assert verdict == "satisfied", why

    # ОБРАТНЫЙ КОНТРОЛЬ №1 — ПРЕЖНЕЕ ПОВЕДЕНИЕ: «мимо» = число объявлявших.
    def test_probe_is_red_when_passed_by_counts_the_calendar(self, tmp_path, probe_on):
        root = _fake_repo(tmp_path, ('"cycles_passed": m["passed_by"]',
                                     '"cycles_passed": m["announced"]'))
        verdict, why = probe_on(root)
        assert verdict == "not_satisfied", (
            f"проба не покраснела на ПРЕЖНЕМ поведении двери — она не меряет предмет: {why}")
        assert "календарь" in why or "мимо" in why

    # ОБРАТНЫЙ КОНТРОЛЬ №2 — ПЕРЕГИБ починки: «мимо» всегда ноль.
    def test_probe_is_red_when_passed_by_is_always_zero(self, tmp_path, probe_on):
        root = _fake_repo(tmp_path, ('"cycles_passed": m["passed_by"]',
                                     '"cycles_passed": 0'))
        verdict, why = probe_on(root)
        assert verdict == "not_satisfied", (
            f"обнулённая ось принята за починку — тот же дефект с другой стороны: {why}")

    # ОБРАТНЫЙ КОНТРОЛЬ №3 — ось ИСЧЕЗЛА из находки: читателю нечем отличить.
    def test_probe_is_red_when_the_neighbouring_axis_is_dropped(self, tmp_path, probe_on):
        root = _fake_repo(tmp_path, ('"cycles_named_the_card": m["named_the_card"]',
                                     '"cycles_dropped": m["named_the_card"]'))
        verdict, why = probe_on(root)
        assert verdict == "not_satisfied", (
            f"находка без оси `cycles_named_the_card` принята: {why}")
        assert "cycles_named_the_card" in why

    # ОБРАТНЫЙ КОНТРОЛЬ №4 — ПЕЧАТЬ молчит о слагаемых, числа при этом верны.
    def test_probe_is_red_when_the_print_hides_the_axis(self, tmp_path, probe_on):
        root = _fake_repo(tmp_path, ('    return f" (объявляли работу {announced}, '
                                     'карточку называли {named})"',
                                     '    return ""'))
        verdict, why = probe_on(root)
        assert verdict == "not_satisfied", (
            f"печать, называющая одно число, принята за две оси: {why}")
        assert "печать" in why
