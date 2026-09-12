---
trackerStatus:
  type: inbox
title: "Каталог доставки берётся из окружения: 15 зовов git, включая checkout origin/main в прод-дерево"
status: new
source: nimbalyst
created: 2026-09-12
priority: high
domain: delivery
---

Замер ADR-356 (цикл #578, прибор `scripts/shell_git_cd_target_census.py`) назвал **15 зовов
git**, чей каталог запуска задаёт ОКРУЖЕНИЕ, а не файл и не место копии. Предмет одинаков
при замере из прод-дерева и из worktree — то есть это свойство кода, а не наблюдателя.

| файл | зовов | откуда значение |
|---|---|---|
| `scripts/code_sync_from_origin.sh` | 5 | `REPO="${SPA_SYNC_REPO:-$HOME/Documents/SPA_Claude}"` |
| `scripts/DEPLOY.sh` | 5 | `CD="$HOME/Documents/SPA_Claude"` |
| `scripts/deploy_all.sh` | 5 | `CD="$HOME/Documents/SPA_Claude"` |

**Почему это не придирка.** У `code_sync_from_origin.sh` следом за `cd "$REPO"` идёт
`git checkout origin/main -- <пути>` — то есть сама доставка кода в рабочее дерево, чьё имя
пришло из окружения. `$HOME` под launchd и в сессии — разные вещи, а рядом с прод-деревом на
той же машине живут `.claude/worktrees` и `/tmp/spa_cNNN`: копии репозитория на СТАРЫХ
ревизиях, где тот же `checkout` означает совсем другое.

**Выход из класса уже написан в самом наборе** — `scripts/git_push.sh:13`:

```sh
REPO="$(cd "$(dirname "$0")/.." && pwd)"
```

Каталог выводится из места самого скрипта, следует за своей копией и в любом дереве попадает
в его корень. Прибор подтверждает это наблюдением, а не чтением: `git_push.sh` даёт
`proven_root` и из прод-дерева, и из worktree.

## Что сделать

1. Вывести каталог из места скрипта во всех трёх файлах; там, где переменная окружения нужна
   как осознанный переключатель (`SPA_SYNC_REPO`), оставить её, но **проверять** результат:
   каталог обязан быть корнем рабочей копии (`git -C "$REPO" rev-parse --show-toplevel`
   равен `$REPO`), иначе — отказ fail-CLOSED, а не тихая работа не в том дереве.
2. После починки **уменьшить** `scripts/shell_git_cd_target_baseline.json`. База может только
   уменьшаться; дописывать в неё запрещено.

## Приёмка

`python3 scripts/shell_git_cd_target_census.py --root . --json` даёт `undetermined` **меньше
15**, и те же ключи исчезли из базы. Контроль на сторожа уже есть в наборе
(`test_the_ratchet_is_able_to_fail`).

## Чего НЕ делать

Не трогать прод-дерево этой правкой: доставка идёт на origin, а синхронизация прод-дерева —
отдельное действие с разрешения владельца (`.claude/rules/deployment.md`, п. 6).

## Отдельная нота, не входящая в предмет

`secure_git_push.sh` выводит корень из `${BASH_SOURCE[0]}` и делает `git push`. Замер
2026-09-12: `env BASH_SOURCE=/hij bash script.sh` **перебивает** это значение на bash 3.2.57
(`/bin/bash` прод-хоста) и не перебивает на bash 5.x. В главный вердикт это не идёт (свойство
хоста), но записать стоит.
