#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
耐力教练 · 天气取数与训练修正（Open-Meteo，无需注册、无第三方依赖）

用途
----
给教练提供「当天实况 + 未来 N 天预报 + 空气质量」，并把天气换算成
**确定性的训练修正**（体感档位、配速修正、户外/室内建议、天气最优时段），
模型只负责复述脚本结论，不自己做加减法。

数据源（都无需注册、无需申请账号）
--------------------
- 预报/实况：https://api.open-meteo.com/v1/forecast          （16 天）
- 空气质量（形状）：https://air-quality-api.open-meteo.com/v1/air-quality （CAMS PM2.5，5 天）
- 空气质量（量级）：https://aqicn.org/aqicn/json/android/<city>/（官方监测站实测，逐小时回看 ~50h）

空气质量口径（重要）
--------------------
CAMS 全球模式在中国北方平原系统性偏高：实测北京海淀 2026-11-22~24 的 45 个配对小时里，
站点实测 PM2.5 中位数 6 µg/m³、CAMS 中位数 59 µg/m³，比例中位数 6.4 倍（p90 24.9 倍）。
直接用 CAMS 绝对值会把「优」判成「重度污染」，导致误取消户外课。所以：

1. **站点实测锚定**：档案里 `location.aq_city` 填了 aqicn 城市 slug 时，用官方监测站实测
   反算的 PM2.5 定绝对量；没填就跳过实测，输出标「模型估算」。
2. **模型只贡献形状**：未来小时 = CAMS ÷ 比例因子，比例因子取最近 48h「模型/实测」稳健中位数
   （≥8 个配对小时才启用，夹在 [0.05, 20]）。
3. **判级用中国 AQI，且看训练时段**：不再用全天 PM2.5 均值，改用最优训练窗口的 AQI。
4. **没锚定就不硬封**：纯模型数据、或预报超过 2 天时，AQ 最多给到「注意」，不据此取消户外课。

坐标来源（按优先级）：
1. 显式 --lat/--lon（配合 --name 显示地名）
2. --athlete 指定的档案文件（默认 `coach/athlete.json`，可用环境变量
   ENDURANCE_COACH_DIR 改默认目录）里的 location.lat / location.lon
3. 档案里只有城市名时，用内置的常见城市中心坐标表解析（近似值）

用法
----
    python weather.py                         # 今天 + 未来 7 天（文本简报）
    python weather.py --days 16               # 最多 16 天
    python weather.py --date 2027-04-18       # 只看某个日期（赛前查比赛日）
    python weather.py --json                  # 机器可读 JSON
    python weather.py --offline               # 只用缓存（断网/测试）
    python weather.py --lat 30.05 --lon 120.10 --name 比赛地
    python weather.py --athlete coach/athlete.json --cache coach/.cache/weather.json
    python weather.py --out-md coach/weather-latest.md --out-json coach/weather-latest.json

退出码
------
    0  成功
    2  天气数据未取到（网络失败且无缓存）—— 模型必须写「天气数据未取到」，禁止臆造
    3  参数/档案配置错误（没有可用坐标、日期格式错误等）

约束
----
- 只做确定性算术与阈值判断，阈值集中在 classify_day / pace_adjust 里，可审计。
- 输出 UTF-8；Windows 控制台会强制切 utf-8，避免 GBK 乱码。
- 缓存 30 分钟；网络失败时允许回退 ≤36h 的旧缓存，并明确标注「可能过期」。
- 脚本里不写死任何人的坐标；位置一律来自参数或档案。
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径与常量
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_COACH_DIR = Path(os.environ.get("ENDURANCE_COACH_DIR", "coach"))
DEFAULT_ATHLETE = DEFAULT_COACH_DIR / "athlete.json"

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
AQ_OBS_URL = "https://aqicn.org/aqicn/json/android/{city}/"   # 官方监测站实测（逐小时）

# US EPA AQI ←→ PM2.5 (µg/m³) 分段（aqicn 给的是 US AQI，要反算浓度）
US_AQI_PM25_BP = [
    (0, 50, 0.0, 12.0),
    (51, 100, 12.1, 35.4),
    (101, 150, 35.5, 55.4),
    (151, 200, 55.5, 150.4),
    (201, 300, 150.5, 250.4),
    (301, 400, 250.5, 350.4),
    (401, 500, 350.5, 500.4),
]

# 中国 HJ 633-2012 PM2.5 24h 浓度 → IAQI 分段
CN_IAQI_PM25_BP = [
    (0.0, 35.0, 0, 50),
    (35.0, 75.0, 50, 100),
    (75.0, 115.0, 100, 150),
    (115.0, 150.0, 150, 200),
    (150.0, 250.0, 200, 300),
    (250.0, 350.0, 300, 400),
    (350.0, 500.0, 400, 500),
]

# 校准：只用最近 N 小时的配对样本，样本太少就不校准
CALIB_WINDOW_HOURS = 48
CALIB_MIN_PAIRS = 8
CALIB_RATIO_MIN, CALIB_RATIO_MAX = 0.05, 20.0
CALIB_BIAS_ALERT = 3.0        # 比例偏离这个范围就提示「模型偏差大」
OBS_MAX_LAG_HOURS = 6         # 站点实测超过这么久没更新就不用来锚定

CACHE_TTL_SECONDS = 30 * 60          # 30 分钟内重复调用直接用缓存
STALE_MAX_SECONDS = 36 * 3600        # 断网时最多接受 36h 的旧缓存
FORECAST_DAYS_FETCHED = 16           # 永远取满 16 天，避免 --date 换宽时缓存不匹配
AQ_DAYS = 5                          # 空气质量预报只取 5 天，更远为 None

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 常见城市中心坐标（近似值，仅供「档案里只写了城市名」时兜底解析）。
# 需要精确位置时请在 athlete.json 里直接写 lat/lon。
CITY_COORDS = {
    "北京": (39.9042, 116.4074),
    "上海": (31.2304, 121.4737),
    "广州": (23.1291, 113.2644),
    "深圳": (22.5431, 114.0579),
    "杭州": (30.2741, 120.1551),
    "成都": (30.5728, 104.0668),
    "重庆": (29.5630, 106.5516),
    "武汉": (30.5928, 114.3055),
    "西安": (34.3416, 108.9398),
    "南京": (32.0603, 118.7969),
    "天津": (39.3434, 117.3616),
    "苏州": (31.2989, 120.5853),
    "青岛": (36.0671, 120.3826),
    "厦门": (24.4798, 118.0894),
    "昆明": (25.0389, 102.7183),
    "长沙": (28.2282, 112.9388),
    "郑州": (34.7466, 113.6254),
    "沈阳": (41.8057, 123.4315),
    "哈尔滨": (45.8038, 126.5349),
    "台北": (25.0330, 121.5654),
    "东京": (35.6762, 139.6503),
    "新加坡": (1.3521, 103.8198),
    "伦敦": (51.5072, -0.1276),
    "纽约": (40.7128, -74.0060),
    "悉尼": (-33.8688, 151.2093),
    "柏林": (52.5200, 13.4050),
    "巴黎": (48.8566, 2.3522),
}

# WMO weather code → 中文
WMO_TEXT = {
    0: "晴", 1: "大部晴", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "毛毛雨", 55: "密毛毛雨",
    56: "冻毛毛雨", 57: "密冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
    80: "阵雨", 81: "强阵雨", 82: "暴阵雨",
    85: "阵雪", 86: "强阵雪",
    95: "雷暴", 96: "雷暴伴小冰雹", 99: "雷暴伴大冰雹",
}
SNOW_CODES = {71, 73, 75, 77, 85, 86}
THUNDER_CODES = {95, 96, 99}


class ConfigError(RuntimeError):
    """档案/坐标/参数配置错误（退出码 3）。"""


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _utf8_stdout() -> None:
    """Windows 控制台默认 GBK，中文/℃/µg 会炸；强制 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def _http_json(url: str, timeout: int = 20, retries: int = 2) -> dict:
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "endurance-coach/1.0 (weather.py)",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            return json.loads(raw)
        except Exception as exc:  # noqa: BLE001 - 统一收集后重试
            last_err = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"请求失败：{last_err}")


def resolve_athlete_path(args: argparse.Namespace) -> Path:
    """--athlete 优先，其次 ENDURANCE_COACH_DIR/athlete.json，最后 coach/athlete.json。"""
    if getattr(args, "athlete", None):
        return Path(args.athlete).expanduser()
    return DEFAULT_ATHLETE


def resolve_cache_path(args: argparse.Namespace, athlete_path: Path) -> Path:
    if getattr(args, "cache", None):
        return Path(args.cache).expanduser()
    coach_dir = athlete_path.parent if athlete_path else DEFAULT_COACH_DIR
    return coach_dir / ".cache" / "weather.json"


def load_athlete(athlete_path: Path) -> dict | None:
    try:
        data = json.loads(athlete_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ 读档案 {athlete_path} 失败（{exc}）", file=sys.stderr)
        return None


def resolve_city(name: str | None) -> tuple[float, float] | None:
    """把城市名解析成近似中心坐标（仅内置常见城市）。"""
    if not name:
        return None
    key = str(name).strip()
    for candidate in (key, key.rstrip("市"), key.lower()):
        if candidate in CITY_COORDS:
            return CITY_COORDS[candidate]
    return None


def load_location(args: argparse.Namespace, athlete: dict | None) -> dict:
    """确定取数坐标：显式参数 > 档案 location > 城市名解析。"""
    profile = (athlete or {}).get("location") or {}
    loc = {
        "name": profile.get("name") or profile.get("city") or "指定坐标",
        "city": profile.get("city") or profile.get("name") or "",
        "lat": profile.get("lat"),
        "lon": profile.get("lon"),
        "timezone": profile.get("timezone") or "auto",
        "aq_city": profile.get("aq_city"),
    }

    if args.lat is not None:
        loc["lat"] = args.lat
    if args.lon is not None:
        loc["lon"] = args.lon
    if args.name:
        loc["name"] = args.name

    if loc["lat"] is None or loc["lon"] is None:
        coords = resolve_city(loc.get("city")) or resolve_city(loc.get("name"))
        if coords is None:
            raise ConfigError(
                "没有可用坐标：请先在 coach/athlete.json 的 location 填写 lat/lon，"
                "或用 --lat/--lon 指定；首次使用可运行 init_athlete.py 生成档案模板。"
            )
        loc["lat"], loc["lon"] = coords

    try:
        loc["lat"] = float(loc["lat"])
        loc["lon"] = float(loc["lon"])
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"坐标不是数字：lat={loc['lat']!r} lon={loc['lon']!r}") from exc

    if not (-90 <= loc["lat"] <= 90) or not (-180 <= loc["lon"] <= 180):
        raise ConfigError(f"坐标超出范围：lat={loc['lat']} lon={loc['lon']}")

    return loc


def guard_aq_city(loc: dict, athlete: dict | None) -> None:
    """取数点偏离档案常驻地 >0.5°（≈55km）时，aqicn 的城市站点不再可比，停用实测锚定。

    典型场景：比赛日在山里/外地，气温用当地坐标，空气却不能再用常驻城市的监测站锚定。
    """
    if not loc.get("aq_city") or not athlete:
        return
    profile = (athlete or {}).get("location") or {}
    try:
        far = (abs(float(loc["lat"]) - float(profile["lat"])) > 0.5
               or abs(float(loc["lon"]) - float(profile["lon"])) > 0.5)
    except (KeyError, TypeError, ValueError):
        return
    if far:
        loc["aq_city"] = None
        loc["aq_skipped"] = "坐标已离开档案城市，停用站点实测锚定（空气退回模型估算）"


def load_venue_for_date(athlete: dict | None, date_str: str | None) -> dict | None:
    """如果 --date 正好是档案里登记的赛事地，自动用比赛地坐标。"""
    if not date_str or not athlete:
        return None
    venues = (athlete.get("weather_policy") or {}).get("venues") or []
    for venue in venues:
        if str(venue.get("date")) == date_str and venue.get("lat") is not None \
                and venue.get("lon") is not None:
            return venue
    return None


def round1(value):
    if value is None:
        return None
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def num(value, fmt: str = "g", fallback: str = "-") -> str:
    """安全格式化可能是 None 的数值。"""
    if value is None:
        return fallback
    try:
        return format(float(value), fmt)
    except (TypeError, ValueError):
        return fallback


def fmt_range(low, high, unit: str = "℃") -> str:
    if low is None or high is None:
        return "无数据"
    return f"{num(low)}~{num(high)}{unit}"


# ---------------------------------------------------------------------------
# 取数（含缓存）
# ---------------------------------------------------------------------------

def _forecast_query(loc: dict) -> str:
    params = {
        "latitude": loc["lat"],
        "longitude": loc["lon"],
        "timezone": loc["timezone"],
        "forecast_days": FORECAST_DAYS_FETCHED,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                   "precipitation,weather_code,wind_speed_10m,wind_gusts_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "apparent_temperature_max,apparent_temperature_min,"
                 "precipitation_sum,precipitation_probability_max,"
                 "wind_speed_10m_max,wind_gusts_10m_max,uv_index_max,"
                 "sunrise,sunset",
        "hourly": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                  "precipitation,precipitation_probability,"
                  "wind_speed_10m,wind_gusts_10m",
    }
    return FORECAST_URL + "?" + urllib.parse.urlencode(params)


def _air_query(loc: dict) -> str:
    params = {
        "latitude": loc["lat"],
        "longitude": loc["lon"],
        "timezone": loc["timezone"],
        # 多取 2 天历史：校准要用「最近 48h 实测 vs 模型」的配对样本
        "past_days": 2,
        "forecast_days": AQ_DAYS,
        "current": "pm2_5",
        "hourly": "pm2_5",
    }
    return AIR_URL + "?" + urllib.parse.urlencode(params)


def _aq_obs_url(loc: dict) -> str | None:
    city = (loc.get("aq_city") or "").strip()
    if not city:
        return None
    return AQ_OBS_URL.format(city=urllib.parse.quote(city))


def load_cache(cache_file: Path) -> dict:
    try:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_cache(cache_file: Path, loc: dict, forecast: dict, air: dict | None,
               aq_obs: dict | None = None) -> None:
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fetched_at": int(time.time()),
            "lat": loc["lat"],
            "lon": loc["lon"],
            "name": loc["name"],
            "aq_city": loc.get("aq_city"),
            "forecast": forecast,
            "air": air,
            "aq_obs": aq_obs,
        }
        cache_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - 缓存失败不影响主流程
        print(f"⚠️ 写缓存失败：{exc}", file=sys.stderr)


def _cache_match(cache: dict, loc: dict) -> bool:
    if not cache.get("forecast"):
        return False
    try:
        if abs(float(cache.get("lat", 999)) - loc["lat"]) >= 0.05:
            return False
        if abs(float(cache.get("lon", 999)) - loc["lon"]) >= 0.05:
            return False
    except (TypeError, ValueError):
        return False
    # 换了城市（aq_city 不同）时，缓存里的实测也不可用
    return (cache.get("aq_city") or None) == (loc.get("aq_city") or None)


def fetch_weather(loc: dict, offline: bool, cache_file: Path,
                  use_obs: bool = True) -> tuple[dict, dict | None, dict | None, dict]:
    """返回 (forecast, air, aq_obs, meta)；forecast 失败抛 RuntimeError。

    air  = CAMS 模型（绝对量不可信，只取形状）
    aq_obs = aqicn 官方监测站实测（锚定绝对量），拿不到就是 None
    """
    cache = load_cache(cache_file)
    now = int(time.time())
    cache_ok = _cache_match(cache, loc)
    cached_obs = cache.get("aq_obs") if use_obs else None

    if offline:
        if not cache_ok:
            raise RuntimeError(
                f"--offline 指定但 {cache_file} 没有该位置的缓存（先联网跑一次）")
        age = now - int(cache.get("fetched_at", 0))
        return cache["forecast"], cache.get("air"), cached_obs, {
            "fetched_at": cache.get("fetched_at"), "from_cache": True,
            "stale": age > CACHE_TTL_SECONDS, "error": None,
        }

    if cache_ok and now - int(cache.get("fetched_at", 0)) <= CACHE_TTL_SECONDS:
        return cache["forecast"], cache.get("air"), cached_obs, {
            "fetched_at": cache.get("fetched_at"), "from_cache": True,
            "stale": False, "error": None,
        }

    error = None
    forecast = air = aq_obs = None
    try:
        forecast = _http_json(_forecast_query(loc))
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
    try:
        air = _http_json(_air_query(loc))
    except Exception:  # noqa: BLE001
        air = None  # 空气质量是加分项，失败不致命
    if use_obs:
        url = _aq_obs_url(loc)
        if url:
            try:
                aq_obs = _http_json(url, retries=1)
            except Exception:  # noqa: BLE001
                aq_obs = None  # 实测拿不到就退回纯模型（会自动降级判级）

    if forecast is None:
        if cache_ok:
            age = now - int(cache.get("fetched_at", 0))
            if age <= STALE_MAX_SECONDS:
                return cache["forecast"], cache.get("air"), cached_obs, {
                    "fetched_at": cache.get("fetched_at"), "from_cache": True,
                    "stale": True, "error": error,
                }
        raise RuntimeError(error or "预报请求失败且没有可用缓存")

    if not use_obs:
        aq_obs = None       # 本次不用实测，但不破坏缓存里已有的实测
    save_cache(cache_file, loc, forecast, air,
               aq_obs if aq_obs is not None else cache.get("aq_obs"))
    return forecast, air, aq_obs, {
        "fetched_at": now, "from_cache": False, "stale": False, "error": None,
    }


# ---------------------------------------------------------------------------
# 阈值规则（确定性）
# ---------------------------------------------------------------------------

def us_aqi_to_pm25(aqi: float | None) -> float | None:
    """aqicn 给的是 US EPA AQI，反算成 PM2.5 浓度（µg/m³）。"""
    if aqi is None:
        return None
    try:
        a = float(aqi)
    except (TypeError, ValueError):
        return None
    for a_lo, a_hi, c_lo, c_hi in US_AQI_PM25_BP:
        if a_lo <= a <= a_hi:
            return round(c_lo + (a - a_lo) * (c_hi - c_lo) / (a_hi - a_lo), 1)
    if a > 500:
        return round(500.4 + (a - 500) * 4.0, 1)
    return None


def pm25_to_cn_iaqi(pm25: float | None) -> int | None:
    """中国 HJ 633-2012：PM2.5 浓度 → IAQI（线性内插，进位取整）。"""
    if pm25 is None:
        return None
    try:
        c = max(0.0, float(pm25))
    except (TypeError, ValueError):
        return None
    if c > 500:
        return 500
    for c_lo, c_hi, i_lo, i_hi in CN_IAQI_PM25_BP:
        if c_lo <= c <= c_hi:
            return int(round(i_lo + (c - c_lo) * (i_hi - i_lo) / (c_hi - c_lo)))
    return 500


def cn_aqi_label(iaqi: float | None) -> str:
    """中国 AQI 六级分档（HJ 633-2012）。"""
    if iaqi is None:
        return "无数据"
    if iaqi <= 50:
        return "优"
    if iaqi <= 100:
        return "良"
    if iaqi <= 150:
        return "轻度污染"
    if iaqi <= 200:
        return "中度污染"
    if iaqi <= 300:
        return "重度污染"
    return "严重污染"


def pm25_label(pm25: float | None) -> str:
    """兼容旧口径：PM2.5 浓度 → 中国 AQI 等级（等价于 pm25_to_cn_iaqi + cn_aqi_label）。"""
    return cn_aqi_label(pm25_to_cn_iaqi(pm25))


_WIND_SCALE = [(1, "0级"), (6, "1级"), (12, "2级"), (20, "3级"), (29, "4级"),
               (39, "5级"), (50, "6级"), (62, "7级"), (75, "8级"), (89, "9级"),
               (103, "10级"), (118, "11级")]


def wind_scale(speed_kmh: float | None) -> str:
    """蒲福风级（按 10m 平均风速，km/h）。"""
    if speed_kmh is None:
        return "0级"
    for limit, label in _WIND_SCALE:
        if speed_kmh < limit:
            return label
    return "12级"


def wind_scale_text(speed_kmh: float | None) -> str:
    if speed_kmh is None:
        return "风无数据"
    return wind_scale(speed_kmh)


def heat_tier(app_max: float | None) -> str:
    if app_max is None:
        return "none"
    if app_max >= 35:
        return "extreme"
    if app_max >= 30:
        return "hot"
    if app_max >= 26:
        return "warm"
    if app_max >= 20:
        return "mild"
    return "cool"


def cold_tier(app_min: float | None) -> str:
    if app_min is None:
        return "none"
    if app_min <= -15:
        return "extreme"
    if app_min <= -8:
        return "severe"
    if app_min <= -3:
        return "cold"
    if app_min <= 5:
        return "chilly"
    return "none"


def pace_adjust(day: dict) -> dict:
    """返回 {low, high, note}：目标配速建议「慢多少秒/公里」+ 说明。"""
    low, high, notes = 0, 0, []
    heat = day["heat_tier"]
    if heat == "warm":
        low, high = 10, 20
        notes.append("体感≥26℃：质量课配速 +10~20s/km，改按心率/体感跑")
    elif heat == "hot":
        low, high = 20, 35
        notes.append("体感≥30℃：配速 +20~35s/km，缩短质量课、补水优先")
    elif heat == "extreme":
        notes.append("体感≥35℃：取消户外强度课，只保留室内或清晨低强度")

    cold = day["cold_tier"]
    if cold == "cold":
        low = max(low, 5)
        notes.append("体感≤-3℃：热身加倍，质量课配速别硬顶（+5~10s/km 或按心率）")
    elif cold == "severe":
        low = max(low, 10)
        notes.append("体感≤-8℃：质量课转室内，室外只做有氧")
    elif cold == "extreme":
        notes.append("体感≤-15℃：停止户外训练")

    gust = day.get("gust_max")
    if gust is not None and gust >= 62:
        low = max(low, 10)
        notes.append("阵风≥62km/h（8级）：户外跑步减量或改室内，迎风段放松")
    elif gust is not None and gust >= 39:
        low = max(low, 5)
        notes.append("阵风≥39km/h（6级）：注意迎风段，间歇改避风路线；骑行改室内")

    if (day.get("precip_mm") or 0) >= 0.5:
        low = max(low, 5)
        notes.append("地面湿滑：缩短步幅、配速保守")

    if not notes:
        notes.append("无（温度/风/降水均在常规范围）")
    return {"low": int(low), "high": int(high), "note": "；".join(notes)}


def classify_day(day: dict) -> dict:
    """定级：适合户外 / 注意 / 不宜户外 / 危险·禁止户外。"""
    flags: list[str] = []
    severe: list[str] = []
    no_outdoor: list[str] = []
    caution: list[str] = []

    code = day.get("code")
    precip = day.get("precip_mm") or 0.0
    prob = day.get("precip_prob") or 0
    tmin = day.get("tmin")
    app_max = day.get("app_max")
    app_min = day.get("app_min")
    gust = day.get("gust_max") or 0.0
    aqi = day.get("aqi_eff")
    aq_hard = bool(day.get("aq_hard"))
    aq_label = day.get("aqi_label") or cn_aqi_label(aqi)
    if day.get("aq_source") == "model":
        aq_note = "（模型估算）"
    elif not aq_hard:
        aq_note = "（远期预报）"
    else:
        aq_note = ""
    uv = day.get("uv_max") or 0.0

    # --- 危险（禁止户外）---
    if code in THUNDER_CODES:
        severe.append("雷暴")
        flags.append("雷暴")
    if precip >= 25:
        severe.append(f"降水{num(precip)}mm")
        flags.append("暴雨")
    elif code in SNOW_CODES and precip >= 20:
        severe.append(f"大暴雪{num(precip)}mm")
        flags.append("暴雪")
    elif code in SNOW_CODES and gust >= 62:
        severe.append(f"风雪（阵风{num(gust, '.0f')}km/h）")
        flags.append("风雪")
    if app_max is not None and app_max >= 35:
        severe.append(f"体感{num(app_max)}℃")
        flags.append("高温")
    if app_min is not None and app_min <= -15:
        severe.append(f"体感{num(app_min)}℃")
        flags.append("严寒")
    if aqi is not None and aqi > 300 and aq_hard:
        severe.append(f"AQI {num(aqi, '.0f')}（{aq_label}）")
        flags.append("严重污染")

    # --- 不宜户外 ---
    if not severe:
        if code in SNOW_CODES:
            no_outdoor.append(WMO_TEXT.get(code, "降雪"))
            flags.append("雪")
        elif precip >= 5 or (prob >= 80 and precip >= 1):
            no_outdoor.append(f"降水{num(precip)}mm/{num(prob, '.0f')}%")
            flags.append("雨雪")
        if tmin is not None and tmin <= 0 and precip >= 0.5:
            no_outdoor.append("路面可能结冰")
            flags.append("结冰")
        if aqi is not None and aqi > 200 and aq_hard:
            no_outdoor.append(f"空气重度污染（AQI {num(aqi, '.0f')}）")
            flags.append("污染")
        if gust >= 75:
            no_outdoor.append(f"阵风{num(gust, '.0f')}km/h")
            flags.append("大风")

    # --- 注意 ---
    if not severe and not no_outdoor:
        if precip >= 0.5 or prob >= 50:
            caution.append("有降水可能")
            flags.append("轻降水")
        if app_max is not None and app_max >= 26:
            caution.append(f"体感{num(app_max)}℃偏热")
            flags.append("偏热")
        if app_min is not None and app_min <= -3:
            caution.append(f"体感{num(app_min)}℃低温")
            flags.append("低温")
        if aqi is not None and aqi > 150:
            caution.append(f"空气{aq_label}（AQI {num(aqi, '.0f')}）{aq_note}"
                           "：质量课改室内，户外只做短有氧")
            flags.append("空气差")
        elif aqi is not None and aqi > 100:
            caution.append(f"空气{aq_label}（AQI {num(aqi, '.0f')}）{aq_note}"
                           "：只做有氧，避开早晚高峰")
            flags.append("空气一般")
        if day.get("aq_divergent"):
            caution.append(f"空气数据分歧大（模型 {num(day.get('pm25_model_max'))} µg/m³"
                           f" vs 实测锚定 AQI {num(aqi, '.0f')}），出门前用手机 AQI 复核")
            flags.append("空气待复核")
        if 39 <= gust < 75:
            caution.append(f"阵风{num(gust, '.0f')}km/h")
            flags.append("大风")
        if uv >= 7:
            caution.append("紫外线强")
            flags.append("强紫外线")

    if severe:
        verdict = "危险·禁止户外"
        summary = "禁止户外：" + "、".join(severe)
        advice = "取消户外课：改室内（跑步机/骑行台）或改期；比赛日启用备用方案"
    elif no_outdoor:
        verdict = "不宜户外"
        summary = "不宜户外：" + "、".join(no_outdoor)
        advice = "户外课改跑步机/骑行台，或顺延到天气转好的日子"
    elif caution:
        verdict = "注意"
        summary = "可户外，注意：" + "、".join(caution)
        advice = "可户外：热身加长、装备按天气调整、按修正配速"
    else:
        verdict = "适合户外"
        summary = "适合户外"
        advice = "按计划户外执行"
    return {"verdict": verdict, "flags": flags, "summary": summary, "advice": advice}


def confidence_for(offset_days: int) -> str:
    if offset_days <= 2:
        return "高"
    if offset_days <= 5:
        return "中"
    if offset_days <= 10:
        return "低"
    return "很低"


# ---------------------------------------------------------------------------
# 组装每日数据
# ---------------------------------------------------------------------------

def _hourly_slice(forecast: dict, date_str: str) -> dict:
    hourly = forecast.get("hourly") or {}
    times = hourly.get("time") or []
    idx = [i for i, t in enumerate(times) if t.startswith(date_str)]
    out: dict = {}
    for key in ("temperature_2m", "apparent_temperature", "relative_humidity_2m",
                "precipitation", "precipitation_probability",
                "wind_speed_10m", "wind_gusts_10m"):
        values = hourly.get(key) or []
        out[key] = [values[i] if i < len(values) else None for i in idx]
    out["hour"] = [int(times[i][11:13]) for i in idx]
    return out


def _local_tz(name: str | None):
    """优先用 zoneinfo；Windows 没装 tzdata 时退回东八区。"""
    if name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001
            pass
    return timezone(timedelta(hours=8))


def _model_pm25_series(air: dict | None) -> dict:
    """CAMS 模型 PM2.5 → {ISO 小时: µg/m³}。"""
    if not air:
        return {}
    hourly = air.get("hourly") or {}
    times = hourly.get("time") or []
    values = hourly.get("pm2_5") or []
    return {t: v for t, v in zip(times, values) if v is not None}


def _observed_pm25_series(aq_obs: dict | None, loc: dict) -> dict:
    """aqicn 官方监测站实测（US AQI 反算浓度）→ {ISO 小时: µg/m³}。"""
    if not aq_obs:
        return {}
    hist = (aq_obs.get("historic") or {}).get("PM2.5") or {}
    try:
        base = int(aq_obs.get("time"))
    except (TypeError, ValueError):
        return {}
    tz = _local_tz(loc.get("timezone"))
    out = {}
    for key, value in hist.items():
        try:
            hours_ago = int(key)
        except (TypeError, ValueError):
            continue
        pm25 = us_aqi_to_pm25(value)
        if pm25 is None:
            continue
        stamp = datetime.fromtimestamp(base - hours_ago * 3600, tz)
        out[stamp.strftime("%Y-%m-%dT%H:00")] = pm25
    return out


def calibration(air: dict | None, obs: dict, now_iso: str) -> dict:
    """用最近 48h 的「实测/模型」配对求稳健比例。

    为什么要这一步：CAMS 全球模式在中国北方平原系统性偏高（北京海淀实测
    2026-11-22~24 中位比 6.4×，p90 24.9×）。所以模型只贡献「形状」，量级由
    站点实测锚定。
    """
    model = _model_pm25_series(air)
    if not obs:
        return {"ratio": 1.0, "pairs": 0, "applied": False, "obs_hours": 0,
                "note": "无站点实测，按模型原值（CAMS 在中国常偏高数倍）"}
    if not model:
        return {"ratio": 1.0, "pairs": 0, "applied": False, "obs_hours": len(obs),
                "note": "无模型序列，直接用实测"}

    try:
        now_dt = datetime.fromisoformat(now_iso)
    except (TypeError, ValueError):
        now_dt = None

    ratios = []
    for stamp, model_value in model.items():
        if now_dt is not None:
            try:
                hour_dt = datetime.fromisoformat(stamp)
            except ValueError:
                continue
            if hour_dt > now_dt:
                continue
            if (now_dt - hour_dt).total_seconds() > CALIB_WINDOW_HOURS * 3600:
                continue
        observed = obs.get(stamp)
        if observed and observed > 0 and model_value is not None:
            ratios.append(model_value / observed)

    if len(ratios) < CALIB_MIN_PAIRS:
        return {"ratio": 1.0, "pairs": len(ratios), "applied": False,
                "obs_hours": len(obs),
                "note": f"配对样本仅 {len(ratios)} 个（<{CALIB_MIN_PAIRS}），不做校准"}

    ratio = max(CALIB_RATIO_MIN, min(CALIB_RATIO_MAX, statistics.median(ratios)))
    note = f"模型/实测中位比 {ratio:.1f}×（{len(ratios)} 个配对小时）"
    if ratio >= CALIB_BIAS_ALERT or ratio <= 1 / CALIB_BIAS_ALERT:
        note += "，模型偏差大，已按实测校准"
    return {"ratio": round(ratio, 3), "pairs": len(ratios), "applied": True,
            "obs_hours": len(obs), "note": note}


def _pm25_hourly(air: dict | None, obs: dict, calib: dict) -> dict:
    """校准后的逐小时 PM2.5：有实测用实测，其余 = 模型 ÷ ratio（模型偏高就往下压）。"""
    out = {}
    ratio = calib.get("ratio") or 1.0
    for stamp, value in _model_pm25_series(air).items():
        out[stamp] = round(value / ratio, 1) if calib.get("applied") else value
    out.update(obs)      # 实测覆盖模型
    return out


def _aq_slice(pm25_hourly: dict, obs: dict, date_str: str) -> dict:
    hourly = {int(k[11:13]): v for k, v in pm25_hourly.items()
              if k.startswith(date_str) and v is not None}
    if not hourly:
        return {"pm25_mean": None, "pm25_max": None, "aqi_max": None,
                "aqi_label": "无数据", "pm25_hourly": {}, "aqi_hourly": {},
                "observed_hours": 0, "hours": 0}
    iaqi_hourly = {h: pm25_to_cn_iaqi(v) for h, v in hourly.items()}
    iaqis = [v for v in iaqi_hourly.values() if v is not None]
    observed = sum(1 for h in hourly if f"{date_str}T{h:02d}:00" in obs)
    aqi_max = max(iaqis) if iaqis else None
    return {
        "pm25_mean": round(sum(hourly.values()) / len(hourly), 1),
        "pm25_max": round(max(hourly.values()), 1),
        "aqi_max": aqi_max,
        "aqi_label": cn_aqi_label(aqi_max),
        "pm25_hourly": hourly,
        "aqi_hourly": iaqi_hourly,
        "observed_hours": observed,
        "hours": len(hourly),
    }


def _best_window(slice_: dict, day: dict, aqi_by_hour: dict | None = None) -> dict | None:
    """在日照时段内选 2 小时「天气最优」窗口（温度和空气都算进去）。"""
    hours = slice_.get("hour") or []
    if not hours:
        return None
    sunrise = day.get("sunrise") or ""
    sunset = day.get("sunset") or ""
    try:
        start_h = int(sunrise[11:13]) + 1
        end_h = int(sunset[11:13])
    except (ValueError, IndexError):
        start_h, end_h = 7, 17
    start_h = min(max(start_h, 5), 21)
    end_h = min(max(end_h, start_h + 2), 22)

    def score(i: int) -> float:
        app = slice_["apparent_temperature"][i]
        if app is None:
            return 99.0
        comfort = abs(app - 10) * (0.55 if app <= 10 else 0.9)
        rain = (slice_["precipitation_probability"][i] or 0) / 10.0
        wet = (slice_["precipitation"][i] or 0) * 2.0
        wind = slice_["wind_speed_10m"][i] or 0
        gust = slice_["wind_gusts_10m"][i] or 0
        wind_pen = 0.4 * max(0, wind - 15) + 0.02 * max(0, gust - 25)
        air_pen = 0.0
        iaqi = (aqi_by_hour or {}).get(hours[i])
        if iaqi is not None:
            # AQI 50 以内不罚；100→2.5；150→5；200→7.5
            air_pen = max(0.0, min(10.0, (iaqi - 50) * 0.05))
        return comfort + rain + wet + wind_pen + air_pen

    best: tuple[float, int] | None = None
    for i, hour in enumerate(hours):
        if hour < start_h or hour > end_h - 2 or i + 1 >= len(hours):
            continue
        s = score(i) + score(i + 1)
        if best is None or s < best[0]:
            best = (s, i)
    if best is None:
        return None
    i = best[1]
    # 窗口按「最差的那一小时」报 AQI：在那 2 小时里跑步，谁高按谁算
    win_aqis = [aq for aq in ((aqi_by_hour or {}).get(hours[i]),
                              (aqi_by_hour or {}).get(hours[i + 1])) if aq is not None]
    return {
        "start": f"{hours[i]:02d}:00",
        "end": f"{hours[i] + 2:02d}:00",
        "apparent": round1(slice_["apparent_temperature"][i]),
        "rain_prob": slice_["precipitation_probability"][i],
        "wind_kmh": round1(slice_["wind_speed_10m"][i]),
        "aqi": max(win_aqis) if win_aqis else None,
        "score": round(best[0], 1),
    }


def build_days(forecast: dict, air: dict | None, aq_obs: dict | None,
               loc: dict, limit: int) -> tuple[list[dict], dict]:
    daily = forecast.get("daily") or {}
    dates = (daily.get("time") or [])
    current = forecast.get("current") or {}
    try:
        today = datetime.fromisoformat(current["time"]).date()
    except Exception:  # noqa: BLE001
        today = datetime.now().date()

    now_iso = current.get("time") or ""
    now_hour_key = now_iso[:13] + ":00" if len(now_iso) >= 13 else ""
    obs = _observed_pm25_series(aq_obs, loc)
    obs_stale = False
    if obs and now_iso:
        try:
            lag = (datetime.fromisoformat(now_iso)
                   - datetime.fromisoformat(max(obs))).total_seconds()
            if lag > OBS_MAX_LAG_HOURS * 3600:
                obs_stale, obs = True, {}      # 实测太久没更新，不能用来锚定量级
        except ValueError:
            pass
    calib = calibration(air, obs, now_iso)
    pm25_hourly = _pm25_hourly(air, obs, calib)
    model_pm25 = _model_pm25_series(air)

    out = []
    for offset, date_str in enumerate(dates):
        if offset >= limit:
            break
        date = datetime.fromisoformat(date_str).date()

        def pick(name):
            values = daily.get(name) or []
            return values[offset] if offset < len(values) else None

        code = pick("weather_code")
        day = {
            "date": date_str,
            "weekday": WEEKDAY_CN[date.weekday()],
            "offset": (date - today).days,
            "code": code,
            "text": WMO_TEXT.get(code, f"未知({code})"),
            "tmin": round1(pick("temperature_2m_min")),
            "tmax": round1(pick("temperature_2m_max")),
            "app_min": round1(pick("apparent_temperature_min")),
            "app_max": round1(pick("apparent_temperature_max")),
            "precip_mm": round1(pick("precipitation_sum")),
            "precip_prob": pick("precipitation_probability_max"),
            "wind_max": round1(pick("wind_speed_10m_max")),
            "gust_max": round1(pick("wind_gusts_10m_max")),
            "uv_max": round1(pick("uv_index_max")),
            "sunrise": pick("sunrise"),
            "sunset": pick("sunset"),
            "confidence": confidence_for(max((date - today).days, 0)),
        }
        day.update(_aq_slice(pm25_hourly, obs, date_str))
        day["heat_tier"] = heat_tier(day["app_max"])
        day["cold_tier"] = cold_tier(day["app_min"])
        day["window"] = _best_window(_hourly_slice(forecast, date_str), day,
                                     day["aqi_hourly"])

        # 当日「此刻」的 AQI：优先当前小时，没有就用最近一个已有数据的小时
        # （aqicn 的城市值滞后约 1 小时，且它的 utime 标签是 JST(+09:00)，别信标签）
        aqi_now = None
        if offset == 0 and now_hour_key:
            hh = int(now_hour_key[11:13])
            got = [h for h in day["aqi_hourly"] if h <= hh]
            if got:
                aqi_now = day["aqi_hourly"][max(got)]

        # 判级用「训练窗口 / 此刻」的 AQI，而不是全天均值：
        # 全天均值会把凌晨的模型尖峰算进来，从而误判白天完全干净的时段。
        cand = [v for v in (aqi_now, (day.get("window") or {}).get("aqi"))
                if v is not None]
        day["aqi_now"] = aqi_now
        day["aqi_eff"] = max(cand) if cand else day["aqi_max"]

        if day["hours"] == 0:
            day["aq_source"] = "none"
        elif day["observed_hours"] >= day["hours"]:
            day["aq_source"] = "obs"
        elif day["observed_hours"] > 0:
            day["aq_source"] = "obs_partial"
        elif calib.get("applied"):
            day["aq_source"] = "calibrated"
        else:
            day["aq_source"] = "model"
        # 只有「有实测锚定 / 已校准」且 2 天内，才允许 AQ 单独取消户外课
        day["aq_hard"] = (day["aq_source"] in ("obs", "obs_partial", "calibrated")
                          and day["offset"] <= 2)
        # 校准是乘性修正，遇到「模型尖叫污染、实测锚定却很干净」要留一条复核提示，
        # 避免把真实的污染过程一起压平。只看**没有实测**的小时：
        # 已经有实测的小时，模型说多少都不算数。
        raw_vals = [v for k, v in model_pm25.items()
                    if k.startswith(date_str) and v is not None and k not in obs]
        day["pm25_model_max"] = round(max(raw_vals), 1) if raw_vals else None
        day["aq_divergent"] = bool(
            calib.get("applied") and raw_vals and max(raw_vals) >= 200
            and (day["aqi_eff"] or 0) <= 100)
        day["aqi_label"] = cn_aqi_label(day["aqi_eff"])
        day.update(classify_day(day))
        day["pace_adjust"] = pace_adjust(day)
        out.append(day)

    recent = [k for k in obs if k <= now_hour_key] if now_hour_key else []
    latest_obs = max(recent) if recent else None
    aq_meta = {
        "source": "aqicn-gov-station" if obs else ("cams-calibrated" if calib.get("applied") else "cams-model"),
        "aq_city": loc.get("aq_city"),
        "observed_hours": len(obs),
        "stale_obs": obs_stale,
        "latest_obs_hour": latest_obs,
        "now_pm25": obs.get(latest_obs) if latest_obs else None,
        "now_aqi": pm25_to_cn_iaqi(obs.get(latest_obs)) if latest_obs else None,
        "calibration": calib,
    }
    return out, aq_meta


def current_now(forecast: dict) -> dict:
    cur = forecast.get("current") or {}
    return {
        "time": cur.get("time"),
        "temp": round1(cur.get("temperature_2m")),
        "apparent": round1(cur.get("apparent_temperature")),
        "humidity": cur.get("relative_humidity_2m"),
        "wind": round1(cur.get("wind_speed_10m")),
        "gust": round1(cur.get("wind_gusts_10m")),
        "precip": round1(cur.get("precipitation")),
        "code": cur.get("weather_code"),
        "text": WMO_TEXT.get(cur.get("weather_code"), "未知"),
    }


# ---------------------------------------------------------------------------
# 文本输出
# ---------------------------------------------------------------------------

def _aq_display(day: dict) -> str:
    aqi = day.get("aqi_eff")
    if aqi is None:
        return "空气无数据"
    src = day.get("aq_source")
    tag = {"obs": "", "obs_partial": "", "calibrated": "·校准",
           "model": "·模型估算"}.get(src, "·模型估算")
    text = f"空气{day.get('aqi_label')}（AQI {num(aqi, '.0f')}{tag}）"
    aqi_max = day.get("aqi_max")
    if aqi_max is not None and aqi is not None and aqi_max - aqi >= 30:
        text += f"，全天最高 AQI {num(aqi_max, '.0f')}"
    return text


def _day_core(day: dict) -> str:
    return (f"{day['text']} {fmt_range(day['tmin'], day['tmax'])}，"
            f"体感 {fmt_range(day['app_min'], day['app_max'])}，"
            f"风{wind_scale_text(day['wind_max'])}阵风{wind_scale(day['gust_max'])}"
            f"（{num(day['gust_max'])}km/h），"
            f"降水 {num(day['precip_mm'])}mm/{num(day['precip_prob'], '.0f')}%，"
            f"{_aq_display(day)}")


def _win_air(win: dict | None) -> str:
    if not win:
        return ""
    aqi = win.get("aqi")
    return f"，空气 AQI {num(aqi, '.0f')}" if aqi is not None else ""


def render_today(day: dict, cur: dict, meta: dict) -> list[str]:
    lines = [f"今日 {day['date']} {day['weekday']}：{_day_core(day)}"]
    if cur.get("time"):
        fresh = "缓存" if meta.get("from_cache") else "实况"
        lines.append(f"  当前（{fresh} {cur['time'].replace('T', ' ')[5:]}）："
                     f"{num(cur['temp'])}℃ 体感 {num(cur['apparent'])}℃ "
                     f"湿度 {num(cur['humidity'], '.0f')}% 风 {num(cur['wind'])}km/h")
    win = day.get("window")
    if win:
        note = ""
        try:
            now_hour = int((cur.get("time") or "").split("T")[1][:2])
            if now_hour > int(win["end"][:2]):
                note = f"（现在 {now_hour:02d}:00，今天已过；明天再看）"
        except (ValueError, IndexError):
            pass
        lines.append(f"  天气最优时段：{win['start']}–{win['end']}（体感 {num(win['apparent'])}℃，"
                     f"降水概率 {num(win['rain_prob'], '.0f')}%，风 {num(win['wind_kmh'])}km/h"
                     f"{_win_air(win)}）{note}")
    lines.append(f"  结论：{day['verdict']}｜{day['summary']}")
    lines.append(f"  修正：{day['pace_adjust']['note']}")
    return lines


def render_day_line(day: dict) -> str:
    win = day.get("window")
    win_text = f"｜最优 {win['start']}–{win['end']}" if win and day["verdict"] == "适合户外" else ""
    return (f"{day['date'][5:]} {day['weekday']} {day['text']} "
            f"{fmt_range(day['tmin'], day['tmax'])} 体感{fmt_range(day['app_min'], day['app_max'])} "
            f"风{wind_scale_text(day['wind_max'])}阵风{wind_scale(day['gust_max'])} "
            f"降水{num(day['precip_mm'])}mm/{num(day['precip_prob'], '.0f')}% "
            f"{_aq_display(day)} → {day['verdict']}{win_text}")


def render_text(days: list[dict], cur: dict, meta: dict, loc: dict,
                mode_date: str | None, aq_meta: dict | None = None) -> str:
    stamp = datetime.fromtimestamp(meta.get("fetched_at") or time.time()).strftime("%m-%d %H:%M")
    src = "缓存" if meta.get("from_cache") else "Open-Meteo"
    stale = "（⚠️ 网络失败，缓存可能过期）" if meta.get("stale") else ""
    lines = [f"【天气 · {loc['name']}】{stamp} 更新 · 来源 {src}{stale}"]
    aq_line = _aq_source_line(aq_meta)
    if aq_line:
        lines.append("  " + aq_line)

    if mode_date:
        target = next((d for d in days if d["date"] == mode_date), None)
        if target:
            lines.append(f"{target['date']} {target['weekday']}（{target['confidence']}可信度）：{_day_core(target)}")
            win = target.get("window")
            if win:
                lines.append(f"  天气最优时段：{win['start']}–{win['end']}（体感 {num(win['apparent'])}℃，"
                             f"降水概率 {num(win['rain_prob'], '.0f')}%{_win_air(win)}）")
            lines.append(f"  结论：{target['verdict']}｜{target['summary']}")
            lines.append(f"  修正：{target['pace_adjust']['note']}")
            lines.append(f"  室内建议：{target['advice']}")
        return "\n".join(lines)

    lines.extend(render_today(days[0], cur, meta))
    lines.append("未来几天：")
    for day in days[1:]:
        lines.append("  " + render_day_line(day))
    lines.append("提示：≥26℃ 配速 +10~20s/km；≥30℃ 再降；<0℃ 热身加倍；"
                 "雪/结冰/雷暴/AQI>200 禁止户外强度；第 6 天以后预报可信度下降。")
    return "\n".join(lines)


def _aq_source_line(aq_meta: dict | None) -> str:
    """说明空气数据的口径，避免再出现「模型说脏、实际很干净」。"""
    if not aq_meta:
        return ""
    calib = aq_meta.get("calibration") or {}
    hours = aq_meta.get("observed_hours") or 0
    if hours <= 0:
        return "空气：无站点实测，以下为 CAMS 模型估算（中国常偏高数倍，仅供参考）"
    if calib.get("applied"):
        return (f"空气：站点实测锚定（{hours} 小时）＋模型形状，"
                f"{calib.get('note', '')}")
    return f"空气：站点实测锚定（{hours} 小时）"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="耐力教练天气取数与训练修正（Open-Meteo，纯标准库）",
        epilog="示例: python weather.py --days 7 --out-md coach/weather-latest.md",
    )
    p.add_argument("--days", type=int, default=7, help=f"预报天数，1~{FORECAST_DAYS_FETCHED}（默认 7）")
    p.add_argument("--date", help="只看某一天，格式 YYYY-MM-DD（例如比赛日 2027-04-18）")
    p.add_argument("--json", action="store_true", help="输出 JSON（机器可读）")
    p.add_argument("--offline", action="store_true", help="只用本地缓存（断网/测试）")
    p.add_argument("--no-aq-obs", action="store_true",
                   help="不取 aqicn 站点实测，退回纯 CAMS 模型（调试/对比用）")
    p.add_argument("--lat", type=float, help="临时覆盖纬度")
    p.add_argument("--lon", type=float, help="临时覆盖经度")
    p.add_argument("--name", help="临时覆盖地点名（报告里显示）")
    p.add_argument("--athlete", help="档案路径（默认 coach/athlete.json，可用 ENDURANCE_COACH_DIR 覆盖目录）")
    p.add_argument("--cache", help="缓存文件路径（默认 <档案目录>/.cache/weather.json）")
    p.add_argument("--out-md", help="把文本简报另存为 UTF-8 文件（给教练直接 read）")
    p.add_argument("--out-json", help="把 JSON 另存为 UTF-8 文件")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    _utf8_stdout()
    args = parse_args(argv)

    if args.date:
        try:
            datetime.fromisoformat(args.date)
        except ValueError:
            print(f"❌ --date 格式必须是 YYYY-MM-DD：{args.date}", file=sys.stderr)
            return 3
        want_days = FORECAST_DAYS_FETCHED
    else:
        want_days = max(1, min(int(args.days), FORECAST_DAYS_FETCHED))

    athlete_path = resolve_athlete_path(args)
    athlete = load_athlete(athlete_path)
    if athlete is None and args.lat is None and args.lon is None:
        print(f"❌ 没有可用档案：{athlete_path}", file=sys.stderr)
        print("   请先运行 init_athlete.py 生成 coach/athlete.json 并填写 location，"
              "或用 --lat/--lon 指定坐标。", file=sys.stderr)
        return 3

    try:
        loc = load_location(args, athlete)
    except ConfigError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 3

    cache_file = resolve_cache_path(args, athlete_path)

    # 比赛日自动切到赛事地坐标（用户没有显式指定坐标时）
    venue = load_venue_for_date(athlete, args.date)
    if venue and args.lat is None and args.lon is None:
        loc["lat"] = float(venue["lat"])
        loc["lon"] = float(venue["lon"])
        loc["name"] = venue.get("name") or loc["name"]
        loc["venue"] = {"name": venue.get("name"), "approx": bool(venue.get("approx"))}
    guard_aq_city(loc, athlete)

    try:
        forecast, air, aq_obs, meta = fetch_weather(
            loc, args.offline, cache_file, use_obs=not args.no_aq_obs)
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ 天气数据未取到：{exc}", file=sys.stderr)
        print("按规则：不得臆造温度/湿度/风力；只能写「天气数据未取到」，"
              "并按无气象数据的原则性建议处理。", file=sys.stderr)
        return 2

    days, aq_meta = build_days(forecast, air, aq_obs, loc, want_days)
    if not days:
        print("❌ 天气数据为空（daily 无记录）", file=sys.stderr)
        return 2

    cur = current_now(forecast)
    meta_payload = {
        "fetched_at": meta.get("fetched_at"),
        "from_cache": meta.get("from_cache"),
        "stale": meta.get("stale"),
        "provider": "open-meteo",
        "air_provider": aq_meta.get("source"),
        "rules_version": "1.1.0",
    }

    if args.date:
        target = next((d for d in days if d["date"] == args.date), None)
        if target is None:
            print(f"❌ {args.date} 超出预报范围（可用 {days[0]['date']} ~ {days[-1]['date']}）",
                  file=sys.stderr)
            return 3
        days = [target]

    if args.json:
        payload = {
            "location": loc,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "meta": meta_payload,
            "air": aq_meta,
            "current": cur,
            "days": days,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=1)
        if args.out_json:
            _write_out(args.out_json, text)
        print(text)
        return 0

    text = render_text(days, cur, meta, loc, args.date, aq_meta)
    if args.out_md:
        _write_out(args.out_md, text)
    if args.out_json:
        payload = {
            "location": loc,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "meta": meta_payload,
            "air": aq_meta,
            "current": cur,
            "days": days,
        }
        _write_out(args.out_json, json.dumps(payload, ensure_ascii=False, indent=1))
    print(text)
    return 0


def _write_out(path_str: str, text: str) -> None:
    """写 UTF-8 输出文件（自动建目录），失败只警告不改变退出码。"""
    try:
        path = Path(path_str).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + ("" if text.endswith("\n") else "\n"), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ 写输出文件失败（{path_str}）：{exc}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
