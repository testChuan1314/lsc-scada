from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
import psycopg2, psycopg2.extras
from database import get_db
from models import SensorInstanceCreate, SensorInstanceUpdate
from services.auth import get_current_user, require_permission, area_filter_sql

router = APIRouter(prefix="/api/instances", tags=["Instances"])

@router.get("")
def list_instances(esp_id: Optional[str] = None, user = Depends(get_current_user)):
    af = area_filter_sql(user, "e.area_id")
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        base = """SELECT si.*, t.model, b.brand_name, tr.name AS tree_name
            FROM sensor_instances si
            JOIN sensor_templates t ON si.template_id=t.id
            JOIN sensor_brands b ON t.brand_id=b.id
            JOIN esp_devices e ON si.esp_id=e.esp_id
            LEFT JOIN trees tr ON si.tree_id=tr.id"""
        if esp_id:
            cur.execute(f"{base} WHERE si.esp_id=%s AND {af} ORDER BY si.id", (esp_id,))
        else:
            cur.execute(f"{base} WHERE {af} ORDER BY si.id")
        rows = cur.fetchall(); cur.close()
    return [dict(r) for r in rows]

@router.post("", status_code=201)
def create_instance(body: SensorInstanceCreate, user = Depends(require_permission("sensor:write"))):
    try:
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("INSERT INTO sensor_instances (esp_id,template_id,slave_address,custom_name,tree_id) VALUES (%s,%s,%s,%s,%s) RETURNING *",
                        (body.esp_id, body.template_id, body.slave_address, body.custom_name, body.tree_id))
            row = cur.fetchone(); cur.close()
        return dict(row)
    except psycopg2.errors.ForeignKeyViolation as e:
        raise HTTPException(400, f"外键约束: {e}")

@router.put("/{instance_id}")
def update_instance(instance_id: int, body: SensorInstanceUpdate, user = Depends(require_permission("sensor:write"))):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM sensor_instances WHERE id=%s", (instance_id,))
        if not cur.fetchone(): cur.close(); raise HTTPException(404, "不存在")
        sets, vals = [], []
        for k in ("slave_address","custom_name","tree_id"):
            v = getattr(body, k)
            if v is not None: sets.append(f"{k}=%s"); vals.append(v)
        vals.append(instance_id)
        if sets: cur.execute(f"UPDATE sensor_instances SET {','.join(sets)} WHERE id=%s RETURNING *", vals)
        else: cur.execute("SELECT * FROM sensor_instances WHERE id=%s", (instance_id,))
        row = cur.fetchone(); cur.close()
    return dict(row)

@router.delete("/{instance_id}")
def delete_instance(instance_id: int, user = Depends(require_permission("sensor:write"))):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM sensor_instances WHERE id=%s", (instance_id,))
        if cur.rowcount == 0: cur.close(); raise HTTPException(404, "不存在")
        cur.close()
    return {"deleted": True}
