# 02 · 负荷与恢复判断（W1/W3 必读）

> 目标：**不靠单一指标**，用多信号红旗表决。设备自带的「状态分」经常偏乐观。

## 1. 负荷指标

| 指标 | 含义 | 健康区 | 危险信号 |
|---|---|---|---|
| CTL | 长期负荷（体能） | 缓慢上升 | 周增幅 > 8–10 |
| ATL | 短期负荷（疲劳） | 与 CTL 同向 | ATL/CTL > 1.5 |
| TSB (=CTL−ATL) | 状态 | −10 ~ +10 可练 | < −20 明显疲劳；> +20 可能练少了 |
| Load Ratio | 官方 ACWR | 0.8–1.3 | > 1.3 预警；> 1.5 次日强制减量 |
| rampRate | 周负荷变化 | < 5 | > 8 风险高 |

> 以上负荷指标取 ICU `get_wellness_data`（`ctl` / `atl` / `rampRate`）；TSB 用 CTL−ATL 算。官方 Load Ratio 优先，没有才自算，两者不混用。

## 2. Readiness 三档（红旗表决）

**信号清单（按个人阈值，取自 `coach/athlete.json` → `health_thresholds`）**

| # | 信号 | 红旗条件 |
|---|---|---|
| 1 | 睡眠 HRV | 低于正常区间下限，或较 7 日均值低 ≥20% |
| 2 | 静息心率 | 较 7 日基线高 ≥5 bpm（`rhr_red_flag_delta_bpm`） |
| 3 | 睡眠 | 睡眠时长（在床口径近似）<6h |
| 4 | 负荷 | Load Ratio >1.3，或 ICU rampRate >8 |
| 5 | 主观 | 用户主动说累 / 酸痛 / 没睡好 / 疼痛 |

> 数据来源（唯一源 Intervals.icu）：HRV、静息心率、睡眠时长、负荷都取 `get_wellness_data`（HRV / `restingHR` / `sleepSecs` / `ctl` / `atl` / `rampRate`）；**Intervals.icu 没有睡眠评分**，评分不参与表决，只按睡眠时长（在床口径）判。

**表决规则**

```
红旗数 = 0            → PASS   （按计划执行）
红旗数 = 1            → CAUTION（保留课表，质量课降预期，提示关注）
红旗数 ≥ 2            → RED    （取消/降级当日质量课）
信号 5 单独成立        → 直接 RED（一票否决，不用凑数）
全部数据缺失          → UNKNOWN（明说未做判定，不得说「状态良好」）
```

> 缺失的信号不参与计数、不计红旗（避免误报）；但缺失本身要在输出里注明。

## 3. 三档动作

| 档位 | 质量课 | 长距离 | 轻松跑 |
|---|---|---|---|
| PASS | 按计划 | 按计划 | 按计划 |
| CAUTION | 组数 −1，或配速放慢 5–8 s/km | 不变，全程降速 | 不变 |
| RED | 取消，改 30–40min Z1–Z2 或完全休息 | 缩短 30% | 可保留极轻松 |

**连续 3 天 RED** → 建议整周减量 20–30%，并在 `coach/decisions.log.md` 记录。

## 4. 「设备状态分偏乐观」的典型模式

**案例（example，虚构数据）**：手表显示「状态良好」（自带状态分 100），但 HRV 44ms（低于正常下限 45）、睡眠 5h55m、静息心率 56（基线 52，+4bpm 未达 5bpm 阈值但方向一致）。
→ 红旗 2 项（HRV + 睡眠时长），正确结论是 **RED**，不是「状态很好可以上强度」。
→ 说明：**设备状态分高与红旗并不矛盾**；它只是一项参考，睡眠差、HRV 低照样该降级。

**规则：设备自带的「状态分」不进红旗清单，也不作为判定依据。**

## 5. 与负荷的交叉判断

- 生理指标好、但 TSB < −20 → CAUTION，别硬上强度。
- 生理指标差、但 TSB > +10 → 仍按生理优先，RED。
- rampRate > 8 且本周计划还要加量 → 先维持，不加。
- 骑行大负荷周（训练冲量高）→ 下周跑量**强制不递增**（保护性维持）。

## 6. 脚本调用

```bash
python <this skill>/scripts/readiness.py \
  --hrv 48 --hrv-baseline 62 --hrv-normal 45 80 \
  --rhr 54 --rhr-baseline 52 \
  --sleep-hours 5.9 \
  --load-ratio 1.18 \
  --subjective none
```

输出 `PASS / CAUTION / RED / UNKNOWN` + 触发的红旗明细。模型只复述结果，不自行加减。
`--subjective` 可用 `none / tired / sore / poorsleep / pain`；任意非 `none` 值都是一票否决。
（上面参数是示例值，实际从 `health_thresholds` 与 Intervals.icu `get_wellness_data` 的当日数据取。）

**取数映射（唯一源 Intervals.icu）**：`--hrv` / `--rhr` / `--load-ratio` 取 `get_wellness_data`；`--sleep-hours` 用 `sleepSecs`（**在床时长，含清醒**，阈值判断为近似口径）；Intervals.icu 没有睡眠评分，`--sleep-score` 缺失就**不传该参数**（脚本支持缺省）。
