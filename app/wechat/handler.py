"""微信消息分发处理"""
import logging, json
from datetime import datetime, timezone
import psycopg2.extras
from database import get_db
from services.influx import influx_query_latest
from wechat.reply import text_reply, news_reply

logger = logging.getLogger("scada-wechat")

def handle_event(msg: dict) -> str:
    """处理事件消息"""
    event = msg.get("Event", "")
    openid = msg.get("FromUserName", "")
    to_user = msg.get("ToUserName", "")

    if event == "subscribe":
        # 关注 → 自动创建用户（游客角色）
        _auto_create_user(openid)
        return text_reply(openid, to_user,
            "欢迎关注川枫景云！🌳\n\n"
            "温江 · 盆景全生命周期管理\n\n"
            "您当前为游客身份，请联系管理员开通权限。\n"
            "开通后可查看盆景数据、上传照片。"
        )
    elif event == "unsubscribe":
        logger.info(f"用户取消关注: {openid}")
        return ""
    elif event == "CLICK":
        key = msg.get("EventKey", "")
        if key == "MY_TREES":
            return _handle_my_trees(openid, to_user)
        elif key == "TODAY_DATA":
            return _handle_today_data(openid, to_user)
    return text_reply(openid, to_user, "收到")

def handle_text(msg: dict) -> str:
    openid = msg.get("FromUserName", "")
    to_user = msg.get("ToUserName", "")
    content = msg.get("Content", "").strip()
    if content in ("1", "数据", "data"):
        return _handle_today_data(openid, to_user)
    if content in ("2", "树", "trees", "盆景"):
        return _handle_my_trees(openid, to_user)
    return text_reply(openid, to_user,
        "🌳 川枫景云\n"
        "回复数字:\n"
        "1 → 今日数据\n"
        "2 → 我的树木\n\n"
        "也可以使用底部菜单"
    )

def handle_image(msg: dict) -> str:
    """拍照上传：暂存图片URL → 引导选择树木"""
    openid = msg.get("FromUserName", "")
    to_user = msg.get("ToUserName", "")
    pic_url = msg.get("PicUrl", "")
    # TODO: 存到待绑定队列，引导用户选树后关联
    logger.info(f"收到用户图片: openid={openid} url={pic_url}")
    return text_reply(openid, to_user, "📷 收到照片！请回复树木编号绑定:\n" + _my_trees_list(openid))

# ==================== 内部函数 ====================

def _auto_create_user(openid: str):
    try:
        with get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM users WHERE wechat_openid=%s", (openid,))
            if cur.fetchone():
                cur.close(); return
            cur.execute(
                "INSERT INTO users (username,password_hash,display_name,wechat_openid,role_id) VALUES (%s,%s,%s,%s,4) ON CONFLICT DO NOTHING",
                (f"wx_{openid[-8:]}", "", f"微信用户{openid[-6:]}", openid))
            cur.close()
        logger.info(f"自动创建微信用户: {openid}")
    except Exception as e:
        logger.error(f"创建用户失败: {e}")

def _get_user_by_openid(openid: str) -> dict:
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT u.*, r.code AS role_code FROM users u LEFT JOIN roles r ON u.role_id=r.id WHERE u.wechat_openid=%s AND u.is_active=true", (openid,))
        u = cur.fetchone(); cur.close()
    return dict(u) if u else {}

def _get_user_area_ids(openid: str) -> list[int]:
    u = _get_user_by_openid(openid)
    if not u or u.get("role_code") == "admin": return []
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("SELECT area_id FROM user_areas WHERE user_id=%s", (u["id"],))
        ids = [r[0] for r in cur.fetchall()]; cur.close()
    return ids

def _my_trees_list(openid: str) -> str:
    area_ids = _get_user_area_ids(openid)
    from services.auth import get_user_area_ids
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if not area_ids:
            cur.execute("SELECT id, name, species FROM trees ORDER BY id")
        else:
            cur.execute(f"SELECT id, name, species FROM trees WHERE area_id IN %s ORDER BY id", (tuple(area_ids),))
        trees = cur.fetchall(); cur.close()
    if not trees: return "暂无树木"
    return "\n".join(f"{t['id']}. {t['name']} ({t['species'] or '?'})" for t in trees)

def _handle_my_trees(openid: str, to_user: str) -> str:
    area_ids = _get_user_area_ids(openid)
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if not area_ids:
            cur.execute("SELECT * FROM trees ORDER BY id")
        else:
            cur.execute(f"SELECT * FROM trees WHERE area_id IN %s ORDER BY id", (tuple(area_ids),))
        trees = cur.fetchall(); cur.close()
    if not trees:
        return text_reply(openid, to_user, "您暂无权限查看任何树木，请联系管理员。")
    lines = ["🌳 我的树木:\n"]
    for t in trees:
        lines.append(f"· {t['name']} | {t['species'] or '?'} | {t['age_years'] or '?'}年 | {t['health_status'] or '-'}")
    return text_reply(openid, to_user, "\n".join(lines))

def _handle_today_data(openid: str, to_user: str) -> str:
    latest = influx_query_latest()
    if not latest:
        return text_reply(openid, to_user, "暂无传感器数据")
    lines = ["📊 最新传感器数据:\n"]
    for d in latest[:8]:
        unit = {"土壤温度":"°C","空气温度":"°C","土壤水分":"%","空气湿度":"%RH","土壤电导率":"μS/cm","光照度 0~65535":"Lux"}.get(d["sensor"],"")
        lines.append(f"{d['sensor']}: {d['value']}{unit} ({d['source'][:8]}...)")
    return text_reply(openid, to_user, "\n".join(lines))
