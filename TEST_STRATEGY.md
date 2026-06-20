# SPA Test Strategy

## Два каталога — два назначения

| Каталог | Что тестирует | CI |
|---------|--------------|-----|
| `spa_core/tests/` | Unit-тесты каждого модуля (950+ файлов) | ✅ всегда |
| `tests/` (root) | Integration-тесты, E2E, cross-module | ✅ всегда |

Оба каталога запускаются в CI (`.github/workflows/ci.yml`).

## Правила

1. Unit-тест (тестирует один класс/функцию) → `spa_core/tests/test_<module>.py`
2. Integration-тест (2+ модуля, реальные файлы) → `tests/test_<feature>.py`
3. Запрещено: создавать тесты только в одном каталоге для обхода CI
4. `[skip ci]` в commit message — запрещено без явного согласования

## Запуск локально

```bash
# Все тесты
bash scripts/run_tests.sh

# Только unit
cd spa_core && python3 -m pytest tests/ -q

# Только integration
python3 -m pytest tests/ -q

# Smoke test (быстро)
python3 -c "from spa_core.base import BaseAnalytics; from spa_core.utils.kanban import increment_done; print('OK')"
```

## Минимальный порог качества

- Smoke test: PASS (import spa_core)
- Unit coverage: не падать ниже текущего числа тестов
- Integration: 0 errors during collection (все импорты чистые)
