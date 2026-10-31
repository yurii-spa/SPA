# S2 — один запрос владельцу: обновить доверенный корень и запустить одну безвредную канарейку

**Статус:** подготовлено, НЕ выполнено. Агент root/sudo не использует и службы не переключает.
**Версия кода:** кандидат `s2/release-materialise`; одобряемый SHA ниже — итоговый SHA отчёта ARB.
Если ARB примет другой SHA, во всех командах ниже меняется только `APPROVED`, а sha256 лаунчера
пересчитывается шагом 0.

## Зачем
Последний обязательный критерий S2 — «до разрешённой активации» (план `976862fb0`, «Пять поставок», S2), а вместе
с ним E5.5/E5.6 на живой системе: «запущено из проверенного артефакта» и откат должны быть измерены на настоящей
службе launchd, а не на стенде. Агенту для этого не хватает двух действий: установки от root и запуска одной
службы. Наблюдение ≥ 3 штатных циклов (E8.4) — поставка S5, сюда не входит.
Денег, ставок, рисков, сайта и `data/` это не касается. Пароль в чат не нужен.

## Что уже стоит на машине (замер 31.10, только чтение)
- `/Library/Application Support/StudioOS/` установлен 28–30.09: лаунчер `bin/release_launcher-eec1ae58…f696.py`
  (прежняя версия — доверяет штампу), `approved_release.json` = `4cb68535…`, `runtime.json` без `trusted_repo`,
  runtime `toolchains/python-3.13-09eecca2da07a581`, релизы `4cb68535…`, `5b652577…`.
- **Ни один plist в `~/Library/LaunchAgents` на эту плоскость не указывает** — канарейка будет первой службой.

## Шаги (набирает владелец в своём терминале)

```bash
# 0. Переменные (не секреты). APPROVED — итоговый SHA отчёта ARB.
WT=~/Documents/SPA_worktrees/s2_release
APPROVED=<итоговый SHA из отчёта ARB, 40 символов>
LAUNCHER=$WT/spa_core/studio_os/release_launcher.py
LSHA=$(shasum -a 256 "$LAUNCHER" | cut -d' ' -f1)      # значение для итогового SHA приведено в отчёте ARB
git -C "$WT" rev-parse HEAD                              # должно совпасть с APPROVED

# 1. Собрать бандл runtime (без root; ничего не устанавливает)
bash $WT/scripts/build_trusted_runtime.sh --src ~/miniconda3/bin/python3.13 --stage /tmp/studioos-python313-runtime --print-digest
RDIGEST=<число RUNTIME_DIGEST из вывода>                # если = 09eecca2…, установленный runtime будет переиспользован

# 2. Сухой прогон установщика (без root) и изолированный прогон тех же функций на временном корне
bash $WT/scripts/install_trusted_bootstrap.sh --dry-run --launcher "$LAUNCHER" --launcher-sha256 "$LSHA" \
  --repo ~/Documents/SPA_Claude --approved "$APPROVED" --runtime /tmp/studioos-python313-runtime --runtime-digest "$RDIGEST"
mkdir -p /tmp/studioos-selftest && bash $WT/scripts/install_trusted_bootstrap.sh --self-test-root /tmp/studioos-selftest \
  --launcher "$LAUNCHER" --launcher-sha256 "$LSHA" --repo ~/Documents/SPA_Claude --approved "$APPROVED" \
  --self-test-app-python ~/miniconda3/bin/python3.13

# 3. Установка (root). Существующие релизы и прежний лаунчер не удаляются; перезаписываются
#    approved_release.json и runtime.json (их не читает ни одна служба).
sudo bash $WT/scripts/install_trusted_bootstrap.sh --launcher "$LAUNCHER" --launcher-sha256 "$LSHA" \
  --repo ~/Documents/SPA_Claude --approved "$APPROVED" --runtime /tmp/studioos-python313-runtime --runtime-digest "$RDIGEST"

# 4. Канарейка: ОДИН новый plist, существующие plist флота не меняются
cat > ~/Library/LaunchAgents/com.spa.release_canary.plist <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.spa.release_canary</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string><string>-I</string>
    <string>/Library/Application Support/StudioOS/bin/release_launcher-$LSHA.py</string><string>canary</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
  <key>StandardOutPath</key><string>/tmp/spa_release_canary.out</string>
  <key>StandardErrorPath</key><string>/tmp/spa_release_canary.err</string>
</dict></plist>
PL
plutil -lint ~/Library/LaunchAgents/com.spa.release_canary.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.spa.release_canary.plist
```

`SPA_DATA_DIR` в plist намеренно НЕ задаётся: `deployment_acceptance`, запущенная из неизменяемого релиза без
`SPA_DATA_DIR`, ничего не пишет (квитанция отказывает) — **ноль записей в `data/`**; проверки свежести живого
состояния она честно назовёт «не измерено». Минимальная затрагиваемая служба — эта одна.

## Проверки до выполнения (агент, по просьбе владельца — без root)
1. `python3 -m spa_core.monitoring.deployment_acceptance` в прод-дереве — записать код возврата (база «до»).
2. `launchctl list | grep com.spa` — снимок кодов выхода флота.
3. Шаг 2 выше — оба прогона без `FAIL-CLOSED`; на временном корне `release_launcher.exec_root` = `ACTIVATE_OK`.
4. Свободно на диске ≥ 20 ГБ (материализация SPA ≈ 230 МБ).

## Проверка успеха (агент, после шага 4)
- `/tmp/spa_release_canary.err` не содержит `trusted-launcher FAIL_CLOSED`; код выхода канарейки в
  `launchctl list com.spa.release_canary` записан (0 или 1 «предупреждение» `deployment_acceptance` без живого
  состояния — оба ожидаемы; 2/3/126 — отказ);
- во время работы `release_state.active_processes("/Library/Application Support/StudioOS/releases")` называет
  процесс с одобренным SHA (если процесс успел завершиться до замера — «не измерено», запуск повторяется
  `launchctl kickstart gui/$(id -u)/com.spa.release_canary`, а не объявляется успехом);
- `git -C ~/Documents/SPA_Claude status --short data/` до и после — одинаково; коды выхода остальных `com.spa.*` не
  изменились; `deployment_acceptance` прод-дерева после — тот же код, что до.

## Условия остановки (любое — сразу откат)
`FAIL-CLOSED` установщика · `trusted-launcher FAIL_CLOSED` канарейки · код 2/3/126 · ACTIVE не подтверждён после
повторного запуска · изменение `data/` · изменение кода выхода любого другого агента · рост ошибок `agent_health`.

## Откат
```bash
launchctl bootout gui/$(id -u)/com.spa.release_canary
mkdir -p ~/Library/LaunchAgents/_archive && mv ~/Library/LaunchAgents/com.spa.release_canary.plist ~/Library/LaunchAgents/_archive/
# прежнее одобрение (для лаунчера eec1ae58, который никем не запускается) — только если нужно вернуть файл как был:
# sudo sh -c 'printf "{\"approved_sha\": \"4cb68535329b2b09cb86d3a863aba6536e3f6c77\"}\n" > "/Library/Application Support/StudioOS/approved_release.json"'
```
Ничего не удаляется: релизы, прежний лаунчер и runtime остаются. Данные не затрагиваются.

## Риски
- Шаги установщика с правами root:wheel и `sudo -u` вне root НЕ проверены (проверены функции материализации и
  записи `runtime.json` на временном корне). Первая настоящая проверка — шаг 3; при `FAIL-CLOSED` ничего не
  публикуется.
- `trusted_repo = ~/Documents/SPA_Claude` — репозиторий пользователя: удаление его git-объектов даст отказ
  `APPROVED_RELEASE_UNVERIFIABLE` (доступность, не целостность: каждый объект перепроверяется по sha1).
- `deployment_acceptance` проверяет импорты ДОЧЕРНИМИ процессами интерпретатора флота без `-B` (замер 31.10 на
  релизе в каталоге пользователя: появилось 40 каталогов `__pycache__`, код выхода 1). В root-owned релизе
  (`root:wheel`, `a-w`, проверка прав установщика) запись невозможна; если бы она прошла, следующий запуск
  отказал бы `APPROVED_RELEASE_CORRUPT` — fail-closed, а не исполнение подменённого кода.
- Одобряемый SHA — ветка, не `main`: канарейка исполняет код кандидата. Это не доставка в `main` и не переключение
  флота.

## Что агент сделает после ответа
Проведёт проверки «до», после шагов 3–4 снимет замер успеха, запишет исход в `S2_STATUS.md` и ADR; при условии
остановки — откат по разделу выше и немедленное сообщение владельцу.
