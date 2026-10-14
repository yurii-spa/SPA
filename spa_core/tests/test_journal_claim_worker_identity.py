"""Журнальный захват мерит РАБОТНИКА, а не запускателя (ADR-722, G721 п. 1).

ЧТО ЗДЕСЬ ЗАКРЕПЛЕНО. Захват карточки живёт в ТРЁХ записях — `claimed_by` во
frontmatter, строка журнала объявлений, пересечение по объявленным файлам. ADR-721
довёл ось РАБОТНИКА (`SPA_RUN_ID` в ОКРУЖЕНИИ — единственная личность, переживающая
запускателя) до ПЕРВОЙ из них. Вторая метки не несла вовсе: `log_session_change.record`
её не писал, и «активность сессии» для шагов 0a/0b мерилась pid ЗАПУСКАТЕЛЯ.

ЗАМЕР ДО ПРАВКИ (14.10, цикл #866): объявление цикла #864 легло как `[cycle-27063]` —
pid запускателя, хотя писал его РАБОТНИК 27717; объявление цикла #866 — `[cycle-24396]`
при работнике 24942. Запускатель — `/bin/bash scripts/agent_orchestrator.sh`, и его
окружение `ps -E` не отдаёт ВООБЩЕ (платформенный двоичный файл Apple), то есть ось
мерила ровно ту личность, которую измерить нельзя и которая по построению умирает раньше
работы.

ВРЕМЯ И ЛИЧНОСТЬ — ВХОДЫ, не окружение. Живость носителя метки инъектируется (`worker=`),
`now` задаётся, `ps` отвечает «процесса нет». Сторож, спрашивающий о живости живую ОС,
менял бы вердикт от того, кто сегодня занял номер, и краснел бы на чужом хосте
(`.claude/rules/deployment.md` § «ЛИЧНОСТЬ ПРОЦЕССА»).
"""
# FROZEN-DATE-OK: injected-clock — литеральный якорь `NOW` передаётся проверяемому коду
# аргументом (`gather(..., now=NOW)`), а все отметки сцены считаются ОТ него
# (`NOW - timedelta(...)`), поэтому ни одно утверждение не зависит от календаря. Пометка
# стои́т КОММЕНТАРИЕМ, а не строкой докстринга: храповик читает именно комментарий, и
# первая редакция этого файла его честно покраснила.
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 14, 14, 0, 0, tzinfo=timezone.utc)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load("_t866_guard", "scripts/check_card_claim.py")


@pytest.fixture(scope="module")
def writer():
    return _load("_t866_writer", "scripts/log_session_change.py")


@pytest.fixture(scope="module")
def lock():
    return _load("_t866_lock", "scripts/orchestrator_cycle_lock.py")


# ── ПИСАТЕЛЬ ────────────────────────────────────────────────────────────────────


class TestTheWriterStampsTheWorker:
    """Метка попадает в запись — иначе читать будет нечего, и ось навсегда `not_declared`."""

    def test_own_entry_carries_the_label(self, writer, tmp_path):
        log = tmp_path / "log.jsonl"
        entry = writer.record("своя запись", [], "", log=str(log),
                              worker=({writer.RUN_ID_FIELD: "orchestrator-1-AAA"}, ""))
        assert entry[writer.RUN_ID_FIELD] == "orchestrator-1-AAA"
        on_disk = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
        assert on_disk[writer.RUN_ID_FIELD] == "orchestrator-1-AAA", (
            "метка есть в возвращённой записи, но не на диске — читатель читает ДИСК")

    def test_an_entry_for_somebody_else_never_carries_my_label(self, writer, tmp_path):
        """Чужой ярлык + моя личность в ОДНОЙ записи — уже стоило выключенной защиты.

        Смысл переопределения `session` — «запись не моя, я лишь записываю»; штамп своей
        личности поверх чужого ярлыка говорит в той же строке обратное, а читатель верит
        личности, а не ярлыку (`agent-claim-guard-blind-when-session-pid-is-set`)."""
        log = tmp_path / "log.jsonl"
        entry = writer.record("чужая запись", [], "", log=str(log), session="cycle-ALIEN")
        assert writer.RUN_ID_FIELD not in entry, entry

    def test_without_the_variable_the_entry_is_byte_for_byte_as_before(self, writer,
                                                                      tmp_path):
        """Поле только ДОБАВЛЯЕТСЯ: без метки форма записи прежняя (контракт чужих тестов)."""
        label, why = writer.worker_label({})
        assert label == {} and "не задала" not in why and writer.RUN_ID_VAR in why
        log = tmp_path / "log.jsonl"
        entry = writer.record("без метки", [], "", log=str(log), worker=({}, why))
        assert writer.RUN_ID_FIELD not in entry

    def test_a_label_with_a_space_is_refused_with_a_reason(self, writer):
        """Прибор ищет метку подстрокой в `ps`, где поля разделены пробелами.

        Метка с пробелом не нашлась бы НИКОГДА ⇒ записалась бы личность, заведомо
        неизмеримая. Отказ громче молчаливо бесполезного поля."""
        label, why = writer.worker_label({writer.RUN_ID_VAR: "orchestrator 1"})
        assert label == {}
        assert "пробел" in why, why

    def test_the_field_name_has_exactly_one_definition(self, guard, writer):
        """Две копии строки переживают переименование МОЛЧА и тихо возвращают прежнее
        поведение — а оно выглядит как «так и было задумано»."""
        name, why = guard.run_id_field(announcer=writer)
        assert name == writer.RUN_ID_FIELD and why == ""

    def test_a_writer_without_the_name_is_refused_loudly(self, guard):
        """Переименование обязано ПАДАТЬ, а не отдавать `not_declared`."""
        class _Mute:
            def record(self, *a, **k):            # pragma: no cover - не вызывается
                raise AssertionError
        name, why = guard.run_id_field(announcer=_Mute())
        assert name is guard.RUN_ID_FIELD_UNKNOWN
        assert "НЕ ИЗМЕРЕНА" in why, why

    def test_load_announcer_requires_the_name(self, guard, tmp_path):
        """Сторож самого контракта: модуль-писатель без имени поля НЕ ввозится."""
        fake = tmp_path / "log_session_change.py"
        fake.write_text("def record(*a, **k):\n    return {}\n", encoding="utf-8")
        with pytest.raises(ImportError) as exc:
            guard.load_announcer(path=str(fake))
        assert "RUN_ID_FIELD" in str(exc.value)


# ── ЧИТАТЕЛЬ ────────────────────────────────────────────────────────────────────

LABEL = "cycle-27063"          #: ярлык-запускатель цикла #864 — замер, а не выдумка
MARK = "orchestrator-27063-T866"
SCENE_WHY = "состояние носителя метки задано входом сцены"


class TestTheReaderMeasuresTheWorker:
    """Сцена: захват ТОЛЬКО в журнале, во frontmatter метки нет вовсе."""

    @pytest.fixture()
    def scene(self, guard, writer, tmp_path):
        tracker = tmp_path / "tracker"
        tracker.mkdir()
        (tracker / "inbox-scene.md").write_text(
            "---\ntrackerStatus:\n  type: inbox\nstatus: in-progress\n---\n\nтело\n",
            encoding="utf-8")
        sibling = guard.load_sibling()

        def _ask(axis, ttl):
            def _probe(run_id):
                if not str(run_id or "").strip():
                    return "not_declared", "метки нет", None
                return axis, SCENE_WHY, ttl
            return _probe

        #: Сентинел нужен и ЗДЕСЬ: «поле не передавать» и «передать None» — два
        #: РАЗНЫХ входа, и первая редакция теста слила их в один, отчего проверка
        #: третьего исхода молча спрашивала про умолчание.
        DEFAULT = object()

        def _verdict(axis, age_s, *, with_mark=True, ttl=15000.0, field=DEFAULT):
            at = (NOW - timedelta(seconds=age_s)).strftime("%Y-%m-%dT%H:%M:%SZ")
            entry = {"ts": at, "session": LABEL, "summary": "сцена", "files": [],
                     "verified": "", "card": "inbox-scene", "card_state": "claim",
                     "session_pid": 27063,
                     "session_pid_start": "Wed Oct 14 00:00:00 2026"}
            if with_mark:
                entry[writer.RUN_ID_FIELD] = MARK
            log = (tmp_path /
                   f"log-{axis}-{int(age_s)}-{with_mark}-{field is DEFAULT}.jsonl")
            log.write_text(json.dumps(entry, ensure_ascii=False) + "\n", encoding="utf-8")
            kw = {} if field is DEFAULT else {"field_name": field}
            return guard.gather("inbox-scene", log=str(log), tracker_dir=str(tracker),
                                sibling=sibling, self_session="t866", now=NOW,
                                ps=lambda _pid: (1, ""), self_anchor=(41866, ""),
                                shared_trees=(), worker=_ask(axis, ttl), **kw)
        return _verdict

    @pytest.fixture()
    def stale_age(self, guard):
        #: СТАРШЕ окна свежести: внутри окна сильный захват блокирует и без оси,
        #: то есть сцена отвечала бы не на свой вопрос.
        return float(guard.DEFAULT_GRACE_HOURS) * 3600.0 + 1800.0

    def test_a_live_worker_holds_a_card_claimed_only_in_the_journal(self, guard, scene,
                                                                    stale_age):
        """ГЛАВНОЕ утверждение: ярлык мёртв, носитель метки ЖИВ ⇒ карточка ЗАНЯТА."""
        rep = scene(guard.W_ALIVE, stale_age)
        assert rep["verdict"] == guard.CLAIMED, rep["verdict"]
        rows = [c for c in rep["claims"] if c["source"] == "announce-log"]
        assert len(rows) == 1 and rows[0]["worker_axis"] == guard.W_ALIVE
        assert rows[0]["worker_run_id"] == MARK

    def test_a_measured_absence_still_releases_the_card(self, guard, scene, stale_age):
        """Обратная сторона: без неё защита — вечный замок (#61, #412, #803)."""
        assert scene(guard.W_GONE, stale_age)["verdict"] == guard.STALE

    def test_an_unmeasurable_axis_is_a_third_outcome(self, guard, scene, stale_age):
        """Инв. #17: «не измерено» не выдаётся ни за «занята», ни за «свободна»."""
        assert scene(guard.W_UNMEASURED, stale_age)["verdict"] == guard.UNCHECKED

    def test_a_hung_worker_releases_the_card_on_its_own_budget(self, guard, scene):
        """Неограниченный отказ есть та самая вечная блокировка, а не защита."""
        assert scene(guard.W_ALIVE, 15001.0, ttl=15000.0)["verdict"] == guard.STALE

    def test_an_entry_without_the_label_behaves_exactly_as_before(self, guard, scene,
                                                                  stale_age):
        """Правка СТРОГО дополняющая: запись старого образца судится как раньше."""
        rep = scene(guard.W_ALIVE, stale_age, with_mark=False)
        assert rep["verdict"] == guard.STALE
        rows = [c for c in rep["claims"] if c["source"] == "announce-log"]
        assert rows and rows[0]["worker_axis"] == guard.W_NOT_DECLARED

    def test_an_unknown_field_name_is_not_measured_rather_than_old_behaviour(
            self, guard, scene, stale_age):
        """Имени поля нет ⇒ читать НЕЧЕМ. Молча вернуться к оси ЗАПУСКАТЕЛЯ нельзя:
        это прежнее поведение, и оно выглядит как «так и было» — ровно подмена «не
        измерено» ответом (инв. #17, урок `pyflakes` из `deployment.md`)."""
        rep = scene(guard.W_ALIVE, stale_age, field=None)
        assert rep["verdict"] == guard.UNCHECKED, rep["verdict"]
        assert any("мет" in str(u) for u in rep["unmeasured"]), rep["unmeasured"]

    def test_the_axis_word_is_a_field_not_prose(self, guard, scene, stale_age):
        """Разбор подстрокой запрещён (ADR-333): слова оси в прозе сцены НЕТ."""
        rows = [c for c in scene(guard.W_ALIVE, stale_age)["claims"]
                if c["source"] == "announce-log"]
        assert guard.W_ALIVE not in str(rows[0]["worker_detail"])
