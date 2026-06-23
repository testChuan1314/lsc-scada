"""盆景树 + 事件 + 照片"""
import os, uuid, shutil
from typing import Optional
from datetime import datetime, date
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query, Depends
import psycopg2, psycopg2.extras
from database import get_db
from models import TreeCreate, TreeUpdate, EventCreate, EventUpdate, PhotoUpdate
from services.auth import get_current_user, require_permission, area_filter_sql

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "uploads", "trees")
os.makedirs(UPLOAD_DIR, exist_ok=True)

router = APIRouter(prefix="/api/trees", tags=["Trees"])

def _season(d: date) -> str:
    m = d.month
    if 3 <= m <= 5: return "春"
    elif 6 <= m <= 8: return "夏"
    elif 9 <= m <= 11: return "秋"
    return "冬"

# ==================== 树 CRUD ====================
@router.get("")
def list_trees(area_id: Optional[int] = None, species: str = "", health_status: str = "", user = Depends(get_current_user)):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        where, vals = [], []
        if area_id:        where.append("t.area_id=%s"); vals.append(area_id)
        if species:        where.append("t.species ILIKE %s"); vals.append(f"%{species}%")
        if health_status:  where.append("t.health_status=%s"); vals.append(health_status)
        where.append(area_filter_sql(user, "t.area_id"))
        w = "WHERE " + " AND ".join(where) if where else ""
        cur.execute(f"""
            SELECT t.*, a.name AS area_name,
                   (SELECT COUNT(*) FROM tree_photos WHERE tree_id=t.id) AS photo_count,
                   (SELECT COUNT(*) FROM tree_events WHERE tree_id=t.id) AS event_count,
                   (SELECT url FROM tree_photos WHERE tree_id=t.id AND is_cover=true LIMIT 1) AS cover_url
            FROM trees t LEFT JOIN areas a ON t.area_id=a.id {w} ORDER BY t.id
        """, vals)
        rows = cur.fetchall(); cur.close()
    return [dict(r) for r in rows]

@router.get("/{tree_id}")
def get_tree(tree_id: int):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT t.*, a.name AS area_name FROM trees t LEFT JOIN areas a ON t.area_id=a.id WHERE t.id=%s", (tree_id,))
        row = cur.fetchone()
        if not row: cur.close(); raise HTTPException(404, "树不存在")
        # 绑定的传感器 + 每个传感器的采集能力
        cur2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur2.execute("""SELECT si.*, tpl.model, tpl.description AS tpl_desc, b.brand_name,
                        tpl.poll_start_addr, tpl.poll_count
                        FROM sensor_instances si
                        JOIN sensor_templates tpl ON si.template_id=tpl.id
                        JOIN sensor_brands b ON tpl.brand_id=b.id WHERE si.tree_id=%s""", (tree_id,))
        sensors = []
        for s in cur2.fetchall():
            sd = dict(s)
            # 查该传感器能采集哪些物理量
            cur3 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur3.execute("SELECT * FROM register_definitions WHERE template_id=%s ORDER BY reg_address", (s["template_id"],))
            sd["registers"] = [dict(r) for r in cur3.fetchall()]; cur3.close()
            sensors.append(sd)
        cur2.close()
        cur.close()
    return {**dict(row), "sensors": sensors}

@router.post("", status_code=201)
def create_tree(body: TreeCreate, user = Depends(require_permission("tree:write"))):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cols = "area_id,name,species,variety,age_years,height_cm,trunk_diameter,crown_width,pot_type,pot_size,source,purchase_date,purchase_price,current_value,health_status,growth_stage,description,lat,lng"
        vals = (body.area_id, body.name, body.species, body.variety, body.age_years, body.height_cm,
                body.trunk_diameter, body.crown_width, body.pot_type, body.pot_size, body.source,
                body.purchase_date, body.purchase_price, body.current_value, body.health_status,
                body.growth_stage, body.description, body.lat, body.lng)
        cur.execute(f"INSERT INTO trees ({cols}) VALUES ({','.join(['%s']*18)}) RETURNING *", vals)
        row = cur.fetchone(); cur.close()
    return dict(row)

@router.put("/{tree_id}")
def update_tree(tree_id: int, body: TreeUpdate, user = Depends(require_permission("tree:write"))):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM trees WHERE id=%s", (tree_id,))
        if not cur.fetchone(): cur.close(); raise HTTPException(404, "不存在")
        sets, vals = [], []
        for k in ("area_id","name","species","variety","age_years","height_cm","trunk_diameter",
                  "crown_width","pot_type","pot_size","source","purchase_date","purchase_price",
                  "current_value","health_status","growth_stage","description","lat","lng"):
            v = getattr(body, k)
            if v is not None: sets.append(f"{k}=%s"); vals.append(v)
        if sets:
            sets.append("updated_at=NOW()")
            vals.append(tree_id)
            cur.execute(f"UPDATE trees SET {','.join(sets)} WHERE id=%s RETURNING *", vals)
        else:
            cur.execute("SELECT * FROM trees WHERE id=%s", (tree_id,))
        row = cur.fetchone(); cur.close()
    return dict(row)

@router.delete("/{tree_id}")
def delete_tree(tree_id: int, user = Depends(require_permission("tree:write"))):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM trees WHERE id=%s", (tree_id,))
        if cur.rowcount == 0: cur.close(); raise HTTPException(404, "不存在")
        cur.close()
    # 清理照片文件
    photo_dir = os.path.join(UPLOAD_DIR, str(tree_id))
    if os.path.exists(photo_dir):
        shutil.rmtree(photo_dir)
    return {"deleted": True}

# ==================== 时间线 ====================
@router.get("/{tree_id}/timeline")
def get_timeline(tree_id: int):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT 'event' AS kind, id, event_date AS ts, title AS summary, category, event_type
            FROM tree_events WHERE tree_id=%s
            UNION ALL
            SELECT 'photo' AS kind, id, taken_at AS ts, note AS summary, photo_type, view_angle
            FROM tree_photos WHERE tree_id=%s AND event_id IS NULL
            ORDER BY ts DESC
        """, (tree_id, tree_id))
        rows = cur.fetchall(); cur.close()
    return [dict(r) for r in rows]

# ==================== 照片墙 ====================
@router.get("/{tree_id}/gallery")
def get_gallery(tree_id: int, view_angle: str = "", season: str = "", photo_type: str = ""):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        where, vals = ["tree_id=%s"], [tree_id]
        if view_angle:  where.append("view_angle=%s"); vals.append(view_angle)
        if season:      where.append("season=%s"); vals.append(season)
        if photo_type:  where.append("photo_type=%s"); vals.append(photo_type)
        w = " AND ".join(where)
        cur.execute(f"SELECT * FROM tree_photos WHERE {w} ORDER BY taken_at DESC", vals)
        rows = cur.fetchall(); cur.close()
    return [dict(r) for r in rows]

# ==================== 事件 CRUD ====================
@router.get("/{tree_id}/events")
def list_events(tree_id: int):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM tree_events WHERE tree_id=%s ORDER BY event_date DESC", (tree_id,))
        rows = cur.fetchall(); cur.close()
    return [dict(r) for r in rows]

@router.post("/{tree_id}/events", status_code=201)
def create_event(tree_id: int, body: EventCreate, user = Depends(require_permission("event:write"))):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("INSERT INTO tree_events (tree_id,category,event_type,title,description,event_date,performed_by,cost) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                    (tree_id, body.category, body.event_type, body.title, body.description, body.event_date, body.performed_by, body.cost))
        row = cur.fetchone(); cur.close()
    return dict(row)

router_event = APIRouter(prefix="/api/events", tags=["Events"])

@router_event.put("/{event_id}")
def update_event(event_id: int, body: EventUpdate):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM tree_events WHERE id=%s", (event_id,))
        if not cur.fetchone(): cur.close(); raise HTTPException(404, "不存在")
        sets, vals = [], []
        for k in ("category","event_type","title","description","event_date","performed_by","cost"):
            v = getattr(body, k)
            if v is not None: sets.append(f"{k}=%s"); vals.append(v)
        vals.append(event_id)
        if sets: cur.execute(f"UPDATE tree_events SET {','.join(sets)} WHERE id=%s RETURNING *", vals)
        else: cur.execute("SELECT * FROM tree_events WHERE id=%s", (event_id,))
        row = cur.fetchone(); cur.close()
    return dict(row)

@router_event.delete("/{event_id}")
def delete_event(event_id: int):
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM tree_events WHERE id=%s", (event_id,))
        if cur.rowcount == 0: cur.close(); raise HTTPException(404, "不存在")
        cur.close()
    return {"deleted": True}

# ==================== 照片 CRUD ====================
@router.get("/{tree_id}/photos")
def list_photos(tree_id: int, view_angle: str = "", season: str = "", photo_type: str = ""):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        where, vals = ["tree_id=%s"], [tree_id]
        if view_angle:  where.append("view_angle=%s"); vals.append(view_angle)
        if season:      where.append("season=%s"); vals.append(season)
        if photo_type:  where.append("photo_type=%s"); vals.append(photo_type)
        w = " AND ".join(where)
        cur.execute(f"SELECT * FROM tree_photos WHERE {w} ORDER BY taken_at DESC", vals)
        rows = cur.fetchall(); cur.close()
    return [dict(r) for r in rows]

@router.post("/{tree_id}/photos", status_code=201)
async def upload_photo(
    tree_id: int,
    file: UploadFile = File(...),
    taken_at: str = Form(""),
    view_angle: str = Form("正面"),
    photo_type: str = Form("routine"),
    event_id: Optional[int] = Form(None),
    note: str = Form(""),
    user = Depends(require_permission("photo:upload")),
):
    # 保存文件
    ext = file.filename.rsplit(".", 1)[-1] if "." in (file.filename or "") else "jpg"
    fname = f"{uuid.uuid4().hex}.{ext}"
    tree_dir = os.path.join(UPLOAD_DIR, str(tree_id))
    os.makedirs(tree_dir, exist_ok=True)
    fpath = os.path.join(tree_dir, fname)
    with open(fpath, "wb") as f:
        f.write(await file.read())

    url = f"/uploads/trees/{tree_id}/{fname}"
    taken = datetime.fromisoformat(taken_at) if taken_at else datetime.now()
    if isinstance(taken, datetime):
        taken_date = taken.date()
    else:
        taken_date = date.today()
    season = _season(taken_date)

    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""INSERT INTO tree_photos (tree_id,event_id,filename,url,taken_at,view_angle,photo_type,season,note)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                    (tree_id, event_id, file.filename, url, taken, view_angle, photo_type, season, note))
        row = cur.fetchone(); cur.close()
    return dict(row)

router_photo = APIRouter(prefix="/api/photos", tags=["Photos"])

@router_photo.put("/{photo_id}")
def update_photo(photo_id: int, body: PhotoUpdate):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM tree_photos WHERE id=%s", (photo_id,))
        row = cur.fetchone()
        if not row: cur.close(); raise HTTPException(404, "不存在")
        sets, vals = [], []
        for k in ("view_angle","photo_type","note","taken_at","event_id"):
            v = getattr(body, k)
            if v is not None: sets.append(f"{k}=%s"); vals.append(v)
        vals.append(photo_id)
        if sets: cur.execute(f"UPDATE tree_photos SET {','.join(sets)} WHERE id=%s RETURNING *", vals)
        else: cur.execute("SELECT * FROM tree_photos WHERE id=%s", (photo_id,))
        row = cur.fetchone(); cur.close()
    return dict(row)

@router_photo.delete("/{photo_id}")
def delete_photo(photo_id: int):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM tree_photos WHERE id=%s", (photo_id,))
        row = cur.fetchone()
        if not row: cur.close(); raise HTTPException(404, "不存在")
        # 删除文件
        fpath = os.path.join(os.path.dirname(__file__), "..", "static", row["url"].lstrip("/"))
        if os.path.exists(fpath): os.remove(fpath)
        cur2 = conn.cursor(); cur2.execute("DELETE FROM tree_photos WHERE id=%s", (photo_id,)); cur2.close()
        cur.close()
    return {"deleted": True}

@router_photo.post("/{photo_id}/cover")
def set_cover(photo_id: int):
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM tree_photos WHERE id=%s", (photo_id,))
        row = cur.fetchone()
        if not row: cur.close(); raise HTTPException(404, "不存在")
        tid = row["tree_id"]
        cur2 = conn.cursor()
        cur2.execute("UPDATE tree_photos SET is_cover=false WHERE tree_id=%s", (tid,))
        cur2.execute("UPDATE tree_photos SET is_cover=true WHERE id=%s", (photo_id,))
        cur2.close(); cur.close()
    return {"status": "ok"}
