/**
 * SudoBoard Skill · cf_worker.test.mjs — 渲染出的 Cloudflare Worker 运行时测试（node --test）。
 *
 * 测试不依赖真实 Cloudflare：把模板 Rs 渲染成临时 ESM worker（jsonata.min.js 放旁边），
 * 注入假的 KV（内存 Map）与假的全局 fetch，直接调用 fetch/scheduled handler 验证：
 *   - 播放页 / 与 /play 返回内联 HTML；
 *   - /api/status 脱敏（不含源凭据）；
 *   - /api/data：无快照 → 引擎真实抓取+JSONATA 抽取落 KV；有新鲜快照 → 不重复抓取；
 *   - 单源失败不阻塞其他源；
 *   - /assets/<id> 二进制 + mime；未知 404；
 *   - /api/refresh POST 强制重抓；scheduled() 落库。
 *
 * 运行: node --test tests/cf_worker.test.mjs
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync, copyFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const SCRIPTS = join(HERE, '..', 'scripts');

function renderWorker(config, playHtml) {
  const tpl = readFileSync(join(SCRIPTS, 'cf_worker.template.js'), 'utf8');
  const js = tpl
    .replaceAll('__SB_CFG__', JSON.stringify(config))
    .replaceAll('__SB_PAGE__', JSON.stringify(playHtml));
  const dir = mkdtempSync(join(tmpdir(), 'sudb-cf-test-'));
  writeFileSync(join(dir, 'worker.mjs'), js, 'utf8');
  // jsonata.min.js 是 UMD/CJS：Node ESM 的 default import 会拿到 module.exports
  copyFileSync(join(SCRIPTS, 'vendor', 'jsonata.min.js'), join(dir, 'jsonata.min.js'));
  return pathToFileURL(join(dir, 'worker.mjs')).href;
}

/** 内存 KV，模拟 env.SDB：get(key, {type:'arrayBuffer'}) 支持二进制读取。 */
export function fakeKV(seed = {}) {
  const store = new Map(Object.entries(seed));
  return {
    _store: store,
    get: async (key, opts) => {
      const v = store.get(key);
      if (v == null) return null;
      if (opts && opts.type === 'arrayBuffer') {
        if (v instanceof ArrayBuffer) return v;
        return new TextEncoder().encode(String(v)).buffer;
      }
      return String(v);
    },
    put: async (key, value) => { store.set(key, value); },
  };
}

/** 按 URL 返回 JSON 的假 fetch 工厂；记录调用次数便于断言缓存。 */
function stubFetch(routes) {
  const calls = [];
  globalThis.fetch = async (input, init) => {
    const url = typeof input === 'string' ? input : input.url;
    calls.push(url);
    const route = routes[url];
    if (!route) return new Response('not found', { status: 404 });
    if (typeof route === 'function') return route();
    if (route instanceof Response) return route; // 预构建的失败响应
    return new Response(JSON.stringify(route), { status: 200 });
  };
  return calls;
}

const CONFIG = {
  boardName: '测试看板',
  theme: 'dark',
  minIntervalSeconds: 300,
  refreshSeconds: 60,
  playUrl: '/play',
  sources: [
    {
      id: 'demo',
      name: '演示源',
      type: 'http',
      enabled: true,
      intervalSeconds: 300,
      fetch: {
        url: 'https://mock.example/metrics',
        method: 'GET',
        headers: { Authorization: 'Bearer tok-secret-999' },
        timeoutSeconds: 8,
      },
      extractors: [
        { name: 'balance', jsonata: 'balance_infos.total_balance' },
        { name: 'org', jsonata: 'org' },
      ],
    },
  ],
  assets: { a1234567890ab: { mime: 'image/jpeg' } },
};

const PLAY_HTML = '<html><body>测试看板播放页</body></html>';

const RAW = {
  balance_infos: { total_balance: 123.45 },
  org: 'acme',
};

async function boot() {
  const url = renderWorker(CONFIG, PLAY_HTML);
  const mod = await import(url);
  return mod.default;
}

test('播放页：/ 与 /play 返回内联 HTML', async () => {
  const worker = await boot();
  const env = { SDB: fakeKV() };
  for (const path of ['/', '/play', '/play/']) {
    const res = await worker.fetch(new Request('https://x.test' + path), env);
    assert.equal(res.status, 200);
    assert.match(await res.text(), /测试看板播放页/);
  }
});

test('/api/status：脱敏，不泄漏源凭据与 token', async () => {
  const worker = await boot();
  const env = { SDB: fakeKV() };
  const res = await worker.fetch(new Request('https://x.test/api/status'), env);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.ok, true);
  assert.equal(body.data.mode, 'cloudflare');
  assert.equal(body.data.boardName, '测试看板');
  assert.ok(Array.isArray(body.data.sources));
  const text = JSON.stringify(body);
  assert.ok(!text.includes('tok-secret-999'), 'status 不应含 Authorization token');
  assert.ok(!text.includes('Authorization'), 'status 不应含源请求头');
});

test('/api/data：无快照 → 引擎真实抓取 + JSONATA 抽取并落 KV', async () => {
  const worker = await boot();
  const env = { SDB: fakeKV() };
  const calls = stubFetch({ 'https://mock.example/metrics': RAW });
  const res = await worker.fetch(new Request('https://x.test/api/data'), env);
  assert.equal(res.status, 200);
  const { ok, data } = await res.json();
  assert.equal(ok, true);
  assert.equal(data.values.balance, 123.45);
  assert.equal(data.values.org, 'acme');
  assert.equal(data.meta.sourceStatus.demo.ok, true);
  assert.equal(calls.length, 1);
  // 快照已落 KV（幂等验证第二次请求不再抓取）
  assert.ok(env.SDB._store.has('snapshot'));
});

test('/api/data：快照新鲜 → 不重复抓取（缓存命中）', async () => {
  const worker = await boot();
  const kv = fakeKV();
  const snap = {
    values: { balance: 1 },
    meta: { updatedAt: new Date().toISOString(), sourceStatus: { demo: { ok: true } }, theme: 'dark' },
  };
  kv.put('snapshot', JSON.stringify(snap));
  const env = { SDB: kv };
  const calls = stubFetch({ 'https://mock.example/metrics': RAW });
  const res = await worker.fetch(new Request('https://x.test/api/data'), env);
  const { data } = await res.json();
  assert.equal(data.values.balance, 1);
  assert.equal(calls.length, 0, '新鲜快照不应触发抓取');
});

test('单源失败不阻塞其他源', async () => {
  const url = renderWorker({
    ...CONFIG,
    sources: [
      CONFIG.sources[0],
      {
        id: 'bad', name: '坏源', type: 'http', enabled: true, intervalSeconds: 60,
        fetch: { url: 'https://mock.example/broken', method: 'GET', timeoutSeconds: 5 },
        extractors: [{ name: 'x', jsonata: 'x' }],
      },
    ],
  }, PLAY_HTML);
  const worker = (await import(url)).default;
  const env = { SDB: fakeKV() };
  stubFetch({
    'https://mock.example/metrics': RAW,
    'https://mock.example/broken': new Response('boom', { status: 500 }),
  });
  const res = await worker.fetch(new Request('https://x.test/api/data'), env);
  const { data } = await res.json();
  assert.equal(data.values.balance, 123.45, '好源的值照常保留');
  assert.equal(data.meta.sourceStatus.bad.ok, false);
  assert.equal(data.meta.sourceStatus.bad.lastError, 'http_500');
});

test('源瞬时失败：保留上一次成功的值（不清空看板）', async () => {
  const worker = await boot();
  const env = { SDB: fakeKV() };
  stubFetch({ 'https://mock.example/metrics': RAW });
  await worker.fetch(new Request('https://x.test/api/refresh', { method: 'POST' }), env);
  // 第二次抓取失败
  stubFetch({ 'https://mock.example/metrics': new Response('down', { status: 503 }) });
  const res = await worker.fetch(new Request('https://x.test/api/refresh', { method: 'POST' }), env);
  const { data } = await res.json();
  assert.equal(data.meta.sourceStatus.demo.ok, false);
  assert.equal(data.meta.sourceStatus.demo.lastError, 'http_503');
  assert.equal(data.values.balance, 123.45, '失败时保留上次的值');
  assert.equal(data.values.org, 'acme');
  // 落 KV 的快照也保留
  const snap = JSON.parse(env.SDB._store.get('snapshot'));
  assert.equal(snap.values.balance, 123.45);
});

test('某源失败时不会污染其他源的值', async () => {
  const url = renderWorker({
    ...CONFIG,
    sources: [
      CONFIG.sources[0],
      {
        id: 'other', name: '另一个源', type: 'http', enabled: true, intervalSeconds: 60,
        fetch: { url: 'https://mock.example/other', method: 'GET', timeoutSeconds: 5 },
        extractors: [{ name: 'otherVal', jsonata: 'v' }],
      },
    ],
  }, PLAY_HTML);
  const worker = (await import(url)).default;
  const env = { SDB: fakeKV() };
  stubFetch({
    'https://mock.example/metrics': RAW,
    'https://mock.example/other': { v: 9 },
  });
  await worker.fetch(new Request('https://x.test/api/refresh', { method: 'POST' }), env);
  // 只让第二个源失败
  stubFetch({
    'https://mock.example/metrics': RAW,
    'https://mock.example/other': new Response('down', { status: 500 }),
  });
  const res = await worker.fetch(new Request('https://x.test/api/refresh', { method: 'POST' }), env);
  const { data } = await res.json();
  assert.equal(data.values.otherVal, 9, '失败源保留旧值');
  assert.equal(data.values.balance, 123.45);
  assert.equal(data.meta.sourceStatus.other.ok, false);
  assert.equal(data.meta.sourceStatus.demo.ok, true);
});

test('/assets/<id>：二进制 + mime；未知 404', async () => {
  const worker = await boot();
  const kv = fakeKV({ 'asset:a1234567890ab': 'fakejpegbytes' });
  const env = { SDB: kv };
  const res = await worker.fetch(new Request('https://x.test/assets/a1234567890ab'), env);
  assert.equal(res.status, 200);
  assert.equal(res.headers.get('content-type'), 'image/jpeg');
  assert.equal(await res.text(), 'fakejpegbytes');
  const miss = await worker.fetch(new Request('https://x.test/assets/nope'), env);
  assert.equal(miss.status, 404);
});

test('/api/refresh：POST 强制重抓并返回新快照', async () => {
  const worker = await boot();
  const env = { SDB: fakeKV({
    snapshot: JSON.stringify({
      values: { balance: 0 },
      meta: { updatedAt: new Date().toISOString(), sourceStatus: { demo: { ok: true } }, theme: 'dark' },
    }),
  }) };
  const calls = stubFetch({ 'https://mock.example/metrics': RAW });
  const res = await worker.fetch(new Request('https://x.test/api/refresh', { method: 'POST' }), env);
  assert.equal(res.status, 200);
  const { data } = await res.json();
  assert.equal(data.values.balance, 123.45);
  assert.equal(calls.length, 1, 'refresh 应无视缓存强制抓取');
});

test('scheduled()：cron 抓取并落 KV', async () => {
  const worker = await boot();
  const env = { SDB: fakeKV() };
  stubFetch({ 'https://mock.example/metrics': RAW });
  await worker.scheduled({}, env);
  assert.ok(env.SDB._store.has('snapshot'));
  const snap = JSON.parse(env.SDB._store.get('snapshot'));
  assert.equal(snap.values.balance, 123.45);
});

test('未知路由 → 404 JSON', async () => {
  const worker = await boot();
  const env = { SDB: fakeKV() };
  const res = await worker.fetch(new Request('https://x.test/nope'), env);
  assert.equal(res.status, 404);
  const body = await res.json();
  assert.equal(body.ok, false);
});

test('/api/me：未启用 Access 时返回未认证', async () => {
  const worker = await boot();
  const env = { SDB: fakeKV() };
  const res = await worker.fetch(new Request('https://x.test/api/me'), env);
  assert.equal(res.status, 200);
  const { data } = await res.json();
  assert.equal(data.authenticated, false);
  assert.equal(data.email, null);
});

test('/api/me：Access 生效时（ctx.access.getIdentity）返回访问者邮箱', async () => {
  const worker = await boot();
  const env = { SDB: fakeKV() };
  const ctx = { access: { getIdentity: async () => ({ email: 'viewer@example.com', name: 'Viewer' }) } };
  const res = await worker.fetch(new Request('https://x.test/api/me'), env, ctx);
  assert.equal(res.status, 200);
  const { data } = await res.json();
  assert.equal(data.authenticated, true);
  assert.equal(data.email, 'viewer@example.com');
});