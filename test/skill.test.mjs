import assert from 'node:assert/strict';
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import { parseFrontmatter } from '../lib/index.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const PACKAGE_ROOT = dirname(HERE);
const SKILL_DIR = join(PACKAGE_ROOT, 'skill', 'endurance-coach');
const SKILL_MD = join(SKILL_DIR, 'SKILL.md');
const REFERENCES = [
  '01-data-sources.md',
  '02-load-readiness.md',
  '03-periodization.md',
  '04-paces-zones.md',
  '05-workouts.md',
  '06-race-execution.md',
  '07-injury-nutrition.md',
  '08-output-templates.md',
  '09-weather.md',
];
const SCRIPTS = ['vdot.py', 'readiness.py', 'nutrition.py', 'weather.py', 'init_athlete.py'];
const ASSETS = ['athlete.example.json', 'decisions.log.template.md'];

/** Generic hygiene checks: the published skill must not carry machine paths, credentials, or private workspace wiring. */
const ABSOLUTE_PATH_RE = /(?:[A-Za-z]:\\|\/Users\/|\/home\/)/u;
const CREDENTIAL_RE = /password|secret|token|api[_-]?key/iu;
const PRIVATE_WORKSPACE_REFS = ['coach/AGENTS.md', 'coach/RULES.md', '.dsh/skills'];

/**
 * The published bundle must be Intervals.icu-only. These names are assembled at
 * runtime on purpose: this test file is inside the package under test, so a
 * literal would make the very scan it defines fail.
 */
const BANNED_SOURCE_RE = new RegExp(
  [
    ['C', 'O', 'R', 'O', 'S'].join(''),
    ['i', 'G', 'P', 'S', 'P', 'O', 'R', 'T'].join(''),
    ['高', '驰'].join(''),
  ].join('|'),
  'iu',
);

const SKIPPED_DIRECTORIES = new Set(['.git', 'node_modules']);

function walkFiles(directory) {
  const files = [];
  if (!existsSync(directory)) return files;
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    if (entry.name.startsWith('.fixture-') || SKIPPED_DIRECTORIES.has(entry.name)) continue;
    const full = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...walkFiles(full));
    else if (entry.isFile()) files.push(full);
  }
  return files;
}

function readSkill() {
  assert.ok(existsSync(SKILL_MD), 'skill/endurance-coach/SKILL.md must exist');
  return readFileSync(SKILL_MD, 'utf8');
}

test('SKILL.md frontmatter is valid and identifies the skill', () => {
  const raw = readSkill();
  const { metadata, content } = parseFrontmatter(raw, SKILL_MD);
  assert.equal(metadata.name, 'endurance-coach');
  assert.equal(typeof metadata.description, 'string');
  assert.ok(metadata.description.trim().length > 20, 'description must be meaningful');
  if (metadata.whenToUse !== undefined) assert.ok(metadata.whenToUse.trim().length > 0);
  assert.ok(content.length > 2000, 'skill body must be substantial');
  assert.ok(!content.startsWith('---'), 'body must not repeat the frontmatter');
});

test('SKILL.md keeps the decision axioms, workflows W1-W5, guardrails, and references index', () => {
  const raw = readSkill();
  for (const required of ['决策公理', 'W1', 'W2', 'W3', 'W4', 'W5', 'references/', '九条', '能力边界', '方法论']) {
    assert.ok(raw.includes(required), `SKILL.md must keep section or term: ${required}`);
  }
  assert.ok(/Setup|首次|初始化/u.test(raw), 'SKILL.md must document first-time setup');
  assert.ok(raw.includes('ENDURANCE_COACH_DIR'));
  assert.ok(raw.includes('init_athlete.py'));
  assert.ok(raw.includes('coach/athlete.json'));
});

test('all nine reference files exist and are indexed by SKILL.md', () => {
  const raw = readSkill();
  for (const filename of REFERENCES) {
    const path = join(SKILL_DIR, 'references', filename);
    assert.ok(existsSync(path), `missing reference: ${filename}`);
    assert.ok(statSync(path).size > 0, `empty reference: ${filename}`);
    assert.ok(raw.includes(`references/${filename}`), `SKILL.md index is missing references/${filename}`);
  }
});

test('every references/... path mentioned in SKILL.md exists', () => {
  const raw = readSkill();
  const mentioned = new Set(raw.match(/references\/[A-Za-z0-9._-]+\.md/gu) ?? []);
  assert.ok(mentioned.size >= REFERENCES.length);
  for (const path of mentioned) {
    assert.ok(existsSync(join(SKILL_DIR, path)), `dangling reference in SKILL.md: ${path}`);
  }
});

test('every scripts/... path mentioned in SKILL.md exists', () => {
  const raw = readSkill();
  for (const filename of SCRIPTS) {
    assert.ok(existsSync(join(SKILL_DIR, 'scripts', filename)), `missing script: ${filename}`);
  }
  const mentioned = new Set(raw.match(/scripts\/[A-Za-z0-9._-]+\.py/gu) ?? []);
  for (const path of mentioned) {
    assert.ok(existsSync(join(SKILL_DIR, path)), `dangling script path in SKILL.md: ${path}`);
  }
});

test('bundled python scripts are standard-library only and offer --help', () => {
  for (const filename of SCRIPTS) {
    const path = join(SKILL_DIR, 'scripts', filename);
    assert.ok(statSync(path).size > 0, `empty script: ${filename}`);
    const source = readFileSync(path, 'utf8');
    assert.ok(/--help|argparse/u.test(source), `${filename} must support --help`);
    assert.ok(!/^import (requests|numpy|pandas|yaml|httpx)\b/mu.test(source), `${filename} must not import third-party packages`);
    assert.ok(!ABSOLUTE_PATH_RE.test(source), `${filename} must not contain absolute machine paths`);
  }
});

test('bundled assets include a valid athlete template and a decision-log template', () => {
  for (const filename of ASSETS) {
    const path = join(SKILL_DIR, 'assets', filename);
    assert.ok(existsSync(path), `missing asset: ${filename}`);
    assert.ok(statSync(path).size > 0, `empty asset: ${filename}`);
  }
  const athlete = JSON.parse(readFileSync(join(SKILL_DIR, 'assets', 'athlete.example.json'), 'utf8'));
  assert.equal(typeof athlete, 'object');
  assert.ok(Object.keys(athlete).length > 0);
  // The template must be self-evidently fictional, never real user data.
  assert.equal(athlete.example, true, 'athlete template must be marked "example": true');
  assert.ok(JSON.stringify(athlete).includes('虚构'), 'athlete template must state that its values are fictional');
  const exampleDates = [
    ...(athlete.races ?? []).map((race) => race.date),
    ...(athlete.pending_tests ?? []).map((entry) => entry.date),
    ...(athlete.weather_policy?.venues ?? []).map((venue) => venue.date),
  ].filter((date) => typeof date === 'string');
  assert.ok(exampleDates.length >= 3, 'athlete template must contain example race / test / venue dates');
  for (const date of exampleDates) {
    assert.match(date, /^\d{4}-\d{2}-\d{2}$/u, `example date must be ISO: ${date}`);
    assert.ok(Number(date.slice(0, 4)) >= 2026, `example date must not reuse older real dates: ${date}`);
  }
});

test('ICU-only contract: Intervals.icu is the single data source and the only plan surface', () => {
  const raw = readSkill();
  const sources = readFileSync(join(SKILL_DIR, 'references', '01-data-sources.md'), 'utf8');

  // SKILL.md positions Intervals.icu as the one and only data source.
  assert.ok(raw.includes('默认数据源 Intervals.icu'), 'SKILL.md description must name Intervals.icu as the default data source');
  assert.ok(raw.includes('唯一数据源'), 'SKILL.md must state that Intervals.icu is the single data source');
  assert.ok(sources.includes('唯一数据源'), '01-data-sources.md must state the single-source rule');

  // The activity / load / recovery chain stays on mcp__intervals__.
  for (const tool of [
    'mcp__intervals__',
    'get_activities',
    'get_activity_details',
    'get_activity_intervals',
    'get_wellness_data',
    'get_athlete_power_curves',
  ]) {
    assert.ok(sources.includes(tool), `01-data-sources.md must document ${tool}`);
  }

  // Plans are Intervals.icu calendar events: read, write/update, delete, confirmed first.
  for (const tool of ['get_events', 'add_or_update_event', 'delete_event']) {
    assert.ok(raw.includes(tool), `SKILL.md must document the plan tool ${tool}`);
    assert.ok(sources.includes(tool), `01-data-sources.md must document the plan tool ${tool}`);
  }
  assert.ok(raw.includes('确认'), 'SKILL.md must require user confirmation before plan writes');
  assert.ok(sources.includes('确认'), '01-data-sources.md must spell out the write-confirmation boundary');
  assert.ok(raw.includes('已同步到 Intervals.icu 日历'), 'SKILL.md must report plan sync as "已同步到 Intervals.icu 日历"');

  // Sleep is time-in-bed only; there is no sleep score or recovery score to fill in.
  assert.ok(raw.includes('在床'), 'SKILL.md must document the time-in-bed sleep convention');
  assert.ok(sources.includes('在床'), '01-data-sources.md must document the time-in-bed sleep convention');
  assert.ok(sources.includes('--sleep-score'), '01-data-sources.md must explain the missing --sleep-score parameter');
  assert.ok(sources.includes('不传'), '01-data-sources.md must say --sleep-score is omitted when unavailable');
});

test('the published bundle never mentions another training-data platform', () => {
  const offenders = [];
  for (const path of walkFiles(PACKAGE_ROOT)) {
    if (path.endsWith('.png')) continue;
    const match = BANNED_SOURCE_RE.exec(readFileSync(path, 'utf8'));
    if (match !== null) offenders.push(`${relative(PACKAGE_ROOT, path)}: ${match[0]}`);
  }
  assert.deepEqual(offenders, [], `no other training-data platform may be mentioned: ${offenders.join(', ')}`);
});

test('the athlete template uses the neutral fitness_baseline field name', () => {
  const template = readFileSync(join(SKILL_DIR, 'assets', 'athlete.example.json'), 'utf8');
  assert.ok(template.includes('"fitness_baseline"'), 'athlete template must use fitness_baseline');
  assert.ok(!template.includes(['c', 'o', 'r', 'o', 's'].join('') + '_baseline'), 'athlete template must not keep the old vendor-named field');
});

test('the skill tree passes generic publication hygiene checks', () => {
  const files = walkFiles(SKILL_DIR);
  assert.ok(files.length >= 15, `expected the full skill tree, found ${files.length} files`);
  for (const path of files) {
    const text = readFileSync(path, 'utf8');
    assert.ok(!ABSOLUTE_PATH_RE.test(text), `${path} contains an absolute machine path`);
    for (const reference of PRIVATE_WORKSPACE_REFS) {
      assert.ok(!text.includes(reference), `${path} references a private workspace file: ${reference}`);
    }
    if (/\.(?:md|json|md\.template)$/u.test(path)) {
      assert.ok(!CREDENTIAL_RE.test(text), `${path} contains a credential-like word`);
    }
  }
});
