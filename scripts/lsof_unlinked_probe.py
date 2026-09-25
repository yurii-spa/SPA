#!/usr/bin/env python3
"""Замер: как ВЫГЛЯДИТ отвязанный файл, открытый на запись, в выводе живого `lsof`.

Вопрос один и он про ОС, а не про наш код: `lsof -Ftnia` на macOS и на Linux
печатают поле `n` для файла, у которого больше нет имени, ПО-РАЗНОМУ. Пока это
не измерено, любая правка разбора есть догадка.

Прибор только ЧИТАЕТ: поднимает свой же дескриптор на отвязанный файл, зовёт
настоящий `lsof` и печатает сырой вывод дословно. Ничего не чинит и ничего не
утверждает о нашем разборе.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
import tempfile


def main() -> int:
    with tempfile.NamedTemporaryFile("w", suffix=".gone", delete=False) as fh:
        path = fh.name
    doomed = open(path, "w")
    os.unlink(path)
    doomed.write("x")
    doomed.flush()
    ino = os.fstat(doomed.fileno()).st_ino

    alive = tempfile.NamedTemporaryFile("w", suffix=".alive", delete=False)
    alive.write("x")
    alive.flush()

    print(f"[ОС] {platform.system()} {platform.release()}")
    print(f"[ОТВЯЗАННЫЙ] исходный путь {path!r} inode={ino}")
    print(f"[ЖИВОЙ]      путь {alive.name!r} inode={os.fstat(alive.fileno()).st_ino}")
    try:
        ver = subprocess.run(["lsof", "-v"], capture_output=True, text=True, timeout=20)
        print("[lsof -v]\n" + (ver.stderr or ver.stdout).strip())
    except Exception as exc:                      # noqa: BLE001 — прибор, не рантайм
        print(f"[lsof -v] НЕ ИЗМЕРЕНО: {exc}")

    cmd = ["lsof", "-a", "-p", str(os.getpid()), "-d", "0-255", "-Ftnia"]
    print(f"[КОМАНДА] {' '.join(cmd)}")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception as exc:                      # noqa: BLE001
        print(f"[СЫРОЙ ВЫВОД] НЕ ИЗМЕРЕНО: {exc}")
        return 2
    print(f"[КОД ВОЗВРАТА] {res.returncode}")
    print("[СЫРОЙ ВЫВОД НАЧАЛО]")
    sys.stdout.write(res.stdout)
    print("[СЫРОЙ ВЫВОД КОНЕЦ]")
    if res.stderr.strip():
        print("[STDERR]\n" + res.stderr.strip())

    doomed.close()
    alive.close()
    os.unlink(alive.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
