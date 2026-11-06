# 01 · 数据源口径（取数前必读）

> 三个源各管一段，**不许串、不许叠加**。这是踩过坑后固化的规则。
> 若某个 MCP 插件没装，对应数据就按「未取到」处理，改用用户手动提供的数据，不要从别的源凑。

## 1. 分工

| 想知道 | 唯一来源 | 工具前缀 |
|---|---|---|
| 跑步执行、训练计划、睡眠/HRV/静息心率/恢复分 | **COROS** | `mcp__coros__` |
| 骑行明细（活动、NP/IF/TSS、分区、分圈、FIT、赛段、FTP） | **iGPSPORT** | `mcp__igpsport__` |
| 综合负荷（CTL / ATL / TSB / rampRate） | **Intervals.icu** | `mcp__intervals__` |

## 2. 三条硬禁止

1. **ICU 活动 + COROS `querySportRecords` 不能相加** —— 同一次跑步会算两遍。
2. **iGPSPORT 骑行量 + ICU 骑行量不能相加** —— 是同一批骑行（经第三方平台进入 ICU）。
3. **不要用 iGPSPORT 的 `analyze_training_load`** —— 实测其综合负荷与 ICU 差一个量级，CTL 类算法不可信。骑行**单次**的 NP/IF/TSS 是准的，可以用。

> 允许相加的只有「不同运动的总距离」（跑步 + 骑行），且必须分别标注来源。

## 3. 取数决策树

```
需要跑步数据？ ── 是 → COROS querySportRecords / getActivityDetail / queryActivityLapData
需要骑行数据？ ── 是 → iGPSPORT list_activities / get_activity_summary / get_activity_laps / get_activity_streams
需要综合负荷？ ── 是 → ICU get_wellness_data（读 ctl / atl / rampRate）
需要睡眠？   ── 是 → COROS querySleepOverview / querySleepHrv（只取 Assessment 段）
需要计划？   ── 是 → COROS queryTrainingSchedule → 计划内再 queryTrainingPlanDetails
```

## 4. 睡眠口径（容易错）

- **睡眠相关数字一律取 COROS**（设备自己测的睡眠结构最完整）。
- ICU `sleepSecs` 是**在床时间（含清醒）**，不是睡着时长。经验上设备显示的「睡着时长」通常比在床时间短 10 分钟到 1 小时，两者不能互相替代。
- `querySleepHrv` 原始时间序列极长，**只读 HRV Assessment 评估段**，不要整段输出。

## 5. 写入边界

| 源 | 规则 |
|---|---|
| COROS | 训练计划**只写这里**。改计划：`queryTrainingPlanDetails` 取完整 courseList → 改该日 → `updateTrainingPlan` 整日提交（按天覆盖，不是追加） |
| iGPSPORT | **只读为主**。`create_workout`（推码表）必须先问用户；`delete_workout` 破坏性，必须二次确认 |
| Intervals.icu | **只做镜像/分析**。写操作（`add_or_update_event` / `add_or_update_note` / `delete_event` / `delete_events_by_date_range` / `add_activity_message` / custom_items 增删改）先说明、等确认 |

## 6. 降级策略（二选一，不许叠加）

- **ICU 挂了** → 负荷退回 COROS `queryTrainingLoadAssessment`，末尾注明「ICU 暂不可用」。
- **iGPSPORT 挂了** → 骑行明细说明不可用，**不要**拿 ICU 里的空壳记录（只有 id 和日期）凑数。
- **COROS 挂了** → 睡眠/恢复无法替代，直接说未取到。

## 7. 数据缺口处理

- 单个工具失败 → 跳过，末尾一行「X 数据未取到」。
- **不推断、不填默认值、不编造数字**（这是 ai-running-coach 规则⑥，已采纳）。
- 全部生理数据缺失 → 必须明说「无生理数据，未做状态判定」，**不得输出「状态良好」**。

## 8. 常用工具速查

**COROS**：`queryRecoveryStatus` `querySleepOverview` `querySleepHrv` `queryRestingHeartRate` `queryFitnessAssessmentOverview` `querySportRecords` `getActivityDetail` `queryActivityLapData` `queryTrainingSchedule` `queryTrainingPlanDetails` `queryTrainingPlanLibrary` `updateTrainingPlan` `createScheduledWorkout` `queryScheduledWorkoutDetails` `updateScheduledWorkout` `queryUserInfo`

**iGPSPORT**：`get_athlete_profile` `list_activities` `get_activity_summary` `get_activity_laps` `get_activity_streams` `get_athlete_stats` `compare_activities` `estimate_thresholds` `list_segments_collected` `get_segment_detail` `get_segment_rank`

**Intervals.icu**：`get_wellness_data` `get_activities` `get_activity_details` `get_activity_intervals` `get_activity_streams` `get_events` `get_athlete_power_curves`

## 9. 坑位清单

- 越野跑不支持时间目标（只能距离/爬升）；跑步、骑行不支持爬升目标。
- 「等强配速」绝对值不支持，只能用 `%等强阈值配速`（intensityType 3）的区间/百分比。
- 已完成或过去的课程改不了 → 如实告知去 COROS App 操作。
- `createSingleWorkout` 只存库不排期；要落到某天用 `createScheduledWorkout`。
- 第三方平台（如 Strava 来源）的活动明细可能 withheld，此时才回退到设备平台并注明来源。
