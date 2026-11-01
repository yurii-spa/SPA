"""S2 (ARB 01.11 п. 2) — репетиция действий владельца на ПОЛЬЗОВАТЕЛЬСКОМ корне (без root, без launchd).

Последовательность ровно та, что в ``OWNER_REQUEST.md``, кроме двух подмен, названных явно:
  * корень — каталог пользователя (не root:wheel); права «только чтение» релизов имитируются ``chmod -R a-w``;
  * установщик идёт режимом ``--self-test-root`` (те же функции материализации и записи runtime.json), канарейку
    запускает этот скрипт (``python3 -I`` + ``main`` установленного лаунчера), а не launchd.
Шаги: пакет из названного коммита (сверка с отчётом и пином) → снимок исходной конфигурации → A и B
материализованы и доказаны → канарейка при одобренном B → откат одобрением A → канарейка при A → восстановление
исходной конфигурации из снимка и сверка. ACTIVE — штатный замер по процессу (``release_state.active_processes``).

    python -m spa_core.tests.s2_canary_rehearsal --base <новый каталог> --bundle-sha <40 hex> --a <sha A> --b <sha B>
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from spa_core.studio_os import release_state as RS
from spa_core.studio_os import trusted_install_bundle as TB

REPO = Path(__file__).resolve().parents[2]
REAL_ROOT = Path("/Library/Application Support/StudioOS")
APP_PY = str(Path.home() / "miniconda3" / "bin" / "python3.13")
BOOT = (
    "import importlib.util, sys\n"
    "spec = importlib.util.spec_from_file_location('installed_release_launcher', sys.argv[1])\n"
    "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
    "r = m.main(sys.argv[4], root=sys.argv[2], active_path=sys.argv[3])\n"
    "if r and r[0] == 'FAIL_CLOSED':\n"
    "    sys.stderr.write('trusted-launcher FAIL_CLOSED: %s\\n' % r[1]); sys.exit(3)\n"
)


def _prod_footprint():
    p = Path.home() / "Documents" / "SPA_Claude"
    st = subprocess.run(["git", "-C", str(p), "status", "--short", "--", "data/"], capture_output=True, text=True).stdout
    return {"prod_data_status_sha": __import__("hashlib").sha256(st.encode()).hexdigest(),
            "real_root_config": {n: (REAL_ROOT / n).read_text() if (REAL_ROOT / n).is_file() else None
                                 for n in TB.CONFIG_FILES}}


def _canary(root: Path, launcher: Path, base: Path, label: str, log: list) -> dict:
    out, err = base / f"canary_{label}.out", base / f"canary_{label}.err"
    env = {k: v for k, v in os.environ.items() if k != "SPA_DATA_DIR"}     # как в plist: SPA_DATA_DIR не задаётся
    with open(out, "w") as fo, open(err, "w") as fe:
        p = subprocess.Popen(["/usr/bin/python3", "-I", "-c", BOOT, str(launcher), str(root), str(base / "active.json"),
                              "canary"], stdout=fo, stderr=fe, env=env, cwd="/", start_new_session=True)
        seen, t0 = [], time.time()
        while p.poll() is None and time.time() - t0 < 600:
            procs = RS.active_processes((root / "releases").resolve())
            if procs:
                seen.append(procs)
            time.sleep(0.2)
        rc = p.wait(timeout=60)
    rec = {"step": f"canary_{label}", "pid": p.pid, "rc": rc, "measured": seen[0] if seen else [],
           "samples": len(seen), "stderr_tail": err.read_text()[-300:], "active_record":
               json.loads((base / "active.json").read_text()) if (base / "active.json").exists() else None,
           "pycache_in_releases": sorted(str(x) for x in (root / "releases").rglob("__pycache__"))[:3]}
    log.append(rec)
    return rec


def run(base: Path, bundle_sha: str, sha_a: str, sha_b: str) -> dict:
    base = Path(base).resolve()
    base.mkdir(parents=True)
    log: list = []
    before = _prod_footprint()
    pin = json.loads((REPO / TB.PIN_PATH).read_text())                   # «значения из отчёта ARB» для репетиции
    expect = {p: v["sha256"] for p, v in pin["files"].items()}
    stage = base / "bundle"
    man = TB.stage(str(REPO), bundle_sha, str(stage), expect)
    log.append({"step": "stage", "sha": bundle_sha, "files": {p: v["sha256"][:12] for p, v in man["files"].items()}})
    root = base / "StudioOS_user_root"
    for d in TB.LISTED_DIRS:
        (root / d).mkdir(parents=True)
    for n in TB.CONFIG_FILES:                                            # исходная конфигурация = копия настоящей
        if (REAL_ROOT / n).is_file():
            shutil.copyfile(REAL_ROOT / n, root / n)
    TB.snapshot(str(root), str(base / "snapshot_before"))
    log.append({"step": "snapshot_before", "snapshot_sha256": TB.snapshot_digest(str(base / "snapshot_before")),
                "verify": TB.verify(str(root), str(base / "snapshot_before"))})
    inst = stage / "scripts" / "install_trusted_bootstrap.sh"
    lnch = stage / "spa_core" / "studio_os" / "release_launcher.py"
    lsha = expect["spa_core/studio_os/release_launcher.py"]

    def install(sha):
        r = subprocess.run(["bash", str(inst), "--self-test-root", str(root), "--launcher", str(lnch),
                            "--launcher-sha256", lsha, "--repo", str(Path.home() / "Documents" / "SPA_Claude"),
                            "--approved", sha, "--self-test-app-python", APP_PY], capture_output=True, text=True)
        log.append({"step": f"install_{sha[:9]}", "rc": r.returncode, "out": r.stdout[-300:], "err": r.stderr[-300:]})
        if r.returncode != 0:
            raise TB.Refused(f"self-test install {sha[:9]} отказал: {r.stderr[-300:]}")
        rel = root / "releases" / sha
        subprocess.run(["chmod", "-R", "a-w", str(rel)], check=True)     # имитация root:wheel a-w (остаток R4)

    install(sha_a)
    install(sha_b)
    installed = root / "bin" / f"release_launcher-{lsha}.py"
    b = _canary(root, installed, base, "B", log)
    install(sha_a)                                                       # откат: одобрение A (каталог A переиспользуется)
    a = _canary(root, installed, base, "A_after_rollback", log)
    recorded = log[1]["snapshot_sha256"]                                  # записан «владельцем» при создании
    diffs = TB.restore(str(root), str(base / "snapshot_before"), recorded)
    log.append({"step": "restore_config", "file_diffs_after_restore": diffs,
                "verify_after": TB.verify(str(root), str(base / "snapshot_before"), recorded)})
    after = _prod_footprint()
    verdict = {
        "B_measured": [x["sha"] for x in b["measured"]] == [sha_b] and b["rc"] in (0, 1),
        "A_measured_after_rollback": [x["sha"] for x in a["measured"]] == [sha_a] and a["rc"] in (0, 1),
        "no_bytecode_in_releases": not b["pycache_in_releases"] and not a["pycache_in_releases"],
        "config_restored": diffs == [],
        "prod_unchanged": before == after,
    }
    rec = {"bundle_sha": bundle_sha, "A": sha_a, "B": sha_b, "verdict": verdict, "ok": all(verdict.values()), "log": log}
    (base / "rehearsal_record.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False, default=str))
    return rec


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    for k in ("--base", "--bundle-sha", "--a", "--b"):
        ap.add_argument(k, required=True)
    ns = ap.parse_args()
    if Path(ns.base).exists():
        sys.exit("--base уже существует")
    r = run(Path(ns.base), ns.bundle_sha, ns.a, ns.b)
    print(json.dumps({"ok": r["ok"], "verdict": r["verdict"]}, indent=1))
    sys.exit(0 if r["ok"] else 1)
