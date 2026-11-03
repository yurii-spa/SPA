# S2 — запрос владельцу: установить доверенный корень из проверенного пакета и измерить канарейку B → A

**Статус:** подготовлено и отрепетировано на пользовательском корне (см. «Репетиция»), НЕ выполнено. Агент root/sudo
не использует, службы не создаёт и не переключает. Пароль в чат не нужен — команды набирает владелец.

## Зачем
Последний обязательный критерий S2 — «разрешённая активация» (план `976862fb0`, «Пять поставок», S2) вместе с
E5.5/E5.6 на живой системе. Нужно измерить на настоящей службе launchd: запуск из проверенного артефакта B, возврат
к предыдущему проверенному A и восстановление изменённой конфигурации доверенного корня. Наблюдение ≥ 3 штатных
циклов — E8.4, поставка S5, сюда не входит. Денег, ставок, рисков, сайта и `data/` это не касается.

## Версии (основания допуска)
| | SHA | Основание |
|---|---|---|
| **Пакет установки** | `92b75ff85692955319efb77259da3da311d8dfed` (`BUNDLE`, проверенный кандидат; CI `41296474076`) | установщик, лаунчер, сборщик runtime и верификатор — из ЭТОГО коммита; их sha256 — в отчёте ARB и в `INSTALL_PIN.json` того же коммита |
| **Лаунчер** (и для A, и для B) | из пакета, sha256 `7e778f2b33494a601413f69d4d90e491fc7632d172ff916e4a0d39685b432aed` | состав по перепроверенному дереву, `-B -E -s`, байткод = лишний файл. Прежний `eec1ae58…` (доверял штампу) в проверке НЕ участвует |
| **A** — предыдущий проверенный релиз | `63b96a1e73e518803a91b96ac7ded94598a9820a` | база `origin/main`, полный ci-control `41120767445` (12/12, 68 известных падений базы); состав доказывает лаунчер при установке |
| **B** — кандидат | `92b75ff85692955319efb77259da3da311d8dfed` (= `BUNDLE`) | полный ci-control `41296474076`: 12/12, новых нарушений от кода S2 нет; состав доказывает лаунчер |

Ожидаемые sha256 файлов пакета (то же — в отчёте ARB):
| Файл | sha256 |
|---|---|
| `scripts/install_trusted_bootstrap.sh` | `1802ce4337bea3a105b0e6e9816f7d8b98f4bb05ebeacac5dcf760881351318f` |
| `scripts/build_trusted_runtime.sh` | `73a7ea352f126833eafeb17054e5f77f16d0f644830ac59ccb2ca30300694b6b` |
| `spa_core/studio_os/release_launcher.py` | `7e778f2b33494a601413f69d4d90e491fc7632d172ff916e4a0d39685b432aed` |
| `spa_core/studio_os/trusted_install_bundle.py` | `85c19934ac99b412a18d3e88123395f9cfe82b6da275113b8d274856ea74b889` |
| runtime digest (закреплён) | `09eecca2da07a58156dff27ee5e904620675e05ffd60e31c08a7866cd10390b2` |

## Что уже стоит на машине (замер 31.10–01.11, только чтение)
`/Library/Application Support/StudioOS/`: лаунчер `bin/release_launcher-eec1ae58…f696.py` (старый), одобрение
`4cb68535…`, `runtime.json` без `trusted_repo`, runtime `toolchains/python-3.13-09eecca2da07a581`, релизы
`4cb68535…`, `5b652577…`. **Ни один plist на эту плоскость не указывает.** Runtime, собранный 01.11 без root из
`~/miniconda3/bin/python3.13`, даёт закреплённый digest — установленный runtime будет переиспользован без изменений.

В zsh (оболочка macOS) переменная перед `:` или `^` пишется в фигурных скобках — `"${BUNDLE}:путь"`: без них zsh
разбирает `:s…` как модификатор параметра (найдено проверкой этих команд 01.11).

## Шаг 0 — без root
```bash
BUNDLE=92b75ff85692955319efb77259da3da311d8dfed   # он же B; проверенный код S2
git -C ~/Documents/SPA_Claude fetch origin s2/release-materialise   # только объекты и remote-ссылка; рабочее дерево и data/ не трогает
A=63b96a1e73e518803a91b96ac7ded94598a9820a
REPO=~/Documents/SPA_Claude
D=$(date +%Y%m%d)
STAGE=~/StudioOS_install_$D                           # не должен существовать
RTSTAGE=~/StudioOS_runtime_$D                         # не должен существовать
ROOT="/Library/Application Support/StudioOS"
RSTAGE="/Library/Application Support/StudioOS_install/${BUNDLE}"      # будет root-owned (шаг 1.0)
RSNAP="/Library/Application Support/StudioOS_install/snapshot_$D"     # будет root-owned (шаг 1.1)
git -C "$REPO" cat-file -e "${BUNDLE}^{commit}" && git -C "$REPO" cat-file -e "${A}^{commit}"
# 0.1 верификатор — из коммита BUNDLE, не из рабочего дерева; сверка системным shasum со значением отчёта
git --no-replace-objects -C "$REPO" show "${BUNDLE}:spa_core/studio_os/trusted_install_bundle.py" > /tmp/tib.py
shasum -a 256 /tmp/tib.py        # обязан = 85c19934ac99b412a18d3e88123395f9cfe82b6da275113b8d274856ea74b889
# 0.2 пакет: каждый файл = значению отчёта И пину коммита; иначе REFUSED и пакета нет
/usr/bin/python3 -I /tmp/tib.py stage --repo "$REPO" --sha "$BUNDLE" --stage "$STAGE" \
  --expect=scripts/install_trusted_bootstrap.sh=1802ce4337bea3a105b0e6e9816f7d8b98f4bb05ebeacac5dcf760881351318f \
  --expect=scripts/build_trusted_runtime.sh=73a7ea352f126833eafeb17054e5f77f16d0f644830ac59ccb2ca30300694b6b \
  --expect=spa_core/studio_os/release_launcher.py=7e778f2b33494a601413f69d4d90e491fc7632d172ff916e4a0d39685b432aed \
  --expect=spa_core/studio_os/trusted_install_bundle.py=85c19934ac99b412a18d3e88123395f9cfe82b6da275113b8d274856ea74b889
# 0.3 runtime (без root): digest ОБЯЗАН совпасть с закреплённым; иначе стоп
bash "$STAGE/scripts/build_trusted_runtime.sh" --src ~/miniconda3/bin/python3.13 --stage "$RTSTAGE" --print-digest
# 0.4 сухой прогон и изолированный прогон тех же функций установщика
RDIGEST=09eecca2da07a58156dff27ee5e904620675e05ffd60e31c08a7866cd10390b2
LSHA=7e778f2b33494a601413f69d4d90e491fc7632d172ff916e4a0d39685b432aed
bash "$STAGE/scripts/install_trusted_bootstrap.sh" --dry-run --launcher "$STAGE/spa_core/studio_os/release_launcher.py" --launcher-sha256 "$LSHA" --repo "$REPO" --approved "$BUNDLE" --runtime "$RTSTAGE" --runtime-digest "$RDIGEST"
mkdir -p /tmp/studioos-selftest && bash "$STAGE/scripts/install_trusted_bootstrap.sh" --self-test-root /tmp/studioos-selftest --launcher "$STAGE/spa_core/studio_os/release_launcher.py" --launcher-sha256 "$LSHA" --repo "$REPO" --approved "$BUNDLE" --self-test-app-python ~/miniconda3/bin/python3.13
# 0.5 база «до»
(cd "$REPO" && python3 -m spa_core.monitoring.deployment_acceptance; echo "rc=$?")
launchctl list | grep com.spa > ~/StudioOS_fleet_before_$D.txt
git -C "$REPO" status --short data/ | shasum -a 256 > ~/StudioOS_data_before_$D.txt
df -g / | tail -1                                                         # ≥ 20 ГБ свободно
```
Любой `REFUSED`, `FAIL-CLOSED`, несовпадение digest или хеша — стоп.

## Шаг 1 — root
**1.0 Пакет и runtime в root-owned каталог** (дальше `sudo` исполняет только его; пользователь его изменить не может):
```bash
sudo mkdir -p "$RSTAGE"
sudo ditto "$STAGE" "$RSTAGE/bundle" && sudo ditto "$RTSTAGE" "$RSTAGE/runtime"
sudo chown -R root:wheel "$RSTAGE" && sudo chmod -R a-w "$RSTAGE"
(cd "$RSTAGE/bundle" && printf '%s  %s\n' \
  1802ce4337bea3a105b0e6e9816f7d8b98f4bb05ebeacac5dcf760881351318f scripts/install_trusted_bootstrap.sh \
  73a7ea352f126833eafeb17054e5f77f16d0f644830ac59ccb2ca30300694b6b scripts/build_trusted_runtime.sh \
  7e778f2b33494a601413f69d4d90e491fc7632d172ff916e4a0d39685b432aed spa_core/studio_os/release_launcher.py \
  85c19934ac99b412a18d3e88123395f9cfe82b6da275113b8d274856ea74b889 spa_core/studio_os/trusted_install_bundle.py \
  | shasum -a 256 -c -)                                               # 4 × OK, иначе стоп
BD="$RSTAGE/bundle"; INST="$BD/scripts/install_trusted_bootstrap.sh"; TIB="$BD/spa_core/studio_os/trusted_install_bundle.py"
LAUNCHER="$BD/spa_core/studio_os/release_launcher.py"; RT="$RSTAGE/runtime"
```
**1.1 Снимок исходной конфигурации — root, в root-owned каталог; хеш ЗАПИСАТЬ вне снимка:**
```bash
sudo /usr/bin/python3 -I "$TIB" snapshot --root "$ROOT" --snapshot "$RSNAP"     # печатает SNAPSHOT_SHA256=…
SNAPSHA=<SNAPSHOT_SHA256 из вывода — записать отдельно (бумага / отчёт), он нужен для восстановления>
sudo /usr/bin/python3 -I "$TIB" verify --root "$ROOT" --snapshot "$RSNAP" --expect-snapshot-sha256 "$SNAPSHA"   # MATCH
```
**1.2 Установка A, затем B (только из `$RSTAGE`):**
```bash
sudo bash "$INST" --launcher "$LAUNCHER" --launcher-sha256 "$LSHA" --repo "$REPO" --approved "$A" --runtime "$RT" --runtime-digest "$RDIGEST"
sudo bash "$INST" --launcher "$LAUNCHER" --launcher-sha256 "$LSHA" --repo "$REPO" --approved "$BUNDLE" --runtime "$RT" --runtime-digest "$RDIGEST"
cat "$ROOT/approved_release.json"     # = BUNDLE (B); оба релиза доказаны установленным лаунчером, root:wheel, a-w
```
Установщик сверяет sha256 и источника, и установленной копии лаунчера. Он проверяет, что обычный пользователь не
может писать лаунчер, одобрение, runtime.json и релиз (на этом держится остаток R4: байткод в релиз не пишется), и
ничего не удаляет.

## Шаг 2 — одна канарейка (новый plist; существующие plist флота не меняются)
```bash
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
Служба одна — `canary` → `deployment_acceptance` (только чтение). `SPA_DATA_DIR` намеренно не задаётся: из
неизменяемого релиза она ничего не пишет (ожидаемый код 1 — «живое состояние не измерено»).

## Шаг 3 — измерения (агент, без root; замер — из дерева ветки S2, где есть `active_processes`)
```bash
MEASURE='from spa_core.studio_os import release_state as R; print(R.active_processes("/Library/Application Support/StudioOS/releases"))'
(cd ~/Documents/SPA_worktrees/s2_release && python3 -c "$MEASURE")     # пока работает канарейка: [{pid, sha=B}]
```
- **B:** замер называет процесс канарейки с SHA = B; в `/tmp/spa_release_canary.err` нет `trusted-launcher FAIL_CLOSED`;
  код в `launchctl list com.spa.release_canary` — 0 или 1. Не успели замерить — `launchctl kickstart gui/$(id -u)/com.spa.release_canary`
  и замер повторяется (успехом не объявляется).
- **Возврат к A (E5.6):** снова проверить пакет `(cd "$RSTAGE/bundle" && … | shasum -a 256 -c -)` (та же строка, что в 1.0), затем
  `sudo bash "$INST" … --approved "$A" …` (строка из 1.2): каталог A переиспользуется доказанным, переписывается только
  одобрение; `launchctl kickstart gui/$(id -u)/com.spa.release_canary`; замер называет процесс с SHA = A. Это доказательство
  запуска ПРЕДЫДУЩЕГО ПРОВЕРЕННОГО релиза тем же новым лаунчером.
- На каждом шаге: `git -C "$REPO" status --short data/ | shasum -a 256` = до; `launchctl list | grep com.spa` — коды
  остальных агентов не изменились.

## Условия остановки (любое — сразу (а), затем (б))
`REFUSED`/`FAIL-CLOSED` установщика · `shasum -c` не `OK` · `trusted-launcher FAIL_CLOSED` · код канарейки 2/3/126 ·
ACTIVE не подтверждён после повторного `kickstart` · изменение `data/` · изменение кода выхода любого другого
`com.spa.*` · рост ошибок `agent_health`.

## Восстановление
**(а) Аварийная остановка канарейки:**
```bash
launchctl bootout gui/$(id -u)/com.spa.release_canary
mkdir -p ~/Library/LaunchAgents/_archive && mv ~/Library/LaunchAgents/com.spa.release_canary.plist ~/Library/LaunchAgents/_archive/
(cd ~/Documents/SPA_worktrees/s2_release && python3 -c "$MEASURE")    # []
```
**(б) Восстановление конфигурации доверенного корня** — approved_release.json и runtime.json (содержимое, uid/gid,
режим) из root-owned снимка 1.1, только по записанному хешу:
```bash
sudo /usr/bin/python3 -I "$TIB" restore --root "$ROOT" --snapshot "$RSNAP" --expect-snapshot-sha256 "$SNAPSHA"
sudo /usr/bin/python3 -I "$TIB" verify  --root "$ROOT" --snapshot "$RSNAP" --expect-snapshot-sha256 "$SNAPSHA"
```
`restore` отказывает, если хеш снимка не совпал с записанным, если снимок не root-owned или доступен на запись не
только root, если копия — ссылка или владелец в снимке не root. После восстановления `verify` назовёт только
перечни `bin/` и `releases/`: новый лаунчер и релизы A/B остаются (ничего не удаляется), а после (а) ни одна служба
на них не указывает.

**(в) Доказательство запуска предыдущего проверенного релиза** — измерение «Возврат к A» шага 3 (новый лаунчер,
A = `63b96a1e7`). Восстановление (б) возвращает исходную конфигурацию, но доказательством безопасного отката не
является: прежний лаунчер `eec1ae58…` для этого не используется.

## Репетиция (выполнено агентом 01.11, без root) — на итоговом коде установки
`~/Documents/SPA_worktrees/arb_s2_evidence_2026-10-31/rehearsal_canary_AB_final/`:
- пакет из коммита `a069a4374` (4 хеша = пин); снимок копии настоящей конфигурации, хеш `1fc70b7f…`;
- A и B материализованы и доказаны, релизы `a-w`;
- канарейка B — pid 90696 в `releases/a069a4374`, код 1; возврат к A — pid 91700 в `releases/63b96a1e7`, код 1;
- `__pycache__` в релизах нет; восстановление по записанному хешу — файлы совпали; `data/` прод-дерева и настоящий
  корень не изменились.

Подмены: корень пользователя вместо root:wheel, `--self-test-root` вместо `sudo`, скрипт вместо launchd. Шаг 0
(0.1–0.2 и снимок/сверка настоящего корня — только чтение) выполнен 01.11 командами из этого файла.

## Риски и что остаётся НЕ ИЗМЕРЕННЫМ до этих шагов
- Шаги установщика под root (`chown root:wheel`, проверка прав `sudo -u`, сверка установленной копии лаунчера) и
  `restore` под root ни разу не исполнялись — первая проверка и есть шаг 1; при отказе ничего не публикуется.
- Запуск канарейки через launchd, её работа от обычного пользователя в gui-домене и попытка записи байткода в
  root-owned релиз (R4) — измеряются только шагами 2–3.
- `trusted_repo = ~/Documents/SPA_Claude` — репозиторий пользователя: удаление его объектов даёт отказ, а не подмену.
- B — коммит ветки, не `main`; это не доставка в `main` и не переключение флота.

## Что агент сделает после ответа
Проведёт шаг 0 (если поручено), после шагов 1–2 — измерения шага 3; при условии остановки — (а) и (б) и сразу
сообщение владельцу. Исход запишет в `S2_STATUS.md` и ADR.
