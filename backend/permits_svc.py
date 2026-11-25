"""排放许可册。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from auth import AuthHeader, require_user, require_writer
from db import connect, now_iso, write_audit
from models import PermitIn
from validators import evaluate_cap_gate

router = APIRouter(tags=["permits"])

# 帽值禁封拍板说明：封批 COD 高于许可帽即红灯拒封，口径当日锁死
CAP_GATE_POLICY = (
    "帽值禁封（当日锁死）：封批快照读数高于许可帽即红灯拒封，整笔回退、正式快照零增；"
    "不符只落影子草稿，对账复核通过方可原子升正。"
)


@router.get("/api/permits")
def list_permits(authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        rows = conn.execute(
            """SELECT d.*, p.plant_code, p.name plant_name FROM discharge_permits d
               JOIN plants p ON p.id=d.plant_id ORDER BY d.id"""
        ).fetchall()
        return {"items": [dict(r) for r in rows]}


@router.get("/api/permits/{permit_code}")
def get_permit(permit_code: str, authorization: AuthHeader = None):
    require_user(authorization)
    with connect() as conn:
        row = conn.execute(
            """SELECT d.*, p.plant_code FROM discharge_permits d
               JOIN plants p ON p.id=d.plant_id WHERE d.permit_code=?""",
            (permit_code,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "许可不存在")
        samples = conn.execute(
            """SELECT sample_code, status, flow_m3h, metrics FROM sample_batches
               WHERE permit_ref=? ORDER BY id DESC""",
            (permit_code,),
        ).fetchall()
        import json

        items = []
        for s in samples:
            d = dict(s)
            metrics = json.loads(d["metrics"] or "{}")
            d["metrics"] = metrics
            gate = evaluate_cap_gate(row, metrics)
            d["cap_passed"] = gate["cap_passed"]
            d["cap_mismatches"] = gate["mismatches"]
            d["cap_checks"] = gate["cap_checks"]
            items.append(d)
        return {
            "permit": dict(row),
            "samples": items,
            "cap_gate_policy": CAP_GATE_POLICY,
        }


@router.get("/api/permits-policy/cap-gate")
def cap_gate_policy(authorization: AuthHeader = None):
    """帽值禁封拍板说明（当日锁死，五页同态只读展示）。"""
    require_user(authorization)
    return {"policy": CAP_GATE_POLICY, "locked": True, "as_of": now_iso()}


@router.post("/api/permits")
def create_permit(body: PermitIn, authorization: AuthHeader = None):
    user = require_writer(authorization)
    with connect() as conn:
        plant = conn.execute(
            "SELECT id FROM plants WHERE id=?", (body.plant_id,)
        ).fetchone()
        if not plant:
            raise HTTPException(404, "处理厂不存在")
        if conn.execute(
            "SELECT id FROM discharge_permits WHERE permit_code=?", (body.permit_code,)
        ).fetchone():
            raise HTTPException(400, "许可编码已存在")
        cur = conn.execute(
            """INSERT INTO discharge_permits(permit_code,plant_id,quota_m3d,cod_cap,nh3n_cap,
               tp_cap,period_label,status,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                body.permit_code,
                body.plant_id,
                body.quota_m3d,
                body.cod_cap,
                body.nh3n_cap,
                body.tp_cap,
                body.period_label,
                "有效",
                now_iso(),
            ),
        )
        write_audit(conn, user, "permit_create", body.permit_code,
                    {**body.model_dump(), "cap_gate_policy": CAP_GATE_POLICY})
        conn.commit()
        return {"id": cur.lastrowid, **body.model_dump(), "status": "有效"}
