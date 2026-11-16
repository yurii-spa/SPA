"""Контроли двери свободных портов (ADR-1030) — в ОБЕ стороны.

Зелёные на целом контуре и КРАСНЫЕ на каждом порванном звене, с названным звеном.
Главный из них — :meth:`TheNumbersAreDistinctByConstruction
.test_an_OS_that_reuses_a_closed_number_still_gets_distinct_ports`: он РАЗЛИЧАЕТ
правильную дверь от той, что измеряет номера по очереди, закрывая каждый сокет
перед следующей пробой. Без такой сцены мутант «закрывать сразу» выживал бы почти
всегда — именно потому, что настоящая ОС редко выдаёт номер повторно, и тест
отвечал бы на вопрос «повезло ли сегодня».
"""
from __future__ import annotations

import socket
import unittest
from pathlib import Path
from unittest import mock

from spa_core.tests import _loopback_ports as lp


class _FakeSock:
    """Сокет-пенёк: знает свой номер и помнит, закрыт ли он."""

    def __init__(self, port: int):
        self.port = port
        self.closed = False

    def getsockname(self):
        return ("127.0.0.1", self.port)

    def close(self):
        self.closed = True


class _ReusingOS:
    """ОС, которая отдаёт номер СНОВА, едва его отпустил последний живой сокет.

    Это не карикатура, а РАЗРЕШЁННОЕ поведение: закрытый порт свободен, и повторная
    выдача — не ошибка ядра. Дверь, держащая сокеты одновременно, от такой ОС всё
    равно получает разные номера; дверь, закрывающая каждый сокет перед следующей
    пробой, получит один и тот же.
    """

    FIRST = 50000

    def __init__(self):
        self.made: list[_FakeSock] = []
        self.calls = 0

    def bind(self, host):
        self.calls += 1
        taken = {s.port for s in self.made if not s.closed}
        port = self.FIRST
        while port in taken:
            port += 1
        sock = _FakeSock(port)
        self.made.append(sock)
        return sock


class _StubbornOS:
    """ОС, нарушающая правило: один и тот же номер даже живым сокетам."""

    def __init__(self, port: int = 50000):
        self.port = port

    def bind(self, host):
        return _FakeSock(self.port)


class TheNumbersAreDistinctByConstruction(unittest.TestCase):

    def test_two_ports_from_the_real_OS_differ_and_both_can_be_bound(self):
        local, public = lp.free_ports(2)
        self.assertNotEqual(local, public)
        for port in (local, public):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((lp.LOOPBACK, port))   # дверь номера НЕ удерживает

    def test_eight_ports_from_the_real_OS_are_all_distinct(self):
        ports = lp.free_ports(8)
        self.assertEqual(len(ports), 8)
        self.assertEqual(len(set(ports)), 8, ports)

    def test_an_OS_that_reuses_a_closed_number_still_gets_distinct_ports(self):
        """РАЗЛИЧАЮЩАЯ сцена: держим одновременно ⇒ разные; по очереди ⇒ дубль."""
        os_ = _ReusingOS()
        ports = lp.free_ports(3, bind=os_.bind)
        self.assertEqual(ports, [50000, 50001, 50002])
        self.assertEqual(os_.calls, 3)
        # и звено, на котором сцена различает: к моменту ПОСЛЕДНЕЙ пробы предыдущие
        # сокеты были ещё ЖИВЫ — иначе ОС вернула бы 50000 трижды
        self.assertEqual(len(os_.made), 3)

    def test_all_sockets_are_released_after_the_call(self):
        os_ = _ReusingOS()
        lp.free_ports(3, bind=os_.bind)
        self.assertTrue(all(s.closed for s in os_.made),
                        "дверь обязана отпустить номера — иначе сцена свяжет занятый порт")

    def test_single_port_goes_through_the_same_door(self):
        os_ = _ReusingOS()
        port = lp.free_port(bind=os_.bind)
        self.assertEqual(port, 50000)
        self.assertEqual(os_.calls, 1)
        self.assertTrue(os_.made[0].closed)

    def test_free_port_has_NO_second_copy_of_the_rule(self):
        """Мутант M4 (своя копия правила в `free_port`) ПЕРЕЖИЛ исходную батарею.

        И пережил по делу: при ``count=1`` у копии НЕТ наблюдаемой разницы в исходе,
        поэтому поведенческой сценой её не отличить вовсе. Претензия «правило в одной
        копии» структурная — и меряется она разбором, а не подстрокой (тот же порядок,
        что у `_injected_clock` и `test_delivery_bytes_pin`).
        """
        import ast
        tree = ast.parse(Path(lp.__file__).read_text(encoding="utf-8"))
        bodies = {node.name: node for node in ast.walk(tree)
                   if isinstance(node, ast.FunctionDef)}
        self.assertIn("free_port", bodies)
        called = {n.func.id for n in ast.walk(bodies["free_port"])
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        attrs = {n.func.attr for n in ast.walk(bodies["free_port"])
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertIn("free_ports", called,
                       "free_port обязан идти ЧЕРЕЗ free_ports, а не измерять сам")
        self.assertNotIn("getsockname", attrs,
                          "free_port сам номер НЕ читает — это вторая копия правила")
        self.assertNotIn("bind", called | attrs,
                          "free_port сам к ОС НЕ ходит — дверь одна")


class TheThirdOutcomeIsLoud(unittest.TestCase):

    def test_a_duplicate_from_the_door_is_a_named_refusal_not_a_silent_pair(self):
        with self.assertRaises(lp.PortsNotMeasured) as caught:
            lp.free_ports(2, bind=_StubbornOS(50000).bind)
        said = str(caught.exception)
        self.assertIn("50000", said, said)
        self.assertIn("НЕ ОБЕСПЕЧЕНА", said, said)

    def test_a_duplicate_is_not_reported_as_a_test_skip_or_an_assertion(self):
        """Скип и `assert` здесь были бы ровно подменой «не измерено» на «прошло»."""
        try:
            lp.free_ports(2, bind=_StubbornOS().bind)
        except lp.PortsNotMeasured:
            pass
        except BaseException as exc:            # noqa: BLE001 — предмет проверки
            self.fail(f"ожидался PortsNotMeasured, пришло {type(exc).__name__}: {exc}")
        else:
            self.fail("дубль прошёл молча")

    def test_a_nonpositive_count_refuses_instead_of_returning_an_empty_list(self):
        for bad in (0, -1):
            with self.assertRaises(lp.PortsNotMeasured, msg=repr(bad)):
                lp.free_ports(bad)

    def test_a_refused_bind_closes_the_socket_it_opened(self):
        """Мутант M6 (`except OSError: raise` без закрытия) ПЕРЕЖИЛ первую редакцию.

        Прежний контроль закрывал сокет САМ, внутри своего пенька, и проверял потом
        свою же работу — то есть сверял константу с самой собой. Настоящая дверь
        `_bind_loopback` открывает сокет НЕ через вход `bind=`, поэтому сцена подменяет
        фабрику сокетов и даёт `bind()` отказать по-настоящему (негодный адрес).
        """
        made: list[socket.socket] = []
        real = socket.socket

        def spy(*a, **k):
            sock = real(*a, **k)
            made.append(sock)
            return sock

        with mock.patch.object(lp.socket, "socket", spy):
            with self.assertRaises(OSError):
                lp._bind_loopback(host="300.300.300.300")
        self.assertEqual(len(made), 1, "сцена не дошла до настоящей двери")
        self.assertEqual(made[0].fileno(), -1,
                          "сокет УТЁК: отказавший bind обязан закрыть то, что открыл")


class TheRealDoorIsTheOneTheServerUses(unittest.TestCase):

    def test_bind_loopback_returns_an_OPEN_socket_on_the_loopback_family(self):
        sock = lp._bind_loopback()
        try:
            self.assertEqual(sock.family, socket.AF_INET)
            self.assertEqual(sock.getsockname()[0], lp.LOOPBACK)
            self.assertNotEqual(sock.fileno(), -1, "сокет обязан быть ОТКРЫТ")
        finally:
            sock.close()


if __name__ == "__main__":
    unittest.main()
