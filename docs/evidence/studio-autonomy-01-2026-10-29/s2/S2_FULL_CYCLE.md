# S2 — сквозной цикл «задача → допуск → изменение → тестирование → проверка результата → сохранение состояния»

**Дата:** 31.10.2026 · **Ветка:** `s2/release-materialise` · **База:** `63b96a1e7` (ci-control `41120767445`).
**Режим исполнителя (E4.2):** «патч для разбора». Песочница НЕ заявляется. Production не активирован, реальный
капитал $0, `main` не тронут, Investment Engine не тронут. Активация — за действующими гейтами и решением ARB.

## 1. Цепочка коммитов (каждый критерий зафиксирован ДО кода)

| Задача | Пакет критериев (до кода) | Реализация | Критерии |
|---|---|---|---|
| 01 — материализация без удаления + состав по хешам | `7b02e8625` 30.10 13:37 | `162549e92` 13:44 | A1–A7 |
| S2-01 (ARB р.5) — эталон = доверенное дерево коммита | замечание ARB | `33ea5392b` 30.10 20:56 | 7 сценариев ARB |
| CI-SLO-01 (ARB р.6) — восстановление `sys.modules` | замечание ARB | `02884cabf` 31.10 07:18 | 4 теста |
| 02 — встроенный резолвер лаунчера по проверенному дереву | `11ba41e03` 31.10 18:45 | `3013ae306` 18:52 | B1–B8 |
| ADR-880 — решение ARB о S1 | — | `f982b7bb5` 18:54 | — |
| 03 — коллизия регистра путей | `2637757eb` 18:55 | `e044f42aa` 19:02 | C1–C7 |

Пакеты: `TASK_01_release_materialise.md`, `TASK_02_launcher_trusted_tree.md`, `TASK_03_case_collision.md` (рядом).

## 2. Звенья цикла на примере задачи 03

| Звено | Что было | Где доказательство |
|---|---|---|
| задача | ARB р.7 назвал её следующей предусмотренной задачей S2; находка задачи 01 на настоящем коммите | `TASK_03` § «Откуда задача» |
| допуск | границы (2 модуля + 1 тест-файл), режим «патч для разбора», запреты (не удалять документы), критерии C1–C7 — коммитом ДО кода | `2637757eb` |
| изменение | одно правило в двух резолверах, TRUST CLOSURE сохранена; git-blob каждого файла | `e044f42aa`, `TASK_03` § «Манифест» |
| тестирование | 8 новых тестов (5 красных на старом коде); соседние release-наборы; мутанты 8/8 в отдельном worktree; пакет сторожей; ci-control | `TASK_03` §C1–C7, раздел 4 ниже |
| проверка результата | замер на НАСТОЯЩЕМ коммите SPA и сквозная демонстрация на двух настоящих коммитах (раздел 3) | вывод ниже |
| сохранение состояния | коммиты на ветке в origin; пакеты + доказательства в git; решение в реестре ADR; 12 файлов `data/` вне коммитов (происхождение — `s2_data_provenance_2026-10-31/`) | этот файл |

## 3. Проверка результата на настоящих коммитах SPA (воспроизводимо)

Сцена: одноразовый «root plane» в scratchpad сессии (каталоги не удаляются), доверенный репозиторий — дерево
ветки, исполнения нет (`python=[]` — тестовый приёмник лаунчера). A = `02884cabf` (кандидат, прошедший CI
`41177105539`), B = `e044f42aa` (вершина ветки).

```python
# из корня дерева s2/release-materialise; SP — любой одноразовый каталог
import json, os, subprocess
from pathlib import Path
from spa_core.studio_os import release_activation as RA, release_launcher as LN
repo = Path(".").resolve(); A = "02884cabf3bc0fb75427f902d04db5216d37e940"
B = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
root = Path(SP) / "full_cycle_root"; (root / "releases").mkdir(parents=True)
(root / "runtime.json").write_text(json.dumps({"app_python": "/usr/bin/false", "trusted_repo": str(repo)}))
run = lambda: LN.main("agent:prober", root=root, python=[], active_path=root / "active.json")
run()                                                            # 0
(root / "approved_release.json").write_text(json.dumps({"approved_sha": A})); run()   # 1
[RA.materialise_release(s, root / "releases", repo) for s in (A, B)]                  # 2
RA.activation_plan(A, B, root / "releases", repo)                                     # 3
run()                                                                                 # 4
# 5: дописать байт в releases/<A>/spa_core/studio_os/release_launcher.py → RA/LN exec_root, run()
# 6: RA.materialise_release(A, …) повторно; 7: вернуть байты → RA.exec_root(A, …)
```

Вывод прогона 31.10:
```
A = 02884cabf3bc0fb75427f902d04db5216d37e940
B = e044f42aabbb1b23add497888843741b3753b091
root = /private/tmp/claude-501/-Users-yuriikulieshov-Documents-SPA-Claude/d2a57ddc-b78b-43e7-858c-1dc94074683b/scratchpad/full_cycle_root_1793469804
0. ничего не одобрено                                ('FAIL_CLOSED', 'DEPLOYMENT_APPROVAL_REQUIRED')
1. одобрен A, релиза нет                             ('FAIL_CLOSED', 'APPROVED_RELEASE_MISSING')
2. materialise 02884cabf OK
2. materialise e044f42aa OK
3. RA.activation_plan(approved=A, staged=B): EXEC_FROM_RELEASE 02884cabf
   LN.exec_root(A): ACTIVATE_OK | LN.exec_root(B): ACTIVATE_OK
4. лаунчер, одобрен A (роль-манифеста в SPA нет)     ('FAIL_CLOSED', 'AGENT_ROLE_NOT_ALLOWLISTED')
5. подмена файла артефакта A: RA APPROVED_RELEASE_CORRUPT | LN APPROVED_RELEASE_CORRUPT
   лаунчер после подмены                             ('FAIL_CLOSED', 'APPROVED_RELEASE_CORRUPT')
6. повторная материализация A (каталог сохраняется): RELEASE_DIR_CORRUPT
7. байты возвращены: RA ACTIVATE_OK
8. active.json записан: False
```

Что это доказывает: одобрен A при подготовленном B — исполнялся бы A (E5.4 на уровне резолвера); подмена одного
файла артефакта — отказ ОБОИХ резолверов до записи active; повреждённый каталог сохраняется (повторная
материализация его не перезаписывает, `RELEASE_DIR_CORRUPT`); возврат байтов возвращает `ACTIVATE_OK` (то есть
эталон — содержимое коммита, а не история каталога). Шаг 4: настоящий лаунчер на настоящем релизе SPA отказывает
`AGENT_ROLE_NOT_ALLOWLISTED` — в дереве SPA нет `studio_release_agents.json`, ни одна служба через лаунчер не
разрешена. Это верный отказ и одновременно блокер активации (раздел 5).

## 4. Тестирование и сравнение с базой

Локально (31.10, дерево ветки, `SPA_ENV=ci PYTHONHASHSEED=0 -p no:randomly`):
- release-наборы (задачи 01–03, bootstrap, shell, лаунчер, CI-SLO-01, acceptance release/launcher, recover runtime) —
  127 + 46 passed;
- пакет сторожей и храповиков (`test_*ratchet*`, `test_*guard*`, `test_architecture*`, `test_spaerror_complete`,
  `test_state_md_is_kept_current`) — 7 failed / 1783 passed. Все 7 имён входят в 8 падений, воспроизведённых на
  чистой базе `63b96a1e7` (отчёт ARB от 31.10); ни один файл S2 в их сообщениях не назван. Это долг базы, не зелень.

Обязательный ci-control вершины ветки и сравнение с базой `41120767445` по имени и краткой причине — в итоговом
отчёте ARB (прогон привязан к точному SHA, поэтому в этот файл, входящий в тот же SHA, не вписывается).

## 5. Чего этот цикл НЕ доказывает (пределы)

- **Активации не было.** Ни launchd, ни перезапусков, ни записи в прод-дерево. E5.5 (измерение реального запуска
  каждой службы) и E5.6 (откат) на живой системе не измерены.
- **Лаунчер не может запустить ни одну настоящую службу:** нет роль-манифеста `studio_release_agents.json` в дереве
  SPA. Его состав (какие службы переводятся на запуск из релиза) — решение об активации, а не инженерная правка.
- Проверка требует локальных git-объектов одобренного коммита (`trusted_repo` в root-owned `runtime.json`); запуск
  без Git отказывает `APPROVED_RELEASE_UNVERIFIABLE` (fail-CLOSED, так задумано).
- Root plane (`/Library/…` доверенный корень, владелец root) не установлен; установка — действие владельца.
- E4 (сменяемые исполнители, квоты, продолжение после потери сессии) в S2 не реализовывался: исполнитель —
  интерактивная сессия в режиме «патч для разбора».
- 68 падений базы CI — известный долг, не исправлялся и не скрывается; AST-таймаут не исправлен.
