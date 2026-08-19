"""Родство ярлыков одной сессии по РАБОЧЕМУ ДЕРЕВУ — вход, до которого токен не дотягивается.

**Авария, которую проигрывает каждый положительный тест здесь** (19.08.2026, цикл #302, живой
замер). Шаг 0a про сессию #301 сказал: «долгоживущий процесс pid64036 завершился, ждать больше
некого — поднимай», и назвал недоставленный файл поимённо. Шаг 0b про ТУ ЖЕ сессию в ту же
минуту ответил `⛔ ЗАНЯТА — НЕ бери эту карточку`. Оба pid к тому моменту были мертвы. Подъём
осиротевшей работы — единственное действие, которое протокол здесь предписывает, — снова
оказался запрещён сторожем.

**Почему починка #293 (родство по токену `pidN`) сюда не дотягивается.** Токен берётся из
САМОГО ярлыка, а ярлык формы `cycle-<PID>` слова `pid` не содержит:

    pid_tokens('cycle-292-pid71239') -> {'pid71239'}     # форма, которую чинил #293
    pid_tokens('cycle-64036')        -> set()            # форма из аварии 19.08

Причин ровно две, и каждой хватило бы: (1) у формы `cycle-<PID>` токена нет вовсе; (2) два
ярлыка одной сессии несут РАЗНЫЕ числа — захват ушёл под `pid64051` (pid однократной
CLI-команды, так велит шаг 0b протокола), объявление владения — под `cycle-64036`
(долгоживущий процесс). Совпадение чисел у двух ярлыков — счастливая случайность, а не
свойство. Замер #302 (журнал 19.08, 1021 запись): **328 захватов из 445 объявлены под ярлыком
без токена**, то есть вне досягаемости родства по токену.

Признак, которым они всё-таки связаны, — общее рабочее дерево: сессия работает в одном
изолированном worktree (§3.4) и объявляет пути внутри него. Он машинный, лежит в тех же
записях и от формы ярлыка не зависит.

**Что здесь закреплено в ОБЕ стороны.** Родство обязано остаться fail-CLOSED: живой держатель
по-прежнему блокирует карточку; общее (главное) дерево родством не считается; два якоря на
одно дерево, два дерева у одного ярлыка и неизмеренные общие деревья родства не дают. Ложное
«свободна» опаснее ложного «занята» — оно отдаёт карточку живой сессии.

Тесты герметичны: свой журнал и свой каталог карточек в ``tmp_path``, `ps` подменяется, время
и список общих деревьев подаются ВХОДОМ. Все отметки журнала и времена старта процессов
отсчитываются от одной точки — обе стороны каждого сравнения закреплены, поэтому файл не
привязан к календарю (`.claude/rules/deployment.md`, порядок предпочтения 1).
"""
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# FROZEN-DATE-OK: время здесь — ВХОД, а не окружение. `now` подаётся сторожу явно, все отметки
# журнала и времена старта процессов отсчитываются от этой же точки ⇒ смена календаря тест не
# двигает. Часы на уровне модуля читать нельзя (сторож `test_no_import_time_clock_in_tests`:
# прогон, пересёкший полночь, покраснеет неповторимо), поэтому точка — литерал.
NOW = datetime(2026, 8, 19, 10, 41, 0, tzinfo=timezone.utc)


def _load(name, rel):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load("_tree_card_claim", "scripts/check_card_claim.py")


@pytest.fixture(scope="module")
def sibling(guard):
    return guard.load_sibling()


def _fmt(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lstart(dt):
    """Время старта процесса в формате `ps -o lstart=` (локальная зона, как отдаёт сам `ps`)."""
    return dt.astimezone().strftime("%a %b %d %H:%M:%S %Y")


# Личности из аварии 19.08 — ровно те, что стояли в журнале.
STARTED = NOW - timedelta(hours=12)
ANCHOR = {"session_pid": 64036, "session_pid_start": _lstart(STARTED)}

CLAIM_LABEL = "pid64051"      # ярлык записи-захвата (передан флагом `--session`, токен ЕСТЬ)
CYCLE_LABEL = "cycle-64036"   # ярлык объявления владения — токена НЕТ, число ДРУГОЕ

TREE = "/tmp/spa_c301"
MAIN_TREE = "/Users/yuriikulieshov/Documents/SPA_Claude"   # общее дерево всех сессий


def entry(session, ts, *, anchor=None, card=None, card_state="claim", files=(),
          summary="работа"):
    e = {"ts": _fmt(ts), "session": session, "summary": summary,
         "files": [str(f) for f in files], "verified": ""}
    if card:
        e["card"], e["card_state"] = card, card_state
    if anchor:
        e.update(anchor)
    return e


@pytest.fixture()
def tracker(tmp_path):
    d = tmp_path / "tracker"
    d.mkdir()
    return d


@pytest.fixture()
def log(tmp_path):
    p = tmp_path / "session_changes.jsonl"
    p.write_text("", encoding="utf-8")
    return p


def write_log(path, entries):
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
                    encoding="utf-8")


def write_card(tracker, cid, *, status="new"):
    p = tracker / f"{cid}.md"
    p.write_text("---\ntrackerStatus:\n  type: inbox\ntitle: Карточка\n"
                 f"status: {status}\n---\n\nтело\n", encoding="utf-8")
    return p


@pytest.fixture()
def ps_dead():
    """`ps` отвечает «процесса нет» — ровно то, что видел цикл #302 про обоих pid сессии #301."""
    return lambda pid: (1, "")


@pytest.fixture()
def ps_alive():
    """`ps` показывает ИМЕННО тот процесс, что записан в якоре ⇒ активность ПОДТВЕРЖДЕНА."""
    return lambda pid: (0, _lstart(STARTED)) if pid == ANCHOR["session_pid"] else (1, "")


def run(guard, sibling, tracker, log, card, *, session="cycle-303", ps=None,
        planned_files=(), shared_trees=(MAIN_TREE,)):
    """Шаг 0b целиком. `shared_trees` подаётся ВХОДОМ — иначе тест звал бы git и мерил хост."""
    return guard.gather(card, log=log, tracker_dir=tracker, sibling=sibling,
                        self_session=session, now=NOW, grace_hours=3.0,
                        planned_files=planned_files, ps=ps, self_anchor=None,
                        shared_trees=shared_trees)


# ── 1. дерево читается из объявленного пути ──────────────────────────────────

class TestTreeIsReadFromDeclaredPaths:
    def test_repo_subdir_names_the_tree(self, sibling):
        assert sibling.tree_of_path(f"{TREE}/scripts/check_card_claim.py") == TREE
        assert sibling.tree_of_path(f"{TREE}/spa_core/tests/test_x.py") == TREE
        assert sibling.tree_of_path(f"{TREE}/nimbalyst-local/tracker/inbox-x.md") == TREE

    def test_private_tmp_and_tmp_are_the_same_tree(self, sibling):
        """Капкан ИМЕННО этой аварии: захват #301 объявил `/private/tmp/spa_c301/…`, а
        объявление владения — `/tmp/spa_c301/…`. Побайтовое сравнение двух написаний одного
        каталога macOS ответило бы «разные деревья» — то есть тот же класс слепоты, который
        мы чиним. `realpath` не годится: снятого дерева на диске уже нет."""
        assert (sibling.tree_of_path("/private/tmp/spa_c301/nimbalyst-local/tracker/x.md")
                == sibling.tree_of_path("/tmp/spa_c301/scripts/y.py") == TREE)

    def test_unknown_top_level_dir_gives_no_tree(self, sibling):
        """Корень не домысливается по «предпоследнему каталогу»: догадка — не измерение."""
        assert sibling.tree_of_path("/tmp/spa_c301/wat/x.py") is None
        assert sibling.tree_of_path("/tmp/spa_c301") is None

    def test_relative_path_gives_no_tree(self, sibling):
        assert sibling.tree_of_path("scripts/check_card_claim.py") is None
        assert sibling.tree_of_path("") is None

    def test_entry_naming_two_trees_has_none(self, sibling):
        """26 ярлыков из 630 в живом журнале объявляли файлы в разных деревьях. Какое из них
        «настоящее» — инструмент не угадывает."""
        e = entry(CLAIM_LABEL, NOW, files=[f"{TREE}/scripts/a.py", "/tmp/spa_c999/scripts/b.py"])
        assert sibling.worktree_of(e) is None

    def test_entry_without_readable_paths_has_no_tree(self, sibling):
        assert sibling.worktree_of(entry(CLAIM_LABEL, NOW, files=[])) is None
        assert sibling.worktree_of(entry(CLAIM_LABEL, NOW, files=["notes.md"])) is None


# ── 2. родство по дереву: только там, где токен не дотянулся ─────────────────

class TestKinByTreeStaysNarrow:
    def _rows(self, *, claim_files=(f"{TREE}/nimbalyst-local/tracker/x.md",),
              cycle_files=(f"{TREE}/scripts/a.py",), anchor=ANCHOR, cycle_label=CYCLE_LABEL):
        return [entry(CLAIM_LABEL, NOW - timedelta(minutes=75), files=claim_files),
                entry(cycle_label, NOW - timedelta(minutes=73), anchor=anchor,
                      files=cycle_files)]

    def test_label_without_a_token_still_lends_its_anchor(self, sibling):
        """Главный случай 19.08: у `cycle-64036` токена нет, числа у ярлыков разные — связывает
        ТОЛЬКО общее дерево."""
        assert sibling.pid_tokens(CYCLE_LABEL) == set()          # причина, а не следствие
        anchors, kin = sibling.anchors_with_kin(self._rows(), shared_trees=(MAIN_TREE,))
        assert anchors[CLAIM_LABEL] == ANCHOR
        assert kin[CLAIM_LABEL] == CYCLE_LABEL

    def test_private_tmp_claim_borrows_from_tmp_announce(self, sibling):
        """Дословная пара записей #301: два написания одного дерева."""
        rows = self._rows(claim_files=("/private/tmp/spa_c301/nimbalyst-local/tracker/x.md",))
        anchors, kin = sibling.anchors_with_kin(rows, shared_trees=(MAIN_TREE,))
        assert anchors[CLAIM_LABEL] == ANCHOR and kin[CLAIM_LABEL] == CYCLE_LABEL

    def test_shared_tree_is_never_kin(self, sibling):
        """Главное дерево общее для ВСЕХ сессий (замер: 101 ярлык, 17 разных якорей) — «то же
        дерево» там не значит «та же сессия», и одного якоря на коротком журнале хватило бы,
        чтобы отдать живую карточку. Сторож обязан быть шире подопечного (#197/#234)."""
        rows = self._rows(claim_files=(f"{MAIN_TREE}/nimbalyst-local/tracker/x.md",),
                          cycle_files=(f"{MAIN_TREE}/scripts/a.py",))
        anchors, kin = sibling.anchors_with_kin(rows, shared_trees=(MAIN_TREE,))
        assert CLAIM_LABEL not in anchors and CLAIM_LABEL not in kin

    def test_shared_trees_not_measured_disables_the_feature(self, sibling):
        """`None` = общие деревья НЕ измерены. Тогда признак не применяется вовсе, а не
        «общих нет»: иначе неудача замера превращалась бы в разрешение."""
        anchors, kin = sibling.anchors_with_kin(self._rows(), shared_trees=None)
        assert CLAIM_LABEL not in anchors and CLAIM_LABEL not in kin
        assert (anchors, kin) == (sibling.durable_by_session(self._rows()), {})

    def test_two_anchors_on_one_tree_give_no_kin(self, sibling):
        """Неоднозначность = отказ, как и у токена."""
        other = {"session_pid": 900, "session_pid_start": _lstart(STARTED)}
        rows = self._rows() + [entry("cycle-777", NOW - timedelta(minutes=60), anchor=other,
                                     files=[f"{TREE}/docs/STATE.md"])]
        anchors, kin = sibling.anchors_with_kin(rows, shared_trees=(MAIN_TREE,))
        assert CLAIM_LABEL not in anchors and CLAIM_LABEL not in kin

    def test_different_trees_are_not_kin(self, sibling):
        """Обратный контроль: две РАЗНЫЕ сессии, каждая в своём дереве. Смерть одной не смеет
        погасить захват другой."""
        rows = self._rows(cycle_files=("/tmp/spa_c999/scripts/a.py",))
        anchors, kin = sibling.anchors_with_kin(rows, shared_trees=(MAIN_TREE,))
        assert CLAIM_LABEL not in anchors and CLAIM_LABEL not in kin

    def test_label_with_two_trees_gets_no_kin(self, sibling):
        rows = [entry(CLAIM_LABEL, NOW - timedelta(minutes=80),
                      files=[f"{TREE}/scripts/a.py"]),
                entry(CLAIM_LABEL, NOW - timedelta(minutes=78),
                      files=["/tmp/spa_c999/scripts/b.py"]),
                entry(CYCLE_LABEL, NOW - timedelta(minutes=73), anchor=ANCHOR,
                      files=[f"{TREE}/scripts/c.py"])]
        anchors, kin = sibling.anchors_with_kin(rows, shared_trees=(MAIN_TREE,))
        assert CLAIM_LABEL not in anchors and CLAIM_LABEL not in kin

    def test_own_anchor_always_wins(self, sibling):
        """Родство — замена отсутствию, а не поправка: свой якорь сильнее любого признака."""
        mine = {"session_pid": 500, "session_pid_start": _lstart(STARTED)}
        rows = [entry(CLAIM_LABEL, NOW - timedelta(minutes=75), anchor=mine,
                      files=[f"{TREE}/scripts/a.py"]),
                entry(CYCLE_LABEL, NOW - timedelta(minutes=73), anchor=ANCHOR,
                      files=[f"{TREE}/scripts/b.py"])]
        anchors, kin = sibling.anchors_with_kin(rows, shared_trees=(MAIN_TREE,))
        assert anchors[CLAIM_LABEL] == mine and CLAIM_LABEL not in kin

    def test_a_process_born_after_the_record_is_not_borrowed(self, sibling):
        """Сужение #265 действует и для родства по дереву: процесс, родившийся ПОСЛЕ записи,
        её не писал — иначе переиспользованный ярлык дал бы ложный ACTIVE."""
        late = {"session_pid": 64036, "session_pid_start": _lstart(NOW - timedelta(minutes=5))}
        rows = self._rows(anchor=late)
        anchors, kin = sibling.anchors_with_kin(rows, shared_trees=(MAIN_TREE,))
        borrowed, why = sibling.borrow_durable(rows[0], anchors, kin)
        assert sibling.durable_fields(borrowed) == {} and why == ""


# ── 3. шаг 0b целиком: вердикт про ту же сессию, что и у шага 0a ─────────────

class TestStep0bAgreesWithStep0aAboutDeath:
    """Положительные контроли — дословная авария 19.08; обратные — то, что меняться не смело."""

    def _journal(self, log, *, anchor=ANCHOR, claim_age_min=75, card="agent-x",
                 claim_tree=TREE, cycle_tree=TREE, cycle_label=CYCLE_LABEL):
        write_log(log, [
            entry(CLAIM_LABEL, NOW - timedelta(minutes=claim_age_min), card=card,
                  files=[f"{claim_tree}/nimbalyst-local/tracker/{card}.md"],
                  summary="[check_card_claim] захват карточки"),
            entry(cycle_label, NOW - timedelta(minutes=claim_age_min - 2), anchor=anchor,
                  card=card, files=[f"{cycle_tree}/scripts/a.py"],
                  summary="цикл #301: работа в дереве"),
        ])

    def test_fresh_claim_of_a_dead_session_is_stale_not_claimed(self, guard, sibling, tracker,
                                                                log, ps_dead):
        """АВАРИЯ 19.08 дословно: свежий захват под `pid64051` + смерть под `cycle-64036`
        (токена нет, число другое) ⇒ шаг 0b отвечал `claimed` и запрещал подъём."""
        write_card(tracker, "agent-x")
        self._journal(log)
        r = run(guard, sibling, tracker, log, "agent-x", ps=ps_dead)
        assert r["verdict"] == guard.STALE
        assert guard.exit_code(r) == 1
        holders = {c["session"]: c for c in r["claims"]}
        assert holders[CLAIM_LABEL]["orphaned"] is True

    def test_the_report_names_where_the_identity_came_from(self, guard, sibling, tracker, log,
                                                           ps_dead):
        """Заимствование НАЗЫВАЕТСЯ вслух: без этого отчёт про ярлык `pid64051` пишет
        «завершился pid64036» — число из ДРУГОЙ записи, и проверить вывод читателю нечем."""
        write_card(tracker, "agent-x")
        self._journal(log)
        r = run(guard, sibling, tracker, log, "agent-x", ps=ps_dead)
        holder = {c["session"]: c for c in r["claims"]}[CLAIM_LABEL]
        assert holder["kin_source"] == CYCLE_LABEL
        assert CYCLE_LABEL in holder["session_state"] and "РОДСТВЕННОМУ" in holder["session_state"]

    def test_a_live_session_still_blocks(self, guard, sibling, tracker, log, ps_alive):
        """Обратный контроль: та же форма журнала, но процесс ЖИВ ⇒ карточка занята.
        Ложное «свободна» отдало бы карточку работающей сессии — это дороже ложного «занята»."""
        write_card(tracker, "agent-x")
        self._journal(log)
        r = run(guard, sibling, tracker, log, "agent-x", ps=ps_alive)
        assert r["verdict"] == guard.CLAIMED

    def test_claim_in_another_tree_still_blocks(self, guard, sibling, tracker, log, ps_dead):
        """Обратный контроль: держатель и мертвец — РАЗНЫЕ сессии в разных деревьях."""
        write_card(tracker, "agent-x")
        self._journal(log, cycle_tree="/tmp/spa_c999")
        r = run(guard, sibling, tracker, log, "agent-x", ps=ps_dead)
        assert r["verdict"] == guard.CLAIMED

    def test_claim_in_the_shared_tree_still_blocks(self, guard, sibling, tracker, log, ps_dead):
        """Обратный контроль к сужению 4: в главном дереве живут все, и родством оно не станет
        даже когда якорь там ровно один."""
        write_card(tracker, "agent-x")
        self._journal(log, claim_tree=MAIN_TREE, cycle_tree=MAIN_TREE)
        r = run(guard, sibling, tracker, log, "agent-x", ps=ps_dead)
        assert r["verdict"] == guard.CLAIMED

    def test_without_kin_the_fresh_claim_still_blocks(self, guard, sibling, tracker, log,
                                                      ps_dead):
        """Обратный контроль: якоря нет НИГДЕ ⇒ поведение прежнее. Родство не открывает дверь
        захватам, о которых ничего не измерено."""
        write_card(tracker, "agent-x")
        self._journal(log, anchor=None)
        r = run(guard, sibling, tracker, log, "agent-x", ps=ps_dead)
        assert r["verdict"] == guard.CLAIMED

    def test_shared_trees_unmeasured_keeps_the_old_verdict(self, guard, sibling, tracker, log,
                                                           ps_dead):
        """`shared_trees=None` — ровно состояние до правки: тот же журнал даёт `claimed`.
        Положительный контроль по построению (мутация «выключить признак»)."""
        write_card(tracker, "agent-x")
        self._journal(log)
        r = run(guard, sibling, tracker, log, "agent-x", ps=ps_dead, shared_trees=None)
        assert r["verdict"] == guard.CLAIMED

    def test_frontmatter_holder_is_measured_through_its_tree(self, guard, sibling, tracker,
                                                             log, ps_dead):
        """Второй вход в тот же дефект: `claimed_by` несёт ЯРЛЫК, записи-захвата может не быть
        вовсе — дерево спрашивается у ярлыка держателя отдельно (`extra_labels`)."""
        write_card(tracker, "agent-x")
        (tracker / "agent-x.md").write_text(
            "---\ntrackerStatus:\n  type: inbox\ntitle: Карточка\nstatus: new\n"
            f"claimed_by: {CLAIM_LABEL}\nclaimed_at: {_fmt(NOW - timedelta(minutes=75))}\n"
            "---\n\nтело\n", encoding="utf-8")
        write_log(log, [
            entry(CLAIM_LABEL, NOW - timedelta(minutes=76),
                  files=[f"{TREE}/nimbalyst-local/tracker/agent-x.md"],
                  summary="объявление владения без якоря"),
            entry(CYCLE_LABEL, NOW - timedelta(minutes=73), anchor=ANCHOR,
                  files=[f"{TREE}/scripts/a.py"]),
        ])
        r = run(guard, sibling, tracker, log, "agent-x", ps=ps_dead)
        assert r["verdict"] == guard.STALE
        assert [c for c in r["claims"] if c["orphaned"]]

    def test_file_overlap_of_a_dead_session_does_not_block_either(self, guard, sibling, tracker,
                                                                  log, ps_dead):
        """Пересечение по файлам — НЕЗАВИСИМОЕ измерение, а вердикт берёт худшее: починка
        одного близнеца из двух — не починка (#37)."""
        write_card(tracker, "agent-y")     # другая карточка: работает только пересечение
        write_log(log, [
            entry(CLAIM_LABEL, NOW - timedelta(minutes=75),
                  files=[f"{TREE}/scripts/check_undelivered_work.py"],
                  summary="объявление владения без якоря"),
            entry(CYCLE_LABEL, NOW - timedelta(minutes=73), anchor=ANCHOR,
                  files=[f"{TREE}/scripts/a.py"]),
        ])
        r = run(guard, sibling, tracker, log, "agent-y", ps=ps_dead,
                planned_files=["scripts/check_undelivered_work.py"])
        assert r["verdict"] == guard.STALE
        assert r["overlaps"] and all(o["orphaned"] for o in r["overlaps"])
