"""Копия каталога данных для одноразового стенда переписи — клоном APFS, где он есть (ADR-849 §3).

Зачем. Переписи моста (`judge_alone_price`, `adapter_repair_price` через карусель, `heir_all_rows_price`,
`run_identity_key_price`, `ledger_day_unit_census`) строят стенд — полную копию `data/` без `backups/` —
десятки раз за прогон decision_loop. Замер 28.10 на замороженном снимке прода: копия ≈ 0,55 ГБ, и копирование
— главная статья времени прогона (1,5–2,8 ч) и источник скачков занятого места на диске.

Что меняется. Ничего в СОДЕРЖИМОМ стенда: на macOS каждый элемент копируется `cp -c -p -R -L` — клон
copy-on-write (те же байты, те же времена и права, по символическим ссылкам — как `shutil.copytree` по
умолчанию), каждый стенд по-прежнему ОТДЕЛЬНАЯ копия, и запись в неё до источника не доходит. Где клона нет
(Linux/CI, другой том) или `cp` отказал — прежний цикл `copytree`/`copy2`, бит-в-бит как было.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable


def _python_copy(items: Iterable[Path], dest_data: Path) -> None:
    for item in items:
        dst = dest_data / item.name
        if item.is_dir():
            shutil.copytree(item, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dst)


def copy_data_tree(source: Path, dest_data: Path, exclude: Iterable[str] = ()) -> str:
    """Скопировать содержимое ``source`` в ``dest_data`` без имён из ``exclude``. Возврат — способ:
    ``"clone"`` или ``"copy"`` (для замера; на результат не влияет)."""
    source, dest_data = Path(source), Path(dest_data)
    dest_data.mkdir(parents=True, exist_ok=True)
    skip = set(exclude)
    items = [p for p in sorted(source.iterdir()) if p.name not in skip]
    if not items:
        return "copy"
    if sys.platform == "darwin":
        try:
            proc = subprocess.run(["/bin/cp", "-c", "-p", "-R", "-L", *map(str, items), str(dest_data) + "/"],
                                  capture_output=True, timeout=600)
            if proc.returncode == 0:
                return "clone"
        except (OSError, subprocess.SubprocessError):
            pass
    _python_copy(items, dest_data)  # прежний путь: докопирует/перезапишет поверх частичного клона
    return "copy"
