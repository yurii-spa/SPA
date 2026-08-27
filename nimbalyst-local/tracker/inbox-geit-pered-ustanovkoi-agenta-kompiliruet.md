---
trackerStatus:
  type: inbox
title: Гейт перед установкой агента КОМПИЛИРУЕТ скрипт вместо импорта — и сказал «PASSED» про агента, который умирает при каждом запуске
status: new
source: nimbalyst
created: 2026-08-27
---

## Что нашли (замер цикла #390, 2026-08-27)

`scripts/agent_static_probe.sh` — зонд, который зовёт гейт перед установкой агента
(`check_agent_before_deploy.sh`). Прогнан против скрипта, который падает при КАЖДОМ
запуске (`find_defillama_sources.py`, авария 26.08):

```
   import probe interpreter: /Users/.../python3
   compile: .../scripts/find_defillama_sources.py ✅ (py_compile, script NOT executed)
✅ STATIC PROBE PASSED — nothing was started, no live instance was disturbed.
```

Скриптовой цели зонд даёт **только `py_compile`** — проверку синтаксиса, напечатанную
после строки «import probe interpreter». Модульной цели он честно делает
`importlib.import_module`, скриптовой — нет.

Вторая половина: обёртку в режиме B (цель — позиционный аргумент шаблона, так устроен
и `agent_source_discovery.sh`) зонд не разбирает вовсе и отказывает fail-CLOSED.
Отказ честный, но означает, что про такого агента гейт не сказал ничего.

## Что сделать

Заменить `py_compile` для скриптовых целей на настоящую загрузку — она уже есть и
доставлена циклом #390: `python3 -m spa_core.monitoring.entrypoint_import_probe
--script <путь>` (ADR-148). Разбор режима B — `resolve_wrapper_target` из того же
модуля. Оба возвращают JSON и коды 0/3/4.

Обязательные условия:
- запасной путь, если в проверяемом дереве модуля ещё нет (гейт судит ЧУЖОЕ дерево);
- прогнать по всем 85 точкам входа ДО включения — на 27.08 цель импортируют 72,
  не импортируют 0, вне разбора 13 (сценарии), то есть ложных отказов не ожидается;
- `spa_core/tests/test_deploy_gate_long_lived.py` — приёмка обеими сторонами.

## Почему НЕ сделано циклом #390

Это правка гейта, через который проходит каждая установка агента. Она заслуживает
своего захода и своей приёмки, а не хвоста чужого коммита. Дыра измерена и названа,
а не оставлена «на память».

Связано: ADR-148, `spa_core/monitoring/entrypoint_import_probe.py`,
`inbox-vklyuchennyi-nochyu-source-discovery-pad`.
