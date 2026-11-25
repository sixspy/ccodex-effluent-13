"""排污寅第13槽 · 红测争：两路会话同批抢封批。

口径：同批封批须抢批锁（sample:{id}），后到只记争用痕；
败方零正式快照、零代推进。并发脚本：scripts/ping_cap_seal_lock.py
"""
from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from app import app
from db import connect, init_db


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr("db.DB_PATH", tmp_path / "effluent13_zheng.db")
    init_db()
    with connect() as conn:
        m13 = conn.execute(
            "SELECT id FROM sample_batches WHERE sample_code=?", ("SM-M13",)
        ).fetchone()["id"]
        # 帽内批（COD 24 < 帽 30）：并发封批能走到锁争用，不被帽值闸门提前拦下
        ok = conn.execute(
            "SELECT id FROM sample_batches WHERE sample_code=?",
            ("SM-OF-N3-A-001",),
        ).fetchone()["id"]
    return {"m13": m13, "ok": ok}


def _client() -> TestClient:
    c = TestClient(app)
    tok = c.post(
        "/api/login", json={"username": "admin", "password": "admin123"}
    ).json()["token"]
    c.headers.update({"Authorization": "Bearer " + tok})
    return c


def test_zheng_concurrent_seal_single_winner(env) -> None:
    """两路会话并发对同一帽内批封批：恰一成一败，败方 409 且零快照零代推进。"""
    sample_id = env["ok"]
    barrier = threading.Barrier(2)
    results: list[dict] = []
    results_lock = threading.Lock()

    def worker() -> None:
        client = _client()
        barrier.wait()  # 两路同时发抢，最大化锁争用
        r = client.post("/api/seals", json={"sample_id": sample_id})
        with results_lock:
            results.append({"status": r.status_code, "body": r.json() if r.content else {}})

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start(); t2.start()
    t1.join(timeout=30); t2.join(timeout=30)

    assert len(results) == 2
    statuses = sorted(r["status"] for r in results)
    assert statuses == [200, 409], statuses
    winners = [r for r in results if r["status"] == 200]
    losers = [r for r in results if r["status"] == 409]
    assert len(winners) == 1
    assert len(losers) == 1
    # 败方无论卡在锁占用还是后到封批冲突，均属争用失败且留痕
    assert "争用" in losers[0]["body"]["detail"]

    with connect() as conn:
        seal_rows = conn.execute(
            "SELECT COUNT(*) c FROM discharge_seals WHERE sample_id=?", (sample_id,)
        ).fetchone()["c"]
        gen = conn.execute(
            "SELECT generation, status FROM sample_batches WHERE id=?", (sample_id,)
        ).fetchone()
        contention = conn.execute(
            "SELECT COUNT(*) c FROM contention_log WHERE lock_key=?",
            (f"sample:{sample_id}",),
        ).fetchone()["c"]

    # 败方零正式快照：恰一笔
    assert seal_rows == 1
    # 后到只记争用痕
    assert contention >= 1
    # 代恰推进一次
    assert gen["generation"] == 2
    assert gen["status"] == "已封批"


def test_zheng_lock_held_second_seal_rejected(env) -> None:
    """确定性争用：批锁被持久持有时，第二路封批 409 且留争用痕、零快照。"""
    sample_id = env["ok"]
    lock_key = f"sample:{sample_id}"
    holder = _client()
    take = holder.post(f"/api/locks/acquire?lock_key={lock_key}")
    assert take.status_code == 200

    rival = _client()
    blocked = rival.post("/api/seals", json={"sample_id": sample_id})
    assert blocked.status_code == 409, blocked.text

    with connect() as conn:
        seals = conn.execute(
            "SELECT COUNT(*) c FROM discharge_seals WHERE sample_id=?", (sample_id,)
        ).fetchone()["c"]
        trace = conn.execute(
            "SELECT actor, action FROM contention_log WHERE lock_key=? ORDER BY id DESC",
            (lock_key,),
        ).fetchall()
    assert seals == 0  # 败方零快照
    assert any(dict(r)["action"] == "争用失败" for r in trace)

    released = holder.post(f"/api/locks/release?lock_key={lock_key}")
    assert released.status_code == 200
    # 释放后接棒可封
    after = holder.post("/api/seals", json={"sample_id": sample_id})
    assert after.status_code == 200


def test_zheng_m13_cap_gate_before_lock_race(env) -> None:
    """SM-M13 帽值不符：两路并发也只能各拿帽值红灯（400），无一正式快照。"""
    sample_id = env["m13"]
    barrier = threading.Barrier(2)
    results: list[dict] = []
    results_lock = threading.Lock()

    def worker() -> None:
        client = _client()
        barrier.wait()
        r = client.post("/api/seals", json={"sample_id": sample_id})
        with results_lock:
            results.append(r.status_code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert sorted(results) == [400, 400]
    with connect() as conn:
        seals = conn.execute(
            "SELECT COUNT(*) c FROM discharge_seals WHERE sample_id=?", (sample_id,)
        ).fetchone()["c"]
        drafts = conn.execute(
            "SELECT COUNT(*) c, SUM(CASE WHEN status='帽值不符作废' THEN 1 ELSE 0 END) v "
            "FROM seal_shadow_drafts WHERE sample_id=?",
            (sample_id,),
        ).fetchone()
    assert seals == 0
    assert drafts["c"] == 2 and drafts["v"] == 2
