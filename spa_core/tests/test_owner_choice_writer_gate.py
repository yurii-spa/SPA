# LLM_FORBIDDEN
"""spa_core/tests/test_owner_choice_writer_gate.py — ответ владельца пишет только владелец.

**Что здесь проверяется (цикл #439, карточка `inbox-agent-mozhet-napisat-owner-choice-otvet`).**
Поле ``owner_choice`` в карточке решения — ЗАПИСЬ ОТВЕТА ВЛАДЕЛЬЦА. ADR-186 научил СТОРОЖА
отличать безымянную запись от ответа; здесь закрывается вторая половина — ПИСАТЕЛЬ, и
третья — МАРШРУТ починки уже написанного.

**Каждый положительный контроль воспроизводит реальную аварию 2026-08-29** (``git show
765363a8e``, 14:41Z): карточка ``owner-decision-tier-steakhouse-2026-08-29`` стояла в
``needs-owner`` с ``owner_choice: ""`` — владелец ещё НЕ отвечал, — и сессия одним коммитом
поставила ``status: ingested`` и ``owner_choice: "2"``. Проза того же коммита говорит
обратное («Выбран вариант 1… Вариант 2 — НЕ сделан»). Владелец ответил кнопкой на 6 ч 20 мин
позже и ответил **1**. Дальше обязательный шаг 0-офис прогон за прогоном звал человека
разрешить спор, которого не было.

**Байты аварии вшиты сюда дословно, а не читаются из git.** В CI дерево выписывается
мелкой глубиной, и ``git show 765363a8e`` там не ответит — тест «пропускался бы по
причине, не имеющей отношения к проверяемому поведению» (тот же класс, что фиксированная
дата в фикстуре, `.claude/rules/deployment.md`). Фикстуры ниже — точные frontmatter обеих
версий того коммита.

**Дат в фикстурах нет как ПРЕДМЕТА:** ``created: 2026-08-29`` — часть исторического
инцидента, не окно свежести. Свежесть здесь не судится вовсе.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.monitoring import owner_answer_delivery as oad  # noqa: E402


def _load(path: Path, name: str):
    """Загрузить модуль ПО ПУТИ: корневые скрипты не пакет, а импорт по имени хрупок."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, f"не удалось загрузить {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GUARD = _load(_REPO_ROOT / "scripts" / "check_owner_choice_authorship.py",
              "_owner_choice_guard")

# ── байты аварии 2026-08-29, коммит 765363a8e ────────────────────────────────
#
# Фикстуры собираются из ТЕКСТА и кодируются: bytes-литерал в Python не носит не-ASCII,
# а карточка владельца по инварианту #15 всегда по-русски. Байты от этого те же самые.
_BODY = "\n## Что случилось\n\nтело карточки, к записи ответа отношения не имеющее\n"

#: Как карточка выглядела ДО коммита: владелец ещё не отвечал (пустой скаляр).
ACCIDENT_BEFORE = ("""---
trackerStatus:
  type: owner-decision
title: "Твоё решение от 7 августа доехало не везде"
status: needs-owner
priority: high
owner: yuriycooleshov@gmail.com
owner_choice: ""
blocks: ""
created: 2026-08-29
---
""" + _BODY).encode("utf-8")

#: Как она уехала на origin: агент написал ОТВЕТ ВЛАДЕЛЬЦА и закрыл карточку.
ACCIDENT_AFTER = ("""---
trackerStatus:
  type: owner-decision
title: "ИСПОЛНЕНО: решение от 7 августа доведено до конца"
status: ingested
priority: high
owner: yuriycooleshov@gmail.com
owner_choice: "2"
blocks: ""
created: 2026-08-29
resolved: 2026-08-29
---
""" + _BODY).encode("utf-8")

#: Как ту же карточку записал ШТАТНЫЙ писатель, когда владелец нажал кнопку: тот же
#: файл, но под значением стоит подпись — провенанс и отметка писателя в журнале.
OWNER_ANSWERED = ("""---
trackerStatus:
  type: owner-decision
title: "ИСПОЛНЕНО: решение от 7 августа доведено до конца"
status: ingested
priority: high
owner: yuriycooleshov@gmail.com
owner_choice: 1
blocks: ""
created: 2026-08-29
resolved: 2026-08-29
owner_answered_at: 2026-08-29T21:00:44.966430+00:00
owner_answer_via: telegram
owner_answered_by: 258651137
status_trail:
  - "2026-08-29T21:00:44.966648+00:00 needs-owner -> owner-done \u00b7 owner_answer.record_owner_answer"
---
""" + _BODY).encode("utf-8")


class TestTheAccidentIsRefused:
    """Положительный контроль: ровно то, что уехало 2026-08-29, теперь отклоняется."""

    def test_agent_writing_owner_choice_is_a_finding(self):
        kind, why = GUARD.verdict(ACCIDENT_AFTER, ACCIDENT_BEFORE)
        assert kind == "finding", why
        assert "БЕЗ ЕДИНОГО признака авторства" in why
        assert "765363a8e" in why, "отказ обязан называть аварию, а не только правило"

    def test_the_empty_scalar_is_read_as_no_answer_not_as_a_value(self):
        """``owner_choice: ""`` — «владелец ещё не ответил», а не «ответ пустой».

        Если бы пустой скаляр читался как значение, авария выглядела бы сменой одного
        ответа на другой, и весь класс исчез бы из виду.
        """
        assert GUARD.choice_of(ACCIDENT_BEFORE) is None
        assert GUARD.choice_of(ACCIDENT_AFTER) == '"2"'

    def test_a_brand_new_card_carrying_an_unsigned_answer_is_a_finding(self):
        """Карточки на origin нет вовсе — подделка от этого не перестаёт быть подделкой."""
        kind, why = GUARD.verdict(ACCIDENT_AFTER, None)
        assert kind == "finding", why


class TestLegitimateWritersStillPass:
    """Обратные контроли — по ОДНОЙ оси каждый: сторож не смеет краснеть на верной работе.

    Ось у каждого своя намеренно: в цепочке отказов условия заслоняют друг друга, и
    контроль, красящий сразу две, не доказывает ни одной.
    """

    def test_button_written_answer_passes(self):
        """Ось: авторство ЕСТЬ. Всё остальное как в аварии — значение меняется."""
        kind, why = GUARD.verdict(OWNER_ANSWERED, ACCIDENT_AFTER)
        assert kind == "ok", why
        assert "подписан" in why

    def test_unchanged_choice_passes(self):
        """Ось: значение НЕ меняется. Авторства по-прежнему нет — и это не важно."""
        kind, why = GUARD.verdict(ACCIDENT_AFTER, ACCIDENT_AFTER)
        assert kind == "ok", why
        assert "не меняется" in why

    def test_card_without_any_answer_passes(self):
        """Ось: ответа в уезжающей копии НЕТ вовсе."""
        kind, why = GUARD.verdict(ACCIDENT_BEFORE, ACCIDENT_BEFORE)
        assert kind == "ok", why

    def test_card_without_answer_against_answered_origin_passes(self):
        """Ось: уезжает копия БЕЗ ответа, а на origin ответ есть — записи мы не делаем."""
        kind, why = GUARD.verdict(ACCIDENT_BEFORE, OWNER_ANSWERED)
        assert kind == "ok", why


class TestUnmeasuredIsRefusalNotClean:
    """Третий исход: не измерено ⇒ ОТКАЗ. Слепое «претензий нет» и есть дефект."""

    def test_missing_local_file_is_unmeasured_not_clean(self, tmp_path):
        card = tmp_path / "nimbalyst-local" / "tracker" / "own-x.md"
        report = GUARD.check([str(card)], _REPO_ROOT)
        assert report["blind"], "файла нет — судить нечем, это не «чисто»"
        assert GUARD.main(["--files", str(card)]) == GUARD.UNMEASURED

    def test_unreadable_ref_is_unmeasured_not_clean(self, tmp_path):
        card = tmp_path / "nimbalyst-local" / "tracker" / "own-x.md"
        card.parent.mkdir(parents=True)
        card.write_bytes(ACCIDENT_AFTER)
        rc = GUARD.main(["--files", str(card), "--ref", "refs/nope/nothing-here"])
        assert rc == GUARD.UNMEASURED

    def test_a_set_without_cards_says_nothing_rather_than_ok(self):
        """Пуш без карточек проверку не будит — отбор это ТРИГГЕР, а не суждение."""
        assert GUARD.main(["--files", "spa_core/risk/policy.py"]) == GUARD.CLEAN
        assert not GUARD.is_card("spa_core/risk/policy.py")

    def test_the_board_is_not_a_card(self):
        """Доска — авто-индекс: у неё нет решения, и судить в ней нечего."""
        assert not GUARD.is_card("nimbalyst-local/tracker/_BOARD.md")
        assert GUARD.is_card("nimbalyst-local/tracker/own-anything.md")


class TestBothDoorsCallTheSameImplementation:
    """Проводка: интерлок обязан стоять в ОБОИХ CLI — урок ADR-номеров дословно.

    26.08 блок жил строками внутри `push_to_github.py::main()`, а `push_to_github_batch.py`
    — drop-in на ту же `batch_push`, под которым стоит `safe_site_push.py`, — его не имел:
    корневой CLI отказывал rc=7, batch печатал «DRY OK» rc=0, и через эту дверь уехал
    второй ADR-145. Проверяется ФОРМА ВЫЗОВА, а не упоминание имени: docstring «как у X»
    читается как вызывающий код и однажды уже чуть не закрыл карточку ложно.
    """

    @pytest.mark.parametrize("cli", ["push_to_github.py", "push_to_github_batch.py"])
    def test_the_cli_calls_the_interlock(self, cli):
        import ast
        tree = ast.parse((_REPO_ROOT / cli).read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "enforce_owner_choice_authorship"]
        assert calls, f"{cli}: интерлок не ВЫЗЫВАЕТСЯ (упоминание в тексте не считается)"

    @pytest.mark.parametrize("cli", ["push_to_github.py", "push_to_github_batch.py"])
    def test_the_refusal_exits_with_the_named_code(self, cli):
        import ast
        tree = ast.parse((_REPO_ROOT / cli).read_text(encoding="utf-8"))
        handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)
                    and isinstance(n.type, ast.Name)
                    and n.type.id == "OwnerChoiceUnattributed"]
        assert handlers, f"{cli}: отказ интерлока не перехватывается — пуш пошёл бы дальше"
        exits = [n for h in handlers for n in ast.walk(h)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "exit"]
        assert exits, f"{cli}: перехват есть, а выхода нет — отказ ничего не останавливает"

    def test_the_batch_cli_reuses_the_root_implementation(self):
        """Вторая КОПИЯ реализации — и есть тот дефект. Здесь обязан быть ре-экспорт."""
        text = (_REPO_ROOT / "push_to_github_batch.py").read_text(encoding="utf-8")
        assert "enforce_owner_choice_authorship = _root_push.enforce_owner_choice_authorship" in text
        assert "def enforce_owner_choice_authorship" not in text, \
            "batch-CLI завёл СВОЮ реализацию — ровно та авария, что с ADR-145"

    def test_the_root_pusher_defines_it_once(self):
        root = _load(_REPO_ROOT / "push_to_github.py", "_root_push_under_test")
        assert callable(root.enforce_owner_choice_authorship)
        assert root.OWNER_CHOICE_INTERLOCK_EXIT not in (0, root.ADR_INTERLOCK_EXIT), \
            "код отказа обязан отличаться от успеха и от соседнего интерлока"

    def test_a_push_without_cards_leaves_the_interlock_silent(self):
        root = _load(_REPO_ROOT / "push_to_github.py", "_root_push_silent")
        assert root.enforce_owner_choice_authorship(["spa_core/risk/policy.py"]) is False

    def test_the_guard_is_refused_when_missing_not_skipped(self, tmp_path):
        """Сторожа нет ⇒ ОТКАЗ, а не тихий пропуск: fail-CLOSED (инвариант #2)."""
        root = _load(_REPO_ROOT / "push_to_github.py", "_root_push_missing_guard")
        (tmp_path / "scripts").mkdir()
        fake_runner = tmp_path / "push_to_github.py"
        fake_runner.write_text("")
        with pytest.raises(root.OwnerChoiceUnattributed):
            root.enforce_owner_choice_authorship(
                ["nimbalyst-local/tracker/own-x.md"], runner_file=str(fake_runner))


class TestRepairRouteExistsAndIsNarrow:
    """Пункт 3 карточки: что делать с уже стоящей безымянной записью — решено, не молча.

    Маршрут обязан СУЩЕСТВОВАТЬ: без него интерлок оставил бы находку, которую нельзя
    закрыть никак, а проверку, мешающую верной работе, обходят — и тогда она не поймает
    настоящую подделку.
    """

    def test_the_repair_replaces_the_unsigned_value_with_the_owners_answer(self):
        cand, why, fields = oad.repair_unattributed_choice(OWNER_ANSWERED, ACCIDENT_AFTER)
        assert cand is not None, why
        assert oad._read_fields(cand, ("owner_choice",))["owner_choice"] == "1"
        assert fields[oad.UNATTRIBUTED_REMOVED_FIELDS["owner_choice"]] == '"2"'

    def test_nothing_is_erased_silently(self):
        """Снятое значение обязано остаться ВИДНЫМ: молча стёртая подделка неотличима
        от подделки, которой не было."""
        cand, _why, _f = oad.repair_unattributed_choice(OWNER_ANSWERED, ACCIDENT_AFTER)
        removed = oad.UNATTRIBUTED_REMOVED_FIELDS["owner_choice"]
        assert oad._read_fields(cand, (removed,))[removed] == '"2"'
        assert oad.key_occurrences(cand, "owner_choice") == 1, \
            "второе вхождение ключа = невидимая запись (авария 30.08)"

    def test_the_body_of_the_decision_is_never_touched(self):
        cand, _why, _f = oad.repair_unattributed_choice(OWNER_ANSWERED, ACCIDENT_AFTER)
        assert oad.card_parts(cand)[1] == oad.card_parts(ACCIDENT_AFTER)[1]

    def test_the_repaired_card_passes_the_new_interlock(self):
        """Гасим МАРШРУТ, а не проверку: починка обязана проходить свой же гейт."""
        cand, _why, _f = oad.repair_unattributed_choice(OWNER_ANSWERED, ACCIDENT_AFTER)
        kind, why = GUARD.verdict(cand, ACCIDENT_AFTER)
        assert kind == "ok", why

    # ── по ОДНОЙ оси на контроль: цепочка отказов иначе заслоняет сама себя ──

    def test_axis_origin_has_authorship_refuses(self):
        """Ось: на origin ЕСТЬ подпись ⇒ это спор двух ответов, сторону не выбираем."""
        signed_origin = ACCIDENT_AFTER.replace(
            b"resolved: 2026-08-29\n",
            b"resolved: 2026-08-29\nowner_answered_at: 2026-08-29T14:41:00+00:00\n")
        cand, why, _f = oad.repair_unattributed_choice(OWNER_ANSWERED, signed_origin)
        assert cand is None
        assert "пятого исхода НЕ держатся" in why

    def test_axis_our_provenance_incomplete_refuses(self):
        """Ось: у НАС провенанс неполный ⇒ отмыть свою безымянную запись нельзя."""
        text = OWNER_ANSWERED.decode("utf-8")
        text = text.replace("owner_answered_by: 258651137\n", "")
        text = "\n".join(ln for ln in text.splitlines()
                         if "status_trail" not in ln
                         and "record_owner_answer" not in ln) + "\n"
        partial = text.encode("utf-8")
        cand, why, _f = oad.repair_unattributed_choice(partial, ACCIDENT_AFTER)
        assert cand is None, why
        assert "пятого исхода НЕ держатся" in why

    def test_axis_origin_carries_no_value_refuses(self):
        """Ось: на origin значения НЕТ ⇒ это не безымянная запись, а отсутствие следа."""
        cand, why, _f = oad.repair_unattributed_choice(OWNER_ANSWERED, ACCIDENT_BEFORE)
        assert cand is None
        assert "не написан вовсе" in why

    def test_axis_already_repaired_refuses(self):
        """Ось: регистр снятой записи на origin УЖЕ стоит ⇒ поверх молча не пишем.

        Ось выделена намеренно. Взять готовый результат починки и подать его обратно
        нельзя: он несёт провенанс, и отказ пришёл бы РАНЬШЕ — от условия «на origin есть
        подпись». Два условия на одну ось не красят ни одной, поэтому здесь строится
        состояние, где подписи по-прежнему нет, а регистр уже есть: ровно то, что
        оставила бы недоделанная починка руками.
        """
        removed = oad.UNATTRIBUTED_REMOVED_FIELDS["owner_choice"]
        half_repaired = ACCIDENT_AFTER.replace(
            b"resolved: 2026-08-29\n",
            b"resolved: 2026-08-29\n" + f"{removed}: \"5\"\n".encode())
        assert not oad.attribution_keys(half_repaired), \
            "фикстура обязана остаться БЕЗ подписи, иначе ось подменится"
        cand, why, _f = oad.repair_unattributed_choice(OWNER_ANSWERED, half_repaired)
        assert cand is None
        assert "уже стоит регистр" in why

    def test_axis_doubled_key_on_origin_refuses(self):
        """Ось: ключ на origin написан дважды ⇒ какое вхождение читают, отсюда не видно."""
        doubled = ACCIDENT_AFTER.replace(b'owner_choice: "2"\n',
                                         b'owner_choice: "2"\nowner_choice: "3"\n')
        cand, why, _f = oad.repair_unattributed_choice(OWNER_ANSWERED, doubled)
        assert cand is None
        assert "НЕСКОЛЬКО раз" in why

    def test_the_proof_judges_the_outcome_not_the_construction(self):
        """Доказательство обязано ОТВЕРГНУТЬ кандидата, тронувшего тело решения."""
        cand, _why, fields = oad.repair_unattributed_choice(OWNER_ANSWERED, ACCIDENT_AFTER)
        sabotaged = cand.replace(_BODY.encode('utf-8'), '\n## подменённое тело\n'.encode('utf-8'))
        ok, why = oad.verify_repair(ACCIDENT_AFTER, sabotaged, fields)
        assert not ok and "тело" in why

    def test_the_proof_rejects_an_unnamed_extra_line(self):
        cand, _why, fields = oad.repair_unattributed_choice(OWNER_ANSWERED, ACCIDENT_AFTER)
        sabotaged = cand.replace(b"owner_choice: 1\n", b"owner_choice: 1\nstatus: done\n")
        ok, why = oad.verify_repair(ACCIDENT_AFTER, sabotaged, fields)
        assert not ok, why

    def test_the_proof_rejects_a_key_written_twice(self):
        """Ключ, написанный ДВАЖДЫ, — невидимая запись: читатель берёт первое вхождение.

        Условие «ключ ровно один раз» первым заходом ПЕРЕЖИЛО мутацию: его заслоняли
        соседние проверки, и в одиночку оно не проверяло ничего. Здесь дублируется
        строка НАЗВАННОГО ключа — все прочие условия доказательства при этом держатся,
        поймать подмену может только оно.
        """
        cand, _why, fields = oad.repair_unattributed_choice(OWNER_ANSWERED, ACCIDENT_AFTER)
        line = b"owner_answered_at: 2026-08-29T21:00:44.966430+00:00\n"
        assert cand.count(line) == 1, "фикстура рассчитывает ровно на одно вхождение"
        doubled = cand.replace(line, line + line, 1)
        assert oad.key_occurrences(doubled, "owner_answered_at") == 2
        ok, why = oad.verify_repair(ACCIDENT_AFTER, doubled, fields)
        assert not ok, "задвоенный ключ принят — читатель следа увидел бы не то"
        assert "раз(а)" in why

    def test_the_proof_rejects_a_value_the_reader_cannot_see(self):
        """Строка есть, а читатель видит другое — ровно авария 30.08."""
        cand, _why, fields = oad.repair_unattributed_choice(OWNER_ANSWERED, ACCIDENT_AFTER)
        sabotaged = cand.replace(b"owner_choice: 1\n", b"owner_choice: 9\n")
        ok, why = oad.verify_repair(ACCIDENT_AFTER, sabotaged, fields)
        assert not ok and "owner_choice" in why


class TestTheRepairRouteIsInvocableNotJustImportable:
    """Новый маршрут проводится ПРИ РОЖДЕНИИ: функция, которую нечем позвать, — не маршрут.

    Отказ интерлока называет починку словами и обязан называть то, что существует;
    иначе сессия, упёршаяся в отказ, обойдёт его флагом — и он не поймает подделку.
    """

    def test_the_delivery_module_exposes_the_repair_action(self):
        import argparse
        parser_seen = {}
        real = argparse.ArgumentParser.add_argument

        def spy(self, *a, **k):
            if a:
                parser_seen[a[0]] = True
            return real(self, *a, **k)

        argparse.ArgumentParser.add_argument = spy
        try:
            with pytest.raises(SystemExit):
                oad.main(["--help"])
        finally:
            argparse.ArgumentParser.add_argument = real
        assert "--repair-unattributed" in parser_seen, \
            "маршрут починки нельзя позвать из командной строки"

    def test_the_interlock_names_a_route_that_exists(self):
        root = _load(_REPO_ROOT / "push_to_github.py", "_root_push_names_route")
        import inspect
        src = inspect.getsource(root.enforce_owner_choice_authorship)
        assert "repair_unattributed_choice" in src
        assert callable(oad.repair_unattributed_choice), \
            "отказ называет маршрут, которого нет — так сторожа и обходят"

    def test_the_repair_refuses_when_the_live_copy_is_absent(self, tmp_path):
        """Третий исход у маршрута тоже есть: чинить нечем ≠ чинить нечего."""
        cand, why = oad.repair_card_from_trees(
            "own-nope.md", str(_REPO_ROOT), str(tmp_path))
        assert cand is None
        assert "нет в живом дереве" in why


class TestTheLivePopulationIsNotRed:
    """Сторож, краснеющий на верном состоянии, обходят — и он не поймает настоящее.

    Замер до написания правила (цикл #439): на ``origin/main`` карточек 845, с непустым
    ``owner_choice`` — 88, ИЗМЕНЁННЫХ против origin — 0. Здесь этот замер закреплён:
    выписанное на origin дерево обязано быть чистым по построению.
    """

    def test_every_card_of_the_tree_agrees_with_origin_or_is_signed(self):
        tracker = _REPO_ROOT / "nimbalyst-local" / "tracker"
        if not tracker.is_dir():
            pytest.skip(f"трекера нет в этом дереве: {tracker}")
        if subprocess.run(["git", "rev-parse", "--verify", "origin/main"],
                          capture_output=True, cwd=str(_REPO_ROOT)).returncode != 0:
            pytest.skip("origin/main в этом дереве не разрешается — сравнивать не с чем")
        cards = [str(p) for p in sorted(tracker.glob("*.md")) if GUARD.is_card(p.name)]
        report = GUARD.check(cards, _REPO_ROOT)
        assert not report["findings"], (
            "живые карточки дерева краснят интерлок: "
            + "; ".join(f"{n}: {w}" for n, w in report["findings"][:5]))
