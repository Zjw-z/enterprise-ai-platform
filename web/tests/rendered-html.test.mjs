import assert from "node:assert/strict";
import { access, readFile, readdir } from "node:fs/promises";
import test from "node:test";

test("builds the enterprise platform server and client assets", async () => {
  const serverEntry = new URL("../dist/server/index.js", import.meta.url);
  const clientAssets = new URL("../dist/client/assets/", import.meta.url);

  await access(serverEntry);
  const files = await readdir(clientAssets);
  assert.ok(files.some((file) => file.endsWith(".js")));
  assert.ok(files.some((file) => file.endsWith(".css")));

  const serverSource = await readFile(serverEntry, "utf8");
  assert.match(serverSource, /Enterprise AI Platform/);
  assert.match(serverSource, /export\s*\{/);
  assert.doesNotMatch(serverSource, /cloudflare:workers/);
});

test("keeps management and business routes in the unified console", async () => {
  const [source, layout, viteConfig] = await Promise.all([
    readFile(
      new URL("../app/platform-console.tsx", import.meta.url),
      "utf8",
    ),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../vite.config.ts", import.meta.url), "utf8"),
  ]);

  assert.match(source, /"\/system\/users"/);
  assert.match(source, /"\/system\/roles"/);
  assert.match(source, /"\/system\/menus"/);
  assert.match(source, /"\/runtime\/tasks"/);
  assert.match(source, /"\/ai\/approvals"/);
  assert.match(source, /"\/business\/weather"/);
  assert.match(source, /agent:\s*"weather-agent"/);
  assert.match(source, /api\.request<MenuNode\[]>\("\/v1\/me\/menus"\)/);
  assert.match(layout, /企业级 AI Agent 平台/);
  assert.match(viteConfig, /plugins:\s*\[vinext\(\)\]/);
  assert.doesNotMatch(viteConfig, /sites|cloudflare|wrangler/i);
});

test("prompt creation supports persisted variable defaults", async () => {
  const source = await readFile(
    new URL("../app/platform-console.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /name="variable_defaults"/);
  assert.match(source, /default:\s*defaults\[name\]/);
  assert.match(source, /评测和调试输入框会自动填入这些默认值/);
});

test("task timeline renders knowledge retrieval chunks", async () => {
  const source = await readFile(
    new URL("../app/console-support.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /"knowledge\.retrieve"/);
  assert.match(source, /查看召回文本块/);
  assert.match(source, /rerank_score/);
  assert.match(source, /vector_score/);
});

test("task timeline explains LLM rounds and Tool batch mode", async () => {
  const source = await readFile(
    new URL("../app/console-support.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /"tool\.batch"/);
  assert.match(source, /第.*轮.*Token/);
  assert.match(source, /并行执行|串行执行/);
});

test("agent evaluation switches between dataset and temporary case modes", async () => {
  const source = await readFile(
    new URL("../app/platform-console.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /selectedEvaluationDatasetId/);
  assert.match(source, /!selectedEvaluationDatasetId.*临时测试输入/s);
  assert.match(source, /已选择评测数据集/);
});

test("model detail imports the shared status translator", async () => {
  const source = await readFile(
    new URL("../app/platform-console.tsx", import.meta.url),
    "utf8",
  );

  assert.match(
    source,
    /import\s*\{[\s\S]*?translatedStatus[\s\S]*?\}\s*from\s*"\.\/console-support";/,
  );
  assert.match(source, /translatedStatus\(viewingModel\.version\.status\)/);
});

test("knowledge search always reports loading, failure, and empty-result states", async () => {
  const source = await readFile(
    new URL("../app/platform-console.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /const \[searching, setSearching\]/);
  assert.match(source, /const \[searchError, setSearchError\]/);
  assert.match(source, /setSearchError\(/);
  assert.match(source, /检索请求失败/);
  assert.match(source, /未召回相关文本块/);
  assert.match(source, /返回结果数量（TopK）/);
  assert.match(source, /limit: searchLimit/);
  assert.match(source, /Milvus 召回/);
  assert.match(source, /Reranker/);
  assert.match(source, /searchCompletedAt/);
});

test("exposes smart routing and the AI application directory", async () => {
  const source = await readFile(
    new URL("../app/platform-console.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /function SmartAssistantPage/);
  assert.match(source, /\/v1\/assistant\/execute/);
  assert.match(source, /function AIApplicationDirectory/);
  assert.match(source, /path === "\/assistant"/);
  assert.match(source, /path === "\/applications"/);
});

test("renders application entry decisions in the task trace", async () => {
  const source = await readFile(
    new URL("../app/console-support.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /traceMetadata\.entry_mode === "assistant"/);
  assert.match(source, /traceMetadata\.routed_application/);
  assert.match(source, /traceMetadata\.entry_mode === "application"/);
});

test("workspace dialogs stay inside the active main canvas", async () => {
  const styles = await readFile(
    new URL("../app/globals.css", import.meta.url),
    "utf8",
  );

  assert.match(styles, /--workspace-modal-left:\s*240px/);
  assert.match(styles, /--workspace-modal-left:\s*64px/);
  assert.match(
    styles,
    /inset:\s*8px 8px 8px var\(--workspace-modal-left,\s*240px\)/,
  );
  assert.match(styles, /max-height:\s*calc\(100% - 64px\)/);
});
