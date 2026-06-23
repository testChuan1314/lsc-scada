"""MQTT 回调 —— 收数据解析 + 写 InfluxDB"""
import json
import logging
from datetime import datetime, timezone
import paho.mqtt.client as mqtt_lib
from config import MQTT_HOST, MQTT_PORT
from services.parser import (
    parse_rtu_frame, load_instance_by_esp_and_slave,
    load_template_with_polling, load_template_registers, parse_modbus_hex,
)
from services.influx import write_ts_point
from services.alarm.engine import record_esp_activity

logger = logging.getLogger("scada-app")
mqtt_client = mqtt_lib.Client(client_id="lsc_scada_app")

def on_connect(client, userdata, flags, rc):
    logger.info(f"MQTT 已连接 (rc={rc})")
    client.subscribe("lsc/devices/+/data")
    client.subscribe("lsc/devices/+/input")

def on_message(client, userdata, msg):
    try:
        topic_parts = msg.topic.split("/")
        esp_id = topic_parts[2]
        payload = msg.payload.decode("utf-8").strip()

        # 记录 ESP 活跃时间（用于心跳检测）
        record_esp_activity(esp_id)

        if topic_parts[-1] == "input":
            logger.info(f"光耦输入 esp={esp_id} → {payload}")
            return

        logger.info(f"收到 esp={esp_id} payload={payload}")
        hex_str = payload.strip()
        if len(hex_str) < 6:
            return

        frame = parse_rtu_frame(hex_str)
        if not frame:
            return
        slave_addr, data_hex = frame

        inst = load_instance_by_esp_and_slave(esp_id, slave_addr)
        if not inst:
            logger.warning(f"未找到实例: esp={esp_id} slave=0x{slave_addr:02X}")
            return

        tpl  = load_template_with_polling(inst["template_id"])
        regs = load_template_registers(inst["template_id"])
        if not regs:
            return

        base_addr = tpl["poll_start_addr"] if tpl else 0
        tpl_desc = tpl.get("description", "") if tpl else ""
        tpl_model = tpl.get("model", "") if tpl else ""
        custom = inst.get("custom_name", "") or ""
        if custom and tpl_model:
            source_name = f"{custom} ({tpl_model})"
        elif tpl_desc and tpl_model:
            source_name = f"{tpl_desc} {tpl_model}"
        else:
            source_name = custom or tpl_model or f"{esp_id}-s{slave_addr}"

        reg_desc_map = {r["reg_name"]: r.get("description", "") or r["reg_name"] for r in regs}
        parsed = parse_modbus_hex(data_hex, regs, base_address=base_addr)
        now = datetime.now(timezone.utc)
        for k, v in parsed.items():
            sensor_label = reg_desc_map.get(k, k)
            write_ts_point(esp_id, slave_addr, sensor_label, v, now, source=source_name)

        logger.info(f"解析 {source_name} slave=0x{slave_addr:02X} base=0x{base_addr:04X} → {parsed}")

    except Exception as e:
        logger.error(f"消息处理异常: {e}", exc_info=True)
