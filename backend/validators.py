"""排放指标与状态校验。"""
from __future__ import annotations

from fastapi import HTTPException

from metrics_math import (
    METRIC_KEYS,
    METRIC_LABELS,
    as_float_map,
    compare_to_caps,
    daily_flow_m3,
    first_exceed,
    format_triplet,
    quota_headroom,
)


def validate_outfall_open(status: str) -> None:
    if status != "开放":
        raise HTTPException(400, f"排放口状态不可采样：{status}")


def validate_plant_running(status: str) -> None:
    if status != "运行":
        raise HTTPException(400, f"处理厂未运行：{status}")


def adjudicate_exceed(metrics: dict, limits: dict) -> tuple[bool, str | None, float, float]:
    """对照排放口限值，返回是否超标及首个超标指标。"""
    label, measured, limit = first_exceed(metrics, limits)
    if label:
        return True, label, measured, limit
    return False, None, 0.0, 0.0


def validate_metrics_nonneg(metrics: dict) -> None:
    for key, val in as_float_map(metrics).items():
        if val < 0:
            raise HTTPException(400, f"指标 {key} 不可为负")


def validate_flow_cap(flow_m3h: float, design_cap_m3d: float) -> None:
    # 设计日处理量粗换算小时流量上限（按 24h 均分 *1.5 峰值）
    hourly_cap = float(design_cap_m3d) / 24.0 * 1.5
    if flow_m3h > hourly_cap:
        raise HTTPException(
            400, f"瞬时流量 {flow_m3h} 超过处理厂峰值 {hourly_cap:.1f} m3/h"
        )


def validate_permit_match(
    permit_caps: dict, sample_metrics: dict, flow_m3h: float, quota_m3d: float, tol: float = 0.05
) -> bool:
    """许可册与采样指标是否账实对齐（粗阈值）。"""
    overs = [r for r in compare_to_caps(sample_metrics, permit_caps, tol=tol) if r["over"]]
    if overs:
        return False
    if quota_headroom(quota_m3d, flow_m3h) < -(tol * 100):
        return False
    _ = daily_flow_m3(flow_m3h)
    return True


def validate_sample_releasable(status: str) -> None:
    if status != "已裁定":
        raise HTTPException(400, f"当前状态不可准排：{status}")


def validate_sample_sealable(status: str) -> None:
    if status not in ("已裁定", "已准排"):
        raise HTTPException(400, f"当前状态不可封批：{status}")


def permit_cap_rows(permit: dict, metrics: dict) -> list[dict]:
    """采样读数对许可帽的逐指标比对明细（封批/对账同口径）。"""
    caps = {
        "cod": float(permit["cod_cap"]),
        "nh3n": float(permit["nh3n_cap"]),
        "tp": float(permit["tp_cap"]),
    }
    # 帽值禁封为硬闸门：不设容差，读数 > 帽即不符（tol=0）
    return compare_to_caps(as_float_map(metrics), caps, tol=0.0)


def cap_mismatch_labels(rows: list[dict]) -> list[str]:
    return [r["metric"] for r in rows if r["over"]]


def evaluate_cap_gate(permit: dict, metrics: dict) -> dict:
    """帽值闸门结论：封批服务与对账服务各自调用，口径不混用。"""
    rows = permit_cap_rows(permit, metrics)
    mismatches = cap_mismatch_labels(rows)
    return {
        "cap_passed": not mismatches,
        "mismatches": mismatches,
        "cap_checks": rows,
    }


def raise_if_cap_mismatch(permit: dict, metrics: dict) -> list[dict]:
    """甲路径：快照读数与许可帽不符 → 封批整笔回退、正式快照零增拒收。"""
    gate = evaluate_cap_gate(permit, metrics)
    if not gate["cap_passed"]:
        detail = "；".join(
            f"{r['metric']} 读数{r['measured']} > 许可帽{r['cap']}"
            for r in gate["cap_checks"]
            if r["over"]
        )
        raise HTTPException(
            400,
            f"帽值禁封：{permit['permit_code']} 快照读数与许可帽不符（{detail}），封批整笔回退",
        )
    return gate["cap_checks"]


def metric_summary(metrics: dict) -> str:
    return format_triplet(metrics)
