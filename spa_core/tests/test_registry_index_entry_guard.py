"""Реестр решений `docs/decisions/INDEX.md` — общая тетрадь, и запись в ней СТРОКА.

Карточка `inbox-reestr-reshenii-index-md-obschaya-tetrad`, цикл #459.

ЧТО БЫЛО. У пушера две дополнительных защиты общей памяти, и реестр не был
объявлен НИ В ОДНОЙ:

* `guard_entry_loss` считает записью заголовок (`## …` / `> **…`). Запись реестра
  — строка таблицы `| ADR-NNN | … |`; для стража она не запись, значит её
  пропажа не пропажа.
* `SHARED_MEMORY_DOCS` (неизмеримая база = отказ, ADR-070 п.7) реестр не
  перечислял, поэтому по историческим путям доставки он уезжал целым файлом
  поверх чужих строк.

ЗАМЕР, породивший эту правку (цикл #459, по ВСЕЙ истории файла — 143 коммита,
142 перехода). Строки реестра исчезали в **семи** коммитах, каждый раз при
параллельных писателях, и каждый раз их возвращал СЛЕДУЮЩИЙ цикл через
час-полтора — ровно столько времени реестр врал:

    ADR-102/103/104  21.08 (дважды: 8caf3f04e, 6cb41115a)
    ADR-116          22.08 (740a6f5cb)
    ADR-117          22.08 (966d98ef4)
    ADR-118          22.08 (6a7f115e7)
    ADR-125          23.08 (c2e424dcd)
    ADR-145          26.08 (eb8828810)

(В текущем реестре ДВЕ строки ADR-145, но вторая помечена `(дубль)` и является
намеренным указателем на коллизию номера — к классу потерь она не относится.)

ЦЕНА, ИЗМЕРЕННАЯ ЧЕСТНО. На той же истории новый страж отказал бы ещё ДВАЖДЫ, и
оба раза — на НАМЕРЕННОМ действии автора: `07f15532b` (08.08) убрал вторую
строку того же ADR-074 (черновик рядом с принятым), `2fcec9669` (26.08)
перенумеровал ADR-144 → ADR-146, когда номер занял параллельный цикл. Это не
ложные срабатывания: строка реестра действительно исчезала. Это объявленная
цена fail-CLOSED — осознанное сокращение проходит через `--allow-overwrite`,
как и у `STATE.md`. Итог замера: 7 аварий закрыто, 2 намеренных действия
требуют явного флага.

ПОЧЕМУ ТОЖДЕСТВО ЗАПИСИ — НОМЕР, А НЕ ЯЧЕЙКА ЦЕЛИКОМ. `07f15532b` заодно
показал границу: в первой ячейке живёт не только номер (`| ADR-074 (проект) |`),
и статус записи меняется штатно (черновик → принято). Если считать тождеством
текст ячейки, страж краснел бы на КАЖДОЕ такое превращение — то есть на штатной
работе. Поэтому ключ — `ADR-NNN` (в т.ч. `ADR-YL-011`, `ADR-OWN-2026-07`,
`ADR-TEST`), а описание записи правится свободно.

ГРАНИЦА, которую эти тесты стерегут В ОБЕ СТОРОНЫ. Расширение — РОВНО один файл:
остальные документы (включая соседей по `docs/decisions/`) судятся как прежде, и
строка таблицы в них записью не становится. Страж, начавший краснеть на чужой
работе, будет отключён — и защита реестра уйдёт вместе с ним.

Тесты герметичны: сети нет, GitHub подменён детерминированным фейком,
литеральных дат в фикстурах нет (`.claude/rules/deployment.md`).

Запуск: python3 -m pytest spa_core/tests/test_registry_index_entry_guard.py -v
"""
import base64
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

INDEX = "docs/decisions/INDEX.md"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def ptg():
    return _load("_test_registry_ptg", "push_to_github.py")


# ── фикстуры реестра (форма — живая, номера — из замера выше) ────────────────

def registry(*rows: str) -> str:
    head = ("# Реестр решений (ADR)\n\n"
            "| № | Решение | Статус | Файл |\n|---|---|---|---|\n")
    tail = ("\n## Соглашения\n\n"
            "- Нумерация: `ADR-NNN` либо `ADR-YL-NNN`, `ADR-OWN-YYYY-MM`.\n")
    return head + "".join(rows) + tail


def row(adr: str, text: str = "решение") -> str:
    return f"| {adr} | {text} | Accepted | [{adr}]({adr}-slug.md) |\n"


#: Снимок remote в форме аварии 21.08: три записи, которые следующий пуш стёр.
REMOTE = registry(row("ADR-104"), row("ADR-103"), row("ADR-102"), row("ADR-101"))


# ═════════════════════════════════════════════════════════════════════════════
# 1. САМ ДЕФЕКТ: пропажа строки реестра. Каждый тест краснеет на пушере ДО правки.
# ═════════════════════════════════════════════════════════════════════════════

def test_lost_registry_rows_are_refused(ptg):
    """Авария 21.08 (8caf3f04e/6cb41115a): пуш без ADR-102/103/104 — отказ."""
    ours = registry(row("ADR-105"), row("ADR-101"))

    with pytest.raises(ptg.EntryLossRefused) as e:
        ptg.guard_entry_loss(INDEX, REMOTE.encode(), ours.encode(), remote_sha="deadbeef")

    msg = str(e.value)
    for adr in ("ADR-102", "ADR-103", "ADR-104"):
        assert adr in msg, f"{adr} обязан быть НАЗВАН в отказе, а не сосчитан"
    assert "ADR-101" not in msg, "уцелевшая запись в списке потерь не место"


@pytest.mark.parametrize("adr", ["ADR-116", "ADR-117", "ADR-118", "ADR-125", "ADR-145"])
def test_each_measured_single_row_loss_is_refused(ptg, adr):
    """Одиночные аварии 22–26.08: пропажа ОДНОЙ строки — тоже отказ."""
    remote = registry(row(adr), row("ADR-101"))
    ours = registry(row("ADR-101"))

    with pytest.raises(ptg.EntryLossRefused) as e:
        ptg.guard_entry_loss(INDEX, remote.encode(), ours.encode(), remote_sha="deadbeef")
    assert adr in str(e.value)


def test_duplicate_id_counts_with_multiplicity(ptg):
    """Класс `07f15532b`: две строки одного номера, снята одна — это потеря.

    Намеренная чистка дубля проходит через `--allow-overwrite` — цена fail-CLOSED,
    названная в шапке файла. Живой пример кратности 2 в реестре есть (`ADR-145` и
    `ADR-145 (дубль)`), но он НАМЕРЕННЫЙ и снимать его никто не собирается.
    """
    remote = registry(row("ADR-145", "черновик"), row("ADR-145", "принято"))
    ours = registry(row("ADR-145", "принято"))

    with pytest.raises(ptg.EntryLossRefused):
        ptg.guard_entry_loss(INDEX, remote.encode(), ours.encode(), remote_sha="deadbeef")

    assert ptg.guard_entry_loss(INDEX, remote.encode(), ours.encode(),
                                remote_sha="deadbeef", allow_overwrite=True) == ""


def test_unmeasured_base_refuses_and_pushes_nothing(ptg, monkeypatch, tmp_path):
    """ADR-070 п.7 для реестра: базы нет ⇒ отказ, на remote не уезжает НИЧЕГО."""
    remote = _FakeRemote({INDEX: REMOTE})
    root = tmp_path / "plain"
    root.mkdir()
    _wire(ptg, monkeypatch, remote, root)
    _write(root, INDEX, registry(row("ADR-105")))

    res = ptg.push_file("pat", str(root / INDEX), "цикл", "o/r")

    assert res["ok"] is False and res.get("diverged") is True
    assert remote.puts == [], "при отказе не должно быть НИ ОДНОЙ записи на remote"
    assert remote.files[INDEX] == REMOTE.encode(), "содержимое remote тронуто"


# ═════════════════════════════════════════════════════════════════════════════
# 2. ОБРАТНАЯ СТОРОНА: штатная работа с реестром обязана проходить.
# ═════════════════════════════════════════════════════════════════════════════

def test_appending_a_row_passes(ptg):
    """Обычный цикл дописывает своё решение — отказа быть не может."""
    ours = registry(row("ADR-105"), row("ADR-104"), row("ADR-103"),
                    row("ADR-102"), row("ADR-101"))
    assert ptg.guard_entry_loss(INDEX, REMOTE.encode(), ours.encode(),
                                remote_sha="deadbeef") == ""


def test_editing_a_rows_description_passes(ptg):
    """Описание записи (вторая ячейка) правится свободно — номер на месте."""
    remote = registry(row("ADR-074", "**черновик** — ждёт владельца"))
    ours = registry(row("ADR-074", "✅ **Принят владельцем** — демоушен тиров"))
    assert ptg.guard_entry_loss(INDEX, remote.encode(), ours.encode(),
                                remote_sha="deadbeef") == ""


def test_status_marker_inside_the_first_cell_is_not_identity(ptg):
    """Форма `07f15532b`: `| ADR-074 (проект) |` → `| ADR-074 |` — не потеря.

    Положительный контроль к ВЫБОРУ КЛЮЧА, и он выбран по замеру: в первой
    ячейке реестра живёт не только номер, а статус записи меняется штатно.
    Мутация «тождество = ячейка целиком» красит именно этот тест — остальные
    она переживает, потому что у них первая ячейка состоит из одного номера.
    """
    remote = ("| ADR-074 (проект) | демоушен тиров | Draft | [ADR-074](x.md) |\n"
              "| ADR-073 | другое | Accepted | [ADR-073](y.md) |\n")
    ours = ("| ADR-074 | демоушен тиров | Draft | [ADR-074](x.md) |\n"
            "| ADR-073 | другое | Accepted | [ADR-073](y.md) |\n")

    assert ptg.guard_entry_loss(INDEX, remote.encode(), ours.encode(),
                                remote_sha="deadbeef") == ""


@pytest.mark.parametrize("adr", ["ADR-197", "ADR-YL-011", "ADR-OWN-2026-07", "ADR-TEST"])
def test_all_numbering_schemes_are_recognised_as_entries(ptg, adr):
    """Реестр знает четыре формы номера — страж обязан видеть каждую."""
    remote = registry(row(adr), row("ADR-101"))
    ours = registry(row("ADR-101"))
    with pytest.raises(ptg.EntryLossRefused) as e:
        ptg.guard_entry_loss(INDEX, remote.encode(), ours.encode(), remote_sha="deadbeef")
    assert adr in str(e.value)


def test_registry_is_declared_in_both_protections(ptg):
    assert ptg.is_append_only_doc(INDEX), "иначе проверка записей не включится"
    assert ptg.is_shared_memory_doc(INDEX), "иначе неизмеримая база пройдёт"


# ═════════════════════════════════════════════════════════════════════════════
# 3. ГРАНИЦА: расширение — РОВНО один файл, чужие документы судятся как прежде.
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("path", [
    "docs/decisions/ADR-101-slug.md",
    "docs/decisions/_TEMPLATE.md",
    "docs/MATURITY_REGISTER.md",
    "push_to_github.py",
])
def test_scope_did_not_widen_to_neighbours(ptg, path):
    """Соседи по каталогу решений общей тетрадью НЕ становятся."""
    assert not ptg.is_append_only_doc(path)
    assert not ptg.is_shared_memory_doc(path)


def test_table_row_is_not_an_entry_outside_the_registry(ptg):
    """Таблица в STATE.md остаётся таблицей: там запись — заголовок.

    Иначе расширение уехало бы молча на все общие тетради, и любая правка
    таблицы в `STATE.md` начала бы отказывать.
    """
    state = ("# STATE\n\n> **(цикл #150) — запись.**\n> тело\n\n"
             "| ADR-102 | строка снимка | Accepted | [ADR-102](x.md) |\n")
    without_row = "# STATE\n\n> **(цикл #150) — запись.**\n> тело\n"

    assert ptg.guard_entry_loss("docs/STATE.md", state.encode(),
                                without_row.encode(), remote_sha="deadbeef") == ""

    assert ptg.entry_pattern("docs/STATE.md") is ptg.ENTRY_HEADER_RE
    assert ptg.entry_pattern(INDEX) is ptg.REGISTRY_ROW_RE


def test_heading_entries_still_judged_by_heading(ptg):
    """Проводка не сломана: журнал по-прежнему теряет запись по заголовку."""
    remote = "# journal\n\n## Цикл #150\n\nтело 150\n\n## Цикл #149\n\nтело 149\n"
    ours = "# journal\n\n## Цикл #149\n\nтело 149\n"
    with pytest.raises(ptg.EntryLossRefused) as e:
        ptg.guard_entry_loss("docs/journal/2026-W32.md", remote.encode(),
                             ours.encode(), remote_sha="deadbeef")
    assert "Цикл #150" in str(e.value)


def test_default_pattern_unchanged_for_callers_that_pass_no_file(ptg):
    """Умолчание вызовов без файла — прежнее (совместимость проводки)."""
    blob = "## A\n\nтело\n\n| ADR-102 | x | y | z |\n".encode()
    assert ptg.entry_headers(blob) == [b"## A"]
    assert ptg.entry_headers(blob, ptg.REGISTRY_ROW_RE) == [b"ADR-102"]


# ── фейковый GitHub (независимый оракул, сети нет) ───────────────────────────

class _FakeRemote:
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
