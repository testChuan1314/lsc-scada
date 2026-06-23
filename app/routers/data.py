from typing import Optional
from fastapi import APIRouter, Depends
from services.influx import influx_query_latest, influx_query_series, influx_get_sensors
from services.auth import get_current_user, get_user_area_ids

router = APIRouter(prefix="/api/data", tags=["Data"])

@router.get("/latest")
def api_latest(esp_id: str = "", user = Depends(get_current_user)):
    area_ids = get_user_area_ids(user)
    if area_ids is not None:
        # 查出管辖区域下的 ESP
        from database import get_db
        import psycopg2.extras
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT esp_id FROM esp_devices WHERE area_id IN %s", (tuple(area_ids),))
            allowed = [r[0] for r in cur.fetchall()]; cur.close()
        return influx_query_latest(esp_id) if not allowed else [d for d in influx_query_latest(esp_id) if d["esp_id"] in allowed]
    return influx_query_latest(esp_id)

@router.get("/query")
def api_query(esp_id: str = "", sensor: str = "", minutes: int = 10, limit: int = 200, user = Depends(get_current_user)):
    area_ids = get_user_area_ids(user)
    if area_ids is not None:
        from database import get_db
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT esp_id FROM esp_devices WHERE area_id IN %s", (tuple(area_ids),))
            allowed = [r[0] for r in cur.fetchall()]; cur.close()
        if esp_id and esp_id not in allowed:
            return []
        return [d for d in influx_query_series(esp_id, sensor, minutes, limit) if d["esp_id"] in allowed]
    return influx_query_series(esp_id, sensor, minutes, limit)

@router.get("/sensors")
def api_sensors(user = Depends(get_current_user)):
    area_ids = get_user_area_ids(user)
    result = influx_get_sensors()
    if area_ids is not None:
        from database import get_db
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT esp_id FROM esp_devices WHERE area_id IN %s", (tuple(area_ids),))
            allowed = [r[0] for r in cur.fetchall()]; cur.close()
        return [s for s in result if s["esp_id"] in allowed]
    return result
