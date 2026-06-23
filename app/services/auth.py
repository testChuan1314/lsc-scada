"""权限校验 + JWT 认证"""
import os, logging
from typing import Optional
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, Depends, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
import psycopg2.extras
from database import get_db

logger = logging.getLogger("scada-app")

# JWT 配置
SECRET_KEY = os.getenv("JWT_SECRET", "chuanfeng-jingyun-2026-wenjiang-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_access_token(user_id: int, username: str, role_code: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    return jwt.encode({"sub": str(user_id), "username": username, "role": role_code, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    x_user_id: Optional[str] = Header(None),
):
    """优先 Bearer Token，兼容旧 x-user-id header"""
    user_id = None
    if credentials:
        payload = decode_token(credentials.credentials)
        if payload:
            user_id = payload.get("sub")
    elif x_user_id:
        user_id = x_user_id
    if not user_id:
        return None
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT u.*, r.code AS role_code FROM users u LEFT JOIN roles r ON u.role_id=r.id WHERE u.id=%s AND u.is_active=true", (user_id,))
        u = cur.fetchone(); cur.close()
    return dict(u) if u else None

def require_permission(perm_code: str):
    async def checker(user = Depends(get_current_user)):
        if not user: raise HTTPException(401, "未登录")
        if user.get("role_code") == "admin": return user
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM role_permissions rp JOIN permissions p ON rp.permission_id=p.id WHERE rp.role_id=%s AND p.code=%s", (user["role_id"], perm_code))
            ok = cur.fetchone(); cur.close()
        if not ok: raise HTTPException(403, f"无权限: {perm_code}")
        return user
    return checker

def get_user_area_ids(user: dict) -> Optional[list[int]]:
    if not user or user.get("role_code") == "admin": return None
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT area_id FROM user_areas WHERE user_id=%s", (user["id"],))
        ids = [r[0] for r in cur.fetchall()]; cur.close()
    return ids if ids else [-1]

def area_filter_sql(user: dict, table_alias: str = "area_id") -> str:
    ids = get_user_area_ids(user)
    if ids is None: return "1=1"
    return f"{table_alias} IN ({','.join(map(str,ids))})"
