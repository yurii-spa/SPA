"""Слепок отправляемых байтов: гейт судил одни байты, уехать собрались другие.

**Авария, которую воспроизводит каждый тест** (замер цикла #890, ADR-774).
У доставки не было своего окна. Пушер сверяет инструмент доставки и — с
ADR-772 — окно мутационного прибора, но ни один из этих вопросов не про САМИ
уезжающие байты: оба отвечают в момент T1, а байты читаются с диска в T2 > T1.

Замер до работы, на живом origin, набор из 10 файлов:

* каждый путь читался с диска НЕЗАВИСИМО ДВА раза — `split_unchanged`
  (решение «изменился ли файл») и `build_entries` (байты, которые уедут), с
  разбросом 0.90…3.87 с;
* окно «первый гейт → чтение отправляемых байтов» = 1.48 с у первого файла и
  5.96 с у последнего, и растёт ЛИНЕЙНО по числу файлов (свой GET на файл);
* положительный контроль с заглушённой сетью: гейт окна ответил «окна нет»
  (верно в T1), прибор открыл окно сразу после него — пушер вышел **0**,
  напечатал «OK: 1 коммит» и отдал байты, которых не судил НИ ОДИН гейт.
  Цели того прибора — `risk/policy.py` и `governance/kill_switch.py`, то есть
  money-path.

Сеть НЕ ТРОГАЕТСЯ: `_api` подменён детерминированным фейком, который считает
созданные blob'ы, — поэтому «уехало или нет» здесь ИЗМЕРЕНИЕ, а не
предположение. Литеральных дат и литеральных pid в файле нет вовсе: предмет —
содержимое файлов, календарь и номера процессов к нему отношения не имеют.

Запуск: python3 -m pytest spa_core/tests/test_delivery_bytes_pin.py -v
"""
from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PUSHER = ROOT / "push_to_github.py"
BATCH_CLI = ROOT / "push_to_github_batch.py"


class Unmeasured(AssertionError):
    """НЕ ИЗМЕРЕНО с названной причиной — третий исход, а не «чисто»."""


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeGitHub:
    """Фейковый remote: ровно те эндпоинты, которыми пользуется `batch_push`."""

    def __init__(self, tree: dict | None = None):
        self.tree = dict(tree or {})
        self.blobs: list[str] = []
        self.commits: list[dict] = []
        self.trees: list[dict] = []
        self.ref_updates: list[str] = []
        self._n = 0

    def _sha(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n:038d}"

    def api(self, pat, method, path, payload=None):
        if method == "GET" and "/git/ref/heads/" in path:
            return {"object": {"sha": "basecommit"}}
        if method == "GET" and "/git/commits/" in path:
            return {"tree": {"sha": "basetree"}}
        if method == "GET" and "/git/trees/" in path:
            return {"tree": [{"path": p, "mode": m, "type": "blob", "sha": s}
                             for p, (m, s) in self.tree.items()],
                    "truncated": False}
        if method == "POST" and path.endswith("/git/blobs"):
            sha = self._sha("b")
            self.blobs.append(payload["content"])
            return {"sha": sha}
        if method == "POST" and path.endswith("/git/trees"):
            sha = self._sha("t")
            self.trees.append({"sha": sha, **payload})
            return {"sha": sha}
        if method == "POST" and path.endswith("/git/commits"):
            sha = self._sha("c")
            self.commits.append({"sha": sha, **payload})
            return {"sha": sha}
        if method == "PATCH" and "/git/refs/heads/" in path:
            self.ref_updates.append(payload["sha"])
            return {"object": {"sha": payload["sha"]}}
        raise AssertionError(f"фейк не знает эндпоинт: {method} {path}")


@pytest.fixture()
def ptg():
    mod = _load("_pin_ptg", "push_to_github.py")
    yield mod
    mod.reset_delivery_pin()


@pytest.fixture()
def repo(tmp_path):
    """Настоящий одноразовый репозиторий.

    `-b main` объявлен ЯВНО: `init.defaultBranch` — свойство ХОСТА (Apple Git
    даёт `main`, git на `ubuntu-latest` — `master`), и фикстура, промолчавшая об
    имени, зелена здесь и красна в CI (`.claude/rules/deployment.md`,
    «GIT-ОКРУЖЕНИЕ в тестах»).
    """
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    return r


@pytest.fixture()
def wired(ptg, repo, monkeypatch):
    """Пушер на фейковом remote и одноразовом дереве. Remote пуст ⇒ всё новое."""
    gh = FakeGitHub()
    monkeypatch.setattr(ptg, "PROJECT_ROOT", repo)
    monkeypatch.setattr(ptg, "_api", gh.api)
    monkeypatch.setattr(ptg, "get_file_sha", lambda *a, **k: None)
    return ptg, gh


def _write(repo: Path, rel: str, text: str) -> Path:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# ═════════════════════════════════════════════════════════════════════════════
# A. АВАРИЯ ДОСЛОВНО: гейт судил байты A, уехали байты B
# ═════════════════════════════════════════════════════════════════════════════
def test_bytes_swapped_after_the_pin_refuse_and_name_the_file(wired, repo):
    """Дословный замер #890: подмена сразу после гейта окна мутаций.

    ДО ADR-774 этот прогон давал код 0 и «OK: 1 коммит», а в blob уезжало
    содержимое, которого не судил ни один гейт.
    """
    ptg, gh = wired
    target = _write(repo, "spa_core/risk/policy.py", "APY_MAX = 0.30\n")
    other = _write(repo, "docs/note.md", "текст\n")
    ptg.pin_delivery_bytes([str(target), str(other)])

    target.write_text("APY_MAX = 99.0  # мутант\n", encoding="utf-8")

    with pytest.raises(ptg.DeliveryBytesDrifted) as exc:
        ptg.batch_push("pat", [str(target), str(other)], "msg", "o/r", "main")

    assert "spa_core/risk/policy.py" in str(exc.value), (
        "отказ обязан НАЗВАТЬ файл: без имени читатель не знает, кого искать")
    assert gh.commits == [] and gh.ref_updates == [], (
        "ни один коммит не создан — отказ fail-CLOSED, а не предупреждение")


def test_untouched_bytes_are_delivered_without_a_false_refusal(wired, repo):
    """Обратная сторона: без подмены пин ничему не мешает.

    Без этого теста предыдущий был бы зелен и на пушере, который отказывает
    ВСЕГДА, — то есть мерил бы не тот предмет.
    """
    ptg, gh = wired
    files = [str(_write(repo, f"pkg/f{i}.py", f"x = {i}\n")) for i in range(3)]
    ptg.pin_delivery_bytes(files)

    res = ptg.batch_push("pat", files, "msg", "o/r", "main")

    assert res["ok"] and res["count"] == 3
    assert len(gh.commits) == 1
    assert "сверен" in ptg.delivery_pin_summary()


# ═════════════════════════════════════════════════════════════════════════════
# B. ДВА НЕЗАВИСИМЫХ ЧТЕНИЯ ОДНОГО ПУТИ БЫЛИ ДВУМЯ НАБЛЮДЕНИЯМИ
#
# Замер: решение «изменился ли файл» принималось по чтению в `split_unchanged`,
# а уезжало содержимое ДРУГОГО чтения — в `build_entries`, через 0.90…3.87 с.
# ═════════════════════════════════════════════════════════════════════════════
def test_change_between_the_idempotency_read_and_the_upload_read_refuses(
        wired, repo, monkeypatch):
    """Подмена ровно в зазоре между двумя чтениями одного пути."""
    ptg, gh = wired
    target = _write(repo, "pkg/a.py", "a = 1\n")
    ptg.pin_delivery_bytes([str(target)])

    real_split = ptg.split_unchanged

    def split_then_swap(pat, repo_name, branch, files):
        out = real_split(pat, repo_name, branch, files)
        target.write_text("a = 2\n", encoding="utf-8")   # зазор
        return out

    monkeypatch.setattr(ptg, "split_unchanged", split_then_swap)

    with pytest.raises(ptg.DeliveryBytesDrifted) as exc:
        ptg.batch_push("pat", [str(target)], "msg", "o/r", "main")

    assert "pkg/a.py" in str(exc.value)
    assert gh.blobs == [], "blob не создан: байты уехать не успели"


def test_the_skip_verdict_and_the_bytes_are_one_observation(ptg, repo, monkeypatch):
    """Файл, совпавший с remote, пропускается — и то же чтение сверено слепком.

    Обратная сторона предыдущего: «одно наблюдение» обязано работать и там, где
    решение — НЕ отправлять.
    """
    gh = FakeGitHub()
    monkeypatch.setattr(ptg, "PROJECT_ROOT", repo)
    monkeypatch.setattr(ptg, "_api", gh.api)
    f = _write(repo, "pkg/same.py", "same\n")
    same_sha = ptg.git_blob_sha(f.read_bytes())
    monkeypatch.setattr(ptg, "get_file_sha", lambda *a, **k: same_sha)
    ptg.pin_delivery_bytes([str(f)])

    res = ptg.batch_push("pat", [str(f)], "msg", "o/r", "main")

    assert res["count"] == 0 and res["skipped"] == 1
    assert ptg.delivery_pin_summary() == "слепок байтов сверен у 1 чтени(я/й)"


# ═════════════════════════════════════════════════════════════════════════════
# C. ТРЕТИЙ ИСХОД (инв. #17): «слепок не снимали» ≠ «байты сверены»
# ═════════════════════════════════════════════════════════════════════════════
def test_unpinned_read_is_unmeasured_and_says_so(ptg, repo, monkeypatch):
    """Библиотечный вызов `batch_push` минуя CLI: сверять НЕ С ЧЕМ.

    Отказывать здесь было бы неверно (притязания никто не выдвигал), а молчать —
    тот самый fail-OPEN: «не измерено» стало бы неотличимо от «сверено».
    """
    gh = FakeGitHub()
    monkeypatch.setattr(ptg, "PROJECT_ROOT", repo)
    monkeypatch.setattr(ptg, "_api", gh.api)
    monkeypatch.setattr(ptg, "get_file_sha", lambda *a, **k: None)
    f = _write(repo, "pkg/x.py", "x\n")

    res = ptg.batch_push("pat", [str(f)], "msg", "o/r", "main")

    assert res["ok"], "отказа тут нет: слепка никто не обещал"
    summary = ptg.delivery_pin_summary()
    assert "НЕ ИЗМЕРЕНО" in summary and "сверен у" not in summary, (
        f"третий исход обязан быть ОТДЕЛЬНЫМ значением, а не тишиной: {summary}")
    assert any(v["state"] == "unmeasured" and v["reason"]
               for v in ptg._PIN_VERDICTS), "у исхода обязана быть НАЗВАННАЯ причина"


def test_pinned_read_is_not_reported_as_unmeasured(wired, repo):
    """Обратная сторона: снятый слепок НЕ выдаётся за «не измерено».

    Без этого предыдущий тест был бы зелен на пушере, который всегда говорит
    «не измерено», — то есть на снятом сторожe.
    """
    ptg, _ = wired
    f = _write(repo, "pkg/y.py", "y\n")
    ptg.pin_delivery_bytes([str(f)])
    ptg.batch_push("pat", [str(f)], "msg", "o/r", "main")
    assert "НЕ ИЗМЕРЕНО" not in ptg.delivery_pin_summary()


def test_reader_never_called_is_its_own_verdict(ptg):
    """«Читателя не позвали» ≠ «сверено у нуля». Пустой счёт есть находка."""
    ptg.reset_delivery_pin()
    assert ptg.delivery_pin_summary() == "слепок байтов: читателя не позвали НИ РАЗУ"


# ═════════════════════════════════════════════════════════════════════════════
# D. ПУТЬ, КОТОРОГО В СЛЕПКЕ НЕТ — это отказ, а не «не измерено»
# ═════════════════════════════════════════════════════════════════════════════
def test_path_absent_from_the_pin_refuses_with_its_own_reason(ptg, repo):
    """Набор изменился ПОСЛЕ пина: слепок брался по тому же списку.

    Своя причина обязательна: «набор вырос» и «байты подменили» ведут читателя
    в РАЗНЫЕ места, и общее сообщение увело бы в одно из них наугад.
    """
    pinned = _write(repo, "pkg/pinned.py", "p\n")
    sneaked = _write(repo, "pkg/sneaked.py", "s\n")
    ptg.pin_delivery_bytes([str(pinned)])

    with pytest.raises(ptg.DeliveryBytesDrifted) as exc:
        ptg.read_delivery_bytes(str(sneaked))

    assert "набор изменился" in str(exc.value)
    assert "pkg/sneaked.py" in str(exc.value) or str(sneaked) in str(exc.value)


def test_path_present_in_the_pin_is_read_without_a_refusal(ptg, repo):
    """Обратная сторона D: присутствие в слепке ничего не ломает."""
    f = _write(repo, "pkg/ok.py", "ok\n")
    ptg.pin_delivery_bytes([str(f)])
    assert ptg.read_delivery_bytes(str(f)) == b"ok\n"


# ═════════════════════════════════════════════════════════════════════════════
# E. НЕЧИТАЕМЫЙ В МОМЕНТ ПИНА — причина НАЗВАНА, а не подменена
# ═════════════════════════════════════════════════════════════════════════════
def test_unreadable_at_pin_time_keeps_its_own_named_reason(ptg, repo):
    missing = repo / "pkg" / "gone.py"
    pin = ptg.pin_delivery_bytes([str(missing)])
    assert str(missing) in pin["unreadable"]
    assert "Error" in pin["unreadable"][str(missing)], (
        "причина обязана назвать ошибку ОС, а не просто «не прочитано»")

    missing.parent.mkdir(parents=True, exist_ok=True)
    missing.write_text("появился позже\n", encoding="utf-8")
    with pytest.raises(ptg.DeliveryBytesDrifted) as exc:
        ptg.read_delivery_bytes(str(missing))
    assert "НЕ ПРОЧИТАН" in str(exc.value), (
        "отказ обязан отличать «в момент пина файла не было» от «байты "
        "подменили»: это две разные причины и два разных следующих шага")


def test_readable_at_pin_time_is_not_recorded_as_unreadable(ptg, repo):
    """Обратная сторона E: читаемый путь в корзину нечитаемых не попадает."""
    f = _write(repo, "pkg/here.py", "here\n")
    pin = ptg.pin_delivery_bytes([str(f)])
    assert pin["unreadable"] == {}


# ═════════════════════════════════════════════════════════════════════════════
# E-bis. КЛЮЧ СЛЕПКА — ТОТ ЖЕ, ЧТО У `resolve_files`
#
# Дыра покрытия, найденная мутацией №19 цикла #890: батарея передавала ТОЛЬКО
# абсолютные пути, а для них `Path(x).absolute()` и `PROJECT_ROOT / x` дают одну
# строку — то есть неверная нормализация была НЕОТЛИЧИМА от верной. Расходятся
# они на ОТНОСИТЕЛЬНОМ аргументе при `cwd` ≠ `PROJECT_ROOT`, и тогда пин лёг бы
# на один ключ, а читатель спросил бы другой: сторож тихо перестал бы
# существовать, а на верном дереве печатал бы ЛОЖНЫЙ отказ — то есть учил бы
# ставить `--allow-bytes-drift` привычкой.
#
# Контракт формулируется НЕ пересказом правила, а СВЕРКОЙ С `resolve_files`:
# это и есть та функция, чьи ключи читатель потом спрашивает.
# ═════════════════════════════════════════════════════════════════════════════
def test_pin_key_matches_resolve_files_for_a_relative_argument(
        ptg, repo, monkeypatch, tmp_path):
    """Относительный аргумент при `cwd` ≠ `PROJECT_ROOT` — обе стороны согласны."""
    monkeypatch.setattr(ptg, "PROJECT_ROOT", repo)
    _write(repo, "pkg/rel.py", "rel\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)          # cwd намеренно НЕ корень репозитория

    pin = ptg.pin_delivery_bytes(["pkg/rel.py"])
    resolved = [str(ap) for _, ap in ptg.resolve_files(["pkg/rel.py"])]

    assert sorted(pin["digests"]) == sorted(resolved), (
        "ключ слепка разошёлся с путём, который потом спросит читатель: пин "
        f"по {sorted(pin['digests'])}, чтение по {sorted(resolved)} — сторож "
        f"перестал бы существовать молча")
    assert pin["unreadable"] == {}, (
        "файл существует относительно PROJECT_ROOT — «не прочитан» здесь "
        "означал бы, что пин смотрит не туда")


def test_a_relative_argument_is_actually_read_through_the_door(
        ptg, repo, monkeypatch, tmp_path):
    """Обратная сторона: по тому же ключу читатель проходит без отказа.

    Без этой половины предыдущий тест был бы зелен и на нормализации, которая
    согласована сама с собой, но не с диском.
    """
    monkeypatch.setattr(ptg, "PROJECT_ROOT", repo)
    _write(repo, "pkg/rel.py", "rel\n")
    elsewhere = tmp_path / "elsewhere2"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    ptg.pin_delivery_bytes(["pkg/rel.py"])
    _, abs_path = ptg.resolve_files(["pkg/rel.py"])[0]
    assert ptg.read_delivery_bytes(abs_path) == b"rel\n"
    assert "сверен" in ptg.delivery_pin_summary()


# ═════════════════════════════════════════════════════════════════════════════
# F. ОБХОД ОБЪЯВЛЕН И НАЗВАН — он не делает расхождение невидимым
# ═════════════════════════════════════════════════════════════════════════════
def test_declared_bypass_delivers_but_names_the_divergence(wired, repo, capsys):
    ptg, gh = wired
    f = _write(repo, "pkg/z.py", "z = 1\n")
    ptg.pin_delivery_bytes([str(f)], allow_drift=True)
    f.write_text("z = 2\n", encoding="utf-8")

    res = ptg.batch_push("pat", [str(f)], "msg", "o/r", "main")

    assert res["ok"] and len(gh.commits) == 1, "обход объявлен ⇒ доставка идёт"
    assert "pkg/z.py" in capsys.readouterr().out, (
        "обход обязан НАЗВАТЬ файл: молчаливый обход и есть прежний дефект")
    assert "РАСХОЖДЕНИЙ" in ptg.delivery_pin_summary()


def test_without_the_bypass_the_same_scene_refuses(wired, repo):
    """Обратная сторона F: согласие — вход, а не умолчание."""
    ptg, _ = wired
    f = _write(repo, "pkg/z.py", "z = 1\n")
    ptg.pin_delivery_bytes([str(f)], allow_drift=False)
    f.write_text("z = 2\n", encoding="utf-8")
    with pytest.raises(ptg.DeliveryBytesDrifted):
        ptg.batch_push("pat", [str(f)], "msg", "o/r", "main")


# ═════════════════════════════════════════════════════════════════════════════
# G. ПЕРЕСЪЁМКА СЛЕПКА СТЁРЛА БЫ НАБЛЮДЕНИЕ
# ═════════════════════════════════════════════════════════════════════════════
def test_a_second_pin_does_not_overwrite_the_first(ptg, repo):
    """Пересъёмка сделала бы «подменили между двумя пинами» невидимой."""
    f = _write(repo, "pkg/w.py", "w = 1\n")
    first = ptg.pin_delivery_bytes([str(f)])["digests"][str(f)]

    f.write_text("w = 2\n", encoding="utf-8")
    second = ptg.pin_delivery_bytes([str(f)])["digests"][str(f)]

    assert second == first, "второй пин не имеет права переснять слепок"
    with pytest.raises(ptg.DeliveryBytesDrifted):
        ptg.read_delivery_bytes(str(f))


# ═════════════════════════════════════════════════════════════════════════════
# H. ПРОВОДКА — ЗАМКНУТЫЙ ПЕРЕЧЕНЬ ЧТЕНИЙ (AST, не подстрока)
#
# Проверка «в файле есть имя `read_delivery_bytes`» была бы украшением: новое
# пятое чтение байтов, добавленное мимо двери, оставило бы её зелёной. Поэтому
# меряется ФОРМА ВЫЗОВА, и перечень читателей ЗАМКНУТ.
# ═════════════════════════════════════════════════════════════════════════════

#: Функции пушера, которые читают байты, предназначенные к отправке.
BYTE_READERS = ("push_file", "create_blob", "split_unchanged", "build_entries")

#: Единственная дверь к этим байтам.
BYTES_DOOR = "read_delivery_bytes"


def _functions(source: str) -> dict:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise Unmeasured(f"НЕ ИЗМЕРЕНО: пушер не разобран ({exc})") from exc
    return {n.name: n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def raw_byte_reads(source: str, names=BYTE_READERS) -> dict:
    """`имя функции → число СЫРЫХ чтений байтов` (мимо двери), по AST.

    Сырое чтение — любой вызов атрибута `.read_bytes(...)`. Дверь байты читает
    сама и внутрь перечня не входит: иначе мера оправдала бы себя.
    """
    funcs = _functions(source)
    missing = [n for n in names if n not in funcs]
    if missing:
        raise Unmeasured(
            f"НЕ ИЗМЕРЕНО: функций {missing} в пушере нет — перечень читателей "
            f"байтов устарел, и мерить замкнутость нечем")
    out = {}
    for name in names:
        out[name] = sum(
            1 for c in ast.walk(funcs[name])
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
            and c.func.attr == "read_bytes")
    return out


def calls_in(source: str, func_name: str) -> list:
    """Имена функций, ВЫЗЫВАЕМЫХ внутри `func_name`, в порядке появления."""
    funcs = _functions(source)
    if func_name not in funcs:
        raise Unmeasured(f"НЕ ИЗМЕРЕНО: функции `{func_name}` нет")
    return [c.func.id for c in ast.walk(funcs[func_name])
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)]


def test_no_reader_of_delivery_bytes_bypasses_the_door():
    """Ни одно из четырёх чтений не идёт мимо `read_delivery_bytes`."""
    counts = raw_byte_reads(PUSHER.read_text(encoding="utf-8"))
    offenders = {k: v for k, v in counts.items() if v}
    assert not offenders, (
        f"сырое чтение отправляемых байтов мимо двери `{BYTES_DOOR}`: "
        f"{offenders}. Именно так до ADR-774 один путь читался дважды и "
        f"уезжало содержимое ДРУГОГО чтения")
    for name in BYTE_READERS:
        assert BYTES_DOOR in calls_in(PUSHER.read_text(encoding="utf-8"), name), (
            f"`{name}` не зовёт `{BYTES_DOOR}` — байты он берёт как-то иначе, "
            f"и слепок до них не доходит")


def test_the_wiring_measure_goes_red_on_a_bypass():
    """Отрицательный контроль H: мера обязана УМЕТЬ покраснеть.

    Проверка, никогда не видевшая настоящей поломки, — украшение
    (`.claude/rules/deployment.md`). Здесь поломка внесена дословно: чтение
    возвращается к прежней форме.
    """
    source = PUSHER.read_text(encoding="utf-8").replace(
        "        local_sha = git_blob_sha(read_delivery_bytes(abs_path))",
        "        local_sha = git_blob_sha(Path(abs_path).read_bytes())", 1)
    assert raw_byte_reads(source)["split_unchanged"] == 1, (
        "мера не увидела возвращённое сырое чтение — значит она ничего не мерит")


def test_both_delivery_doors_pin_before_any_gate():
    """Слепок снимается ПЕРВЫМ. Снятый после гейта оставил бы ему своё окно."""
    for label, path in (("push_to_github.py", PUSHER),
                        ("push_to_github_batch.py", BATCH_CLI)):
        calls = calls_in(path.read_text(encoding="utf-8"), "main")
        assert "pin_delivery_bytes" in calls, (
            f"{label}: `main()` не ЗОВЁТ `pin_delivery_bytes` — дверь без "
            f"слепка доставляет то, что первая дверь отклоняет (урок номеров "
            f"ADR: 26.08 через вторую дверь уехал второй ADR-145)")
        assert "enforce_delivery_toolchain" in calls, (
            f"{label}: перечень гейтов изменился — порядок мерить не от чего")
        assert calls.index("pin_delivery_bytes") < calls.index(
            "enforce_delivery_toolchain"), (
            f"{label}: слепок снимается ПОСЛЕ первого гейта — у этого гейта "
            f"остаётся своё окно, то есть предмет ADR-774 на шаг короче")


def test_order_measure_goes_red_when_the_pin_moves_after_a_gate():
    """Отрицательный контроль порядка: мера видит перестановку."""
    source = (
        "def main():\n"
        "    enforce_delivery_toolchain(all_files)\n"
        "    pin_delivery_bytes(all_files)\n")
    calls = calls_in(source, "main")
    assert calls.index("pin_delivery_bytes") > calls.index(
        "enforce_delivery_toolchain"), "мера порядка не различает перестановку"


def test_the_batch_door_has_no_second_implementation():
    """У второй двери нет СВОЕЙ реализации слепка — только ре-экспорт.

    Мерить это сравнением с модулем, загруженным тестом, НЕЛЬЗЯ: batch-CLI сам
    грузит каноническую копию по пути, поэтому у теста и у CLI это РАЗНЫЕ
    объекты модуля по построению — и такое сравнение краснело бы на верном
    коде. Предмет здесь другой и он измеряется у самого CLI: внутри одного
    процесса его имена обязаны БЫТЬ объектами его собственного `_root_push`, а
    своего определения у него не должно быть ни одного.
    """
    cli = _load("_pin_cli_identity", "push_to_github_batch.py")
    try:
        for name in ("pin_delivery_bytes", "read_delivery_bytes",
                     "delivery_pin_summary", "reset_delivery_pin",
                     "DeliveryBytesDrifted"):
            assert getattr(cli, name) is getattr(cli._root_push, name), (
                f"`{name}` у batch-CLI — НЕ объект канонической копии: "
                f"вторая реализация означала бы, что одна дверь сверяет, а "
                f"вторая молчит (урок номеров ADR: 26.08 через вторую дверь "
                f"уехал второй ADR-145)")
        assert cli.BYTES_DRIFT_EXIT == cli._root_push.BYTES_DRIFT_EXIT

        own = _functions(BATCH_CLI.read_text(encoding="utf-8"))
        for name in ("pin_delivery_bytes", "read_delivery_bytes"):
            assert name not in own, (
                f"batch-CLI определяет СВОЙ `{name}` — два store, и слепок "
                f"одной двери не виден читателю байтов другой")
        assert "_DELIVERY_PIN" not in BATCH_CLI.read_text(encoding="utf-8"), (
            "batch-CLI объявляет свой store — пин снимался бы в один словарь, "
            "а сверялся бы по другому")
    finally:
        cli._root_push.reset_delivery_pin()


def test_unparsable_source_is_the_third_outcome_not_a_pass():
    """Не разобрали ⇒ `Unmeasured` с причиной, а не зелёный вердикт."""
    with pytest.raises(Unmeasured) as exc:
        raw_byte_reads("def broken(:\n")
    assert "НЕ ИЗМЕРЕНО" in str(exc.value)


def test_a_vanished_reader_is_the_third_outcome_not_a_pass():
    """Исчезнувший читатель ⇒ `Unmeasured`: перечень устарел, а не «чисто»."""
    with pytest.raises(Unmeasured) as exc:
        raw_byte_reads("def other():\n    pass\n", names=("split_unchanged",))
    assert "устарел" in str(exc.value)


def test_refusal_carries_its_own_exit_code():
    """Свой код возврата: общий `1` отправил бы читателя смотреть remote."""
    root = _load("_pin_exit_code", "push_to_github.py")
    try:
        taken = {root.BYTES_DRIFT_EXIT, root.ADR_INTERLOCK_EXIT,
                 root.OWNER_CHOICE_INTERLOCK_EXIT, root.CHANGE_EVIDENCE_EXIT,
                 root.MUTATION_WINDOW_EXIT}
        assert len(taken) == 5, (
            "код слепка совпал с кодом соседнего интерлока — различить отказы "
            "станет нечем")
        assert root.BYTES_DRIFT_EXIT not in (0, 1, 2, 3, 4, 5, 6)
    finally:
        root.reset_delivery_pin()
