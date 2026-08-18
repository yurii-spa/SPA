"""Распределитель номеров ADR: номер нельзя занять дважды.

Каждый тест здесь — положительный контроль настоящей аварии 2026-08-08, а не украшение
(`.claude/rules/deployment.md`, «проверка сторожа сторожей»). В тот день номера столкнулись
ДВАЖДЫ за сутки: две сессии выписали `ADR-073`, потом две выписали `ADR-076`. Проигравший
каждый раз переименовывался и оставлял на старом номере строку-указатель. Следы обоих исходов
лежат в дереве до сих пор: `ADR-073` разошёлся честно сразу, `ADR-067` — только 2026-08-15
(цикл #251, перенумерован в `ADR-087` по тому же правилу: номер остаётся за тем, кто раньше
приземлился на origin). Синтетические фикстуры ниже намеренно воспроизводят ФОРМУ обеих аварий,
а не сегодняшнее состояние дерева: форма — это то, что сторож обязан ловить и после починки.

Почему существующий сторож эту аварию не видел: `check_memory_in_git --links` меряет, что
каждая ссылка реестра разрешается и каждый файл упомянут в реестре. Два РАЗНЫХ решения под
одним номером проходят его зелёными насквозь — оба файла есть, обе строки на месте. Класс
известный: сторож честно отвечает на СВОЙ вопрос, а читают его как ответ на нужный.

Тесты герметичны: свой временный git-репозиторий с ref `refs/remotes/origin/main`, сети нет.
Отдельно — ратчет по ЖИВОМУ репозиторию (база дублей может только уменьшаться) и контроль
ПРОВОДКИ: интерлок в пушере запускается настоящим `push_to_github.py --dry-run`, потому что
тесты на детали остаются зелёными, пока проводка мертва (урок цикла #144).
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name, rel):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


adr = _load("adr_number_under_test", "scripts/adr_number.py")
# Пушер импортируется как модуль (весь исполняемый код у него под `if __name__`), чтобы
# порцию для сторожа строил САМ пушер, а не её копия в тесте.
pusher = _load("push_to_github_under_test", "push_to_github.py")

BASELINE = Path(__file__).parent / "adr_duplicate_baseline.json"

INDEX_HEAD = (
    "# ADR INDEX\n\n"
    "| ADR | Заголовок | Статус | Файл |\n"
    "|---|---|---|---|\n"
)


def _row(num, title="решение", status="Accepted", fname=None, dup=False):
    label = f"ADR-{num} (дубль)" if dup else f"ADR-{num}"
    fname = fname or f"ADR-{num}-x.md"
    return f"| {label} | {title} | {status} | [ADR-{num}]({fname}) |\n"


def _run(cwd, *args):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    """Репозиторий, где ветка `origin/main` играет роль origin — как у соседних тестов."""
    r = tmp_path / "repo"
    (r / "docs" / "decisions").mkdir(parents=True)
    _run(r, "git", "init", "-q")
    _run(r, "git", "config", "user.email", "t@t")
    _run(r, "git", "config", "user.name", "t")
    return r


def _commit_origin(repo, files: dict):
    """Положить набор файлов и объявить это состоянием origin/main."""
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    _run(repo, "git", "add", "-A")
    _run(repo, "git", "commit", "-qm", "origin state")
    rc = _run(repo, "git", "rev-parse", "HEAD")
    _run(repo, "git", "update-ref", "refs/remotes/origin/main", rc.stdout.strip())


# ── что считается занятым номером ────────────────────────────────────────────

def test_number_taken_by_a_file_on_origin_only_is_not_free(repo):
    """АВАРИЯ 08.08 дословно: номер занят СОСЕДНЕЙ сессией, у меня на диске его нет.

    Это и есть механизм столкновения — параллельная сессия приземляется на origin, а
    распределитель, смотрящий в рабочее дерево, о ней не знает.

    Реестр НАМЕРЕННО оставлен пустым: иначе номер числился бы занятым по строке INDEX, и
    тест был бы зелёным даже если каталог решений на origin вовсе не читается. Первая
    редакция этого теста была написана именно так и мутацию «origin игнорируется»
    пропустила — то есть стерегла не то, о чём говорило её имя.
    """
    _commit_origin(repo, {
        "docs/decisions/ADR-073-redistribution.md": "x",
        "docs/decisions/INDEX.md": INDEX_HEAD,
    })
    # рабочее дерево о номере 073 не знает: файл удалён локально
    (repo / "docs" / "decisions" / "ADR-073-redistribution.md").unlink()

    taken, unchecked = adr.taken_keys(repo)
    assert not unchecked
    assert "073" in taken, "файл решения на origin обязан занимать номер"


def test_number_taken_by_an_index_row_alone_is_not_free(repo):
    """Второй независимый источник: строка реестра есть, файла ещё нет.

    Так выглядит номер, который сосед уже застолбил в INDEX, но файл дописывает. Оба
    источника меряются отдельно, потому что отказ каждого из них — своя авария.
    """
    _commit_origin(repo, {
        "docs/decisions/ADR-070-a.md": "x",
        "docs/decisions/INDEX.md": (INDEX_HEAD + _row("070", fname="ADR-070-a.md")
                                    + _row("073", fname="ADR-073-redistribution.md")),
    })
    # Реестр РАБОЧЕГО дерева откатываем к состоянию без 073: иначе номер числится занятым
    # по строке из дерева, и тест зеленеет даже когда реестр origin не читается вовсе.
    (repo / "docs" / "decisions" / "INDEX.md").write_text(
        INDEX_HEAD + _row("070", fname="ADR-070-a.md"), encoding="utf-8")

    taken, unchecked = adr.taken_keys(repo)
    assert not unchecked
    assert "073" in taken, "строка реестра на origin обязана занимать номер"


def test_next_number_is_max_plus_one_across_origin_and_tree(repo):
    _commit_origin(repo, {
        "docs/decisions/ADR-070-a.md": "x",
        "docs/decisions/INDEX.md": INDEX_HEAD + _row("070", fname="ADR-070-a.md"),
    })
    (repo / "docs" / "decisions" / "ADR-072-local.md").write_text("x", encoding="utf-8")

    number, _, unchecked = adr.next_number(repo)
    assert not unchecked
    assert number == 73, "занятость меряется союзом origin и дерева"


def test_next_number_skips_gaps_because_gaps_are_already_spoken_for(repo):
    """Дыра в нумерации не свободна: `ADR-071` назван в STATE до того, как написан файл.

    «Первый свободный» выдал бы 71 и столкнул новое решение с уехавшей ссылкой — ровно та
    авария, которую модуль устраняет.
    """
    _commit_origin(repo, {
        "docs/decisions/ADR-070-a.md": "x",
        "docs/decisions/ADR-072-b.md": "x",
        "docs/decisions/INDEX.md": (INDEX_HEAD + _row("070", fname="ADR-070-a.md")
                                    + _row("072", fname="ADR-072-b.md")),
    })
    number, _, unchecked = adr.next_number(repo)
    assert not unchecked
    assert number == 73, "дыра 071 не выдаётся: на неё уже ссылаются"


def test_pointer_row_does_not_claim_the_number(repo):
    """Форма, которой разошёлся ADR-073: живая строка + строка-указатель `Superseded`.

    Указатель обязан НЕ считаться претензией — иначе честно разошедшийся номер вечно
    числился бы конфликтом, и сторож краснел бы на ВЕРНОЕ состояние.
    """
    index = (INDEX_HEAD
             + _row("073", fname="ADR-073-redistribution.md")
             + _row("073", title="Указатель: номер занят", status="Superseded",
                    fname="ADR-073-telegram.md", dup=True))
    _commit_origin(repo, {
        "docs/decisions/ADR-073-redistribution.md": "x",
        "docs/decisions/ADR-073-telegram.md": "x",
        "docs/decisions/INDEX.md": index,
    })
    assert adr.live_duplicates(repo) == {}, "указатель — не вторая претензия на номер"


def test_two_accepted_rows_on_one_number_are_a_duplicate(repo):
    """Форма, которой ADR-067 НЕ разошёлся: два разных решения, оба действуют."""
    index = (INDEX_HEAD
             + _row("067", title="гейт go-live", fname="ADR-067-golive.md")
             + _row("067", title="мандат автопилота", fname="ADR-067-autopilot.md"))
    _commit_origin(repo, {"docs/decisions/INDEX.md": index})
    assert list(adr.live_duplicates(repo)) == ["067"]


# ── дубль по ФАЙЛАМ: второй источник, не копия реестрового ───────────────────
#
# `live_duplicates` судит по строкам INDEX.md. Реестр пишет человек, файлы кладёт работа —
# и авария 067 жила ровно в этом зазоре: два ПРИНЯТЫХ решения лежали файлами под одним
# номером с 06.08 по 15.08. Строка реестра — описание, файл — предмет; сторож, читающий
# только описание, стережёт не то. Поэтому измерение отдельное и из другого источника.

_POINTER_BODY = (
    "# ADR-067 (номер занят) → решение перенумеровано в ADR-087\n\n"
    "**Статус:** ❌ не решение, а указатель. Содержимого здесь нет.\n")


def test_two_real_decisions_under_one_number_are_a_file_duplicate(repo):
    """Авария 067 дословно, но замеренная по ФАЙЛАМ: реестра тут вообще нет.

    Положительный контроль: воспроизведён предмет аварии (два решения на номере), а не её
    описание в INDEX.md. Реестр в фикстуру не кладётся намеренно — измерение обязано
    состояться и тогда, когда реестр «выглядит целым» или его правку ещё не написали.
    """
    d = repo / "docs" / "decisions"
    (d / "ADR-067-golive-blocks.md").write_text("# ADR-067 гейт go-live\n", encoding="utf-8")
    (d / "ADR-067-autopilot-mandate.md").write_text("# ADR-067 мандат\n", encoding="utf-8")

    assert adr.file_duplicates(repo) == {
        "067": ["ADR-067-autopilot-mandate.md", "ADR-067-golive-blocks.md"]}


def test_a_pointer_file_next_to_a_decision_is_not_a_duplicate(repo):
    """Принятый способ разойтись обязан оставаться зелёным — иначе сторожа отключат.

    Указатель существует ровно затем, чтобы уехавшая в коммиты ссылка не упиралась в пустоту.
    Требовать его удаления значило бы чинить сторожа ценой воскрешения мёртвой ссылки, то есть
    менять реальную потерю на зелёный цвет.
    """
    d = repo / "docs" / "decisions"
    (d / "ADR-067-golive-blocks.md").write_text(_POINTER_BODY, encoding="utf-8")
    (d / "ADR-067-autopilot-mandate.md").write_text("# ADR-067 мандат\n", encoding="utf-8")

    assert adr.file_duplicates(repo) == {}


def test_pointer_is_recognised_by_heading_and_by_status_independently():
    """Два признака указателя держатся ПОРОЗНЬ: они писались независимо и оба живые.

    Если бы требовались оба сразу, переписанная шапка одного из будущих указателей молча
    превратила бы его в «второе решение» и покрасила сторожа не на том.
    """
    assert adr.is_pointer_file("# ADR-073 (номер занят) → переехало в ADR-075\n")
    assert adr.is_pointer_file("# ADR-073 переехал\n\n**Статус:** не решение, а указатель.\n")
    assert not adr.is_pointer_file("# ADR-073 перераздача бюджета\n\n**Статус:** Accepted\n")


def test_named_families_are_not_numbered_and_never_collide(repo):
    """`ADR-YL-011` и `ADR-OWN-…` — своё пространство имён, распределяется только числовое.

    Без этого разграничения пять файлов `ADR-OWN-*` читались бы как пятикратный дубль номера
    «OWN» и сторож краснел бы на живом дереве с первого дня — то есть был бы снят.
    """
    d = repo / "docs" / "decisions"
    for name in ("ADR-YL-011-a.md", "ADR-YL-012-b.md", "ADR-OWN-2026-07-c.md",
                 "ADR-OWN-2026-07-d.md"):
        (d / name).write_text("# решение\n", encoding="utf-8")

    assert adr.file_duplicates(repo) == {}


def test_unreadable_decision_counts_as_a_claim_not_as_a_pass(repo, monkeypatch):
    """fail-CLOSED: «не прочитали файл» не сворачивается в «указатель, номер свободен».

    Обратное поведение отдало бы номер по нечитаемому файлу — та же форма, что и «origin
    недоступен ⇒ по дереву свободно», из-за которой всё это и строилось.
    """
    d = repo / "docs" / "decisions"
    (d / "ADR-067-one.md").write_text(_POINTER_BODY, encoding="utf-8")
    (d / "ADR-067-two.md").write_text("# ADR-067 решение\n", encoding="utf-8")

    real_read = Path.read_text

    def blind(self, *a, **kw):
        if self.name == "ADR-067-one.md":
            raise OSError("нечитаемо")
        return real_read(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", blind)
    assert list(adr.file_duplicates(repo)) == ["067"]


# ── fail-CLOSED ──────────────────────────────────────────────────────────────

def test_unreadable_origin_refuses_to_hand_out_a_number(repo):
    """origin недоступен ⇒ номер НЕ выдаётся. «По дереву свободно» — это и есть авария."""
    (repo / "docs" / "decisions" / "ADR-070-a.md").write_text("x", encoding="utf-8")
    number, _, unchecked = adr.next_number(repo)  # ref origin/main не создан
    assert number is None
    assert unchecked, "недоступный origin обязан быть «не измерено», а не «свободно»"


def test_empty_decisions_dir_is_broken_measurement_not_number_one(repo):
    """Пустой каталог решений — сломанное измерение, а не «начинай с 001» (fail-CLOSED)."""
    _commit_origin(repo, {"docs/decisions/INDEX.md": INDEX_HEAD})
    number, _, unchecked = adr.next_number(repo)
    assert number is None and unchecked


def test_check_push_without_origin_is_unchecked_not_ok(repo):
    findings, unchecked = adr.check_push(repo, ["docs/decisions/ADR-078-new.md"])
    assert findings == []
    assert unchecked, "«не измерено» никогда не сворачивается в «в порядке»"


# ── интерлок доставки: набор файлов ──────────────────────────────────────────

def _origin_with_073(repo):
    _commit_origin(repo, {
        "docs/decisions/ADR-073-redistribution.md": "x",
        "docs/decisions/INDEX.md": INDEX_HEAD + _row("073", fname="ADR-073-redistribution.md"),
    })


def test_new_file_on_a_number_taken_on_origin_is_refused(repo):
    """АВАРИЯ 08.08: второе решение выписало ADR-073 и поехало. Ловится ДО пуша."""
    _origin_with_073(repo)
    p = repo / "docs" / "decisions" / "ADR-073-owner-decisions-in-telegram.md"
    p.write_text("x", encoding="utf-8")
    findings, unchecked = adr.check_push(repo, [str(p)])
    assert not unchecked
    assert any("уже занят" in f for f in findings), findings


def test_updating_an_existing_decision_is_not_a_collision(repo):
    """Правка своего же файла — обновление, а не столкновение. Иначе сторож запирает работу."""
    _origin_with_073(repo)
    p = repo / "docs" / "decisions" / "ADR-073-redistribution.md"
    p.write_text("обновлено", encoding="utf-8")
    findings, unchecked = adr.check_push(repo, [str(p)])
    assert (findings, unchecked) == ([], [])


def test_decision_without_an_index_row_is_refused_before_landing(repo):
    """Сейчас это краснит main тестом ПОСЛЕ приземления — по следам чужой сессии.

    Требование карточки дословно: «файл решения без строки в INDEX.md не должен доживать
    до пуша».
    """
    _origin_with_073(repo)
    p = repo / "docs" / "decisions" / "ADR-078-brand-new.md"
    p.write_text("x", encoding="utf-8")
    findings, unchecked = adr.check_push(repo, [str(p)])
    assert not unchecked
    assert any("нет ни одной строки" in f for f in findings), findings


def test_index_delivered_in_the_same_push_counts(repo):
    """Реестр едет ЭТИМ же набором ⇒ судить надо по нему, иначе честная доставка отказана."""
    _origin_with_073(repo)
    new = repo / "docs" / "decisions" / "ADR-078-brand-new.md"
    new.write_text("x", encoding="utf-8")
    index = repo / "docs" / "decisions" / "INDEX.md"
    index.write_text(index.read_text(encoding="utf-8")
                     + _row("078", fname="ADR-078-brand-new.md"), encoding="utf-8")
    findings, unchecked = adr.check_push(repo, [str(new), str(index)])
    assert (findings, unchecked) == ([], [])


def test_push_creating_a_second_live_row_is_refused(repo):
    _origin_with_073(repo)
    new = repo / "docs" / "decisions" / "ADR-073-second.md"
    new.write_text("x", encoding="utf-8")
    index = repo / "docs" / "decisions" / "INDEX.md"
    index.write_text(index.read_text(encoding="utf-8")
                     + _row("073", title="второе решение", fname="ADR-073-second.md"),
                     encoding="utf-8")
    findings, unchecked = adr.check_push(repo, [str(new), str(index)])
    assert not unchecked
    assert any("делят двое" in f for f in findings), findings


def test_preexisting_duplicate_does_not_block_unrelated_edit(repo):
    """Предсуществующий дубль (ADR-067) не запирает правку файла под тем же номером.

    Сторож, краснеющий на чужой беспорядок, отключают первым — и тогда он не поймает уже
    и настоящее столкновение. Порог — «стало хуже, чем на origin», а не «плохо вообще».
    """
    index = (INDEX_HEAD
             + _row("067", title="гейт", fname="ADR-067-golive.md")
             + _row("067", title="мандат", fname="ADR-067-autopilot.md"))
    _commit_origin(repo, {
        "docs/decisions/ADR-067-golive.md": "x",
        "docs/decisions/ADR-067-autopilot.md": "x",
        "docs/decisions/INDEX.md": index,
    })
    p = repo / "docs" / "decisions" / "ADR-067-golive.md"
    p.write_text("уточнение формулировки", encoding="utf-8")
    findings, unchecked = adr.check_push(repo, [str(p)])
    assert (findings, unchecked) == ([], []), findings


def test_fixing_a_duplicate_is_never_blocked(repo):
    """Разойтись (одна строка становится указателем) обязано ПРОХОДИТЬ гейт."""
    index_before = (INDEX_HEAD
                    + _row("067", title="гейт", fname="ADR-067-golive.md")
                    + _row("067", title="мандат", fname="ADR-067-autopilot.md"))
    _commit_origin(repo, {
        "docs/decisions/ADR-067-golive.md": "x",
        "docs/decisions/ADR-067-autopilot.md": "x",
        "docs/decisions/INDEX.md": index_before,
    })
    index = repo / "docs" / "decisions" / "INDEX.md"
    index.write_text(INDEX_HEAD
                     + _row("067", title="гейт", fname="ADR-067-golive.md")
                     + _row("067", title="Указатель: см. ADR-078", status="Superseded",
                            fname="ADR-067-autopilot.md", dup=True), encoding="utf-8")
    p = repo / "docs" / "decisions" / "ADR-067-golive.md"
    findings, unchecked = adr.check_push(repo, [str(p), str(index)])
    assert (findings, unchecked) == ([], []), findings


def test_push_without_decisions_is_silent(repo):
    """Пуш, не касающийся решений, этот сторож не замечает вовсе."""
    _origin_with_073(repo)
    assert adr.check_push(repo, ["docs/STATE.md", "spa_core/risk/policy.py"]) == ([], [])


# ── РЕЗЕРВ НОМЕРА: две ветки, одна база ──────────────────────────────────────
#
# Карточка `inbox-nomera-adr-stalkivayutsya-po-ustroistvu` (17.08): столкновения 067, 091, 087
# случились не по невнимательности, а ПО УСТРОЙСТВУ — `next` меряет занятость и НИЧЕГО не
# занимает, поэтому две ветки, спросившие номер в разное время суток, обе получают верный
# ответ и обе правы. Тесты ниже воспроизводят ровно эту форму: один origin, две рабочие копии.


@pytest.fixture()
def two_branches(tmp_path):
    """(origin, ветка-облако, ветка-Мак) — форма аварии 087 дословно.

    Общий bare-origin играет роль GitHub: только он видит обе стороны, и только на нём резерв
    может быть атомарным. На origin уже лежит ADR-091, то есть «следующий свободный» для обеих
    веток — 092, как и было 15.08.
    """
    origin = tmp_path / "origin.git"
    _run(tmp_path, "git", "init", "-q", "--bare", "-b", "main", str(origin))

    seed = tmp_path / "seed"
    (seed / "docs" / "decisions").mkdir(parents=True)
    _run(seed, "git", "init", "-q", "-b", "main")
    _run(seed, "git", "config", "user.email", "t@t")
    _run(seed, "git", "config", "user.name", "t")
    (seed / "docs" / "decisions" / "ADR-091-a.md").write_text("x", encoding="utf-8")
    (seed / "docs" / "decisions" / "INDEX.md").write_text(
        INDEX_HEAD + _row("091", fname="ADR-091-a.md"), encoding="utf-8")
    _run(seed, "git", "add", "-A")
    _run(seed, "git", "commit", "-qm", "seed")
    _run(seed, "git", "push", "-q", str(origin), "main")

    clones = []
    for name in ("cloud", "mac"):
        path = tmp_path / name
        _run(tmp_path, "git", "clone", "-q", str(origin), str(path))
        _run(path, "git", "config", "user.email", "t@t")
        _run(path, "git", "config", "user.name", "t")
        clones.append(path)
    return (origin, *clones)


def test_two_branches_asking_at_once_get_different_numbers(two_branches):
    """КРИТЕРИЙ ГОТОВНОСТИ карточки: две ветки, одна база — РАЗНЫЕ номера.

    Отрицательный контроль вверху — это сегодняшнее поведение: `next_number` обеим честно
    отвечает «092», и обе правы. Он обязан остаться зелёным (совет и есть совет), а вот
    `allocate` обязан развести ветки, потому что номер он не советует, а ЗАБИРАЕТ.
    """
    _origin, cloud, mac = two_branches

    # Как было: обе ветки спрашивают и получают ОДИН И ТОТ ЖЕ номер — авария 087 целиком.
    assert adr.next_number(cloud)[0] == 92
    assert adr.next_number(mac)[0] == 92

    first, races_a, unchecked_a = adr.allocate(cloud, transport="git")
    second, races_b, unchecked_b = adr.allocate(mac, transport="git")

    assert (unchecked_a, unchecked_b) == ([], []), (unchecked_a, unchecked_b)
    assert first != second, "обе ветки снова получили один номер — резерв не работает"
    assert {first, second} == {92, 93}, (first, second, races_a, races_b)


def _blind_first_ls_remote(real):
    """git, у которого ПЕРВОЕ чтение резервов ещё не видит чужого — окно аварии 087.

    Обе ветки меряют занятость ДО того, как соперник записал свой резерв: измерение честное,
    ответ одинаковый. Разводит их не чтение, а запись — compare-and-swap на сервере.
    """
    seen = {"blind": True}

    def git(cwd, *args):
        rc, out, err = real(cwd, *args)
        if args and args[0] == "ls-remote" and seen["blind"]:
            seen["blind"] = False
            return rc, "", err
        return rc, out, err

    return git


def test_the_race_window_itself_is_closed_by_the_write_not_the_read(two_branches):
    """Сценарий 087 в самой жёсткой форме: соперник застолбил номер ПОСЛЕ нашего измерения.

    Проверка того, что резерв держится записью, а не удачным чтением: даже когда ветка-Мак
    смотрит на устаревшую картину и уверенно идёт за 092, сервер её отвергает, и она берёт 093
    сама — без разбора «кто приземлился раньше» и без правки чужих ссылок.
    """
    _origin, cloud, mac = two_branches
    assert adr.reserve_number(cloud, 92, transport="git")[0] == adr.RESERVED

    number, races, unchecked = adr.allocate(mac, transport="git",
                                            git=_blind_first_ls_remote(adr._git))
    assert unchecked == [], unchecked
    assert races, "гонка не воспроизведена: ветка-Мак не пыталась взять чужой номер"
    assert number == 93, (number, races)


def test_a_reservation_alone_occupies_the_number(two_branches):
    """Резерв — самая ранняя претензия: ни файла, ни строки реестра ещё нет.

    Соседние тесты стерегут два прежних источника (файл на origin, строка INDEX). Этот —
    третий, и он единственный существует в НАЧАЛЕ чужой работы, то есть в том самом окне,
    где и жили все четыре столкновения.
    """
    _origin, cloud, mac = two_branches
    assert adr.reserve_number(cloud, 92, transport="git")[0] == adr.RESERVED

    keys, unchecked = adr.reserved_keys(mac, remote="origin")
    assert (keys, unchecked) == ({"092"}, [])
    assert adr.next_number(mac, remote="origin")[0] == 93, "чужой резерв обязан занимать номер"


def test_next_number_is_still_max_plus_one_over_reservations(two_branches):
    """Дыры не свободны и с резервами: резерв 095 двигает следующий номер на 096, а не на 092.

    Тонкость закреплена соседним `…skips_gaps…` (ADR-071 назван в STATE раньше, чем написан
    файл). Резерв — ещё один источник «дыры»: между 091 и 095 номера остаются НЕ выданными.
    """
    _origin, cloud, mac = two_branches
    assert adr.reserve_number(cloud, 95, transport="git")[0] == adr.RESERVED
    assert adr.next_number(mac, remote="origin")[0] == 96


def test_reservation_survives_a_rival_whose_commit_is_an_ancestor(two_branches):
    """Замер: без лизинга чужой резерв был бы ТИХО перезаписан fast-forward'ом.

    Ветка-Мак ушла вперёд от общей базы, поэтому её коммит — потомок того, на который смотрит
    чужой резерв. Обычный `git push` счёл бы это законным продвижением ref'а и «зарезервировал»
    бы уже занятый номер молча — то есть авария вернулась бы, а сторож остался бы зелёным.
    """
    _origin, cloud, mac = two_branches
    assert adr.reserve_number(cloud, 92, transport="git")[0] == adr.RESERVED

    (mac / "docs" / "decisions" / "ADR-092-mine.md").write_text("x", encoding="utf-8")
    _run(mac, "git", "add", "-A")
    _run(mac, "git", "commit", "-qm", "работа ветки-Мака")

    status, detail = adr.reserve_number(mac, 92, transport="git")
    assert status == adr.TAKEN, (status, detail)


def test_release_frees_an_abandoned_reservation(two_branches):
    """Цена варианта 1 — висящие резервы у брошенных работ; они видны и подметаются."""
    _origin, cloud, mac = two_branches
    adr.reserve_number(cloud, 92, transport="git")
    assert adr.next_number(mac, remote="origin")[0] == 93

    ok, detail = adr.release_number(cloud, 92)
    assert ok, detail
    assert adr.next_number(mac, remote="origin")[0] == 92


# ── fail-CLOSED резерва: не смог занять ⇒ не выдал ───────────────────────────

def test_unreachable_remote_refuses_to_hand_out_a_number(repo):
    """Резервы соперника не прочитаны ⇒ номер НЕ выдаётся. «По дереву свободно» — авария."""
    _commit_origin(repo, {
        "docs/decisions/ADR-091-a.md": "x",
        "docs/decisions/INDEX.md": INDEX_HEAD + _row("091", fname="ADR-091-a.md"),
    })
    number, _races, unchecked = adr.allocate(repo, remote="origin")  # remote не настроен
    assert number is None
    assert any("резервы номеров" in u for u in unchecked), unchecked


def test_transport_failure_never_degrades_into_an_unreserved_number(two_branches):
    """Измерение прошло, а ЗАНЯТЬ не вышло ни одним транспортом ⇒ номер не выдаётся.

    Самый соблазнительный обход — «зарезервировать не смог, но номер-то свободен, бери» —
    возвращает ровно то устройство, из-за которого столкновения и происходили.
    """
    _origin, cloud, _mac = two_branches

    class _NoPat:
        def get_pat(self):
            raise RuntimeError("PAT не найден в Keychain")

    number, _races, unchecked = adr.allocate(cloud, remote="origin", transport="api",
                                             pusher=_NoPat())
    assert number is None
    assert any("fail-CLOSED" in u for u in unchecked), unchecked


# ── второй транспорт: контекст Мака (PAT + GitHub API) ───────────────────────

class _FakeGitHub:
    """GitHub API в объёме, который трогает резерв: `POST /git/refs` = compare-and-swap."""

    def __init__(self):
        self.refs = set()

    def get_pat(self):
        return "pat"

    def get_base_ref(self, pat, repo, branch):
        return ("d" * 40, "t" * 40)

    def _api(self, pat, method, path, payload=None):
        assert (method, path) == ("POST", "/repos/yurii-spa/SPA/git/refs"), (method, path)
        ref = payload["ref"]
        if ref in self.refs:
            import io
            import urllib.error
            raise urllib.error.HTTPError(
                "https://api.github.com" + path, 422, "Unprocessable Entity", {},
                io.BytesIO(b'{"message":"Reference already exists"}'))
        self.refs.add(ref)
        return {"ref": ref}


def test_api_transport_reserves_and_sees_a_taken_number(two_branches):
    """Мак пушит не git'ом, а API с PAT из Keychain — резерв обязан работать И ТАМ.

    Иначе механизм закрывает ровно одну из двух сторон столкновения, а сталкиваются они
    как раз попарно: облачная сессия против автономного цикла.
    """
    _origin, cloud, mac = two_branches
    api = _FakeGitHub()

    assert adr.reserve_number(cloud, 92, transport="api", pusher=api) == (
        adr.RESERVED, "refs/adr-reserved/092")
    status, detail = adr.reserve_number(mac, 92, transport="api", pusher=api)
    assert status == adr.TAKEN, (status, detail)
    assert api.refs == {"refs/adr-reserved/092"}


def test_number_is_normalised_so_92_and_092_are_one_number():
    """`92` и `092` обязаны быть ОДНИМ ref'ом — иначе два резерва на один номер."""
    assert adr._reserve_ref(92) == adr._reserve_ref("092") == "refs/adr-reserved/092"


# ── разбор реестра ───────────────────────────────────────────────────────────

def test_status_is_read_from_the_end_not_the_third_column():
    """Заголовки решений длинные и содержат разделители — колонки берутся с КОНЦА.

    Настоящая строка ADR-054 несёт внутри заголовка и скобки, и запятые, и вложенные
    ссылки; отсчёт слева ломается на первом же таком заголовке.
    """
    line = ("| ADR-054 | Kill-switch authority — latches (manual_pause vs risk), "
            "D-08 accepted | Accepted | [ADR-054](ADR-054-kill-switch-authority.md) |")
    rows = adr.parse_index(line)
    assert rows == {"054": [("Accepted", False)]}


def test_named_families_are_a_separate_namespace():
    """`ADR-YL-011` / `ADR-OWN-…` — другое пространство имён, числовой ряд им не мешает."""
    assert adr.file_key("ADR-YL-011-site-custodian.md") == "YL"
    assert adr.file_key("ADR-076-live-feeds.md") == "076"
    assert adr.file_key("INDEX.md") is None
    assert adr.file_key("_TEMPLATE.md") is None


# ── ПРОВОДКА: интерлок реально стоит в пушере ────────────────────────────────

def test_pusher_refuses_a_colliding_decision_end_to_end():
    """Контроль ПРОВОДКИ, а не детали: зовём настоящий пушер (урок #144).

    `--dry-run` доходит до интерлока и упирается в него ДО сети и до чтения PAT — это тот
    же отказ, что и на настоящем пуше (сверка инструмента доставки устроена так же).
    Имя файла заведомо столкновенное: номер 067 занят на origin ДРУГИМИ файлами.
    """
    r = subprocess.run(
        [sys.executable, str(ROOT / "push_to_github.py"), "--dry-run", "-m", "probe",
         "--files", "docs/decisions/ADR-067-a-parallel-session-decision.md"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180)
    assert r.returncode == 7, f"интерлок не сработал: rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    out = r.stdout + r.stderr
    # В чекауте без ref `origin/main` занятость честно НЕ измерена — это тоже отказ, и тоже
    # правильный (fail-CLOSED). Тест принимает обе причины, но НЕ принимает молчаливый пропуск.
    assert ("уже занят" in out) or ("НЕ ИЗМЕРЕНО" in out), out


def test_pusher_interlock_is_scoped_to_decisions_only():
    """Обратная сторона проводки: пуш без решений интерлок не трогает (иначе его снимут).

    Проверяется ОТБОР файлов, а не полный прогон пушера: `--dry-run` идёт дальше интерлока
    и спрашивает remote (в выводе появляется `→ create`), то есть тест стал бы сетевым и
    его законно завернул бы `network_guard`. Здесь исполняется тот же самый предикат
    отбора из `push_to_github.py`, взятый из исходника, — если условие сузят или расширят,
    тест это увидит; а что интерлок ВООБЩЕ включён в поток, доказывает соседний тест,
    доходящий до реального отказа rc=7.
    """
    src = (ROOT / "push_to_github.py").read_text(encoding="utf-8")
    assert '"docs/decisions/ADR-" in str(f).replace("\\\\", "/")' in src, (
        "предикат отбора решений в пушере изменился — сверь, что интерлок всё ещё "
        "срабатывает ТОЛЬКО на docs/decisions/ADR-*")

    def selects(path):  # тот же предикат, дословно
        return "docs/decisions/ADR-" in str(path).replace("\\", "/")

    assert not selects("docs/STATE.md")
    assert not selects("spa_core/risk/policy.py")
    assert not selects("docs/decisions/INDEX.md"), "реестр сам по себе решением не является"
    assert selects("docs/decisions/ADR-078-x.md")


def test_pusher_shows_the_guard_the_whole_delivery_set(repo):
    """АВАРИЯ 09.08 дословно: честная пара (решение + реестр) получала отказ rc=7.

    Это тест ПРОВОДКИ, а не детали, и он собран из ДВУХ настоящих частей: порцию строит
    сам пушер (`adr_interlock_payload`), судит её настоящий сторож (`check_push`). Соседний
    `test_index_delivered_in_the_same_push_counts` проверяет ту же ситуацию и остаётся
    зелёным при мёртвой проводке — потому что зовёт сторожа напрямую, минуя пушер, который
    как раз и вырезал `INDEX.md` из набора (урок #144: мутировать надо проводку, а не части).

    Отрицательный контроль внизу воспроизводит ровно ту порцию, что уходила сторожу ДО
    починки, и обязан остаться красным: он и есть доказательство, что тест видел аварию.
    """
    _origin_with_073(repo)
    new = repo / "docs" / "decisions" / "ADR-078-brand-new.md"
    new.write_text("x", encoding="utf-8")
    index = repo / "docs" / "decisions" / "INDEX.md"
    index.write_text(index.read_text(encoding="utf-8")
                     + _row("078", fname="ADR-078-brand-new.md"), encoding="utf-8")
    # Набор доставки реальной сессии: решение, реестр и посторонние файлы рядом.
    delivered = [str(new), str(index), "docs/STATE.md", "docs/journal/2026-W32.md"]

    payload = pusher.adr_interlock_payload(delivered)
    assert str(index) in payload, "реестр уезжает этим же пушем, а сторож его не увидит"
    assert adr.check_push(repo, payload) == ([], []), (
        "честная пара (решение + строка реестра) отказана — сторож судит реестр с origin")

    # ДО починки пушер отдавал сторожу только это — и получал ложную находку.
    narrowed = [f for f in delivered if "docs/decisions/ADR-" in f]
    findings, _ = adr.check_push(repo, narrowed)
    assert any("нет ни одной строки" in f for f in findings), (
        "отрицательный контроль зелёный ⇒ тест не воспроизводит аварию 09.08")


def test_pusher_trigger_stays_narrow_while_the_payload_is_full(repo):
    """Обратная сторона: расширяется ПОРЦИЯ, а не ТРИГГЕР — иначе интерлок начнёт краснеть
    на пушах без решений, и его снимут первым.

    `test_pusher_interlock_is_scoped_to_decisions_only` стережёт предикат-триггер, здесь —
    что полная порция сама по себе ничего не запирает: сторож на наборе без решений молчит.
    """
    _origin_with_073(repo)
    payload = pusher.adr_interlock_payload(["docs/STATE.md", "docs/decisions/INDEX.md",
                                            "spa_core/risk/policy.py"])
    assert adr.check_push(repo, payload) == ([], []), (
        "набор без решений обязан быть сторожу безразличен")


def test_pusher_actually_calls_the_payload_builder():
    """Функция не должна стать мёртвым кодом рядом с прежним узким `*_adr`.

    Без этого ассерта починку можно откатить в одну строку, а оба теста выше останутся
    зелёными: они зовут `adr_interlock_payload` сами.
    """
    src = (ROOT / "push_to_github.py").read_text(encoding="utf-8")
    assert "*adr_interlock_payload(all_files)" in src, (
        "интерлок снова получает не весь набор доставки — сверь, видит ли сторож INDEX.md")


def test_pusher_declares_the_conscious_bypass():
    """Осознанный обход существует и НАЗВАН — как `--allow-toolchain-mismatch` рядом."""
    src = (ROOT / "push_to_github.py").read_text(encoding="utf-8")
    assert "--allow-adr-collision" in src
    assert "SPA_PUSH_ALLOW_ADR_COLLISION" in src


# ── переиспользование, а не копия ────────────────────────────────────────────

def test_git_helper_is_reused_not_copied():
    """Второй реализации одного измерения в этом репозитории быть не должно.

    Сверяемся с модулем, который импортировал сам `adr_number` (`sys.modules`), а не с
    загруженной заново копией: копия — другой объект ПО ПОСТРОЕНИЮ, и такой ассерт краснел
    бы даже при честном переиспользовании. Та же оговорка стоит у соседнего
    `test_memory_in_git.py`; здесь она была нарушена и тест это поймал.
    """
    step0a = sys.modules["check_undelivered_work"]
    assert Path(step0a.__file__).resolve() == (ROOT / "scripts" / "check_undelivered_work.py")
    assert adr._git is step0a._git
    src = (ROOT / "scripts" / "adr_number.py").read_text(encoding="utf-8")
    assert "def _git" not in src


# ── ратчет по ЖИВОМУ репозиторию ─────────────────────────────────────────────

def test_live_duplicate_numbers_only_shrink():
    """База дублей может только уменьшаться — как храповик литеральных дат рядом.

    Почему не «ноль дублей»: `ADR-067` держат ДВА принятых решения, на которые уже
    ссылаются MEMORY.md и STATE. Перенумерация — правка чужого принятого решения и всех
    ссылок на него; сделанная походя, она ломает адресацию памяти проекта, поэтому она
    вынесена в отдельную карточку и ждёт решения. Пока она ждёт — НОВЫЙ дубль появиться
    не может, а этот назван вслух, а не забыт.
    """
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    known = set(baseline["known_duplicates"])
    actual = set(adr.live_duplicates(ROOT))

    new = sorted(actual - known)
    assert not new, (
        f"новый дубль номера ADR: {new}. Возьми свободный номер "
        f"(`python3 scripts/adr_number.py next`) и оставь на старом строку-указатель "
        f"Superseded — добавлять номер в базу, чтобы погасить падение, запрещено")

    healed = sorted(known - actual)
    assert not healed, (
        f"дубли {healed} разошлись — удали их из {BASELINE.name}: база храповика обязана "
        f"уменьшаться, иначе она перестаёт что-либо стеречь")


def test_live_decision_files_never_share_a_number():
    """Ратчет по ФАЙЛАМ живого дерева: под одним номером — одно решение. Порог — НОЛЬ.

    Базы известных исключений здесь нет намеренно, и это не строгость ради строгости: на
    2026-08-18 дерево измеримо чисто (`067` и `073` держат по указателю рядом с решением, а
    указатель номер не занимает), поэтому любая находка — новая. База имела бы смысл только
    при существующем долге; заведённая пустой, она становится приглашением гасить падение
    записью в неё.

    Устойчивость к росту реестра: утверждение не перечисляет номеров и не знает, сколько их.
    Новый ADR его не касается — красным он станет ровно тогда, когда номер займут дважды.
    """
    dupes = adr.file_duplicates(ROOT)
    assert dupes == {}, (
        f"под одним номером лежит больше одного решения: {dupes}. Возьми свободный номер "
        f"(`python3 scripts/adr_number.py next`), переименуй ПРОИГРАВШЕГО (кто приземлился на "
        f"origin позже) и оставь на старом имени файл-указатель — ссылки на старый адрес уже "
        f"уехали в коммиты, мёртвая ссылка хуже указателя")


def test_file_and_index_measurements_are_not_the_same_measurement():
    """Два сторожа обязаны отвечать на РАЗНЫЕ вопросы, иначе второй — украшение.

    Контроль на вырождение: реестр, «выглядящий целым», не должен успокаивать измерение по
    файлам. Ровно эта разница и есть причина существования `file_duplicates` — если бы она
    исчезла (например, `file_duplicates` начал бы читать INDEX.md), тест назовёт это вслух.
    """
    findings = adr.file_duplicates(ROOT / "spa_core")   # каталога решений там нет
    assert findings == {}, "измерение обязано молчать там, где решений нет"

    src = (ROOT / "scripts" / "adr_number.py").read_text(encoding="utf-8")
    body = src.split("def file_duplicates(")[1].split("\ndef ")[0]
    assert "INDEX" not in body and "parse_index" not in body, (
        "file_duplicates начал читать реестр — второе измерение схлопнулось в копию первого, "
        "и авария 067 (реестр цел, файлы столкнулись) снова пройдёт незамеченной")


def test_baseline_entries_carry_a_traceable_reason():
    """Молчаливых записей в базе нет: у каждой — причина и карточка, где она решается.

    **Намеренное изменение проверки (инв. #16, цикл #251, журнал `docs/journal/2026-W33.md`).**
    Здесь стояло `assert baseline["known_duplicates"]` («пустая база — сначала удали храповик»).
    Оно было верно ровно до тех пор, пока дубль существовал, и становилось ЛОЖНОЙ ТРЕВОГОЙ в
    момент, когда храповик добивался своей цели: 2026-08-15 последний дубль (`067`) разошёлся
    в ADR-087, база опустела — и проверка покраснела бы на УСПЕХЕ, требуя снять сторожа именно
    тогда, когда он впервые стал максимально строгим (при пустой базе любой дубль — новый).

    Прежний запрет — молчаливая запись без причины — сохранён дословно. Заменено ровно одно
    утверждение: «база непуста» → «пустая база легальна ТОЛЬКО при пустой реальности». Ослабления
    нет: единственный случай, который перестал краснеть, — пустая база при отсутствии дублей,
    то есть достигнутая цель храповика; пустая база при живом дубле краснеет по-прежнему.

    Общую сверку «база ≡ реальность» этот тест намеренно НЕ повторяет: обе её стороны уже держит
    соседний `test_live_duplicate_numbers_only_shrink` (`new` и `healed`), и продублировать её
    здесь значило бы повторить дефект, разобранный в цикле #250, — одна проверка обязана
    утверждать ОДНО, иначе мутация красит три теста и непонятно, чей отказ настоящий.
    """
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    known = baseline["known_duplicates"]

    for key, why in known.items():
        assert why.get("reason"), f"{key}: причина не записана"
        assert why.get("card"), f"{key}: не названа карточка, где это решается"

    if not known:
        assert not adr.live_duplicates(ROOT), (
            "база храповика пуста, а в docs/decisions/INDEX.md живой дубль "
            f"{sorted(adr.live_duplicates(ROOT))}: пустая база разрешена только тогда, когда "
            f"разошлись ВСЕ номера — иначе дубль остался бы вовсе без учёта")
