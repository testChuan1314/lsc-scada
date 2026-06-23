"""微信公众号回调接口"""
import hashlib, time, logging, xml.etree.ElementTree as ET
from fastapi import APIRouter, Request, Query
from fastapi.responses import PlainTextResponse, Response
from wechat.config import TOKEN
from wechat.handler import handle_text, handle_event, handle_image

logger = logging.getLogger("scada-wechat")
router = APIRouter(prefix="/api/wechat", tags=["Wechat"])

@router.get("/callback")
async def verify_signature(
    signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
):
    """微信服务器 GET 验证：签名校验"""
    tmp = sorted([TOKEN, timestamp, nonce])
    sha1 = hashlib.sha1("".join(tmp).encode()).hexdigest()
    if sha1 == signature:
        logger.info("微信签名验证通过")
        return PlainTextResponse(echostr)
    logger.warning("微信签名验证失败")
    return PlainTextResponse("fail")

@router.post("/callback")
async def receive_message(request: Request):
    """接收微信推送的消息/事件"""
    body = await request.body()
    xml_str = body.decode("utf-8")
    logger.debug(f"微信消息: {xml_str[:200]}")

    try:
        root = ET.fromstring(xml_str)
        msg = {child.tag: child.text for child in root}
    except Exception as e:
        logger.error(f"XML解析失败: {e}")
        return Response(content="success")

    msg_type = msg.get("MsgType", "")
    try:
        if msg_type == "event":
            reply = handle_event(msg)
        elif msg_type == "text":
            reply = handle_text(msg)
        elif msg_type == "image":
            reply = handle_image(msg)
        else:
            reply = ""
    except Exception as e:
        logger.error(f"处理消息失败: {e}", exc_info=True)
        reply = ""

    return Response(content=reply or "success", media_type="application/xml")
