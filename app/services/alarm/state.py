"""告警状态机 —— 去重 / 防抖 / 升级 / 自动恢复"""
import logging
from datetime import datetime, timezone
from typing import Optional, List
from dataclasses import dataclass, field
from enum import Enum

import psycopg2.extras
from database import get_db
from .rules import AlarmVerdict, Severity

logger = logging.getLogger("scada-alarm")

DEBOUNCE_COUNT = 3          # 连续触发次数才确认
RESOLVE_COUNT = 2           # 连续不触发次数才恢复
ESCALATE_MINUTES = 30       # 告警持续多久升级


class AlarmStatus(str, Enum):
    PENDING = "pending"          # 防抖中
    ACTIVE = "active"            # 告警中
    CONFIRMED = "confirmed"      # 人工已确认
    RESOLVED = "resolved"        # 已恢复


@dataclass
class AlarmState:
    """内存中的告警状态（配合 PG 持久化）"""
    dedup_key: str               # 去重键：rule_name + tree_id/esp_id
    rule_name: str
    severity: Severity
    message: str
    tree_id: Optional[int]
    esp_id: Optional[str]
    sensor_name: Optional[str]
    detail: dict

    status: AlarmStatus = AlarmStatus.PENDING
    hit_count: int = 0           # 连续命中次数
    miss_count: int = 0          # 连续未命中次数
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    activated_at: Optional[datetime] = None
    db_id: Optional[int] = None  # PG 中的 ID


class AlarmStateMachine:
    """管理所有活跃告警的状态转换"""

    def __init__(self):
        self._active: dict[str, AlarmState] = {}
        self._resolved_history: list[AlarmState] = []  # 最近恢复的，供前端展示

    def process_verdicts(self, verdicts: List[AlarmVerdict], now: datetime) -> List[AlarmState]:
        """
        输入：这一轮规则产生的所有 verdits
        输出：需要发通知的告警变化（新建 / 升级 / 恢复）
        """
        seen_keys = set()
        notifications: List[AlarmState] = []

        for v in verdicts:
            key = self._make_key(v)
            seen_keys.add(key)

            if key in self._active:
                state = self._active[key]
                state.hit_count += 1
                state.miss_count = 0
                state.last_seen = now
                state.message = v.message  # 更新最新描述

                # PENDING → ACTIVE
                if state.status == AlarmStatus.PENDING and state.hit_count >= DEBOUNCE_COUNT:
                    state.status = AlarmStatus.ACTIVE
                    state.activated_at = now
                    self._save_to_db(state, "active")
                    notifications.append(state)
                    logger.info(f"告警激活: {state.message}")

                # ACTIVE → 升级
                elif state.status == AlarmStatus.ACTIVE:
                    escalated = self._maybe_escalate(state, now)
                    if escalated:
                        self._save_to_db(state, "escalated")
                        notifications.append(state)

            else:
                # 新告警 → PENDING
                state = AlarmState(
                    dedup_key=key,
                    rule_name=v.rule_name,
                    severity=v.severity,
                    message=v.message,
                    tree_id=v.tree_id,
                    esp_id=v.esp_id,
                    sensor_name=v.sensor_name,
                    detail=v.detail,
                    status=AlarmStatus.PENDING,
                    hit_count=1,
                    first_seen=now,
                    last_seen=now,
                )
                self._active[key] = state

        # 检查未触发的告警 → 恢复
        for key, state in list(self._active.items()):
            if key not in seen_keys:
                state.miss_count += 1
                state.hit_count = 0
                if state.status in (AlarmStatus.ACTIVE, AlarmStatus.CONFIRMED):
                    if state.miss_count >= RESOLVE_COUNT:
                        state.status = AlarmStatus.RESOLVED
                        self._save_to_db(state, "resolved")
                        notifications.append(state)
                        logger.info(f"告警恢复: {state.message}")
                        self._resolved_history.append(state)
                        del self._active[key]
                        # 只保留最近 100 条恢复记录
                        if len(self._resolved_history) > 100:
                            self._resolved_history = self._resolved_history[-100:]
                elif state.status == AlarmStatus.PENDING:
                    # 防抖期间就消失了
                    del self._active[key]

        return notifications

    def confirm(self, dedup_key: str, user: str):
        """人工确认告警"""
        state = self._active.get(dedup_key)
        if state and state.status == AlarmStatus.ACTIVE:
            state.status = AlarmStatus.CONFIRMED
            self._save_to_db(state, "confirmed", user)
            logger.info(f"告警已确认: {state.message} by {user}")

    def get_all(self) -> List[AlarmState]:
        return list(self._active.values())

    def _make_key(self, v: AlarmVerdict) -> str:
        """构造去重键"""
        parts = [v.rule_name]
        if v.tree_id is not None:
            parts.append(f"t{v.tree_id}")
        if v.esp_id is not None:
            parts.append(v.esp_id)
        if v.sensor_name is not None:
            parts.append(v.sensor_name)
        return ":".join(parts)

    def _maybe_escalate(self, state: AlarmState, now: datetime) -> bool:
        """检查是否需要升级严重度"""
        if state.activated_at is None:
            return False
        elapsed = (now - state.activated_at).total_seconds()
        if elapsed > ESCALATE_MINUTES * 60 * 2:
            # 持续 2× 升级时间 → 再升级
            if state.severity == Severity.WARNING:
                state.severity = Severity.URGENT
                state.message = f"[升级] {state.message}"
                return True
        elif elapsed > ESCALATE_MINUTES * 60:
            if state.severity == Severity.INFO:
                state.severity = Severity.WARNING
                state.message = f"[升级] {state.message}"
                return True
        return False

    def _save_to_db(self, state: AlarmState, action: str, user: str = ""):
        """持久化到 PostgreSQL"""
        try:
            with get_db() as conn:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                if action == "active":
                    cur.execute("""
                        INSERT INTO alarm_records
                            (rule_name, category, severity, status, message, detail_json,
                             tree_id, esp_id, sensor_name, dedup_key, triggered_at)
                        VALUES (%s, %s, %s, 'active', %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (dedup_key) WHERE status = 'active'
                        DO UPDATE SET message = EXCLUDED.message,
                                      severity = EXCLUDED.severity,
                                      detail_json = EXCLUDED.detail_json
                        RETURNING id
                    """, (
                        state.rule_name, "sensor_fault", state.severity.value,
                        state.message, json_dumps(state.detail),
                        state.tree_id, state.esp_id, state.sensor_name,
                        state.dedup_key, state.activated_at or datetime.now(timezone.utc)
                    ))
                    row = cur.fetchone()
                    if row:
                        state.db_id = row["id"]
                elif action == "resolved":
                    cur.execute("""
                        UPDATE alarm_records SET status='resolved', resolved_at=%s
                        WHERE dedup_key=%s AND status IN ('active','confirmed')
                    """, (datetime.now(timezone.utc), state.dedup_key))
                elif action == "confirmed":
                    cur.execute("""
                        UPDATE alarm_records SET status='confirmed', confirmed_at=%s, confirmed_by=%s
                        WHERE dedup_key=%s AND status='active'
                    """, (datetime.now(timezone.utc), user, state.dedup_key))
                elif action == "escalated":
                    cur.execute("""
                        UPDATE alarm_records SET severity=%s, message=%s
                        WHERE dedup_key=%s AND status='active'
                    """, (state.severity.value, state.message, state.dedup_key))
                cur.close()
        except Exception as e:
            logger.error(f"保存告警记录失败: {e}")


import json as _json

def json_dumps(obj):
    return _json.dumps(obj, ensure_ascii=False, default=str)


# 全局单例
alarm_state_machine = AlarmStateMachine()
