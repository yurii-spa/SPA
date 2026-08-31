"""Отложенный агент не воскресает штатной переустановкой флота.

Замер 31.08. Вечером трое агентов были отложены в карантин (плюс трое из первой
партии), реестр — `attic/agents/QUARANTINE.json`. Проверка чётности флота показала
семь «объявлен, но не работает», и пятеро из них — именно отложенные: установщик о
реестре не знал ВОВСЕ и ставил их явными строками.

`bash scripts/install_all_agents.sh` документирован в CLAUDE.md как штатный способ
переустановки. То есть одна обычная команда отменяла бы карантин молча — и вместе с ним
весь замер «кто закричит», ради которого агентов и отложили (вердикт — 12.09).

Тест гоняет НАСТОЯЩИЙ установщик с подменёнными путями и заглушкой launchctl: копия
его логики проверяла бы мою выемку, а не поведение.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_INSTALLER = _ROOT / "scripts" / "install_all_agents.sh"
_VICTIM = "com.spa.dfb_capture"     # реально отложен 30.08


def _stub_launchctl(bin_dir: Path):
    stub = bin_dir / "launchctl"
    stub.write_text("#!/bin/bash\nexit 0\n")
    stub.chmod(0o755)


def _run(repo: Path, quarantined):
    """Запускает установщик в песочнице. Возвращает (код, вывод)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        launchd, binz = tmp / "LaunchAgents", tmp / "bin"
        launchd.mkdir(); binz.mkdir()
        _stub_launchctl(binz)
        if quarantined is not None:
            reg = repo / "attic" / "agents" / "QUARANTINE.json"
            reg.parent.mkdir(parents=True, exist_ok=True)
            reg.write_text(quarantined if isinstance(quarantined, str)
                           else json.dumps({"quarantined": [{"label": l} for l in quarantined]}))
        env = dict(os.environ)
        env.update({"SPA_REPO": str(repo), "SPA_LAUNCHD_DIR": str(launchd),
                    "PATH": f"{binz}:{env['PATH']}", "HOME": str(tmp)})
        p = subprocess.run(["bash", str(_INSTALLER)], capture_output=True,
                           text=True, env=env, timeout=180)
        return p.returncode, p.stdout + p.stderr


def _sandbox_repo(tmp: Path) -> Path:
    """Копия репо только в том объёме, что нужен установщику: plist-файлы."""
    repo = tmp / "repo"
    for sub in ("scripts", "launchd"):
        (repo / sub).mkdir(parents=True, exist_ok=True)
        src = _ROOT / sub
        if src.is_dir():
            for f in src.glob("com.spa.*.plist"):
                (repo / sub / f.name).write_bytes(f.read_bytes())
    return repo


@unittest.skipUnless(_INSTALLER.is_file(), "установщика нет в этом дереве")
class TestInstallerRespectsQuarantine(unittest.TestCase):

    def test_quarantined_agent_is_not_installed(self):
        with tempfile.TemporaryDirectory() as t:
            repo = _sandbox_repo(Path(t))
            code, out = _run(repo, [_VICTIM])
        self.assertIn(_VICTIM, out, "агента вообще нет в установщике — тест бессмыслен")
        self.assertRegex(
            out, rf"\[SKIP\] {_VICTIM} — отложен в карантин",
            f"отложенный агент был бы установлен штатной переустановкой:\n{out[-1500:]}")

    def test_without_a_registry_nothing_is_skipped_for_quarantine(self):
        """Обратный контроль: нет реестра — обычная установка, никого не пропускаем."""
        with tempfile.TemporaryDirectory() as t:
            repo = _sandbox_repo(Path(t))
            code, out = _run(repo, None)
        self.assertNotIn("отложен в карантин", out,
                         "без реестра установщик всё равно кого-то пропустил")

    def test_unreadable_registry_refuses_instead_of_resurrecting(self):
        """Битый реестр ⇒ ОТКАЗ: не зная, кого нельзя ставить, ставить нельзя никого."""
        with tempfile.TemporaryDirectory() as t:
            repo = _sandbox_repo(Path(t))
            code, out = _run(repo, "{это не json")
        self.assertEqual(code, 2, f"установщик продолжил работу на битом реестре:\n{out[-800:]}")
        self.assertIn("ОТКАЗ", out)


if __name__ == "__main__":
    unittest.main()
