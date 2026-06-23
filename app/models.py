"""Pydantic 请求/响应模型"""
from typing import Optional
from datetime import date, datetime
from pydantic import BaseModel

# ---- 区域 ----
class AreaCreate(BaseModel):
    name: str; parent_id: Optional[int] = None; description: str = ""
class AreaUpdate(BaseModel):
    name: Optional[str] = None; parent_id: Optional[int] = None; description: Optional[str] = None

# ---- 盆景树 ----
class TreeCreate(BaseModel):
    area_id: Optional[int] = None; name: str
    species: str = ""; variety: str = ""
    age_years: Optional[int] = None; height_cm: Optional[float] = None
    trunk_diameter: Optional[float] = None; crown_width: Optional[float] = None
    pot_type: str = ""; pot_size: str = ""
    source: str = ""; purchase_date: Optional[date] = None
    purchase_price: Optional[float] = None; current_value: Optional[float] = None
    health_status: str = "健康"; growth_stage: str = ""
    description: str = ""; lat: Optional[float] = None; lng: Optional[float] = None
class TreeUpdate(BaseModel):
    area_id: Optional[int] = None; name: Optional[str] = None
    species: Optional[str] = None; variety: Optional[str] = None
    age_years: Optional[int] = None; height_cm: Optional[float] = None
    trunk_diameter: Optional[float] = None; crown_width: Optional[float] = None
    pot_type: Optional[str] = None; pot_size: Optional[str] = None
    source: Optional[str] = None; purchase_date: Optional[date] = None
    purchase_price: Optional[float] = None; current_value: Optional[float] = None
    health_status: Optional[str] = None; growth_stage: Optional[str] = None
    description: Optional[str] = None; lat: Optional[float] = None; lng: Optional[float] = None

# ---- 事件 ----
class EventCreate(BaseModel):
    category: str = ""; event_type: str = ""; title: str = ""
    description: str = ""; event_date: date
    performed_by: str = ""; cost: Optional[float] = None
class EventUpdate(BaseModel):
    category: Optional[str] = None; event_type: Optional[str] = None
    title: Optional[str] = None; description: Optional[str] = None
    event_date: Optional[date] = None; performed_by: Optional[str] = None
    cost: Optional[float] = None

# ---- 照片元数据更新 ----
class PhotoUpdate(BaseModel):
    view_angle: Optional[str] = None; photo_type: Optional[str] = None
    note: Optional[str] = None; taken_at: Optional[datetime] = None
    event_id: Optional[int] = None

# ---- 用户 / 角色 / 权限 ----
class UserCreate(BaseModel):
    display_name: str = ""; phone: str = ""; role_id: Optional[int] = None
    wechat_openid: str = ""; wechat_nickname: str = ""; wechat_avatar: str = ""
class UserUpdate(BaseModel):
    display_name: Optional[str] = None; phone: Optional[str] = None
    role_id: Optional[int] = None; is_active: Optional[bool] = None
    wechat_nickname: Optional[str] = None; wechat_avatar: Optional[str] = None
class UserAreaUpdate(BaseModel):
    area_ids: list[int] = []
class RoleCreate(BaseModel):
    name: str; code: str; description: str = ""
class PermissionCreate(BaseModel):
    code: str; name: str = ""; resource: str = ""; action: str = ""

# ---- 原有传感器模型 ----
class EspCreate(BaseModel):
    esp_id: str; name: str = ""; location: str = ""; mqtt_topic: str = ""; area_id: Optional[int] = None
class EspUpdate(BaseModel):
    name: Optional[str] = None; location: Optional[str] = None; mqtt_topic: Optional[str] = None; area_id: Optional[int] = None
class BrandCreate(BaseModel):
    brand_name: str; website: str = ""
class BrandUpdate(BaseModel):
    brand_name: Optional[str] = None; website: Optional[str] = None
class TemplateCreate(BaseModel):
    brand_id: int; model: str; description: str = ""; baud_rate: int = 4800
    poll_start_addr: int = 0; poll_count: int = 1
class TemplateUpdate(BaseModel):
    model: Optional[str] = None; description: Optional[str] = None; baud_rate: Optional[int] = None
    poll_start_addr: Optional[int] = None; poll_count: Optional[int] = None
class RegisterCreate(BaseModel):
    template_id: int; reg_address: int; reg_name: str
    data_type: str = "uint16"; multiplier: float = 1.0; unit: str = ""; description: str = ""
class RegisterUpdate(BaseModel):
    reg_name: Optional[str] = None; data_type: Optional[str] = None
    multiplier: Optional[float] = None; unit: Optional[str] = None; description: Optional[str] = None
class SensorInstanceCreate(BaseModel):
    esp_id: str; template_id: int; slave_address: int = 1; custom_name: str = ""; tree_id: Optional[int] = None
class SensorInstanceUpdate(BaseModel):
    slave_address: Optional[int] = None; custom_name: Optional[str] = None; tree_id: Optional[int] = None
class RelayCreate(BaseModel):
    esp_id: str; channel: int; name: str = ""; reg_address: Optional[int] = None
class RelayUpdate(BaseModel):
    name: Optional[str] = None; reg_address: Optional[int] = None
