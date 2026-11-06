#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""比赛/长距离补给计算器（纯标准库）。

用法:
  python nutrition.py --duration-min 210 --intensity race
  python nutrition.py --duration-min 90 --intensity moderate --temp-c 28
  python nutrition.py --sweat --weight-before 70.5 --weight-after 69.6 --fluid-ml 800 --duration-min 120

说明:
  - 碳水、水、钠按运动时长与强度给区间；高温（>=26℃）自动取上限档。
  - 能量胶数量按补给时间点算（每 35min 一点 + 赛前 15min），不按碳水总量硬除。
  - --sweat 模式下用前后体重差与补水量估算出汗率（1kg≈1L）。
  - 所有补给方案都应先在训练中试过一次，比赛日不尝新。
"""
import argparse
import json
import sys


def main():
    ap = argparse.ArgumentParser(
        description="比赛/长距离补给计算器（纯标准库）",
        epilog="示例: python nutrition.py --duration-min 210 --intensity race",
    )
    ap.add_argument("--duration-min", type=float, default=90, help="运动时长（分钟，默认 90）")
    ap.add_argument("--intensity", default="moderate",
                    choices=["easy", "moderate", "race"], help="强度档位")
    ap.add_argument("--weight-kg", type=float, default=None,
                    help="体重（kg，可选，仅作记录/换算参考，不参与核心计算）")
    ap.add_argument("--temp-c", type=float, default=None, help="环境温度（℃），>=26 按高温取上限")
    ap.add_argument("--sweat", action="store_true", help="改为计算出汗率")
    ap.add_argument("--weight-before", type=float, help="运动前体重（kg，--sweat 用）")
    ap.add_argument("--weight-after", type=float, help="运动后体重（kg，--sweat 用）")
    ap.add_argument("--fluid-ml", type=float, default=0, help="运动中补水量（ml，--sweat 用）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    if args.sweat:
        if args.weight_before is None or args.weight_after is None:
            ap.error("--sweat 需要 --weight-before 与 --weight-after")
        if args.duration_min <= 0:
            ap.error("--duration-min 必须为正数")
        loss_l = args.weight_before - args.weight_after + args.fluid_ml / 1000.0
        rate = loss_l / (args.duration_min / 60.0)
        out = {"sweat_rate_l_per_h": round(rate, 2),
               "loss_l": round(loss_l, 2),
               "note": "按 1kg≈1L 估算；湿热/大汗取上限"}
        if args.json:
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print("出汗率: %.2f L/h（本次流失 %.2f L）" % (rate, loss_l))
            print("建议: 补水 %.0f-%.0f ml/h" % (rate * 0.8 * 1000, rate * 1.0 * 1000))
        return

    if args.duration_min <= 0:
        ap.error("--duration-min 必须为正数")

    hours = args.duration_min / 60.0

    # 碳水 g/h
    if args.duration_min < 150:
        carb_lo, carb_hi = 30, 60
    else:
        carb_lo, carb_hi = 60, 90
    if args.intensity == "easy":
        carb_lo, carb_hi = min(carb_lo, 30), min(carb_hi, 60)
    if args.intensity == "race":
        carb_lo, carb_hi = max(carb_lo, 60), max(carb_hi, 90)

    # 水 ml/h
    fluid_lo, fluid_hi = 400, 800
    hot = args.temp_c is not None and args.temp_c >= 26
    if hot:
        fluid_lo, fluid_hi = 600, 1000

    # 钠 mg/h
    na_lo, na_hi = 300, 600
    if hot:
        na_lo, na_hi = 400, 800

    gel_carb = 23.0
    total_carb = (carb_lo * hours, carb_hi * hours)

    # 补给时间点（每 35min 一次，赛前 15min 一次）
    schedule = []
    t = 15
    step = 35
    while t <= args.duration_min - 10:
        schedule.append(t)
        t += step

    # 胶数按时间点算，不按碳水总量硬除（否则会出现不现实的数字）
    gel_lo = max(1, len(schedule))
    gel_hi = max(gel_lo, len(schedule) + 1)
    carb_from_gels = (gel_lo * gel_carb, gel_hi * gel_carb)

    out = {
        "duration_min": args.duration_min,
        "intensity": args.intensity,
        "carbs_g_per_h": [carb_lo, carb_hi],
        "total_carbs_g": [round(total_carb[0]), round(total_carb[1])],
        "gels": [gel_lo, gel_hi],
        "carbs_from_gels_g": [round(carb_from_gels[0]), round(carb_from_gels[1])],
        "gel_schedule_min": schedule,
        "fluid_ml_per_h": [fluid_lo, fluid_hi],
        "sodium_mg_per_h": [na_lo, na_hi],
        "hot_weather": hot,
        "notes": [
            "所有补给先在训练中试过再用于比赛",
            "赛前15min 1支胶 + 100-200ml水",
            "胶不足以覆盖总碳水时，用含糖运动饮料/能量棒补齐",
            ">30℃ 取水/钠上限；比赛日不尝新",
        ],
    }

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    print("时长 %.0fmin · 强度 %s%s" % (args.duration_min, args.intensity,
                                      " · 高温" if hot else ""))
    print("-" * 46)
    print("碳水   : %d-%d g/h（合计 %d-%d g）" %
          (carb_lo, carb_hi, total_carb[0], total_carb[1]))
    print("能量胶 : %d-%d 支（约 %.0f g 碳水/支）" % (gel_lo, gel_hi, gel_carb))
    print("胶供碳水: %d-%d g（缺口用含糖饮料/能量棒补齐）"
          % (round(carb_from_gels[0]), round(carb_from_gels[1])))
    print("时间点 : 第 %s 分钟" % "、".join(str(x) for x in schedule))
    print("水     : %d-%d ml/h" % (fluid_lo, fluid_hi))
    print("钠     : %d-%d mg/h" % (na_lo, na_hi))
    print("-" * 46)
    print("提示: 赛前15min 1支胶；湿热取上限；比赛日不尝新。")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
