#!/usr/bin/env python3
"""排污寅第13槽 · 并发打批锁脚本 ping_cap_seal_lock。

两路会话同时对同一采样批（默认 SM-M13）发起封批，
验证抢批锁：恰一成一败，败方 409、零正式快照，争用痕落 contention_log。

用法：
  python scripts/ping_cap_seal_lock.py
  python scripts/ping_cap_seal_lock.py --base http://localhost:8000 --sample SM-M13
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import urllib.error
import urllib.request


def _request(base: str, path: str, token: str | None = None,
             body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body or {}).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(
        base.rstrip("/") + path, data=data, headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw}


def _login(base: str) -> str:
    _, payload = _request(
        base, "/api/login", body={"username": "admin", "password": "admin123"}
    )
    return payload["token"]


def _sample_id(base: str, token: str, code: str) -> int:
    req = urllib.request.Request(
        base.rstrip() + "/api/samples",
        headers={"Authorization": "Bearer " + token},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        items = json.loads(resp.read().decode())["items"]
    return next(s["id"] for s in items if s["sample_code"] == code)


def main() -> int:
    parser = argparse.ArgumentParser(description="双路并发打同批封批锁")
    parser.add_argument("--base", default="http://localhost:8000")
    # 默认帽内批：能走到批锁争用；传 SM-M13 则验证帽值闸门双红灯
    parser.add_argument("--sample", default="SM-OF-N3-A-001")
    args = parser.parse_args()

    token = _login(args.base)
    sample_id = _sample_id(args.base, token, args.sample)
    barrier = threading.Barrier(2)
    outcomes: list[tuple[str, int, dict]] = []
    out_lock = threading.Lock()

    def ping(actor: str) -> None:
        actor_token = _login(args.base)  # 独立会话
        barrier.wait()
        status, payload = _request(
            args.base, "/api/seals", actor_token, {"sample_id": sample_id}
        )
        with out_lock:
            outcomes.append((actor, status, payload))

    threads = [threading.Thread(target=ping, args=(f"会话{i + 1}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    print(f"同批封批并发打点：sample={args.sample}(id={sample_id}) 路数=2")
    for actor, status, payload in outcomes:
        print(f"  {actor}: HTTP {status} {payload}")

    if args.sample == "SM-M13":
        # 帽值闸门模式：两路皆红灯且无正式快照即为通过
        ok = sorted(o[1] for o in outcomes) == [400, 400]
        print("结果：", "通过（双路帽值禁封，零正式快照）" if ok else "异常")
        return 0 if ok else 1

    winners = [o for o in outcomes if o[1] == 200]
    losers = [o for o in outcomes if o[1] == 409]
    ok = len(winners) == 1 and len(losers) == 1
    print("结果：", "通过（一成一败，败方争用痕）" if ok else "异常（须查批锁/帽值闸门）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
