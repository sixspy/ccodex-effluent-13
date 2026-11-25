"""排放封批升代快照。

帽值禁封口径（甲乙两路，比对口径同一、落点分离）：
- 甲路径（本服务封批入口）：快照读数与许可帽不符 → 整笔回退、正式快照零增拒收，
  同时落影子快照草稿（状态：帽值不符作废），对账不得计入齐套。
- 乙路径（草稿复核）：帽内草稿复核通过后原子升正正式区，升正零改；
  帽值不符草稿一律作废，不得转正。
批锁 sample:{id} 保证两路会话抢同批封批恰一成一败，败方只记争用痕。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from db import connect, now_iso, write_audit
from locks import record_contention, release, require_lock
from models import SealIn
from validators import (
    evaluate_cap_gate,
    metric_summary,
    raise_if_cap_mismatch,
    validate_sample_sealable,
)

router = APIRouter(tags=["seal"])


def _load_permit(conn, permit_ref: str):
    permit = conn.execute(
        "SELECT * FROM discharge_permits WHERE permit_code=?", (permit_ref,)
    ).fetchone()
    if not permit:
        raise HTTPException(400, "排放许可不存在")
    if permit["status"] != "有效":
        raise HTTPException(400, "排放许可未生效，禁止封批")
    return permit


def _write_shadow_draft(conn, sample, gen: int, snapshot: str, gate: dict) -> int:
    cur = conn.execute(
        """INSERT INTO seal_shadow_drafts(sample_id,sample_generation,snapshot,permit_code,
           cap_detail,cap_passed,zone,status,created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            sample["id"],
            gen,
            snapshot,
            sample["permit_ref"],
            json.dumps(gate["cap_checks"], ensure_ascii=False),
            1 if gate["cap_passed"] else 0,
            "shadow",
            "待复核" if gate["cap_passed"] else "帽值不符作废",
            now_iso(),
        ),
    )
    return cur.lastrowid


@router.get("/api/seals")
def list_seals(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT d.*, s.sample_code FROM discharge_seals d
               JOIN sample_batches s ON s.id=d.sample_id
               ORDER BY d.id DESC"""
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.get("/api/seal-drafts")
def list_shadow_drafts(authorization: AuthHeader = None):
    """影子快照草稿区（乙路径对账复核用），与正式封批分区可见。"""
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT d.*, s.sample_code FROM seal_shadow_drafts d
               JOIN sample_batches s ON s.id=d.sample_id
               ORDER BY d.id DESC"""
        ).fetchall()
        items = []
        for r in rows:
            row = dict(r)
            row["cap_checks"] = json.loads(row.pop("cap_detail") or "[]")
            row["cap_passed"] = bool(row["cap_passed"])
            items.append(row)
        return {"items": items}


@router.post("/api/seals")
def create_seal(body: SealIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    lock_key = f"sample:{body.sample_id}"
    with connect() as conn:
        require_lock(conn, lock_key, user)
        try:
            sample = conn.execute(
                "SELECT * FROM sample_batches WHERE id=?", (body.sample_id,)
            ).fetchone()
            if not sample:
                raise HTTPException(404, "采样批次不存在")
            # 抢批锁后重读：他路已先封批 → 本路为败方，409 只记争用痕、零正式写入
            if sample["status"] == "已封批":
                record_contention(
                    conn, lock_key, user,
                    f"后到封批：{sample['sample_code']} 已被他路封批",
                )
                conn.commit()
                raise HTTPException(409, f"批次已封批，后到会话记争用：{sample['sample_code']}")
            validate_sample_sealable(sample["status"])
            open_hold = conn.execute(
                "SELECT id FROM exceed_holds WHERE sample_id=? AND status='开放'",
                (body.sample_id,),
            ).fetchone()
            if open_hold:
                raise HTTPException(400, "开放挂起未闭，禁止封批")

            metrics = json.loads(sample["metrics"] or "{}")
            permit = _load_permit(conn, sample["permit_ref"])
            gen = int(sample["generation"]) + 1
            snap = body.snapshot or metric_summary(metrics)

            # 同代防重：已存在该代正式封批则按争用处理，保证重复请求零增
            dup = conn.execute(
                "SELECT id FROM discharge_seals WHERE sample_id=? AND sample_generation=?",
                (body.sample_id, gen),
            ).fetchone()
            if dup:
                record_contention(
                    conn, lock_key, user,
                    f"同代重复封批：{sample['sample_code']} G{gen} 已存在",
                )
                conn.commit()
                raise HTTPException(409, f"该批次第 {gen} 代已封批，后到会话记争用")

            gate = evaluate_cap_gate(permit, metrics)
            # 不符一律先落影子草稿（乙路径痕迹），再走甲路径硬拒收
            draft_id = _write_shadow_draft(conn, sample, gen, snap, gate)

            if not gate["cap_passed"]:
                # 甲路径：帽值不符 → 草稿作废、整笔回退、正式快照零增
                conn.execute(
                    "UPDATE seal_shadow_drafts SET status=?, settled_at=? WHERE id=?",
                    ("帽值不符作废", now_iso(), draft_id),
                )
                write_audit(
                    conn, user, "seal_cap_reject", sample["sample_code"],
                    {"draft_id": draft_id, "mismatches": gate["mismatches"],
                     "permit": permit["permit_code"]},
                )
                conn.commit()
                raise_if_cap_mismatch(permit, metrics)

            # 帽内：原子升正——影子草稿与正式封批同事务落库，正式区零改
            seal_ref = f"SL-{sample['sample_code']}-G{gen}"
            cur = conn.execute(
                """INSERT INTO discharge_seals(sample_id,sample_generation,snapshot,seal_ref,
                   status,sealed_at) VALUES (?,?,?,?,?,?)""",
                (body.sample_id, gen, snap, seal_ref, "已封批", now_iso()),
            )
            seal_id = cur.lastrowid
            conn.execute(
                """UPDATE seal_shadow_drafts SET status=?, promoted_seal_id=?, settled_at=?
                   WHERE id=?""",
                ("复核通过已升正", seal_id, now_iso(), draft_id),
            )
            conn.execute(
                "UPDATE sample_batches SET generation=?, status=? WHERE id=?",
                (gen, "已封批", body.sample_id),
            )
            write_audit(
                conn,
                user,
                "seal",
                sample["sample_code"],
                {"seal_ref": seal_ref, "generation": gen, "snapshot": snap,
                 "draft_id": draft_id, "cap_passed": True},
            )
            conn.commit()
            return {"seal_ref": seal_ref, "generation": gen, "snapshot": snap,
                    "draft_id": draft_id}
        finally:
            release(conn, lock_key, user)
            conn.commit()


@router.post("/api/seal-drafts/{draft_id}/promote")
def promote_shadow_draft(draft_id: int, authorization: AuthHeader = None):
    """乙路径：影子草稿对账复核通过后原子升正；帽值不符草稿作废拒升。"""
    user = require_writer(authorization)
    with connect() as conn:
        draft = conn.execute(
            "SELECT * FROM seal_shadow_drafts WHERE id=?", (draft_id,)
        ).fetchone()
        if not draft:
            raise HTTPException(404, "影子草稿不存在")
        lock_key = f"sample:{draft['sample_id']}"
        require_lock(conn, lock_key, user)
        try:
            if draft["status"] == "复核通过已升正":
                raise HTTPException(400, "草稿已升正，勿重复")
            sample = conn.execute(
                "SELECT * FROM sample_batches WHERE id=?", (draft["sample_id"],)
            ).fetchone()
            permit = _load_permit(conn, draft["permit_code"])
            metrics = json.loads(sample["metrics"] or "{}")
            gate = evaluate_cap_gate(permit, metrics)
            if not gate["cap_passed"]:
                conn.execute(
                    "UPDATE seal_shadow_drafts SET status=?, settled_at=? WHERE id=?",
                    ("帽值不符作废", now_iso(), draft_id),
                )
                write_audit(
                    conn, user, "seal_draft_void", sample["sample_code"],
                    {"draft_id": draft_id, "mismatches": gate["mismatches"]},
                )
                conn.commit()
                raise HTTPException(400, "帽值不符草稿作废，禁止升正正式区")

            gen = int(draft["sample_generation"])
            dup = conn.execute(
                "SELECT id FROM discharge_seals WHERE sample_id=? AND sample_generation=?",
                (sample["id"], gen),
            ).fetchone()
            if dup:
                raise HTTPException(400, f"第 {gen} 代正式封批已存在，升正零改")
            seal_ref = f"SL-{sample['sample_code']}-G{gen}"
            cur = conn.execute(
                """INSERT INTO discharge_seals(sample_id,sample_generation,snapshot,seal_ref,
                   status,sealed_at) VALUES (?,?,?,?,?,?)""",
                (sample["id"], gen, draft["snapshot"], seal_ref, "已封批", now_iso()),
            )
            # 原子升正：草稿快照逐字进正式区，零改
            conn.execute(
                """UPDATE seal_shadow_drafts SET status=?, promoted_seal_id=?, settled_at=?
                   WHERE id=?""",
                ("复核通过已升正", cur.lastrowid, now_iso(), draft_id),
            )
            conn.execute(
                "UPDATE sample_batches SET generation=?, status=? WHERE id=?",
                (gen, "已封批", sample["id"]),
            )
            write_audit(
                conn, user, "seal_draft_promote", sample["sample_code"],
                {"draft_id": draft_id, "seal_ref": seal_ref, "generation": gen},
            )
            conn.commit()
            return {"seal_ref": seal_ref, "generation": gen,
                    "snapshot": draft["snapshot"], "draft_id": draft_id}
        finally:
            release(conn, lock_key, user)
            conn.commit()
