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
| **Пакет установки** | итоговый SHA отчёта ARB (`BUNDLE`) | установщик, лаунчер, сборщик runtime и верификатор берутся из ЭТОГО коммита; их sha256 — в отчёте ARB и в `INSTALL_PIN.json` того же коммита |
| **Лаунчер** (и для A, и для B) | из пакета, sha256 `7e778f2b33494a601413f69d4d90e491fc7632d172ff916e4a0d39685b432aed` | проверка состава по перепроверенному дереву, `-B -E -s`, байткод = лишний файл. Прежний лаунчер `eec1ae58…` (доверял штампу) в проверке НЕ участвует |
| **A** — предыдущий проверенный релиз | `63b96a1e73e518803a91b96ac7ded94598a9820a` | база `origin/main`, полный ci-control `41120767445` (12/12, 68 известных падений базы); состав доказывает лаунчер при установке |
| **B** — кандидат | итоговый SHA отчёта ARB (= `BUNDLE`) | полный ci-control итогового SHA (отчёт ARB); состав доказывает лаунчер |

## Что уже стоит на машине (замер 31.10–01.11, только чтение)
`/Library/Application Support/StudioOS/`: лаунчер `bin/release_launcher-eec1ae58…f696.py` (старый), одобрение
`4cb68535…`, `runtime.json` без `trusted_repo`, runtime `toolchains/python-3.13-09eecca2da07a581`, релизы
`4cb68535…`, `5b652577…`. **Ни один plist на эту плоскость не указывает.** Runtime, собранный 01.11 без root из
`~/miniconda3/bin/python3.13`, даёт digest `09eecca2da07a58156dff27ee5e904620675e05ffd60e31c08a7866cd10390b2` —
тот же, установленный runtime будет переиспользован без изменений.

## Шаг 0 — без root
В zsh (оболочка macOS) переменные перед `:` и `^` пишутся в фигурных скобках — `"${BUNDLE}:путь"`: без них
zsh разбирает `:s…` как модификатор параметра (найдено проверкой этих команд 01.11).
```bash
BUNDLE=<итоговый SHA из отчёта ARB, 40 hex>          # он же B
A=63b96a1e73e518803a91b96ac7ded94598a9820a
REPO=~/Documents/SPA_Claude
STAGE=~/StudioOS_install_$(date +%Y%m%d)              # не должен существовать
SNAP=~/StudioOS_config_before_$(date +%Y%m%d)         # не должен существовать
ROOT="/Library/Application Support/StudioOS"
git -C "$REPO" cat-file -e "${BUNDLE}^{commit}" && git -C "$REPO" cat-file -e "${A}^{commit}"
# 0.1 верификатор берётся из коммита BUNDLE, а не из рабочего дерева
git --no-replace-objects -C "$REPO" show "${BUNDLE}:spa_core/studio_os/trusted_install_bundle.py" > /tmp/tib.py
shasum -a 256 /tmp/tib.py        # обязан = d7ced956e2d358ac6ff9858544d33af25572b0416147cfc05f3a831bfd23e05a (отчёт ARB)
# 0.2 пакет: каждый файл сверяется со ЗНАЧЕНИЯМИ ОТЧЁТА и с пином коммита; при расхождении — REFUSED, пакета нет
/usr/bin/python3 -I /tmp/tib.py stage --repo "$REPO" --sha "$BUNDLE" --stage "$STAGE" \
  --expect=scripts/install_trusted_bootstrap.sh=1802ce4337bea3a105b0e6e9816f7d8b98f4bb05ebeacac5dcf760881351318f \
  --expect=scripts/build_trusted_runtime.sh=73a7ea352f126833eafeb17054e5f77f16d0f644830ac59ccb2ca30300694b6b \
  --expect=spa_core/studio_os/release_launcher.py=7e778f2b33494a601413f69d4d90e491fc7632d172ff916e4a0d39685b432aed \
  --expect=spa_core/studio_os/trusted_install_bundle.py=d7ced956e2d358ac6ff9858544d33af25572b0416147cfc05f3a831bfd23e05a
# 0.3 снимок исходной конфигурации: содержимое, sha256, uid/gid, режим, перечни bin/releases/toolchains
/usr/bin/python3 -I "$STAGE/spa_core/studio_os/trusted_install_bundle.py" snapshot --root "$ROOT" --snapshot "$SNAP"
/usr/bin/python3 -I "$STAGE/spa_core/studio_os/trusted_install_bundle.py" verify --root "$ROOT" --snapshot "$SNAP"   # MATCH
# 0.4 runtime: digest ОБЯЗАН совпасть с закреплённым; иначе стоп (новое значение не принимается)
bash "$STAGE/scripts/build_trusted_runtime.sh" --src ~/miniconda3/bin/python3.13 --stage /tmp/studioos-python313-runtime --print-digest
RDIGEST=09eecca2da07a58156dff27ee5e904620675e05ffd60e31c08a7866cd10390b2
LAUNCHER="$STAGE/spa_core/studio_os/release_launcher.py"
LSHA=7e778f2b33494a601413f69d4d90e491fc7632d172ff916e4a0d39685b432aed
# 0.5 сухой прогон и изолированный прогон тех же функций (без root)
bash "$STAGE/scripts/install_trusted_bootstrap.sh" --dry-run --launcher "$LAUNCHER" --launcher-sha256 "$LSHA" --repo "$REPO" --approved "$BUNDLE" --runtime /tmp/studioos-python313-runtime --runtime-digest "$RDIGEST"
mkdir -p /tmp/studioos-selftest && bash "$STAGE/scripts/install_trusted_bootstrap.sh" --self-test-root /tmp/studioos-selftest --launcher "$LAUNCHER" --launcher-sha256 "$LSHA" --repo "$REPO" --approved "$BUNDLE" --self-test-app-python ~/miniconda3/bin/python3.13
# 0.6 база «до»
python3 -m spa_core.monitoring.deployment_acceptance; echo "rc=$?"       # из прод-дерева, записать код
launchctl list | grep com.spa > ~/StudioOS_fleet_before.txt
git -C "$REPO" status --short data/ | shasum -a 256 > ~/StudioOS_data_before.txt
df -g / | tail -1                                                         # ≥ 20 ГБ свободно
```
Любой `REFUSED`, `FAIL-CLOSED`, несовпадение digest или хеша — стоп, дальше не идти.

## Шаг 1 — root: установка A, затем B (только из пакета `$STAGE`)
```bash
sudo bash "$STAGE/scripts/install_trusted_bootstrap.sh" --launcher "$LAUNCHER" --launcher-sha256 "$LSHA" --repo "$REPO" --approved "$A" --runtime /tmp/studioos-python313-runtime --runtime-digest "$RDIGEST"
sudo bash "$STAGE/scripts/install_trusted_bootstrap.sh" --launcher "$LAUNCHER" --launcher-sha256 "$LSHA" --repo "$REPO" --approved "$BUNDLE" --runtime /tmp/studioos-python313-runtime --runtime-digest "$RDIGEST"
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

## Шаг 3 — измерения (агент, без root)
- **B:** пока процесс работает, `python3 -c "from spa_core.studio_os import release_state as R; print(R.active_processes('$ROOT/releases'))"`
  называет процесс канарейки с SHA = B; в `/tmp/spa_release_canary.err` нет `trusted-launcher FAIL_CLOSED`; код в
  `launchctl list com.spa.release_canary` — 0 или 1. Не успели замерить — `launchctl kickstart gui/$(id -u)/com.spa.release_canary`
  и замер повторяется (успехом не объявляется).
- **Возврат к A (E5.6):** `sudo bash "$STAGE/scripts/install_trusted_bootstrap.sh" … --approved "$A" …` (та же строка, что в
  шаге 1): каталог A переиспользуется доказанным, переписывается только одобрение; затем
  `launchctl kickstart gui/$(id -u)/com.spa.release_canary`; замер называет процесс с SHA = A. Это доказательство
  запуска ПРЕДЫДУЩЕГО ПРОВЕРЕННОГО релиза тем же новым лаунчером.
- На каждом шаге: `git -C "$REPO" status --short data/ | shasum -a 256` = до; `launchctl list | grep com.spa` — коды
  остальных агентов не изменились.

## Условия остановки (любое — сразу (а), затем (б))
`REFUSED`/`FAIL-CLOSED` установщика · `trusted-launcher FAIL_CLOSED` · код канарейки 2/3/126 · ACTIVE не
подтверждён после повторного `kickstart` · изменение `data/` · изменение кода выхода любого другого `com.spa.*` ·
рост ошибок `agent_health`.

## Восстановление
**(а) Аварийная остановка канарейки:**
```bash
launchctl bootout gui/$(id -u)/com.spa.release_canary
mkdir -p ~/Library/LaunchAgents/_archive && mv ~/Library/LaunchAgents/com.spa.release_canary.plist ~/Library/LaunchAgents/_archive/
python3 -c "from spa_core.studio_os import release_state as R; print(R.active_processes('$ROOT/releases'))"   # []
```
**(б) Восстановление конфигурации доверенного корня** — approved_release.json и runtime.json (содержимое, владелец,
режим) из снимка шага 0.3; нужен root, т. к. файлы root:wheel:
```bash
sudo /usr/bin/python3 -I "$STAGE/spa_core/studio_os/trusted_install_bundle.py" restore --root "$ROOT" --snapshot "$SNAP"
/usr/bin/python3 -I "$STAGE/spa_core/studio_os/trusted_install_bundle.py" verify --root "$ROOT" --snapshot "$SNAP"
```
`restore` отказывает на подменённом снимке и сам перепроверяет файлы. `verify` после восстановления назовёт только
перечни `bin/` и `releases/`: новый лаунчер и релизы A/B остаются (ничего не удаляется), а после (а) ни одна служба
на них не указывает.

**(в) Доказательство запуска предыдущего проверенного релиза** — это измерение «Возврат к A» шага 3 (новый лаунчер,
A = `63b96a1e7`). Восстановление (б) возвращает исходную конфигурацию, но доказательством безопасного отката не
является: прежний лаунчер `eec1ae58…` для этого не используется.

## Репетиция (выполнено агентом 01.11, без root)
`~/Documents/SPA_worktrees/arb_s2_evidence_2026-10-31/rehearsal_canary_AB/`:
- пакет из коммита `5c4a9549b` (4 хеша = пин);
- снимок копии настоящей конфигурации; A и B материализованы и доказаны; релизы `a-w`;
- канарейка B — pid 70489 в `releases/5c4a9549b`, код 1; возврат к A — pid 71505 в `releases/63b96a1e7`, код 1;
- `__pycache__` в релизах нет; `restore` — файлы совпали; `data/` прод-дерева и настоящий корень не изменились.

Подмены: корень пользователя вместо root:wheel, `--self-test-root` вместо `sudo`, скрипт вместо launchd.

## Риски и что остаётся НЕ ИЗМЕРЕННЫМ до этих шагов
- Шаги установщика под root (`chown root:wheel`, проверка прав `sudo -u`, сверка установленной копии) ни разу не
  исполнялись — первая проверка и есть шаг 1; при отказе ничего не публикуется.
- Запуск канарейки через launchd, её работа от обычного пользователя в gui-домене и попытка записи байткода в
  root-owned релиз (R4) — измеряются только шагами 2–3.
- `trusted_repo = ~/Documents/SPA_Claude` — репозиторий пользователя: удаление его объектов даёт отказ, а не подмену.
- B — коммит ветки, не `main`; это не доставка в `main` и не переключение флота.

## Что агент сделает после ответа
Проведёт шаг 0 (если поручено), после шагов 1–2 — измерения шага 3; при условии остановки — (а) и (б) и сразу
сообщение владельцу. Исход запишет в `S2_STATUS.md` и ADR.
