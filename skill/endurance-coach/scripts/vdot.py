#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VDOT 与五区配速计算器（Daniels & Gilbert 公式，纯标准库）。

用法:
  python vdot.py --distance 5k --time 22:00
  python vdot.py --distance 42195 --time 3:45:00 --json
  python vdot.py --vdot 41

说明:
  - 距离可用别名 5k / 10k / hm / half / m / marathon / full，也可直接写米数。
  - 时间支持 mm:ss 或 h:mm:ss；只给一个数字时按分钟解释。
  - 输出 E/M/T/I/R 五区的典型配速与区间，供课表引用；设备阈值配速与之
    相差 >5s/km 时，以心率区间校准，不要把两套数字混写进同一份课表。
"""
import argparse
import json
import math
import sys

DISTANCES = {
    "5k": 5000, "10k": 10000, "hm": 21097.5, "half": 21097.5,
    "m": 42195, "marathon": 42195, "full": 42195,
}

# Daniels %VDOT 区间 (low, high, typical)
ZONES = {
    "E": (0.59, 0.74, 0.65),
    "M": (0.75, 0.84, 0.80),
    "T": (0.83, 0.88, 0.86),
    "I": (0.95, 1.00, 0.98),
    "R": (1.05, 1.10, 1.07),
}


def parse_time(text):
    parts = str(text).strip().split(":")
    if len(parts) == 1:
        return float(parts[0]) * 60.0  # seconds -> minutes
    if len(parts) == 2:
        return float(parts[0]) + float(parts[1]) / 60.0
    h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
    return h * 60 + m + s / 60.0


def parse_distance(text):
    key = str(text).strip().lower()
    if key in DISTANCES:
        return DISTANCES[key]
    return float(text)


def vo2_from_velocity(v):
    return -4.60 + 0.182258 * v + 0.000104 * v * v


def velocity_from_vo2(vo2):
    a, b, c = 0.000104, 0.182258, -(vo2 + 4.60)
    return (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a)


def vdot_from_race(distance_m, time_min):
    v = distance_m / time_min
    vo2 = vo2_from_velocity(v)
    pct = (0.8
           + 0.1894393 * math.exp(-0.012778 * time_min)
           + 0.2989558 * math.exp(-0.1932605 * time_min))
    return vo2 / pct


def pace_for_pct(vdot, pct):
    vo2 = pct * vdot
    v = velocity_from_vo2(vo2)            # m/min
    sec_per_km = 1000.0 / v * 60.0
    return sec_per_km


def fmt_pace(sec_per_km):
    sec = int(round(sec_per_km))
    return "%d:%02d/km" % (sec // 60, sec % 60)


def main():
    ap = argparse.ArgumentParser(
        description="VDOT 与五区配速计算器（Daniels & Gilbert 公式，纯标准库）",
        epilog="示例: python vdot.py --distance 5k --time 22:00",
    )
    ap.add_argument("--distance", default=None, help="5k/10k/hm/m/42195 或米数")
    ap.add_argument("--time", default=None, help="完赛时间，如 22:00 或 3:45:00")
    ap.add_argument("--vdot", type=float, default=None, help="直接指定 VDOT")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    if args.vdot is not None:
        vdot = args.vdot
        src = "manual"
        race = None
    elif args.distance and args.time:
        dist_m = parse_distance(args.distance)
        t_min = parse_time(args.time)
        if dist_m <= 0 or t_min <= 0:
            ap.error("距离与时间必须为正数")
        vdot = vdot_from_race(dist_m, t_min)
        src = "race"
        race = {"distance_m": dist_m, "time_min": round(t_min, 3)}
    else:
        ap.error("需要 --distance+--time，或 --vdot")

    zones = {}
    for name, (lo, hi, typ) in ZONES.items():
        zones[name] = {
            "pct_range": [lo, hi],
            "pace_typical": fmt_pace(pace_for_pct(vdot, typ)),
            "pace_range": [fmt_pace(pace_for_pct(vdot, hi)),
                           fmt_pace(pace_for_pct(vdot, lo))],
        }

    out = {"vdot": round(vdot, 2), "source": src, "race": race, "zones": zones}
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    print("VDOT  = %.2f  (来源: %s)" % (vdot, src))
    if race:
        print("依据  = %.0fm / %.2f min" % (race["distance_m"], race["time_min"]))
    print("-" * 46)
    print("%-3s %-12s %-16s %s" % ("区", "%VDOT", "典型配速", "区间"))
    for name in ("E", "M", "T", "I", "R"):
        z = zones[name]
        print("%-3s %-12s %-16s %s ~ %s" % (
            name,
            "%.0f-%.0f%%" % (z["pct_range"][0] * 100, z["pct_range"][1] * 100),
            z["pace_typical"],
            z["pace_range"][0], z["pace_range"][1],
        ))
    print("-" * 46)
    print("提示: 与设备阈值配速差 >5s/km 时，以心率区间校准，勿混写两套数字。")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
