from fastapi import APIRouter, HTTPException
import psycopg2, psycopg2.extras
from database import get_db
from models import BrandCreate, BrandUpdate

router = APIRouter(prefix="/api/brands", tags=["Brands"])

@router.get("")
def list_brands():
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM sensor_brands ORDER BY id"); rows = cur.fetchall(); cur.close()
    return [dict(r) for r in rows]

@router.post("", status_code=201)
def create_brand(body: BrandCreate):
    try:
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("INSERT INTO sensor_brands (brand_name,website) VALUES (%s,%s) RETURNING *",
                        (body.brand_name, body.website))
            row = cur.fetchone(); cur.close()
        return dict(row)
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(400, f"品牌 '{body.brand_name}' 已存在")

@router.put("/{brand_id}")
def update_brand(brand_id: int, body: BrandUpdate):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM sensor_brands WHERE id=%s", (brand_id,))
        if not cur.fetchone(): cur.close(); raise HTTPException(404, "不存在")
        sets, vals = [], []
        for k in ("brand_name","website"):
            v = getattr(body, k)
            if v is not None: sets.append(f"{k}=%s"); vals.append(v)
        vals.append(brand_id)
        if sets: cur.execute(f"UPDATE sensor_brands SET {','.join(sets)} WHERE id=%s RETURNING *", vals)
        else: cur.execute("SELECT * FROM sensor_brands WHERE id=%s", (brand_id,))
        row = cur.fetchone(); cur.close()
    return dict(row)

@router.delete("/{brand_id}")
def delete_brand(brand_id: int):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM sensor_brands WHERE id=%s", (brand_id,))
        if cur.rowcount == 0: cur.close(); raise HTTPException(404, "不存在")
        cur.close()
    return {"deleted": True}
