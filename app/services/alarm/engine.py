"""告警引擎 —— 独立线程，定时轮询 InfluxDB，运行所有规则，推送通知"""
import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

from .context import TemporalContext
from .rules import (
    SensorWindow, AlarmVerdict,
    LAYER0_RULES, LAYER1_RULES, LAYER2_RULES,
    check_esp_heartbeat,
)
from .state import alarm_state_machine, AlarmState
from .notify import send_notifications

from services.influx import influx_query

logger = logging.getLogger("scada-alarm")

# 全局 ESP 最后活跃时间
_esp_last_seen: Dict[str, datetime] = {}
_esp_last_seen_lock = threading.Lock()


def record_esp_activity(esp_id: str, ts: Optional[datetime] = None):
    """MQTT 回调中调用，记录 ESP 最后活跃时间"""
    with _esp_last_seen_lock:
        _esp_last_seen[esp_id] = ts or datetime.now(timezone.utc)


class AlarmEngine:
    """告警引擎 —— 同步定时循环，跑在独立 daemon 线程里"""

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        """启动引擎"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="alarm-engine")
        self._thread.start()
        logger.info("告警引擎已启动（独立线程）")

    def stop(self):
        """停止引擎"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("告警引擎已停止")

    # ── 主循环 ──

    def _loop(self):
        """主循环：每 30 秒跑 Layer 0 + 心跳，每 5 分钟跑 Layer 1 + Layer 2"""
        fast_ticks = 0
        while self._running:
            try:
                now = datetime.now(timezone.utc)
                ctx = TemporalContext.at(now)
                fast_ticks += 1

                # ══ 快周期：每次（数据质量 + 心跳）══
                windows = self._fetch_all_sensor_windows(now, lookback_minutes=15)
                for win in windows:
                    for rule_fn in LAYER0_RULES:
                        try:
                            verdicts = rule_fn(win, ctx)
                            if verdicts:
                                notifications = alarm_state_machine.process_verdicts(verdicts, now)
                                send_notifications(notifications)
                        except Exception as e:
                            logger.error(f"规则 {rule_fn.__name__} 失败: {e}")

                self._check_esp_heartbeats(now)

                # ══ 慢周期：每 10 个快周期（≈5 分钟）═
                if fast_ticks % 10 == 0:
                    logger.debug("触发慢周期评估 (Layer 1 + 2)")
                    windows = self._fetch_all_sensor_windows(now, lookback_minutes=30)

                    for win in windows:
                        for rule_fn in LAYER1_RULES:
                            try:
                                verdicts = rule_fn(win, ctx)
                                if verdicts:
                                    notifications = alarm_state_machine.process_verdicts(verdicts, now)
                                    send_notifications(notifications)
                            except Exception as e:
                                logger.error(f"规则 {rule_fn.__name__} 失败: {e}")

                        for rule_fn in LAYER2_RULES:
                            try:
                                verdicts = rule_fn(win, ctx)
                                if verdicts:
                                    notifications = alarm_state_machine.process_verdicts(verdicts, now)
                                    send_notifications(notifications)
                            except Exception as e:
                                logger.error(f"规则 {rule_fn.__name__} 失败: {e}")

            except Exception as e:
                logger.error(f"告警引擎循环异常: {e}", exc_info=True)

            # 睡眠 30 秒，支持优雅退出
            for _ in range(30):
                if not self._running:
                    break
                time.sleep(1)

    # ── 数据获取 ──

    def _check_esp_heartbeats(self, now: datetime):
        with _esp_last_seen_lock:
            esp_list = list(_esp_last_seen.items())

        for esp_id, last_seen in esp_list:
            verdict = check_esp_heartbeat(esp_id, last_seen, now)
            if verdict:
                notifications = alarm_state_machine.process_verdicts([verdict], now)
                send_notifications(notifications)

    def _fetch_all_sensor_windows(self, now: datetime, lookback_minutes: int) -> list:
        try:
            from database import get_db
            import psycopg2.extras

            with get_db() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute("""
                    SELECT si.id, si.esp_id, si.tree_id, si.custom_name, si.slave_address,
                           t.model, t.description,
                           r.reg_name, r.unit
                    FROM sensor_instances si
                    JOIN sensor_templates t ON si.template_id = t.id
                    JOIN register_definitions r ON r.template_id = t.id
                    ORDER BY si.tree_id, si.esp_id, si.slave_address
                """)
                rows = cur.fetchall()
                cur.close()

            # 按 (tree_id, esp_id) 分组
            groups: dict[tuple, dict] = {}
            for r in rows:
                key = (r["tree_id"], r["esp_id"])
                if key not in groups:
                    groups[key] = {"tree_id": r["tree_id"], "esp_id": r["esp_id"], "sensors": []}
                groups[key]["sensors"].append(r)

            windows = []
            for key, group in groups.items():
                tree_id = group["tree_id"]
                esp_id = group["esp_id"]

                sensor_data, last_times = self._fetch_influx_series(esp_id, lookback_minutes)

                series_map: dict[str, list] = {}
                for pt in sensor_data:
                    skey = pt.get("sensor", "")
                    val = pt.get("value")
                    if val is not None:
                        series_map.setdefault(skey, []).append(val)

                field_map = {
                    "temperature": "air_temp", "humidity": "air_humidity",
                    "soil_temp": "soil_temp", "soil_moisture": "soil_moisture",
                    "conductivity": "conductivity", "lux": "lux",
                    "rainfall": "rainfall", "leaf_temp": "leaf_temp",
                    "leaf_humidity": "leaf_humidity",
                }

                win_kwargs = {
                    "now": now, "lookback_minutes": lookback_minutes,
                    "tree_id": tree_id, "esp_id": esp_id,
                    "last_data_time": last_times,
                }
                for influx_key, attr_name in field_map.items():
                    values = series_map.get(influx_key, [])
                    if values:
                        win_kwargs[attr_name] = values

                windows.append(SensorWindow(**win_kwargs))

            return windows

        except Exception as e:
            logger.error(f"拉取传感器数据窗口失败: {e}", exc_info=True)
            return []

    def _fetch_influx_series(self, esp_id: str, minutes: int):
        try:
            from config import INFLUX_BUCKET
            flux = f'''
            from(bucket: "{INFLUX_BUCKET}")
              |> range(start: -{minutes}m)
              |> filter(fn: (r) => r._measurement == "sensor_data")
              |> filter(fn: (r) => r._field == "value")
              |> filter(fn: (r) => r.esp_id == "{esp_id}")
            '''
            rows = influx_query(flux)

            last_times = {}
            for r in rows:
                sensor = r.get("sensor", "")
                t_str = r.get("time", "")
                if t_str:
                    try:
                        t = datetime.fromisoformat(t_str.replace("Z", "+00:00"))
                        if sensor not in last_times or t > last_times[sensor]:
                            last_times[sensor] = t
                    except (ValueError, TypeError):
                        pass

            return rows, last_times
        except Exception as e:
            logger.error(f"InfluxDB 查询失败 (esp={esp_id}): {e}")
            return [], {}


alarm_engine = AlarmEngine()
