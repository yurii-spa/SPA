"""The ``tests/`` root's offline block must WRAP ``urlopen``, never assign it.

Incident (measured 2026-08-17, card
``inbox-storozh-telegram-dverei-vybivaet-storozh``)
---------------------------------------------------------------------------
``tests/conftest.py`` installed its blanket offline block with a plain
assignment (``_urllib_req.urlopen = _blocked_urlopen``).  That single line
removed BOTH guards the other root had installed; the file then re-installed
only :mod:`telegram_guard`, so :mod:`network_guard` was absent until the first
test's autouse fixture repaired it — and the repair was attributed to that
test.  Measured sequence, in the order a repo-root run loads the conftests::

    spa_core conftest: network_guard.install()   chain=2  network_guard -> urlopen
    spa_core conftest: telegram_guard.install()  chain=3  telegram_guard -> network_guard -> urlopen
    tests/conftest.py PLAIN ASSIGNMENT           chain=1  _blocked_urlopen
                                                 ng.is_installed=False  tg.is_installed=False
    tests/conftest.py telegram_guard.install()   chain=2  telegram_guard -> _blocked_urlopen
    first test, autouse repair                   chain=4  clobbers=[(first test, 'urlopen')]

and the end-of-run banner therefore said::

    ==================== network guard was RE-INSTALLED mid-run ====================
      missing[urlopen]  spa_core/tests/test_doc_drift.py::test_canonical_dr_doc_exists

on a file that never touches ``urlopen``.  Three innocent files wore that label
over this wave.

Which tests here are POSITIVE CONTROLS — measured red against the un-fixed
tree (``git stash`` of the fix), not assumed:

* :class:`TestNoGuardIsKnockedOutInACombinedRun` — runs a real two-root
  ``pytest`` in a subprocess and fails on the banner.  This is the reported
  symptom itself.
* :class:`TestTheOfflineBlockIsInstalledByWrapping` — AST ratchet: no plain
  assignment to ``urllib.request.urlopen`` anywhere in ``tests/conftest.py``.
  It is what stops the one-line regression from coming back quietly.

The remaining classes are regression pins for the new layer: they hold the
order-independence property in all six install orders, so the next layer added
to this chain cannot re-create the defect by being loaded first.

Hermetic where it can be: FRESH copies of all three modules (never the ones
``conftest`` installed), an inert transport, saved/restored wrappers, no repo
state, no network, no wall clock.  The subprocess control deliberately is not
hermetic — the defect only existed across two conftests.
"""
from __future__ import annotations

import ast
import importlib.util
import itertools
import os
import subprocess
import sys
import unittest
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent

_TG_URL = "https://api.telegram.org/bot123456:FAKE-TOKEN-NOT-REAL/sendMessage"
_LIVE_URL = "https://api.llama.fi/pools"
_LOCAL_URL = "http://127.0.0.1:8765/health"

_BANNER = "network guard was RE-INSTALLED mid-run"


def _load(name: str, filename: str):
    """A FRESH copy of a guard module — never the one conftest installed."""
    spec = importlib.util.spec_from_file_location(name, _HERE / filename)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)                 # type: ignore[union-attr]
    return mod


class _ThreeLayerSandbox(unittest.TestCase):
    """Fresh copies of all three layers over an inert transport, restored after."""

    def setUp(self):
        import socket

        self._socket = socket
        # Saved ONCE, here — never re-saved from inside a subTest loop.  Doing
        # that would capture the sandbox's own inert transport as "the real
        # one" and leak it into the rest of the run, which is precisely the
        # class of damage this file is about (measured: the leak made the
        # suite's own network guard report itself clobbered by these tests).
        self._saved_urlopen = urllib.request.urlopen
        self._saved_connect = socket.socket.connect
        self._saved_connect_ex = socket.socket.connect_ex
        self.delegated = []

        def _inert_urlopen(req, *args, **kwargs):
            self.delegated.append(req)
            return "REAL-RESPONSE"

        self._inert_urlopen = _inert_urlopen
        self._inert_connect = lambda s, addr: self.delegated.append(addr)
        self._fresh()

    def _fresh(self):
        """A clean slate: fresh module copies over the inert transport.

        Safe to call inside a ``subTest`` loop — it restores nothing, so the
        originals saved in :meth:`setUp` stay the originals.
        """
        self.ng = _load("spa_network_guard_ob_under_test", "network_guard.py")
        self.tg = _load("spa_telegram_guard_ob_under_test", "telegram_guard.py")
        self.ob = _load("spa_offline_block_under_test", "offline_block.py")
        self.delegated.clear()
        # Installed BEFORE any install() so the layers genuinely WRAP it.
        urllib.request.urlopen = self._inert_urlopen
        self._socket.socket.connect = self._inert_connect
        self._socket.socket.connect_ex = self._inert_connect

    def tearDown(self):
        urllib.request.urlopen = self._saved_urlopen
        self._socket.socket.connect = self._saved_connect
        self._socket.socket.connect_ex = self._saved_connect_ex

    # -- helpers ---------------------------------------------------------
    def _install(self, name):
        if name == "ng":
            self.ng.install()
        elif name == "tg":
            self.tg.install()
        elif name == "ob":
            self.ob.install(self.ng)
        else:  # pragma: no cover — typo guard
            raise AssertionError(name)

    def _chain_len(self):
        return len(self.ng.urlopen_chain())


class TestEveryInstallOrderLeavesEveryLayerReachable(_ThreeLayerSandbox):
    """No layer may depend on being installed first, last, or at all.

    The defect was exactly this dependency: the offline block worked only when
    it went in FIRST, and silently deleted whatever had gone in before it.
    """

    ORDERS = list(itertools.permutations(("ng", "tg", "ob")))

    def test_all_three_layers_are_present_in_every_order(self):
        for order in self.ORDERS:
            with self.subTest(order=order):
                self._fresh()
                for name in order:
                    self._install(name)
                self.assertTrue(
                    self.ng.is_installed(),
                    f"network guard knocked out by order {order}",
                )
                self.assertTrue(
                    self.tg.is_installed(),
                    f"telegram guard knocked out by order {order}",
                )
                self.assertTrue(
                    self.ob.is_installed(),
                    f"offline block knocked out by order {order}",
                )

    def test_each_door_catches_its_own_case_in_every_order(self):
        """With the conftests' final ``telegram_guard.install()`` applied.

        Both roots end their guard setup by (re-)installing the Telegram guard,
        because only the OUTERMOST layer sees a call first and therefore only
        then does ``api.telegram.org`` get the specific, token-redacting report
        instead of a generic refusal.  That is the contract asserted here.
        """
        for order in self.ORDERS:
            with self.subTest(order=order):
                self._fresh()
                for name in order:
                    self._install(name)
                self.tg.install()  # what both conftests do last
                self.assertTrue(self.tg.is_outermost())

                with self.assertRaises(self.tg.LiveTelegramSendAttempted):
                    urllib.request.urlopen(_TG_URL)
                self.assertEqual(
                    self.tg.attempts(),
                    ["https://api.telegram.org/bot<redacted>/sendMessage"],
                )

                self.ng.reset()
                with self.assertRaises(self.ng.LiveNetworkAccessAttempted):
                    urllib.request.urlopen(_LIVE_URL)
                self.assertEqual(
                    len(self.ng.attempts()),
                    1,
                    "the live-feed refusal never reached the network guard's "
                    f"ledger in order {order} — a layer above answered for it",
                )

                with self.assertRaises(self.ob.OfflineError):
                    urllib.request.urlopen(_LOCAL_URL)

                # Nothing reached the transport in any of the three cases.
                self.assertEqual(self.delegated, [])

    def test_re_installing_does_not_grow_the_chain(self):
        for order in self.ORDERS:
            with self.subTest(order=order):
                self._fresh()
                for name in order:
                    self._install(name)
                self.tg.install()
                settled = self._chain_len()
                for _ in range(5):
                    for name in order:
                        self._install(name)
                    self.tg.install()
                self.assertEqual(
                    self._chain_len(),
                    settled,
                    f"chain grew on re-install in order {order}",
                )


class TestTheOfflineBlockKeepsTheLedgerReachable(_ThreeLayerSandbox):
    """A block that answers for every URL makes the guard beneath it a fiction.

    Three tests assert on ``network_guard``'s ledger; if the offline block
    refused non-loopback addresses itself, that ledger would stay empty while
    the suite believed the guard was working — the fail-OPEN shape both guard
    modules exist to close.
    """

    def test_non_loopback_is_delegated_down_to_the_network_guard(self):
        self.ng.install()
        self.ob.install(self.ng)
        self.ng.reset()
        with self.assertRaises(self.ng.LiveNetworkAccessAttempted):
            urllib.request.urlopen(_LIVE_URL)
        self.assertEqual(len(self.ng.attempts()), 1)
        self.ng.reset()

    def test_loopback_is_refused_by_the_block_not_allowed_through(self):
        """The ``tests/`` root has refused local URLs since SPA-D003."""
        self.ng.install()
        self.ob.install(self.ng)
        with self.assertRaises(OSError):
            urllib.request.urlopen(_LOCAL_URL)
        self.assertEqual(self.delegated, [])

    def test_the_two_layers_agree_on_what_loopback_means(self):
        """The block asks the guard rather than re-deriving the rule."""
        for url, is_local in (
            ("http://127.0.0.1:8765/x", True),
            ("http://localhost/x", True),
            ("http://[::1]:9/x", True),
            ("file:///tmp/x", True),
            ("https://api.llama.fi/pools", False),
            ("https://api.telegram.org/bot1/sendMessage", False),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.ng.is_loopback_url(url), is_local)


class TestTheOfflineBlockIsInstalledByWrapping(unittest.TestCase):
    """POSITIVE CONTROL (red on the un-fixed tree): no plain assignment.

    ``tests/conftest.py`` line 58 was ``_urllib_req.urlopen = _blocked_urlopen``.
    A source-level ratchet, because the runtime consequence is only observable
    across two conftests and one full run — by which time the damage has
    already been repaired and mis-attributed.
    """

    CONFTESTS = (
        Path("tests/conftest.py"),
        Path("spa_core/tests/conftest.py"),
    )

    def test_no_conftest_assigns_urlopen_directly(self):
        offenders = []
        for rel in self.CONFTESTS:
            path = _REPO / rel
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                targets = []
                if isinstance(node, ast.Assign):
                    targets = list(node.targets)
                elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                    targets = [node.target]
                for tgt in targets:
                    if isinstance(tgt, ast.Attribute) and tgt.attr == "urlopen":
                        offenders.append(f"{rel}:{node.lineno}")
        self.assertEqual(
            offenders,
            [],
            "a conftest replaces urllib.request.urlopen by plain assignment "
            f"at {offenders} — that discards every layer already installed "
            "(network_guard AND telegram_guard). Wrap it instead: take the "
            "current callable, call it from inside your check, and publish it "
            "as __wrapped__ so the chain stays walkable. See "
            "spa_core/tests/offline_block.py.",
        )


class TestNoGuardIsKnockedOutInACombinedRun(unittest.TestCase):
    """POSITIVE CONTROL (red on the un-fixed tree): the reported symptom.

    Reproduced verbatim on the un-fixed tree with exactly these two files —
    one from each root — which is the smallest run that loads both conftests::

        ==================== network guard was RE-INSTALLED mid-run ====================
          missing[urlopen]  spa_core/tests/test_doc_drift.py::test_canonical_dr_doc_exists

    Not hermetic on purpose: the defect lived in the interaction between the
    two conftests and cannot be seen from inside a single process that has
    already been repaired.
    """

    #: One file from each root. Neither imports this module, so the child run
    #: cannot recurse into it.
    SLICE = (
        "spa_core/tests/test_doc_drift.py",
        "tests/test_adapter_registry.py",
    )

    def test_a_two_root_run_reports_no_clobber(self):
        env = dict(os.environ)
        # The parent's autouse isolation points this at a tmp dir; the child
        # must resolve data/ the way a normal run does.
        env.pop("SPA_DATA_DIR", None)
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", *self.SLICE, "-q", "-p", "no:randomly"],
            cwd=str(_REPO),
            env=env,
            capture_output=True,
            text=True,
            timeout=900,
        )
        output = proc.stdout + proc.stderr
        self.assertNotIn(
            _BANNER,
            output,
            "a guard was knocked out of the urlopen chain and re-installed "
            "mid-run — something replaced urllib.request.urlopen by plain "
            "assignment instead of wrapping it. Child run output:\n" + output,
        )
        self.assertEqual(
            proc.returncode,
            0,
            "the two-root control slice itself failed:\n" + output,
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
