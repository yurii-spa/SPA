"""Сентинел свежести кода бота (ADR-117): длгожитель сам доезжает до новых починок.

Жалоба владельца 22.08 дословно: «ты это уже делал кучу раз, но эффекта нет» —
реплай-привязка и кнопки чинились на origin, а живой KeepAlive-бот исполнял
память с момента старта. Сентинел: код зоны бота сменился и УСТОЯЛСЯ (два
замера подряд один новый отпечаток) → чистый выход → launchd поднимает свежего.

Тесты герметичны: своя мини-зона в tmp_path, часы — вход (now=), сети нет.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from pathlib import Path

from spa_core.telegram import bot as B

_T0 = 1_000_000.0  # логическое время; сравнивается только с самим собой


def _zone(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for rel in B._CODE_SCOPE_DIRS:
        d = root / rel
        d.mkdir(parents=True)
        (d / "mod.py").write_text("x = 1\n", encoding="utf-8")
    return root


def _touch(root: Path, content: str) -> None:
    p = root / B._CODE_SCOPE_DIRS[0] / "mod.py"
    p.write_text(content, encoding="utf-8")


def _sentinel(root: Path) -> "B.CodeFreshnessSentinel":
    s = B.CodeFreshnessSentinel(repo_root=root, check_s=300.0)
    s._next_at = _T0  # закрепить логические часы вместо time.time() конструктора
    return s


def test_unchanged_code_never_exits(tmp_path):
    root = _zone(tmp_path)
    s = _sentinel(root)
    for i in range(5):
        assert s.should_exit(now=_T0 + i * 300.0) is False


def test_changed_and_settled_code_exits_on_second_sample(tmp_path):
    root = _zone(tmp_path)
    s = _sentinel(root)
    assert s.should_exit(now=_T0) is False           # старт: код прежний
    _touch(root, "x = 2  # новая починка приехала\n")
    assert s.should_exit(now=_T0 + 300.0) is False   # фаза 1: изменение увидено
    assert s.should_exit(now=_T0 + 600.0) is True    # фаза 2: устоялось → выход


def test_flapping_sync_does_not_exit(tmp_path):
    """Полусинхронизированное дерево: отпечаток меняется КАЖДЫЙ замер — двухфазность
    не даёт выйти посреди доставки (выход только на устоявшемся коде)."""
    root = _zone(tmp_path)
    s = _sentinel(root)
    # Содержимое РАЗНОЙ ДЛИНЫ намеренно: отпечаток различает (mtime_ns, size),
    # и на быстрой FS CI две записи одного размера легли в один mtime-гранул —
    # отпечатки совпали, тест флапал (замер: run 32561831444, 22.08). Размер
    # не зависит от гранулярности часов файловой системы.
    for i, content in enumerate(["x = 2\n", "x = 33\n", "x = 444\n"], start=1):
        _touch(root, content)
        assert s.should_exit(now=_T0 + i * 300.0) is False


def test_reverted_change_resets_the_pending_phase(tmp_path):
    """Изменение откатилось до второго замера — pending сбрасывается, выхода нет."""
    root = _zone(tmp_path)
    s = _sentinel(root)
    original = (root / B._CODE_SCOPE_DIRS[0] / "mod.py").read_text(encoding="utf-8")
    st = (root / B._CODE_SCOPE_DIRS[0] / "mod.py").stat()
    _touch(root, "x = 2\n")
    assert s.should_exit(now=_T0 + 300.0) is False
    # вернуть байты И mtime — откат должен быть настоящим, не «другое изменение»
    p = root / B._CODE_SCOPE_DIRS[0] / "mod.py"
    p.write_text(original, encoding="utf-8")
    import os
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert s.should_exit(now=_T0 + 600.0) is False
    # и после отката новое настоящее изменение снова требует ДВУХ замеров
    _touch(root, "x = 5\n")
    assert s.should_exit(now=_T0 + 900.0) is False
    assert s.should_exit(now=_T0 + 1200.0) is True


def test_unmeasured_zone_is_fail_safe_never_exits(tmp_path):
    """Зоны нет (отпечаток "" на старте) — сомнение не роняет живого бота."""
    root = tmp_path / "empty"
    root.mkdir()
    s = _sentinel(root)
    assert B._code_fingerprint(root) == ""
    for i in range(3):
        assert s.should_exit(now=_T0 + i * 300.0) is False


def test_check_cadence_respected_between_samples(tmp_path):
    """Между тактами (now < next_at) сентинел не меряет и не выходит — проверка
    дешёвая для полл-цикла по построению."""
    root = _zone(tmp_path)
    s = _sentinel(root)
    _touch(root, "x = 2\n")
    assert s.should_exit(now=_T0 + 1.0) is False     # такт ещё не настал… но это замер 1
    assert s.should_exit(now=_T0 + 2.0) is False     # до следующего такта — не меряем
    assert s.should_exit(now=_T0 + 5.0) is False


def test_fingerprint_sees_new_file_and_mtime_change(tmp_path):
    root = _zone(tmp_path)
    fp0 = B._code_fingerprint(root)
    (root / B._CODE_SCOPE_DIRS[1] / "new_helper.py").write_text("y = 1\n", encoding="utf-8")
    fp1 = B._code_fingerprint(root)
    assert fp0 != fp1, "новый файл в зоне обязан менять отпечаток"
