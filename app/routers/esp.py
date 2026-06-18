from fastapi import APIRouter, HTTPException
import psycopg2, psycopg2.extras
from database import get_db
from models import EspCreate, EspUpdate

router = APIRouter(prefix="/api/esp", tags=["ESP"])

@router.get("")
def list_esp():
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT e.*, a.name AS area_name FROM esp_devices e LEFT JOIN areas a ON e.area_id=a.id ORDER BY e.id"); rows = cur.fetchall(); cur.close()
    return [dict(r) for r in rows]

@router.post("", status_code=201)
def create_esp(body: EspCreate):
    try:
        with get_db() as conn:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("INSERT INTO esp_devices (esp_id,name,location,mqtt_topic,area_id) VALUES (%s,%s,%s,%s,%s) RETURNING *",
                        (body.esp_id, body.name, body.location, body.mqtt_topic, body.area_id))
            row = cur.fetchone(); cur.close()
        return dict(row)
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(400, f"ESP '{body.esp_id}' 已存在")

@router.put("/{esp_id}")
def update_esp(esp_id: str, body: EspUpdate):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM esp_devices WHERE esp_id=%s", (esp_id,))
        if not cur.fetchone(): cur.close(); raise HTTPException(404, "不存在")
        sets, vals = [], []
        for k in ("name","location","mqtt_topic","area_id"):
            v = getattr(body, k)
            if v is not None: sets.append(f"{k}=%s"); vals.append(v)
        vals.append(esp_id)
        if sets: cur.execute(f"UPDATE esp_devices SET {','.join(sets)} WHERE esp_id=%s RETURNING *", vals)
        else: cur.execute("SELECT * FROM esp_devices WHERE esp_id=%s", (esp_id,))
        row = cur.fetchone(); cur.close()
    return dict(row)

@router.delete("/{esp_id}")
def delete_esp(esp_id: str):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM esp_devices WHERE esp_id=%s", (esp_id,))
        if cur.rowcount == 0: cur.close(); raise HTTPException(404, "不存在")
        cur.close()
    return {"deleted": True}
