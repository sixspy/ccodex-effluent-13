"""SQLite：污水排放批母仓公共库层。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DB_PATH = DATA / "app.db"
FIXTURES = ROOT / "fixtures"
FRONTEND = ROOT / "frontend"

PRODUCT_META = {
    "product": "污水排放批",
    "skeleton": "采样批次入库后裁定超标才准排放封批，驳回进旁路挂起，指标血缘与排放许可对账",
    "modules": [
        "plants",
        "outfalls",
        "samples",
        "exceed",
        "release",
        "seal",
        "permits",
        "metric_lineage",
        "reconcile",
        "locks",
        "audit",
    ],
    "stubs": ["lab_courier_stub", "sludge_plan_stub"],
}


def connect() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    # WAL：批锁须跨连接互斥，两路会话抢同批封批时后到连接在锁上等待而非盲写。
    # 只读库（如受限环境挂载）无法切 WAL，容错降级为默认日志，读路径不受影响。
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def sha_password(password: str) -> str:
    import hashlib

    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  username TEXT PRIMARY KEY,
  password_sha TEXT NOT NULL,
  role TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plants(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  plant_code TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  basin TEXT NOT NULL,
  design_cap_m3d REAL NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outfalls(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  outfall_code TEXT UNIQUE NOT NULL,
  plant_id INTEGER NOT NULL,
  river_reach TEXT NOT NULL,
  cod_limit REAL NOT NULL,
  nh3n_limit REAL NOT NULL,
  tp_limit REAL NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(plant_id) REFERENCES plants(id)
);
CREATE TABLE IF NOT EXISTS discharge_permits(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  permit_code TEXT UNIQUE NOT NULL,
  plant_id INTEGER NOT NULL,
  quota_m3d REAL NOT NULL,
  cod_cap REAL NOT NULL,
  nh3n_cap REAL NOT NULL,
  tp_cap REAL NOT NULL,
  period_label TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(plant_id) REFERENCES plants(id)
);
CREATE TABLE IF NOT EXISTS sample_batches(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sample_code TEXT UNIQUE NOT NULL,
  outfall_id INTEGER NOT NULL,
  permit_ref TEXT NOT NULL,
  metrics TEXT NOT NULL,
  flow_m3h REAL NOT NULL,
  generation INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL,
  adjudicated_at TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(outfall_id) REFERENCES outfalls(id)
);
CREATE TABLE IF NOT EXISTS exceed_holds(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sample_id INTEGER NOT NULL,
  hold_key TEXT NOT NULL,
  exceed_metric TEXT NOT NULL,
  measured REAL NOT NULL,
  limit_value REAL NOT NULL,
  status TEXT NOT NULL,
  opened_at TEXT NOT NULL,
  closed_at TEXT,
  note TEXT,
  FOREIGN KEY(sample_id) REFERENCES sample_batches(id)
);
CREATE TABLE IF NOT EXISTS discharge_releases(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sample_id INTEGER NOT NULL,
  outfall_id INTEGER NOT NULL,
  release_ref TEXT NOT NULL,
  status TEXT NOT NULL,
  officer TEXT NOT NULL,
  released_at TEXT NOT NULL,
  FOREIGN KEY(sample_id) REFERENCES sample_batches(id),
  FOREIGN KEY(outfall_id) REFERENCES outfalls(id)
);
CREATE TABLE IF NOT EXISTS discharge_seals(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sample_id INTEGER NOT NULL,
  sample_generation INTEGER NOT NULL,
  snapshot TEXT NOT NULL,
  seal_ref TEXT NOT NULL,
  status TEXT NOT NULL,
  sealed_at TEXT NOT NULL,
  FOREIGN KEY(sample_id) REFERENCES sample_batches(id)
);
CREATE TABLE IF NOT EXISTS seal_shadow_drafts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sample_id INTEGER NOT NULL,
  sample_generation INTEGER NOT NULL,
  snapshot TEXT NOT NULL,
  permit_code TEXT NOT NULL,
  cap_detail TEXT NOT NULL,
  cap_passed INTEGER NOT NULL,
  zone TEXT NOT NULL DEFAULT 'shadow',
  status TEXT NOT NULL,
  promoted_seal_id INTEGER,
  created_at TEXT NOT NULL,
  settled_at TEXT,
  FOREIGN KEY(sample_id) REFERENCES sample_batches(id)
);
CREATE TABLE IF NOT EXISTS metric_lineage(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  from_sample_id INTEGER NOT NULL,
  to_sample_id INTEGER,
  edge_type TEXT NOT NULL,
  detail TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(from_sample_id) REFERENCES sample_batches(id)
);
CREATE TABLE IF NOT EXISTS effluent_locks(
  lock_key TEXT PRIMARY KEY,
  holder TEXT NOT NULL,
  acquired_at TEXT NOT NULL,
  persistent INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS contention_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lock_key TEXT NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  detail TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_trail(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  target TEXT,
  payload TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lab_courier_jobs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sample_code TEXT NOT NULL,
  courier_slot TEXT NOT NULL,
  mode TEXT NOT NULL,
  status TEXT NOT NULL,
  detail TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sludge_plan_jobs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  plant_id INTEGER,
  digester_bay TEXT NOT NULL,
  mode TEXT NOT NULL,
  status TEXT NOT NULL,
  detail TEXT,
  created_at TEXT NOT NULL
);
"""


def write_audit(
    conn: sqlite3.Connection, actor: str, action: str, target: str, payload: dict
) -> None:
    conn.execute(
        """INSERT INTO audit_trail(actor,action,target,payload,created_at)
           VALUES (?,?,?,?,?)""",
        (actor, action, target, json.dumps(payload, ensure_ascii=False), now_iso()),
    )


def _load_json(name: str):
    path = FIXTURES / name
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def seed_users(conn: sqlite3.Connection) -> None:
    seeds = (
        ("admin", sha_password("admin123"), "admin"),
        ("writer", sha_password("writer123"), "clerk"),
        ("viewer", sha_password("viewer123"), "viewer"),
    )
    for u, pw, role in seeds:
        conn.execute(
            "INSERT OR IGNORE INTO users(username,password_sha,role) VALUES (?,?,?)",
            (u, pw, role),
        )


def _plant_id(conn, code: str) -> int | None:
    row = conn.execute("SELECT id FROM plants WHERE plant_code=?", (code,)).fetchone()
    return int(row["id"]) if row else None


def seed_plants(conn: sqlite3.Connection) -> None:
    for row in _load_json("plants.json"):
        if conn.execute(
            "SELECT id FROM plants WHERE plant_code=?", (row["plant_code"],)
        ).fetchone():
            continue
        conn.execute(
            """INSERT INTO plants(plant_code,name,basin,design_cap_m3d,status,created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                row["plant_code"],
                row["name"],
                row["basin"],
                float(row["design_cap_m3d"]),
                row.get("status", "运行"),
                row.get("created_at", now_iso()),
            ),
        )


def seed_outfalls(conn: sqlite3.Connection) -> None:
    for row in _load_json("outfalls.json"):
        if conn.execute(
            "SELECT id FROM outfalls WHERE outfall_code=?", (row["outfall_code"],)
        ).fetchone():
            continue
        plant = _plant_id(conn, row["plant_code"])
        if not plant:
            continue
        conn.execute(
            """INSERT INTO outfalls(outfall_code,plant_id,river_reach,cod_limit,nh3n_limit,
               tp_limit,status,created_at) VALUES (?,?,?,?,?,?,?,?)""",
            (
                row["outfall_code"],
                plant,
                row["river_reach"],
                float(row["cod_limit"]),
                float(row["nh3n_limit"]),
                float(row["tp_limit"]),
                row.get("status", "开放"),
                row.get("created_at", now_iso()),
            ),
        )


def seed_permits(conn: sqlite3.Connection) -> None:
    for row in _load_json("permits.json"):
        if conn.execute(
            "SELECT id FROM discharge_permits WHERE permit_code=?",
            (row["permit_code"],),
        ).fetchone():
            continue
        plant = _plant_id(conn, row["plant_code"])
        if not plant:
            continue
        conn.execute(
            """INSERT INTO discharge_permits(permit_code,plant_id,quota_m3d,cod_cap,nh3n_cap,
               tp_cap,period_label,status,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                row["permit_code"],
                plant,
                float(row["quota_m3d"]),
                float(row["cod_cap"]),
                float(row["nh3n_cap"]),
                float(row["tp_cap"]),
                row["period_label"],
                row.get("status", "有效"),
                row.get("created_at", now_iso()),
            ),
        )


def _outfall_id(conn, code: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM outfalls WHERE outfall_code=?", (code,)
    ).fetchone()
    return int(row["id"]) if row else None


def seed_samples(conn: sqlite3.Connection) -> None:
    for row in _load_json("samples.json"):
        if conn.execute(
            "SELECT id FROM sample_batches WHERE sample_code=?", (row["sample_code"],)
        ).fetchone():
            continue
        outfall = _outfall_id(conn, row["outfall_code"])
        if not outfall:
            continue
        conn.execute(
            """INSERT INTO sample_batches(sample_code,outfall_id,permit_ref,metrics,flow_m3h,
               generation,status,adjudicated_at,created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                row["sample_code"],
                outfall,
                row["permit_ref"],
                json.dumps(row.get("metrics", {}), ensure_ascii=False),
                float(row["flow_m3h"]),
                int(row.get("generation", 1)),
                row.get("status", "已裁定"),
                row.get("adjudicated_at"),
                row.get("created_at", now_iso()),
            ),
        )


def seed_exceeds(conn: sqlite3.Connection) -> None:
    for row in _load_json("exceeds.json"):
        sample = conn.execute(
            "SELECT id FROM sample_batches WHERE sample_code=?", (row["sample_code"],)
        ).fetchone()
        if not sample:
            continue
        if conn.execute(
            "SELECT id FROM exceed_holds WHERE hold_key=?", (row["hold_key"],)
        ).fetchone():
            continue
        conn.execute(
            """INSERT INTO exceed_holds(sample_id,hold_key,exceed_metric,measured,limit_value,
               status,opened_at,closed_at,note) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                sample["id"],
                row["hold_key"],
                row["exceed_metric"],
                float(row["measured"]),
                float(row["limit_value"]),
                row.get("status", "开放"),
                row["opened_at"],
                row.get("closed_at"),
                row.get("note", ""),
            ),
        )


def seed_releases(conn: sqlite3.Connection) -> None:
    for row in _load_json("releases.json"):
        sample = conn.execute(
            "SELECT id, outfall_id FROM sample_batches WHERE sample_code=?",
            (row["sample_code"],),
        ).fetchone()
        if not sample:
            continue
        if conn.execute(
            "SELECT id FROM discharge_releases WHERE release_ref=?",
            (row["release_ref"],),
        ).fetchone():
            continue
        conn.execute(
            """INSERT INTO discharge_releases(sample_id,outfall_id,release_ref,status,officer,released_at)
               VALUES (?,?,?,?,?,?)""",
            (
                sample["id"],
                sample["outfall_id"],
                row["release_ref"],
                row.get("status", "已准排"),
                row.get("officer", "值班员"),
                row["released_at"],
            ),
        )


def seed_seals(conn: sqlite3.Connection) -> None:
    for row in _load_json("seals.json"):
        sample = conn.execute(
            "SELECT id, generation FROM sample_batches WHERE sample_code=?",
            (row["sample_code"],),
        ).fetchone()
        if not sample:
            continue
        if conn.execute(
            "SELECT id FROM discharge_seals WHERE seal_ref=?", (row["seal_ref"],)
        ).fetchone():
            continue
        conn.execute(
            """INSERT INTO discharge_seals(sample_id,sample_generation,snapshot,seal_ref,status,sealed_at)
               VALUES (?,?,?,?,?,?)""",
            (
                sample["id"],
                int(row.get("sample_generation", sample["generation"])),
                row["snapshot"],
                row["seal_ref"],
                row.get("status", "已封批"),
                row["sealed_at"],
            ),
        )


def seed_lineage(conn: sqlite3.Connection) -> None:
    for row in _load_json("lineage.json"):
        fr = conn.execute(
            "SELECT id FROM sample_batches WHERE sample_code=?", (row["from_sample"],)
        ).fetchone()
        if not fr:
            continue
        to_id = None
        if row.get("to_sample"):
            to_row = conn.execute(
                "SELECT id FROM sample_batches WHERE sample_code=?", (row["to_sample"],)
            ).fetchone()
            to_id = to_row["id"] if to_row else None
        if conn.execute(
            """SELECT id FROM metric_lineage WHERE from_sample_id=? AND edge_type=? AND detail=?""",
            (fr["id"], row["edge_type"], row["detail"]),
        ).fetchone():
            continue
        conn.execute(
            """INSERT INTO metric_lineage(from_sample_id,to_sample_id,edge_type,detail,created_at)
               VALUES (?,?,?,?,?)""",
            (
                fr["id"],
                to_id,
                row["edge_type"],
                row["detail"],
                row.get("created_at", now_iso()),
            ),
        )


def migrate(conn: sqlite3.Connection) -> None:
    """幂等迁移：旧库补 effluent-13 帽值禁封所需表与列，新库为空操作。"""
    lock_cols = {r[1] for r in conn.execute("PRAGMA table_info(effluent_locks)")}
    if "persistent" not in lock_cols:
        conn.execute("ALTER TABLE effluent_locks ADD COLUMN persistent INTEGER NOT NULL DEFAULT 0")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "seal_shadow_drafts" not in tables:
        conn.execute(
            """CREATE TABLE seal_shadow_drafts(
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               sample_id INTEGER NOT NULL,
               sample_generation INTEGER NOT NULL,
               snapshot TEXT NOT NULL,
               permit_code TEXT NOT NULL,
               cap_detail TEXT NOT NULL,
               cap_passed INTEGER NOT NULL,
               zone TEXT NOT NULL DEFAULT 'shadow',
               status TEXT NOT NULL,
               promoted_seal_id INTEGER,
               created_at TEXT NOT NULL,
               settled_at TEXT,
               FOREIGN KEY(sample_id) REFERENCES sample_batches(id)
            )"""
        )


def init_db() -> None:
    try:
        with connect() as conn:
            conn.executescript(SCHEMA)
            migrate(conn)
            seed_users(conn)
            seed_plants(conn)
            seed_outfalls(conn)
            seed_permits(conn)
            seed_samples(conn)
            seed_exceeds(conn)
            seed_releases(conn)
            seed_seals(conn)
            seed_lineage(conn)
            conn.commit()
    except sqlite3.OperationalError as exc:
        # 只读挂载（受限环境）：保留现有数据，跳过建表/迁移/播种，读路径仍可用。
        # 可写环境（如 Docker 新卷）不会进入此分支。
        if "readonly" not in str(exc).lower():
            raise
        import warnings

        warnings.warn(f"数据库只读，跳过初始化与迁移：{DB_PATH}（{exc}）", RuntimeWarning)


def dashboard_stats(conn: sqlite3.Connection) -> dict:
    plants = conn.execute("SELECT COUNT(*) c FROM plants").fetchone()["c"]
    outfalls = conn.execute("SELECT COUNT(*) c FROM outfalls").fetchone()["c"]
    samples = conn.execute("SELECT COUNT(*) c FROM sample_batches").fetchone()["c"]
    open_holds = conn.execute(
        "SELECT COUNT(*) c FROM exceed_holds WHERE status='开放'"
    ).fetchone()["c"]
    released = conn.execute(
        "SELECT COUNT(*) c FROM discharge_releases WHERE status='已准排'"
    ).fetchone()["c"]
    sealed = conn.execute(
        "SELECT COUNT(*) c FROM discharge_seals WHERE status='已封批'"
    ).fetchone()["c"]
    permits = conn.execute("SELECT COUNT(*) c FROM discharge_permits").fetchone()["c"]
    pending = conn.execute(
        "SELECT COUNT(*) c FROM sample_batches WHERE status='旁路挂起'"
    ).fetchone()["c"]
    stubs = {
        "lab_courier_jobs": conn.execute(
            "SELECT COUNT(*) c FROM lab_courier_jobs"
        ).fetchone()["c"],
        "sludge_plan_jobs": conn.execute(
            "SELECT COUNT(*) c FROM sludge_plan_jobs"
        ).fetchone()["c"],
    }
    return {
        "plants": plants,
        "outfalls": outfalls,
        "samples": samples,
        "open_exceeds": open_holds,
        "discharge_releases": released,
        "discharge_seals": sealed,
        "permits": permits,
        "side_pending": pending,
        "stubs": stubs,
        "meta": PRODUCT_META,
    }
