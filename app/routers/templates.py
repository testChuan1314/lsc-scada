from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
import psycopg2, psycopg2.extras
from database import get_db
from models import TemplateCreate, TemplateUpdate
from services.auth import require_permission

router = APIRouter(prefix="/api/templates", tags=["Templates"])

@router.get("")
def list_templates(brand_id: Optional[int] = None):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if brand_id:
            cur.execute("SELECT t.*, b.brand_name FROM sensor_templates t JOIN sensor_brands b ON t.brand_id=b.id WHERE t.brand_id=%s ORDER BY t.id", (brand_id,))
        else:
            cur.execute("SELECT t.*, b.brand_name FROM sensor_templates t JOIN sensor_brands b ON t.brand_id=b.id ORDER BY t.id")
        rows = cur.fetchall(); cur.close()
    return [dict(r) for r in rows]

@router.post("", status_code=201)
def create_template(body: TemplateCreate, user = Depends(require_permission("sensor:write"))):
    try:
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("INSERT INTO sensor_templates (brand_id,model,description,baud_rate,poll_start_addr,poll_count) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
                        (body.brand_id, body.model, body.description, body.baud_rate, body.poll_start_addr, body.poll_count))
            row = cur.fetchone(); cur.close()
        return dict(row)
    except psycopg2.errors.ForeignKeyViolation: raise HTTPException(400, "品牌不存在")
    except psycopg2.errors.UniqueViolation:      raise HTTPException(400, "型号已存在")

@router.put("/{template_id}")
def update_template(template_id: int, body: TemplateUpdate):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM sensor_templates WHERE id=%s", (template_id,))
        if not cur.fetchone(): cur.close(); raise HTTPException(404, "不存在")
        sets, vals = [], []
        for k in ("model","description","baud_rate","poll_start_addr","poll_count"):
            v = getattr(body, k)
            if v is not None: sets.append(f"{k}=%s"); vals.append(v)
        vals.append(template_id)
        if sets: cur.execute(f"UPDATE sensor_templates SET {','.join(sets)} WHERE id=%s RETURNING *", vals)
        else: cur.execute("SELECT * FROM sensor_templates WHERE id=%s", (template_id,))
        row = cur.fetchone(); cur.close()
    return dict(row)

@router.delete("/{template_id}")
def delete_template(template_id: int):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM sensor_templates WHERE id=%s", (template_id,))
        if cur.rowcount == 0: cur.close(); raise HTTPException(404, "不存在")
        cur.close()
    return {"deleted": True}
