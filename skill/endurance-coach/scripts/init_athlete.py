#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""耐力教练 · 首次配置：从 assets 模板生成个人档案。

用法:
  python init_athlete.py
  python init_athlete.py --out mycoach/athlete.json
  python init_athlete.py --force

行为:
  1. 把本 skill 的 assets/athlete.example.json 复制成目标档案
     （默认 coach/athlete.json；可用环境变量 ENDURANCE_COACH_DIR 改默认目录）。
  2. 同目录创建 decisions.log.md（来自 assets/decisions.log.template.md）。
  3. 目标文件已存在时拒绝覆盖，除非加 --force。
  4. 打印下一步操作提示。

退出码: 0 成功；1 已存在而拒绝 / 模板缺失 / 写入失败。
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
EXAMPLE_PATH = SKILL_DIR / "assets" / "athlete.example.json"
DECISIONS_TEMPLATE = SKILL_DIR / "assets" / "decisions.log.template.md"


def default_coach_dir() -> Path:
    return Path(os.environ.get("ENDURANCE_COACH_DIR", "coach"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="耐力教练 · 首次配置：从 assets 模板生成 coach/athlete.json 与 decisions.log.md",
        epilog="示例: python init_athlete.py --out coach/athlete.json",
    )
    ap.add_argument("--out", default=None,
                    help="目标档案路径（默认 <ENDURANCE_COACH_DIR 或 coach>/athlete.json）")
    ap.add_argument("--decisions-out", default=None,
                    help="目标调整日志路径（默认与档案同目录的 decisions.log.md）")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的文件")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要做什么，不写文件")
    args = ap.parse_args()

    if not EXAMPLE_PATH.is_file():
        print(f"❌ 找不到示例档案：{EXAMPLE_PATH}", file=sys.stderr)
        print("   本脚本必须在完整的 skill 目录内运行（assets/ 与 scripts/ 同级）。", file=sys.stderr)
        return 1
    if not DECISIONS_TEMPLATE.is_file():
        print(f"❌ 找不到 decisions 模板：{DECISIONS_TEMPLATE}", file=sys.stderr)
        return 1

    out_path = Path(args.out).expanduser() if args.out else default_coach_dir() / "athlete.json"
    decisions_path = (Path(args.decisions_out).expanduser() if args.decisions_out
                      else out_path.parent / "decisions.log.md")

    if out_path.exists() and not args.force:
        print(f"❌ 档案已存在：{out_path}", file=sys.stderr)
        print("   为避免覆盖你的真实数据，本次不做任何修改。", file=sys.stderr)
        print("   确需重建请加 --force（会覆盖档案；decisions.log.md 不会被覆盖）。", file=sys.stderr)
        return 1

    # 先验证模板是合法 JSON，避免写出坏档案
    try:
        json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 示例档案不是合法 JSON：{exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("DRY-RUN：将创建")
        print(f"  - {out_path}（来自 {EXAMPLE_PATH}）")
        print(f"  - {decisions_path}（{'已存在，跳过' if decisions_path.exists() else '来自模板'}）")
        return 0

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(EXAMPLE_PATH, out_path)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 写档案失败：{exc}", file=sys.stderr)
        return 1

    if decisions_path.exists() and not args.force:
        decisions_note = "已存在，保留原文件"
    else:
        try:
            write_text(decisions_path, DECISIONS_TEMPLATE.read_text(encoding="utf-8"))
            decisions_note = "已创建"
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ 写 decisions.log.md 失败：{exc}", file=sys.stderr)
            decisions_note = "创建失败（可手动复制 assets/decisions.log.template.md）"

    print("✅ 首次配置完成")
    print(f"   档案: {out_path.resolve()}")
    print(f"   调整日志: {decisions_path.resolve()}（{decisions_note}）")
    print("")
    print("下一步：")
    print("  1. 打开档案，把 example 值替换成自己的真实数据：")
    print("     location（天气坐标）、races（A/B 赛事与目标）、coros_baseline、")
    print("     pace_guide、cycling、health_thresholds、availability。")
    print("  2. 测试天气取数：")
    print(f"     python {SCRIPT_DIR / 'weather.py'} --days 7")
    print("  3. 测试 VDOT / 配速区间：")
    print(f"     python {SCRIPT_DIR / 'vdot.py'} --distance 5k --time 22:00")
    print("  4. 回到对话里说「今天练什么」，从工作流 W1 开始。")
    print("")
    print("注意：示例档案里的数值全部是虚构的，直接拿去做训练决策会误导自己。")
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.exit(main())
