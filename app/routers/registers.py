from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
import psycopg2, psycopg2.extras
from database import get_db
from models import RegisterCreate, RegisterUpdate
from services.auth import require_permission

router = APIRouter(prefix="/api/registers", tags=["Registers"])

@router.get("")
def list_registers(template_id: Optional[int] = None):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if template_id:
            cur.execute("SELECT * FROM register_definitions WHERE template_id=%s ORDER BY reg_address", (template_id,))
        else:
            cur.execute("SELECT * FROM register_definitions ORDER BY id")
        rows = cur.fetchall(); cur.close()
    return [dict(r) for r in rows]

@router.post("", status_code=201)
def create_register(body: RegisterCreate):
    try:
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("INSERT INTO register_definitions (template_id,reg_address,reg_name,data_type,multiplier,unit,description) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                        (body.template_id, body.reg_address, body.reg_name, body.data_type, body.multiplier, body.unit, body.description))
            row = cur.fetchone(); cur.close()
        return dict(row)
    except psycopg2.errors.ForeignKeyViolation:
        raise HTTPException(400, "模板不存在")

@router.put("/{reg_id}")
def update_register(reg_id: int, body: RegisterUpdate):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM register_definitions WHERE id=%s", (reg_id,))
        if not cur.fetchone(): cur.close(); raise HTTPException(404, "不存在")
        sets, vals = [], []
        for k in ("reg_name","data_type","multiplier","unit","description"):
            v = getattr(body, k)
            if v is not None: sets.append(f"{k}=%s"); vals.append(v)
        vals.append(reg_id)
        if sets: cur.execute(f"UPDATE register_definitions SET {','.join(sets)} WHERE id=%s RETURNING *", vals)
        else: cur.execute("SELECT * FROM register_definitions WHERE id=%s", (reg_id,))
        row = cur.fetchone(); cur.close()
    return dict(row)

@router.delete("/{reg_id}")
def delete_register(reg_id: int):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM register_definitions WHERE id=%s", (reg_id,))
        if cur.rowcount == 0: cur.close(); raise HTTPException(404, "不存在")
        cur.close()
    return {"deleted": True}
