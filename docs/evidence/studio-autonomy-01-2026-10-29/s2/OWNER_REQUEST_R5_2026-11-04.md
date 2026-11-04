# R5 — запрос владельцу (перепин на релиз 03.11): доверенный корень из проверенного пакета и канарейка B → A

**Статус:** подготовлено, шаг 0 выполнен агентом БЕЗ root 04.11 на этих SHA (все проверки прошли), шаги 1–3 НЕ выполнены.
Агент root/sudo не использует. Пароль вводится только в терминале Mac, в чат не нужен. Заменяет SHA прежнего
`OWNER_REQUEST.md` (B=`92b75ff85`, A=`63b96a1e7` — старый S2-коммит, не релиз); процедура, проверки и восстановление те же.

## Версии
| | SHA | Основание |
|---|---|---|
| **B** — пакет установки и запускаемый релиз | `c74e178666baf615048223fba97d717b81845a4a` | `main` после стадии r3 (ADR-909), ci-control `41735344220` (12/12, регрессий состава нет) |
| **A** — предыдущий проверенный релиз | `ca86fd56866e6fac329e54a294b486849711a9ec` | `main` после стадии r2, ci-control `41726124099` (12/12) |

Файлы установщика в B побайтно те же, что в прежнем пакете и в `INSTALL_PIN.json` этого коммита (сверено 04.11):
`install_trusted_bootstrap.sh` `1802ce43…318f` · `build_trusted_runtime.sh` `73a7ea35…4b6b` · `release_launcher.py`
`7e778f2b…2aed` · `trusted_install_bundle.py` `85c19934…b889` · runtime digest `09eecca2…90b2`.

## Что агент уже сделал без root (04.11, песочница агента)
0.1 верификатор из коммита B = `85c19934…` · 0.2 `stage` — 4/4 хеша = пин · 0.3 runtime digest = закреплённый ·
0.4 `--dry-run` = 0; `--self-test-root` A и B — оба релиза материализованы и доказаны лаунчером (rc=0).
Корень сейчас (только чтение): одобрен `4cb68535…`, лаунчер `eec1ae58…`, релизы `4cb68535…`/`5b652577…`; ни один plist флота
на корень не указывает. Свободно на `/` 82 ГБ.

## Шаг 0 — без root (у Мака, ~5 мин; любой REFUSED / несовпадение — стоп)
```bash
BUNDLE=c74e178666baf615048223fba97d717b81845a4a
A=ca86fd56866e6fac329e54a294b486849711a9ec
REPO=~/Documents/SPA_Claude
D=$(date +%Y%m%d)
STAGE=~/StudioOS_install_$D ; RTSTAGE=~/StudioOS_runtime_$D          # оба НЕ должны существовать
ROOT="/Library/Application Support/StudioOS"
RSTAGE="/Library/Application Support/StudioOS_install/${BUNDLE}"
RSNAP="/Library/Application Support/StudioOS_install/snapshot_$D"
RDIGEST=09eecca2da07a58156dff27ee5e904620675e05ffd60e31c08a7866cd10390b2
LSHA=7e778f2b33494a601413f69d4d90e491fc7632d172ff916e4a0d39685b432aed
git -C "$REPO" fetch origin main
git -C "$REPO" cat-file -e "${BUNDLE}^{commit}" && git -C "$REPO" cat-file -e "${A}^{commit}" && echo OK
git --no-replace-objects -C "$REPO" show "${BUNDLE}:spa_core/studio_os/trusted_install_bundle.py" > /tmp/tib.py
shasum -a 256 /tmp/tib.py        # = 85c19934ac99b412a18d3e88123395f9cfe82b6da275113b8d274856ea74b889
/usr/bin/python3 -I /tmp/tib.py stage --repo "$REPO" --sha "$BUNDLE" --stage "$STAGE" \
  --expect=scripts/install_trusted_bootstrap.sh=1802ce4337bea3a105b0e6e9816f7d8b98f4bb05ebeacac5dcf760881351318f \
  --expect=scripts/build_trusted_runtime.sh=73a7ea352f126833eafeb17054e5f77f16d0f644830ac59ccb2ca30300694b6b \
  --expect=spa_core/studio_os/release_launcher.py=7e778f2b33494a601413f69d4d90e491fc7632d172ff916e4a0d39685b432aed \
  --expect=spa_core/studio_os/trusted_install_bundle.py=85c19934ac99b412a18d3e88123395f9cfe82b6da275113b8d274856ea74b889
bash "$STAGE/scripts/build_trusted_runtime.sh" --src ~/miniconda3/bin/python3.13 --stage "$RTSTAGE" --print-digest   # RUNTIME_DIGEST = $RDIGEST
(cd "$REPO" && python3 -m spa_core.monitoring.deployment_acceptance; echo "rc=$?")                                  # rc=0
launchctl list | grep com.spa > ~/StudioOS_fleet_before_$D.txt
git -C "$REPO" status --short data/ | shasum -a 256 > ~/StudioOS_data_before_$D.txt
```
В zsh переменная перед `:` или `^` — только в фигурных скобках (`"${BUNDLE}:путь"`).

## Шаг 1 — ПЕРВОЕ административное действие (sudo, пароль в терминале)
**1.0 пакет и runtime → root-owned каталог, сверка 4 хешей:**
```bash
sudo mkdir -p "$RSTAGE"
sudo ditto "$STAGE" "$RSTAGE/bundle" && sudo ditto "$RTSTAGE" "$RSTAGE/runtime"
sudo chown -R root:wheel "$RSTAGE" && sudo chmod -R a-w "$RSTAGE"
(cd "$RSTAGE/bundle" && printf '%s  %s\n' \
  1802ce4337bea3a105b0e6e9816f7d8b98f4bb05ebeacac5dcf760881351318f scripts/install_trusted_bootstrap.sh \
  73a7ea352f126833eafeb17054e5f77f16d0f644830ac59ccb2ca30300694b6b scripts/build_trusted_runtime.sh \
  7e778f2b33494a601413f69d4d90e491fc7632d172ff916e4a0d39685b432aed spa_core/studio_os/release_launcher.py \
  85c19934ac99b412a18d3e88123395f9cfe82b6da275113b8d274856ea74b889 spa_core/studio_os/trusted_install_bundle.py \
  | shasum -a 256 -c -)                                                   # 4 × OK
BD="$RSTAGE/bundle"; INST="$BD/scripts/install_trusted_bootstrap.sh"; TIB="$BD/spa_core/studio_os/trusted_install_bundle.py"
LAUNCHER="$BD/spa_core/studio_os/release_launcher.py"; RT="$RSTAGE/runtime"
```
**1.1 снимок исходной конфигурации (хеш записать НА БУМАГЕ / в отчёт — нужен для отката):**
```bash
sudo /usr/bin/python3 -I "$TIB" snapshot --root "$ROOT" --snapshot "$RSNAP"     # печатает SNAPSHOT_SHA256=…
SNAPSHA=<значение SNAPSHOT_SHA256>
sudo /usr/bin/python3 -I "$TIB" verify --root "$ROOT" --snapshot "$RSNAP" --expect-snapshot-sha256 "$SNAPSHA"   # MATCH
```
**1.2 установка A, затем B:**
```bash
sudo bash "$INST" --launcher "$LAUNCHER" --launcher-sha256 "$LSHA" --repo "$REPO" --approved "$A" --runtime "$RT" --runtime-digest "$RDIGEST"
sudo bash "$INST" --launcher "$LAUNCHER" --launcher-sha256 "$LSHA" --repo "$REPO" --approved "$BUNDLE" --runtime "$RT" --runtime-digest "$RDIGEST"
cat "$ROOT/approved_release.json"     # {"approved_sha":"c74e1786…"}
```

## Шаг 2 — одна канарейка (новый plist; plist флота не меняются)
Текст plist и команды — дословно `OWNER_REQUEST.md`, шаг 2 (меняется только SHA в одобрении, plist SHA не содержит).

## Шаг 3 — измерения (делает агент; ты только пишешь «готово» после шага 2)
```bash
MEASURE='from spa_core.studio_os import release_state as R; print(R.active_processes("/Library/Application Support/StudioOS/releases"))'
(cd ~/Documents/SPA_Claude && python3 -c "$MEASURE")      # пока работает канарейка: процесс с sha = B
```
Возврат к A: повторить сверку 1.0 → `sudo bash "$INST" … --approved "$A" …` → `launchctl kickstart gui/$(id -u)/com.spa.release_canary`
→ замер называет sha = A. До/после каждого шага: `git -C "$REPO" status --short data/ | shasum -a 256` = до;
`launchctl list | grep com.spa` — коды остальных агентов не изменились.

## Стоп и восстановление
Стоп-условия и восстановление (а) остановка канарейки, (б) `restore` по записанному `SNAPSHA`, (в) доказательство A —
дословно `OWNER_REQUEST.md`, разделы «Условия остановки» и «Восстановление».

## Что остаётся НЕ измеренным
Шаги под root (`chown`, проверка `sudo -u`, сверка установленной копии лаунчера, `restore`) ни разу не исполнялись —
первая проверка и есть шаг 1; запуск канарейки через launchd в gui-домене — только шаги 2–3. R5 доказывает механизм
«запустить проверенный релиз → откатиться на предыдущий»; флот на корень не переключается.
