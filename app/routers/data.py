from typing import Optional
from fastapi import APIRouter, Query
from services.influx import influx_query_latest, influx_query_series, influx_get_sensors

router = APIRouter(prefix="/api/data", tags=["Data"])

@router.get("/latest")
def api_latest(esp_id: str = ""):
    return influx_query_latest(esp_id)

@router.get("/query")
def api_query(esp_id: str = "", sensor: str = "", minutes: int = 10, limit: int = 200):
    return influx_query_series(esp_id=esp_id, sensor=sensor, minutes=minutes, limit=limit)

@router.get("/sensors")
def api_sensors():
    return influx_get_sensors()
