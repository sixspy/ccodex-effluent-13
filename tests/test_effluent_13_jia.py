"""排污寅第13槽 · 红测甲：帽值不符仍出正式封批快照。

口径（甲路径）：采样读数与许可帽不符 → 封批整笔回退，
正式快照（discharge_seals）零增、封批升代拒收。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import app
from db import init_db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "effluent13_jia.db")
    init_db()
    c = TestClient(app)
    tok = c.post(
        "/api/login", json={"username": "admin", "password": "admin123"}
    ).json()["token"]
    c.headers.update({"Authorization": "Bearer " + tok})
    return c


def _sample_id(client: TestClient, code: str = "SM-M13") -> int:
    rows = client.get("/api/samples").json()["items"]
    return next(s["id"] for s in rows if s["sample_code"] == code)


def _seal_count(client: TestClient, sample_id: int) -> int:
    detail = client.get(f"/api/samples/{sample_id}").json()
    return len(detail["discharge_seals"])


def test_jia_cap_mismatch_blocks_official_seal(client: TestClient) -> None:
    """SM-M13 预置夹具：COD=58 > 许可帽 cod_cap=50。"""
    sample_id = _sample_id(client)
    before = _seal_count(client, sample_id)
    sample_before = client.get(f"/api/samples/{sample_id}").json()["sample"]
    assert sample_before["status"] == "已裁定"
    assert sample_before["generation"] == 1

    # 夹带手填快照同样不得放行（快照读数仍超帽）
    resp = client.post(
        "/api/seals",
        json={"sample_id": sample_id, "snapshot": "COD=58.0 NH3-N=4.10 TP=0.330"},
    )

    assert resp.status_code == 400, resp.text
    assert "帽" in resp.json()["detail"]
    # 正式快照零增
    assert _seal_count(client, sample_id) == before
    # 整笔回退：状态与代均未变
    sample_after = client.get(f"/api/samples/{sample_id}").json()["sample"]
    assert sample_after["status"] == "已裁定"
    assert sample_after["generation"] == 1
    # 封批列表中不得出现 SM-M13 的正式封批
    seals = client.get("/api/seals").json()["items"]
    assert all(s["sample_code"] != "SM-M13" for s in seals)


def test_jia_cap_match_still_seals(client: TestClient) -> None:
    """对照：帽内采样（SM-OF-N3-A-001 COD=24 < 帽30）封批升代正常。"""
    rows = client.get("/api/samples").json()["items"]
    ok_id = next(s["id"] for s in rows if s["sample_code"] == "SM-OF-N3-A-001")
    resp = client.post("/api/seals", json={"sample_id": ok_id})
    assert resp.status_code == 200, resp.text
    assert resp.json()["generation"] == 2
    assert _seal_count(client, ok_id) == 1
