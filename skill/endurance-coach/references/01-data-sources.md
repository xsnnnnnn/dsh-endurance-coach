# 01 · 数据源口径（取数前必读）

> **单一数据源：COROS。** 训练执行、训练计划、睡眠/HRV、恢复、负荷全部来自 COROS 一个平台。
> 天气来自 Open-Meteo；阈值（FTP/LTHR/配速）来自你自己的实测或手动提供。
> 这是踩过坑后固化的规则：**跨源相加会重复计数，第三方 CTL 算法不可验证**。

## 1. 分工

| 想知道 | 唯一来源 | 工具前缀 |
|---|---|---|
| 跑步执行、骑行执行（活动、功率、NP/IF/TSS、分区、分圈、FIT） | **COROS** | `mcp__coros__` |
| 训练计划（读、写、改） | **COROS** | `mcp__coros__` |
| 睡眠、HRV、静息心率、恢复分 | **COROS** | `mcp__coros__` |
| 训练负荷（短期/长期负荷、load ratio、TSB 推算） | **COROS** | `mcp__coros__` |
| 骑行阈值（FTP/LTHR）、配速区间、比赛预测 | COROS 实测或用户自测/手动提供 | — |
| 天气与空气质量 | Open-Meteo + aqicn（脚本内置） | `<this skill>/scripts/weather.py` |

## 2. 三条硬规则（单源版）

1. **不引第二套数字**。同一指标（距离、负荷、睡眠、功率）只在 COROS 拿一次，不要再用别的平台核对后再相加或取平均。
2. **不用第三方的 CTL/ATL/TSB 算法**。负荷一律取 COROS 自己算的短期/长期负荷与 load ratio；需要 TSB 时用「长期负荷 − 短期负荷」推算，并在输出里注明「COROS 负荷推算」。
3. **允许相加的只有「不同运动的总距离」**（跑步 + 骑行），且必须分别标注来源与项目。

## 3. 取数决策树

```
需要跑步数据？ ── 是 → COROS querySportRecords（跑步 sportTypeCodes）→ getActivityDetail / queryActivityLapData
需要骑行数据？ ── 是 → COROS querySportRecords（骑行 sportTypeCodes 200-205）→ getActivityDetail / queryActivityLapData
                        需要功率曲线 → downloadActivityFitFiles / queryActivityFitFileDownloadUrls
需要训练计划？ ── 是 → COROS queryTrainingSchedule → 计划内再 queryTrainingPlanDetails
需要睡眠？    ── 是 → COROS querySleepOverview / querySleepHrv（只取 Assessment 段）
需要恢复？    ── 是 → COROS queryRecoveryStatus / queryRestingHeartRate
需要负荷？    ── 是 → COROS queryTrainingLoadAssessment（短期/长期负荷、load ratio）
```

## 4. 负荷口径（最容易造反）

- COROS `queryTrainingLoadAssessment` 给的是**短期负荷 / 长期负荷 / load ratio**，用它们做红黄绿灯与减量判断。
- **不要**把另一平台的 CTL/ATL/TSB 拿来和 COROS 的负荷混用或互相换算——两边算法不同，换算出来的数字没有意义。
- 需要 TSB 时：`TSB ≈ 长期负荷 − 短期负荷`，并注明「COROS 负荷推算」；不要把它当官方 TSB 展示。
- 负荷趋势看 4–6 周的走向，不要盯单日波动；单日异常先查是否漏记录/多记录。

## 5. 睡眠口径（容易错）

- **睡眠相关数字一律取 COROS**（设备自己测的睡眠结构最完整）。
- `querySleepHrv` 原始时间序列极长，**只读 HRV Assessment 评估段**，不要整段输出。
- 没有设备数据时写「睡眠数据未取到」，不要用「感觉睡得还行」顶上。

## 6. 写入边界

| 操作 | 规则 |
|---|---|
| 读数据（活动/睡眠/负荷/计划） | 随便读，不做任何写操作 |
| 改训练计划 | **只写 COROS**：`queryTrainingPlanDetails` 取完整 courseList → 改该日 → `updateTrainingPlan` 整日提交（按天覆盖，不是追加）；写前说明并等确认 |
| 新建单次课程 | `createScheduledWorkout`（直接排到某天）或 `createSingleWorkout`（只存库）；先确认 |
| 已完成/已过去的课程 | 改不了，如实告知去 COROS App 操作 |
| 阈值类设置（FTP/LTHR） | 不自动写；用户明确要求且同意后，由用户自己在设备端改 |

## 7. 降级策略

- **COROS 不可用** → 直接说「COROS 数据未取到」，可以请用户手动贴数据并标注「手动」；**不要**拿别的平台顶上，也不要编数字。
- **天气不可用** → 写「天气数据未取到」，只给原则性建议（按体感降速）。
- 单个工具失败 → 跳过该项，末尾一行「X 数据未取到」。

## 8. 数据缺口处理

- **不推断、不填默认值、不编造数字**。
- 全部生理数据缺失 → 必须明说「无生理数据，未做状态判定」，**不得输出「状态良好」**。
- 负荷缺失时不要用「训练量」倒推疲劳等级。

## 9. 常用工具速查（全部 `mcp__coros__`）

`queryRecoveryStatus` `queryTrainingLoadAssessment` `querySleepOverview` `querySleepHrv` `queryRestingHeartRate`
`queryAvgHeartRate` `queryFitnessAssessmentOverview` `queryUserInfo`
`querySportRecords`（骑行 `sportTypeCodes` 200-205）`getActivityDetail` `queryActivityLapData` `queryCustomActivityLapData`
`downloadActivityFitFiles` / `queryActivityFitFileDownloadUrls`
`queryTrainingSchedule` `queryTrainingPlanLibrary` `queryTrainingPlanDetails` `updateTrainingPlan`
`createScheduledWorkout` `queryScheduledWorkoutDetails` `updateScheduledWorkout` `createSingleWorkout` `queryWorkoutLibrary` `queryWorkoutDetails` `updateWorkoutDetails`

## 10. 坑位清单

- 越野跑不支持时间目标（只能距离/爬升）；跑步、骑行不支持爬升目标。
- 「等强配速」绝对值不支持，只能用 `%等强阈值配速`（intensityType 3）的区间/百分比。
- 已完成或过去的课程改不了 → 如实告知去 COROS App 操作。
- `createSingleWorkout` 只存库不排期；要落到某天用 `createScheduledWorkout`。
- 时间目标与距离目标不要混着写在一节课里；每段只给一个 targetType。
- 别把「Lap 平均功率」当单次骑行的平均功率；没功率就是没功率，不要用速度估。
