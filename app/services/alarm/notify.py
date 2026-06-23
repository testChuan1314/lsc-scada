"""告警通知管道 —— 微信推送 + Web 记录 + 日志"""
import logging
from datetime import datetime, timezone
from typing import List, Optional

from .state import AlarmState, AlarmStatus, Severity

logger = logging.getLogger("scada-alarm")

# 全局微信推送回调（由 main.py 注入）
_wechat_pusher = None


def set_wechat_pusher(fn):
    """注入微信推送函数: fn(openid: str, message: str)"""
    global _wechat_pusher
    _wechat_pusher = fn


def send_notifications(states: List[AlarmState]):
    """根据状态变化推送告警"""
    now = datetime.now(timezone.utc)
    for state in states:
        if state.status == AlarmStatus.ACTIVE:
            _push_active(state, now)
        elif state.status == AlarmStatus.RESOLVED:
            _push_resolved(state, now)


def _push_active(state: AlarmState, now: datetime):
    """
    推送策略：
    - urgent → 立即
    - warning → 同棵树/ESP 至少间隔 5 分钟
    - info → 攒到整点（简化：直接发，频率由引擎周期控制）
    """
    emoji = "🔴" if state.severity == Severity.URGENT else "⚠️" if state.severity == Severity.WARNING else "ℹ️"
    msg = f"{emoji} {state.message}"

    # 附加位置信息
    if state.tree_id:
        msg += f"\n  树ID: {state.tree_id}"
    if state.esp_id:
        msg += f"\n  设备: {state.esp_id}"

    msg += f"\n  时间: {now.strftime('%m-%d %H:%M')}"

    logger.info(f"告警推送: {msg}")

    # 微信推送
    if _wechat_pusher and state.severity in (Severity.URGENT, Severity.WARNING):
        try:
            _wechat_pusher(None, msg)  # openid 由 pusher 内部决定
        except Exception as e:
            logger.error(f"微信推送失败: {e}")


def _push_resolved(state: AlarmState, now: datetime):
    """推送恢复通知"""
    msg = f"✅ 已恢复: {state.message}\n  时间: {now.strftime('%m-%d %H:%M')}"
    logger.info(f"告警恢复推送: {msg}")

    if _wechat_pusher:
        try:
            _wechat_pusher(None, msg)
        except Exception as e:
            logger.error(f"微信推送失败: {e}")
