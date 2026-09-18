/**
 * SudoBoard Skill · cf_worker.template.js — Cloudflare Worker 部署模板（无需 App）。
 *
 * 由 deploy_cf.py 渲染为 dist/cf/worker.js（替换配置与播放页两个占位 token）：
 *   - 数据引擎：HTTP 源真实抓取（Method/Headers/超时）→ JSONATA 抽取命名值
 *     （与 engine.js / App 引擎同一套逻辑的 Worker 移植）；
 *   - KV（binding=SDB）：snapshot 最新快照（values+meta）；asset:<id> 资产二进制；
 *   - cron（scheduled）：按源最小 intervalSeconds 定时抓取落库；
 *   - API：/ 与 /play（生成的播放页）、/api/status（脱敏）、/api/data（快照，
 *     过期按需重抓）、/api/refresh（POST 强制刷新）、/assets/<id>（资产）。
 */
import jsonata from './jsonata.min.js';

/* 配置注入（deploy_cf.py 渲染后此处为 CONFIG 对象字面量） */
const CONFIG = __SB_CFG__;

/* 播放页注入（deploy_cf.py 渲染后此处为播放页 HTML 字符串） */
const PLAY_HTML = __SB_PAGE__;

const KEY_SNAPSHOT = 'snapshot';
const ASSET_PREFIX = 'asset:';

/* ================= 数据引擎（1:1 移植 engine.js 的 HTTP 源逻辑） ================= */

async function fetchSource(f) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), (f.timeoutSeconds || 10) * 1000);
  try {
    const headers = { ...(f.headers || {}) };
    if (f.body && !Object.keys(headers).some((k) => k.toLowerCase() === 'content-type')) {
      headers['content-type'] = 'application/json';
    }
    const res = await fetch(f.url, {
      method: f.method || 'GET',
      headers,
      body: f.body ? String(f.body) : undefined,
      signal: ctrl.signal,
    });
    const text = await res.text();
    if (!res.ok) return { ok: false, lastError: 'http_' + res.status };
    let raw;
    try {
      raw = JSON.parse(text);
    } catch (e) {
      return { ok: false, lastError: 'non_json_response' };
    }
    return { ok: true, raw };
  } catch (e) {
    return {
      ok: false,
      lastError: e && e.name === 'AbortError' ? 'timeout'
        : String((e && e.message) || e).split('\n')[0],
    };
  } finally {
    clearTimeout(timer);
  }
}

async function extract(raw, extractors) {
  const values = {};
  for (const ex of extractors || []) {
    try {
      values[ex.name] = await jsonata(ex.jsonata).evaluate(raw);
    } catch (e) {
      throw new Error(`jsonata "${ex.name}": ${String((e && e.message) || e).split('\n')[0]}`);
    }
  }
  return values;
}

/** 抓取全部启用源 → 组装快照 → 落 KV。
 *  单源失败不阻塞其他源（与 App 一致）；失败源沿用上一份快照里属于它的命名值，
 *  避免一次瞬时抖动把整块看板清空（App 侧是分源保留快照）。 */
async function runEngine(env) {
  const kv = env.SDB;
  let prevValues = {};
  try {
    const raw = await kv.get(KEY_SNAPSHOT);
    if (raw) {
      const prev = JSON.parse(raw);
      if (prev && prev.values && typeof prev.values === 'object') prevValues = prev.values;
    }
  } catch (e) { prevValues = {}; }

  const values = {};
  const sourceStatus = {};
  const keepPrev = (src) => {
    for (const ex of src.extractors || []) {
      if (ex && ex.name in prevValues) values[ex.name] = prevValues[ex.name];
    }
  };
  for (const src of CONFIG.sources || []) {
    if (src.enabled === false) continue;
    if (src.type !== 'http') {
      sourceStatus[src.id] = { ok: false, lastError: 'unsupported_type:' + src.type };
      continue;
    }
    const snap = await fetchSource(src.fetch || {});
    if (!snap.ok) {
      keepPrev(src);
      sourceStatus[src.id] = { ok: false, lastError: snap.lastError };
      continue;
    }
    try {
      const extracted = await extract(snap.raw, src.extractors);
      for (const [k, v] of Object.entries(extracted)) values[k] = v;
      sourceStatus[src.id] = { ok: true, lastError: null };
    } catch (e) {
      keepPrev(src);
      sourceStatus[src.id] = { ok: false, lastError: String((e && e.message) || e) };
    }
  }
  const snapshot = {
    values,
    meta: {
      updatedAt: new Date().toISOString(),
      sourceStatus,
      theme: CONFIG.theme || 'dark',
    },
  };
  await kv.put(KEY_SNAPSHOT, JSON.stringify(snapshot));
  return snapshot;
}

/** 返回快照：KV 里有且未超过源最小间隔 → 直接返回；否则按需重抓并落库。 */
async function getSnapshot(env) {
  const raw = await env.SDB.get(KEY_SNAPSHOT);
  let snap = null;
  if (raw) {
    try { snap = JSON.parse(raw); } catch (e) { snap = null; }
  }
  const ttlMs = (CONFIG.minIntervalSeconds || 300) * 1000;
  if (snap && snap.meta && snap.meta.updatedAt) {
    const age = Date.now() - new Date(snap.meta.updatedAt).getTime();
    if (age >= 0 && age < ttlMs) return snap;
  }
  return runEngine(env);
}

/* ================= HTTP 路由 ================= */

function json(body, status) {
  return new Response(JSON.stringify(body), {
    status: status || 200,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'access-control-allow-origin': '*',
      'cache-control': 'no-store',
    },
  });
}

async function handler(request, env, ctx) {
  const url = new URL(request.url);
  const p = url.pathname;

  if (p === '/' || p === '/play' || p === '/play/') {
    return new Response(PLAY_HTML, {
      headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' },
    });
  }
  if (p === '/api/me') {
    // Access 生效时（Worker 级 Access，2026-08+）返回当前访问者邮箱，用于确认访问控制已上锁。
    let email = null;
    try {
      if (ctx && ctx.access && typeof ctx.access.getIdentity === 'function') {
        const identity = await ctx.access.getIdentity();
        email = (identity && identity.email) || null;
      }
    } catch (e) { /* 未启用 Access 时保持未认证 */ }
    return json({ ok: true, data: { authenticated: !!email, email } });
  }
  if (p === '/api/status') {
    const raw = await env.SDB.get(KEY_SNAPSHOT);
    let snap = null;
    if (raw) {
      try { snap = JSON.parse(raw); } catch (e) { snap = null; }
    }
    const sources = (CONFIG.sources || [])
      .filter((s) => s.enabled !== false)
      .map((s) => {
        const st = snap && snap.meta && snap.meta.sourceStatus
          ? snap.meta.sourceStatus[s.id] : null;
        return {
          id: s.id,
          name: s.name,
          ok: !!(st && st.ok),
          lastError: (st && st.lastError) || null,
        };
      });
    return json({
      ok: true,
      data: {
        mode: 'cloudflare',
        boardName: CONFIG.boardName,
        theme: CONFIG.theme || 'dark',
        updatedAt: (snap && snap.meta && snap.meta.updatedAt) || null,
        refreshSeconds: CONFIG.refreshSeconds || 60,
        sources,
        playUrl: CONFIG.playUrl || '/play',
      },
    });
  }
  if (p === '/api/data') {
    return json({ ok: true, data: await getSnapshot(env) });
  }
  if (p === '/api/refresh' && request.method === 'POST') {
    return json({ ok: true, data: await runEngine(env) });
  }
  if (p.startsWith('/assets/')) {
    const id = decodeURIComponent(p.slice('/assets/'.length));
    const meta = (CONFIG.assets || {})[id];
    const buf = await env.SDB.get(ASSET_PREFIX + id, { type: 'arrayBuffer' });
    if (buf == null) return json({ ok: false, error: 'not_found' }, 404);
    return new Response(buf, {
      headers: {
        'content-type': (meta && meta.mime) || 'application/octet-stream',
        'cache-control': 'public, max-age=3600',
      },
    });
  }
  if (p === '/robots.txt') {
    return new Response('User-agent: *\nDisallow: /\n', {
      headers: { 'content-type': 'text/plain' },
    });
  }
  return json({ ok: false, error: 'not_found' }, 404);
}

/** cron 定时抓取：与 getSnapshot 相同的落库逻辑（观众查询前数据已就绪）。 */
async function scheduled(event, env, ctx) {
  await runEngine(env);
}

export default { fetch: handler, scheduled };