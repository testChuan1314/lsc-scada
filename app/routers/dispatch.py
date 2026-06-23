from fastapi import APIRouter, Depends
from services.dispatcher import push_config_to_esp, push_relay_cmd
from services.auth import require_permission

router = APIRouter(prefix="/api/esp", tags=["Dispatch"])

@router.post("/{esp_id}/dispatch")
def api_dispatch(esp_id: str, user = Depends(require_permission("esp:write"))):
    config = push_config_to_esp(esp_id)
    return {"status": "dispatched", "config": config}

@router.post("/{esp_id}/relay/{channel}/on")
def api_relay_on(esp_id: str, channel: int, user = Depends(require_permission("relay:control"))):
    push_relay_cmd(esp_id, channel, True)
    return {"status": "sent"}

@router.post("/{esp_id}/relay/{channel}/off")
def api_relay_off(esp_id: str, channel: int, user = Depends(require_permission("relay:control"))):
    push_relay_cmd(esp_id, channel, False)
    return {"status": "sent"}
