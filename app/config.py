"""环境变量"""
import os

MQTT_HOST     = os.getenv("MQTT_HOST",     "localhost")
MQTT_PORT     = int(os.getenv("MQTT_PORT", "1883"))
DB_HOST       = os.getenv("DB_HOST",       "localhost")
DB_USER       = os.getenv("DB_USER",       "lsc_admin")
DB_PASSWORD   = os.getenv("DB_PASSWORD",   "lsc_password_2026")
DB_NAME       = os.getenv("DB_NAME",       "lsc_scada")
INFLUX_URL    = os.getenv("INFLUX_URL",    "http://localhost:8086")
INFLUX_TOKEN  = os.getenv("INFLUX_TOKEN",  "lsc-token-2026")
INFLUX_ORG    = os.getenv("INFLUX_ORG",    "lsc-scada")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "scada")
