# GIT_WORKFLOW.md — GitHub Workflow для SPA
> **Версия:** 1.0 | **Дата:** 2026-06-13 | **Статус:** ОБЯЗАТЕЛЬНО
> Полное руководство по пушу кода. Читай перед любым взаимодействием с GitHub.

---

## 🏗️ АРХИТЕКТУРА PUSH-СИСТЕМЫ

```
AI-агент (sandbox)
    │
    ├─► Создаёт: scripts/push_vNNN.sh  ← АТОМАРНО, chmod +x
    │
    └─► Сообщает пользователю: "Запустить scripts/push_vNNN.sh из Terminal"

Пользователь (Mac Terminal)
    │
    └─► Запускает: bash ~/Documents/SPA_Claude/scripts/push_vNNN.sh
              │
              └─► push_to_github.py → GitHub API → yurii-spa/SPA repo
```

**Критически важно:** Sandbox агента НЕ имеет доступа к macOS Keychain и GitHub.
Пуш ВСЕГДА происходит из Terminal пользователя. Это физическое ограничение, не выбор.

---

## 📦 СОЗДАНИЕ PUSH-СКРИПТА (шаблон)

Каждый спринт создаёт ОДИН push-скрипт. Шаблон:

```bash
#!/bin/bash
# Push MP-NNN <Описание> (SPA-VNNN)
# Создан: YYYY-MM-DD спринт vX.YZ
# Запускать: bash ~/Documents/SPA_Claude/scripts/push_vNNN.sh

COMMIT_MSG="feat(SPA-VNNN): MP-NNN <краткое описание>, N tests green"

FILES="\
spa_core/analytics/<module>.py \
spa_core/tests/test_<module>.py \
data/<module>_log.json \
KANBAN.json \
CURRENT_STATE.md"

# ── PAT fallback chain (НИКОГДА не встраивать PAT напрямую) ──
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && {
    echo "❌ PAT не найден. Добавь в Keychain:"
    echo "   security add-generic-password -s GITHUB_PAT_SPA -a spa -w YOUR_PAT"
    exit 1
}

echo "📦 Pushing MP-NNN..."
cd "$(dirname "$0")/.." || exit 1
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "✅ Done — проверить: https://github.com/yurii-spa/SPA/commits/main"
```

**Обязательные условия:**
- `chmod +x scripts/push_vNNN.sh` сразу после создания
- Все пути файлов — абсолютные или от корня репо
- Коммит-сообщение в формате Conventional Commits (см. ниже)

---

## 📝 CONVENTIONAL COMMITS (формат коммитов)

```
<type>(SPA-VNNN): <описание>, <N> tests green

Types:
  feat      — новый модуль / функциональность
  fix       — исправление бага
  refactor  — рефакторинг без изменения поведения
  docs      — только документация
  infra     — инфраструктура (launchd, пуш-система, CI)
  test      — добавление тестов
  chore     — обновление KANBAN, CURRENT_STATE, служебное

Примеры:
  feat(SPA-V664): MP-741 YieldCurveAnalyzer slope/curvature/inversion signals, 72 tests green
  fix(SPA-V665): MP-742 fix atomic write in ring_buffer logger
  infra(SPA-V666): MP-313 fix autopush launchd plist PYTHON_PATH
  docs(SPA-V667): update CURRENT_STATE v6.67, DECISIONS.md
```

---

## 🔑 PAT FALLBACK CHAIN

Агент ищет PAT в следующем порядке (используй именно эту цепочку в скриптах):

```bash
# 1. macOS Keychain (ПРИОРИТЕТ 1 — единственный надёжный источник)
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")

# 2. Env-переменная GITHUB_PAT_SPA
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-}"

# 3. Env-переменная SPA_GITHUB_PAT (алиас)
[ -z "$PAT" ] && PAT="${SPA_GITHUB_PAT:-}"

# 4. ~/.github_pat — ТОЛЬКО если там реальный токен, НЕ заглушка "INVALID_PLACEHOLDER"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ "$PAT" = "INVALID_PLACEHOLDER" ] && PAT=""  # игнорировать заглушку

# Финальная проверка
[ -z "$PAT" ] && { echo "❌ PAT не найден"; exit 1; }
```

**ИЗВЕСТНАЯ ПРОБЛЕМА:** `~/.github_pat` содержит `INVALID_PLACEHOLDER` — НЕ использовать как источник токена. Реальный PAT — только в Keychain (`GITHUB_PAT_SPA`).

---

## ✅ ВЕРИФИКАЦИЯ УСПЕШНОГО ПУША

После запуска push-скрипта пользователь должен увидеть:
```
✅ Done — проверить: https://github.com/yurii-spa/SPA/commits/main
```

Агент проверяет успешность пуша по выходу из `push_to_github.py` (exit code 0).

Для верификации через GitHub API (опционально):
```bash
curl -s -H "Authorization: token $PAT" \
  https://api.github.com/repos/yurii-spa/SPA/commits?per_page=1 \
  | python3 -c "import json,sys; c=json.load(sys.stdin)[0]; print(c['commit']['message'][:80])"
```

---

## 🔢 НУМЕРАЦИЯ PUSH-СКРИПТОВ

```
scripts/push_vNNN.sh    — основной скрипт спринта
scripts/push_vNNNb.sh   — если основной уже существует (параллельный спринт)
scripts/push_vNNNc.sh   — третий (редко)
```

Текущий последний скрипт: `push_v680.sh` (2026-06-13).
Следующий новый: `push_v681.sh`.

Проверка перед созданием:
```bash
NEXT=$(ls scripts/push_v*.sh 2>/dev/null | sort -t v -k2 -n | tail -1 | grep -o 'v[0-9]*' | head -1)
echo "Последний: $NEXT"
```

---

## 📋 МАСТЕР-СКРИПТ: run_all_pushes.sh

`scripts/run_all_pushes.sh` — запускает все pending push-скрипты последовательно.

Использование когда накопился пуш-долг (несколько unpushed скриптов):
```bash
bash ~/Documents/SPA_Claude/scripts/run_all_pushes.sh
```

Скрипт:
- Читает PAT из Keychain однократно
- Итерирует по `scripts/push_v*.sh` в числовом порядке
- Пропускает уже запушенные (из `.push_log`)
- При ошибке продолжает, записывает в `.push_failed`

---

## ⚡ КОНФЛИКТЫ И СИНХРОНИЗАЦИЯ

### Если push завершился с ошибкой:
1. Проверить PAT: `security find-generic-password -s GITHUB_PAT_SPA -w | wc -c` (должно быть > 0)
2. Проверить файлы: все пути из `FILES=` должны существовать
3. Проверить сеть: доступность api.github.com
4. Повторить: тот же скрипт безопасно повторить — `push_to_github.py` идемпотентен

### Если локальная копия отстала от GitHub:
```bash
# Проверить разницу:
git -C ~/Documents/SPA_Claude log --oneline origin/main..HEAD
# Синхронизировать (только read, не pull — агент не делает git pull):
# → Сообщить пользователю о необходимости git pull
```

### GitHub стал stale (данные устарели):
- Причина: autopush `com.spa.autopush` НЕ установлен (см. CURRENT_STATE.md)
- Немедленное решение: запустить `bash run_all_pushes.sh` из Terminal
- Долгосрочное: MP-313 — установить autopush (USER ACTION)

---

## 🚫 ЗАПРЕТЫ (GIT-специфичные)

1. **НЕ встраивать PAT в скрипт** — использовать только fallback chain
2. **НЕ создавать `push_*.html`** — только `.sh`
3. **НЕ пушить из sandbox** — только скрипты для Terminal
4. **НЕ удалять старые `push_vNNN.sh`** — `run_all_pushes.sh` использует их для tracking
5. **НЕ использовать `~/.github_pat`** если там `INVALID_PLACEHOLDER`
6. **НЕ делать `git push` напрямую** — только через `push_to_github.py`

---

*Источник: docs/governance/GIT_WORKFLOW.md v1.0 (2026-06-13)*
