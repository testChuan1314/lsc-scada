"""告警查询 / 确认 API"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
import psycopg2.extras
from database import get_db
from models import AlarmConfirm
from services.auth import get_current_user
from services.alarm.state import alarm_state_machine

router = APIRouter(prefix="/api/alarms", tags=["Alarms"])


@router.get("")
def list_alarms(
    status: Optional[str] = None,
    esp_id: Optional[str] = None,
    tree_id: Optional[int] = None,
    limit: int = 50,
    user=Depends(get_current_user),
):
    """查询告警列表。默认返回最近 50 条活跃告警。"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        where = []
        params = []
        if status:
            where.append("status = %s")
            params.append(status)
        else:
            where.append("status IN ('active','confirmed')")
        if esp_id:
            where.append("esp_id = %s")
            params.append(esp_id)
        if tree_id:
            where.append("tree_id = %s")
            params.append(tree_id)

        sql = "SELECT * FROM alarm_records"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY triggered_at DESC LIMIT %s"
        params.append(limit)

        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
    return [dict(r) for r in rows]


@router.get("/active")
def list_active_alarms(user=Depends(get_current_user)):
    """获取所有内存中的活跃告警（含 pending 状态）"""
    states = alarm_state_machine.get_all()
    return [
        {
            "dedup_key": s.dedup_key,
            "rule_name": s.rule_name,
            "severity": s.severity.value,
            "status": s.status.value,
            "message": s.message,
            "tree_id": s.tree_id,
            "esp_id": s.esp_id,
            "sensor_name": s.sensor_name,
            "hit_count": s.hit_count,
            "first_seen": s.first_seen.isoformat() if s.first_seen else None,
            "last_seen": s.last_seen.isoformat() if s.last_seen else None,
            "activated_at": s.activated_at.isoformat() if s.activated_at else None,
        }
        for s in states
    ]


@router.post("/{dedup_key}/confirm")
def confirm_alarm(dedup_key: str, body: AlarmConfirm = AlarmConfirm(), user=Depends(get_current_user)):
    """人工确认告警"""
    alarm_state_machine.confirm(dedup_key, body.confirmed_by or user.get("display_name", "未知"))
    return {"ok": True}


@router.get("/history")
def list_history(limit: int = 100, user=Depends(get_current_user)):
    """查看已恢复的告警历史"""
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT * FROM alarm_records WHERE status = 'resolved' ORDER BY resolved_at DESC LIMIT %s",
            (limit,),
        )
        rows = cur.fetchall()
        cur.close()
    return [dict(r) for r in rows]
