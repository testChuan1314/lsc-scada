from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
import psycopg2, psycopg2.extras
from database import get_db
from models import AreaCreate, AreaUpdate
from services.auth import get_current_user, require_permission

router = APIRouter(prefix="/api/areas", tags=["Areas"])

@router.get("")
def list_areas(user = Depends(get_current_user)):
    from services.auth import area_filter_sql
    af = area_filter_sql(user, "a.id")
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(f"""SELECT a.*, COUNT(DISTINCT e.id) AS esp_count, COUNT(DISTINCT t.id) AS tree_count
            FROM areas a LEFT JOIN esp_devices e ON e.area_id=a.id LEFT JOIN trees t ON t.area_id=a.id
            WHERE {af} GROUP BY a.id ORDER BY a.id""")
        rows = cur.fetchall(); cur.close()
    return [dict(r) for r in rows]

@router.post("", status_code=201)
def create_area(body: AreaCreate, user = Depends(require_permission("area:write"))):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("INSERT INTO areas (name,parent_id,description) VALUES (%s,%s,%s) RETURNING *",
                    (body.name, body.parent_id, body.description))
        row = cur.fetchone(); cur.close()
    return dict(row)

@router.put("/{area_id}")
def update_area(area_id: int, body: AreaUpdate, user = Depends(require_permission("area:write"))):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM areas WHERE id=%s", (area_id,))
        if not cur.fetchone(): cur.close(); raise HTTPException(404, "不存在")
        sets, vals = [], []
        for k in ("name","parent_id","description"):
            v = getattr(body, k)
            if v is not None: sets.append(f"{k}=%s"); vals.append(v)
        vals.append(area_id)
        if sets: cur.execute(f"UPDATE areas SET {','.join(sets)} WHERE id=%s RETURNING *", vals)
        else: cur.execute("SELECT * FROM areas WHERE id=%s", (area_id,))
        row = cur.fetchone(); cur.close()
    return dict(row)

@router.delete("/{area_id}")
def delete_area(area_id: int, user = Depends(require_permission("area:write"))):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM areas WHERE id=%s", (area_id,))
        if cur.rowcount == 0: cur.close(); raise HTTPException(404, "不存在")
        cur.close()
    return {"deleted": True}
