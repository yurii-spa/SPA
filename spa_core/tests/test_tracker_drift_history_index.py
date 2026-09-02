"""Один обход истории вместо `rev-list` на карточку (цикл #454) — и чем за него можно заплатить.

**Что чинили.** `check_tracker_drift.analyze()` на живом трекере стоил **107 с** и порождал
~1041 процесс git: `git rev-list <ref> -- <путь>` на КАЖДУЮ разошедшуюся карточку, и каждый
такой вызов проходил историю в 1977 коммитов. Эту цену платит не отчёт раз в сутки, а КАЖДЫЙ
обязательный шаг протокола — `orchestrator_queue.py list` зовёт `analyze` всегда (разбор
Inbox, инжест решений владельца, шаг 0-офис). Из-за неё живая доска `_BOARD.md` собиралась
`--no-origin-check` и бо́льшую часть времени писала «Сверка с origin НЕ ИЗМЕРЕНА»: цена
сторожа выключила сторожа. После — **2.5 с**, набор находок сверен ПОИМЕННО (551 = 551).

**Чем за такую замену платят, и почему каждый тест здесь — положительный контроль.**
Ускорение, меняющее вердикт, хуже медленной правды: `stale` («дерево строго отстаёт,
origin авторитетен») и `diverged` («у дерева своя правка, сверять руками») различаются ровно
тем, нашлась ли версия дерева в истории пути. Потерянная версия молча превращает один в
другой. Поэтому проверяется не скорость, а ТОЖДЕСТВО ответа — и отдельно каждая ловушка,
в которую этот способ измерения умеет провалиться:

* версия, пришедшая **merge-коммитом** (без `-m` у `--raw` по merge пусто — в живой истории
  трекера таких коммитов 35 из 864);
* **кириллица** в карточке (`cat-file --batch` объявляет размер в БАЙТАХ, и разбор по
  декодированной строке уезжает на первом же русском слове — а карточки владельцу русские
  по правилу §2.4);
* **удаление** пути (у коммита-удаления blob'а нет, и подставлять там пустоту нельзя);
* **имя пути в кавычках** — версия, которую не удалось разобрать однозначно, обязана стать
  «не измерено», а не тихо пропасть.

Литеральных дат и номеров процессов здесь нет: всё строится в песочнице фикстурой.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _REPO_ROOT / "scripts"
for _p in (str(_REPO_ROOT), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import check_tracker_drift as drift  # noqa: E402

REF = "main"


def _run(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


def _card(title="карточка", status="new", body="тело"):
    return (f"---\ntrackerStatus:\n  type: inbox\ntitle: \"{title}\"\nstatus: {status}\n"
            f"---\n\n{body}\n")


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / drift.TRACKER_REL).mkdir(parents=True)
    _run(root.parent, "init", "-q", "-b", REF, str(root))
    _run(root, "config", "user.email", "t@example.com")
    _run(root, "config", "user.name", "test")
    return root


def _tracker(root: Path) -> Path:
    return root / drift.TRACKER_REL


def _write(root: Path, name: str, text: str) -> Path:
    p = _tracker(root) / f"{name}.md"
    p.write_text(text, encoding="utf-8")
    return p


def _commit(root: Path, msg="c"):
    _run(root, "add", "-A")
    _run(root, "commit", "-q", "-m", msg)


def _index(root: Path):
    return drift.HistoryIndex.build(root, REF, drift.TRACKER_REL)


def _rel(name: str) -> str:
    return f"{drift.TRACKER_REL}/{name}.md"


# --------------------------------------------------------------------------------------
# Тождество ответа. Старый способ (процесс git на путь) — эталон; новый обязан совпасть
# с ним ПОИМЕННО на всех путях каталога, а не «в основном».
# --------------------------------------------------------------------------------------

def test_index_returns_exactly_what_the_per_path_walk_returned(repo):
    """Эталон и замена дают один и тот же набор версий для КАЖДОГО пути.

    Это главный контроль правки: `_proven_behind` решает `stale` против `diverged` ровно по
    вхождению в этот набор, и лишняя/потерянная версия здесь есть неверный вердикт очереди.
    """
    _write(repo, "inbox-a", _card(status="new"))
    _write(repo, "inbox-b", _card(title="вторая"))
    _commit(repo)
    _write(repo, "inbox-a", _card(status="in-progress"))
    _commit(repo, "правка a")
    _write(repo, "inbox-a", _card(status="done", body="тело\n\n## Резолюция"))
    _write(repo, "inbox-c", _card(title="третья"))
    _commit(repo, "закрытие a + новая c")

    index = _index(repo)
    for name in ("inbox-a", "inbox-b", "inbox-c"):
        rel = _rel(name)
        assert drift.historical_blobs(repo, rel, REF, index) == \
            drift.historical_blobs(repo, rel, REF), f"наборы версий разошлись у {name}"
    assert len(index.blobs(_rel("inbox-a"))) == 3, "три правки — три версии, новые первыми"


def test_a_version_that_exists_only_at_the_merge_commit_is_not_lost(repo):
    """Положительный контроль `-m`: без него `--raw` по merge-коммиту печатает НИЧЕГО.

    Ловушка узкая, и первая редакция этого теста её ПРОМАХНУЛА (снятие `-m` оставляло тест
    зелёным): когда мёрж просто принимает версию ветки, та же версия лежит и в коммите самой
    ветки, и обход её всё равно находит. Теряется только версия, которой нет НИ У ОДНОГО
    родителя, — разрешение конфликта. В живой истории трекера, где параллельные сессии правят
    одни и те же карточки, это ровно тот случай, который и случается: две ветки закрыли
    карточку по-разному, мёрж свёл их в третий текст. Потеряв его, сторож объявит «у дерева
    своя правка, сверять руками» карточке, которая на origin ровно такая и есть.
    """
    _write(repo, "inbox-m", _card(status="new"))
    _commit(repo, "база")
    _run(repo, "checkout", "-q", "-b", "side")
    _write(repo, "inbox-m", _card(status="done", body="версия ветки"))
    _commit(repo, "закрыто в ветке")
    _run(repo, "checkout", "-q", REF)
    _write(repo, "inbox-m", _card(status="in-progress", body="версия main"))
    _commit(repo, "правка в main")
    subprocess.run(["git", "-C", str(repo), "merge", "--no-ff", "-m", "мёрж", "side"],
                   capture_output=True, text=True)  # конфликт ожидаем — разрешаем ниже
    resolved = _card(status="done", body="разрешение конфликта: текста нет ни у одного родителя")
    _write(repo, "inbox-m", resolved)
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "мёрж разрешён")
    resolved_sha = drift.blob_sha(resolved.encode())

    rel = _rel("inbox-m")
    assert resolved_sha in drift.historical_blobs(repo, rel, REF), (
        "предпосылка теста: прежний обход по пути эту версию находит")
    assert resolved_sha in _index(repo).blobs(rel), (
        "версия, живущая ТОЛЬКО в merge-коммите, обязана быть в истории пути — без `-m` "
        "у `git log --raw` её там нет")
    assert drift.historical_blobs(repo, rel, REF, _index(repo)) == \
        drift.historical_blobs(repo, rel, REF), "наборы версий разошлись на мёрже"


def test_merge_is_counted_once_not_once_per_parent(repo):
    """`-m` показывает merge против КАЖДОГО родителя — post-image один, версий тоже одна.

    Иначе потолок зонда (`_HISTORY_PROBE_CAP`) выедался бы повторами одного и того же
    содержимого, и глубина сверки молча падала бы на карточках с мёржами.
    """
    _write(repo, "inbox-m", _card(status="new"))
    _commit(repo, "база")
    _run(repo, "checkout", "-q", "-b", "side")
    _write(repo, "inbox-m", _card(status="done", body="версия ветки"))
    _commit(repo, "ветка")
    _run(repo, "checkout", "-q", REF)
    _write(repo, "inbox-m", _card(status="in-progress", body="версия main"))
    _commit(repo, "main")
    subprocess.run(["git", "-C", str(repo), "merge", "--no-ff", "-m", "мёрж", "side"],
                   capture_output=True, text=True)
    _write(repo, "inbox-m", _card(status="done", body="после мёржа"))
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "мёрж разрешён")

    blobs = _index(repo).blobs(_rel("inbox-m"))
    assert len(blobs) == len(set(blobs)), f"версии продублированы по родителям мёржа: {blobs}"
    assert len(blobs) == len(drift.historical_blobs(repo, _rel("inbox-m"), REF)), (
        "число версий обязано совпасть с прежним обходом по пути, а не только не иметь дублей")


def test_deleted_path_contributes_no_blob(repo):
    """У коммита-удаления версии пути нет — и подставлять там пустую строку нельзя.

    Пустой текст, попавший в историю, совпал бы разве что с пустым файлом, но `historical_blobs`
    от лишнего sha испортил бы вердикт `deleted_on_origin`/`undelivered`.
    """
    text = _card(title="исчезнет")
    _write(repo, "inbox-gone", text)
    _commit(repo, "создана")
    (_tracker(repo) / "inbox-gone.md").unlink()
    _commit(repo, "удалена")

    blobs = _index(repo).blobs(_rel("inbox-gone"))
    assert blobs == [drift.blob_sha(text.encode())], (
        "в истории пути должна остаться РОВНО одна версия — та, что жила до удаления")
    assert drift.historical_blobs(repo, _rel("inbox-gone"), REF, _index(repo)) == \
        drift.historical_blobs(repo, _rel("inbox-gone"), REF)


def test_quoted_path_is_unmeasured_not_a_silently_dropped_version(repo):
    """Fail-CLOSED: строку истории, которую не разобрать однозначно, нельзя пропустить молча.

    Молча потерянная версия пути превращает `stale` в `diverged` — то есть «origin
    авторитетен» в «сверяйте руками» — и никто об этом не узнает.
    """
    real = drift._git

    def fake(root, args, stdin_text=None):
        if "log" in args:
            return 0, ('\x00abc123\n'
                       ':100644 100644 1111111 2222222 M\t"nimbalyst-local/tracker/имя.md"\n')
        return real(root, args, stdin_text)

    drift._git, saved = fake, real
    try:
        with pytest.raises(drift.Unmeasured) as err:
            _index(repo)
    finally:
        drift._git = saved
    assert "кавычк" in str(err.value)


# --------------------------------------------------------------------------------------
# Батч текстов: заголовок `cat-file --batch` объявляет размер в БАЙТАХ.
# --------------------------------------------------------------------------------------

def test_batch_texts_survive_cyrillic(repo):
    """Карточки владельцу по правилу §2.4 обязаны быть по-русски — разбор по символам врёт.

    Положительный контроль именно нарезки: два blob'а подряд, первый русский. Отсчитав его
    длину в символах вместо байтов, разбор съедет и второй текст придёт мусором.
    """
    first = _card(title="Добавить ключ Etherscan на сервер",
                  body="Без него не работает проверка кошельков — длинная русская строка.")
    second = _card(title="вторая", body="ASCII tail")
    _write(repo, "inbox-ru", first)
    _write(repo, "inbox-ascii", second)
    _commit(repo)

    sha_ru, sha_ascii = drift.blob_sha(first.encode()), drift.blob_sha(second.encode())
    texts = drift.batch_blob_texts(repo, [sha_ru, sha_ascii])
    assert texts[sha_ru] == first
    assert texts[sha_ascii] == second


def test_batch_texts_omit_unknown_blobs_instead_of_inventing_empty_ones(repo):
    """`<oid> missing` — это «не измерено», а не «пустая карточка»."""
    text = _card()
    _write(repo, "inbox-x", text)
    _commit(repo)
    known = drift.blob_sha(text.encode())
    missing = "0" * 40

    texts = drift.batch_blob_texts(repo, [known, missing])
    assert texts == {known: text}, "неизвестный blob обязан отсутствовать, а не прийти пустым"


def test_historical_texts_agree_with_the_per_path_walk(repo):
    """Тексты версий (и флаг «упёрлись в потолок») — тоже поимённо те же, что были."""
    for status in ("new", "in-progress", "done"):
        _write(repo, "inbox-t", _card(status=status, body=f"тело {status}"))
        _commit(repo, status)

    rel = _rel("inbox-t")
    assert drift.historical_texts(repo, rel, REF, _index(repo)) == \
        drift.historical_texts(repo, rel, REF)


# --------------------------------------------------------------------------------------
# Сквозной вердикт: ускорение не имеет права передвинуть карточку между классами находок.
# --------------------------------------------------------------------------------------

def test_verdicts_are_unchanged_end_to_end(repo):
    """Все пять классов сразу — и `stale`, живущий ровно на истории пути."""
    _write(repo, "inbox-stale", _card(status="new"))
    _write(repo, "inbox-same", _card(title="совпадает"))
    _write(repo, "inbox-gone", _card(title="исчезнет"))
    _commit(repo, "первый")
    stale_text = (_tracker(repo) / "inbox-stale.md").read_text(encoding="utf-8")
    gone_text = (_tracker(repo) / "inbox-gone.md").read_text(encoding="utf-8")

    _write(repo, "inbox-stale", _card(status="done", body="закрыта"))
    _write(repo, "inbox-hidden", _card(title="только на origin"))
    (_tracker(repo) / "inbox-gone.md").unlink()
    _commit(repo, "второй")

    _write(repo, "inbox-stale", stale_text)                    # дерево отстало
    _write(repo, "inbox-gone", gone_text)                      # удалена на origin
    _write(repo, "inbox-diverged", _card(title="своя правка")) # нет на origin вовсе
    (_tracker(repo) / "inbox-hidden.md").unlink()              # невидима дереву

    report = drift.analyze(_tracker(repo), REF)
    got = {f.kind: sorted(x.card_id for x in report.of_kind(f.kind)) for f in report.findings}
    assert got == {
        drift.KIND_STALE: ["inbox-stale"],
        drift.KIND_HIDDEN: ["inbox-hidden"],
        drift.KIND_UNDELIVERED: ["inbox-diverged"],
        drift.KIND_DELETED: ["inbox-gone"],
    }


def test_analyze_does_not_spawn_a_git_process_per_card(repo):
    """Смысл правки — в ЧИСЛЕ процессов; без этого теста регресс вернётся молча.

    Считаем вызовы git, а не секунды: секунды зависят от машины, число вызовов — нет.
    Раньше каждая разошедшаяся карточка стоила `rev-list` + `show` на версию, и рост
    трекера умножал их линейно.
    """
    for i in range(12):
        _write(repo, f"inbox-{i}", _card(status="new", body=f"тело {i}"))
    _commit(repo, "первый")
    olds = {i: (_tracker(repo) / f"inbox-{i}.md").read_text(encoding="utf-8") for i in range(12)}
    for i in range(12):
        _write(repo, f"inbox-{i}", _card(status="done", body=f"закрыта {i}"))
    _commit(repo, "второй")
    for i, text in olds.items():
        _write(repo, f"inbox-{i}", text)

    calls = []
    real = drift._git

    def counting(root, args, stdin_text=None):
        calls.append(args[0] if args[0] != "-c" else args[2])
        return real(root, args, stdin_text)

    drift._git = counting
    try:
        report = drift.analyze(_tracker(repo), REF)
    finally:
        drift._git = real

    assert len(report.of_kind(drift.KIND_STALE)) == 12, "предпосылка теста: 12 отставших карточек"
    assert calls.count("rev-list") == 0, f"обход истории по ПУТИ вернулся: {calls}"
    assert calls.count("log") == 1, f"обход истории каталога должен быть ровно один: {calls}"
    assert len(calls) <= 6, f"процессов git на 12 находок должно быть единицы, а не {len(calls)}"
