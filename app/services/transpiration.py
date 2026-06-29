"""蒸腾作用评估 —— VPD / CWSI / ET₀ / 蒸腾状态"""
import math
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional
import logging

logger = logging.getLogger("scada-transpiration")

# ── 物理常数 ──
LATENT_HEAT = 2.45e6    # 水的汽化潜热 J/kg
STEFAN_BOLTZMANN = 5.67e-8  # W/(m²·K⁴)
CP_AIR = 1005            # 空气定压比热 J/(kg·K)
# 成都温江经纬度
DEFAULT_LAT = 30.7
DEFAULT_LNG = 103.8


# ═══════════════════════════════════════
# 1. 饱和水汽压 & VPD
# ═══════════════════════════════════════

def saturation_vapor_pressure(T_celsius: float) -> float:
    """August-Roche-Magnus 公式: 饱和水汽压 (kPa)

    Args:
        T_celsius: 空气/叶片温度 (°C)
    """
    return 0.6108 * math.exp(17.27 * T_celsius / (T_celsius + 237.3))


def actual_vapor_pressure(T_celsius: float, RH_percent: float) -> float:
    """实际水汽压 (kPa)"""
    es = saturation_vapor_pressure(T_celsius)
    return es * RH_percent / 100.0


def compute_vpd_air(T_air: float, RH_air: float) -> float:
    """空气 VPD (kPa)

    蒸腾的"拉力"——VPD 越大，大气从叶片吸水的力量越强。
    """
    es = saturation_vapor_pressure(T_air)
    ea = es * RH_air / 100.0
    return max(0.0, es - ea)


def compute_vpd_leaf(T_leaf: float, T_air: float, RH_air: float) -> float:
    """叶面 VPD (kPa)

    用叶片温度算叶面饱和水汽压，用空气实际水汽压做差。
    叶片被太阳晒热后 VPD_leaf > VPD_air，蒸腾驱动力更强。
    """
    es_leaf = saturation_vapor_pressure(T_leaf)
    ea = actual_vapor_pressure(T_air, RH_air)
    return max(0.0, es_leaf - ea)


# ═══════════════════════════════════════
# 2. VPD 植物生理解读
# ═══════════════════════════════════════

@dataclass
class VpdInterpretation:
    vpd_kpa: float
    vpd_leaf_kpa: Optional[float] = None
    level: str = ""               # optimal / moderate / stressed / severe
    label_cn: str = ""            # 中文标签
    color: str = ""               # 显示颜色
    stomata_status: str = ""      # 气孔状态
    plant_effect: str = ""        # 植物影响
    suggestion: str = ""          # 养护建议


def interpret_vpd(vpd_kpa: float, vpd_leaf_kpa: Optional[float] = None,
                  lux: Optional[float] = None) -> VpdInterpretation:
    """将 VPD 数值翻译为植物生理意义。

    核心修正：光照 ≈ 0（夜间）时，气孔生理性关闭，不管 VPD 多大蒸腾都接近零。
    VPD 高只表示空气干燥，不代表植物在蒸腾。
    """
    result = VpdInterpretation(vpd_kpa=vpd_kpa, vpd_leaf_kpa=vpd_leaf_kpa)

    is_night = lux is not None and lux < 50

    # ── 夜间：气孔关闭，VPD 仅反映空气干燥程度 ──
    if is_night:
        if vpd_kpa < 0.4:
            result.level = "low"
            result.label_cn = "夜间高湿"
            result.color = "#3b82f6"
            result.stomata_status = "气孔关闭（夜间正常）"
            result.plant_effect = "夜间空气近乎饱和，无蒸腾。持续高湿增加真菌病害风险。"
            result.suggestion = "如持续多夜高湿，注意通风"
        elif vpd_kpa < 1.5:
            result.level = "night_normal"
            result.label_cn = "夜间正常"
            result.color = "#64748b"
            result.stomata_status = "气孔关闭（夜间正常）"
            result.plant_effect = "夜间无蒸腾。空气湿度适中。植物正常休眠代谢。"
            result.suggestion = "无需干预"
        else:
            result.level = "night_dry"
            result.label_cn = "夜间干燥"
            result.color = "#f59e0b"
            result.stomata_status = "气孔关闭（夜间正常）"
            result.plant_effect = "夜间空气偏干，但气孔关闭所以不蒸腾。不影响植物。"
            result.suggestion = "无需干预。白天再观察 VPD。"
        return result

    # ── 白天：VPD 决定蒸腾强度 ──
    if vpd_kpa < 0.4:
        result.level = "low"
        result.label_cn = "过湿"
        result.color = "#3b82f6"
        result.stomata_status = "气孔全开，但蒸腾弱"
        result.plant_effect = "空气近乎饱和，水分凝结风险。真菌孢子易萌发（灰霉病、炭疽病窗口）"
        result.suggestion = "加强通风，降低湿度"
    elif vpd_kpa < 0.8:
        result.level = "optimal"
        result.label_cn = "理想"
        result.color = "#22c55e"
        result.stomata_status = "气孔全开"
        result.plant_effect = "蒸腾流畅，光合效率最高。养分吸收活跃。"
        result.suggestion = "维持当前环境"
    elif vpd_kpa < 1.2:
        result.level = "good"
        result.label_cn = "良好"
        result.color = "#84cc16"
        result.stomata_status = "气孔开放"
        result.plant_effect = "蒸腾正常，光合良好。"
        result.suggestion = "注意监测"
    elif vpd_kpa < 2.0:
        result.level = "moderate"
        result.label_cn = "偏高"
        result.color = "#f59e0b"
        result.stomata_status = "气孔部分关闭"
        result.plant_effect = "蒸腾加剧。植物开始节水。叶片可能出现午休现象。"
        result.suggestion = "考虑增加空气湿度或喷雾"
    elif vpd_kpa < 3.0:
        result.level = "stressed"
        result.label_cn = "胁迫"
        result.color = "#f97316"
        result.stomata_status = "气孔大幅关闭"
        result.plant_effect = "蒸腾严重受限。即使土壤有水，根系输水速度也跟不上。光合下降。"
        result.suggestion = "立即喷雾增湿或遮阳"
    else:
        result.level = "severe"
        result.label_cn = "严重"
        result.color = "#ef4444"
        result.stomata_status = "气孔几乎全关"
        result.plant_effect = "极端干旱空气。植物关闭气孔保命。光合停止。不可逆损伤风险。"
        result.suggestion = "紧急喷雾 + 遮阳"

    # 如果叶面 VPD 比空气 VPD 差很大，说明叶片被太阳晒热
    if vpd_leaf_kpa is not None and vpd_leaf_kpa - vpd_kpa > 0.5:
        result.plant_effect += " 叶片受太阳直射加热，蒸腾需求更强。"
        if result.level == "good":
            result.suggestion += "；可适当遮阳降低叶温"

    return result


# ═══════════════════════════════════════
# 3. 叶温-气温差 → 蒸腾冷却信号
# ═══════════════════════════════════════

@dataclass
class LeafCoolingSignal:
    delta_T: float               # T_leaf - T_air
    cooling_active: bool         # 蒸腾冷却是否在工作
    transpiration_level: str     # active / moderate / limited / suppressed
    interpretation: str


def analyze_leaf_cooling(T_leaf: float, T_air: float, lux: Optional[float] = None) -> LeafCoolingSignal:
    """用叶温-气温差判断蒸腾冷却状态"""
    dt = T_leaf - T_air
    result = LeafCoolingSignal(delta_T=dt, cooling_active=False,
                                transpiration_level="unknown", interpretation="")

    is_day = lux is not None and lux > 500

    if dt < -2.0:
        result.cooling_active = True
        result.transpiration_level = "active"
        result.interpretation = "蒸腾冷却强劲——植物水分充足，气孔全开，光合旺盛。"
    elif dt < 0:
        result.cooling_active = True
        result.transpiration_level = "moderate"
        result.interpretation = "蒸腾正常。如果光照很强但叶温仍低于气温→供水充足。"
    elif dt < 1.5:
        result.cooling_active = False
        result.transpiration_level = "limited"
        if is_day:
            result.interpretation = "蒸腾冷却不足。可能是轻度午休或VPD胁迫。"
        else:
            result.interpretation = "夜间无光照，气孔关闭，正常。"
    elif dt < 3.0:
        result.cooling_active = False
        result.transpiration_level = "suppressed"
        result.interpretation = "蒸腾严重受抑。气孔关闭保水。光合大幅下降。"
    else:
        result.cooling_active = False
        result.transpiration_level = "suppressed"
        result.interpretation = "蒸腾几乎停止。叶片正在发烧。检查灌溉和土壤湿度。"

    return result


# ═══════════════════════════════════════
# 4. CWSI —— 作物水分胁迫指数
# ═══════════════════════════════════════

def compute_cwsi(T_leaf: float, T_air: float, RH_air: float) -> Optional[float]:
    """简化 CWSI（不需要基准线标定）

    基于能量平衡的 Idso 方法。CWSI ∈ [0, 1]。
    0 = 供水充足 | 0.5 = 中度胁迫 | 1 = 完全胁迫

    简化逻辑：
    - VPD 越大，叶片理论最大温差越大
    - 实际温差 dT = T_leaf - T_air
    - CWSI = (dT - dT_min) / (dT_max - dT_min)
    - dT_min ≈ -2°C (充分供水冷却)
    - dT_max ≈ f(VPD)，粗略线性 ≈ 2 + 1.5×VPD
    """
    vpd = compute_vpd_air(T_air, RH_air)
    dt = T_leaf - T_air

    # 充分供水下的最低温差（蒸腾冷却最大）
    dt_min = -2.0
    # 完全胁迫下的最高温差（气孔全关 = 没有蒸腾冷却）
    dt_max = 2.0 + 1.5 * vpd

    if dt_max <= dt_min:
        return None

    cwsi = (dt - dt_min) / (dt_max - dt_min)
    return max(0.0, min(1.0, cwsi))


def interpret_cwsi(cwsi: float) -> str:
    """CWSI 的中文解读"""
    if cwsi < 0.15:
        return "供水充足，蒸腾顺畅"
    elif cwsi < 0.35:
        return "轻度水分胁迫，灌溉窗口"
    elif cwsi < 0.55:
        return "中度胁迫，建议尽快灌溉"
    elif cwsi < 0.75:
        return "严重胁迫，植物正在受损"
    else:
        return "极端胁迫，气孔全关"


# ═══════════════════════════════════════
# 5. ET₀ —— 参考蒸散量
# ═══════════════════════════════════════

def extraterrestrial_radiation(lat: float, doy: int) -> float:
    """天顶外大气层日辐射 Ra (MJ/m²/day)

    使用 FAO-56 公式。只依赖纬度和日期。
    """
    lat_rad = math.radians(lat)
    # 太阳赤纬
    decl = 0.409 * math.sin(2 * math.pi / 365 * doy - 1.39)
    # 日落时角
    omega_s = math.acos(-math.tan(lat_rad) * math.tan(decl))
    # 日地距离修正
    dr = 1 + 0.033 * math.cos(2 * math.pi / 365 * doy)

    gsc = 0.0820  # MJ/m²/min solar constant
    ra = (24 * 60 / math.pi) * gsc * dr * (
        omega_s * math.sin(lat_rad) * math.sin(decl) +
        math.cos(lat_rad) * math.cos(decl) * math.sin(omega_s)
    )
    return ra


def compute_et0_hargreaves(T_max: float, T_min: float, lat: float, doy: int) -> float:
    """Hargreaves-Samani 参考蒸散量 (mm/day)

    Args:
        T_max, T_min: 日最高/最低气温 (°C)
        lat: 纬度
        doy: 一年中的第几天 (1-366)

    Returns:
        参考蒸散量 mm/day（毫米/天）
    """
    T_mean = (T_max + T_min) / 2.0
    T_diff = max(0.5, T_max - T_min)  # 防止零温差

    Ra = extraterrestrial_radiation(lat, doy)

    et0 = 0.0023 * Ra * (T_mean + 17.8) * math.sqrt(T_diff)
    return max(0.0, et0)


# ═══════════════════════════════════════
# 6. 综合蒸腾评估
# ═══════════════════════════════════════

@dataclass
class TranspirationAssessment:
    """综合蒸腾评估结果"""
    timestamp: str = ""
    # VPD
    vpd_air: float = 0.0
    vpd_leaf: Optional[float] = None
    vpd_interpretation: Optional[VpdInterpretation] = None
    # 叶温信号
    leaf_cooling: Optional[LeafCoolingSignal] = None
    # CWSI
    cwsi: Optional[float] = None
    cwsi_interpretation: str = ""
    # ET₀
    et0_mm: Optional[float] = None
    # 综合状态
    plant_status: str = "未知"
    recommendation: str = ""


def assess_transpiration(
    T_air: Optional[float],
    RH_air: Optional[float],
    T_leaf: Optional[float] = None,
    lux: Optional[float] = None,
    T_max: Optional[float] = None,
    T_min: Optional[float] = None,
    lat: float = DEFAULT_LAT,
    doy: Optional[int] = None,
) -> Optional[TranspirationAssessment]:
    """一站式蒸腾评估

    最少需要 T_air + RH_air 即可计算 VPD。
    有叶温传感器时可以额外计算 CWSI 和蒸腾冷却。
    有日温极值时可计算 ET₀。
    """
    if T_air is None or RH_air is None:
        return None

    now = datetime.now(timezone.utc)
    if doy is None:
        doy = now.timetuple().tm_yday

    result = TranspirationAssessment(timestamp=now.isoformat())

    # VPD
    result.vpd_air = round(compute_vpd_air(T_air, RH_air), 2)

    if T_leaf is not None:
        result.vpd_leaf = round(compute_vpd_leaf(T_leaf, T_air, RH_air), 2)
        # 叶温冷却分析
        result.leaf_cooling = analyze_leaf_cooling(T_leaf, T_air, lux)
        # CWSI
        result.cwsi = round(compute_cwsi(T_leaf, T_air, RH_air), 3)
        result.cwsi_interpretation = interpret_cwsi(result.cwsi) if result.cwsi is not None else ""

    # VPD 解读（传入光照，夜间气孔关闭 ≠ 蒸腾良好）
    result.vpd_interpretation = interpret_vpd(result.vpd_air, result.vpd_leaf, lux)

    # ET₀
    if T_max is not None and T_min is not None:
        result.et0_mm = round(compute_et0_hargreaves(T_max, T_min, lat, doy), 2)

    # ── 综合状态 ──
    status_parts = []
    rec_parts = []

    vpdl = result.vpd_interpretation
    if vpdl:
        status_parts.append(f"VPD {result.vpd_air:.2f} kPa（{vpdl.label_cn}）")
        if vpdl.level in ("stressed", "severe"):
            rec_parts.append(vpdl.suggestion)

    if result.leaf_cooling:
        status_parts.append(result.leaf_cooling.transpiration_level)
        if result.leaf_cooling.transpiration_level == "suppressed":
            rec_parts.append("检查土壤湿度和灌溉状态")
        if result.cwsi is not None and result.cwsi > 0.4:
            rec_parts.append(result.cwsi_interpretation)

    result.plant_status = "；".join(status_parts) if status_parts else "未知"
    result.recommendation = "；".join(rec_parts) if rec_parts else "无需干预"

    return result


# ═══════════════════════════════════════
# 7. 从 InfluxDB 拉数据并评估
# ═══════════════════════════════════════

def fetch_and_assess(esp_id: str = "") -> list:
    """从 InfluxDB 拉取最近数据并做蒸腾评估"""
    from services.influx import influx_query_latest, influx_query_series
    from config import INFLUX_BUCKET

    latest = influx_query_latest(esp_id)

    # 按 source（树）分组
    tree_data: dict[str, dict] = {}
    for pt in latest:
        src = pt.get("source", pt.get("esp_id", "unknown"))
        sensor = pt.get("sensor", "")
        val = pt.get("value")
        if val is None:
            continue
        if src not in tree_data:
            tree_data[src] = {}
        tree_data[src][sensor] = val

    # 获取每个 ESP 的日最高/最低气温
    from services.influx import influx_query
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tmin_tmax = {}
    for esp_id_key in set(pt.get("esp_id", "") for pt in latest):
        if not esp_id_key:
            continue
        try:
            flux = f'''
            from(bucket: "{INFLUX_BUCKET}")
              |> range(start: {today_start.isoformat()})
              |> filter(fn: (r) => r._measurement == "sensor_data")
              |> filter(fn: (r) => r._field == "value")
              |> filter(fn: (r) => r.esp_id == "{esp_id_key}")
              |> filter(fn: (r) => r.sensor == "temperature" or r.sensor == "空气温度")
            '''
            rows = influx_query(flux)
            values = [r["value"] for r in rows if r.get("value") is not None]
            if values:
                tmin_tmax[esp_id_key] = (min(values), max(values))
        except Exception:
            pass

    results = []
    for src, sensors in tree_data.items():
        air_temp = sensors.get("temperature") or sensors.get("空气温度")
        air_rh = sensors.get("humidity") or sensors.get("空气湿度")
        leaf_temp = sensors.get("leaf_temp") or sensors.get("叶面温度")
        lux_val = sensors.get("lux") or sensors.get("光照度 0~65535")

        esp_for_tt = ""
        for pt in latest:
            if pt.get("source") == src:
                esp_for_tt = pt.get("esp_id", "")
                break

        t_range = tmin_tmax.get(esp_for_tt)
        t_max = t_range[1] if t_range else None
        t_min = t_range[0] if t_range else None

        if air_temp is None or air_rh is None:
            continue

        assessment = assess_transpiration(
            T_air=air_temp, RH_air=air_rh,
            T_leaf=leaf_temp, lux=lux_val,
            T_max=t_max, T_min=t_min,
            lat=DEFAULT_LAT,
        )
        if assessment:
            results.append({
                "source": src,
                "esp_id": esp_for_tt,
                "vpd_air": assessment.vpd_air,
                "vpd_leaf": assessment.vpd_leaf,
                "vpd_level": assessment.vpd_interpretation.level if assessment.vpd_interpretation else "",
                "vpd_label": assessment.vpd_interpretation.label_cn if assessment.vpd_interpretation else "",
                "vpd_color": assessment.vpd_interpretation.color if assessment.vpd_interpretation else "",
                "vpd_stomata": assessment.vpd_interpretation.stomata_status if assessment.vpd_interpretation else "",
                "vpd_effect": assessment.vpd_interpretation.plant_effect if assessment.vpd_interpretation else "",
                "vpd_suggestion": assessment.vpd_interpretation.suggestion if assessment.vpd_interpretation else "",
                "cwsi": assessment.cwsi,
                "cwsi_interpretation": assessment.cwsi_interpretation,
                "leaf_delta_t": assessment.leaf_cooling.delta_T if assessment.leaf_cooling else None,
                "leaf_cooling": assessment.leaf_cooling.transpiration_level if assessment.leaf_cooling else "",
                "et0_mm": assessment.et0_mm,
                "plant_status": assessment.plant_status,
                "recommendation": assessment.recommendation,
                "timestamp": assessment.timestamp,
            })

    return results
