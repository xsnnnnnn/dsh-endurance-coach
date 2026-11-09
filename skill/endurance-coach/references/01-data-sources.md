# 01 · 数据源口径（取数前必读）

> **唯一数据源是 Intervals.icu**（MCP 前缀 `mcp__intervals__`）：活动、分圈、秒级流、综合负荷、生理与恢复、功率曲线、训练计划日历事件，全部从这里取。
> 只有一个源，所以**不存在跨源相加**：不把其它平台的数据加进来，也不用其它平台的数据补差、对账或回退。
> 若 Intervals.icu MCP 没装或不可用，对应数据按「未取到」处理，改用用户手动提供的数据（标注「手动」）。

## 1. 一个源管全部

| 想知道 | 工具 | 说明 |
|---|---|---|
| 活动/课次（跑步、越野、骑行、游泳）：距离、时间、均速、HR、训练负荷 | `get_activities` → `get_activity_details` | 先按日期范围定位，再取单次汇总 |
| 分圈 / 区间：GAP、步频、功率、W' | `get_activity_intervals` | 需要逐秒才 `get_activity_streams`（数据量大，慎用） |
| 综合负荷：CTL / ATL / TSB / rampRate | `get_wellness_data` | TSB = CTL − ATL；官方 Load Ratio 优先 |
| 生理与恢复：静息心率、HRV、睡眠在床时长、体重、步数、eFTP | `get_wellness_data` | `sleepSecs` 是在床口径（见第 5 节） |
| 功率 / 阈值：功率曲线、eFTP | `get_athlete_power_curves` + `get_wellness_data` 的 eFTP | 阈值以 eFTP / 功率曲线为准 |
| 训练计划：读 | `get_events` | 只反映 Intervals.icu 日历里的既有安排 |
| 训练计划：写 / 改 | `add_or_update_event`（结构化 `workout_doc`） | **写前必须说明并等用户确认** |
| 训练计划：删 | `delete_event` | 破坏性操作，**二次确认** |
| 天气 | `<this skill>/scripts/weather.py`（Open-Meteo） | 与训练数据源无关，无需注册 |

## 2. 取数顺序（活动）

1. `get_activities`：按日期范围定位活动（跑步、越野、骑行、游泳）。
2. `get_activity_details`：单次汇总（距离、时间、HR、训练负荷等）。
3. `get_activity_intervals`：分圈 / 区间（GAP、步频、功率、W'）。
4. 只有需要逐秒分析时才 `get_activity_streams`（秒级流，注意上下文消耗）。

生理与负荷一次 `get_wellness_data` 读回 `ctl` / `atl` / `rampRate` / `eFTP` / `restingHR` / HRV / `sleepSecs` / `weight` / `steps`；功率曲线用 `get_athlete_power_curves`。

## 3. 单一来源纪律

1. **同一活动、同一指标只认 Intervals.icu**：不把其它平台的数据加进来，也不用其它平台的数据补缺或对账。
2. **不推断、不填默认值、不编造数字**：取不到就写「X 数据未取到」。
3. 允许相加的只有「不同运动的总距离」（跑步 + 骑行），且都来自 Intervals.icu，必须分别标注。

## 4. 计划读写（Intervals.icu 日历事件）

- **读**：`get_events` 看已有安排；返回空就如实说「日历里暂无安排」，不要推断用户是不是在别处记了计划。
- **写 / 改**：`add_or_update_event`，`workout_doc` 传结构化 steps（warmup / 主课 / cooldown 分开），事件描述写清拉伸内容与天气替代方案。**写入前必须先说明改哪几天、改成什么，等用户确认后再写**。
- **删**：`delete_event` 属于破坏性操作，**二次确认**后才能执行。
- **复查**：写完用 `get_events` 读回改动日期，确认事件与课表一致。
- **ID 保密**：事件 ID / 活动 ID 只是内部句柄，**不向用户展示**。
- 已过去或已完成的日期不要擅自改动；需要改时先说明，由用户在 Intervals.icu 里确认。

## 5. 睡眠口径（容易错）

- `get_wellness_data` 的 `sleepSecs` 是**在床时长（含清醒）**，不是睡着时长；输出必须标注「在床」。
- Intervals.icu **没有睡眠评分 / 恢复分**：取不到就不写、不猜、不用别的源补。
- `readiness.py` 的 `--sleep-hours` 用 `sleepSecs ÷ 3600`（在床近似口径，阈值判断会比睡着时长得宽松）；`--sleep-score` 取不到就**不传这个参数**（脚本支持缺省，缺失不参与表决）。

## 6. 取数决策树

```
读写计划？       ── 读 → get_events
                     写/改 → 说明 + 等确认 → add_or_update_event → get_events 复查
                     删 → 二次确认 → delete_event
今天能不能练？   ── → get_wellness_data + get_activities + get_events
复盘某次活动？   ── → get_activities → get_activity_details → get_activity_intervals
                     （需要逐秒才 get_activity_streams）
综合负荷？       ── → get_wellness_data（ctl / atl / rampRate）
睡眠？           ── → get_wellness_data 的 sleepSecs（在床口径，无评分）
功率 / 阈值？     ── → get_athlete_power_curves / eFTP
天气？           ── → weather.py（Open-Meteo）
```

## 7. 写入边界

| 操作 | 工具 | 规则 |
|---|---|---|
| 读活动 / 负荷 / 生理 / 功率 / 计划 | `get_*` | 随时可读 |
| 写 / 改计划事件 | `add_or_update_event` | 先说明改动并等用户确认 |
| 删计划事件 | `delete_event` | 破坏性，二次确认 |
| 加备注 / 活动留言 | `add_or_update_note` / `add_activity_message` | 先说明，等确认 |
| 其它写操作（custom items 增删改等） | 对应工具 | 先说明，等确认 |

> 默认只读；任何写操作都要先说清楚写什么、写到哪天，得到用户明确同意后再执行。

## 8. 降级与缺口（没有第二数据源）

- Intervals.icu 不可用 → 对应数据如实写「数据未取到」，**不回退到别的平台**。
- 用户可手动贴数据 → 采用并标注「手动」，不让模型猜。
- 单个工具失败 → 跳过，末尾一行「X 数据未取到」。
- 全部生理数据缺失 → 必须明说「无生理数据，未做状态判定」，**不得输出「状态良好」**。

## 9. 工具速查

**Intervals.icu（唯一数据源）**：
- 活动：`get_activities` `get_activity_details` `get_activity_intervals` `get_activity_streams`
- 负荷 / 生理：`get_wellness_data`
- 功率：`get_athlete_power_curves`
- 计划：`get_events` `add_or_update_event` `delete_event`
- 备注：`add_or_update_note` `add_activity_message`

**天气**：`<this skill>/scripts/weather.py`（Open-Meteo，无需注册）

## 10. 坑位清单

- `sleepSecs` 是在床口径，不要当睡着时长写进晨报。
- `get_events` 为空只说明 ICU 日历里没安排，不代表用户没有计划；如实说，不要推断。
- 写事件前一定先读 `get_events`，避免同一天重复创建；改已有事件用 `add_or_update_event`，不要新建一个。
- 事件 ID / 活动 ID 不展示给用户。
- `get_activity_streams` 数据量大，只在需要逐秒分析时取。
- 第三方平台（如 Strava 来源）的活动明细可能 withheld，此时如实说「明细未取到」。
- 已过去 / 已完成的日期不擅自改；提示用户在 Intervals.icu 里操作。
- 同一指标只有一个源：不存在「用另一个源核对」这种动作。
