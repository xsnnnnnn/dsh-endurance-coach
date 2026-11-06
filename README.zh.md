# dsh-endurance-coach

**耐力教练** —— 给 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 用的耐力训练决策技能（skill），打包成可安装的 DSH skill-provider bundle。

它把 COROS、iGPSPORT、Intervals.icu 的训练数据转成具体决策：今天练不练、这一周怎么排、某次跑步/骑行复盘、赛前怎么准备、什么时候重新评估能力。技能文件随包分发；插件把它注册进 DSH 的技能注册表，模型和用户都能像内置技能一样加载。

- 包名：`dsh-endurance-coach`（DSH 插件 bundle，技能提供方）
- 技能名：`endurance-coach`
- 许可证：MIT
- 包里**不含任何个人数据**；运动员档案放在**你自己的 workspace**。

## 安装

需要 DeepSeek Harness `>= 0.2.1-rc.1` 和 Node.js `>= 20`。

```bash
dsh plugin --profile desktop add 'github:xsnnnnnn/dsh-endurance-coach'
```

安装后重启 DSH（或重新加载 profile），`endurance-coach` 技能就会出现在技能目录里，模型可通过 `skill` 工具加载。

确认 bundle 已挂载：

```bash
dsh --profile desktop --dump-config    # 找到 id 为 dsh-endurance-coach 的条目
dsh plugin --profile desktop list      # 依赖列表里出现 dsh-endurance-coach
```

卸载：

```bash
dsh plugin --profile desktop remove dsh-endurance-coach
```

也可以从本地 checkout 安装（pnpm 会以链接方式接入）：

```bash
dsh plugin --profile desktop add /path/to/dsh-endurance-coach
```

## 首次配置：运动员档案

技能**不保存个人数据**。它从 workspace 读取 JSON 档案，也绝不把个人数字写回安装包：

```
<你的 workspace>/coach/athlete.json     # 阈值、目标、每周可用时间
<你的 workspace>/coach/decisions.log.md # 计划调整日志
```

用随包模板生成：

1. 在 workspace 里让 agent 初始化耐力教练，或手动运行。已安装的技能目录通常在
   `<DSH_HOME>/profiles/<profile>/node_modules/dsh-endurance-coach/skill/endurance-coach`：

   ```bash
   cd /path/to/your-workspace
   python <skill-dir>/scripts/init_athlete.py
   ```

2. 编辑 `coach/athlete.json` 填真实数据（阈值、赛事目标、每周可训练天数）。模板里的示例值全部是虚构的，必须替换。
3. 如果想把教练文件放在 `<workspace>/coach` 以外，设置环境变量 `ENDURANCE_COACH_DIR=/absolute/path`。

`init_athlete.py` 默认拒绝覆盖已有文件，确认要覆盖时才能加 `--force`。

> 提示：生成的文件请私有保存——里面是你的训练数据，不要公开。

## 依赖

| 组件 | 要求 | 说明 |
|---|---|---|
| DeepSeek Harness | `>= 0.2.1-rc.1` | bundle 声明 `dsh.bundle.patch`；插件需要 `skills` 服务。 |
| Node.js | `>= 20` | 宿主插件运行时。bundle 自身**零 npm 运行时依赖**。 |
| Python | 3.10+ | 随包脚本只使用 **标准库**。 |
| COROS 数据（推荐） | [`dsh-coros`](https://github.com/xsnnnnnn/dsh-coros) 插件 | 提供技能要用的 COROS MCP 工具（跑步、计划、睡眠）。 |
| iGPSPORT（可选） | MCP server | 骑行明细与功率数据。 |
| Intervals.icu（可选） | MCP server | 综合负荷（CTL/ATL/TSB）。 |
| 天气 | 无 | 自带 `weather.py` 走 Open-Meteo，无需注册或登录。 |

推荐的配套安装命令：

```bash
dsh plugin --profile desktop add 'github:xsnnnnnn/dsh-coros'
```

数据源缺失时，技能应明确说「该数据未取到」，而不是编数字。只用人工输入的数字也可以。

## 它能做什么

### 五种工作流

| 工作流 | 触发场景 | 产出 |
|---|---|---|
| **W1 · 今日判断** | 「今天能不能练」「今天练什么」/ 晨报 | 可练 / 谨慎 / 休息三档结论、今日课表 + 天气提示、一条提醒。 |
| **W2 · 周计划** | 「排一下这周」/ 调整课表 | 滚动两周排课：阶段、课型配比、结合天气的落位。 |
| **W3 · 复盘** | 「复盘这次跑步/骑行」「这周怎么样」 | 以完成度为标准的复盘：做得好、差在哪、下次怎么改。 |
| **W4 · 赛前 2–4 周** | 备赛 | 减量曲线、分段配速、补给计划、湿热修正、赛后恢复周。 |
| **W5 · 周期重评** | 每 4 周或出现新成绩 | 重算 VDOT / 阈值；变化足够大才全量替换区间。 |

### 硬性护栏

- **安全 > 科学 > 效率**：所有建议先过安全闸。
- **先取数，再说话**：取不到就写「未取到」，绝不编造。
- **算术交给脚本**：VDOT、配速换算、恢复判定、补给量、天气修正由 `scripts/*.py` 计算，模型只复述结果。
- **只做小调整**：单次调整 ≤ ±30%，每周最多主动调整 2 次；连续 3 天红灯则整周减量 20–30%。
- **不做医疗诊断**：持续疼痛、胸闷、心悸 → 停练并建议就医。
- **不向用户展示内部 ID**：Plan ID / Workout ID 等只留在内部。
- **每节课都有热身与放松**；写课前先做天气修正；训练计划只写入 COROS。

## 仓库结构

```
dsh-endurance-coach/
├── package.json            # bundle 元数据、dsh.bundle.patch、engines
├── cordis.patch.yml        # 插入 dsh-endurance-coach 插件行
├── dsh.plugin.json         # 插件管理器的展示元数据
├── lib/index.js            # 宿主插件：用 ctx.skills 注册技能
├── locale/{en,zh}.json     # 插件展示标题 / 描述
├── assets/icon.png         # 原创 512×512 图标
├── skill/endurance-coach/    # 技能本体
│   ├── SKILL.md
│   ├── references/         # 数据源、恢复、周期化、区间……
│   ├── scripts/            # vdot、readiness、nutrition、weather、init_athlete
│   └── assets/             # 运动员档案与决策日志模板
├── test/                   # node:test 测试（不进入 npm tarball）
├── README.md
├── README.zh.md
└── LICENSE
```

## 开发与测试

```bash
node --test        # 或 npm test
```

在禁止管道子进程的沙箱环境里（Node 测试运行器会为每个测试文件 spawn 一个进程），改用 `npm run test:sandbox`（即 `node --test --test-isolation=none`）。

测试完全离线、零依赖：mock Cordis context，读取真实 `SKILL.md`，校验 manifest、patch 行、locale、图标，并断言 provider 恰好暴露 1 个 `endurance-coach` 候选、description 非空、加载内容带 `Bundled files` 索引。

宿主插件 API 很小且稳定：

- `export const name = 'dsh-endurance-coach'` 与 `export const inject = ['skills']`
- `apply(ctx, config)` 扫描 `skill/<name>/SKILL.md`，构建候选列表，调用 `ctx.skills.registerProvider(() => provider)`；返回的 disposer 通过 `ctx.effect(...)` 注册清理。
- 候选使用 `rank: 600`（bundled 技能优先级），因此用户自己 profile 里的同名本地技能可以覆盖它。
- `config.skillDir` 可覆盖技能目录（开发用）；目录缺失或损坏时只记 warning，不弄崩宿主。

## 安全免责声明

本项目是训练规划辅助工具，**不是医疗建议**，不能替代医生、康复师或持证教练。出现胸痛、晕厥、心悸，或跑步时加重的疼痛，请停止训练并就医。训练数据可能错误或延迟——对 agent 给出的数字要自己复核。使用风险自负；作者不对伤病、疾病或数据丢失承担责任。详见 [LICENSE](LICENSE)。

## 许可与方法论来源

MIT —— Copyright (c) 2026 xsnnnnnn。

训练方法论蒸馏自以下开源项目的思路；本项目的实现与文案为原创，它们都不是运行时依赖：

| 来源 | 借鉴内容 |
|---|---|
| [ai-running-coach](https://github.com/xiaolouJB/ai-running-coach) | 三档调整协议、VDOT 自动校准、确定性算术交脚本 |
| [tri-coach](https://github.com/SweetGingerGreen/tri-coach) | 生成 → 评审 → 候选清单、安全护栏 |
| [cycling-plan-coach](https://github.com/estruyf/skill-cycling-plan-coach) | 骑手类型判定、极化周、课表质量校验清单 |
| [claude-coach](https://github.com/felixrieseberg/claude-coach) | 周期化分层、赛事执行、reference 分文件结构 |
| [strava-coach](https://github.com/AlvaroLaraFF/strava-coach) | 三项分配、合并负荷、游泳指标 |
| [endurance-coaching](https://github.com/MrHadiSatrio/Skills) | 周期化理论与区间定义 |

这些项目多数默认依赖 Strava API；本技能刻意改读 COROS / iGPSPORT / Intervals.icu / 手动输入。
