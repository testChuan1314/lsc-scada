"""InfluxDB 写入 & 查询"""
import logging
from datetime import datetime
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from config import INFLUX_URL, INFLUX_TOKEN, INFLUX_ORG, INFLUX_BUCKET

logger = logging.getLogger("scada-app")

_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
_write_api = _client.write_api(write_options=SYNCHRONOUS)
_query_api = _client.query_api()

def write_ts_point(esp_id: str, slave: int, sensor_key: str, value: float, ts: datetime, source: str = ""):
    point = (
        Point("sensor_data")
        .tag("esp_id", esp_id).tag("slave", str(slave)).tag("sensor", sensor_key)
        .tag("source", source).field("value", value).time(ts)
    )
    _write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)

def influx_query(flux: str) -> list[dict]:
    result = _query_api.query(flux, org=INFLUX_ORG)
    rows = []
    for table in result:
        for record in table.records:
            rows.append({
                "esp_id": record.values.get("esp_id", ""),
                "slave": record.values.get("slave", ""),
                "sensor": record.values.get("sensor", ""),
                "source": record.values.get("source", ""),
                "value": record.get_value(),
                "time": record.get_time().isoformat(),
            })
    return rows

def influx_query_latest(esp_id: str = "") -> list[dict]:
    filter_esp = f'|> filter(fn: (r) => r.esp_id == "{esp_id}")' if esp_id else ""
    flux = f'''
    from(bucket: "{INFLUX_BUCKET}") |> range(start: -5m)
      |> filter(fn: (r) => r._measurement == "sensor_data") |> filter(fn: (r) => r._field == "value")
      {filter_esp} |> last()
    '''
    rows = influx_query(flux)
    seen = {}
    for r in sorted(rows, key=lambda x: x["time"], reverse=True):
        key = (r.get("source") or r["esp_id"], r["sensor"])
        if key not in seen:
            seen[key] = r
    return list(seen.values())

def influx_query_series(esp_id: str = "", sensor: str = "", minutes: int = 10, limit: int = 200) -> list[dict]:
    filters = []
    if esp_id: filters.append(f'|> filter(fn: (r) => r.esp_id == "{esp_id}")')
    if sensor: filters.append(f'|> filter(fn: (r) => r.sensor == "{sensor}")')
    filter_str = "\n      ".join(filters)
    flux = f'''
    from(bucket: "{INFLUX_BUCKET}") |> range(start: -{minutes}m)
      |> filter(fn: (r) => r._measurement == "sensor_data") |> filter(fn: (r) => r._field == "value")
      {filter_str} |> limit(n: {limit})
    '''
    return influx_query(flux)

def influx_get_sensors() -> list[dict]:
    flux = f'''
    from(bucket: "{INFLUX_BUCKET}") |> range(start: -30m)
      |> filter(fn: (r) => r._measurement == "sensor_data") |> filter(fn: (r) => r._field == "value")
      |> keyValues(keyColumns: ["esp_id", "sensor"]) |> distinct()
    '''
    result = _query_api.query(flux, org=INFLUX_ORG)
    pairs = set()
    for table in result:
        for record in table.records:
            pairs.add((record.values.get("esp_id", ""), record.values.get("sensor", "")))
    return [{"esp_id": e, "sensor": s} for e, s in sorted(pairs)]
