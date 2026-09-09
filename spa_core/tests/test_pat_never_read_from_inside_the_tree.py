"""Секрет НЕ читается из рабочего дерева (инвариант #7, ADR-275).

Авария, ради которой это закреплено: 2026-08-30 `com.spa.dashboard` поднял `http.server`
на ВСЕХ интерфейсах в корне репозитория и отдавал листинг вместе с `.git/` и `.github_pat`
(ADR-187). Режим 600 не защищает — сервер работает от того же пользователя. Сервер починили,
но пока чтение секрета из дерева остаётся штатным путём, у файла есть причина там лежать.

Замер 2026-09-09: `.github_pat` (24 байта, 13.06) в корне прод-дерева жив; `~/.github_pat`
не существует. Единственным читателем внутридеревного пути был список в `push_to_github.py`.

**Мерить надо КОД, а не текст.** Первая редакция этого сторожа искала подстроку и краснела
на КОММЕНТАРИИ, который объясняет, что путь убран, — то есть отвечала на вопрос «упоминается
ли путь», а не «читается ли он». Ровно тот класс, против которого написаны ADR-270/272/274.
Поэтому здесь разбор синтаксиса: ищется выражение `PROJECT_ROOT / "<файл секрета>"`.
"""
from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SECRET_NAMES = (".github_pat", ".spa_pat")
_TREE_ROOTS = ("PROJECT_ROOT", "_ROOT", "REPO_ROOT", "ROOT")


def _in_tree_secret_reads(source: str) -> list[str]:
    """Выражения вида ``<корень дерева> / "<секрет>"`` — по AST, а не по тексту.

    Разобрать не вышло ⇒ третий исход: поднять, а не вернуть пустой список (иначе
    «не измерено» стало бы неотличимо от «чисто»).
    """
    tree = ast.parse(source)          # SyntaxError здесь — громкий отказ, и это правильно
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
            continue
        names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        consts = {c.value for c in ast.walk(node)
                  if isinstance(c, ast.Constant) and isinstance(c.value, str)}
        if names & set(_TREE_ROOTS) and any(
                any(s in c for s in _SECRET_NAMES) for c in consts):
            found.append(f"line {node.lineno}: {sorted(names)} / {sorted(consts)}")
    return found


def _pat_resolver_source() -> str:
    src = (_ROOT / "push_to_github.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and "pat" in node.name.lower():
            seg = ast.get_source_segment(src, node)
            if seg and ".github_pat" in seg:
                return seg
    raise AssertionError(
        "в push_to_github.py не нашлось функции, читающей PAT — проверка не состоялась, "
        "и это НЕ повод считать её пройденной (переименовали ⇒ починить сторожа)")


def test_the_pusher_never_reads_a_secret_from_the_repository_tree():
    got = _in_tree_secret_reads(_pat_resolver_source())
    assert got == [], (
        "путь к секрету внутри дерева вернулся в список источников PAT: именно этот файл "
        f"дашборд однажды раздал в локальную сеть (ADR-187). Найдено: {got}")


def test_the_guard_would_catch_the_removed_line_positive_control():
    """Контроль, что сторож не украшение: та самая убранная строка обязана краснеть."""
    bad = 'def get_pat():\n    for f in [PROJECT_ROOT / ".github_pat"]:\n        pass\n'
    assert _in_tree_secret_reads(bad), "сторож не видит собственный предмет"


def test_the_guard_ignores_a_comment_that_merely_mentions_the_path():
    """Обратный контроль: упоминание в комментарии — не чтение (дефект первой редакции)."""
    ok = ('def get_pat():\n'
          '    # `PROJECT_ROOT / ".github_pat"` из этого списка УБРАН\n'
          '    for f in [Path.home() / ".github_pat"]:\n        pass\n')
    assert _in_tree_secret_reads(ok) == []


def test_the_keychain_is_still_the_first_source():
    """Контроль обратного направления: порядок Keychain → окружение → файл не сломан."""
    seg = _pat_resolver_source()
    i_key = seg.find("find-generic-password")
    i_env = seg.find("os.environ.get")
    i_file = seg.find('Path.home() / ".github_pat"')
    assert -1 < i_key < i_env < i_file, (i_key, i_env, i_file)


def test_home_paths_are_still_accepted():
    """Правило про ДЕРЕВО, а не про файлы вообще: путь в домашнем каталоге остаётся."""
    seg = _pat_resolver_source()
    assert 'Path.home() / ".github_pat"' in seg and 'Path.home() / ".spa_pat"' in seg


def test_no_runtime_module_reads_a_secret_from_the_tree_root():
    """Тот же запрет для остального рантайма — тоже по AST, не по подстроке."""
    offenders: list[str] = []
    for base in ("spa_core", "scripts"):
        for f in (_ROOT / base).rglob("*.py"):
            if "archive" in f.parts or "tests" in f.parts:
                continue
            try:
                src = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if ".github_pat" not in src and ".spa_pat" not in src:
                continue
            try:
                hits = _in_tree_secret_reads(src)
            except SyntaxError as exc:
                offenders.append(f"{f.relative_to(_ROOT)}: НЕ РАЗОБРАН ({exc})")
                continue
            offenders += [f"{f.relative_to(_ROOT)}: {h}" for h in hits]
    assert offenders == [], offenders
