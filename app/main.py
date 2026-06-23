"""LSC SCADA 主站 —— 模块化架构"""
import os, logging, time
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn

from database import init_postgres
from services.mqtt import mqtt_client, on_connect, on_message
from services.seed import seed_sample_data
from services.dispatcher import push_config_to_esp
from config import MQTT_HOST, MQTT_PORT

from routers import esp, brands, templates, registers, instances, relays, dispatch, data
from routers import areas, trees, users
from wechat.router import router as wechat_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("scada-app")

app = FastAPI(title="川枫景云 - 盆景全生命周期管理")

# 注册 API 路由
for r in (esp, brands, templates, registers, instances, relays, dispatch, data, areas, trees, users):
    app.include_router(r.router)
app.include_router(trees.router_event)
app.include_router(trees.router_photo)
app.include_router(wechat_router)

# 上传文件挂载
uploads_dir = os.path.join(os.path.dirname(__file__), "static", "uploads")
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

if __name__ == "__main__":
    init_postgres()
    seed_sample_data()

    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
    mqtt_client.loop_start()

    time.sleep(1)
    push_config_to_esp("rtu-001")

    static_dir = os.path.join(os.path.dirname(__file__), "static")
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    logger.info("LSC SCADA 主站启动完成")
    uvicorn.run(app, host="0.0.0.0", port=8000)
