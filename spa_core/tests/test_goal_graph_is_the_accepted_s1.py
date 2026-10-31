"""S2 T05: модуль допуска S1 в дереве S2 — ровно принятый S1, а не его копия с правками.

ADR-880: S1 принят на ``a172b79d4`` (ветка ``autonomy/s1``). Истории веток ``autonomy/s1`` и этой ветки не имеют
общего предка, поэтому модуль перенесён файлом; этот тест держит его побайтно равным принятому blob. Изменить
допуск S1 из S2 нельзя — любая правка краснит тест и требует решения ARB по S1, а не по S2."""
import hashlib
from pathlib import Path

ACCEPTED_S1_SHA = "a172b79d4de6cf45c78bc1118009518995720381"
ACCEPTED_BLOB = "7ca9be78185ac815b75c82b9faae7744d5f06918"   # git rev-parse a172b79d4:spa_core/studio_os/goal_graph.py


def test_goal_graph_is_byte_identical_to_the_accepted_s1_blob():
    data = (Path(__file__).resolve().parents[1] / "studio_os" / "goal_graph.py").read_bytes()
    assert hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest() == ACCEPTED_BLOB
