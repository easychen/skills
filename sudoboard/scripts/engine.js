#!/usr/bin/env node
/**
 * SudoBoard Skill · engine.js — 本地数据引擎（Node 版）
 *
 * 按 board.json 中数据源的 fetch/db 配置**真实取数**，组装模板契约 __DATA__
 * （values + meta）写入 preview/data.json，供本地预览渲染。
 *
 * - HTTP 源：fetch（Method/Headers/超时）→ JSONATA 抽取命名值（官方 jsonata 实现，
 *   与 App 的 jsonata_dart 同语言）；
 * - DB 源（sqlite / mysql / pg）：执行命名查询 → values[查询名] = {columns, rows}
 *   （与 App QueryTable.toJson() 同形态）；只读拦截 1:1 移植 ReadOnlyGuard；
 *   sqlite 用 Node 内置 node:sqlite（≥22.13）零依赖，mysql2/pg 为纯 JS 驱动、
 *   首次使用自动安装到 scripts/vendor/nodejs/；
 * - 单源失败不阻塞其他源；与 App 一致：部分查询失败时 ok=false，但成功结果照常保留。
 * - 限制：一次性取数，不做定时轮询与环比计算。
 *
 * 用法:
 *   node engine.js [--dir <sudoboard工程目录>] [--out <data.json路径>] [--source key1,key2]
 *
 * 依赖: Node 18+（HTTP 源）；DB 源 sqlite 需 Node ≥22.13（内置 node:sqlite）
 */
'use strict';
const fs = require('fs');
const path = require('path');
const jsonata = require(path.join(__dirname, 'vendor', 'jsonata.min.js'));

const VENDOR_NODE = path.join(__dirname, 'vendor', 'nodejs');

function argVal(name, def) {
  const i = process.argv.indexOf(name);
  return (i >= 0 && process.argv[i + 1] !== undefined) ? process.argv[i + 1] : def;
}

/* ================= ReadOnlyGuard（1:1 移植 app/lib/security/readonly_guard.dart） ================= */

const WRITE_PREFIXES = new Set([
  'insert', 'update', 'delete', 'drop', 'alter', 'truncate', 'replace',
  'create', 'grant', 'revoke', 'set', 'call', 'merge', 'comment', 'rename',
  'lock', 'unlock', 'vacuum', 'attach', 'detach', 'pragma',
]);

/// 移除字符串字面量与 `--` 行注释（用于分号检测）。
function stripCommentsAndStrings(sql) {
  let out = '';
  let singleQuote = false;
  for (let j = 0; j < sql.length; j++) {
    const ch = sql[j];
    if (singleQuote) {
      if (ch === "'") singleQuote = false;
      continue;
    }
    if (ch === "'") {
      singleQuote = true;
      continue;
    }
    if (ch === '-' && j + 1 < sql.length && sql[j + 1] === '-') {
      while (j < sql.length && sql[j] !== '\n') j++;
      if (j < sql.length) out += '\n';
      continue;
    }
    out += ch;
  }
  return out;
}

/// 检查结果：null 表示通过；否则返回拒绝原因。
function readOnlyGuardCheck(sql, readOnly) {
  const stripped = stripCommentsAndStrings(sql);
  const firstSemicolon = stripped.indexOf(';');
  if (firstSemicolon >= 0 && firstSemicolon < stripped.trim().length - 1) {
    return 'multi_statement_blocked';
  }
  const trimmed = sql.trim().toLowerCase();
  if (!trimmed) return 'empty_sql';
  const firstToken = trimmed.split(/\s+/)[0];
  if (WRITE_PREFIXES.has(firstToken)) {
    if (readOnly) return `readonly_blocked:${firstToken}`;
    if (firstSemicolon >= 0) return 'multi_statement_blocked'; // 即使允许写：多语句仍拦截
    return null;
  }
  return null;
}

/* ================= HTTP 源 ================= */

/** 按 source 配置执行一次 HTTP 抓取，返回 { ok, raw?, lastError? }。 */
async function fetchSource(payload) {
  const f = payload.fetch || payload;
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
    if (!res.ok) return { ok: false, lastError: `http_${res.status}` };
    let raw;
    try {
      raw = JSON.parse(text);
    } catch {
      return { ok: false, lastError: 'non_json_response' };
    }
    return { ok: true, raw };
  } catch (e) {
    return { ok: false, lastError: e.name === 'AbortError' ? 'timeout' : String(e.message || e).split('\n')[0] };
  } finally {
    clearTimeout(timer);
  }
}

/** 对原始 JSON 依次执行 JSONATA 抽取器，产出命名值。任一表达式失败即抛错（源级失败）。 */
async function extract(raw, extractors) {
  const values = {};
  for (const ex of extractors || []) {
    try {
      values[ex.name] = await jsonata(ex.jsonata).evaluate(raw);
    } catch (e) {
      throw new Error(`jsonata "${ex.name}": ${String(e.message || e).split('\n')[0]}`);
    }
  }
  return values;
}

/* ================= DB 源（对齐 app/lib/engine/db_executor.dart + data_engine._fetchDb） ================= */

function tryRequire(name) {
  for (const base of [undefined, path.join(VENDOR_NODE, 'node_modules')]) {
    try {
      return base ? require(path.join(base, name)) : require(name);
    } catch { /* 尝试下一个位置 */ }
  }
  return null;
}

/** 纯 JS 驱动缺失时自动安装一次（mysql2 / pg，无原生编译）。 */
function ensureDriver(name) {
  const mod = tryRequire(name);
  if (mod) return mod;
  console.log(`  ⚠ 驱动 ${name} 未安装，自动安装到 scripts/vendor/nodejs/（仅首次，需要网络）...`);
  fs.mkdirSync(VENDOR_NODE, { recursive: true });
  const pkg = path.join(VENDOR_NODE, 'package.json');
  if (!fs.existsSync(pkg)) {
    fs.writeFileSync(pkg, JSON.stringify({ name: 'sudoboard-skill-drivers', private: true, version: '1.0.0' }, null, 2));
  }
  const { execSync } = require('child_process');
  execSync(`npm install --no-audit --no-fund --loglevel=error ${name}`, {
    cwd: VENDOR_NODE, stdio: 'inherit', timeout: 180000,
  });
  const mod2 = tryRequire(name);
  if (!mod2) throw new Error(`driver_install_failed:${name}`);
  return mod2;
}

/** 按 DbConfig 创建执行器：query(sql) → {columns, rows}（QueryTable 形态）。 */
function createExecutor(db, boardDir) {
  const password = db.password || '';
  if (db.kind === 'sqlite') {
    let file = db.file || '';
    if (!path.isAbsolute(file)) file = path.join(boardDir, file);
    let DatabaseSync;
    try {
      ({ DatabaseSync } = require('node:sqlite'));
    } catch {
      throw new Error('sqlite 需要 Node >= 22.13（内置 node:sqlite）');
    }
    const conn = new DatabaseSync(file);
    return {
      async query(sql) {
        const rows = conn.prepare(sql).all();
        if (!rows.length) return { columns: [], rows: [] };
        const columns = Object.keys(rows[0]);
        return { columns, rows: rows.map((r) => columns.map((c) => r[c])) };
      },
      async close() { conn.close(); },
    };
  }
  if (db.kind === 'mysql') {
    const mysql = ensureDriver('mysql2');
    const conn = mysql.createConnection({
      host: db.host,
      port: db.port ?? 3306,
      user: db.username,
      password,
      database: db.database,
      dateStrings: true, // DATE/DATETIME 按字符串输出（贴近 Dart 驱动行为）
      connectTimeout: 10000,
      ...(db.secure ? { ssl: { rejectUnauthorized: false } } : {}),
    });
    conn.on('error', () => {}); // 连接层异步错误由 ready/query 的 reject 传递，避免进程崩溃
    const p = conn.promise();
    const ready = p.connect(); // 显式连接（失败 → 每个 query reject 同一错误）
    return {
      async query(sql) {
        await ready;
        const [rows] = await p.query(sql);
        const arr = Array.isArray(rows) ? rows : [rows];
        if (!arr.length) return { columns: [], rows: [] };
        const columns = Object.keys(arr[0]);
        return { columns, rows: arr.map((r) => columns.map((c) => r[c])) };
      },
      async close() { await ready.catch(() => {}); await p.end().catch(() => {}); },
    };
  }
  if (db.kind === 'pg') {
    const { Client } = ensureDriver('pg');
    const client = new Client({
      host: db.host,
      port: db.port ?? 5432,
      user: db.username,
      password,
      database: db.database,
      connectionTimeoutMillis: 10000,
    });
    client.on('error', () => {}); // 同上
    const ready = client.connect(); // ★ 必须显式连接：pg 不会在 query 时自动连
    return {
      async query(sql) {
        await ready;
        const res = await client.query(sql);
        if (!res.rows.length) return { columns: [], rows: [] };
        const columns = res.fields.map((f) => f.name);
        return { columns, rows: res.rows.map((r) => columns.map((c) => r[c])) };
      },
      async close() { await ready.catch(() => {}); await client.end().catch(() => {}); },
    };
  }
  throw new Error(`unsupported_db_kind:${db.kind}`);
}

/** DB 源：按命名查询执行（先过只读拦截），结果 → 命名值（对齐 _fetchDb 语义）。 */
async function runDbSource(key, payload, boardDir) {
  const db = payload.db;
  if (!db) {
    console.log(`✗ [${key}] db_config_missing`);
    return { ok: false, lastError: 'db_config_missing', values: {} };
  }
  const values = {};
  const errors = [];
  let anyError = false;
  let executor = null;
  try {
    executor = createExecutor(db, boardDir);
    for (const q of payload.queries || []) {
      const blocked = readOnlyGuardCheck(q.sql, db.readOnly !== false);
      if (blocked) {
        anyError = true;
        errors.push(`${q.name}:${blocked}`);
        console.log(`  ⛔ ${q.name}: ${blocked}`);
        continue;
      }
      try {
        const table = await executor.query(q.sql);
        values[q.name] = table;
        console.log(`  ✓ ${q.name}: ${table.columns.length} 列 × ${table.rows.length} 行`);
      } catch (e) {
        anyError = true;
        errors.push(`${q.name}:${e.message}`);
        console.log(`  ✗ ${q.name}: ${e.message}`);
      }
    }
  } catch (e) {
    console.log(`✗ [${key}] ${e.message || e}`);
    return { ok: false, lastError: String(e.message || e), values };
  } finally {
    if (executor) await executor.close().catch(() => {});
  }
  return { ok: !anyError, values, lastError: anyError ? errors.join(';') : null };
}

/* ================= 主流程 ================= */

async function main() {
  const dir = path.resolve(argVal('--dir', './sudoboard'));
  const out = path.resolve(argVal('--out', path.join(dir, 'preview', 'data.json')));
  const only = (argVal('--source', '') || '').split(',').map((s) => s.trim()).filter(Boolean);

  const boardPath = path.join(dir, 'board.json');
  if (!fs.existsSync(boardPath)) {
    console.error(`✗ 找不到 ${boardPath}`);
    process.exit(1);
  }
  const board = JSON.parse(fs.readFileSync(boardPath, 'utf8'));
  const sources = (board.sources || []).filter((s) => !only.length || only.includes(s.key));
  if (!sources.length) {
    console.error('✗ board.json 里没有可取数的数据源');
    process.exit(1);
  }

  // DB 驱动预检：缺失的纯 JS 驱动提前一次性安装
  const dbKinds = new Set(
    sources
      .filter((s) => (s.create || {}).type === 'db')
      .map((s) => (s.create.db || {}).kind),
  );
  for (const kind of dbKinds) {
    if (kind === 'mysql' || kind === 'pg') ensureDriver(kind === 'mysql' ? 'mysql2' : 'pg');
  }

  const values = {};
  const sourceStatus = {};
  let okCount = 0;

  for (const src of sources) {
    const key = src.key || '?';
    const payload = src.create || {};
    if (payload.type === 'db') {
      process.stdout.write(`🗄 [${key}] ${payload.db?.kind} ... \n`);
      const r = await runDbSource(key, payload, dir);
      for (const [k, v] of Object.entries(r.values)) {
        if (k in values) console.log(`  ⚠ 命名值 "${k}" 在多个源中重复，后者覆盖`);
        values[k] = v;
      }
      sourceStatus[key] = { ok: r.ok, lastError: r.lastError };
      if (r.ok) okCount++;
      continue;
    }
    if (payload.type !== 'http') {
      console.log(`⚠ [${key}] 未知类型 "${payload.type}"，跳过`);
      sourceStatus[key] = { ok: false, lastError: `unsupported_type:${payload.type}` };
      continue;
    }
    const f = payload.fetch || {};
    process.stdout.write(`↓ [${key}] ${(f.method || 'GET')} ${f.url} ... `);
    const snap = await fetchSource(payload);
    if (!snap.ok) {
      console.log(`✗ ${snap.lastError}`);
      sourceStatus[key] = { ok: false, lastError: snap.lastError };
      continue;
    }
    try {
      const extracted = await extract(snap.raw, payload.extractors);
      for (const [k, v] of Object.entries(extracted)) {
        if (k in values) console.log(`  ⚠ 命名值 "${k}" 在多个源中重复，后者覆盖`);
        values[k] = v;
      }
      sourceStatus[key] = { ok: true, lastError: null };
      okCount++;
      console.log(`✓ ${Object.keys(extracted).length} 个命名值: ${Object.keys(extracted)}`);
    } catch (e) {
      console.log(`✗ ${e.message}`);
      sourceStatus[key] = { ok: false, lastError: e.message };
    }
  }

  const theme = (board.board || {}).theme || 'dark';
  const data = {
    values,
    meta: {
      updatedAt: new Date().toISOString(),
      sourceStatus,
      theme,
    },
  };

  if (okCount === 0) {
    // 全部源失败：不落盘 —— 否则空的 values 会盖掉 board.json 的 demoData，
    // 让后续预览显示空看板（也保住上一次成功抓取的 data.json）。
    console.log(`⚠ 0/${sources.length} 源成功，未写入 ${out}（预览将沿用 demoData 或上一次快照）`);
    process.exit(1);
  }

  fs.mkdirSync(path.dirname(out), { recursive: true });
  const tmp = `${out}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2));
  fs.renameSync(tmp, out);

  console.log(`✓ 真实数据已写入 ${out}（${okCount}/${sources.length} 源成功，共 ${Object.keys(values).length} 个命名值）`);
  console.log('下一步: python3 build_preview.py --dir ... --open（渲染刚抓取的真实数据）');
  process.exit(0);
}

main().catch((e) => {
  console.error(`✗ ${e.message || e}`);
  process.exit(1);
});
