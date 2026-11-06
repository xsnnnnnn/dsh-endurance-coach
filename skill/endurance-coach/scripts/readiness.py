#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Readiness 三档判定（多信号红旗表决，纯标准库）。

用法:
  python readiness.py --hrv 48 --hrv-baseline 62 --hrv-normal 45 80 \
      --rhr 54 --rhr-baseline 52 --sleep-score 64 --sleep-hours 5.9 \
      --load-ratio 1.18
  python readiness.py --subjective tired

规则:
  红旗 0 项 -> PASS；1 项 -> CAUTION；>=2 项 -> RED；
  --subjective 非 none 时直接一票否决 RED；
  4 类信号全部缺失 -> UNKNOWN（明说未做判定）。
  缺失的信号不参与计数，但会在输出里列出。
"""
import argparse
import json
import sys

PASS, CAUTION, RED, UNKNOWN = "PASS", "CAUTION", "RED", "UNKNOWN"


def main():
    ap = argparse.ArgumentParser(
        description="Readiness 三档判定（多信号红旗表决，纯标准库）",
        epilog="示例: python readiness.py --hrv 48 --hrv-normal 45 80 --rhr 54 --rhr-baseline 52",
    )
    ap.add_argument("--hrv", type=float, help="睡眠 HRV（ms）")
    ap.add_argument("--hrv-baseline", type=float, help="HRV 7 日均值/基线（ms）")
    ap.add_argument("--hrv-normal", type=float, nargs=2, metavar=("LOW", "HIGH"),
                    help="HRV 正常区间下限与上限")
    ap.add_argument("--rhr", type=float, help="静息心率（bpm）")
    ap.add_argument("--rhr-baseline", type=float, help="静息心率 7 日基线（bpm）")
    ap.add_argument("--rhr-delta", type=float, default=5.0, help="静息心率红旗阈值（默认 5 bpm）")
    ap.add_argument("--sleep-score", type=float, help="睡眠评分")
    ap.add_argument("--sleep-hours", type=float, help="睡眠时长（小时）")
    ap.add_argument("--sleep-score-min", type=float, default=70.0, help="睡眠评分红旗阈值（默认 70）")
    ap.add_argument("--sleep-hours-min", type=float, default=6.0, help="睡眠时长红旗阈值（默认 6h）")
    ap.add_argument("--load-ratio", type=float, help="官方负荷比 ACWR")
    ap.add_argument("--load-ratio-max", type=float, default=1.3, help="负荷比红旗阈值（默认 1.3）")
    ap.add_argument("--ramp-rate", type=float, help="负荷周变化 rampRate")
    ap.add_argument("--ramp-max", type=float, default=8.0, help="rampRate 红旗阈值（默认 8）")
    ap.add_argument("--subjective", default="none",
                    choices=["none", "tired", "sore", "poorsleep", "pain"],
                    help="主观反馈；任意非 none 值一票否决为 RED")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    flags = []
    missing = []

    # 1) 睡眠 HRV
    if args.hrv is not None and (args.hrv_normal or args.hrv_baseline):
        hit = False
        if args.hrv_normal and args.hrv < args.hrv_normal[0]:
            hit = True
            flags.append("HRV %.0f 低于正常下限 %.0f" % (args.hrv, args.hrv_normal[0]))
        if args.hrv_baseline and args.hrv <= args.hrv_baseline * 0.80:
            if not hit:
                flags.append("HRV %.0f 较基线 %.0f 低 >=20%%" % (args.hrv, args.hrv_baseline))
                hit = True
        if hit:
            pass
    else:
        missing.append("HRV")

    # 2) 静息心率
    if args.rhr is not None and args.rhr_baseline is not None:
        if args.rhr >= args.rhr_baseline + args.rhr_delta:
            flags.append("静息心率 %.0f 较基线 %.0f 高 %.0f bpm"
                         % (args.rhr, args.rhr_baseline, args.rhr - args.rhr_baseline))
    else:
        missing.append("静息心率")

    # 3) 睡眠
    if args.sleep_score is not None or args.sleep_hours is not None:
        if args.sleep_score is not None and args.sleep_score < args.sleep_score_min:
            flags.append("睡眠评分 %.0f < %.0f" % (args.sleep_score, args.sleep_score_min))
        if args.sleep_hours is not None and args.sleep_hours < args.sleep_hours_min:
            flags.append("睡眠时长 %.1fh < %.1fh" % (args.sleep_hours, args.sleep_hours_min))
    else:
        missing.append("睡眠")

    # 4) 负荷
    if args.load_ratio is not None or args.ramp_rate is not None:
        if args.load_ratio is not None and args.load_ratio > args.load_ratio_max:
            flags.append("负荷比 %.2f > %.2f" % (args.load_ratio, args.load_ratio_max))
        if args.ramp_rate is not None and args.ramp_rate > args.ramp_max:
            flags.append("rampRate %.1f > %.0f" % (args.ramp_rate, args.ramp_max))
    else:
        missing.append("负荷")

    # 5) 主观（一票否决）
    subjective_hit = args.subjective != "none"
    if subjective_hit:
        flags.append("主观反馈: %s" % args.subjective)

    n = len(flags)
    if subjective_hit:
        verdict = RED
    elif n == 0 and len(missing) == 4:
        verdict = UNKNOWN
    elif n == 0:
        verdict = PASS
    elif n == 1:
        verdict = CAUTION
    else:
        verdict = RED

    actions = {
        PASS: "按计划执行",
        CAUTION: "保留课表；质量课组数-1或放慢5-8s/km，长距离不改",
        RED: "取消/降级当日质量课：改30-40min Z1-Z2 或完全休息；长距离缩30%",
        UNKNOWN: "生理数据缺失，未做状态判定；按计划但保守执行，并补数据",
    }

    out = {"verdict": verdict, "flags": flags, "missing": missing,
           "action": actions[verdict]}
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    print("判定: %s" % verdict)
    print("红旗: %d 项" % n)
    for f in flags:
        print("  - %s" % f)
    if missing:
        print("缺失: %s" % "、".join(missing))
    print("动作: %s" % actions[verdict])
    if n >= 2:
        print("提示: 连续3天 RED -> 整周减量20-30%，并写入 decisions.log.md")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
