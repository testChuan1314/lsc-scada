"""创建/更新公众号菜单（需 AppSecret，一次性的设置脚本）"""
import json, requests
from wechat.config import APPID, SECRET

MENU = {
    "button": [
        {
            "name": "🌳 我的树木",
            "type": "click",
            "key": "MY_TREES"
        },
        {
            "name": "📊 今日数据",
            "type": "click",
            "key": "TODAY_DATA"
        },
        {
            "name": "📷 拍照上传",
            "type": "click",
            "key": "MY_TREES"  # 先显示树列表
        }
    ]
}

def set_menu():
    if not SECRET:
        print("请先设置 WECHAT_SECRET 环境变量")
        return
    # 1. 获取 access_token
    r = requests.get(f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={APPID}&secret={SECRET}")
    token = r.json().get("access_token")
    if not token:
        print(f"获取token失败: {r.json()}")
        return
    # 2. 创建菜单
    r = requests.post(f"https://api.weixin.qq.com/cgi-bin/menu/create?access_token={token}", json=MENU)
    print(r.json())

if __name__ == "__main__":
    set_menu()
