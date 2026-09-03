"""Общая память не уезжает вслепую: неизмеримая база пуша = ОТКАЗ.

Решение владельца **ADR-070 п.7** («точечный fail-CLOSED для `docs/STATE.md`,
`docs/journal/*`, `_BOARD.md` при неизмеримой базе пуша; остальное как есть»),
карточка `inbox-adr-070-7-tochechnyi-fail-closed-pamyati`, цикл #151.

ЧТО БЫЛО. Страж перезаписи отвечает честно только там, где у него ЕСТЬ база
(`base_version`). Где базы нет, вердикт `DIVERGENCE_UNMEASURED` печатал ноту и
пуш ПРОПУСКАЛ — направление выбрано намеренно, чтобы не остановить autopush и
дневной цикл. Неизмеренный путь прикрывала проверка записей
(`guard_entry_loss`), но у неё объявленная граница: она ловит исчезновение
ЗАГОЛОВКА записи и НЕ ловит удаление её ТЕЛА. Замер, породивший карточку #139:
`a3c015f05` снёс 1729 строк `docs/STATE.md`, не тронув ни одного заголовка, и
остался невидимым. `_BOARD.md` та проверка не касается вовсе (он пересобирается
целиком).

ПОЧЕМУ ИМЕННО ЭТИ ТРИ ФАЙЛА. По ним потом судят, что было сделано: `CLAUDE.md`
§4 («не записано — работа НЕ завершена») и инвариант #16 (обоснование намеренной
правки теста живёт в журнале) опираются на них как на доказательство. Стёртая
память делает оба непроверяемыми задним числом.

ГРАНИЦА, которую эти тесты стерегут В ОБЕ СТОРОНЫ. Владелец выбрал «точечный»
вариант, а не «строгий везде»: всё остальное при неизмеримой базе уезжает
ПО-ПРЕЖНЕМУ. Страж, который начнёт отказывать autopush'у, будет отключён — и
защита памяти уйдёт вместе с ним. Поэтому контролей «уехало как раньше» здесь
столько же, сколько контролей «отказано».

Все тесты герметичны: настоящих git-репозиториев не требуется там, где база
заведомо неизмерима (обычный каталог), GitHub подменён детерминированным фейком,
сети нет. Времени в тестах нет — литеральных дат в фикстурах нет по построению
(`.claude/rules/deployment.md`, «время в тестах»).

Запуск: python3 -m pytest spa_core/tests/test_shared_memory_unmeasured_base.py -v
"""
import base64
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from spa_core.tests import _pusher_wiring as wiring

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def ptg():
    return _load("_test_mem_ptg", "push_to_github.py")


# ── фейковый GitHub (независимый оракул, сети нет) ───────────────────────────

class FakeRemote:
    def __init__(self, files: dict):
        self.files = {k: v.encode() if isinstance(v, str) else v
                      for k, v in files.items()}
        self.puts: list = []

    def get_file_sha(self, ptg):
        def _sha(pat, repo, repo_path, branch="main"):
            data = self.files.get(repo_path)
            return None if data is None else ptg.git_blob_sha(data)
        return _sha

    def get_file_content(self):
        def _content(pat, repo, repo_path, branch="main"):
            return self.files.get(repo_path)
        return _content

    def urlopen(self):
        class _Resp:
            def __init__(self, payload):
                self._payload = payload

            def read(self):
                return json.dumps(self._payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def _open(req, *a, **kw):
            body = json.loads(req.data.decode())
            path = req.full_url.split("/contents/", 1)[1]
            content = base64.b64decode(body["content"])
            self.files[path] = content
            self.puts.append((path, content))
            import hashlib
            sha = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
            return _Resp({"content": {"sha": sha}})

        return _open


@pytest.fixture()
def plain(tmp_path):
    """Каталог, который НЕ является рабочей копией ветки доставки.

    Ровно та ситуация, в которой база неизмерима: `base_version` не может
    сказать, от чего мы отталкивались, — а значит и того, что затираем.
    """
    root = tmp_path / "plain"
    root.mkdir()
    return root


def _wire(ptg, monkeypatch, remote, root):
    monkeypatch.setattr(ptg, "PROJECT_ROOT", root)
    monkeypatch.setattr(ptg, "get_file_sha", remote.get_file_sha(ptg))
    monkeypatch.setattr(ptg, "get_file_content", remote.get_file_content())
    monkeypatch.setattr(ptg.urllib.request, "urlopen", remote.urlopen())
    monkeypatch.delenv("SPA_AUTONOMOUS", raising=False)


def _write(root: Path, repo_path: str, text) -> Path:
    p = root / repo_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode() if isinstance(text, str) else text)
    return p


STATE_REMOTE = (
    "# SPA - STATE\n\n"
    "> **(цикл #150) — карточка о 16 стёртых записях опровергнута.**\n"
    "> тело записи 150: замер, мутации, приёмка\n\n"
    "> **(цикл #149) — шаг 0a перестал морить очередь.**\n"
    "> тело записи 149: 18 строк НЕ ИЗМЕРЕНО на пустом месте\n\n"
)
JOURNAL_REMOTE = (
    "# journal\n\n"
    "## Цикл #150 (автономный) — что сделано\n\nтело записи 150\n\n"
    "## Цикл #149 (автономный) — что сделано\n\nтело записи 149\n\n"
)
BOARD_REMOTE = "# Доска\n\n- карточка A (needs-owner)\n- карточка B (new)\n"


# ═════════════════════════════════════════════════════════════════════════════
# 1. САМ ДЕФЕКТ: общая память уезжает из копии, у которой базы нет.
#    Каждый тест краснеет на пушере ДО этой правки.
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("repo_path, remote_text", [
    ("docs/STATE.md", STATE_REMOTE),
    ("docs/journal/2026-W32.md", JOURNAL_REMOTE),
    ("nimbalyst-local/tracker/_BOARD.md", BOARD_REMOTE),
])
def test_shared_memory_from_unmeasured_base_is_refused(
        ptg, monkeypatch, plain, repo_path, remote_text):
    """Все три файла общей памяти — отказ, и на remote не уезжает НИЧЕГО."""
    remote = FakeRemote({repo_path: remote_text})
    _wire(ptg, monkeypatch, remote, plain)
    _write(plain, repo_path, "моя версия целиком\n")

    res = ptg.push_file("pat", str(plain / repo_path), "цикл", "o/r")

    assert res["ok"] is False and res.get("diverged") is True
    assert remote.puts == [], "при отказе не должно быть НИ ОДНОЙ записи на remote"
    assert remote.files[repo_path] == remote_text.encode(), "содержимое remote тронуто"


def test_body_loss_that_the_entry_guard_cannot_see_is_now_refused(ptg, monkeypatch, plain):
    """Класс `a3c015f05`: 1729 строк тела снесены, ЗАГОЛОВКИ целы.

    Проверка записей по своей объявленной границе такой пуш пропускает (и это не
    её недосмотр). До этой правки он уезжал молча — вот ровно та потеря, ради
    которой владелец потребовал fail-CLOSED.
    """
    remote = FakeRemote({"docs/STATE.md": STATE_REMOTE})
    _wire(ptg, monkeypatch, remote, plain)
    gutted = "".join(
        line for line in STATE_REMOTE.splitlines(keepends=True)
        if not line.startswith("> тело")
    )
    _write(plain, "docs/STATE.md", gutted)

    # предпосылка теста: ни один ЗАГОЛОВОК не пропал — иначе он проверял бы
    # старую защиту, а не новую
    assert ptg.dropped_entries(STATE_REMOTE.encode(), gutted.encode()) == []

    res = ptg.push_file("pat", str(plain / "docs" / "STATE.md"), "цикл", "o/r")

    assert res["ok"] is False, "потеря ТЕЛА записи уехала молча"
    assert remote.files["docs/STATE.md"] == STATE_REMOTE.encode()


def test_board_is_refused_although_the_entry_guard_never_covered_it(ptg, monkeypatch, plain):
    """`_BOARD.md` проверка записей не трогает вовсе — значит новый страж не дубль.

    Для доски исчезновение строки нормально (она пересобирается целиком), поэтому
    ловить её потерей записи нельзя; а вот запушить доску поверх чужой, не зная
    базы, нельзя тем более.
    """
    board = "nimbalyst-local/tracker/_BOARD.md"
    assert ptg.is_append_only_doc(board) is False, "граница старой проверки сдвинулась"
    assert ptg.is_shared_memory_doc(board) is True

    remote = FakeRemote({board: BOARD_REMOTE})
    _wire(ptg, monkeypatch, remote, plain)
    _write(plain, board, "# Доска\n\n- только моя карточка\n")

    res = ptg.push_file("pat", str(plain / board), "доска", "o/r")

    assert res["ok"] is False
    assert remote.files[board] == BOARD_REMOTE.encode()


def test_refusal_names_the_file_and_the_way_out(ptg, monkeypatch, plain):
    """Отказ без выхода — тупик. Он обязан назвать файл, причину и что делать.

    Берём потерю ТЕЛА (заголовки целы): именно она доходит до нового стража, —
    случай с пропажей заголовка перехватывает проверка записей, и это проверено
    отдельно ниже.
    """
    remote = FakeRemote({"docs/STATE.md": STATE_REMOTE})
    _wire(ptg, monkeypatch, remote, plain)
    gutted = "".join(line for line in STATE_REMOTE.splitlines(keepends=True)
                     if not line.startswith("> тело"))
    _write(plain, "docs/STATE.md", gutted)

    res = ptg.push_file("pat", str(plain / "docs" / "STATE.md"), "цикл", "o/r")

    err = res["error"]
    assert "docs/STATE.md" in err
    assert "НЕ ИЗМЕРЕНО" in err, "причина отказа не названа"
    assert "worktree" in err, "не сказано, откуда пушить общую память"
    assert "--allow-overwrite" in err, "осознанный обход не назван — отказ стал тупиком"


def test_the_more_specific_refusal_wins_when_entries_disappear(ptg, monkeypatch, plain):
    """Пропали ЗАГОЛОВКИ ⇒ побеждает сообщение, называющее пропавшее поимённо.

    Порядок проверок выбран ради этого: оба пути ведут к отказу, но автору
    нужнее тот, который говорит, ЧТО именно восстанавливать. Если однажды новый
    страж встанет раньше, этот тест покраснеет — потеря полезного сообщения не
    должна пройти незамеченной.
    """
    remote = FakeRemote({"docs/STATE.md": STATE_REMOTE})
    _wire(ptg, monkeypatch, remote, plain)
    _write(plain, "docs/STATE.md", "# SPA - STATE\n\n> **(цикл #151) — только моя.**\n")

    res = ptg.push_file("pat", str(plain / "docs" / "STATE.md"), "цикл", "o/r")

    assert res["ok"] is False
    assert "стёр бы 2 запис" in res["error"], "отказ не называет пропадающие записи"
    assert "цикл #150" in res["error"]


def test_missing_file_on_remote_is_still_refused(ptg, monkeypatch, plain):
    """`sha is None` — НЕ доказательство, что терять нечего.

    Тот же аргумент, что и в `divergence_verdict`: отсутствующая sha значит и
    «файла нет», и «сеть отвалилась», и «файл удалили» — различить нельзя.
    Считать это «всё в порядке» и было бы fail-OPEN.
    """
    remote = FakeRemote({})
    _wire(ptg, monkeypatch, remote, plain)
    _write(plain, "docs/journal/2026-W33.md", "# journal\n\n## Цикл #151\n")

    res = ptg.push_file("pat", str(plain / "docs" / "journal" / "2026-W33.md"),
                        "цикл", "o/r")

    assert res["ok"] is False and remote.puts == []


# ═════════════════════════════════════════════════════════════════════════════
# 2. ГРАНИЦА «остальное как есть»: живая доставка не остановлена.
#    Без этих контролей правка доказывала бы лишь «отказ существует».
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("repo_path", [
    "data/agent_health.json",          # дневной цикл и мониторы
    "CURRENT_STATE.md",                # ДРУГОЙ файл: его пушат push_v*.sh
    "spa_core/monitoring/health.py",   # обычный код
    "docs/journal/notes.txt",          # в каталоге памяти, но не запись
    "landing/src/pages/index.astro",   # сайт (кастодиан, safe_site_push)
])
def test_everything_else_still_pushes_from_unmeasured_base(
        ptg, monkeypatch, plain, repo_path):
    """Прежний путь доставки цел — владелец выбрал ТОЧЕЧНЫЙ вариант."""
    remote = FakeRemote({repo_path: "старое содержимое\n"})
    _wire(ptg, monkeypatch, remote, plain)
    _write(plain, repo_path, "новое содержимое\n")

    res = ptg.push_file("pat", str(plain / repo_path), "autopush", "o/r")

    assert res["ok"] is True, f"{repo_path} заблокирован, хотя не общая память"
    assert remote.files[repo_path] == "новое содержимое\n".encode()


def test_unmeasured_is_still_never_reported_as_safe(ptg, monkeypatch, plain, capsys):
    """Не-память по-прежнему уезжает с НАЗВАННОЙ причиной, а не молча."""
    remote = FakeRemote({"data/x.json": "{}\n"})
    _wire(ptg, monkeypatch, remote, plain)
    _write(plain, "data/x.json", '{"новое": 1}\n')

    ptg.push_file("pat", str(plain / "data" / "x.json"), "autopush", "o/r")

    out = capsys.readouterr().out
    assert "НЕ ИЗМЕРЕНО" in out


def test_allow_overwrite_is_the_deliberate_escape_hatch(ptg, monkeypatch, plain):
    """Осознанная перезапись остаётся возможной — но перестаёт быть умолчанием."""
    remote = FakeRemote({"docs/STATE.md": STATE_REMOTE})
    _wire(ptg, monkeypatch, remote, plain)
    _write(plain, "docs/STATE.md", "моя версия\n")

    res = ptg.push_file("pat", str(plain / "docs" / "STATE.md"), "цикл", "o/r",
                        allow_overwrite=True)

    assert res["ok"] is True
    assert remote.files["docs/STATE.md"] == "моя версия\n".encode()


# ═════════════════════════════════════════════════════════════════════════════
# 3. Там, где база ЕСТЬ (worktree протокола §3.4), новый страж не мешает
# ═════════════════════════════════════════════════════════════════════════════
def _git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["HOME"] = str(cwd)
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, check=True, env=env)


@pytest.mark.skipif(shutil.which("git") is None,
                    reason="нужен настоящий git: база читается через git cat-file")
def test_measured_base_delivers_shared_memory_verbatim(ptg, monkeypatch, tmp_path):
    """Из worktree от ветки доставки память уезжает БАЙТ В БАЙТ, как и раньше.

    Это главный контроль в обратную сторону: отказ обязан быть невозможен на
    штатном пути, иначе правка остановила бы каждый цикл оркестратора.
    """
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _write(root, "docs/STATE.md", STATE_REMOTE)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "база")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")

    remote = FakeRemote({"docs/STATE.md": STATE_REMOTE})
    _wire(ptg, monkeypatch, remote, root)
    mine = ("# SPA - STATE\n\n"
            "> **(цикл #151) — общая память под fail-CLOSED.**\n"
            "> тело записи 151\n\n") + STATE_REMOTE.split("\n\n", 1)[1]
    _write(root, "docs/STATE.md", mine)

    res = ptg.push_file("pat", str(root / "docs" / "STATE.md"), "цикл #151", "o/r")

    assert res["ok"] is True, res
    assert remote.files["docs/STATE.md"] == mine.encode()


# ═════════════════════════════════════════════════════════════════════════════
# 4. Набор путей — точечный и НЕ совпадает с набором проверки записей
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("repo_path, expected", [
    ("docs/STATE.md", True),
    ("docs/journal/2026-W32.md", True),
    ("docs/journal/STATE-archive-2026-08-07.md", True),
    ("nimbalyst-local/tracker/_BOARD.md", True),
    ("CURRENT_STATE.md", False),
    ("docs/STATE_ARCHIVE.md", False),
    ("docs/journal/notes.txt", False),
    ("nimbalyst-local/tracker/inbox-adr-070-7-tochechnyi.md", False),
    ("push_to_github.py", False),
    ("data/golive_status.json", False),
])
def test_shared_memory_set_is_exactly_what_the_owner_named(ptg, repo_path, expected):
    assert ptg.is_shared_memory_doc(repo_path) is expected


def test_the_two_sets_are_deliberately_different(ptg):
    """`_BOARD.md` — память, но НЕ append-only: перепутать их значило бы либо
    краснеть на каждой пересборке доски, либо оставить доску без защиты."""
    board = "nimbalyst-local/tracker/_BOARD.md"
    assert ptg.is_shared_memory_doc(board) and not ptg.is_append_only_doc(board)
    for p in ("docs/STATE.md", "docs/journal/2026-W32.md"):
        assert ptg.is_shared_memory_doc(p) and ptg.is_append_only_doc(p)


# ═════════════════════════════════════════════════════════════════════════════
# 5. ВСТРАИВАНИЕ: проверка бесполезна, если её никто не зовёт
# ═════════════════════════════════════════════════════════════════════════════
def test_refusal_is_a_divergence_refusal(ptg):
    """Оба вызывающих ловят `DivergenceRefused` — иначе отказ проломит батч
    трассировкой вместо честного FAIL."""
    assert issubclass(ptg.UnmeasuredBaseRefused, ptg.DivergenceRefused)


def test_guard_is_wired_into_the_unmeasured_branch(ptg):
    src = (ROOT / "push_to_github.py").read_text(encoding="utf-8")
    unmeasured = src.split("DIVERGENCE_UNMEASURED:")[1].split("# DIVERGENCE_DIVERGED")[0]
    assert "is_shared_memory_doc" in unmeasured, (
        "страж не встроен в ветку, ради которой написан")
    # Подъём #467: с появлением второй охраняемой единицы смысла ветка зовёт
    # дверь `guard_content_loss`. Вопрос («доходит ли сюда проверка записей?»)
    # тот же и стал строже — второе звено меряется разбором AST, а не текстом.
    wiring.assert_branch_reaches(unmeasured, "guard_entry_loss",
                                 "неизмеренная ветка (защита #139)")


def test_batch_push_of_shared_memory_aborts_the_whole_set(ptg, monkeypatch, plain):
    """Отказ роняет ВЕСЬ батч: рваного набора на main не появляется."""
    remote = FakeRemote({"docs/STATE.md": STATE_REMOTE})
    _wire(ptg, monkeypatch, remote, plain)
    _write(plain, "docs/STATE.md", "моя версия\n")
    code = _write(plain, "spa_core/x.py", "print(1)\n")

    calls: list = []

    def fake_api(pat, method, path, payload=None):
        calls.append(f"{method} {path}")
        if method == "GET" and "/git/ref/heads/" in path:
            return {"object": {"sha": "basecommit"}}
        if method == "GET" and "/git/commits/" in path:
            return {"tree": {"sha": "basetree"}}
        if method == "GET" and "/git/trees/" in path:
            return {"tree": [], "truncated": False}
        if method == "POST" and path.endswith("/git/blobs"):
            return {"sha": "b" * 40}
        raise AssertionError(f"батч дошёл до записи, хотя обязан был отказать: {method}")

    monkeypatch.setattr(ptg, "_api", fake_api)
    with pytest.raises(ptg.DivergenceRefused):
        ptg.batch_push("pat", [str(plain / "docs" / "STATE.md"), str(code)],
                       "цикл", "o/r", "main")

    assert not any(c.startswith("PATCH") for c in calls), "ветка сдвинулась при отказе"


def test_guard_does_not_depend_on_who_launched_the_pusher(ptg, monkeypatch, plain):
    """Никакой привязки к `SPA_AUTONOMOUS`: один и тот же набор файлов обязан
    доставляться одинаково из cron и из рук (иначе тесты зависят от среды)."""
    remote = FakeRemote({"docs/STATE.md": STATE_REMOTE})
    _wire(ptg, monkeypatch, remote, plain)
    monkeypatch.setenv("SPA_AUTONOMOUS", "1")
    _write(plain, "docs/STATE.md", "моя версия\n")

    with_env = ptg.push_file("pat", str(plain / "docs" / "STATE.md"), "цикл", "o/r")
    monkeypatch.delenv("SPA_AUTONOMOUS", raising=False)
    without_env = ptg.push_file("pat", str(plain / "docs" / "STATE.md"), "цикл", "o/r")

    assert with_env["ok"] is False and without_env["ok"] is False


def test_both_pushers_share_one_implementation(ptg):
    """Второй копии логики быть не должно (историческая беда двух пушеров)."""
    batch = _load("_test_mem_batch", "push_to_github_batch.py")
    for name in ("is_shared_memory_doc", "UnmeasuredBaseRefused", "guard_overwrite"):
        assert getattr(batch, name) is getattr(batch._root_push, name), (
            f"{name} разъехался между push_to_github_batch.py и каноническим модулем")
