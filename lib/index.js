/**
 * dsh-endurance-coach — host half (Cordis plugin) for DeepSeek Harness.
 *
 * The bundle patch inserts this plugin. At load time it registers the bundled
 * `endurance-coach` skill with the DSH skills registry (`ctx.skills`), so the model
 * can load it through the normal `skill` tool and users see it in the skill
 * catalog. No skill body is shipped twice: the plugin reads the `SKILL.md` from
 * `skill/<name>/` on demand and appends a short "Bundled files" index so the
 * model knows which reference, script, or asset to open next.
 *
 * Design constraints:
 *   - No npm runtime dependencies. Only Node.js builtins are imported, and the
 *     frontmatter reader deliberately supports one-line `key: value` entries
 *     only (that is all SKILL.md needs here).
 *   - Every path is resolved from `import.meta.url`, so the bundle is
 *     relocatable (git install, tarball, linked checkout, profile node_modules).
 *   - A missing or malformed skill directory must never crash the host: `apply`
 *     logs a warning and returns without registering a provider.
 *   - The provider is ranked like a bundled skill (600) so a user's own local
 *     skill with the same name can override it.
 */

import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { basename, dirname, isAbsolute, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const PACKAGE_ROOT = dirname(HERE);
const DEFAULT_SKILL_DIR = join(PACKAGE_ROOT, 'skill');
const PROVIDER_NAME = 'dsh-endurance-coach';
const SKILL_FILE = 'SKILL.md';

/**
 * Priority used by the DSH skill registry (lower wins). 600 is the rank of
 * bundled skills in @deepseek-ai/dsh-skill; kept as a local constant so this
 * package stays dependency-free instead of importing the runtime package.
 */
const BUNDLED_SKILL_RANK = 600;

const FRONTMATTER_RE = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/u;
const KEBAB_CASE_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** Directories inside a skill directory worth indexing for the model. */
const BUNDLED_DIRECTORIES = [
  ['references', '参考文档（按需读取）'],
  ['scripts', '确定性计算脚本（python，纯标准库）'],
  ['assets', '模板与示例文件'],
];

/** Human-readable purpose per bundled path; unknown files fall back to the directory note. */
const FILE_PURPOSES = new Map([
  ['references/01-data-sources.md', '数据源口径：每个数字由哪个源负责，哪些数字绝不能相加。取数前先读。'],
  ['references/02-load-readiness.md', '负荷与恢复判断：红黄绿灯、Load Ratio、HRV / 静息心率 / 睡眠口径。'],
  ['references/03-periodization.md', '周期化：阶段判定、滚动两周排课、减量与七项校验。'],
  ['references/04-paces-zones.md', '配速 / 心率 / 功率 / 泳速区间与 VDOT 换算规则。'],
  ['references/05-workouts.md', '课型库与单节课结构规则（热身、主课、拉伸）。'],
  ['references/06-race-execution.md', '赛前 2–4 周减量、分段配速、比赛日执行与赛后恢复。'],
  ['references/07-injury-nutrition.md', '疼痛 / 伤病降级路径与营养、补给计算规则。'],
  ['references/08-output-templates.md', '晨报 / 周计划 / 复盘 / 周摘要的输出版式模板。'],
  ['references/09-weather.md', '天气取数与修正：高温、低温、风、雨雪、空气质量及 courseDescription 写法。'],
  ['scripts/vdot.py', 'VDOT 与训练配速换算（确定性算术，模型只复述结果）。'],
  ['scripts/readiness.py', '恢复三档判定：输入 HRV、静息心率、睡眠、负荷比，输出 PASS / CAUTION / RED。'],
  ['scripts/nutrition.py', '比赛补给与碳水 / 电解质计算。'],
  ['scripts/weather.py', 'Open-Meteo 天气取数与配速修正建议（无需注册，Open-Meteo 公开接口；坐标来自 athlete.json 或参数）。'],
  ['scripts/init_athlete.py', '首次配置：从模板生成 coach/athlete.json 与 coach/decisions.log.md。'],
  ['assets/athlete.example.json', '运动员档案模板，init_athlete.py 据此生成个人 coach/athlete.json。'],
  ['assets/decisions.log.template.md', '决策日志模板，记录每次动态调整的原因与结果。'],
]);

export const name = 'dsh-endurance-coach';
export const inject = ['skills'];

/** Log through the host logger when present; never let logging break apply. */
function log(ctx, level, message) {
  try {
    const logger = ctx?.logger;
    if (logger && typeof logger[level] === 'function') logger[level](message);
  } catch {
    /* logging is best-effort */
  }
}

function errorText(error) {
  return error instanceof Error ? error.message : String(error);
}

/** Convert a native path to the forward-slash form DSH resource paths use. */
function toResourcePath(path) {
  return path.split(sep).join('/');
}

function unquote(value) {
  if (value.length >= 2) {
    const first = value[0];
    const last = value[value.length - 1];
    if ((first === '"' && last === '"') || (first === "'" && last === "'")) return value.slice(1, -1);
  }
  return value;
}

/**
 * Parse a SKILL.md file into frontmatter metadata and the body.
 *
 * Only single-line `key: value` frontmatter entries are supported by design:
 * `name`, `description`, and `whenToUse` are all one line in practice, and the
 * parser must not pull a YAML dependency into the host process. An unsupported
 * entry fails fast with the offending line so packaging mistakes are obvious.
 *
 * @param {string} raw - Full SKILL.md text.
 * @param {string} [label] - Path used in error messages.
 * @returns {{metadata: Record<string, string>, content: string}}
 */
export function parseFrontmatter(raw, label = SKILL_FILE) {
  const text = raw.charCodeAt(0) === 0xfeff ? raw.slice(1) : raw;
  const match = FRONTMATTER_RE.exec(text);
  if (match === null || match[1] === undefined) {
    throw new Error(`[dsh-endurance-coach] ${label} has no YAML frontmatter block`);
  }
  const metadata = {};
  for (const line of match[1].split(/\r?\n/u)) {
    const trimmed = line.trim();
    if (trimmed === '' || trimmed.startsWith('#')) continue;
    if (/^[\s-]/.test(line) || trimmed.startsWith('- ')) {
      throw new Error(`[dsh-endurance-coach] ${label}: only single-line "key: value" frontmatter is supported: ${line}`);
    }
    const separator = trimmed.indexOf(':');
    if (separator <= 0) {
      throw new Error(`[dsh-endurance-coach] ${label}: unsupported frontmatter line: ${line}`);
    }
    const key = trimmed.slice(0, separator).trim();
    if (!/^[A-Za-z][A-Za-z0-9_-]*$/u.test(key)) {
      throw new Error(`[dsh-endurance-coach] ${label}: invalid frontmatter key: ${key}`);
    }
    metadata[key] = unquote(trimmed.slice(separator + 1).trim());
  }
  const description = metadata.description;
  if (typeof description !== 'string' || description.trim() === '') {
    throw new Error(`[dsh-endurance-coach] ${label} has no non-empty description`);
  }
  return {
    metadata,
    content: text.slice(match[0].length).trim(),
  };
}

/**
 * Read one skill directory into a candidate summary plus the parsed body.
 * @param {string} skillDirectory - Absolute directory that contains SKILL.md.
 * @param {string} [skillNameFromDirectory] - Directory name used when frontmatter has no name.
 */
export function readSkill(skillDirectory, skillNameFromDirectory = basename(skillDirectory)) {
  const locator = join(skillDirectory, SKILL_FILE);
  const { metadata, content } = parseFrontmatter(readFileSync(locator, 'utf8'), locator);
  const skillName = metadata.name ?? skillNameFromDirectory;
  if (typeof metadata.name === 'string' && metadata.name !== '' && metadata.name !== skillNameFromDirectory) {
    throw new Error(
      `[dsh-endurance-coach] ${locator}: frontmatter name "${metadata.name}" does not match directory name "${skillNameFromDirectory}"`,
    );
  }
  return {
    skillName,
    description: metadata.description,
    whenToUse: metadata.whenToUse,
    directory: skillDirectory,
    locator,
    content,
  };
}

/**
 * Discover every skill inside a bundle skill directory.
 *
 * Throws only when the skill directory itself is unusable; a child directory
 * without SKILL.md is reported through `onWarn` and skipped so one stray folder
 * cannot take down the provider.
 *
 * @param {string} skillDirectory - Directory that holds one subdirectory per skill.
 * @param {{onWarn?: (message: string) => void}} [options]
 */
export function discoverSkills(skillDirectory, options = {}) {
  if (!existsSync(skillDirectory)) {
    throw new Error(`[dsh-endurance-coach] skill directory not found: ${skillDirectory}`);
  }
  if (!statSync(skillDirectory).isDirectory()) {
    throw new Error(`[dsh-endurance-coach] skill path is not a directory: ${skillDirectory}`);
  }
  const onWarn = typeof options.onWarn === 'function' ? options.onWarn : () => {};
  const skills = [];
  const entries = readdirSync(skillDirectory, { withFileTypes: true }).sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const directory = join(skillDirectory, entry.name);
    if (!existsSync(join(directory, SKILL_FILE))) {
      onWarn(`[dsh-endurance-coach] skipping ${toResourcePath(directory)}: no ${SKILL_FILE}`);
      continue;
    }
    const skill = readSkill(directory, entry.name);
    if (!KEBAB_CASE_RE.test(skill.skillName)) {
      throw new Error(`[dsh-endurance-coach] ${skill.locator}: skill name must be kebab-case, got "${skill.skillName}"`);
    }
    skills.push(skill);
  }
  return skills;
}

/** Build the "## Bundled files" index appended to the loaded skill body. */
export function bundledFilesSection(skillDirectory) {
  const rows = [];
  for (const [directoryName, fallbackPurpose] of BUNDLED_DIRECTORIES) {
    const directory = join(skillDirectory, directoryName);
    if (!existsSync(directory) || !statSync(directory).isDirectory()) continue;
    const files = readdirSync(directory, { withFileTypes: true })
      .filter((entry) => entry.isFile())
      .map((entry) => entry.name)
      .sort();
    for (const file of files) {
      const relativePath = `${directoryName}/${file}`;
      rows.push(`- \`${relativePath}\` — ${FILE_PURPOSES.get(relativePath) ?? fallbackPurpose}`);
    }
  }
  const lines = [
    '',
    '## Bundled files',
    '',
    `本技能的参考文档、脚本与模板位于 \`resourceBase\` 目录：\`${toResourcePath(skillDirectory)}\`。按需读取，不要一次全读；脚本一律用 \`python\` 从该目录运行。以下路径均相对于该目录。`,
    '',
  ];
  if (rows.length === 0) lines.push('- （未找到 references / scripts / assets 下的文件）');
  else lines.push(...rows);
  return `\n${lines.join('\n')}\n`;
}

/** Build the provider object registered with `ctx.skills.registerProvider`. */
export function createProvider(skills) {
  const candidates = new Map(skills.map((skill) => [skill.skillName, skill]));
  return {
    name: PROVIDER_NAME,
    list: () => Promise.resolve(skills.map((skill) => createCandidate(skill))),
    async get(candidate, options = {}) {
      const skill = candidates.get(candidate?.name) ?? skills.find((entry) => entry.skillName === candidate?.name);
      if (skill === undefined) {
        throw new Error(`[dsh-endurance-coach] unknown skill: ${candidate?.name ?? '<missing>'}`);
      }
      const raw = await readFile(skill.locator, { encoding: 'utf8', signal: options.signal });
      const parsed = parseFrontmatter(raw, skill.locator);
      if (parsed.metadata.name !== undefined && parsed.metadata.name !== '' && parsed.metadata.name !== skill.skillName) {
        throw new Error(`[dsh-endurance-coach] ${skill.locator}: skill name changed after discovery`);
      }
      return {
        ...createCandidate(skill),
        content: `${parsed.content}${bundledFilesSection(skill.directory)}`,
      };
    },
  };
}

function createCandidate(skill) {
  return {
    name: skill.skillName,
    description: skill.description,
    invocation: {
      modelInvocable: true,
      userInvocable: true,
    },
    provider: PROVIDER_NAME,
    source: 'bundled',
    rank: BUNDLED_SKILL_RANK,
    resourceBase: {
      kind: 'directory',
      path: toResourcePath(skill.directory),
    },
    locator: skill.locator,
  };
}

/** Resolve the configured skill directory, defaulting to `<package>/skill`. */
function resolveSkillDirectory(config) {
  const configured = config?.skillDir;
  if (typeof configured === 'string' && configured.trim() !== '') {
    return isAbsolute(configured) ? configured : resolve(PACKAGE_ROOT, configured);
  }
  return DEFAULT_SKILL_DIR;
}

/**
 * Register the bundled skills with the DSH skills registry.
 *
 * @param {object} ctx - Cordis context that must expose `skills.registerProvider`.
 * @param {{skillDir?: string, enabled?: boolean}} [config] - Optional overrides.
 */
export async function apply(ctx, config = {}) {
  if (typeof ctx?.skills?.registerProvider !== 'function') {
    throw new Error('[dsh-endurance-coach] the skills registry is unavailable; the dsh skill service is not mounted');
  }
  if (config.enabled === false) {
    log(ctx, 'info', '[dsh-endurance-coach] disabled by configuration');
    return;
  }

  const skillDirectory = resolveSkillDirectory(config);
  let skills;
  try {
    skills = discoverSkills(skillDirectory, { onWarn: (message) => log(ctx, 'warn', message) });
  } catch (error) {
    log(
      ctx,
      'warn',
      `[dsh-endurance-coach] cannot load the bundled skill (${errorText(error)}); the endurance-coach skill is unavailable`,
    );
    return;
  }
  if (skills.length === 0) {
    log(ctx, 'warn', `[dsh-endurance-coach] no skills found under ${toResourcePath(skillDirectory)}; nothing registered`);
    return;
  }

  const provider = createProvider(skills);
  let dispose;
  try {
    dispose = ctx.skills.registerProvider(() => provider);
  } catch (error) {
    log(ctx, 'warn', `[dsh-endurance-coach] could not register the skill provider (${errorText(error)})`);
    return;
  }
  log(
    ctx,
    'info',
    `[dsh-endurance-coach] registered skill provider "${PROVIDER_NAME}" with ${skills.length} skill(s): ${skills
      .map((skill) => skill.skillName)
      .join(', ')}`,
  );

  if (typeof dispose === 'function') {
    try {
      ctx.effect?.(() => dispose, 'dsh-endurance-coach.skill-provider');
    } catch (error) {
      log(ctx, 'warn', `[dsh-endurance-coach] could not register cleanup (${errorText(error)})`);
      try {
        dispose();
      } catch {
        /* already disposed */
      }
    }
  }
}

export { PROVIDER_NAME, BUNDLED_SKILL_RANK };
