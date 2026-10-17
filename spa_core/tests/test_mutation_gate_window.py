"""ОКНО у ВТОРОГО мутирующего прибора: `scripts/mutation_gate.py` (ADR-773, цикл #889).

Предмет — не «верно ли гейт мерит мутантов» (это его собственный вопрос), а другой:
**что остаётся в дереве и кто об этом скажет, если гейт НЕ ДОЖИЛ до возврата.**

Почему батарея нужна отдельно от `test_delta_mutation_window.py`. Та закрепляет окно у
прибора дельты. Заказ владельца G772 п. 2 назвал ВТОРОЙ инструмент той же формы: гейт
подменял файл на месте, держал исходный текст в локальной переменной и возвращал его в
`finally`. `SIGKILL` не исполняет ни `finally`, ни `atexit`, ни обработчик сигнала —
свойство ОС, а не этого кода, — поэтому единственная копия исходных байтов умирала вместе
с процессом.

Замер ДО правки (одноразовое дерево, настоящий `SIGKILL` настоящего гейта через 12 с):
`spa_core/risk/policy.py` остался с мутацией `risk_apy_max_bound_flip`, то есть с
ОТКЛЮЧЁННОЙ верхней границей APY единственного hard-гейта системы (инв. #1). Читатель
окна при этом отвечал «✅ ОКНА НЕТ, дерево чисто» (код 0), а `enforce_no_delivered_mutant`
пушера — «ПРОПУСТИЛ БЫ». Нагрузка тяжелее, чем у находки #888: гейт мутирует
`risk/policy.py`, `governance/kill_switch.py`, `execution/reconciliation.py`,
`execution/gate_chain_audit.py` — файлы, которые читает дневной цикл.

Устройство — по звеньям, у каждого обратная сторона с НАЗВАННЫМ звеном:

* окно объявляется ДО первой подмены, и слепок кладётся ФАЙЛОМ (по хешу вернуть нельзя);
* запись пишется в ТОМ ЖЕ формате, что у прибора дельты, и её читает ТОТ ЖЕ читатель —
  своей копии правила у гейта нет (две копии разошлись бы при первой правке формата);
* поле `tool` называет, КТО открыл окно: у гейта файла-спецификации нет вовсе, и без
  этого поля наследник искал бы `--spec`, которого не существует;
* второе окно в том же дереве ОТКАЗЫВАЕТ;
* читателя нет на месте / он без нужного API ⇒ прогон НЕ СОСТОИТСЯ (код 3), и ни один
  файл не тронут. Третий исход не выдаётся ни за «чисто», ни за «гейт провалился»
  (инв. #17, урок `pyflakes` цикла #465);
* байты после прогона СВЕРЯЮТСЯ со слепком, и несошедшиеся возвращаются; возврат неполон
  ⇒ запись ОСТАЁТСЯ и вердикт «НЕ ИЗМЕРЕНО» — дерево с мутантом не имеет права
  выглядеть чистым по мерке собственного сторожа, даже когда сам гейт PASS;
* `--repo-root` доходит до ПРОВОДКИ: мутируется и прогоняется ОДНО дерево, названное
  вызывающим, иначе pytest судил бы о чужом коде.

Часы, номер процесса и прогон мутантов — ВХОДЫ. Литеральных дат и литеральных pid в файле
нет (`.claude/rules/deployment.md` §§ «ВРЕМЯ В ТЕСТАХ», «ЛИЧНОСТЬ ПРОЦЕССА»).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_GATE = os.path.join(_REPO_ROOT, "scripts", "mutation_gate.py")
_TOOL = os.path.join(_REPO_ROOT, "scripts", "delta_mutation_run.py")


def _load(path, name):
    """Ввезти модуль из файла. Регистрация в `sys.modules` ДО исполнения — требование
    `dataclasses`: строковые аннотации разрешаются через `sys.modules[__module__]`, и
    без записи `@dataclass` падает `AttributeError: 'NoneType' ... '__dict__'`. Ровно так
    отказал первый прогон правки #889 — и отказал ВЕРНО, fail-CLOSED поймал дефект
    загрузки раньше, чем прибор тронул хоть один файл."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


mg = _load(_GATE, "_mutation_gate_under_test")
dmr = _load(_TOOL, "_delta_window_for_gate_test")


# ───────────────────────────── подмостки ─────────────────────────────

def _scene(tmp_path):
    """Одноразовое дерево с читателем окна и всеми целями мутаций гейта.

    Цели создаются СТУБАМИ, а не копиями настоящих money-path модулей: предмет батареи —
    запись окна, а не поведение RiskPolicy. Текст у каждого стуба СВОЙ, иначе слепки
    четырёх файлов совпали бы и подмена одного молча зачлась бы за другой.
    """
    root = tmp_path / "tree"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "delta_mutation_run.py").write_bytes(
        open(_TOOL, "rb").read())
    rels = sorted({m.file for m in mg.MUTATIONS})
    for rel in rels:
        target = root.joinpath(*rel.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# стуб цели мутаций: {rel}\nVALUE = {len(rel)}\n",
                          encoding="utf-8")
    return str(root), rels


def _record(root):
    with open(dmr.window_record_path(root), encoding="utf-8") as fh:
        return json.load(fh)


# ═════════════════════════════════════════════════════════════════════
# 1. Реестр мутаций — запись окна без имени мутации бесполезна
# ═════════════════════════════════════════════════════════════════════
def test_every_curated_mutation_names_itself():
    """Безымянная мутация в записи окна = «файл тронут, чем — неизвестно».

    Читатель окна называет наследнику мутации-кандидаты ПО ИМЕНИ; пустое имя он
    отбрасывает, и файл остался бы названным без объяснения.
    """
    unnamed = [m.file for m in mg.MUTATIONS if not m.name]
    assert unnamed == [], f"мутации без имени: {unnamed}"


def test_every_mutation_target_exists_in_this_repo():
    """Реестр не должен протухать: несуществующая цель = вечное «не измерено»."""
    missing = [m.file for m in mg.MUTATIONS
               if not os.path.exists(os.path.join(_REPO_ROOT, m.file))]
    assert missing == [], f"цели мутаций, которых нет в репо: {missing}"


def test_targets_are_the_money_path_modules():
    """Предмет гейта назван в батарее ЗАМЕРОМ, а не прозой шапки.

    Если набор целей однажды сузится до безобидных файлов, рассказ выше («нагрузка
    тяжелее, чем у #888») перестанет быть правдой молча — тест этого не допустит.
    """
    files = {m.file for m in mg.MUTATIONS}
    assert "spa_core/risk/policy.py" in files
    assert "spa_core/governance/kill_switch.py" in files


# ═════════════════════════════════════════════════════════════════════
# 2. Окно объявляется ДО первой подмены
# ═════════════════════════════════════════════════════════════════════
def test_open_window_snapshots_every_target_before_any_substitution(tmp_path):
    """Слепок КАЖДОЙ цели лежит файлом, и байты совпадают с исходными."""
    root, rels = _scene(tmp_path)
    record = mg.open_gate_window(mg.load_window_facility(root), root)

    assert sorted(item["file"] for item in record["files"]) == rels
    for item in record["files"]:
        copy = os.path.join(root, *item["pristine_copy"].split("/"))
        assert os.path.isfile(copy), f"слепка нет файлом: {item['file']}"
        target = os.path.join(root, *item["file"].split("/"))
        assert open(copy, "rb").read() == open(target, "rb").read()


def test_window_record_names_the_tool_that_opened_it(tmp_path):
    """`tool` = гейт, а не прибор дельты: иначе наследник искал бы `--spec`."""
    root, _ = _scene(tmp_path)
    mg.open_gate_window(mg.load_window_facility(root), root)
    doc = _record(root)
    assert doc["tool"] == "scripts/mutation_gate.py"
    assert doc["spec_path"] is None
    assert "mutation_gate" in (doc["spec_title"] or "")


def test_the_shared_reader_understands_the_gate_record(tmp_path):
    """Межинструментальная совместимость: запись гейта читает ЧИТАТЕЛЬ ПРИБОРА.

    Обратная сторона звена «своей копии сверки у гейта нет»: если формат разойдётся,
    этот тест покраснеет, а не одна дверь начнёт пропускать мутанта.
    """
    root, rels = _scene(tmp_path)
    mg.open_gate_window(mg.load_window_facility(root), root)

    clean = dmr.window_state(root)
    assert clean["state"] == dmr.WINDOW_OPEN_PRISTINE
    assert "scripts/mutation_gate.py" in clean["detail"]

    victim = rels[0]
    with open(os.path.join(root, *victim.split("/")), "a", encoding="utf-8") as fh:
        fh.write("MUTANT = True\n")
    held = dmr.window_state(root)
    assert held["state"] == dmr.WINDOW_HOLDS_MUTANT
    assert held["rc"] == dmr.RC_WINDOW_FINDING
    assert victim in [m["file"] for m in held["mutants"]]


def test_several_mutations_on_one_file_are_named_as_candidates(tmp_path):
    """Читатель не выдаёт ОДНУ из пяти мутаций за установленный факт.

    По байтам слепка нельзя узнать, какая именно мутация лежит. Прежняя форма печатала
    `mutations[0]` утвердительно — у спецификации с одной мутацией на файл это совпадало,
    а у кураторского набора гейта на `risk/policy.py` их пять.
    """
    root, _ = _scene(tmp_path)
    mg.open_gate_window(mg.load_window_facility(root), root)
    policy = "spa_core/risk/policy.py"
    many = [m.name for m in mg.MUTATIONS if m.file == policy]
    assert len(many) > 1, "сцена потеряла смысл: мутаций на policy.py стало ≤ 1"

    with open(os.path.join(root, *policy.split("/")), "a", encoding="utf-8") as fh:
        fh.write("MUTANT = True\n")
    detail = dmr.window_state(root)["detail"]
    assert "одна из мутаций окна по этому файлу" in detail
    for name in many:
        assert name in detail, f"кандидат не назван: {name}"


def test_second_window_in_the_same_tree_is_refused(tmp_path):
    """Второе окно затёрло бы слепок первого, и мутант стал бы вечным."""
    root, _ = _scene(tmp_path)
    facility = mg.load_window_facility(root)
    first = mg.open_gate_window(facility, root)
    with pytest.raises(mg.WindowUnavailable) as exc:
        mg.open_gate_window(facility, root)
    assert "УЖЕ открыто окно" in str(exc.value)
    # слепок первого окна НЕ тронут
    assert _record(root)["opened_at"] == first["opened_at"]


def test_unreadable_target_refuses_to_open_the_window(tmp_path):
    """Нет байтов цели ⇒ слепка нет ⇒ окно объявить НЕЧЕМ (а не открыть пустое)."""
    root, rels = _scene(tmp_path)
    os.unlink(os.path.join(root, *rels[0].split("/")))
    with pytest.raises(mg.WindowUnavailable) as exc:
        mg.open_gate_window(mg.load_window_facility(root), root)
    assert rels[0] in str(exc.value)
    assert not os.path.exists(dmr.window_record_path(root))


# ═════════════════════════════════════════════════════════════════════
# 3. Читателя нет на месте — это ТРЕТИЙ ИСХОД, а не разрешение мутировать
# ═════════════════════════════════════════════════════════════════════
def test_missing_reader_is_named_not_assumed(tmp_path):
    """Путь читателя — ВХОД: сцена не удаляет файл из настоящего дерева."""
    absent = str(tmp_path / "нет-такого" / "delta_mutation_run.py")
    with pytest.raises(mg.WindowUnavailable) as exc:
        mg.load_window_facility(str(tmp_path), reader_path=absent)
    assert "читателя окна нет" in str(exc.value)
    assert absent in str(exc.value)


def test_reader_without_the_api_is_refused_not_used(tmp_path):
    """Устаревшая копия инструмента ⇒ отказ с ПЕРЕЧНЕМ отсутствующего.

    Это и есть причина, по которой `scripts/delta_mutation_run.py` добавлен в
    `TOOLCHAIN_FILES` (заказ G772 п. 3): копия из чужого дерева может отстать от формата.
    """
    stale = tmp_path / "stale_reader.py"
    stale.write_text("def window_state(*a, **k):\n    return {}\n", encoding="utf-8")
    with pytest.raises(mg.WindowUnavailable) as exc:
        mg.load_window_facility(str(tmp_path), reader_path=str(stale))
    msg = str(exc.value)
    assert "open_window" in msg and "restore_window" in msg


def test_unloadable_reader_names_the_exception(tmp_path):
    """Читатель есть, но падает на импорте ⇒ причина НАЗВАНА, а не проглочена."""
    broken = tmp_path / "broken_reader.py"
    broken.write_text("raise ValueError('сломан намеренно')\n", encoding="utf-8")
    with pytest.raises(mg.WindowUnavailable) as exc:
        mg.load_window_facility(str(tmp_path), reader_path=str(broken))
    assert "ValueError" in str(exc.value)
    assert "сломан намеренно" in str(exc.value)


# ═════════════════════════════════════════════════════════════════════
# 4. Сверка ПОСЛЕ прогона: возврат неполон ⇒ запись остаётся
# ═════════════════════════════════════════════════════════════════════
def test_close_restores_the_drifted_bytes_and_closes(tmp_path):
    """Уцелевший `finally` — быстрый путь; закрытие сверяет байты и чинит остаток."""
    root, rels = _scene(tmp_path)
    facility = mg.load_window_facility(root)
    mg.open_gate_window(facility, root)
    victim = os.path.join(root, *rels[0].split("/"))
    before = open(victim, "rb").read()
    with open(victim, "a", encoding="utf-8") as fh:
        fh.write("MUTANT = True\n")

    out = mg.close_gate_window(facility, root)
    assert out["restored"] == [rels[0]]
    assert sorted(out["already_clean"]) == rels[1:]
    assert out["closed"] is True
    assert open(victim, "rb").read() == before
    assert dmr.window_state(root)["state"] == dmr.WINDOW_NONE


def test_clean_run_leaves_no_window_record(tmp_path):
    """Чистый прогон записи НЕ оставляет: «записи нет» обязано значить «чисто»."""
    root, _ = _scene(tmp_path)
    facility = mg.load_window_facility(root)
    mg.open_gate_window(facility, root)
    mg.close_gate_window(facility, root)
    assert not os.path.exists(dmr.window_record_path(root))
    assert not os.path.isdir(os.path.join(root, dmr.WINDOW_DIR))


def test_corrupt_snapshot_keeps_the_record_and_refuses(tmp_path):
    """Испорченный слепок = вернуть НЕ К ЧЕМУ. Запись НЕ снимается.

    Обратная сторона звена: снять её значило бы объявить дерево с мутантом чистым по
    мерке самого сторожа.
    """
    root, rels = _scene(tmp_path)
    facility = mg.load_window_facility(root)
    record = mg.open_gate_window(facility, root)
    victim_rel = rels[0]
    with open(os.path.join(root, *victim_rel.split("/")), "a", encoding="utf-8") as fh:
        fh.write("MUTANT = True\n")
    copy_rel = next(i["pristine_copy"] for i in record["files"]
                    if i["file"] == victim_rel)
    with open(os.path.join(root, *copy_rel.split("/")), "a", encoding="utf-8") as fh:
        fh.write("# слепок испорчен\n")

    with pytest.raises(mg.WindowUnavailable) as exc:
        mg.close_gate_window(facility, root)
    assert "возврат НЕ ПОЛОН" in str(exc.value)
    assert "--window-restore" in str(exc.value)
    assert os.path.exists(dmr.window_record_path(root)), "запись окна СНЯТА — fail-OPEN"


def test_unreadable_record_after_the_run_is_unmeasured(tmp_path):
    """Нечитаемая запись ⇒ «НЕ ИЗМЕРЕНО», а не «чисто» (инв. #17)."""
    root, _ = _scene(tmp_path)
    facility = mg.load_window_facility(root)
    mg.open_gate_window(facility, root)
    with open(dmr.window_record_path(root), "w", encoding="utf-8") as fh:
        fh.write("{это не json")
    with pytest.raises(mg.WindowUnavailable) as exc:
        mg.close_gate_window(facility, root)
    assert "НЕ ИЗМЕРЕНО" in str(exc.value)


# ═════════════════════════════════════════════════════════════════════
# 5. ПРОВОДКА main(): три исхода и ни одного тронутого файла без окна
# ═════════════════════════════════════════════════════════════════════
def _stub_gate(monkeypatch, *, survivors=0, raises=None):
    """Подменить сам мутационный прогон: предмет этих тестов — проводка окна."""
    calls: list[dict] = []

    def fake(threshold=0, repo_root=None):
        calls.append({"threshold": threshold, "repo_root": repo_root})
        if raises is not None:
            raise raises
        return {"module": "mutation_gate", "version": "v1.0",
                "repo_root": str(repo_root), "threshold": threshold,
                "n_mutants": 1, "n_killed": 1 - survivors,
                "n_survivors": survivors, "n_anchor_errors": 0,
                "survivors": ["x"] * survivors, "pass": survivors <= threshold,
                "elapsed_s": 0.0, "results": []}

    monkeypatch.setattr(mg, "run_gate", fake)
    return calls


def test_main_refuses_without_a_window_and_runs_nothing(tmp_path, monkeypatch, capsys):
    """Окно объявить нечем ⇒ код 3 и НИ ОДНОГО вызова прогона.

    Головной контроль класса: прогон без записи — это и есть дефект, против которого
    написан ADR-773. «Не измерено» не выдаётся ни за PASS, ни за FAIL.
    """
    calls = _stub_gate(monkeypatch)
    monkeypatch.setattr(mg, "load_window_facility",
                        lambda *a, **k: (_ for _ in ()).throw(
                            mg.WindowUnavailable("читателя окна нет (сцена)")))
    rc = mg.main(["--repo-root", str(tmp_path)])
    assert rc == mg.RC_NOT_MEASURED == 3
    assert calls == [], "прогон пошёл БЕЗ окна"
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().err


def test_main_refuses_when_the_tree_already_holds_a_window(tmp_path, monkeypatch,
                                                           capsys):
    """Дерево под чужим окном ⇒ код 3, и прогон не начинается."""
    root, _ = _scene(tmp_path)
    calls = _stub_gate(monkeypatch)
    mg.open_gate_window(mg.load_window_facility(root), root)
    rc = mg.main(["--repo-root", root])
    assert rc == mg.RC_NOT_MEASURED
    assert calls == []
    assert "УЖЕ открыто окно" in capsys.readouterr().err


def test_main_passes_and_reports_the_window(tmp_path, monkeypatch, capsys):
    """Чистый прогон: код 0, окно снято, и отчёт НАЗЫВАЕТ его."""
    root, rels = _scene(tmp_path)
    calls = _stub_gate(monkeypatch, survivors=0)
    rc = mg.main(["--repo-root", root, "--json"])
    assert rc == mg.RC_PASS == 0
    assert calls and calls[0]["repo_root"] == root
    doc = json.loads(capsys.readouterr().out)
    assert doc["window"]["tool"] == "scripts/mutation_gate.py"
    assert doc["window"]["closed"] is True
    assert sorted(doc["window"]["files"]) == rels
    assert not os.path.exists(dmr.window_record_path(root))


def test_main_returns_one_for_survivors_and_still_closes_the_window(tmp_path,
                                                                    monkeypatch):
    """Выжившие — это FAIL гейта (код 1), а не «не измерено»; окно всё равно снято."""
    root, _ = _scene(tmp_path)
    _stub_gate(monkeypatch, survivors=1)
    rc = mg.main(["--repo-root", root])
    assert rc == mg.RC_SURVIVORS == 1
    assert not os.path.exists(dmr.window_record_path(root))


def test_main_closes_the_window_even_when_the_run_explodes(tmp_path, monkeypatch):
    """Исключение внутри прогона ⇒ `finally` снимает окно (путь ЧЕРЕЗ стек)."""
    root, _ = _scene(tmp_path)
    _stub_gate(monkeypatch, raises=RuntimeError("прогон упал"))
    with pytest.raises(RuntimeError):
        mg.main(["--repo-root", root])
    assert not os.path.exists(dmr.window_record_path(root))


def test_a_green_gate_over_a_dirty_tree_is_not_reported_as_pass(tmp_path, monkeypatch,
                                                                capsys):
    """ЗВЕНО, которого раньше не было вовсе: гейт PASS, а байты не сошлись.

    Сцена: прогон «прошёл», но оставил в дереве изменённый файл И испорченный слепок,
    то есть вернуть байты нечем. Вердикт обязан быть «НЕ ИЗМЕРЕНО» (код 3), а не PASS:
    иначе дерево с мутантом уезжает под зелёной печатью собственного сторожа.
    """
    root, rels = _scene(tmp_path)
    victim_rel = rels[0]

    def dirty(threshold=0, repo_root=None):
        tree = str(repo_root)
        doc = _record(tree)
        with open(os.path.join(tree, *victim_rel.split("/")), "a",
                  encoding="utf-8") as fh:
            fh.write("MUTANT = True\n")
        copy_rel = next(i["pristine_copy"] for i in doc["files"]
                        if i["file"] == victim_rel)
        with open(os.path.join(tree, *copy_rel.split("/")), "a",
                  encoding="utf-8") as fh:
            fh.write("# слепок испорчен\n")
        return {"module": "mutation_gate", "version": "v1.0", "pass": True,
                "threshold": 0, "n_mutants": 1, "n_killed": 1, "n_survivors": 0,
                "n_anchor_errors": 0, "survivors": [], "elapsed_s": 0.0,
                "results": [], "repo_root": str(repo_root)}

    monkeypatch.setattr(mg, "run_gate", dirty)
    rc = mg.main(["--repo-root", root])
    assert rc == mg.RC_NOT_MEASURED, "зелёный гейт над грязным деревом зачтён за PASS"
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().err
    assert os.path.exists(dmr.window_record_path(root)), "запись окна СНЯТА — fail-OPEN"


# ═════════════════════════════════════════════════════════════════════
# 6. `--repo-root` доходит до ПРОВОДКИ, а не только до парсера
# ═════════════════════════════════════════════════════════════════════
def test_repo_root_reaches_the_substitution(tmp_path, monkeypatch):
    """Подменяется файл НАЗВАННОГО дерева, а не дерева самого прибора.

    Без этого звена правило `.claude/rules/deployment.md` («прогон — в ОТДЕЛЬНОМ
    дереве») было неисполнимо: прибор мутировал только своё дерево.
    """
    root, _ = _scene(tmp_path)
    rel = "spa_core/risk/policy.py"
    target = os.path.join(root, *rel.split("/"))
    before = open(target, encoding="utf-8").read()
    anchor = "VALUE ="
    seen: dict = {}

    m = mg.Mutation(name="проба", file=rel, old=anchor, new="VALUE2 =",
                    tests=["нет-такого-теста.py"], why="проводка --repo-root")

    def fake_tests(test_files, repo_root=None):
        seen["cwd"] = repo_root
        seen["bytes"] = open(target, encoding="utf-8").read()
        return False, ""  # «тесты красные» ⇒ мутант убит

    monkeypatch.setattr(mg, "_run_tests", fake_tests)
    result = mg._apply_mutant(m, repo_root=root)

    assert result.killed is True
    assert seen["cwd"] == root, "pytest позван в ЧУЖОМ дереве"
    assert "VALUE2 =" in seen["bytes"], "подмена ушла не в названное дерево"
    assert open(target, encoding="utf-8").read() == before, "быстрый возврат не сработал"


def test_run_tests_runs_inside_the_named_tree(tmp_path, monkeypatch):
    """Прямое закрепление `cwd`: pytest обязан судить о ТОМ дереве, что мутировано."""
    captured: dict = {}

    class _Proc:
        returncode = 1
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return _Proc()

    monkeypatch.setattr(mg.subprocess, "run", fake_run)
    mg._run_tests(["a.py"], repo_root=str(tmp_path))
    assert captured["cwd"] == str(tmp_path)
