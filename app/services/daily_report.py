"""日总结 —— 每天日落后推送每棵树的养护摘要"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from services.influx import influx_query
from config import INFLUX_BUCKET

logger = logging.getLogger("scada-alarm")


def generate_daily_summary(tree_id: Optional[int] = None):
    """生成日总结文本。tree_id 为 None 时生成所有树的。"""
    summaries = []

    # 获取所有有传感器的树
    from database import get_db
    import psycopg2.extras

    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if tree_id:
            cur.execute("""
                SELECT DISTINCT t.id, t.name, t.species, t.health_status,
                       si.esp_id
                FROM trees t
                JOIN sensor_instances si ON si.tree_id = t.id
                WHERE t.id = %s
            """, (tree_id,))
        else:
            cur.execute("""
                SELECT DISTINCT t.id, t.name, t.species, t.health_status,
                       si.esp_id
                FROM trees t
                JOIN sensor_instances si ON si.tree_id = t.id
            """)
        trees = cur.fetchall()
        cur.close()

    for tree in trees:
        stats = _fetch_tree_stats(tree["esp_id"], tree["id"])
        if not stats:
            continue

        summary = _format_summary(tree, stats)
        summaries.append(summary)

    return summaries


def _fetch_tree_stats(esp_id: str, tree_id: int) -> dict:
    """从 InfluxDB 拉取今天的数据统计"""
    now = datetime.now(timezone.utc)
    # 当天 00:00 UTC 开始
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    try:
        flux = f'''
        from(bucket: "{INFLUX_BUCKET}")
          |> range(start: {today_start.isoformat()})
          |> filter(fn: (r) => r._measurement == "sensor_data")
          |> filter(fn: (r) => r._field == "value")
          |> filter(fn: (r) => r.esp_id == "{esp_id}")
        '''
        rows = influx_query(flux)
    except Exception as e:
        logger.error(f"日总结 InfluxDB 查询失败 (esp={esp_id}): {e}")
        return {}

    if not rows:
        return {}

    stats = {}
    for sensor_key in ["temperature", "humidity", "soil_temp", "soil_moisture",
                        "conductivity", "lux", "rainfall"]:
        values = [r["value"] for r in rows if r.get("sensor") == sensor_key]
        if values:
            stats[sensor_key] = {
                "min": min(values),
                "max": max(values),
                "latest": values[-1],
            }

    # 计算 DLI (日光积分)
    if "lux" in stats:
        lux_avg = sum(v["max"] + v["min"] for v in [stats["lux"]]) / 2
        dli = lux_avg * 0.0185 * 24 / 1_000_000  # 粗略估算 mol/m²/d
        stats["dli"] = round(dli, 1)

    return stats


def _format_summary(tree: dict, stats: dict) -> str:
    """格式化单棵树的日总结"""
    name = tree["name"]
    species = tree.get("species", "")

    lines = [f"🌳 {name}（{species}）今日小结"]

    if "air_temp" in stats:
        t = stats["air_temp"]
        lines.append(f"  气温: {t['min']:.1f} ~ {t['max']:.1f}°C")

    if "soil_temp" in stats:
        t = stats["soil_temp"]
        lines.append(f"  土温: {t['min']:.1f} ~ {t['max']:.1f}°C")

    if "soil_moisture" in stats:
        m = stats["soil_moisture"]
        lines.append(f"  土壤湿度: {m['min']:.1f}% ~ {m['max']:.1f}%")

    if "conductivity" in stats:
        c = stats["conductivity"]
        lines.append(f"  EC: {c['latest']:.1f} μS/cm")

    if "dli" in stats:
        dli = stats["dli"]
        level = "充足" if dli > 15 else "一般" if dli > 8 else "不足"
        lines.append(f"  日光积分 DLI: {dli} ({level})")

    if "rainfall" in stats:
        rain_total = sum(v for v in stats["rainfall"].values() if isinstance(v, (int, float)))
        if rain_total > 0:
            lines.append(f"  今日降雨: {rain_total:.1f} mm")

    # 干旱评估
    if "soil_moisture" in stats:
        sm = stats["soil_moisture"]["latest"]
        if sm < 25:
            lines.append("  ⚠️ 土壤偏干，建议明天浇水")
        elif sm > 80:
            lines.append("  ℹ️ 土壤偏湿，注意排水")

    return "\n".join(lines)
