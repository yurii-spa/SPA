# GitHub PAT — Runbook по ротации и устройству

> **Зачем этот файл:** токены теперь имеют срок жизни (это защита, а не баг).
> Когда пуши в GitHub перестанут работать — НЕ ищи проблему, открой этот файл.
> Создан 2026-06-10 после инцидента с утечкой PAT (детали внизу).

---

## TL;DR — пуши сломались, что делать (2 минуты)

Симптом: `auto_push.py` пишет 401 в `~/.spa_push.log`, либо `push_to_github.py` падает с 401.
Причина почти наверняка: **истёк срок основного токена** (см. таблицу ниже).

1. Открой https://github.com/settings/personal-access-tokens → **Generate new token**
   - Token name: `spa-claude-fg` (старый можно удалить)
   - Expiration: **90 days**
   - Repository access: **Only select repositories** → `yurii-spa/SPA`
   - Permissions → Repository permissions:
     - **Contents: Read and write**
     - **Workflows: Read and write**
     - (Metadata: Read-only добавится сам)
   - Generate token → скопируй значение
2. В терминале:
   ```bash
   cd ~/Documents/SPA_Claude && bash setup_pat.sh
   ```
   (вставишь токен интерактивно — он попадёт в Keychain, не в файлы и не в историю shell)
3. Проверка:
   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' \
     -H "Authorization: Bearer $(security find-generic-password -s GITHUB_PAT_SPA -w)" \
     https://api.github.com/repos/yurii-spa/SPA
   # должно напечатать 200
   ```

Всё. Автопуши заработают со следующего цикла.

---

## Инвентарь токенов (на 2026-06-10)

| Токен | Тип | Права | Истекает | Кто использует | Действие при истечении |
|---|---|---|---|---|---|
| **spa-claude-fg** | fine-grained | только `yurii-spa/SPA`: Contents RW, Workflows RW | **2026-09-08** | **ВСЁ**: Keychain `GITHUB_PAT_SPA` → `auto_push.py`, `push_to_github.py`, `push_to_github.command`, `trigger_workflow.command` | **Ротация по TL;DR выше** |
| spa | fine-grained | (старый, не трогали) | 2026-06-20 | неизвестно / legacy | дать умереть; если что-то сломается ~20 июня — мигрировать это на Keychain |
| New token | classic | repo, workflow | 2026-06-25 | ничто (never used) | дать умереть или удалить |
| spa-claude | classic | repo | 2026-07-10 | ничто (регенерирован 2026-06-10, новое значение нигде не сохранено) | дать умереть |

GitHub присылает **email-предупреждение примерно за неделю** до истечения каждого токена —
это и есть штатный сигнал к ротации, не жди 401.

## Как устроено хранение (single source of truth)

```
GitHub (выпуск токена, 90 дней)
   └─► macOS Keychain: service=GITHUB_PAT_SPA, account=spa   ← ЕДИНСТВЕННОЕ место хранения
          ├─► auto_push.py            (почасовой автопуш, launchd)
          ├─► push_to_github.py       (ручной пуш)
          ├─► push_to_github.command  (double-click пуш)
          └─► trigger_workflow.command (запуск GitHub Actions)
```

- Запись/обновление: `bash setup_pat.sh` (интерактивно) или
  `security add-generic-password -s GITHUB_PAT_SPA -a spa -w 'TOKEN' -U`
- Чтение: `security find-generic-password -s GITHUB_PAT_SPA -w`
- **Токен НИКОГДА не пишется в файлы** — см. SECRETS POLICY в CLAUDE.md.

## Защитные слои (что ловит утечку, если она всё же случится)

1. **SECRETS POLICY в CLAUDE.md** — агенты Claude не пишут секреты в файлы.
2. `secure_git_push.sh` — отказывается пушить, если токен совпадает с известными утёкшими суффиксами.
3. `auto_push.py` SKIP_PATTERNS — не пушит `.claude/`, `.pytest_cache`, `push_v*`, `*.bak.*`.
4. **GitHub Push Protection + Secret Protection включены** в репо (Settings → Advanced Security) —
   блокируют пуш файлов с распознаваемыми секретами на стороне GitHub.
5. Fine-grained токен с минимальными правами и сроком 90 дней — ограничивает ущерб.

## Справка: инцидент 2026-06-10

Классический PAT с полными админ-правами лежал в plaintext в CLAUDE.md и был растиражирован
агентами в 90+ сгенерированных файлов (`push_*.html` и др.); один такой файл (`push_v23.html`)
попал в репозиторий. 2026-06-10 оба утёкших токена отозваны, все файлы зачищены (локально и
в репо), выпущен fine-grained токен, вся цепочка переведена на Keychain. Старые версии файлов
с отозванными токенами остались в git-истории репо — это безвредно (токены мертвы).
Полная хронология: `SECURITY_REMEDIATION.md`.

**Корневой урок:** секрет, записанный в файл, который читают агенты, самовоспроизводится.
Секреты живут только в Keychain.
