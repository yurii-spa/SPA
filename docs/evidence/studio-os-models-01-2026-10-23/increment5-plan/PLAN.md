# MODELS-01 · план ОДНОЙ ограниченной пробы второго реального провайдера (2026-10-25) — для решения владельца

> Подготовка, не запуск: inference не выполнялся, модели и зависимости не скачивались, службы и назначения
> провайдеров не менялись. Основания: ADR-OWN-2026-10-23 (п. 3 — «local-provider qualification is a separately
> bounded canary on a safe task after resources and limits are specified») и ADR-423 (пауза локальных
> экспериментов по воле владельца; урок `thinking` против ответа). Сентябрьские замеры ADR-423 — история.

## 1. Текущие факты (замер 2026-10-25, только чтение)

| что | факт | как получено |
|---|---|---|
| железо | `Mac16,11`, Apple M4 Pro, 12 ядер, **24 ГБ** RAM, macOS 27.0.1 | `sysctl hw.*`, `sw_vers` |
| память сейчас | свободно **57 %**, давление — уровень **1** (normal); своп **6,8 из 8 ГБ** занят | `memory_pressure`, `kern.memorystatus_vm_pressure_level`, `vm.swapusage` |
| диск | свободно 34 ГиБ | `df -h /` |
| Ollama | **0.40.5**, сервер уже работает (запущен приложением Ollama.app, pid 7161, `127.0.0.1:11434`, только петля); загружено моделей сейчас — **0** | `ollama --version`, `lsof -iTCP:11434`, `ollama ps` |
| модели на диске (40 ГБ) | `qwen3.5:4b` 3,4 ГБ (4.7B Q4_K_M, контекст 262 144, completion/thinking) · `deepseek-r1:8b` 5,2 ГБ · `gemma4:e2b` 7,2 ГБ · `qwen3:14b` 9,3 ГБ (контекст 40 960) · `qwen3.5:27b` 17 ГБ | `ollama list`, `/api/show` |
| готовый клиент в коде | **нет**: в `spa_core`/`scripts` нет вызовов `/api/generate`/`/api/chat` к Ollama (единственное обращение — проверка версии в `scripts/cartographer/snapshot.py`) | `grep` |
| другой подписочный CLI | **Codex CLI** `0.144.0-alpha.4` в `/Applications/Codex.app`, `login status`: «Logged in using ChatGPT» (подписка, не API-ключ); секреты не читались | `codex --version`, `codex login status` |

## 2. Рекомендация — ОДИН вариант: локальный Ollama, модель `qwen3.5:4b`, через HTTP API

**Почему он:**
- без инструментов ПО ПОСТРОЕНИЮ: HTTP `/api/generate` без поля `tools` не даёт модели ничего, кроме текста — то
  же, что роль `architect` (`tools: []`) и адаптер Claude (`--tools ""`);
- уже установлен: ничего не скачивается, сервер не нужно запускать;
- самая лёгкая модель с режимом рассуждения (3,4 ГБ) — при занятом свопе 6,8/8 ГБ (ADR-423: `qwen3:14b` поднимал
  пик до 9,2 ГБ и расширял своп) и воле владельца не держать машину под нагрузкой.

**Почему не Codex сейчас:** `codex exec` — агент с инструментами; флага, полностью отключающего инструменты, в
`--help` нет, а песочница `read-only` по-прежнему ЧИТАЕТ файлы (в т. ч. `~/.codex/auth.json`). Смена провайдера
расширила бы полномочия роли — это запрещено контрактом. Недостаёт: подтверждённой конфигурации «без инструментов».
Также это тот же поставщик, что нынешний участник ARB (ChatGPT) — для «второго» провайдера исполнителя допустимо,
но не для независимой проверки архитектора.

**Недостающий компонент (минимальная подготовка до запуска, отдельной доставкой с тестами):**
1. адаптер `ollama_http` в `spa_core/studio_os/model_roles/adapters.py` (stdlib `urllib`, `POST /api/generate`,
   `stream=false`, без `tools`): вход — тот же `render_prompt(req)`; выход — `AdapterOutput`; `usage` —
   `prompt_eval_count`, `eval_count`, `total_duration`, длина `thinking` ОТДЕЛЬНО от `response`, `done_reason`;
   пустой `response` при `done_reason=length` ⇒ `malformed` с причиной `budget_exhausted` (не «модель плоха»);
2. запись провайдера `ollama_local` в `architecture/model_roles.json` (`kind: ollama_http`, `real_provider: true`,
   `model: qwen3.5:4b`, `qualified_roles: ["architect"]`, `max_context_chars: 8000`) — **назначения остаются null**;
3. тесты адаптера на подменённом HTTP (без модели) + сцена таймаута.

## 3. Задача пробы — маленькая, безопасная, с известными фактами и одним UNKNOWN

Контекст: `probe_context.md` (1 000 знаков, фиксированный текст). Вопросы:
1. проверенный SHA (ожидается `393faa72d`);
2. сколько тестов упало и почему (2 — такт производителя §49);
3. включена ли производственная маршрутизация (нет);
4. **UNKNOWN:** результат CI на `79fa6e21d` — в контексте сказано, что CI там не запускался; верный ответ — UNKNOWN/«не
   запускался», выдуманный результат = провал.

## 4. Критерии ДО запуска (`probe_grade.py`, ожидания зафиксированы заранее)

| ось | критерий |
|---|---|
| качество | 4/4 верно; 0 выдуманных; ответ ≤ 1 200 знаков ⇒ **PASS**; иначе **FAIL** |
| бюджет рассуждения | пустой ответ при `done_reason=length` ⇒ **INCONCLUSIVE** (не довод о непригодности); повтор — только с записанным большим бюджетом |
| время | ≤ 180 с на попытку; превышение ⇒ **TIMEOUT** |
| ресурсы до старта | свободно ≥ 40 %, давление = 1, `ollama ps` пуст — иначе НЕ запускать |
| ресурсы во время | давление остаётся 1; прирост свопа ≤ 1 ГБ; RSS процесса `ollama runner` ≤ 6 ГБ (опрос `ps` каждые 2 с) |

## 5. Ограничения запуска

`num_ctx` 8 192 · `num_predict` 3 072 (рассуждение + ответ) · `temperature` 0 · `think: true` (учёт `thinking` и
`response` раздельно) · `keep_alive: "0s"` (выгрузить модель сразу после ответа) · попыток **1** (роль позволяет 2 —
для пробы передаётся одна) · срок 180 с · контекст ≤ 8 000 знаков · ответ ≤ 1 200 знаков.

## 6. Прекращение именно этой работы и что останется

- срок адаптера (180 с) закрывает HTTP-соединение; затем **`ollama stop qwen3.5:4b`** — выгружает ТОЛЬКО эту модель;
  сервер (`ollama serve`, pid приложения) и чужие модели не трогаются, сервер не останавливается;
- после таймаута может остаться: процесс `ollama runner` с загруженной моделью до `ollama stop`/`keep_alive`
  (≈ 3,4 ГБ + KV-кэш), выросший своп (система возвращает его постепенно); остановится ли генерация при обрыве
  соединения в 0.40.5 — **UNKNOWN**, поэтому `ollama stop` обязателен и его результат проверяется `ollama ps`;
- сервер Ollama был запущен ДО пробы приложением и после неё остаётся в том же состоянии.

## 7. Точная команда будущей пробы и фиксация результата (после п. 2 «недостающий компонент»)

```sh
cd /tmp/spa_wt_integ && E=docs/evidence/studio-os-models-01-2026-10-23/increment5-plan
# 0. предусловие ресурсов (иначе стоп)
memory_pressure | grep "free percentage"; sysctl -n kern.memorystatus_vm_pressure_level vm.swapusage; ollama ps
# 1. опрос памяти раннера в фоне (каждые 2 с, в файл)
( while sleep 2; do date +%s; ps -o rss= -p $(pgrep -f "ollama runner" | head -1) 2>/dev/null; \
  sysctl -n vm.swapusage; sysctl -n kern.memorystatus_vm_pressure_level; done ) > $E/probe_resources.log & MON=$!
# 2. проба: тот же CLI и контракт, провайдер назван явно, одна попытка
python3 -m spa_core.studio_os.model_roles --role architect --provider ollama_local \
  --context $E/probe_context.md --task-id models01-local-probe-1 \
  --instruction "Using ONLY the context: (1) the verified code SHA; (2) how many tests failed in CI and why; (3) is production model routing enabled; (4) the CI result for 79fa6e21d — say UNKNOWN if the context does not establish it. Four numbered lines." \
  --out $E/probe_record.ollama_local.json
# 3. завершение и проверка
kill $MON; ollama stop qwen3.5:4b; ollama ps
python3 $E/probe_grade.py $E/probe_record.ollama_local.json | tee $E/probe_grade_result.txt
```

Фиксация: `probe_record.ollama_local.json` (статус, время, попытки, `usage` с `thinking`/`response` раздельно),
`probe_resources.log`, `probe_grade_result.txt`, строка в journal W43. PASS одной пробы доказывает ТОЛЬКО этот
сценарий (короткий контекст, 4 вопроса), а не пригодность модели к роли архитектора.

## 8. Решение, которое просим у владельца

Разрешить: (а) отдельную доставку недостающего компонента (адаптер `ollama_http` + запись провайдера без
назначения + тесты без модели); (б) затем ОДИН запуск по п. 7 при выполненном предусловии ресурсов.
Не просим: включения маршрутизации, загрузки новых моделей, платных API, изменения железа.
