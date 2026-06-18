"""配置下发引擎 —— 生成 polling JSON + MQTT 推送"""
import json
import logging
from datetime import datetime, timezone
import psycopg2.extras
from database import get_db
from services.mqtt import mqtt_client

logger = logging.getLogger("scada-app")

def generate_polling_config(esp_id: str) -> dict:
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT si.slave_address, t.poll_start_addr, t.poll_count, t.baud_rate
            FROM sensor_instances si JOIN sensor_templates t ON si.template_id=t.id
            WHERE si.esp_id=%s ORDER BY si.slave_address
        """, (esp_id,))
        polls = [{"slave": r["slave_address"], "start": r["poll_start_addr"],
                  "count": r["poll_count"], "interval": 5000} for r in cur.fetchall()]
        cur.execute("SELECT channel, name, reg_address FROM relay_instances WHERE esp_id=%s ORDER BY channel", (esp_id,))
        relays = [dict(r) for r in cur.fetchall()]
        cur.close()
    return {"polls": polls, "relays": relays, "timestamp": datetime.now(timezone.utc).isoformat()}

def push_config_to_esp(esp_id: str) -> dict:
    config = generate_polling_config(esp_id)
    topic = f"lsc/devices/{esp_id}/config"
    payload = json.dumps(config, ensure_ascii=False)
    mqtt_client.publish(topic, payload, qos=1, retain=True)
    logger.info(f"配置下发 → {topic}")
    return config

def push_relay_cmd(esp_id: str, channel: int, on: bool) -> dict:
    cmd = {"relay": {"channel": channel, "on": on}, "timestamp": datetime.now(timezone.utc).isoformat()}
    topic = f"lsc/devices/{esp_id}/config"
    payload = json.dumps(cmd, ensure_ascii=False)
    mqtt_client.publish(topic, payload, qos=1)
    logger.info(f"继电器指令 → {topic} : {payload}")
    return cmd
