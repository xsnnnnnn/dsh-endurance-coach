import assert from 'node:assert/strict';
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, isAbsolute, join, normalize, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import { apply, inject, name } from '../lib/index.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const PACKAGE_ROOT = dirname(HERE);
const SKILL_DIR = join(PACKAGE_ROOT, 'skill');
const SKILL_MD = join(SKILL_DIR, 'endurance-coach', 'SKILL.md');

/** Generic hygiene checks: the published skill must not carry machine paths, credentials, or private workspace wiring. */
const ABSOLUTE_PATH_RE = /(?:[A-Za-z]:\\|\/Users\/|\/home\/)/u;
const CREDENTIAL_RE = /password|secret|token|api[_-]?key/iu;
const PRIVATE_WORKSPACE_REFS = ['coach/AGENTS.md', 'coach/RULES.md', '.dsh/skills'];

function createMockContext() {
  const state = {
    factories: [],
    effects: [],
    disposers: [],
    disposed: 0,
    logs: [],
  };
  const ctx = {
    skills: {
      registerProvider(factory) {
        state.factories.push(factory);
        const dispose = () => {
          state.disposed += 1;
        };
        state.disposers.push(dispose);
        return dispose;
      },
    },
    logger: {
      info(message) {
        state.logs.push({ level: 'info', message });
      },
      warn(message) {
        state.logs.push({ level: 'warn', message });
      },
    },
    effect(callback, label) {
      const disposer = callback();
      state.effects.push({ label, disposer });
      return disposer;
    },
  };
  return { ctx, state };
}

function makeFixtureSkill() {
  const root = mkdtempSync(join(HERE, '.fixture-'));
  const skill = join(root, 'fixture-skill');
  mkdirSync(join(skill, 'references'), { recursive: true });
  mkdirSync(join(skill, 'scripts'), { recursive: true });
  writeFileSync(
    join(skill, 'SKILL.md'),
    ['---', 'name: fixture-skill', 'description: A fixture skill used by the unit tests.', '---', '', '# Fixture', '', 'Body.'].join('\n'),
  );
  writeFileSync(join(skill, 'references', '01-note.md'), '# note\n');
  writeFileSync(join(skill, 'scripts', 'thing.py'), 'print("hi")\n');
  return { root, skill };
}

test('plugin identity and injection', () => {
  assert.equal(name, 'dsh-endurance-coach');
  assert.deepEqual(inject, ['skills']);
});

test('apply registers one provider that exposes the bundled endurance-coach skill', async (t) => {
  if (!existsSync(SKILL_MD)) {
    t.skip('skill/endurance-coach/SKILL.md is not written yet (content task in progress)');
    return;
  }
  const { ctx, state } = createMockContext();
  await apply(ctx);

  assert.equal(state.factories.length, 1, 'registerProvider must be called exactly once');
  const provider = state.factories[0]();
  assert.equal(provider.name, 'dsh-endurance-coach');

  const list = await provider.list();
  assert.equal(list.length, 1);
  const [candidate] = list;
  assert.equal(candidate.name, 'endurance-coach');
  assert.equal(typeof candidate.description, 'string');
  assert.ok(candidate.description.trim().length > 20, 'description must be meaningful');
  assert.deepEqual(candidate.invocation, { modelInvocable: true, userInvocable: true });
  assert.equal(candidate.provider, 'dsh-endurance-coach');
  assert.equal(candidate.source, 'bundled');
  assert.equal(candidate.rank, 600);
  assert.equal(candidate.resourceBase.kind, 'directory');
  assert.ok(!candidate.resourceBase.path.includes('\\'), 'resourceBase.path must use forward slashes');
  assert.ok(existsSync(candidate.resourceBase.path), 'resourceBase.path must exist');
  assert.ok(isAbsolute(candidate.locator), 'locator must be absolute');
  assert.ok(candidate.locator.endsWith(`${sep}SKILL.md`) || candidate.locator.endsWith('/SKILL.md'));
  assert.equal(normalize(dirname(candidate.locator)), normalize(candidate.resourceBase.path));

  const definition = await provider.get(candidate, {});
  assert.equal(definition.name, 'endurance-coach');
  assert.equal(definition.description, candidate.description);
  assert.equal(typeof definition.content, 'string');
  assert.ok(definition.content.length > 2000, 'loaded skill body must be substantial');
  assert.ok(!definition.content.startsWith('---'), 'loaded content must not include frontmatter');
  for (const heading of ['决策公理', 'W1', 'W2', 'W3', 'W4', 'W5', 'references/']) {
    assert.ok(definition.content.includes(heading), `loaded content must mention ${heading}`);
  }
  assert.ok(definition.content.includes('Intervals.icu'), 'loaded content must name Intervals.icu');
  for (const tool of ['get_events', 'add_or_update_event', 'delete_event']) {
    assert.ok(definition.content.includes(tool), `loaded content must document the ICU plan tool ${tool}`);
  }
  assert.ok(definition.content.includes('在床'), 'loaded content must document the time-in-bed sleep convention');
  assert.ok(definition.content.includes('## Bundled files'));
  for (const relativePath of [
    'references/01-data-sources.md',
    'references/09-weather.md',
    'scripts/vdot.py',
    'scripts/init_athlete.py',
    'assets/athlete.example.json',
  ]) {
    assert.ok(definition.content.includes(relativePath), `Bundled files index must list ${relativePath}`);
  }

  assert.ok(!ABSOLUTE_PATH_RE.test(definition.content), 'loaded content must not contain absolute machine paths');
  assert.ok(!CREDENTIAL_RE.test(definition.content), 'loaded content must not contain credential words');
  for (const reference of PRIVATE_WORKSPACE_REFS) {
    assert.ok(!definition.content.includes(reference), `loaded content must not reference private workspace file ${reference}`);
  }

  assert.equal(state.effects.length, 1, 'the provider disposer must be registered through ctx.effect');
  assert.equal(typeof state.disposers[0], 'function');
  state.effects[0].disposer();
  assert.equal(state.disposed, 1);
});

test('get() rejects an unknown candidate', async (t) => {
  if (!existsSync(SKILL_MD)) {
    t.skip('skill/endurance-coach/SKILL.md is not written yet (content task in progress)');
    return;
  }
  const { ctx, state } = createMockContext();
  await apply(ctx);
  const provider = state.factories[0]();
  await assert.rejects(() => provider.get({ name: 'not-a-skill' }, {}), /unknown skill/);
});

test('config.skillDir overrides the bundled directory', async () => {
  const fixture = makeFixtureSkill();
  try {
    const { ctx, state } = createMockContext();
    await apply(ctx, { skillDir: fixture.root });
    assert.equal(state.factories.length, 1);
    const provider = state.factories[0]();
    const list = await provider.list();
    assert.equal(list.length, 1);
    assert.equal(list[0].name, 'fixture-skill');
    assert.equal(list[0].rank, 600);
    assert.equal(normalize(list[0].resourceBase.path), normalize(fixture.skill));
    const definition = await provider.get(list[0], {});
    assert.ok(definition.content.includes('# Fixture'));
    assert.ok(definition.content.includes('## Bundled files'));
    assert.ok(definition.content.includes('references/01-note.md'));
    assert.ok(definition.content.includes('scripts/thing.py'));
  } finally {
    rmSync(fixture.root, { recursive: true, force: true });
  }
});

test('a missing skill directory warns without throwing or registering', async () => {
  const { ctx, state } = createMockContext();
  await apply(ctx, { skillDir: join(PACKAGE_ROOT, 'definitely-not-a-skill-dir') });
  assert.equal(state.factories.length, 0);
  assert.ok(state.logs.some((entry) => entry.level === 'warn' && entry.message.includes('cannot load')));
});

test('apply rejects when the skills registry is unavailable', async () => {
  await assert.rejects(() => apply({}, {}), /skills registry is unavailable/);
});
