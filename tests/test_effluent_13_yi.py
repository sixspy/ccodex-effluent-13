"""排污寅第13槽 · 红测乙：对账把影子草稿当齐套。

口径（乙路径）：帽值不符只落影子快照草稿，对账复核通过后
才原子升正正式区（零改），不符草稿作废；对账齐套不得跳过帽值比对。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import app
from db import init_db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "effluent13_yi.db")
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


def test_yi_reconcile_flags_cap_mismatch_not_balanced(client: TestClient) -> None:
    """SM-M13（COD 58 > 帽 50）在对账页必须显式帽值不符，不得标齐套。"""
    data = client.get("/api/reconcile/DP-2026-E01").json()

    m13 = next(s for s in data["samples"] if s["sample_code"] == "SM-M13")
    # 每条采样必须带帽值比对明细，对账不得跳过帽值比对
    assert m13["matched"] is False
    cap_rows = {r["metric"]: r for r in m13["cap_checks"]}
    assert cap_rows["COD"]["over"] is True
    assert cap_rows["COD"]["measured"] == 58.0
    assert cap_rows["COD"]["cap"] == 50.0
    # 整许可不得齐套、不得出证明
    assert data["balanced"] is False
    assert data["proof_ready"] is False


def test_yi_shadow_draft_never_counted_as_balanced(client: TestClient) -> None:
    """帽值不符的封批请求只落影子草稿，影子草稿不得被对账当齐套，
    且不得原子升正为正式封批。"""
    sample_id = _sample_id(client)

    resp = client.post("/api/seals", json={"sample_id": sample_id})
    # 乙路径：不产生正式封批（请求被帽值闸门拒绝，仅留影子痕迹）
    assert resp.status_code == 400
    detail = client.get(f"/api/samples/{sample_id}").json()
    assert len(detail["discharge_seals"]) == 0

    # 影子快照草稿可查，且标注帽值不符、未转正
    drafts = client.get("/api/seal-drafts").json()["items"]
    mine = [d for d in drafts if d["sample_code"] == "SM-M13"]
    assert mine, "帽值不符封批须落影子快照草稿"
    draft = mine[-1]
    assert draft["zone"] == "shadow"
    assert draft["cap_passed"] is False
    assert draft["status"] == "帽值不符作废"

    # 对账不得把影子草稿算进齐套/封批数
    recon = client.get("/api/reconcile/DP-2026-E01").json()
    assert recon["balanced"] is False
    official_seals = [
        s for s in client.get("/api/seals").json()["items"]
        if s["sample_code"] == "SM-M13"
    ]
    assert official_seals == []


def test_yi_compliant_draft_promotes_atomically(client: TestClient) -> None:
    """对照：帽内采样草稿复核通过后原子升正，正式区零改语义
    （升正前后快照字符串逐字一致，且只升正一次）。"""
    rows = client.get("/api/samples").json()["items"]
    ok_id = next(s["id"] for s in rows if s["sample_code"] == "SM-OF-N3-A-001")

    resp = client.post("/api/seals", json={"sample_id": ok_id})
    assert resp.status_code == 200
    seal = resp.json()

    detail = client.get(f"/api/samples/{ok_id}").json()
    assert len(detail["discharge_seals"]) == 1
    official = detail["discharge_seals"][0]
    assert official["snapshot"] == seal["snapshot"]

    # 重复封批同一代不得再产生正式快照（后到按争用 409 处理）
    again = client.post("/api/seals", json={"sample_id": ok_id})
    assert again.status_code == 409
    detail2 = client.get(f"/api/samples/{ok_id}").json()
    assert len(detail2["discharge_seals"]) == 1
