---
trackerStatus:
  type: inbox
title: "origin/main красен ещё восемью тестами: три из них — сторожа сторожей, и их вердикты недействительны"
status: new
source: nimbalyst
created: 2026-10-07
---

## Что случилось и почему это важно

`origin/main` красен **тринадцатью** тестами, и это измерено, а не предположено. Цикл #790
(07.10) мерил дифференциально: один и тот же набор прогнан в ДВУХ чистых worktree —
`53c5a59e7` (до коммита цикла) и `9b482969` (после). Результат: **8 failed, 90 passed в обоих,
НАБОР ИМЁН ИДЕНТИЧЕН** ⇒ ни одно падение не внесено работой #790 и ни одно ею не починено.

Две группы уже заведены своими карточками (`inbox-hrapovik-invarianta-17-krasen-na-main-tr`,
`inbox-perepis-cd-pered-git-krasna-na-main-depl`). **Эта карточка — про остальные пять файлов,
восемь тестов:**

| тест | что он охраняет |
|---|---|
| `test_decision_journal_coverage.py::ReaderPopulationRatchet::test_every_production_reader_is_in_the_population` | население читателей журнала решений — храповик |
| `test_python_git_ref_provenance.py::TestRatchet::test_real_tree_matches_the_frozen_baseline` | провенанс git-ссылок в python, база |
| `test_python_git_ref_provenance.py::RegistryGovernance::test_an_intact_baseline_passes` | **положительный контроль самого храповика** |
| `test_python_git_ref_provenance.py::RegistryReactsToTheCensus::test_removing_an_unresolved_identity_reduces_the_debt` | реагирует ли реестр на перепись |
| `test_python_git_ref_provenance.py::RegistryReactsToTheCensus::test_the_unchanged_census_is_green` | неизменная перепись обязана быть зелёной |
| `test_repair_phantom_intake_cards.py::test_close_note_explains_it_was_not_the_owner` | закрытие карточки ОБЪЯСНЯЕТ, что это не владелец (инв. #14) |
| `test_timeseries_lane_modules.py::test_falling_apy_riskier_than_rising[apy_tracker]` | падающий APY рискованнее растущего — свойство прибора |
| `test_unwired_registry_evidence.py::TestTheRuleOnTheRealRepo::test_the_carve_out_did_not_swallow_the_watch` | вычет R&D не отключил сторожа подключённости |

**Почему это серьёзнее обычной красноты.** Три из восьми — это сторожа СТОРОЖЕЙ
(`test_an_intact_baseline_passes`, `test_the_unchanged_census_is_green`,
`test_the_carve_out_did_not_swallow_the_watch`). Когда красен положительный контроль храповика,
нельзя сказать, что храповик вообще что-то меряет: его вердикт перестаёт быть вердиктом. А
`test_close_note_explains_it_was_not_the_owner` стои́т прямо на инварианте #14 — закрытие
карточки владельца без объяснения, что закрыл её НЕ владелец.

Отдельно: в том же прогоне **7 отказов из 2 тестов** — продуктовый код под тестом тянется к
ЖИВОМУ фиду и получает fail-CLOSED `OSError` (`test_rwa_backstop.py::test_real_registry_loads_and_classifies`
×6, `test_agents_llm_and_routing.py::TestLLMAgentFallback::test_fallback_triggers_on_api_error` ×1).
Это нарушение `.claude/rules/adapters.md` («тесты инжектят `FakeFeed`, не завязывать тесты на
живую сеть») и само по себе делает прогон зависящим от сети.

## Что от тебя нужно

1. Разобрать каждый из восьми ПО ОТДЕЛЬНОСТИ: это настоящая находка сторожа (чинить код) или
   сторож краснеет на верное состояние (чинить сторожа и закреплять тестом в обе стороны)?
   Дописывать в базы храповиков, чтобы погасить падение, ЗАПРЕЩЕНО (инв. #16).
2. Начать с трёх сторожей сторожей: пока они красны, вердикты их храповиков недействительны, и
   любая работа, опирающаяся на «храповик зелёный», опирается на ничто.
3. Отдельно — инжекция фида в двух тестах, тянущихся к сети.
4. Назвать ЦИКЛ-ИСТОЧНИК каждого падения (`git log -S` по базе/по тесту): краснота, у которой
   нет автора, возвращается.

## Как понять, что готово

`SPA_ENV=ci PYTHONHASHSEED=0 python3 -m pytest spa_core/tests/test_decision_journal_coverage.py spa_core/tests/test_python_git_ref_provenance.py spa_core/tests/test_repair_phantom_intake_cards.py spa_core/tests/test_timeseries_lane_modules.py spa_core/tests/test_unwired_registry_evidence.py -q`
зелёный, базы храповиков НЕ выросли, и ни один тест не тянется к живой сети.

## Что будет после

`main` перестаёт быть красным, а «храповик зелёный» снова что-то значит. Пока эти восемь красны,
каждый следующий цикл платит за них дифференциальным замером (цикл #790 потратил на это два
прогона по 16 минут только чтобы доказать, что краснота не его).
