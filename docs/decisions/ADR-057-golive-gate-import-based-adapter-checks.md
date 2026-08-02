# ADR-057 — go-live gate verifies adapters by IMPORT, not just compile()

- **Статус:** Accepted (owner Variant Б, 2026-07-23)
- **Контекст-источник:** карта `owner-decision-geit-gotovnosti-zelenyi-po-adapteru-koto.md`.
- **Домен:** go-live readiness gate (advisory; не money-path, не RiskPolicy). Расширяет honesty-линию.

## Контекст

Гейт готовности к go-live (29 критериев) проверял критерии-адаптеры через `_check_file_syntax`
(`compile()` — только синтаксис). Замерено (цикл #39): `pendle_pt_adapter` был ЗЕЛЁНЫМ, хотя модуль
выведен из строя (MP-354, первая строка `raise ImportError`). `compile()` проходит на идеальном
синтаксисе → гейт благословлял НЕЗАГРУЖАЕМЫЙ модуль. Тот же приём применялся ко всем 4 критериям-адаптерам.
Мы собираемся опираться на этот гейт при санкции реального капитала — false-green здесь недопустим.

## Решение (Variant Б)

Новый helper `_check_adapter_importable(repo_root, filename)` реально ИМПОРТИРУЕТ модуль
(`importlib.import_module("spa_core.adapters.<name>")`) — существование файла + загружаемость. Все 4
критерия-адаптера переключены на него (`compound_v3`, `morpho_steakhouse`, `aave_arbitrum`, `pendle_pt`).

- Замер 2026-07-23: из 4 мёртв только `pendle_pt_adapter` (ImportError MP-354); остальные импортируются.
- `pendle_pt_adapter` честно КРАСНЕЕТ → критерий red. НЕ перецеливается молча на живой `pendle_pt`
  (MP-201) — канонический адаптер решается картой S23; red уйдёт после того решения.
- Число готовности на момент правки: **28/29** (единственный блокер — pendle; `apy_above_floor`
  ушёл в зелёный после редеплоя портфеля 30.07). Без правки `compile` пропустил бы pendle → ложные 29/29.

## Последствия

- (+) Гейт, которым санкционируется реальный капитал, больше не благословляет незагружаемый модуль;
  класс false-green закрыт для ВСЕХ критериев-адаптеров.
- (−) `import` тяжелее `compile` (загружает модуль) — приемлемо: адаптеры import-safe, сетевых
  side-effects при импорте нет.
- Тесты: `_full_checker` симулирует пост-S23 здоровый Pendle (READY-путь), + новый
  `test_dead_pendle_adapter_fails_import_check` пиннит реальное поведение (мёртвый pendle → red,
  «import failed»; здоровые не false-fail) — защита от отката к `compile()`. 64 passed.

## Связанные

Карта S23 (`owner-decision-strategiya-s23`, Variant A — после неё критерий Pendle перецеливается на
MP-201 и зеленеет), memory `fail-open-monitor-class`, ADR-056 (тот же honesty-класс в rules_watchdog).
