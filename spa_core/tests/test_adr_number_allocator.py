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
