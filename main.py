"""年会大屏头像抽奖与弹幕互动系统 —— 后端 Demo。

技术栈：FastAPI + SQLite + Jinja2
启动：
    python main.py
或：
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import uvicorn
from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

logger = logging.getLogger("annual-party")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
AVATAR_DIR = STATIC_DIR / "avatars"
TEMPLATES_DIR = BASE_DIR / "templates"
DB_PATH = BASE_DIR / "lottery.db"

AVATAR_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

MAX_AVATAR_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_NAME_LENGTH = 20
MAX_REAL_NAME_LENGTH = 20
MAX_DEPARTMENT_LENGTH = 30
MAX_EMPLOYEE_ID_LENGTH = 30
MAX_DANMAKU_LENGTH = 100
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
EXT_BY_CONTENT_TYPE = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

USER_COLUMNS = (
    "id, name, nickname, real_name, department, employee_id, "
    "avatar_url, is_winner, is_excluded, must_win"
)

DEFAULT_PRIZES = (
    ("一等奖", 1, 0),
    ("二等奖", 3, 1),
    ("三等奖", 5, 2),
)


class PrizeItem(BaseModel):
    name: str
    count: int = Field(ge=1, le=10)


class PrizeListPayload(BaseModel):
    prizes: list[PrizeItem]


class UserFlagsPayload(BaseModel):
    is_excluded: int | None = Field(default=None, ge=0, le=1)
    must_win: int | None = Field(default=None, ge=0, le=1)


# ---------------------------------------------------------------------------
# 数据库
# ---------------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    """每次请求使用独立连接，避免 FastAPI 线程池下的跨线程问题。"""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """建表，并对旧版本数据库做增量迁移。"""
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                nickname    TEXT    NOT NULL DEFAULT '',
                real_name   TEXT    NOT NULL DEFAULT '',
                department  TEXT    NOT NULL DEFAULT '',
                employee_id TEXT    NOT NULL DEFAULT '',
                avatar_url  TEXT    NOT NULL,
                is_winner   INTEGER NOT NULL DEFAULT 0,
                is_excluded INTEGER NOT NULL DEFAULT 0,
                must_win    INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        # 旧库没有这些字段时自动补齐，保留已有用户数据。
        migrations = {
            "nickname": "TEXT NOT NULL DEFAULT ''",
            "real_name": "TEXT NOT NULL DEFAULT ''",
            "department": "TEXT NOT NULL DEFAULT ''",
            "employee_id": "TEXT NOT NULL DEFAULT ''",
            "is_excluded": "INTEGER NOT NULL DEFAULT 0",
            "must_win": "INTEGER NOT NULL DEFAULT 0",
        }
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        for column, definition in migrations.items():
            if column not in existing:
                conn.execute(f'ALTER TABLE users ADD COLUMN "{column}" {definition}')
                existing.add(column)

        # 老用户用原来的 name 补齐新字段，避免大屏出现空名字。
        conn.execute("UPDATE users SET nickname = name WHERE nickname = ''")
        conn.execute("UPDATE users SET real_name = name WHERE real_name = ''")

        # 控制台奖项预设；首次建库时写入默认奖项。
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prizes (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT    NOT NULL,
                count      INTEGER NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        prize_count = conn.execute("SELECT COUNT(*) AS n FROM prizes").fetchone()["n"]
        if int(prize_count) == 0:
            conn.executemany(
                "INSERT INTO prizes (name, count, sort_order) VALUES (?, ?, ?)",
                DEFAULT_PRIZES,
            )


def reset_demo_users() -> None:
    """演示模式：每次服务启动清空签到名单，奖项预设保留。"""
    with db() as conn:
        conn.execute("DELETE FROM users")
        has_sequence = conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'sqlite_sequence'"
        ).fetchone()
        if has_sequence:
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'users'")


def delete_user(user_id: int) -> bool:
    """删除签退用户；返回是否真的删掉了一行。"""
    with db() as conn:
        cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return cursor.rowcount > 0


def _count_users(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
    return int(row["n"])


def _list_prizes(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, name, count FROM prizes ORDER BY sort_order ASC, id ASC"
    ).fetchall()
    return [dict(row) for row in rows]


def _clean_field(value: str, label: str, max_length: int) -> str:
    cleaned = (value or "").strip()
    if len(cleaned) > max_length:
        raise HTTPException(status_code=400, detail=f"{label}不能超过 {max_length} 个字符")
    return cleaned


# ---------------------------------------------------------------------------
# WebSocket 连接池
# ---------------------------------------------------------------------------
class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        # 签到用户与 WebSocket 的对应关系，用于断线时广播 leave。
        self._socket_users: dict[WebSocket, int] = {}
        self._user_sockets: dict[int, set[WebSocket]] = {}

    @property
    def count(self) -> int:
        return len(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)

    def bind_user(self, websocket: WebSocket, user_id: int) -> bool:
        """把连接绑定到签到用户；同一用户重复绑定返回 False。"""
        if self._socket_users.get(websocket) == user_id:
            return False
        self._drop_user_link(websocket)
        self._socket_users[websocket] = user_id
        self._user_sockets.setdefault(user_id, set()).add(websocket)
        return True

    def _drop_user_link(self, websocket: WebSocket) -> int | None:
        """移除连接与用户的关联；该用户已无任何连接时返回 user_id。"""
        user_id = self._socket_users.pop(websocket, None)
        if user_id is None:
            return None
        sockets = self._user_sockets.get(user_id)
        if sockets is None:
            return None
        sockets.discard(websocket)
        if not sockets:
            self._user_sockets.pop(user_id, None)
            return user_id
        return None

    def disconnect(self, websocket: WebSocket) -> tuple[bool, int | None]:
        """返回 (是否真的移除了连接, 是否是该用户最后一个连接)。"""
        removed = websocket in self._connections
        if removed:
            self._connections.remove(websocket)
        last_user_id = self._drop_user_link(websocket)
        return removed, last_user_id

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for connection in list(self._connections):
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for connection in dead:
            _, user_id = self.disconnect(connection)
            if user_id is not None:
                # 发送失败的连接也按签退处理，直接移出名单。
                await _remove_disconnected_user(user_id)


manager = ConnectionManager()
draw_lock = asyncio.Lock()


async def _remove_disconnected_user(user_id: int) -> None:
    """签退即删除数据库用户，并通知大屏移除头像卡片。"""
    if delete_user(user_id):
        await manager.broadcast({"type": "leave", "user_id": user_id})


# ---------------------------------------------------------------------------
# 应用
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    reset_demo_users()
    logger.info("SQLite 数据库已就绪（演示模式：启动时已清空签到名单）：%s", DB_PATH)
    yield


app = FastAPI(title="年会大屏头像抽奖与弹幕互动系统", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# 页面路由
# ---------------------------------------------------------------------------
@app.get("/")
def index() -> RedirectResponse:
    return RedirectResponse(url="/screen")


@app.get("/register")
def register_page(request: Request):
    # host 由服务端按当前请求动态注入，不写死任何 IP。
    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={"host": request.headers.get("host", "")},
    )


@app.get("/screen")
def screen_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="screen.html",
        context={"host": request.headers.get("host", "")},
    )


@app.get("/control")
def control_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="control.html",
        context={"host": request.headers.get("host", "")},
    )


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@app.post("/api/register", status_code=201)
async def register(
    name: str = Form(...),
    nickname: str = Form(default=""),
    real_name: str = Form(default=""),
    department: str = Form(default=""),
    employee_id: str = Form(default=""),
    is_excluded: int = Form(default=0),
    must_win: int = Form(default=0),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """接收昵称、真实姓名、部门、工号、头像等签到信息。"""
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="昵称不能为空")
    if len(name) > MAX_NAME_LENGTH:
        raise HTTPException(status_code=400, detail=f"昵称不能超过 {MAX_NAME_LENGTH} 个字符")

    # 兼容旧客户端：未传昵称/真名时回退到 name。
    nickname = _clean_field(nickname, "昵称", MAX_NAME_LENGTH) or name
    real_name = _clean_field(real_name, "真实姓名", MAX_REAL_NAME_LENGTH) or nickname
    department = _clean_field(department, "部门", MAX_DEPARTMENT_LENGTH)
    employee_id = _clean_field(employee_id, "工号", MAX_EMPLOYEE_ID_LENGTH)
    is_excluded = 1 if is_excluded else 0
    must_win = 1 if must_win else 0

    content_type = (file.content_type or "").lower()
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        suffix = EXT_BY_CONTENT_TYPE.get(content_type, "")
    if not content_type.startswith("image/") or not suffix:
        raise HTTPException(status_code=400, detail="请上传 png/jpg/gif/webp 格式的图片")

    data = await file.read(MAX_AVATAR_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="上传的图片为空")
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=413, detail="头像不能超过 5MB")

    filename = f"{uuid.uuid4().hex}{suffix}"
    avatar_path = AVATAR_DIR / filename
    avatar_path.write_bytes(data)
    avatar_url = f"/static/avatars/{filename}"

    with db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO users
                (name, nickname, real_name, department, employee_id,
                 avatar_url, is_excluded, must_win)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                nickname,
                real_name,
                department,
                employee_id,
                avatar_url,
                is_excluded,
                must_win,
            ),
        )
        row = conn.execute(
            f"SELECT {USER_COLUMNS} FROM users WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        total = _count_users(conn)

    user = dict(row)
    await manager.broadcast({"type": "register", "user": user, "count": total})
    return {"success": True, "user": user, "count": total}


@app.get("/api/users")
def list_users() -> dict[str, Any]:
    with db() as conn:
        rows = conn.execute(
            f"SELECT {USER_COLUMNS} FROM users ORDER BY id ASC"
        ).fetchall()
        total = _count_users(conn)
    return {"users": [dict(row) for row in rows], "count": total}


@app.patch("/api/users/{user_id}/flags")
async def update_user_flags(
    user_id: int, payload: UserFlagsPayload
) -> dict[str, Any]:
    """控制台修改单个用户的排除抽奖 / 内定必中状态。"""
    updates: dict[str, int] = {}
    if payload.is_excluded is not None:
        updates["is_excluded"] = int(payload.is_excluded)
    if payload.must_win is not None:
        updates["must_win"] = int(payload.must_win)

    if not updates:
        raise HTTPException(status_code=400, detail="请至少提供一个状态字段")
    if updates.get("is_excluded") == 1 and updates.get("must_win") == 1:
        raise HTTPException(status_code=400, detail="排除抽奖和内定必中不能同时开启")

    # 两个开关互斥：开启任意一个时，自动关闭另一个。
    if updates.get("is_excluded") == 1:
        updates["must_win"] = 0
    if updates.get("must_win") == 1:
        updates["is_excluded"] = 0

    assignments = ", ".join(f"{column} = ?" for column in updates)
    with db() as conn:
        exists = conn.execute(
            "SELECT 1 FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="用户不存在")
        conn.execute(
            f"UPDATE users SET {assignments} WHERE id = ?",
            (*updates.values(), user_id),
        )
        row = conn.execute(
            f"SELECT {USER_COLUMNS} FROM users WHERE id = ?", (user_id,)
        ).fetchone()

    user = dict(row)
    await manager.broadcast({"type": "user_update", "user": user})
    return {"success": True, "user": user}


@app.get("/api/prizes")
def list_prizes() -> dict[str, Any]:
    with db() as conn:
        prizes = _list_prizes(conn)
    return {"prizes": prizes}


@app.put("/api/prizes")
async def save_prizes(payload: PrizeListPayload) -> dict[str, Any]:
    """整体保存奖项预设，供控制台选择奖项后抽奖。"""
    if not payload.prizes:
        raise HTTPException(status_code=400, detail="至少配置一个奖项")
    if len(payload.prizes) > 12:
        raise HTTPException(status_code=400, detail="奖项数量不能超过 12 个")

    normalized: list[tuple[str, int]] = []
    seen: set[str] = set()
    for item in payload.prizes:
        name = item.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="奖项名称不能为空")
        if len(name) > 20:
            raise HTTPException(status_code=400, detail="奖项名称不能超过 20 个字符")
        if name in seen:
            raise HTTPException(status_code=400, detail=f"奖项名称重复：{name}")
        seen.add(name)
        normalized.append((name, item.count))

    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM prizes")
        conn.executemany(
            "INSERT INTO prizes (name, count, sort_order) VALUES (?, ?, ?)",
            [
                (name, count, index)
                for index, (name, count) in enumerate(normalized)
            ],
        )
        prizes = _list_prizes(conn)

    await manager.broadcast({"type": "prizes", "prizes": prizes})
    return {"success": True, "prizes": prizes}


@app.post("/api/draw")
async def draw_winners(count: int = Query(default=1, ge=1, le=10)) -> dict[str, Any]:
    """优先抽 must_win=1，排除 is_excluded=1，且不重复中奖。"""
    async with draw_lock:
        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")

            # 第一优先级：必中名单（随机排序），抽中后清除必中标记。
            rows = list(
                conn.execute(
                    f"""
                    SELECT {USER_COLUMNS}
                    FROM users
                    WHERE must_win = 1 AND is_excluded = 0 AND is_winner = 0
                    ORDER BY RANDOM()
                    LIMIT ?
                    """,
                    (count,),
                ).fetchall()
            )

            # 名额未满时，再从普通用户中随机补齐。
            remaining_slots = count - len(rows)
            if remaining_slots > 0:
                rows.extend(
                    conn.execute(
                        f"""
                        SELECT {USER_COLUMNS}
                        FROM users
                        WHERE must_win = 0 AND is_excluded = 0 AND is_winner = 0
                        ORDER BY RANDOM()
                        LIMIT ?
                        """,
                        (remaining_slots,),
                    ).fetchall()
                )

            if not rows:
                raise HTTPException(
                    status_code=400,
                    detail="没有可抽取的用户（可能已全部中奖或被排除），请先让同事扫码签到",
                )

            winner_ids = [row["id"] for row in rows]
            placeholders = ",".join("?" for _ in winner_ids)
            conn.execute(
                f"UPDATE users SET is_winner = 1, must_win = 0 WHERE id IN ({placeholders})",
                winner_ids,
            )

            winners = []
            for row in rows:
                winner = dict(row)
                winner["is_winner"] = 1
                winner["must_win"] = 0
                winners.append(winner)

            remaining = conn.execute(
                "SELECT COUNT(*) AS n FROM users "
                "WHERE is_excluded = 0 AND is_winner = 0"
            ).fetchone()["n"]
            total = _count_users(conn)

    await manager.broadcast(
        {
            "type": "draw",
            "winners": winners,
            "count": len(winners),
            "requested": count,
            "remaining": remaining,
            "total": total,
        }
    )
    return {
        "success": True,
        "winners": winners,
        "count": len(winners),
        "requested": count,
        "remaining": remaining,
    }


@app.post("/api/reset")
async def reset_winners() -> dict[str, Any]:
    """清空中奖标记，方便 Demo 反复演示。"""
    async with draw_lock:
        with db() as conn:
            conn.execute("UPDATE users SET is_winner = 0")
            total = _count_users(conn)
    await manager.broadcast({"type": "reset", "count": total})
    return {"success": True, "count": total}


# ---------------------------------------------------------------------------
# WebSocket：签到动态 + 弹幕广播
# ---------------------------------------------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    await manager.broadcast({"type": "online", "count": manager.count})
    try:
        while True:
            try:
                payload = await websocket.receive_json()
            except json.JSONDecodeError:
                continue  # 忽略非 JSON 消息

            if not isinstance(payload, dict):
                continue

            message_type = str(payload.get("type", "danmaku"))

            # 签到页把连接绑定到用户，断线时才能广播对应的 user_id。
            if message_type == "identify":
                try:
                    user_id = int(payload.get("user_id"))
                except (TypeError, ValueError):
                    continue
                if user_id <= 0:
                    continue
                with db() as conn:
                    exists = conn.execute(
                        "SELECT 1 FROM users WHERE id = ?", (user_id,)
                    ).fetchone()
                if not exists:
                    continue
                if manager.bind_user(websocket, user_id):
                    await manager.broadcast({"type": "join", "user_id": user_id})
                continue

            # 签到成功后的专属进场弹幕，按普通弹幕广播给大屏。
            if message_type == "enter_danmaku":
                name = (
                    str(payload.get("name", "")).strip()[:MAX_NAME_LENGTH] or "匿名"
                )
                text = (
                    str(payload.get("text", "")).strip()[:MAX_DANMAKU_LENGTH]
                    or "闪亮登场！"
                )
                await manager.broadcast(
                    {
                        "type": "danmaku",
                        "kind": "enter",
                        "name": name,
                        "text": text,
                        "time": datetime.now().strftime("%H:%M:%S"),
                    }
                )
                continue

            text = str(payload.get("text", "")).strip()
            if not text:
                continue

            name = str(payload.get("name", "")).strip()[:MAX_NAME_LENGTH] or "匿名"
            await manager.broadcast(
                {
                    "type": "danmaku",
                    "name": name,
                    "text": text[:MAX_DANMAKU_LENGTH],
                    "time": datetime.now().strftime("%H:%M:%S"),
                }
            )
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket 连接异常")
    finally:
        removed, user_id = manager.disconnect(websocket)
        if removed:
            await manager.broadcast({"type": "online", "count": manager.count})
        if user_id is not None:
            await _remove_disconnected_user(user_id)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
