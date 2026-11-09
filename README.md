# dsh-endurance-coach

**Endurance Coach (耐力教练)** — an endurance-coaching skill for [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness), packaged as an installable DSH skill-provider bundle.

It reads **all** training data from **Intervals.icu** (activities, intervals, streams, training load, and wellness such as resting HR, HRV, sleep time-in-bed, eFTP, and power curves), and it uses the Intervals.icu calendar as the training-plan surface: existing sessions are read with `get_events`, and new or adjusted sessions are written back as calendar events with `add_or_update_event` — always described and confirmed with you first. The result is concrete training decisions: whether to train today, what the week should look like, how a session went, how to prepare for a race, and when to re-evaluate fitness. The skill files ship with the package; the plugin registers the skill with DSH's skill registry so the model and the user can load it like any built-in skill.

- Package: `dsh-endurance-coach` (DSH plugin bundle, skill provider)
- Skill name: `endurance-coach`
- License: MIT
- No personal data is bundled. Your athlete profile lives in **your** workspace.

## Install

Requires DeepSeek Harness `>= 0.2.1-rc.1` and Node.js `>= 20`.

```bash
dsh plugin --profile desktop add 'github:xsnnnnnn/dsh-endurance-coach'
```

Restart DSH (or reload the profile) after installation. The `endurance-coach` skill then appears in the skill catalog, and the model can load it through the normal `skill` tool.

Verify the bundle is mounted:

```bash
dsh --profile desktop --dump-config    # look for an entry id "dsh-endurance-coach"
dsh plugin --profile desktop list      # the dependency dsh-endurance-coach is listed
```

Uninstall:

```bash
dsh plugin --profile desktop remove dsh-endurance-coach
```

Installing from a checkout instead of GitHub also works — point `add` at the package directory (pnpm links it):

```bash
dsh plugin --profile desktop add /path/to/dsh-endurance-coach
```

## First-time setup: your athlete profile

The skill deliberately keeps **no athlete data inside itself**. It reads a JSON profile from your workspace and never writes personal numbers back into the package:

```
<your-workspace>/coach/athlete.json     # your thresholds, goals, available days
<your-workspace>/coach/decisions.log.md # running log of plan adjustments
```

Create them from the bundled templates:

1. In your workspace, ask the agent to initialize the coach, or run the script manually. The installed skill directory is usually
   `<DSH_HOME>/profiles/<profile>/node_modules/dsh-endurance-coach/skill/endurance-coach`:

   ```bash
   cd /path/to/your-workspace
   python <skill-dir>/scripts/init_athlete.py
   ```

2. Edit `coach/athlete.json` with your real numbers (thresholds, goals, weekly availability). Every example value in the template is fictional and must be replaced.
3. Set `ENDURANCE_COACH_DIR=/absolute/path` if you want the coach files somewhere other than `<workspace>/coach`.

`init_athlete.py` refuses to overwrite existing files unless you pass `--force`.

> Tip: check in the resulting files privately. They contain your training data — do not publish them.

## Dependencies

The bundle itself has **zero npm runtime dependencies**; it requires DeepSeek Harness `>= 0.2.1-rc.1` and Node.js `>= 20` (see [Install](#install)). The only required data source is Intervals.icu:

| Component | Need | Notes |
|---|---|---|
| Intervals.icu (the only data source) | Intervals.icu MCP server (`mcp__intervals__`) | Activities, intervals, streams, training load (CTL/ATL/TSB/rampRate), wellness (resting HR, HRV, sleep time-in-bed, eFTP), power curves, and training-plan calendar events (`get_events` to read, `add_or_update_event` to write/update, `delete_event` to delete). |
| Python | 3.10+ | Only the Python **standard library** is used by the bundled scripts. |
| Weather | Open-Meteo — no account needed | The bundled `weather.py` calls the public Open-Meteo APIs, which need no sign-up. |

If the Intervals.icu MCP server is missing, the skill reports "that data was not available" instead of inventing numbers, and there is no second data source to fall back to. You can also use it with manually supplied numbers only.

## What it does

### Five workflows

| Workflow | When | Output |
|---|---|---|
| **W1 · Today** | "Should I train today?" / morning check | A go / caution / rest decision, today's session with a weather note, one reminder. |
| **W2 · Week** | "Plan my week" / adjust the plan | Rolling two-week schedule with phase, session mix, and weather-aware placements; changes are written back to the Intervals.icu calendar as events after confirmation. |
| **W3 · Review** | "Review that run/ride" / "how was this week" | Completion-based review: what went well, what did not, what changes next. |
| **W4 · Race prep** | 2–4 weeks before a race | Taper curve, segment pacing, fueling plan, heat/humidity correction, recovery week. |
| **W5 · Reassessment** | Every 4 weeks or after a new result | Recalculate VDOT/thresholds; only fully replace zones when the change is meaningful. |

### Non-negotiable guardrails

- **Safety > science > efficiency.** Every suggestion passes the safety gate first.
- **Data first, then words.** Missing data is reported as missing, never guessed.
- **Arithmetic belongs to scripts.** VDOT, pace conversion, readiness flags, fueling, and weather corrections are computed by `scripts/*.py`; the model retells the result.
- **Small changes only.** A single adjustment is at most ±30%, at most two proactive adjustments per week; three red-light days trigger a 20–30% deload week.
- **No medical diagnosis.** Persistent pain, chest tightness, or palpitations mean stop and see a doctor.
- **No internal IDs in answers.** Event IDs, activity IDs, and similar handles stay internal.
- **Warm-up and cooldown on every session**, weather corrections are applied before the session is written, and training plans are read from and written to the Intervals.icu calendar as events — every write (including edits and deletions) is described and confirmed with you first.

## Repository layout

```
dsh-endurance-coach/
├── package.json            # bundle metadata, dsh.bundle.patch, engines
├── cordis.patch.yml        # inserts the dsh-endurance-coach plugin row
├── dsh.plugin.json         # display metadata for the plugin manager
├── lib/index.js            # host plugin: registers the skill with ctx.skills
├── locale/{en,zh}.json     # plugin display title / description
├── assets/icon.png         # original 512×512 icon
├── skill/endurance-coach/    # the skill itself
│   ├── SKILL.md
│   ├── references/         # data sources, readiness, periodization, zones, ...
│   ├── scripts/            # vdot, readiness, nutrition, weather, init_athlete
│   └── assets/             # athlete profile + decision-log templates
├── test/                   # node:test suites (not shipped in the npm tarball)
├── README.md
├── README.zh.md
└── LICENSE
```

## Development

```bash
node --test        # or: npm test
```

In sandboxed environments that deny piped child processes (the Node test runner spawns one process per file), use `npm run test:sandbox` (`node --test --test-isolation=none`) instead.

The tests are offline and dependency-free. They mock the Cordis context, load the real `SKILL.md`, and verify the manifest, patch row, locales, icon, and that the provider exposes exactly one `endurance-coach` candidate with a non-empty description and a `Bundled files` index.

The host plugin API is small and stable:

- `export const name = 'dsh-endurance-coach'` and `export const inject = ['skills']`
- `apply(ctx, config)` discovers `skill/<name>/SKILL.md`, builds a candidate list, and calls `ctx.skills.registerProvider(() => provider)`; the returned disposer is registered through `ctx.effect(...)`.
- Candidates use `rank: 600` (the bundled-skill rank), so a local skill with the same name in your own profile can override this one.
- `config.skillDir` overrides the bundled skill directory (useful for development); a missing or malformed skill directory logs a warning instead of crashing the host.

## Safety and disclaimer

This project is a training-planning aid, **not medical advice**. It is not a substitute for a doctor, physiotherapist, or qualified coach. Stop training and seek professional help for chest pain, fainting, palpitations, or pain that worsens while running. Training data can be wrong or delayed — always sanity-check what the agent reports. Use at your own risk; the authors accept no liability for injury, illness, or lost data. See [LICENSE](LICENSE).

## License and attribution

MIT — Copyright (c) 2026 xsnnnnnn.

The coaching methodology was distilled from ideas in these open-source projects; the implementation and wording here are original, and none of them are runtime dependencies:

| Source | What was borrowed |
|---|---|
| [ai-running-coach](https://github.com/xiaolouJB/ai-running-coach) | three-tier adjustment protocol, VDOT auto-calibration, deterministic arithmetic in scripts |
| [tri-coach](https://github.com/SweetGingerGreen/tri-coach) | generate → review → candidate checklist, safety guardrails |
| [cycling-plan-coach](https://github.com/estruyf/skill-cycling-plan-coach) | rider-type classification, polarized weeks, workout quality checklist |
| [claude-coach](https://github.com/felixrieseberg/claude-coach) | periodization layers, race execution, split reference files |
| [strava-coach](https://github.com/AlvaroLaraFF/strava-coach) | triathlon allocation, combined load, swim metrics |
| [endurance-coaching](https://github.com/MrHadiSatrio/Skills) | periodization theory and zone definitions |

These projects mostly assume Strava APIs; this skill reads Intervals.icu as its only data source (activities, load, recovery, power, and plan calendar events), and accepts manual input when Intervals.icu is unavailable — there is no second data-source fallback.
