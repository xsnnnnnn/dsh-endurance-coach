import assert from 'node:assert/strict';
import { existsSync, readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import { inject } from '../lib/index.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = dirname(HERE);
const read = (relativePath) => readFileSync(join(ROOT, relativePath), 'utf8');
const pkg = JSON.parse(read('package.json'));

const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
const MAX_ICON_BYTES = 256 * 1024;

test('package.json declares the expected bundle identity', () => {
  assert.equal(pkg.name, 'dsh-endurance-coach');
  assert.equal(pkg.version, '1.0.0');
  assert.equal(pkg.type, 'module');
  assert.equal(pkg.main, 'lib/index.js');
  assert.equal(pkg.license, 'MIT');
  assert.equal(pkg.icon, 'assets/icon.png');
  assert.equal(typeof pkg.description, 'string');
  assert.ok(pkg.description.length > 20);
});

test('package.json exports the entry points a bundle is expected to expose', () => {
  assert.equal(pkg.exports['.'], './lib/index.js');
  assert.equal(pkg.exports['./cordis.patch.yml'], './cordis.patch.yml');
  assert.equal(pkg.exports['./package.json'], './package.json');
  assert.equal(pkg.exports['./locale/*.json'], './locale/*.json');
  assert.equal(pkg.exports['./icon'], './assets/icon.png');
});

test('package.json files whitelist ships the bundle and excludes tests', () => {
  const files = pkg.files;
  assert.ok(Array.isArray(files));
  for (const expected of [
    'lib',
    'skill',
    'locale',
    'assets/icon.png',
    'cordis.patch.yml',
    'dsh.plugin.json',
    'README.md',
    'README.zh.md',
    'LICENSE',
  ]) {
    assert.ok(files.includes(expected), `files must include ${expected}`);
  }
  assert.ok(!files.some((entry) => entry === 'test' || entry.startsWith('test/')), 'tests must not be packed');
  assert.ok(!files.some((entry) => entry.includes('node_modules') || entry === '.git'));
});

test('package.json engines and dsh bundle metadata are valid', () => {
  assert.equal(pkg.engines.node, '>=20.0.0');
  assert.equal(pkg.engines.dsh, '>=0.2.1-rc.1');
  assert.equal(pkg.dsh.bundle.patch, './cordis.patch.yml');
  assert.equal(pkg.dsh.compatibility.dshReleases['0.2.1-rc.5'], 'compatible');
  assert.equal(pkg.dsh.compatibility.dshReleases['0.2.2-rc.1'], 'compatible');
  assert.ok(existsSync(join(ROOT, pkg.dsh.bundle.patch)), 'bundle patch file must exist');
  assert.ok(existsSync(join(ROOT, pkg.main)), 'main entry must exist');
});

test('the package has no runtime dependencies and only an optional peer', () => {
  assert.deepEqual(pkg.dependencies ?? {}, {});
  assert.deepEqual(Object.keys(pkg.peerDependencies ?? {}), ['@deepseek-ai/dsh-skill']);
  assert.equal(pkg.peerDependenciesMeta['@deepseek-ai/dsh-skill'].optional, true);
  assert.ok(pkg.scripts.test.includes('node --test'));
});

test('repository, homepage, and bugs point at the public repository', () => {
  assert.equal(pkg.repository.type, 'git');
  assert.equal(pkg.repository.url, 'git+https://github.com/xsnnnnnn/dsh-endurance-coach.git');
  assert.equal(pkg.homepage, 'https://github.com/xsnnnnnn/dsh-endurance-coach#readme');
  assert.equal(pkg.bugs.url, 'https://github.com/xsnnnnnn/dsh-endurance-coach/issues');
});

test('dsh.plugin.json matches package.json and the plugin exports', () => {
  const plugin = JSON.parse(read('dsh.plugin.json'));
  assert.equal(plugin.name, pkg.name);
  assert.equal(plugin.version, pkg.version);
  assert.equal(plugin.description, pkg.description);
  assert.equal(plugin.entry.name, pkg.name);
  assert.deepEqual(plugin.entry.inject, inject);
});

test('cordis.patch.yml inserts exactly one dsh-endurance-coach row', () => {
  const patch = read('cordis.patch.yml');
  assert.match(patch, /^-\s*insert:/mu);
  assert.match(patch, /id:\s*dsh-endurance-coach/u);
  assert.match(patch, /name:\s*'dsh-endurance-coach'/u);
  assert.equal((patch.match(/^\s*-\s*insert:/gmu) ?? []).length, 1);
  assert.equal((patch.match(/^\s*-\s*id:\s*dsh-endurance-coach\s*$/gmu) ?? []).length, 1);
});

test('locale files are valid and carry the plugin display metadata', () => {
  const en = JSON.parse(read('locale/en.json'));
  const zh = JSON.parse(read('locale/zh.json'));
  for (const locale of [en, zh]) {
    assert.equal(typeof locale.meta.title, 'string');
    assert.ok(locale.meta.title.length > 0);
    assert.equal(typeof locale.meta.description, 'string');
    assert.ok(locale.meta.description.length > 10);
  }
  assert.equal(en.meta.title, 'Endurance Coach');
  assert.equal(zh.meta.title, '耐力教练');
  assert.notEqual(en.meta.description, zh.meta.description);
});

test('assets/icon.png is a valid 512x512 PNG under 256 KiB', () => {
  const iconPath = join(ROOT, 'assets/icon.png');
  assert.ok(existsSync(iconPath));
  const bytes = statSync(iconPath).size;
  assert.ok(bytes > 0 && bytes < MAX_ICON_BYTES, `icon must be under 256 KiB, got ${bytes}`);
  const buffer = readFileSync(iconPath);
  assert.ok(buffer.subarray(0, 8).equals(PNG_SIGNATURE), 'icon must start with the PNG signature');
  const width = buffer.readUInt32BE(16);
  const height = buffer.readUInt32BE(20);
  assert.equal(width, 512);
  assert.equal(height, 512);
});

test('LICENSE is the MIT license attributed to xsnnnnnn', () => {
  const license = read('LICENSE');
  assert.ok(license.includes('MIT License'));
  assert.ok(license.includes('Copyright (c) 2026 xsnnnnnn'));
  assert.ok(license.includes('WITHOUT WARRANTY OF ANY KIND'));
});

test('READMEs exist and document install, setup, and safety', () => {
  for (const filename of ['README.md', 'README.zh.md']) {
    const text = read(filename);
    assert.ok(text.length > 2000, `${filename} is too short`);
    assert.ok(text.includes("dsh plugin --profile desktop add 'github:xsnnnnnn/dsh-endurance-coach'"));
    assert.ok(text.includes('coach/athlete.json'));
    assert.ok(text.includes('ENDURANCE_COACH_DIR'));
    assert.ok(text.includes('init_athlete.py'));
    assert.ok(text.includes('not medical advice') || text.includes('不是医疗建议'));
    assert.ok(text.includes('MIT'));
  }
});
