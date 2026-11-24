#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
虹夏 · 越野需求量与爬升剂量（确定性算术，模型只复述）

用途
----
1. 把「距离 + 爬升」换算成同一口径的赛事量级（ITRA km-effort = km + D+/100），
   让 10km/500m 和 50km/2500m 能放在一起比。
2. 按赛事爬升给出**周爬升护栏**：下一周最多 +10%、峰值不超过赛事爬升 ×1.5。
3. 给出补给档位与单次长课爬升上限，避免模型在对话里手算或编公式。

用法
----
    python trail.py --distance-km 13 --climb-m 1000
    python trail.py --distance-km 50 --climb-m 2500 --descent-m 2400
    python trail.py --distance-km 50 --climb-m 2500 --week-climb 900
    python trail.py --distance-km 50 --climb-m 2500 --json

退出码
------
    0 成功
    3 参数错误（缺距离/爬升、数值非法）

约束
----
- 只做算术与查表，**不做成绩预测**；没有本人同类数据就不给配速。
- 峰值系数 1.0–1.5 是经验值，不是公式；首次越野取下限。
"""

from __future__ import annotations

import argparse
import json
import sys

# 周爬升护栏
CLIMB_WEEK_GROWTH = 1.10          # 单周爬升增幅上限 +10%
CLIMB_PEAK_LOW, CLIMB_PEAK_HIGH = 1.0, 1.5   # 峰值周爬升 = 赛事爬升 × 系数
LONG_RUN_CLIMB_SHARE = 0.60       # 单次长课爬升 ≤ 周爬升的 60%

# 档位（按 km-effort，ITRA 口径）
TIERS = [
    ("短越野", 0, 35, "≤3h 量级：当天可恢复，补给按公路半马档"),
    ("中距越野", 35, 70, "3–8h 量级：需要专门补给演练"),
    ("长距/超马", 70, 10**9, "≥8h 量级：按月排周期，胃和脚优先"),
]

# 补给档（碳水 g/h），与 references/10-trail.md §9 一致
FUEL = {
    "短越野": (30, 45, "胶为主，口渴抿水"),
    "中距越野": (30, 60, "胶 + 咸软食；先保证吃得下"),
    "长距/超马": (30, 60, "来源多样，后程偏咸；胃翻立刻减"),
}


def km_effort(distance_km: float, climb_m: float) -> float:
    """ITRA 口径：km-effort = 距离(km) + 爬升(m)/100。"""
    return round(distance_km + climb_m / 100.0, 1)


def classify(effort: float) -> tuple[str, str, str]:
    for name, lo, hi, note in TIERS:
        if lo <= effort < hi:
            return name, note, FUEL[name][2]
    return TIERS[-1][0], TIERS[-1][3], FUEL[TIERS[-1][0]][2]


def climb_plan(race_climb: float, week_climb: float | None) -> dict:
    """周爬升护栏。只给区间与上限，不预测成绩。"""
    peak_low = round(race_climb * CLIMB_PEAK_LOW)
    peak_high = round(race_climb * CLIMB_PEAK_HIGH)
    # 单次长课爬升上限以「当前/下周的周爬升」为基准，没给周爬升就用峰值下限
    base_for_long = week_climb if week_climb and week_climb > 0 else peak_low
    out = {
        "race_climb_m": round(race_climb),
        "peak_week_climb_m": [peak_low, peak_high],
        "peak_note": "经验值：赛事爬升 ×1.0–1.5；首次越野取下限",
        "long_run_climb_cap_m": round(base_for_long * LONG_RUN_CLIMB_SHARE),
        "long_run_climb_basis_m": round(base_for_long),
    }
    if week_climb is not None:
        nxt = round(week_climb * CLIMB_WEEK_GROWTH)
        capped = min(nxt, peak_high)
        out["current_week_climb_m"] = round(week_climb)
        out["next_week_climb_m"] = capped
        if capped < nxt:
            out["next_note"] = f"已按峰值上限 {peak_high}m 截断（+10% 会到 {nxt}m）"
        elif week_climb > peak_high:
            out["next_note"] = f"当前周爬升已超峰值上限 {peak_high}m，建议回落而不是继续加"
        else:
            out["next_note"] = "按 +10% 递增；每 3–4 周插一个减载周（爬升 −30~40%）"
    return out


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="越野需求量与爬升剂量（ITRA km-effort）")
    p.add_argument("--distance-km", type=float, required=True, help="赛事距离（km）")
    p.add_argument("--climb-m", type=float, required=True, help="累计爬升 D+（m）")
    p.add_argument("--descent-m", type=float, help="累计下降 D−（m，缺省按 ≈D+ 估）")
    p.add_argument("--week-climb", type=float, help="当前周爬升（m），给了才会算下周目标")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    args = p.parse_args(argv)

    if args.distance_km <= 0 or args.climb_m < 0:
        print("❌ 距离必须 >0，爬升必须 ≥0", file=sys.stderr)
        return 3

    descent = args.descent_m if args.descent_m is not None else args.climb_m
    effort = km_effort(args.distance_km, args.climb_m)
    tier, tier_note, fuel_note = classify(effort)
    carb_low, carb_high, _ = FUEL[tier]
    climb = climb_plan(args.climb_m, args.week_climb)

    payload = {
        "race": {
            "distance_km": args.distance_km,
            "climb_m": round(args.climb_m),
            "descent_m": round(descent),
            "descent_estimated": args.descent_m is None,
            "km_effort": effort,
            "descent_climb_ratio": round(descent / args.climb_m, 2) if args.climb_m else None,
        },
        "tier": tier,
        "tier_note": tier_note,
        "fuel": {"carb_g_per_h": [carb_low, carb_high], "note": fuel_note},
        "climb": climb,
        "walk_run": {
            "run_below_grade_pct": 8,
            "mix_8_15": "8–15% 跑走结合，心率 Z3",
            "hike_above_grade_pct": 15,
            "note": "坡度 >15% 走路合法；没练过 power hike 的人赛日一定走崩",
        },
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        return 0

    print(f"【赛事】{args.distance_km:g} km / D+ {args.climb_m:g} m / D− {descent:g} m"
          f"{'（按 D+ 估）' if args.descent_m is None else ''}")
    print(f"  km-effort（ITRA）= {effort}  →  档位：{tier}")
    print(f"  {tier_note}")
    print(f"  补给：碳水 {carb_low}–{carb_high} g/h（按小时，不按公里）；{fuel_note}")
    print("【爬升护栏】")
    print(f"  峰值周爬升：{climb['peak_week_climb_m'][0]}–{climb['peak_week_climb_m'][1]} m"
          f"（{climb['peak_note']}）")
    print(f"  本周单次长课爬升上限：约 {climb['long_run_climb_cap_m']} m"
          f"（以 {climb['long_run_climb_basis_m']} m 周爬升的 60% 算）")
    if "next_week_climb_m" in climb:
        print(f"  当前周爬升 {climb['current_week_climb_m']} m → 下周建议 {climb['next_week_climb_m']} m")
        print(f"  {climb['next_note']}")
    print("【走跑切换】")
    print(f"  坡度 <{payload['walk_run']['run_below_grade_pct']}% 直接跑；"
          f"8–15% 跑走结合；>{payload['walk_run']['hike_above_grade_pct']}% 走是合法动作")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
