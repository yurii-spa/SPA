"""Сторож класса S23: заявленный стратегией адаптер ОБЯЗАН импортироваться.

Корень инцидента S23 (owner-requirement 2026-07-23, карточка
agent-guard-no-silent-mock-in-tournament): стратегия заявляла «беру живой
Pendle», импортировала адаптер внутри ``try/except: pass``, адаптер был
УДАЛЁН (retired MP-354) → ImportError глотался молча → стратегия НАВСЕГДА
сидела на mock-числе 7%, и оно уходило в турнир как реальная оценка.

Рантайм-глотание не трогаем — оно осознанное (ADR-059: сбой сети не должен
валить стратегию, честный флаг ``*_live=False`` ведётся). Сторож бьёт по
КОРНЮ: мёртвая ССЫЛКА (модуля нет / символа нет) — это не рантайм-край,
а сломанная поставка, и она обязана краснить CI, а не тихо превращаться
в mock. Поэтому скан идёт ПО ИСХОДНИКУ (AST), где try/except невидим,
а не по рантайм-поведению.

LLM_FORBIDDEN · stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import importlib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STRATEGIES_DIR = _REPO_ROOT / "spa_core" / "strategies"
_ADAPTERS_PREFIX = "spa_core.adapters"


def scan_claimed_adapter_imports(strategies_dir: Path = _STRATEGIES_DIR):
    """(module, attr|None) -> [файлы-стратегии]. AST-скан, try/except прозрачен.

    attr=None — форма ``import spa_core.adapters.x``; иначе
    ``from spa_core.adapters.x import Y``.
    """
    seen: dict[tuple[str, str | None], list[str]] = {}
    for p in sorted(strategies_dir.glob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.ImportFrom) and node.module
                    and node.module.startswith(_ADAPTERS_PREFIX)):
                for a in node.names:
                    seen.setdefault((node.module, a.name), []).append(p.name)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith(_ADAPTERS_PREFIX):
                        seen.setdefault((a.name, None), []).append(p.name)
    return seen



def find_broken(seen):
    """Мёртвые связки из результата скана: [(модуль, файлы), ...].
    ЕДИНСТВЕННАЯ реализация проверки — и боевой тест, и положительный
    контроль зовут её же (дубль логики делал контроль украшением)."""
    broken = []
    for (mod, attr), files in sorted(seen.items()):
        try:
            m = importlib.import_module(mod)
        except Exception:  # noqa: BLE001
            broken.append((mod, files))
            continue
        if attr is not None and not hasattr(m, attr):
            broken.append((mod, files))
    return broken

def test_every_claimed_adapter_imports_and_has_the_symbol():
    """Мёртвая ссылка стратегия→адаптер = красный CI, не молчаливый mock."""
    seen = scan_claimed_adapter_imports()
    broken = [f"{mod} мёртв (нет модуля или символа) — заявлен в {', '.join(files)}"
              for mod, files in find_broken(seen)]
    assert not broken, (
        "Стратегия заявляет адаптер, которого больше нет — в рантайме это "
        "молчаливый mock в турнире (класс S23). Чинить ссылку или стратегию, "
        "НЕ этот тест:\n  " + "\n  ".join(broken))


def test_scanner_is_not_running_on_empty(tmp_path):
    """Якорь против fail-OPEN самого сторожа: опечатка в пути глушила бы его
    молча (пустой скан = «всё зелено»). Скан обязан видеть известную живую
    связку S23 и не быть карликом."""
    seen = scan_claimed_adapter_imports()
    assert ("spa_core.adapters.pendle_pt", "get_pendle_apy") in seen, (
        "скан не видит связку S23→pendle_pt — сторож ослеп (путь? форма импорта?)")
    assert len(seen) >= 10, f"скан видит лишь {len(seen)} связок — подозрительно пусто"
    # Несуществующий каталог не должен маскироваться под «нет нарушений»
    # тем же путём, каким проверяется настоящий: пустой результат тут честен,
    # но основной прогон закреплён якорем выше.
    assert scan_claimed_adapter_imports(tmp_path / "nope") == {}


def test_import_inside_try_except_is_still_seen(tmp_path):
    """Суть сторожа: try/except прячет ImportError в рантайме — скан по AST
    обязан видеть импорт СКВОЗЬ try. Иначе сторож не ловит ровно тот случай,
    ради которого построен."""
    d = tmp_path / "strategies"
    d.mkdir()
    (d / "s99_fake.py").write_text(
        "try:\n"
        "    from spa_core.adapters.retired_ghost import GhostAdapter\n"
        "except Exception:\n"
        "    pass\n",
        encoding="utf-8")
    seen = scan_claimed_adapter_imports(d)
    assert ("spa_core.adapters.retired_ghost", "GhostAdapter") in seen
    assert seen[("spa_core.adapters.retired_ghost", "GhostAdapter")] == ["s99_fake.py"]


def test_a_dead_reference_is_reported_with_its_strategy(tmp_path):
    """Положительный контроль всей цепочки: подложная стратегия с импортом
    несуществующего адаптера доводит ОСНОВНУЮ проверку до падения, и отчёт
    называет и модуль, и файл стратегии."""
    d = tmp_path / "strategies"
    d.mkdir()
    (d / "s98_dead.py").write_text(
        "from spa_core.adapters.retired_mp354_pendle import PendlePtAdapter\n",
        encoding="utf-8")
    # Вторая форма смерти ссылки: модуль жив, СИМВОЛ исчез (переименовали API).
    (d / "s97_dead_symbol.py").write_text(
        "from spa_core.adapters.pendle_pt import no_such_symbol_anymore\n",
        encoding="utf-8")
    seen = scan_claimed_adapter_imports(d)
    assert sorted(find_broken(seen)) == [
        ("spa_core.adapters.pendle_pt", ["s97_dead_symbol.py"]),
        ("spa_core.adapters.retired_mp354_pendle", ["s98_dead.py"]),
    ]
