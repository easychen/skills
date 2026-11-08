#!/usr/bin/env node
/**
 * Ask4Me client for Agent Skills.
 *
 * Zero dependencies beyond Node 18+ (fetch / node:crypto).
 * Server: multi-user API key + per-request ServerChan notify + optional E2EE.
 */
import { randomBytes } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { preparePayload, decryptResult } from "./e2ee.mjs";

const TRIAL_BASE_URL = "https://ask.app.ft07.com";
const DEFAULT_BASE_URL = process.env.ASK4ME_BASE_URL || TRIAL_BASE_URL;
const DEFAULT_INVITE = "askd-2026";
const DEFAULT_EXPIRES = 600;
const USER_AGENT = "ask4me-skill/1.1.0";
const UPDATE_URLS = [
  process.env.ASK4ME_UPDATE_URL,
  "https://cdn.jsdelivr.net/gh/easychen/skills@main/ask4me/VERSION",
  "https://raw.githubusercontent.com/easychen/skills/main/ask4me/VERSION"
].filter(Boolean);
const CACHE_DIR = join(homedir(), ".cache", "ask4me");
const CACHE_FILE = join(CACHE_DIR, "state.json");
const DAY_MS = 24 * 60 * 60 * 1000;

function localVersion() {
  try {
    return readFileSync(new URL("../VERSION", import.meta.url), "utf8").trim();
  } catch {
    return "0.0.0";
  }
}

const LOCAL_VERSION = localVersion();


function usage() {
  process.stderr.write(`Ask4Me client

Usage:
  node scripts/ask4me.mjs keygen [--invite <invite>]
  node scripts/ask4me.mjs test [options]
  node scripts/ask4me.mjs ask  [options]
  node scripts/ask4me.mjs version

Default trial server: ${TRIAL_BASE_URL}
Default invite:      ${DEFAULT_INVITE}
This is a shared trial server. It may be unstable or lose data; self-host for production:
https://github.com/easychen/ask4me

Options:
  --base-url <url>          default: $ASK4ME_BASE_URL or ${DEFAULT_BASE_URL}
  --api-key <key>           default: $ASK4ME_API_KEY (a4m_<invite>_<random>)
  --notify-sendkey <key>    default: $ASK4ME_SERVERCHAN_SENDKEY or $SERVERCHAN_SENDKEY
  --title <text>            default: 需要你的确认
  --body <text>             default: 请打开链接查看并提交。
  --mcd <text>              MCD controls (buttons / input)
  --mcd-file <path>         read MCD from a file
  --jsonforms <path>        JSON Forms spec file: {schema,uischema,data,submit_label}
  --jsonforms-file <path>   alias of --jsonforms
  --expires <seconds>       default: 600
  --e2ee-password <pass>    default: $ASK4ME_E2EE_PASSWORD (optional)
  --no-e2ee                 do not encrypt even if ASK4ME_E2EE_PASSWORD is set
  --no-update-check         skip the daily GitHub version check
  --quiet                   suppress progress messages on stderr
  --json                    accepted for compatibility; output is always JSON
  -h, --help                show this help

Exit codes:
  0 submitted, 1 config/HTTP/notify failure, 2 expired or timeout

Examples:
  node scripts/ask4me.mjs keygen
  node scripts/ask4me.mjs ask --title "确认发布" --body "请确认" \\
    --mcd $':::buttons\\n- [OK](ok)\\n- [取消](cancel)\\n:::'
  node scripts/ask4me.mjs ask --title "填个表" --jsonforms ./form.json
`);
}

function fail(message, code = 1) {
  process.stderr.write(String(message).replace(/\n+$/, "") + "\n");
  process.exit(code);
}

function parseArgs(argv) {
  const out = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "-h" || arg === "--help") {
      out.help = true;
      continue;
    }
    if (arg === "--json") {
      out.json = true;
      continue;
    }
    if (arg === "--quiet") {
      out.quiet = true;
      continue;
    }
    if (arg === "--no-e2ee") {
      out.noE2ee = true;
      continue;
    }
    if (arg === "--no-update-check") {
      out.noUpdateCheck = true;
      continue;
    }
    if (arg.startsWith("--")) {
      const key = arg.slice(2);
      const next = argv[i + 1];
      if (next === undefined || next.startsWith("--")) {
        out[key] = true;
      } else {
        out[key] = next;
        i++;
      }
      continue;
    }
    out._.push(arg);
  }
  return out;
}

function validateInvite(invite) {
  if (!/^[A-Za-z0-9-]{4,64}$/.test(invite)) {
    fail("邀请码格式不对：只允许 A-Z a-z 0-9 -，长度 4-64，不能包含下划线。");
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function* readSSE(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, idx).replace(/\r$/, "");
      buffer = buffer.slice(idx + 1);
      if (!line.startsWith("data:")) continue;
      const data = line.slice(5).trimStart();
      if (data === "[DONE]") return;
      if (!data) continue;
      try {
        yield JSON.parse(data);
      } catch {
        // Ignore malformed SSE lines.
      }
    }
  }
}

function readTextFile(path, label) {
  try {
    return readFileSync(path, "utf8");
  } catch (err) {
    fail(`${label} 读取失败：${err.message}`);
  }
}

function readJSONFile(path, label) {
  const text = readTextFile(path, label);
  try {
    return JSON.parse(text);
  } catch (err) {
    fail(`${label} 不是合法 JSON：${err.message}`);
  }
}

function readCache() {
  try {
    return JSON.parse(readFileSync(CACHE_FILE, "utf8"));
  } catch {
    return {};
  }
}

function writeCache(value) {
  try {
    mkdirSync(CACHE_DIR, { recursive: true });
    writeFileSync(CACHE_FILE, JSON.stringify(value));
  } catch {
    // A read-only home is fine; update checks simply won't be throttled.
  }
}

function compareVersions(a, b) {
  const pa = String(a).split(".").map((x) => Number(x) || 0);
  const pb = String(b).split(".").map((x) => Number(x) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] || 0;
    const y = pb[i] || 0;
    if (x !== y) return x > y ? 1 : -1;
  }
  return 0;
}

async function fetchText(url, timeoutMs = 1500) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      headers: { "User-Agent": USER_AGENT }
    });
    if (!response.ok) return null;
    return (await response.text()).trim();
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Once per day: remind trial users, and check GitHub for a newer skill version.
 * Never fails the request; network errors are ignored.
 */
async function maybeCheckUpdate(baseUrl, options = {}) {
  const { test = false, noUpdateCheck = false } = options;
  const now = Date.now();
  const cache = readCache();
  const normalizedBase = String(baseUrl || "").replace(/\/+$/, "");
  const isTrial = normalizedBase === TRIAL_BASE_URL;

  if (
    isTrial &&
    process.env.ASK4ME_NO_TRIAL_NOTICE !== "1" &&
    (test || now - Number(cache.trial_notice_at || 0) >= DAY_MS)
  ) {
    process.stderr.write(
      "[Ask4Me] 这是公共试用服务器 ask.app.ft07.com：可能不稳定、限流或清理数据，请不要放长期/敏感数据。\n" +
        "[Ask4Me] 正式使用或遇到问题，请自建独立服务器：https://github.com/easychen/ask4me\n"
    );
    cache.trial_notice_at = now;
  }

  if (process.env.ASK4ME_NO_UPDATE_CHECK === "1" || noUpdateCheck) {
    writeCache(cache);
    return;
  }
  if (cache.checked_at && now - Number(cache.checked_at) < DAY_MS) {
    writeCache(cache);
    return;
  }

  let latest = null;
  for (const url of UPDATE_URLS) {
    const value = await fetchText(url);
    if (value && /^\d+\.\d+\.\d+$/.test(value)) {
      latest = value;
      break;
    }
  }

  cache.checked_at = now;
  if (latest) cache.latest = latest;
  writeCache(cache);

  if (latest && compareVersions(latest, LOCAL_VERSION) > 0 && cache.notified_version !== latest) {
    process.stderr.write(
      `[Ask4Me] 发现 skill 新版本 ${latest}（当前 ${LOCAL_VERSION}）。\n` +
        "[Ask4Me] 更新：npx skills add easychen/skills --skill ask4me\n"
    );
    cache.notified_version = latest;
    writeCache(cache);
  }
}

function httpError(status, body) {
  if (status === 401) {
    return new Error("401 Unauthorized：API key 无效或邀请码已更换，请重新 keygen。");
  }
  if (status === 429) {
    return new Error(`429 配额已满：${body || "请稍后再试"}`);
  }
  if (status >= 400 && status < 500) {
    return new Error(`${status} 请求被拒绝：${body || "检查参数"}`);
  }
  return new Error(`${status} 服务端错误：${body || "unknown"}`);
}

function defaultMCD() {
  return ":::buttons\n- [OK](ok)\n- [取消](cancel)\n:::";
}

function defaultPayload(args) {
  const title = (args.title && String(args.title)) || "需要你的确认";
  const body = (args.body && String(args.body)) || "请打开链接查看并提交。";

  const jsonformsPath = args.jsonforms || args["jsonforms-file"];
  const mcdPath = args["mcd-file"];
  if (jsonformsPath && (args.mcd || mcdPath)) {
    fail("--jsonforms 和 --mcd 不能同时使用。");
  }

  const payload = {
    title,
    body,
    notify: {},
    serverchan_action_links: true,
    expires_in_seconds: Number(args.expires || process.env.ASK4ME_EXPIRES || DEFAULT_EXPIRES)
  };

  if (jsonformsPath) {
    const spec = readJSONFile(jsonformsPath, "JSON Forms 文件");
    if (!spec || typeof spec !== "object" || !spec.schema) {
      fail("JSON Forms 文件必须包含 schema。");
    }
    payload.jsonforms = spec;
  } else {
    const mcd = mcdPath ? readTextFile(mcdPath, "MCD 文件") : args.mcd;
    payload.mcd = typeof mcd === "string" && mcd.trim() ? mcd : defaultMCD();
  }

  if (!Number.isFinite(payload.expires_in_seconds) || payload.expires_in_seconds < 30) {
    fail("--expires 必须是 >=30 的秒数。");
  }
  return payload;
}

function resolveConfig(args) {
  const baseUrl = String(
    args["base-url"] || process.env.ASK4ME_BASE_URL || DEFAULT_BASE_URL
  ).replace(/\/+$/, "");
  if (!/^https?:\/\//i.test(baseUrl)) {
    fail("--base-url 必须以 http:// 或 https:// 开头。");
  }

  const apiKey = String(args["api-key"] || process.env.ASK4ME_API_KEY || "").trim();
  if (!apiKey) {
    fail(
      "缺少 ASK4ME_API_KEY。\n" +
        "先运行：node scripts/ask4me.mjs keygen\n" +
        "（默认邀请码 askd-2026；自有服务器用 --invite <邀请码>）\n" +
        "把输出保存到当前项目的环境变量 ASK4ME_API_KEY（不要提交到仓库）。"
    );
  }

  const sendkey = String(
    args["notify-sendkey"] ||
      process.env.ASK4ME_SERVERCHAN_SENDKEY ||
      process.env.SERVERCHAN_SENDKEY ||
      ""
  ).trim();
  if (!sendkey) {
    fail(
      "缺少 ServerChan SendKey。\n" +
        "没有的话去 https://sct.ftqq.com/ 申请，保存到 ASK4ME_SERVERCHAN_SENDKEY。\n" +
        "多用户服务器要求每次请求带 notify，不能使用服务端全局渠道。"
    );
  }

  const e2eePassword = args.noE2ee
    ? ""
    : String(
        args["e2ee-password"] ?? process.env.ASK4ME_E2EE_PASSWORD ?? ""
      );

  return { baseUrl, apiKey, sendkey, e2eePassword };
}

async function runAsk(args) {
  const { baseUrl, apiKey, sendkey, e2eePassword } = resolveConfig(args);
  const quiet = Boolean(args.quiet);
  const info = (message) => {
    if (!quiet) process.stderr.write(message.replace(/\n+$/, "") + "\n");
  };

  let payload = defaultPayload(args);
  payload.notify = { serverchan_sendkey: sendkey };

  let e2eeKey = null;
  if (e2eePassword) {
    const prepared = preparePayload(payload, e2eePassword);
    payload = prepared.payload;
    e2eeKey = prepared.key;
    info("已启用端到端加密（E2EE）；口令不会被发送到服务端。");
  }

  const controller = new AbortController();
  const timeoutMs = (payload.expires_in_seconds + 30) * 1000;
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  let requestId = null;
  let lastEventId = null;
  let interactionURL = null;
  let attempts = 0;

  try {
    while (true) {
      const url = new URL(`${baseUrl}/v1/ask`);
      url.searchParams.set("stream", "true");
      if (requestId) url.searchParams.set("request_id", requestId);
      if (lastEventId) url.searchParams.set("last_event_id", lastEventId);

      const response = await fetch(url, {
        method: "POST",
        headers: {
          Accept: "text/event-stream",
          "Content-Type": "application/json",
          Authorization: `Bearer ${apiKey}`,
          "User-Agent": USER_AGENT
        },
        body: requestId ? null : JSON.stringify(payload),
        signal: controller.signal
      });

      if (!response.ok) {
        const text = await response.text().catch(() => "");
        throw httpError(response.status, text);
      }
      if (!requestId) {
        requestId = response.headers.get("x-ask4me-request-id") || null;
      }

      for await (const ev of readSSE(response)) {
        if (!ev || typeof ev !== "object") continue;
        if (ev.id) lastEventId = ev.id;
        if (ev.request_id && !requestId) requestId = ev.request_id;

        if (ev.type === "request.created") {
          interactionURL = ev.data?.interaction_url || interactionURL;
          info(`请求已创建：${requestId || ev.request_id || "unknown"}`);
          if (interactionURL) info(`打开链接或查看通知：${interactionURL}`);
          continue;
        }

        if (ev.type === "notify.sent") {
          info("通知已发送，等待对方提交...");
          continue;
        }

        if (ev.type === "notify.failed") {
          const message = ev.data?.error || "unknown";
          process.stderr.write(`通知发送失败：${message}\n`);
          if (interactionURL) {
            process.stderr.write(`仍可手动打开链接：${interactionURL}\n`);
          }
          const out = {
            request_id: requestId,
            last_event_type: "notify.failed",
            data: ev.data || {},
            interaction_url: interactionURL
          };
          process.stdout.write(JSON.stringify(out, null, 2) + "\n");
          process.exitCode = 1;
          return;
        }

        if (ev.type === "user.submitted") {
          let data = ev.data || {};
          if (e2eeKey) {
            try {
              data = decryptResult(data, e2eeKey);
            } catch (err) {
              throw new Error(`回答解密失败：${err.message}`);
            }
          }
          const out = {
            request_id: requestId,
            last_event_type: "user.submitted",
            data
          };
          process.stdout.write(JSON.stringify(out, null, 2) + "\n");
          process.exitCode = 0;
          return;
        }

        if (ev.type === "request.expired") {
          process.stderr.write("请求已过期，对方没有提交。\n");
          const out = {
            request_id: requestId,
            last_event_type: "request.expired",
            data: ev.data || {},
            interaction_url: interactionURL
          };
          process.stdout.write(JSON.stringify(out, null, 2) + "\n");
          process.exitCode = 2;
          return;
        }
      }

      if (attempts++ >= 3) {
        throw new Error("SSE 连接中断，重试次数用尽。");
      }
      await sleep(500);
    }
  } catch (err) {
    if (err && err.name === "AbortError") {
      process.stderr.write("等待超时。\n");
      process.exitCode = 2;
    } else {
      process.stderr.write(`${err.message}\n`);
      process.exitCode = 1;
    }
    if (interactionURL) {
      process.stderr.write(`链接：${interactionURL}\n`);
    }
  } finally {
    clearTimeout(timer);
  }
}

function keygen(args) {
  const invite = String(args.invite || process.env.ASK4ME_INVITE || DEFAULT_INVITE).trim();
  validateInvite(invite);
  process.stdout.write(`a4m_${invite}_${randomBytes(16).toString("hex")}\n`);
}

async function main() {
  const nodeMajor = Number(process.versions.node.split(".")[0]);
  if (!Number.isFinite(nodeMajor) || nodeMajor < 18) {
    fail(`需要 Node.js 18+，当前是 ${process.version}。`);
  }

  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    usage();
    return;
  }
  const command = args._[0] || "ask";
  if (command === "version") {
    process.stdout.write(LOCAL_VERSION + "\n");
    return;
  }
  if (command === "keygen") {
    keygen(args);
    return;
  }
  if (command === "ask" || command === "test") {
    const baseUrl = String(
      args["base-url"] || process.env.ASK4ME_BASE_URL || DEFAULT_BASE_URL
    ).replace(/\/+$/, "");
    await maybeCheckUpdate(baseUrl, {
      test: command === "test",
      noUpdateCheck: Boolean(args.noUpdateCheck)
    });
    if (command === "test") {
      args.title = args.title || "Ask4Me 配置测试";
      args.body = args.body || "收到请点 OK，确认 Ask4Me 链路正常。";
      if (!args.mcd && !args["mcd-file"] && !args.jsonforms && !args["jsonforms-file"]) {
        args.mcd = defaultMCD();
      }
    }
    await runAsk(args);
    return;
  }
  usage();
  process.exitCode = 1;
}

main().catch((err) => {
  process.stderr.write(`${err?.message || err}\n`);
  process.exitCode = 1;
});
