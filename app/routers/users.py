"""用户管理 + 角色 + 权限"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Header
import psycopg2, psycopg2.extras
from database import get_db
from models import UserCreate, UserUpdate, UserAreaUpdate
from services.auth import get_current_user, require_permission, verify_password, create_access_token
from pydantic import BaseModel

class LoginRequest(BaseModel):
    username: str
    password: str

router = APIRouter(prefix="/api", tags=["Users"])

@router.post("/auth/login")
def login(body: LoginRequest):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT u.*, r.code AS role_code, r.name AS role_name FROM users u LEFT JOIN roles r ON u.role_id=r.id WHERE u.username=%s AND u.is_active=true", (body.username,))
        u = cur.fetchone(); cur.close()
    if not u or not verify_password(body.password, u["password_hash"]):
        raise HTTPException(401, "用户名或密码错误")
    token = create_access_token(u["id"], u["username"], u["role_code"])
    return {"token": token, "user": {"id": u["id"], "username": u["username"], "display_name": u["display_name"], "role_name": u["role_name"], "role_code": u["role_code"]}}

# ==================== 用户 CRUD ====================
@router.get("/users")
def list_users(user = Depends(require_permission("user:manage"))):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT u.*, r.name AS role_name, r.code AS role_code, COALESCE(array_agg(ua.area_id) FILTER(WHERE ua.area_id IS NOT NULL),'{}') AS area_ids FROM users u LEFT JOIN roles r ON u.role_id=r.id LEFT JOIN user_areas ua ON u.id=ua.user_id GROUP BY u.id, r.name, r.code ORDER BY u.id")
        rows = cur.fetchall(); cur.close()
    return [dict(r) for r in rows]

@router.post("/users", status_code=201)
def create_user(body: UserCreate, user = Depends(require_permission("user:manage"))):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("INSERT INTO users (display_name,phone,wechat_openid,wechat_nickname,wechat_avatar,role_id) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
                    (body.display_name, body.phone, body.wechat_openid, body.wechat_nickname, body.wechat_avatar, body.role_id))
        row = cur.fetchone(); cur.close()
    return dict(row)

@router.put("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, user = Depends(require_permission("user:manage"))):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM users WHERE id=%s", (user_id,))
        if not cur.fetchone(): cur.close(); raise HTTPException(404, "用户不存在")
        sets, vals = [], []
        for k in ("display_name","phone","role_id","is_active","wechat_nickname","wechat_avatar"):
            v = getattr(body, k)
            if v is not None: sets.append(f"{k}=%s"); vals.append(v)
        vals.append(user_id)
        if sets: cur.execute(f"UPDATE users SET {','.join(sets)} WHERE id=%s RETURNING *", vals)
        else: cur.execute("SELECT * FROM users WHERE id=%s", (user_id,))
        row = cur.fetchone(); cur.close()
    return dict(row)

@router.delete("/users/{user_id}")
def delete_user(user_id: int, user = Depends(require_permission("user:manage"))):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
        if cur.rowcount == 0: cur.close(); raise HTTPException(404, "不存在")
        cur.close()
    return {"deleted": True}

@router.get("/users/{user_id}/areas")
def get_user_areas(user_id: int, user = Depends(require_permission("user:manage"))):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT a.* FROM areas a JOIN user_areas ua ON a.id=ua.area_id WHERE ua.user_id=%s", (user_id,))
        rows = cur.fetchall(); cur.close()
    return [dict(r) for r in rows]

@router.put("/users/{user_id}/areas")
def update_user_areas(user_id: int, body: UserAreaUpdate, user = Depends(require_permission("user:manage"))):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM user_areas WHERE user_id=%s", (user_id,))
        for aid in body.area_ids:
            cur.execute("INSERT INTO user_areas (user_id,area_id) VALUES (%s,%s)", (user_id, aid))
        cur.close()
    return {"status": "ok"}

@router.get("/roles")
def list_roles():
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT r.*, COALESCE(array_agg(p.code) FILTER(WHERE p.code IS NOT NULL),'{}') AS permissions FROM roles r LEFT JOIN role_permissions rp ON r.id=rp.role_id LEFT JOIN permissions p ON rp.permission_id=p.id GROUP BY r.id ORDER BY r.id")
        rows = cur.fetchall(); cur.close()
    return [dict(r) for r in rows]

@router.get("/permissions")
def list_permissions():
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM permissions ORDER BY resource, action")
        rows = cur.fetchall(); cur.close()
    return [dict(r) for r in rows]
