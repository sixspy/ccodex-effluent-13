"""排放批争用锁。"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from db import connect, now_iso, write_audit

router = APIRouter(tags=["locks"])

# 后到会话在批锁上的等待窗口：窗口内锁释放则接棒，超时判争用失败只记痕
LOCK_WAIT_SECONDS = 3.0
LOCK_POLL_INTERVAL = 0.05


def require_lock(conn, lock_key: str, holder: str, persistent: bool = False) -> None:
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    flag = 1 if persistent else 0
    while True:
        row = conn.execute(
            "SELECT holder, persistent FROM effluent_locks WHERE lock_key=?",
            (lock_key,),
        ).fetchone()
        if row and row["holder"] == holder and not (row["persistent"] and not persistent):
            # 同持有人且非“持久锁被普通请求复用”：放行；acquire 可升级为持久
            if persistent and not row["persistent"]:
                conn.execute(
                    "UPDATE effluent_locks SET persistent=1 WHERE lock_key=?",
                    (lock_key,),
                )
            return
        if not row:
            # 立即尝试占位；并发下若被他路先插（唯一键冲突），转入等待重判
            try:
                conn.execute(
                    """INSERT INTO effluent_locks(lock_key,holder,acquired_at,persistent)
                       VALUES (?,?,?,?)""",
                    (lock_key, holder, now_iso(), flag),
                )
                return
            except Exception:
                conn.rollback()
                row = conn.execute(
                    "SELECT holder FROM effluent_locks WHERE lock_key=?", (lock_key,)
                ).fetchone()
        if time.monotonic() >= deadline:
            owner = row["holder"] if row else "他路"
            conn.execute(
                """INSERT INTO contention_log(lock_key,actor,action,detail,created_at)
                   VALUES (?,?,?,?,?)""",
                (lock_key, holder, "争用失败", f"持有人={owner}", now_iso()),
            )
            conn.commit()
            raise HTTPException(409, f"锁被占用：{lock_key} 持有人 {owner}")
        time.sleep(LOCK_POLL_INTERVAL)


def release(conn, lock_key: str, holder: str) -> None:
    """只释放请求内自动锁；手动持久锁须经 /api/locks/release 显式释放。"""
    conn.execute(
        "DELETE FROM effluent_locks WHERE lock_key=? AND holder=? AND persistent=0",
        (lock_key, holder),
    )


def record_contention(conn, lock_key: str, actor: str, detail: str) -> None:
    """后到会话只记争用痕，不产生任何正式写入。"""
    conn.execute(
        """INSERT INTO contention_log(lock_key,actor,action,detail,created_at)
           VALUES (?,?,?,?,?)""",
        (lock_key, actor, "争用失败", detail, now_iso()),
    )


@router.get("/api/locks")
def list_locks(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        locks = [dict(r) for r in conn.execute("SELECT * FROM effluent_locks").fetchall()]
        logs = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM contention_log ORDER BY id DESC LIMIT 50"
            ).fetchall()
        ]
        return {"locks": locks, "contention": logs}


@router.post("/api/locks/acquire")
def acquire(lock_key: str, authorization: AuthHeader = None):
    user = require_writer(authorization)
    with connect() as conn:
        require_lock(conn, lock_key, user, persistent=True)
        write_audit(conn, user, "lock_acquire", lock_key, {"persistent": True})
        conn.commit()
        return {"ok": True, "lock_key": lock_key, "holder": user, "persistent": True}


@router.post("/api/locks/release")
def release_api(lock_key: str, authorization: AuthHeader = None):
    user = require_writer(authorization)
    with connect() as conn:
        conn.execute(
            "DELETE FROM effluent_locks WHERE lock_key=? AND holder=?",
            (lock_key, user),
        )
        write_audit(conn, user, "lock_release", lock_key, {})
        conn.commit()
        return {"ok": True}
