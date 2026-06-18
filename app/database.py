"""PostgreSQL 连接 + 建表（11 张表）"""
import logging
from contextlib import contextmanager
import psycopg2, psycopg2.extras
from config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME

logger = logging.getLogger("scada-app")

@contextmanager
def get_db():
    conn = psycopg2.connect(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, dbname=DB_NAME)
    try: yield conn; conn.commit()
    except Exception: conn.rollback(); raise
    finally: conn.close()

def init_postgres():
    with get_db() as conn:
        cur = conn.cursor()
        for t in ("tree_photos","tree_events","trees","areas",
                  "register_definitions","sensor_instances","relay_instances",
                  "sensor_templates","sensor_brands","esp_devices","sensors","devices"):
            cur.execute(f"DROP TABLE IF EXISTS {t} CASCADE;")

        # 1. 区域
        cur.execute("""
            CREATE TABLE areas (
                id SERIAL PRIMARY KEY, name VARCHAR(128) NOT NULL,
                parent_id INTEGER REFERENCES areas(id) ON DELETE SET NULL,
                description VARCHAR(512), created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        # 2. ESP
        cur.execute("""
            CREATE TABLE esp_devices (
                id SERIAL PRIMARY KEY, esp_id VARCHAR(64) UNIQUE NOT NULL,
                name VARCHAR(128), location VARCHAR(256), mqtt_topic VARCHAR(256),
                area_id INTEGER REFERENCES areas(id) ON DELETE SET NULL,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        # 3. 盆景树
        cur.execute("""
            CREATE TABLE trees (
                id SERIAL PRIMARY KEY, area_id INTEGER REFERENCES areas(id) ON DELETE SET NULL,
                name VARCHAR(128) NOT NULL, species VARCHAR(128), variety VARCHAR(128),
                age_years INTEGER, height_cm REAL, trunk_diameter REAL, crown_width REAL,
                pot_type VARCHAR(64), pot_size VARCHAR(64),
                source VARCHAR(256), purchase_date DATE,
                purchase_price NUMERIC(10,2), current_value NUMERIC(10,2),
                health_status VARCHAR(64) DEFAULT '健康', growth_stage VARCHAR(64),
                description TEXT, lat DOUBLE PRECISION, lng DOUBLE PRECISION,
                created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW()
            );
        """)
        # 4. 生命周期事件
        cur.execute("""
            CREATE TABLE tree_events (
                id SERIAL PRIMARY KEY, tree_id INTEGER NOT NULL REFERENCES trees(id) ON DELETE CASCADE,
                category VARCHAR(64), event_type VARCHAR(128),
                title VARCHAR(256), description TEXT,
                event_date DATE NOT NULL, performed_by VARCHAR(64),
                cost NUMERIC(10,2), created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        # 5. 树木照片
        cur.execute("""
            CREATE TABLE tree_photos (
                id SERIAL PRIMARY KEY, tree_id INTEGER NOT NULL REFERENCES trees(id) ON DELETE CASCADE,
                event_id INTEGER REFERENCES tree_events(id) ON DELETE SET NULL,
                filename VARCHAR(256) NOT NULL, url VARCHAR(512) NOT NULL,
                thumbnail_url VARCHAR(512),
                taken_at TIMESTAMP NOT NULL DEFAULT NOW(),
                view_angle VARCHAR(32) DEFAULT '正面',
                photo_type VARCHAR(32) DEFAULT 'routine',
                season VARCHAR(8), is_cover BOOLEAN DEFAULT FALSE,
                note VARCHAR(256), uploaded_at TIMESTAMP DEFAULT NOW()
            );
        """)
        # 6. 品牌
        cur.execute("""
            CREATE TABLE sensor_brands (
                id SERIAL PRIMARY KEY, brand_name VARCHAR(128) UNIQUE NOT NULL,
                website VARCHAR(256), created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        # 7. 模板
        cur.execute("""
            CREATE TABLE sensor_templates (
                id SERIAL PRIMARY KEY, brand_id INTEGER NOT NULL REFERENCES sensor_brands(id) ON DELETE CASCADE,
                model VARCHAR(128) NOT NULL, description VARCHAR(512),
                baud_rate INTEGER DEFAULT 4800, data_bits INTEGER DEFAULT 8, stop_bits INTEGER DEFAULT 1,
                parity VARCHAR(8) DEFAULT 'NONE', poll_start_addr INTEGER DEFAULT 0, poll_count INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT NOW(), UNIQUE(brand_id, model)
            );
        """)
        # 8. 寄存器
        cur.execute("""
            CREATE TABLE register_definitions (
                id SERIAL PRIMARY KEY, template_id INTEGER NOT NULL REFERENCES sensor_templates(id) ON DELETE CASCADE,
                reg_address INTEGER NOT NULL, reg_name VARCHAR(64) NOT NULL, data_type VARCHAR(16) DEFAULT 'uint16',
                multiplier REAL DEFAULT 1.0, unit VARCHAR(32), description VARCHAR(256), created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        # 9. 传感器实例（+tree_id）
        cur.execute("""
            CREATE TABLE sensor_instances (
                id SERIAL PRIMARY KEY, esp_id VARCHAR(64) NOT NULL REFERENCES esp_devices(esp_id) ON DELETE CASCADE,
                template_id INTEGER NOT NULL REFERENCES sensor_templates(id) ON DELETE CASCADE,
                slave_address INTEGER DEFAULT 1, custom_name VARCHAR(128),
                tree_id INTEGER REFERENCES trees(id) ON DELETE SET NULL,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        # 10. 继电器
        cur.execute("""
            CREATE TABLE relay_instances (
                id SERIAL PRIMARY KEY, esp_id VARCHAR(64) NOT NULL REFERENCES esp_devices(esp_id) ON DELETE CASCADE,
                channel INTEGER NOT NULL, name VARCHAR(128), reg_address INTEGER, created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        cur.close()
    logger.info("数据库 11 表初始化完成")
