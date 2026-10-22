"""Срок прогона переживает обойдённый модуль (ADR-676, вторая половина).

Обходчики населения (`run_identity_key_price` и родня) зовут чужие модули, а
вердикт срока pytest-timeout (`Failed`, прямой потомок `BaseException`) прилетает
туда, где в этот момент исполняется код. `timeout_door_census.is_foreign_failure`
защищает только ``except`` САМОГО обходчика; модуль, которого он зовёт, вправе
иметь свой ``except BaseException`` — и тогда вердикт гибнет внутри него, а
таймер ``ITIMER_REAL`` одноразовый: второго срабатывания не будет.

Модуль живёт отдельно от `timeout_door_census` намеренно: тот прибор мерит
двери (`signal.signal(SIGALRM, …)`, `setitimer`) по дереву и молчаливого
исключения для себя не имеет (`test_the_instrument_does_not_become_its_own_finding`);
охрана срока сама является таким местом и честно числится в его находках.
"""
from __future__ import annotations

import signal
import threading
import time
from typing import Optional

#: Шаг ПОВТОРНОГО срабатывания после того, как срок прогона уже вынесен. Это не
#: новый лимит и не продление: срок истёк, и повтор лишь не даёт обойдённому
#: модулю досидеть до конца, проглотив первый вердикт.
DEADLINE_REPEAT_S = 0.5


class keep_deadline:
    """Срок прогона переживает ОБОЙДЁННЫЙ модуль (ADR-676, вторая половина).

    ``is_foreign_failure`` защищает только ``except`` САМОГО обходчика. Модуль,
    которого обходчик зовёт, вправе иметь свой ``except BaseException`` — и
    тогда вердикт срока (`Failed` pytest-timeout) гибнет внутри него, а таймер
    ``ITIMER_REAL`` одноразовый: второго срабатывания нет, и случай живёт до
    конца переписи. Замер 22.10 (`BatteryHoleTests`, ``--timeout=180``): срок
    сработал на 188 с внутри зова ``acceptance_tree_capability`` →
    ``card_acceptance._probe_portfolio_decision_owner_covers_capital``, где
    ``except BaseException`` вернул «перепись упала», и тест шёл ≈1230 с.

    Что делает на время зова:

    * ставит ретранслятор поверх текущего обработчика ``SIGALRM``: первое
      срабатывание отдаётся настоящему обработчику, его исключение ЗАПОМИНАЕТСЯ
      и таймер взводится повторно на :data:`DEADLINE_REPEAT_S` — повторы
      поднимают то же исключение, пока оно не выйдет из модуля;
    * на выходе: срок сработал ⇒ поднимается ТО ЖЕ исключение, что бы модуль ни
      вернул или ни поднял взамен; модуль снял внешний таймер
      (``alarm(0)``/``setitimer(…, 0)``) ⇒ остаток срока взводится заново;
      обработчик, оставленный модулем, заменяется прежним.

    Обработчика-функции нет (``SIG_DFL``/``SIG_IGN``) или поток не главный ⇒
    ничего не делается: срока, который можно потерять, нет.
    """

    def __init__(self) -> None:
        self.active = False
        self.fired: Optional[BaseException] = None

    def __enter__(self) -> "keep_deadline":
        if threading.current_thread() is not threading.main_thread():
            return self
        try:
            prev = signal.getsignal(signal.SIGALRM)
        except (AttributeError, ValueError):
            return self
        if not callable(prev):
            return self
        self._prev = prev
        self._clock = time.monotonic
        self._t0 = time.monotonic()
        self._remaining = signal.getitimer(signal.ITIMER_REAL)[0]

        def relay(signum, frame):
            if self.fired is not None:
                signal.setitimer(signal.ITIMER_REAL, DEADLINE_REPEAT_S)
                raise self.fired
            try:
                prev(signum, frame)
            except BaseException as exc:  # noqa: BLE001 — запоминается и ПОДНИМАЕТСЯ
                self.fired = exc
                signal.setitimer(signal.ITIMER_REAL, DEADLINE_REPEAT_S)
                raise

        self._relay = relay
        signal.signal(signal.SIGALRM, relay)
        self.active = True
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if not self.active:
            return False
        self.active = False
        if self.fired is not None:
            signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, self._prev)
        if self.fired is not None:
            if exc is self.fired:
                return False
            raise self.fired
        if self._remaining > 0 and signal.getitimer(signal.ITIMER_REAL)[0] == 0:
            left = self._remaining - (self._clock() - self._t0)
            signal.setitimer(signal.ITIMER_REAL, max(left, 0.001))
        return False
