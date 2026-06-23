"""告警规则 —— 纯函数，不碰 IO。输入 SensorWindow + TemporalContext，输出 AlarmVerdict 列表"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List
from enum import Enum
import logging

from .context import TemporalContext

logger = logging.getLogger("scada-alarm")


# ═══════════════════════════════════════
# 基础类型
# ═══════════════════════════════════════

class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    URGENT = "urgent"


class RuleCategory(str, Enum):
    SENSOR_FAULT = "sensor_fault"       # 传感器/接线故障
    DEVICE_FAULT = "device_fault"       # ESP 离线等
    PLANT_CARE = "plant_care"           # 养护相关


@dataclass
class AlarmVerdict:
    """单条规则判断结果"""
    rule_name: str
    category: RuleCategory
    severity: Severity
    message: str
    tree_id: Optional[int] = None
    esp_id: Optional[str] = None
    sensor_name: Optional[str] = None
    detail: dict = field(default_factory=dict)


@dataclass
class SensorWindow:
    """最近 N 分钟内的传感器数据切片，所有规则共享这个输入"""
    # 时间范围
    now: datetime
    lookback_minutes: int

    # ── 单传感器时序 ──
    leaf_temp: List[float] = field(default_factory=list)
    leaf_humidity: List[float] = field(default_factory=list)
    air_temp: List[float] = field(default_factory=list)
    air_humidity: List[float] = field(default_factory=list)
    soil_temp: List[float] = field(default_factory=list)
    soil_moisture: List[float] = field(default_factory=list)
    conductivity: List[float] = field(default_factory=list)   # EC
    lux: List[float] = field(default_factory=list)
    rainfall: List[float] = field(default_factory=list)

    # ── 元数据 ──
    tree_id: Optional[int] = None
    esp_id: Optional[str] = None
    # 各传感器最后数据时间
    last_data_time: dict = field(default_factory=dict)

    def data_age_seconds(self, sensor_key: str) -> Optional[float]:
        t = self.last_data_time.get(sensor_key)
        if t is None:
            return None
        return (self.now - t).total_seconds()

    def has(self, sensor_key: str) -> bool:
        series = getattr(self, sensor_key, None)
        return series is not None and len(series) > 0

    def latest(self, sensor_key: str) -> Optional[float]:
        series = getattr(self, sensor_key, None)
        if series is None:
            return None
        valid = [v for v in series if v is not None]
        return valid[-1] if valid else None

    def std(self, sensor_key: str) -> Optional[float]:
        series = getattr(self, sensor_key, None)
        if series is None or len(series) < 2:
            return None
        valid = [v for v in series if v is not None]
        if len(valid) < 2:
            return None
        mean = sum(valid) / len(valid)
        var = sum((v - mean) ** 2 for v in valid) / len(valid)
        return var ** 0.5

    def min(self, sensor_key: str) -> Optional[float]:
        series = getattr(self, sensor_key, None)
        if series is None:
            return None
        valid = [v for v in series if v is not None]
        return min(valid) if valid else None

    def max(self, sensor_key: str) -> Optional[float]:
        series = getattr(self, sensor_key, None)
        if series is None:
            return None
        valid = [v for v in series if v is not None]
        return max(valid) if valid else None

    def max_delta(self, sensor_key: str) -> Optional[float]:
        """相邻两点的最大绝对跳变"""
        series = getattr(self, sensor_key, None)
        if series is None or len(series) < 2:
            return None
        valid = [v for v in series if v is not None]
        if len(valid) < 2:
            return None
        return max(abs(valid[i+1] - valid[i]) for i in range(len(valid)-1))


# ═══════════════════════════════════════
# Layer 0: 单传感器数据质量
# ═══════════════════════════════════════

def check_data_freshness(win: SensorWindow, ctx: TemporalContext) -> List[AlarmVerdict]:
    """检查各传感器数据是否过期"""
    results = []
    thresholds = {
        "air_temp": ("空气温度", 10 * 60),      # 10 分钟
        "air_humidity": ("空气湿度", 10 * 60),
        "soil_temp": ("土壤温度", 15 * 60),
        "soil_moisture": ("土壤湿度", 15 * 60),
        "conductivity": ("电导率", 15 * 60),
        "lux": ("光照", 15 * 60),
        # 叶面和雨量是可选传感器，只有存在时才检查
        "leaf_temp": ("叶面温度", 15 * 60),
        "leaf_humidity": ("叶面湿度", 15 * 60),
        "rainfall": ("雨量", 30 * 60),
    }
    for key, (label, max_age) in thresholds.items():
        age = win.data_age_seconds(key)
        if age is None:
            continue  # 传感器不存在，跳过
        if age > max_age:
            minutes = int(age // 60)
            # 叶面/雨量传感器暂时缺失不发告警（可能还没接）
            if key.startswith("leaf_") or key == "rainfall":
                sev = Severity.INFO
            else:
                sev = Severity.WARNING if minutes < 30 else Severity.URGENT
            results.append(AlarmVerdict(
                rule_name="data_stale",
                category=RuleCategory.SENSOR_FAULT,
                severity=sev,
                message=f"{label} {minutes} 分钟无数据",
                tree_id=win.tree_id,
                esp_id=win.esp_id,
                sensor_name=key,
                detail={"sensor": key, "age_minutes": minutes},
            ))
    return results


def check_frozen_value(win: SensorWindow, ctx: TemporalContext) -> List[AlarmVerdict]:
    """检查数据是否冻结（读数卡死）"""
    results = []
    checks = [
        ("air_temp", "空气温度"),
        ("air_humidity", "空气湿度"),
        ("soil_temp", "土壤温度"),
        ("soil_moisture", "土壤湿度"),
        ("conductivity", "电导率"),
        ("lux", "光照"),
    ]
    for key, label in checks:
        std = win.std(key)
        series = getattr(win, key, None)
        if series is None or len(series) < 12:
            continue
        if std is not None and std < 1e-6 and len(series) >= 12:
            # 12 个点全部一样，几乎不可能
            results.append(AlarmVerdict(
                rule_name="frozen_value",
                category=RuleCategory.SENSOR_FAULT,
                severity=Severity.WARNING,
                message=f"{label} 读数可能冻结（{len(series)}个点完全相同）",
                tree_id=win.tree_id,
                esp_id=win.esp_id,
                sensor_name=key,
                detail={"sensor": key, "point_count": len(series)},
            ))
    return results


def check_physical_range(win: SensorWindow, ctx: TemporalContext) -> List[AlarmVerdict]:
    """检查是否超出物理量程"""
    results = []
    ranges = {
        "air_temp": ("空气温度", -40, 80),
        "air_humidity": ("空气湿度", 0, 100),
        "soil_temp": ("土壤温度", -20, 60),
        "soil_moisture": ("土壤湿度", 0, 100),
        "conductivity": ("电导率", 0, 20000),
        "lux": ("光照", 0, 200000),
    }
    for key, (label, lo, hi) in ranges.items():
        v = win.latest(key)
        if v is not None and (v < lo or v > hi):
            results.append(AlarmVerdict(
                rule_name="out_of_range",
                category=RuleCategory.SENSOR_FAULT,
                severity=Severity.WARNING,
                message=f"{label} 读数 {v} 超出量程 [{lo}, {hi}]",
                tree_id=win.tree_id,
                esp_id=win.esp_id,
                sensor_name=key,
                detail={"sensor": key, "value": v, "range": [lo, hi]},
            ))
    return results


def check_spike(win: SensorWindow, ctx: TemporalContext) -> List[AlarmVerdict]:
    """检查瞬间跳变（物理上不可能的变化速率）"""
    results = []
    limits = {
        "air_temp": ("空气温度", 8.0),       # °C/次
        "soil_temp": ("土壤温度", 3.0),       # 土壤热容量大，不可能突变
        "conductivity": ("电导率", 500.0),    # μS/cm/次
        "lux": ("光照", 50000.0),            # 除非被人用手电筒照
    }
    for key, (label, limit) in limits.items():
        delta = win.max_delta(key)
        if delta is not None and delta > limit:
            # 雨量检查：如果下雨中，气压变化等可能导致光照骤降，放宽判断
            if key == "lux" and ctx.raining_now:
                continue
            results.append(AlarmVerdict(
                rule_name="value_spike",
                category=RuleCategory.SENSOR_FAULT,
                severity=Severity.WARNING,
                message=f"{label} 瞬间跳变 {delta:.1f}，可能接线松动",
                tree_id=win.tree_id,
                esp_id=win.esp_id,
                sensor_name=key,
                detail={"sensor": key, "delta": delta},
            ))
    return results


# ═══════════════════════════════════════
# Layer 1: 跨传感器物理验证
# ═══════════════════════════════════════

def check_temperature_order(win: SensorWindow, ctx: TemporalContext) -> List[AlarmVerdict]:
    """白天应满足：叶温 >= 气温 >= 土温。违反物理定律 → 传感器故障"""
    results = []
    leaf = win.latest("leaf_temp")
    air = win.latest("air_temp")
    soil = win.latest("soil_temp")

    if any(v is None for v in (leaf, air, soil)):
        return results  # 传感器不全，跳过

    if ctx.is_day and not ctx.raining_now and not ctx.irrigating_now:
        # 叶温应该 >= 空气温度（太阳辐射加热叶片）
        if leaf < air - 2.0:
            results.append(AlarmVerdict(
                rule_name="temp_order_violation",
                category=RuleCategory.SENSOR_FAULT,
                severity=Severity.WARNING,
                message=f"白天叶温({leaf:.1f}°C)低于气温({air:.1f}°C)超过2°C，违反物理规律",
                tree_id=win.tree_id,
                esp_id=win.esp_id,
                detail={"leaf_temp": leaf, "air_temp": air, "soil_temp": soil},
            ))

        # 土壤温度白天应低于空气温度
        if soil > air + 5.0:
            results.append(AlarmVerdict(
                rule_name="temp_order_violation_soil",
                category=RuleCategory.SENSOR_FAULT,
                severity=Severity.WARNING,
                message=f"白天土温({soil:.1f}°C)显著高于气温({air:.1f}°C)，可能土壤探头暴露",
                tree_id=win.tree_id,
                esp_id=win.esp_id,
                detail={"leaf_temp": leaf, "air_temp": air, "soil_temp": soil},
            ))

    return results


def check_dark_heat(win: SensorWindow, ctx: TemporalContext) -> List[AlarmVerdict]:
    """夜间光照=0 但叶温 > 气温超过 2°C → 物理上不可能"""
    results = []
    lux = win.latest("lux")
    leaf = win.latest("leaf_temp")
    air = win.latest("air_temp")

    if any(v is None for v in (lux, leaf, air)):
        return results

    if lux is not None and lux < 5 and ctx.is_night:
        if leaf > air + 2.0:
            results.append(AlarmVerdict(
                rule_name="dark_heat_anomaly",
                category=RuleCategory.SENSOR_FAULT,
                severity=Severity.WARNING,
                message=f"夜间无光照但叶温({leaf:.1f}°C)高于气温({air:.1f}°C)，传感器异常",
                tree_id=win.tree_id,
                esp_id=win.esp_id,
                detail={"leaf_temp": leaf, "air_temp": air, "lux": lux},
            ))
    return results


def check_moisture_spike_without_rain(win: SensorWindow, ctx: TemporalContext) -> List[AlarmVerdict]:
    """土壤湿度飙升但没有下雨也没有灌溉 → 传感器被水泡 / 漏水"""
    results = []
    if not win.has("soil_moisture"):
        return results

    if ctx.raining_now or ctx.rained_recently or ctx.irrigating_now:
        return results

    # 最近 5 个点的土壤湿度 vs 前 5 个点
    sm = [v for v in win.soil_moisture if v is not None]
    if len(sm) < 10:
        return results
    older = sm[:5]
    newer = sm[-5:]
    old_avg = sum(older) / len(older)
    new_avg = sum(newer) / len(newer)
    if new_avg - old_avg > 10:  # 飙升 > 10%
        results.append(AlarmVerdict(
            rule_name="moisture_spike_no_rain",
            category=RuleCategory.SENSOR_FAULT,
            severity=Severity.WARNING,
            message=f"土壤湿度飙升 {new_avg - old_avg:.1f}%，但无降雨无灌溉，可能传感器异常",
            tree_id=win.tree_id,
            esp_id=win.esp_id,
            sensor_name="soil_moisture",
            detail={"old_avg": old_avg, "new_avg": new_avg},
        ))
    return results


def check_ec_probe_fault(win: SensorWindow, ctx: TemporalContext) -> List[AlarmVerdict]:
    """EC 跳变但土壤湿度不变 → 探头接触不良或故障"""
    results = []
    if not win.has("conductivity") or not win.has("soil_moisture"):
        return results

    ec_delta = win.max_delta("conductivity")
    sm_delta = win.max_delta("soil_moisture")

    if ec_delta is not None and ec_delta > 500 and sm_delta is not None and sm_delta < 2:
        results.append(AlarmVerdict(
            rule_name="ec_spike_no_moisture_change",
            category=RuleCategory.SENSOR_FAULT,
            severity=Severity.WARNING,
            message=f"电导率跳变 {ec_delta:.0f} μS/cm 但土壤湿度几乎不变，EC 探头可能故障",
            tree_id=win.tree_id,
            esp_id=win.esp_id,
            sensor_name="conductivity",
            detail={"ec_delta": ec_delta, "sm_delta": sm_delta},
        ))
    return results


# ═══════════════════════════════════════
# Layer 2: 植物养护评估
# ═══════════════════════════════════════

def check_drought_stress(win: SensorWindow, ctx: TemporalContext) -> List[AlarmVerdict]:
    """干旱胁迫评分：综合土湿 + 叶温-气温差 + 光照 + 空气湿度 + 雨量"""
    results = []
    sm = win.latest("soil_moisture")
    leaf = win.latest("leaf_temp")
    air = win.latest("air_temp")
    lux = win.latest("lux")
    ah = win.latest("air_humidity")

    if sm is None:
        return results

    score = 0
    reasons = []

    if sm < 25:
        score += 30
        reasons.append(f"土壤湿度 {sm:.1f}%")
    elif sm < 35:
        score += 15
        reasons.append(f"土壤湿度偏低 {sm:.1f}%")

    if leaf is not None and air is not None and leaf > air + 3:
        score += 25
        reasons.append(f"叶温高于气温 {leaf - air:.1f}°C（蒸腾不足）")

    if lux is not None and lux > 60000:
        score += 15
        reasons.append(f"强光照 {lux:.0f} lux")

    if ah is not None and ah < 35:
        score += 15
        reasons.append(f"空气干燥 {ah:.1f}%")

    if not ctx.rained_recently and not ctx.irrigating_now:
        score += 15

    if score >= 80:
        results.append(AlarmVerdict(
            rule_name="drought_stress",
            category=RuleCategory.PLANT_CARE,
            severity=Severity.URGENT,
            message=f"严重缺水（评分 {score}）：{'，'.join(reasons)}",
            tree_id=win.tree_id,
            esp_id=win.esp_id,
            detail={"score": score, "reasons": reasons},
        ))
    elif score >= 60:
        results.append(AlarmVerdict(
            rule_name="drought_stress",
            category=RuleCategory.PLANT_CARE,
            severity=Severity.WARNING,
            message=f"建议浇水（评分 {score}）：{'，'.join(reasons)}",
            tree_id=win.tree_id,
            esp_id=win.esp_id,
            detail={"score": score, "reasons": reasons},
        ))

    return results


def check_frost_risk(win: SensorWindow, ctx: TemporalContext) -> List[AlarmVerdict]:
    """冻害监测 —— 分层预警"""
    results = []
    leaf = win.latest("leaf_temp")
    air = win.latest("air_temp")

    temp = leaf if leaf is not None else air
    if temp is None:
        return results

    sensor_label = "叶温" if leaf is not None else "气温"

    # 只在夜间 + 冬季/早春判断
    if not ctx.is_night and not (ctx.season in ("winter", "spring") and ctx.is_dawn_dusk):
        return results

    if temp < 0.0:
        results.append(AlarmVerdict(
            rule_name="frost",
            category=RuleCategory.PLANT_CARE,
            severity=Severity.URGENT,
            message=f"🔴 霜冻！{sensor_label} {temp:.1f}°C，叶片正在结冰",
            tree_id=win.tree_id,
            esp_id=win.esp_id,
            detail={"temperature": temp, "sensor": "leaf" if leaf is not None else "air"},
        ))
    elif temp < 4.0:
        results.append(AlarmVerdict(
            rule_name="frost_warning",
            category=RuleCategory.PLANT_CARE,
            severity=Severity.WARNING,
            message=f"⚠️ 低温预警：{sensor_label} {temp:.1f}°C，有霜冻风险",
            tree_id=win.tree_id,
            esp_id=win.esp_id,
            detail={"temperature": temp, "sensor": "leaf" if leaf is not None else "air"},
        ))

    return results


def check_heat_stress(win: SensorWindow, ctx: TemporalContext) -> List[AlarmVerdict]:
    """高温胁迫"""
    results = []
    leaf = win.latest("leaf_temp")
    air = win.latest("air_temp")
    lux = win.latest("lux")

    temp = leaf if leaf is not None else air
    if temp is None:
        return results

    sensor_label = "叶温" if leaf is not None else "气温"

    if temp > 40:
        results.append(AlarmVerdict(
            rule_name="heat_stress",
            category=RuleCategory.PLANT_CARE,
            severity=Severity.URGENT,
            message=f"🔴 高温胁迫：{sensor_label} {temp:.1f}°C，光合作用停止",
            tree_id=win.tree_id,
            esp_id=win.esp_id,
            detail={"temperature": temp},
        ))
    elif temp > 35 and ctx.is_day and ctx.solar_noon:
        # 正午超过 35°C
        results.append(AlarmVerdict(
            rule_name="heat_warning",
            category=RuleCategory.PLANT_CARE,
            severity=Severity.WARNING,
            message=f"⚠️ {sensor_label} {temp:.1f}°C，建议遮阳或喷水",
            tree_id=win.tree_id,
            esp_id=win.esp_id,
            detail={"temperature": temp},
        ))

    return results


def check_leaf_wetness_disease(win: SensorWindow, ctx: TemporalContext) -> List[AlarmVerdict]:
    """叶面持续湿润 → 病害风险"""
    results = []
    lh = win.latest("leaf_humidity")
    air_temp = win.latest("air_temp")

    if lh is None or air_temp is None:
        return results

    if lh > 90 and 15 <= air_temp <= 28 and ctx.is_night:
        # 夜间高湿 + 适宜温度 = 灰霉病窗口
        results.append(AlarmVerdict(
            rule_name="disease_risk",
            category=RuleCategory.PLANT_CARE,
            severity=Severity.WARNING,
            message=f"⚠️ 叶面湿度 {lh:.1f}% + 气温 {air_temp:.1f}°C，灰霉病高风险，建议预防打药",
            tree_id=win.tree_id,
            esp_id=win.esp_id,
            detail={"leaf_humidity": lh, "air_temp": air_temp},
        ))

    return results


def check_root_rot_risk(win: SensorWindow, ctx: TemporalContext) -> List[AlarmVerdict]:
    """土壤长期过湿 → 烂根风险"""
    results = []
    sm = win.latest("soil_moisture")
    if sm is None:
        return results

    if sm > 80:
        # 检查是否已经持续很久
        high_count = sum(1 for v in win.soil_moisture if v is not None and v > 80)
        if high_count >= len(win.soil_moisture) * 0.8:  # 80% 的点 > 80%
            results.append(AlarmVerdict(
                rule_name="root_rot_risk",
                category=RuleCategory.PLANT_CARE,
                severity=Severity.WARNING,
                message=f"土壤湿度 > 80% 持续时间长，根系缺氧烂根风险",
                tree_id=win.tree_id,
                esp_id=win.esp_id,
                detail={"soil_moisture": sm, "high_points": high_count},
            ))
    return results


def check_nutrient_depletion(win: SensorWindow, ctx: TemporalContext) -> List[AlarmVerdict]:
    """EC 长期偏低 → 养分耗尽"""
    results = []
    ec = win.latest("conductivity")
    if ec is None:
        return results

    if ec < 0.2:
        results.append(AlarmVerdict(
            rule_name="nutrient_depleted",
            category=RuleCategory.PLANT_CARE,
            severity=Severity.INFO,
            message=f"土壤 EC {ec:.2f} mS/cm，养分可能耗尽，建议追肥",
            tree_id=win.tree_id,
            esp_id=win.esp_id,
            detail={"ec": ec},
        ))
    elif ec > 4.0:
        results.append(AlarmVerdict(
            rule_name="excess_salinity",
            category=RuleCategory.PLANT_CARE,
            severity=Severity.WARNING,
            message=f"土壤 EC {ec:.1f} mS/cm 偏高，可能盐害，建议淋洗",
            tree_id=win.tree_id,
            esp_id=win.esp_id,
            detail={"ec": ec},
        ))
    return results


# ═══════════════════════════════════════
# Layer 3: 设备/系统健康
# ═══════════════════════════════════════

def check_esp_heartbeat(esp_id: str, last_seen: datetime, now: datetime) -> Optional[AlarmVerdict]:
    """ESP 心跳检查（不在 SensorWindow 里，因为不依赖传感器数据）"""
    age = (now - last_seen).total_seconds()
    if age > 30 * 60:
        return AlarmVerdict(
            rule_name="esp_offline",
            category=RuleCategory.DEVICE_FAULT,
            severity=Severity.URGENT,
            message=f"ESP {esp_id} 离线超过 30 分钟",
            esp_id=esp_id,
            detail={"last_seen": last_seen.isoformat(), "age_minutes": int(age // 60)},
        )
    elif age > 5 * 60:
        return AlarmVerdict(
            rule_name="esp_offline",
            category=RuleCategory.DEVICE_FAULT,
            severity=Severity.WARNING,
            message=f"ESP {esp_id} 离线超过 5 分钟",
            esp_id=esp_id,
            detail={"last_seen": last_seen.isoformat(), "age_minutes": int(age // 60)},
        )
    return None


# ═══════════════════════════════════════
# 规则注册表
# ═══════════════════════════════════════

# Layer 0: 质量检查（每周期都跑）
LAYER0_RULES = [
    check_data_freshness,
    check_frozen_value,
    check_physical_range,
    check_spike,
]

# Layer 1: 物理验证（有完整传感器数据时跑）
LAYER1_RULES = [
    check_temperature_order,
    check_dark_heat,
    check_moisture_spike_without_rain,
    check_ec_probe_fault,
]

# Layer 2: 养护评估（慢周期跑）
LAYER2_RULES = [
    check_drought_stress,
    check_frost_risk,
    check_heat_stress,
    check_leaf_wetness_disease,
    check_root_rot_risk,
    check_nutrient_depletion,
]
