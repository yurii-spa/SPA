"""`RETIRED_LABELS` не спорит с манифестом: «похоронен» в одном месте и `active` в другом — дефект.

Тревога после перезагрузки 15.10 (карточка `inbox-arb-razobrat-trevogu-telegram-posle-pere`):
три WARNING `retired_but_loaded — … (owner: launchctl bootout …)` про `digest_weekly`,
`tier1_digest`, `weekly_backup`. Разбор истории: вывод own-21 (15.07) ОТМЕНЁН более поздним
решением владельца 2026-08-08 («четыре — ставить», own-31, коммит 07f15532b) — агенты прошли
гейт и загружены, манифест `intent: active`. Устарела константа, а не флот: пульс советовал
выгрузить то, что владелец велел ставить, а weekly_backup — единственный носитель
append-only ledgers в резерве (REVIEW_1 #12).

Положительный контроль: на origin 8f913113 тест красный (три метки в обоих местах с разным
ответом). Обратный: настоящий retired-but-loaded (метка retired и в константе, и без записи
`active` в манифесте) по-прежнему WARNING — сторож не стал тише на новом случае.
"""
from __future__ import annotations

import json
import plistlib
from pathlib import Path

from spa_core.monitoring import agent_health_monitor as ahm

_ROOT = Path(__file__).resolve().parents[2]


def _manifest_intents() -> dict:
    doc = json.loads((_ROOT / "architecture" / "manifest.json").read_text(encoding="utf-8"))
    return {a["label"]: a.get("intent") for a in doc["agents"] if isinstance(a, dict)}


def test_no_retired_label_is_active_in_the_manifest():
    intents = _manifest_intents()
    clash = sorted(l for l in ahm.RETIRED_LABELS if intents.get(l) == "active")
    assert clash == [], (
        f"RETIRED_LABELS и architecture/manifest.json спорят о судьбе агентов: {clash}. "
        "Сверить с последним решением владельца и поправить ту запись, что устарела")


def test_owner_reinstated_agents_are_not_retired():
    for label in ("com.spa.digest_weekly", "com.spa.tier1_digest", "com.spa.weekly_backup"):
        assert label not in ahm.RETIRED_LABELS, label


def test_installer_declares_the_reinstated_agents():
    text = (_ROOT / "scripts" / "install_all_agents.sh").read_text(encoding="utf-8")
    for label in ("com.spa.digest_weekly", "com.spa.tier1_digest", "com.spa.weekly_backup"):
        assert f'"$REPO/scripts/{label}.plist" \\\n    "{label}"' in text, label


def test_a_new_retired_but_loaded_agent_still_warns(tmp_path):
    label = "com.spa.checkpoint-7day"          # всё ещё retired: и в константе, и в манифесте
    assert label in ahm.RETIRED_LABELS
    la = tmp_path / "LaunchAgents"
    la.mkdir()
    with open(la / f"{label}.plist", "wb") as fh:
        plistlib.dump({"Label": label, "StartCalendarInterval": {"Month": 6, "Day": 19}}, fh)
    data = tmp_path / "data"
    data.mkdir()
    rep = ahm.AgentHealthMonitor(data_dir=data, launch_agents_dir=la,
                                 launchctl_output=f"-\t0\t{label}\n",
                                 launchctl_disabled_output="").collect()
    row = next(a for a in rep["agents"] if a["label"] == label)
    assert row["status"] == ahm.WARNING
    assert row["issue"].startswith("retired_but_loaded")
