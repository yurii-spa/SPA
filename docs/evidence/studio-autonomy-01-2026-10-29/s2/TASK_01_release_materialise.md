# S2 · задача 01 — `materialise_release` без удаления и с проверкой состава (STUDIO-AUTONOMY-01, E5.3)

**Статус:** пакет зафиксирован ДО кода (этот коммит), реализация — следующим коммитом той же ветки.
**Режим исполнителя (E4.2):** «патч для разбора». Проверенной изоляции записи/сети/секретов у исполнителя нет —
техническая песочница НЕ заявляется; работа идёт в отдельном worktree `~/Documents/SPA_worktrees/s2_release`
от `origin/main` `63b96a1e73e518803a91b96ac7ded94598a9820a`, без прод-данных, без launchd, без сети, кроме git.
**Активация:** модуль не запускается ни launchd, ни циклом (импортёры: `release_state`, `release_launcher` (копия
встроена), два файла тестов). Активация = доставка кода через действующий гейт; перезапусков нет. Денег нет.

## Откуда задача (существующий backlog, а не новая)
- карточка `inbox-storozh-golyh-runtimeerror-snova-krasnyi` (02.10): голые `RuntimeError` в
  `spa_core/studio_os/release_activation.py:67,70` держат красным `tests/test_spaerror_complete.py::test_20_zero_bare_exceptions_in_spa_core`;
- START_HERE STUDIO-AUTONOMY-01 §1: «`materialise_release` вызывает rm — запускать нельзя» → E5.3 («без rm/prune/
  усечения; повреждённые и незавершённые копии сохраняются с отказом; уникальное резервирование; запрет подмены;
  `.release_sha` сам по себе не доказывает состав»).

## Границы (scope)
Меняются ТОЛЬКО: `spa_core/studio_os/release_activation.py`; новый `spa_core/tests/test_release_activation_materialise.py`;
этот пакет. `release_launcher.py` (встроенная копия), `release_state.py`, карточки трекера, прод-дерево — НЕ трогаются.
Карточку inbox в `in-progress` не перевожу: машинной пробы приёмки под этот предмет в реестре нет (правило
`.claude/rules/acceptance.md`); критерии ниже — тесты и сторож, исполняемые командой.

## Критерии приёмки (до работы; исполнитель их не правит)
Исходные числа на базе `63b96a1e7`: `bare_raises(spa_core)` = **16**, из них в `release_activation.py` — **2**;
`test_release_activation_shell.py` + `test_trusted_bootstrap.py` — **16 passed**.

| # | Критерий | Как проверить (команда) |
|---|---|---|
| A1 | существующие тесты release зелёные | `SPA_ENV=ci PYTHONHASHSEED=0 python3 -m pytest spa_core/tests/test_release_activation_shell.py spa_core/tests/test_trusted_bootstrap.py -q -p no:randomly` → 16 passed |
| A2 | в `release_activation.py` нет голых подъёмов; общее число падает 16 → 14 | `bare_raises` из `tests/test_spaerror_complete.py` |
| A3 | в модуле нет удаления: ни `rm`, ни `rmtree`/`remove`/`unlink`/`rmdir` | AST-тест в новом файле |
| A4 | повреждённый каталог релиза сохраняется и даёт отказ; незавершённый (резерв без штампа) — сохраняется и даёт отказ; существующий верный — не меняется ни байтом; объекта нет — отказ без каталога | тесты в новом файле |
| A5 | состав проверяется по хешам: подменённый файл релиза ⇒ `exec_root` = `APPROVED_RELEASE_CORRUPT` | тест в новом файле |
| A6 | два процесса материализуют один sha одновременно: ровно один создаёт, второй получает `OK` (уже готов) либо названный отказ, без подмены и без смешанного каталога | тест в новом файле |
| A7 | каждое звено краснит свой тест (мутации) | прогон мутантов, итог в разделе «Доказательства» |
