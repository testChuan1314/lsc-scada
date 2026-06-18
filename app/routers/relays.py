from typing import Optional
from fastapi import APIRouter, HTTPException
import psycopg2, psycopg2.extras
from database import get_db
from models import RelayCreate, RelayUpdate

router = APIRouter(prefix="/api/relays", tags=["Relays"])

@router.get("")
def list_relays(esp_id: Optional[str] = None):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if esp_id: cur.execute("SELECT * FROM relay_instances WHERE esp_id=%s ORDER BY id", (esp_id,))
        else:      cur.execute("SELECT * FROM relay_instances ORDER BY id")
        rows = cur.fetchall(); cur.close()
    return [dict(r) for r in rows]

@router.post("", status_code=201)
def create_relay(body: RelayCreate):
    try:
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("INSERT INTO relay_instances (esp_id,channel,name,reg_address) VALUES (%s,%s,%s,%s) RETURNING *",
                        (body.esp_id, body.channel, body.name, body.reg_address))
            row = cur.fetchone(); cur.close()
        return dict(row)
    except psycopg2.errors.ForeignKeyViolation:
        raise HTTPException(400, f"ESP '{body.esp_id}' 不存在")

@router.put("/{relay_id}")
def update_relay(relay_id: int, body: RelayUpdate):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM relay_instances WHERE id=%s", (relay_id,))
        if not cur.fetchone(): cur.close(); raise HTTPException(404, "不存在")
        sets, vals = [], []
        for k in ("name","reg_address"):
            v = getattr(body, k)
            if v is not None: sets.append(f"{k}=%s"); vals.append(v)
        vals.append(relay_id)
        if sets: cur.execute(f"UPDATE relay_instances SET {','.join(sets)} WHERE id=%s RETURNING *", vals)
        else: cur.execute("SELECT * FROM relay_instances WHERE id=%s", (relay_id,))
        row = cur.fetchone(); cur.close()
    return dict(row)

@router.delete("/{relay_id}")
def delete_relay(relay_id: int):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM relay_instances WHERE id=%s", (relay_id,))
        if cur.rowcount == 0: cur.close(); raise HTTPException(404, "不存在")
        cur.close()
    return {"deleted": True}
