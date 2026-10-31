# S2 — один запрос владельцу: установить доверенный корень и одну безвредную канарейку

**Зачем.** Всё, что S2 может доказать без root и без живой службы, доказано на стенде (`S2_STATUS.md`). Последний
критерий S2 — «разрешённая активация» (план `976862fb0`, «Пять поставок», S2), а с ним E5.5/E5.6 на живой системе —
требует двух действий, которые агент сделать не вправе: установка от root и запуск одной службы launchd.
Без этого S2 остаётся «доказан на стенде, живая активация НЕ ИЗМЕРЕНА». Денег, ставок, рисков, сайта это не касается.
Пароль в чат не нужен — команды набираются владельцем в его терминале.

## Что именно (точные изменения)

| # | Действие | Кто | Что меняется |
|---|---|---|---|
| 1 | Выбрать одобряемый SHA ветки `s2/release-materialise` (итоговый SHA отчёта ARB) и включить в `studio_release_agents.json` ровно ОДНУ роль канарейки — или использовать уже встроенную службу лаунчера `canary` (`deployment_acceptance`, только читает) — **рекомендация: встроенная `canary`, роль-манифест не нужен** | владелец решает | ничего |
| 2 | `sudo bash scripts/install_trusted_bootstrap.sh --launcher <abs>/spa_core/studio_os/release_launcher.py --launcher-sha256 <sha256> --repo <abs репо с объектом SHA> --approved <SHA> --runtime <собранный бандл 3.13> --runtime-digest <digest>` (сначала тем же набором с `--dry-run`) | владелец | `/Library/Application Support/StudioOS/{bin/release_launcher-<sha256>.py, releases/<SHA>/, approved_release.json, runtime.json (+trusted_repo), toolchains/<rid>/}` — всё root:wheel; существующий каталог релиза не удаляется (T08) |
| 3 | Создать `~/Library/LaunchAgents/com.spa.release_canary.plist`: `ProgramArguments = /usr/bin/python3 -I "/Library/Application Support/StudioOS/bin/release_launcher-<sha256>.py" canary`, без `KeepAlive`, `RunAtLoad=true`, логи `/tmp/spa_release_canary.{out,err}`; `launchctl bootstrap gui/$UID <plist>` | владелец | один новый plist; существующие plist флота НЕ меняются |

## Предварительные проверки (агент, до шага 2)
- `--dry-run` установщика печатает план без ошибок; `--verify-runtime` бандла — OK.
- `python3 -m spa_core.monitoring.deployment_acceptance` до — записать код возврата.
- SHA есть в локальных объектах `--repo`; `release_launcher.exec_root` на временном корне (`--self-test-root`) — `ACTIVATE_OK`.

## Проверка успеха
`launchctl list com.spa.release_canary` — код выхода 0; во время работы `release_state.active_processes`
называет процесс с одобренным SHA; лог `deployment_acceptance` — OK; `deployment_acceptance` флота после — тот же
код, что до; коды выхода остальных `com.spa.*` не изменились. Наблюдение ≥ 3 штатных запусков — E8.4 (поставка S5);
до этого статус «активировано, наблюдение не завершено».

## Условия остановки
Любой код ≠ 0 у канарейки; `FAIL_CLOSED` лаунчера; ACTIVE не подтверждён (`[]`); изменение кода выхода любого
другого агента; рост ошибок `agent_health`; любое сообщение установщика `FAIL-CLOSED`.

## Откат
`launchctl bootout gui/$UID/com.spa.release_canary`; plist переносится в архив (не удаляется). Корень StudioOS
остаётся — ни одна служба флота на него не указывает. Неверный релиз — новое одобрение предыдущего SHA установщиком.
Данные (`data/`) не затрагиваются ни установкой, ни откатом.

## Риски
- Установщик впервые запускается после правки T08 от root: его функции материализации проверены изолированно
  (`--self-test-root`), шаги с правами root:wheel и `sudo -u` — НЕ проверены вне root (NOT MEASURED до шага 2).
- `trusted_repo` указывает на репозиторий пользователя: удаление его git-объектов даст отказ
  `APPROVED_RELEASE_UNVERIFIABLE` (доступность, не целостность — лаунчер перепроверяет каждый объект по sha1).

## Что агент сделает после ответа
Проведёт предварительные проверки, по факту шагов 2–3 снимет замер (`active_processes`, коды выхода, логи),
запишет исход в `S2_STATUS.md` и ADR, при условии остановки — откат по пункту выше и сообщение владельцу сразу.
