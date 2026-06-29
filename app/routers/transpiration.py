"""蒸腾作用 API —— VPD / CWSI / ET₀"""
from typing import Optional
from fastapi import APIRouter, Depends
from services.transpiration import fetch_and_assess, assess_transpiration, DEFAULT_LAT
from services.auth import get_current_user
from datetime import datetime, timezone

router = APIRouter(prefix="/api/transpiration", tags=["Transpiration"])


@router.get("/vpd")
def api_vpd(esp_id: str = "", user=Depends(get_current_user)):
    """获取 VPD 值及植物生理意义"""
    results = fetch_and_assess(esp_id)
    return [
        {
            "source": r["source"],
            "esp_id": r["esp_id"],
            "vpd_air": r["vpd_air"],
            "vpd_leaf": r["vpd_leaf"],
            "level": r["vpd_level"],
            "label_cn": r["vpd_label"],
            "color": r["vpd_color"],
            "stomata": r["vpd_stomata"],
            "effect": r["vpd_effect"],
            "suggestion": r["vpd_suggestion"],
        }
        for r in results
    ]


@router.get("/summary")
def api_summary(esp_id: str = "", user=Depends(get_current_user)):
    """获取完整蒸腾评估"""
    results = fetch_and_assess(esp_id)
    return results


@router.get("/et0")
def api_et0(
    T_max: Optional[float] = None,
    T_min: Optional[float] = None,
    lat: float = DEFAULT_LAT,
    user=Depends(get_current_user),
):
    """计算当日 ET₀ 参考蒸散量 (mm/day)

    如果未传 T_max/T_min，则从 InfluxDB 中查询今日数据。
    """
    now = datetime.now(timezone.utc)
    doy = now.timetuple().tm_yday

    if T_max is not None and T_min is not None:
        from services.transpiration import compute_et0_hargreaves
        et0 = compute_et0_hargreaves(T_max, T_min, lat, doy)
        return {
            "et0_mm": round(et0, 2),
            "note": f"基于 T_max={T_max}°C T_min={T_min}°C 第{doy}天 lat={lat}°",
        }

    # 从 InfluxDB 查
    from services.influx import influx_query
    from config import INFLUX_BUCKET
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        flux = f'''
        from(bucket: "{INFLUX_BUCKET}")
          |> range(start: {today_start.isoformat()})
          |> filter(fn: (r) => r._measurement == "sensor_data")
          |> filter(fn: (r) => r._field == "value")
          |> filter(fn: (r) => r.sensor == "temperature" or r.sensor == "空气温度")
        '''
        rows = influx_query(flux)
        values = [r["value"] for r in rows if r.get("value") is not None]
        if values:
            t_max = max(values)
            t_min = min(values)
            from services.transpiration import compute_et0_hargreaves
            et0 = compute_et0_hargreaves(t_max, t_min, lat, doy)
            return {
                "et0_mm": round(et0, 2),
                "T_max": round(t_max, 1),
                "T_min": round(t_min, 1),
                "note": f"基于今日实际气温 {t_min:.1f}~{t_max:.1f}°C",
            }
    except Exception as e:
        return {"error": str(e)}

    return {"et0_mm": None, "note": "无气温数据"}
