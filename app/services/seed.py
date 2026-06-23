"""种子数据"""
import logging, psycopg2.extras
from database import get_db

logger = logging.getLogger("scada-app")

def seed_sample_data():
    with get_db() as conn:
        cur = conn.cursor()

        # ====== 预置角色 ======
        cur.execute("INSERT INTO roles (id,name,code,description) VALUES (1,'超级管理员','admin','拥有所有权限') ON CONFLICT DO NOTHING;")
        cur.execute("INSERT INTO roles (id,name,code,description) VALUES (2,'区域管理员','area_manager','管辖区域内设备/树管理+数据查看') ON CONFLICT DO NOTHING;")
        cur.execute("INSERT INTO roles (id,name,code,description) VALUES (3,'养护员','gardener','管辖区域内树详情/事件/照片/传感器数据') ON CONFLICT DO NOTHING;")
        cur.execute("INSERT INTO roles (id,name,code,description) VALUES (4,'游客','viewer','只读查看管辖区域数据') ON CONFLICT DO NOTHING;")

        # ====== 预置权限 ======
        perms = [
            (1,"area:read","查看区域","area","read"),(2,"area:write","管理区域","area","write"),
            (3,"esp:read","查看ESP","esp","read"),(4,"esp:write","管理ESP","esp","write"),
            (5,"sensor:read","查看传感器数据","sensor","read"),(6,"sensor:write","管理传感器配置","sensor","write"),
            (7,"tree:read","查看树木","tree","read"),(8,"tree:write","管理树木","tree","write"),
            (9,"event:write","新增事件","event","write"),(10,"photo:upload","上传照片","photo","upload"),
            (11,"relay:control","控制继电器","relay","control"),(12,"user:manage","管理用户","user","write"),
        ]
        for pid, code, name, res, act in perms:
            cur.execute("INSERT INTO permissions (id,code,name,resource,action) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", (pid, code, name, res, act))

        # ====== 角色→权限映射 ======
        rp = {
            1: [1,2,3,4,5,6,7,8,9,10,11,12],  # admin: 全部
            2: [1,3,5,7,8,9,10,11],              # area_manager
            3: [1,3,5,7,9,10],                   # gardener
            4: [1,3,5,7],                        # viewer
        }
        for rid, pids in rp.items():
            for pid in pids:
                cur.execute("INSERT INTO role_permissions (role_id,permission_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (rid, pid))

        # ====== 测试用户（密码: 123456） ======
        from services.auth import hash_password
        pw = hash_password("123456")
        cur.execute("INSERT INTO users (id,username,password_hash,display_name,phone,role_id) VALUES (1,'admin',%s,'管理员','13800000000',1) ON CONFLICT DO NOTHING;", (pw,))
        cur.execute("INSERT INTO users (id,username,password_hash,display_name,phone,role_id) VALUES (2,'laoli',%s,'老李','13800000001',3) ON CONFLICT DO NOTHING;", (pw,))
        cur.execute("INSERT INTO users (id,username,password_hash,display_name,phone,role_id) VALUES (3,'manager',%s,'大棚负责人','13800000002',2) ON CONFLICT DO NOTHING;", (pw,))

        # 区域
        cur.execute("INSERT INTO areas (id,name,description) VALUES (1,'一号大棚','川枫景云 · 温江室内养护区') ON CONFLICT DO NOTHING;")
        cur.execute("INSERT INTO areas (id,name,description) VALUES (2,'露天养护区','川枫景云 · 室外自然养护') ON CONFLICT DO NOTHING;")
        cur.execute("INSERT INTO areas (id,name,description) VALUES (3,'精品展示区','川枫景云 · 参展盆景陈列') ON CONFLICT DO NOTHING;")

        # 品牌
        cur.execute("INSERT INTO sensor_brands (brand_name) VALUES ('仁科') ON CONFLICT DO NOTHING;")
        cur.execute("INSERT INTO sensor_brands (brand_name) VALUES ('哲泰盛') ON CONFLICT DO NOTHING;")
        cur.execute("SELECT id, brand_name FROM sensor_brands;")
        brands = {r[1]: r[0] for r in cur.fetchall()}

        # 模板
        cur.execute("INSERT INTO sensor_templates (brand_id,model,description,baud_rate,poll_start_addr,poll_count)"
                    " VALUES (%s,'RS-ECTH-N01-TR-1','土壤温度水分电导率三合一',4800,0,3)"
                    " ON CONFLICT DO NOTHING", (brands["仁科"],))
        cur.execute("INSERT INTO sensor_templates (brand_id,model,description,baud_rate,poll_start_addr,poll_count)"
                    " VALUES (%s,'RS-GZ-N01-2','光照度温湿度三合一',4800,0,7)"
                    " ON CONFLICT DO NOTHING", (brands["仁科"],))
        cur.execute("INSERT INTO sensor_templates (brand_id,model,description,baud_rate,poll_start_addr,poll_count)"
                    " VALUES (%s,'ZTS-3000-TR-ECWS-N01','土壤温湿度电导率',4800,0,3)"
                    " ON CONFLICT DO NOTHING", (brands["哲泰盛"],))
        cur.close()

    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, model FROM sensor_templates")
        templates = {r["model"]: r["id"] for r in cur.fetchall()}
        cur.close()

    regs = [
        (templates["RS-ECTH-N01-TR-1"], 0x0000, "moisture","uint16",0.1,"%","土壤水分"),
        (templates["RS-ECTH-N01-TR-1"], 0x0001, "temperature","int16",0.1,"°C","土壤温度"),
        (templates["RS-ECTH-N01-TR-1"], 0x0002, "conductivity","uint16",1.0,"μS/cm","土壤电导率"),
        (templates["RS-GZ-N01-2"], 0x0000, "humidity","uint16",0.1,"%RH","空气湿度"),
        (templates["RS-GZ-N01-2"], 0x0001, "temperature","int16",0.1,"°C","空气温度"),
        (templates["RS-GZ-N01-2"], 0x0006, "lux","uint16",1.0,"Lux","光照度 0~65535"),
        (templates["ZTS-3000-TR-ECWS-N01"], 0x0000, "moisture","uint16",0.1,"%","土壤水分"),
        (templates["ZTS-3000-TR-ECWS-N01"], 0x0001, "temperature","int16",0.1,"°C","土壤温度"),
        (templates["ZTS-3000-TR-ECWS-N01"], 0x0002, "conductivity","uint16",1.0,"μS/cm","土壤电导率"),
    ]
    with get_db() as conn:
        cur = conn.cursor()
        for r in regs:
            cur.execute("INSERT INTO register_definitions (template_id,reg_address,reg_name,data_type,multiplier,unit,description) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", r)
        cur.close()

    # ESP
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO esp_devices (esp_id,name,location,mqtt_topic,area_id) VALUES ('rtu-001','艾尔赛ESP32-4CH-Relay','A区配电房','lsc/devices/rtu-001/data',1) ON CONFLICT (esp_id) DO NOTHING")
        cur.close()

    # 盆景树
    trees_data = [
        (1, "黑松-001", "黑松", "寸梢黑松", 8, 45.0, 8.0, 35.0, "方盆", "30×20×8cm", "日本进口", "2021-03-15", 2000, 8000, "健康", "生长期", "造型完成，树冠饱满"),
        (1, "真柏-003", "真柏", "系鱼川真柏", 15, 60.0, 12.0, 50.0, "圆盆", "35×25×10cm", "苗培", "2018-06-01", 3500, 15000, "恢复中", "恢复期", "去年换盆后恢复中"),
        (2, "五针松-001", "五针松", "五针松", 3, 20.0, 3.0, 15.0, "小方盆", "15×10×5cm", "下山桩", "2024-02-10", 500, 500, "健康", "生长期", "幼苗培养，尚未造型"),
        (3, "枫树-001", "枫树", "出猩猩枫", 6, 40.0, 6.0, 30.0, "椭圆盆", "28×18×7cm", "苗培", "2020-04-20", 1200, 4500, "健康", "休眠期", "秋季红叶品种，参展预备"),
    ]
    with get_db() as conn:
        cur = conn.cursor()
        for t in trees_data:
            cur.execute("INSERT INTO trees (area_id,name,species,variety,age_years,height_cm,trunk_diameter,crown_width,pot_type,pot_size,source,purchase_date,purchase_price,current_value,health_status,growth_stage,description) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", t)
        cur.close()

    # 传感器实例（绑定到树）
    with get_db() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, model FROM sensor_templates")
        tpl = {r["model"]: r["id"] for r in cur.fetchall()}
        cur.execute("SELECT id, name FROM trees")
        tree_ids = {r["name"]: r["id"] for r in cur.fetchall()}
        cur.close()

    instances = [
        (tpl["ZTS-3000-TR-ECWS-N01"], 0x01, "哲泰盛土壤三合一", tree_ids.get("黑松-001")),
        (tpl["RS-ECTH-N01-TR-1"], 0x02, "仁科土壤三合一", tree_ids.get("真柏-003")),
        (tpl["RS-GZ-N01-2"], 0x03, "仁科光照温湿度", None),
    ]
    with get_db() as conn:
        cur = conn.cursor()
        for tid, addr, name, tree_id in instances:
            cur.execute("INSERT INTO sensor_instances (esp_id,template_id,slave_address,custom_name,tree_id) VALUES ('rtu-001',%s,%s,%s,%s) ON CONFLICT DO NOTHING", (tid, addr, name, tree_id))
        for ch, name, reg in [(0,"继电器 #1",0),(1,"继电器 #2",1),(2,"继电器 #3",2),(3,"继电器 #4",3)]:
            cur.execute("INSERT INTO relay_instances (esp_id,channel,name,reg_address) VALUES ('rtu-001',%s,%s,%s) ON CONFLICT DO NOTHING", (ch, name, reg))
        cur.close()

    # 示例事件
    with get_db() as conn:
        cur = conn.cursor()
        bhs = tree_ids.get("黑松-001")
        if bhs:
            cur.execute("INSERT INTO tree_events (tree_id,category,event_type,title,event_date,performed_by,description) VALUES (%s,'造型','修剪','春季摘芽','2025-04-03','老李','去除顶部强势芽，保留侧枝弱芽') ON CONFLICT DO NOTHING", (bhs,))
            cur.execute("INSERT INTO tree_events (tree_id,category,event_type,title,event_date,performed_by,description) VALUES (%s,'换盆','换盆','换盆升级','2025-02-15','老李','方盆→大一号方盆，根系健康') ON CONFLICT DO NOTHING", (bhs,))
        cur.close()

    # 用户管辖区域
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO user_areas (user_id,area_id) VALUES (2,1) ON CONFLICT DO NOTHING;")  # 老李→A区大棚
        cur.execute("INSERT INTO user_areas (user_id,area_id) VALUES (3,1) ON CONFLICT DO NOTHING;")  # 大棚负责人→A区大棚
        cur.execute("INSERT INTO user_areas (user_id,area_id) VALUES (3,2) ON CONFLICT DO NOTHING;")  # 大棚负责人→露天养护区
        cur.close()

    logger.info("种子数据完成 (4角色+12权限+3用户+3区域+1ESP+2品牌×3模板×9寄存器+3实例+4树+4继电器+2事件)")
