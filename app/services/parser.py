"""Modbus RTU 帧解析 + 模板驱动解析引擎"""
import struct
import logging
from typing import Optional
import psycopg2.extras
from database import get_db

logger = logging.getLogger("scada-app")

def load_template_with_polling(template_id: int) -> Optional[dict]:
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM sensor_templates WHERE id=%s", (template_id,))
        row = cur.fetchone(); cur.close()
    return dict(row) if row else None

def load_template_registers(template_id: int) -> list[dict]:
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM register_definitions WHERE template_id=%s ORDER BY reg_address", (template_id,))
        rows = cur.fetchall(); cur.close()
    return [dict(r) for r in rows]

def load_instance_by_esp_and_slave(esp_id: str, slave_address: int) -> Optional[dict]:
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM sensor_instances WHERE esp_id=%s AND slave_address=%s", (esp_id, slave_address))
        row = cur.fetchone(); cur.close()
    return dict(row) if row else None

def parse_modbus_hex(data_hex: str, registers: list[dict], base_address: int = 0) -> dict:
    """绝对地址解析——跳过寄存器空洞"""
    raw = bytes.fromhex(data_hex)
    result = {}
    for reg in registers:
        offset = (reg["reg_address"] - base_address) * 2
        dtype = reg["data_type"]
        size = {"uint16": 2, "int16": 2, "uint32": 4, "float32": 4}.get(dtype, 2)
        if offset < 0 or offset + size > len(raw):
            continue
        chunk = raw[offset:offset + size]
        if dtype == "uint16":   val = struct.unpack(">H", chunk)[0]
        elif dtype == "int16":  val = struct.unpack(">h", chunk)[0]
        elif dtype == "uint32": val = struct.unpack(">I", chunk)[0]
        elif dtype == "float32":val = struct.unpack(">f", chunk)[0]
        else:                   val = struct.unpack(">H", chunk)[0]
        val = val * reg["multiplier"]
        result[reg["reg_name"]] = round(val, 4)
    return result

def parse_rtu_frame(hex_str: str) -> Optional[tuple]:
    """拆 RTU 帧 → (slave_addr, data_hex)"""
    raw = bytes.fromhex(hex_str)
    if len(raw) < 4:
        return None
    slave_addr  = raw[0]
    byte_count  = raw[2]
    data_bytes  = raw[3:3 + byte_count]
    return slave_addr, data_bytes.hex()
