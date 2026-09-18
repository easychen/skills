/**
 * engine.js 契约测试（node:test）：全部源失败时不落盘（避免空数据覆盖 demoData）。
 *
 * 运行: node --test skills/sudoboard/tests/engine.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { execFile } from 'node:child_process';
import { mkdtempSync, writeFileSync, mkdirSync, existsSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

const execFileAsync = promisify(execFile);
const HERE = dirname(fileURLToPath(import.meta.url));
const ENGINE = join(HERE, '..', 'scripts', 'engine.js');

function makeProject(root, url) {
  mkdirSync(join(root, 'templates'), { recursive: true });
  writeFileSync(join(root, 'templates', 'main.jsx'),
    'export default function Screen({ data }) { return null; }');
  writeFileSync(join(root, 'board.json'), JSON.stringify({
    board: { name: 'engine-test', theme: 'dark' },
    sources: [{
      key: 'only', create: {
        name: 'only', type: 'http', intervalSeconds: 300, enabled: true,
        fetch: { url, method: 'GET', timeoutSeconds: 3 },
        extractors: [{ name: 'v', jsonata: 'value' }],
      },
    }],
    template: { key: 'main', name: 't', file: 'templates/main.jsx',
      demoData: { values: { demo: 1 }, meta: {} } },
    dashboard: { key: 'main', name: 'd', templateKey: 'main', sourceKeys: ['only'], refreshSeconds: 60 },
    playback: { key: 'main', name: 'g', dashboardKeys: ['main'], durationSeconds: 30,
      transition: { style: 'fade', durationMs: 800 }, activate: true },
  }, null, 2));
}

async function runEngine(dir) {
  try {
    const r = await execFileAsync(process.execPath, [ENGINE, '--dir', dir], { timeout: 30000 });
    return { code: 0, out: r.stdout + r.stderr };
  } catch (e) {
    return { code: e.code ?? 1, out: (e.stdout || '') + (e.stderr || '') };
  }
}

test('全部源失败 → 不写 preview/data.json（保留 demoData 兜底）', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'sudb-engine-fail-'));
  makeProject(dir, 'http://127.0.0.1:1/nope');   // 端口 1：必然连接失败
  const r = await runEngine(dir);
  assert.equal(r.code, 1, `应退出码 1，实际 ${r.code}\n${r.out}`);
  assert.equal(existsSync(join(dir, 'preview', 'data.json')), false,
    '全部源失败时不应生成 data.json');
  assert.match(r.out, /预览将沿用 demoData|不写|保持/);
});

test('至少一个源成功 → 写 preview/data.json', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'sudb-engine-ok-'));
  const srv = createServer((req, res) => {
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ value: 42 }));
  });
  await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  const url = `http://127.0.0.1:${srv.address().port}/metrics`;
  try {
    makeProject(dir, url);
    const r = await runEngine(dir);
    assert.equal(r.code, 0, r.out);
    const data = JSON.parse(readFileSync(join(dir, 'preview', 'data.json'), 'utf8'));
    assert.equal(data.values.v, 42);
    assert.equal(data.meta.sourceStatus.only.ok, true);
  } finally {
    srv.close();
  }
});

test('全部源失败时保留上一次成功的 data.json', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'sudb-engine-keep-'));
  const srv = createServer((req, res) => {
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ value: 7 }));
  });
  await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  const port = srv.address().port;
  try {
    makeProject(dir, `http://127.0.0.1:${port}/metrics`);
    assert.equal((await runEngine(dir)).code, 0);
    const before = readFileSync(join(dir, 'preview', 'data.json'), 'utf8');
    srv.close();
    const r2 = await runEngine(dir);   // 服务已关：抓取失败
    assert.equal(r2.code, 1, r2.out);
    assert.equal(readFileSync(join(dir, 'preview', 'data.json'), 'utf8'), before,
      '失败不应清掉上一次的好数据');
  } finally {
    try { srv.close(); } catch { /* 已关 */ }
  }
});
