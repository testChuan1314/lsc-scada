"""微信公众号配置"""
import os

APPID  = os.getenv("WECHAT_APPID",  "wx996201850ece68b6")
SECRET = os.getenv("WECHAT_SECRET", "")  # 需要去微信后台获取
TOKEN  = os.getenv("WECHAT_TOKEN",  "chuanfeng2026")    # 自定义，3-32位，微信后台要填一致
AES_KEY = os.getenv("WECHAT_AES_KEY", "")  # 消息加密模式才需要，先不弄
