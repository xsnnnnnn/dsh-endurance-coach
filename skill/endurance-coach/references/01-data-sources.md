# 01 · 数据源口径（取数前必读）

> **默认只用 Intervals.icu 取数**；COROS 只负责「训练计划读写 + ICU 没有的字段补位 + ICU 不可用时回退」；iGPSPORT 只做兜底。
> 各源各管一段，**不许串、不许叠加**。这是踩过坑后固化的规则。
> 若某个 MCP 插件没装，对应数据就按「未取到」处理，改用用户手动提供的数据（标注「手动」），不要从别的源凑。

## 1. 分工（默认 + 角色）

| 想知道 | 默认来源 | 工具前缀 | 其他源的角色 |
|---|---|---|---|
| 活动/课次（跑步、越野、骑行、游泳）：距离、时间、均速、HR、训练负荷、设备名 | **Intervals.icu** | `mcp__intervals__` | COROS 仅 ICU 不可用或缺明细时回退；iGPSPORT 只兜底骑行 |
| 分圈 / 区间：GAP、步频、功率、W' | **Intervals.icu** | `mcp__intervals__` | 同上 |
| 综合负荷：CTL / ATL / TSB / rampRate | **Intervals.icu** | `mcp__intervals__` | 不可用才回退 COROS `queryTrainingLoadAssessment` |
| 生理与恢复：静息心率、HRV、睡眠在床时长、体重、步数、eFTP | **Intervals.icu** `get_wellness_data` | `mcp__intervals__` | 睡眠评分 / 恢复分 / HRV 评估状态 ICU 没有 → COROS 补 |
| 功率 / 阈值：功率曲线、eFTP | **Intervals.icu** `get_athlete_power_curves` + eFTP | `mcp__intervals__` | 码表 FTP / LTHR 用 iGPSPORT 核对 |
| 训练计划（读取 / 写入） | **COROS**（唯一权威） | `mcp__coros__` | 计划通常在高驰、不会镜像到 ICU 日历，不能用 ICU 替代 |
| 睡眠评分 sleep score / 恢复分 recovery / HRV 评估状态 | **COROS**（补位） | `mcp__coros__` | ICU 没有这些字段，只在需要时取并标注「COROS 补充」 |
| 天气 | Open-Meteo | `<this skill>/scripts/weather.py` | 与训练数据源无关，无需注册 |

> ICU 的 `get_events` 只在**用户把计划放进 ICU 日历**时才有用；高驰训练计划不会自动镜像到 ICU（实测 `get_events` 为空），所以计划读取/写入仍走 COROS。

## 2. ICU 默认取数顺序

1. `get_activities`：按日期范围定位活动（跑步、越野、骑行、游泳）。
2. `get_activity_details`：单次汇总（距离、时间、HR、训练负荷等）。
3. `get_activity_intervals`：分圈 / 区间（GAP、步频、功率、W'）。
4. 需要逐秒分析时才 `get_activity_streams`（秒级流，注意上下文消耗）。
5. 综合负荷与生理：`get_wellness_data`（一次读回 `ctl` / `atl` / `rampRate` / `eFTP` / `restingHR` / HRV / `sleepSecs` / `weight` / `steps`）。
6. 功率曲线：`get_athlete_power_curves`；阈值优先用 eFTP。

## 3. 三条硬禁止（＋同一活动不跨源相加）

1. **ICU 活动 + COROS `querySportRecords` 不能相加** —— 同一次跑步会算两遍。
2. **ICU 骑行量 + iGPSPORT 骑行量不能相加** —— 是同一批骑行（经第三方平台进入 ICU）。
3. **不要用 iGPSPORT 的 `analyze_training_load`** —— 实测其综合负荷与 ICU 差一个量级，CTL 类算法不可信。骑行**单次**的 NP/IF/TSS 是准的，只在 iGPSPORT 兜底时使用。

> **同一活动、同一指标只认一个源**：两个源都有时默认 ICU，不得相加。
> 允许相加的只有「不同运动的总距离」（跑步 + 骑行），且必须分别标注来源。

## 4. COROS 的三个保留角色

1. **训练计划唯一权威**：`queryTrainingSchedule` / `queryTrainingPlanLibrary` / `queryTrainingPlanDetails` / `updateTrainingPlan` / `createScheduledWorkout` / `queryScheduledWorkoutDetails` / `updateScheduledWorkout`。计划的读取与写入只走这里，不要用 ICU `get_events` 替代。
2. **ICU 没有的字段补位**：`querySleepOverview`（睡眠评分）、`queryRecoveryStatus`（恢复分）、`querySleepHrv`（只读 Assessment 评估段）。只在需要时取，输出标注「COROS 补充」。
3. **回退**：ICU 不可用、或该活动在 ICU 缺明细时回退（见第 8 节）。

> `querySportRecords` / `queryTrainingLoadAssessment` 等执行类工具只在降级时用，不是默认取数。

## 5. iGPSPORT 兜底

默认**不取**。只有两种场景：

- ICU 缺该次骑行明细（Strava 来源 withheld / 无数据）→ 用它补这一次的骑行明细，并注明来源。
- 核对码表里的 FTP / LTHR（和 ICU eFTP 对不上时）。

## 6. 取数决策树

```
要不要读写计划？ ── 是 → COROS（唯一权威）
今天能不能练？   ── → ICU get_wellness_data + 最近活动（get_activities）
                      睡眠评分缺失才 COROS querySleepOverview 补
复盘某次活动？   ── → ICU get_activities → get_activity_details → get_activity_intervals
                      （需要逐秒才 get_activity_streams；ICU 缺明细才回退 COROS / iGPSPORT）
综合负荷？       ── → ICU get_wellness_data（ctl / atl / rampRate）
睡眠？           ── → ICU sleepSecs（在床口径）；要评分或睡着时长 → COROS 补
功率 / 阈值？    ── → ICU get_athlete_power_curves / eFTP（码表 FTP 用 iGPSPORT 核对）
天气？           ── → weather.py（Open-Meteo）
```

## 7. 睡眠口径（容易错）

- **默认取 ICU `sleepSecs`**，它是在**床时长（含清醒）**，不是睡着时长；输出必须标注「在床」。
- 需要**睡着时长**或**睡眠评分** → COROS `querySleepOverview` 补，标注「COROS 补充」。两个数字不能互相替代。
- `readiness.py` 的 `--sleep-hours` 用 ICU 在床时长（阈值判断是近似口径，会比睡着时长得宽松）；`--sleep-score` 只有 COROS 有，取不到就**不传这个参数**（脚本支持缺省，缺失不参与表决）。
- `querySleepHrv` 原始时间序列极长，**只读 HRV Assessment 评估段**，不要整段输出。

## 8. 写入边界

| 源 | 规则 |
|---|---|
| COROS | 训练计划**只写这里**。改计划：`queryTrainingPlanDetails` 取完整 courseList → 改该日 → `updateTrainingPlan` 整日提交（按天覆盖，不是追加） |
| Intervals.icu | **只读为主**。写操作（`add_or_update_event` / `add_or_update_note` / `delete_event` / `delete_events_by_date_range` / `add_activity_message` / custom_items 增删改）先说明、等确认 |
| iGPSPORT | **只读为主**。`create_workout`（推码表）必须先问用户；`delete_workout` 破坏性，必须二次确认 |

## 9. 降级策略（一次只降一级，注明回退）

- **ICU 挂了** → 跑步回退 COROS `querySportRecords` + `queryTrainingLoadAssessment`，骑行回退 iGPSPORT，睡眠回退 COROS；末尾注明「ICU 不可用，已回退 X」。
- **COROS 挂了** → 计划读写如实说不可用（不要假装能读写）；睡眠评分 / 恢复分缺失，用 ICU 在床时长 + HRV / 静息心率判灯并注明「COROS 不可用，睡眠为近似判断」。
- **iGPSPORT 挂了** → 直接用 ICU 骑行数据，无需替代。
- **全部缺失** → 请用户手动贴数据，标注「手动」。

> 降级后不要再把两个源的同一活动/同一指标相加（见第 3 节）。

## 10. 数据缺口处理

- 单个工具失败 → 跳过，末尾一行「X 数据未取到」。
- **不推断、不填默认值、不编造数字**（这是 ai-running-coach 规则⑥，已采纳）。
- 全部生理数据缺失 → 必须明说「无生理数据，未做状态判定」，**不得输出「状态良好」**。

## 11. 常用工具速查

**Intervals.icu（默认）**：`get_activities` `get_activity_details` `get_activity_intervals` `get_activity_streams` `get_wellness_data` `get_athlete_power_curves` `get_events`（仅当计划在 ICU）

**COROS（计划 + 补位 + 回退）**：
- 计划：`queryTrainingSchedule` `queryTrainingPlanLibrary` `queryTrainingPlanDetails` `updateTrainingPlan` `createScheduledWorkout` `queryScheduledWorkoutDetails` `updateScheduledWorkout`
- 补位：`querySleepOverview` `queryRecoveryStatus` `querySleepHrv`
- 回退：`querySportRecords` `getActivityDetail` `queryActivityLapData` `queryTrainingLoadAssessment` `queryRestingHeartRate`

**iGPSPORT（兜底）**：`list_activities` `get_activity_summary` `get_activity_laps` `get_activity_streams` `get_athlete_profile` `estimate_thresholds`

**天气**：`<this skill>/scripts/weather.py`（Open-Meteo，无需注册）

## 12. 坑位清单

- 越野跑不支持时间目标（只能距离/爬升）；跑步、骑行不支持爬升目标。
- 「等强配速」绝对值不支持，只能用 `%等强阈值配速`（intensityType 3）的区间/百分比。
- 已完成或过去的课程改不了 → 如实告知去 COROS App 操作。
- `createSingleWorkout` 只存库不排期；要落到某天用 `createScheduledWorkout`。
- 第三方平台（如 Strava 来源）的活动明细可能 withheld，此时才回退到设备平台并注明来源。
- 高驰计划不会同步到 ICU 日历：读计划走 COROS，**不要用 `get_events` 判断「今天有没有课」**。
- ICU `sleepSecs` 是在床口径，不要当睡着时长写进晨报；要写睡着时长就标注「COROS 补充」。
