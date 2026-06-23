"""时间上下文 —— 日出日落 / 季节 / 天气 / 灌溉状态"""
import math
from datetime import datetime, date, timezone, timedelta
from dataclasses import dataclass, field
from typing import Optional
import logging

logger = logging.getLogger("scada-alarm")

# 成都温江大致经纬度
DEFAULT_LAT = 30.7
DEFAULT_LNG = 103.8

@dataclass
class TemporalContext:
    """当前时刻的物理环境上下文，规则用这个判断「正常还是异常」"""
    timestamp: datetime
    lat: float = DEFAULT_LAT
    lng: float = DEFAULT_LNG

    # ── 计算字段 ──
    is_day: bool = False
    is_night: bool = False
    is_dawn_dusk: bool = False     # 日出/日落前后 1 小时
    solar_noon: bool = False        # 正午 ±1h
    season: str = ""                # spring / summer / autumn / winter
    hour_of_day: int = 0
    sunrise: Optional[datetime] = None
    sunset: Optional[datetime] = None

    # ── 外部注入 ──
    raining_now: bool = False       # 最近 30min 雨量 > 0
    rained_recently: bool = False   # 最近 2h 下过雨
    irrigating_now: bool = False    # 灌溉继电器开启中
    weather_temp: Optional[float] = None  # 天气预报气温

    @classmethod
    def now(cls, **kwargs) -> "TemporalContext":
        return cls.at(datetime.now(timezone.utc), **kwargs)

    @classmethod
    def at(cls, ts: datetime, lat: float = DEFAULT_LAT, lng: float = DEFAULT_LNG, **kwargs) -> "TemporalContext":
        # 统一转 naive UTC 做内部计算
        if ts.tzinfo is not None:
            ts_naive = ts.replace(tzinfo=None)
        else:
            ts_naive = ts

        ctx = cls(timestamp=ts, lat=lat, lng=lng, **kwargs)
        ctx._compute_sun()
        ctx._compute_season()
        ctx.hour_of_day = ts_naive.hour

        if ctx.sunrise and ctx.sunset:
            dawn_start = ctx.sunrise - timedelta(hours=1)
            dawn_end = ctx.sunrise + timedelta(hours=1)
            dusk_start = ctx.sunset - timedelta(hours=1)
            dusk_end = ctx.sunset + timedelta(hours=1)

            ctx.is_day = ctx.sunrise <= ts_naive <= ctx.sunset
            ctx.is_night = not ctx.is_day
            ctx.is_dawn_dusk = (
                (dawn_start <= ts_naive <= dawn_end) or
                (dusk_start <= ts_naive <= dusk_end)
            )
            noon = ctx.sunrise + (ctx.sunset - ctx.sunrise) / 2
            ctx.solar_noon = abs((ts_naive - noon).total_seconds()) < 3600

        return ctx

    def _compute_sun(self):
        """近似计算日出日落（误差 ±5 分钟）。

        使用 NOAA 太阳计算器简化公式，返回 UTC 时间。
        """
        try:
            ts = self.timestamp
            # 统一转为 UTC naive（用于 replace(hour=0)）
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)

            doy = ts.timetuple().tm_yday
            lat_rad = math.radians(self.lat)

            # 太阳赤纬（弧度）
            decl = 0.4093 * math.sin(2 * math.pi / 365 * doy - 1.405)

            # 时角（cos HA = -tan(lat)*tan(decl) - 考虑折射）
            cos_ha = (
                -math.sin(math.radians(-0.833)) - math.sin(lat_rad) * math.sin(decl)
            ) / (math.cos(lat_rad) * math.cos(decl))
            cos_ha = max(-1.0, min(1.0, cos_ha))
            ha_deg = math.degrees(math.acos(cos_ha))

            # 正午（太阳过中天）的 UTC 小时
            noon_utc_hours = 12.0 - self.lng / 15.0

            sunrise_hours = noon_utc_hours - ha_deg / 15.0
            sunset_hours = noon_utc_hours + ha_deg / 15.0

            base = ts.replace(hour=0, minute=0, second=0, microsecond=0)
            self.sunrise = base + timedelta(hours=sunrise_hours)
            self.sunset = base + timedelta(hours=sunset_hours)
        except Exception:
            self.sunrise = self.timestamp.replace(hour=6, minute=0, second=0)
            self.sunset = self.timestamp.replace(hour=18, minute=0, second=0)

    def _compute_season(self):
        m = self.timestamp.month
        if 3 <= m <= 5:    self.season = "spring"
        elif 6 <= m <= 8:  self.season = "summer"
        elif 9 <= m <= 11: self.season = "autumn"
        else:              self.season = "winter"

    def summary(self) -> str:
        parts = []
        parts.append("白天" if self.is_day else "夜间")
        parts.append(self.season)
        if self.raining_now:
            parts.append("下雨中")
        elif self.rained_recently:
            parts.append("刚下过雨")
        if self.irrigating_now:
            parts.append("灌溉中")
        return " · ".join(parts)
