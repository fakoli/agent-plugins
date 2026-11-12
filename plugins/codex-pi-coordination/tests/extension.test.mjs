import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { createHash } from "node:crypto";
import extension, { checkToolPath, loadTask } from "../extensions/coordination.js";

function fixture(t, changes = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "coordination-extension-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const workspace = path.join(root, "workspace");
  const output = path.join(root, "output");
  fs.mkdirSync(workspace);
  fs.mkdirSync(output);
  fs.writeFileSync(path.join(workspace, "input.txt"), "original\n");
  const taskPath = path.join(root, "task.json");
  const task = { version: 1, run_id: "run-01", task_id: "task-01", kind: "review", instructions: "Inspect the supplied input and report limitations.", workspace, output_directory: output, allowed_tools: ["read", "grep", "find", "ls"], writable_paths: [], max_tool_calls: 8, ...changes };
  fs.writeFileSync(taskPath, JSON.stringify(task));
  return { root, task, taskPath, workspace, output };
}

function runtime(taskPath, cwd, allowedTools) {
  const handlers = new Map();
  const tools = new Map();
  const commands = new Map();
  let active = ["read", "grep", "find", "ls", "write", "edit", "bash", "coordination_status", "coordination_handoff"];
  const ctx = { cwd, hasUI: false, model: { provider: "fixture-provider", id: "fixture-model" }, aborted: 0, shutdowns: 0, abort() { this.aborted += 1; }, shutdown() { this.shutdowns += 1; } };
  const pi = {
    registerFlag() {}, getFlag: () => taskPath,
    registerTool: (tool) => tools.set(tool.name, tool),
    registerCommand: (name, command) => commands.set(name, command),
    on: (name, handler) => handlers.set(name, handler),
    getActiveTools: () => active,
    getThinkingLevel: () => ctx.thinking ?? "high",
    setActiveTools: (names) => { active = allowedTools ? names.filter((name) => allowedTools.includes(name)) : names; },
  };
  extension(pi);
  return {
    ctx, tools, commands,
    active: () => active,
    emit: async (name, event = {}) => handlers.get(name)?.(event, ctx),
    async call(toolName, input = {}) {
      const event = { toolName, input, toolCallId: "call-" + toolName };
      const decision = await handlers.get("tool_call")(event, ctx);
      if (decision?.block) return decision;
      return tools.has(toolName) ? tools.get(toolName).execute(event.toolCallId, input, undefined, undefined, ctx) : { permitted: true, path: event.input.path };
    },
  };
}

const handoff = (changed_files = []) => ({ status: "completed", summary: "Inspected the provided fixture.", evidence: ["input.txt"], changed_files, limitations: ["Model self-report; external checks remain required."] });
const events = (f) => fs.readFileSync(path.join(f.output, "extension-events.jsonl"), "utf8").trim().split("\n").map(JSON.parse);

test("versioned task IDs preserve legacy native run IDs and reject unsupported options", async (t) => {
  for (const version of [1, 2]) {
    const maximum = version === 1 ? 80 : 128;
    const base = { version, ...(version === 2 ? { operation: "run", run_options: {}, runtime_defaults: { model: "fixture-provider/fixture-model", thinking: "high" } } : {}) };
    const f = fixture(t, { ...base, task_id: "t".repeat(maximum), run_id: "run:" + "r".repeat(124) });
    assert.equal(loadTask(f.taskPath, f.workspace).task.run_id.length, 128);
    const r = runtime(f.taskPath, f.workspace);
    await r.emit("session_start");
    assert.ok((await r.emit("before_agent_start", { systemPrompt: "original" })).systemPrompt);
    assert.equal(r.ctx.aborted, 0);
    await r.emit("session_shutdown");
    for (const [field, invalid] of [["task_id", "t".repeat(maximum + 1)], ["task_id", "task-one\n"], ["task_id", "task-one\r\n"], ["run_id", "r".repeat(129)], ["run_id", "run-one\n"], ["run_id", "run-one\r\n"]]) {
      const invalidFixture = fixture(t, { ...base, [field]: invalid });
      assert.throws(() => loadTask(invalidFixture.taskPath, invalidFixture.workspace), new RegExp(field));
    }
    const namespaced = fixture(t, { ...base, task_id: "project:T001" });
    if (version === 1) {
      assert.throws(() => loadTask(namespaced.taskPath, namespaced.workspace), /task_id/);
      for (const run_options of [{}, { thinking: "low" }, null]) {
        const invalidFixture = fixture(t, { ...base, run_options });
        assert.throws(() => loadTask(invalidFixture.taskPath, invalidFixture.workspace), /run_options/);
      }
    } else {
      assert.equal(loadTask(namespaced.taskPath, namespaced.workspace).task.task_id, "project:T001");
    }
  }
});

test("v2 binds namespaced scope and actual options before model work", async (t) => {
  const f = fixture(t, { version: 2, task_id: "project:T001", operation: "run", run_options: { thinking: "low" }, runtime_defaults: { model: "fixture-provider/fixture-model", thinking: "high" } });
  const r = runtime(f.taskPath, f.workspace);
  r.ctx.thinking = "low";
  await r.emit("session_start");
  await r.emit("before_agent_start", { systemPrompt: "original" });
  await r.emit("before_agent_start", { systemPrompt: "original" });
  assert.deepEqual(events(f).map((event) => event.type), ["task_loaded", "run_configuration"]);
  assert.deepEqual(events(f)[1].configuration, { provider: "fixture-provider", model: "fixture-model", thinking: "low" });
  await r.emit("session_shutdown");
});

test("v2 rejects malformed options and mismatched effective model or thinking", async (t) => {
  const base = { version: 2, operation: "run", run_options: {}, runtime_defaults: { model: "fixture-provider/fixture-model", thinking: "high" } };
  for (const run_options of [{ model: "unpaired" }, { provider: "unpaired" }, { thinking: "auto" }, { thinking: "dynamic" }, { thinking: "default" }, { extra: "value" }]) {
    const f = fixture(t, { ...base, run_options });
    assert.throws(() => loadTask(f.taskPath, f.workspace), /run options/);
  }
  for (const changes of [{ model: { provider: "foreign", id: "model" } }, { thinking: "low" }]) {
    const f = fixture(t, base);
    const r = runtime(f.taskPath, f.workspace);
    Object.assign(r.ctx, changes);
    await r.emit("session_start");
    assert.equal(await r.emit("before_agent_start", { systemPrompt: "original" }), undefined);
    assert.equal(r.ctx.aborted, 1);
    assert.equal(events(f).at(-1).code, "configuration_mismatch");
    assert.equal(fs.existsSync(path.join(f.output, "model-report.json")), false);
    await r.emit("session_shutdown");
  }
});

test("explicit provider and model identifiers remain separate across slash boundaries", async (t) => {
  for (const actual of [{ provider: "one", id: "two/three" }, { provider: "one/two", id: "three" }]) {
    const f = fixture(t, { version: 2, operation: "run", run_options: { provider: "one/two", model: "three" }, runtime_defaults: { model: "one/two/three", thinking: "high" } });
    const r = runtime(f.taskPath, f.workspace);
    r.ctx.model = actual;
    await r.emit("session_start");
    const prompt = await r.emit("before_agent_start", { systemPrompt: "original" });
    if (actual.provider === "one/two") {
      assert.ok(prompt.systemPrompt);
      assert.equal(events(f).at(-1).type, "run_configuration");
    } else {
      assert.equal(prompt, undefined);
      assert.equal(r.ctx.aborted, 1);
      assert.equal(events(f).at(-1).code, "configuration_mismatch");
    }
    await r.emit("session_shutdown");
  }
});

test("qualified defaults load and reach the pre-prompt guard at both component bounds", async (t) => {
  for (const [provider, id] of [["fixture-provider", "fixture-model"], ["p", "m".repeat(255)], ["p".repeat(256), "m".repeat(256)], ["a/" + "b".repeat(254), "c/" + "d".repeat(254)]]) {
    const f = fixture(t, { version: 2, operation: "run", run_options: {}, runtime_defaults: { model: `${provider}/${id}`, thinking: "high" } });
    assert.equal(loadTask(f.taskPath, f.workspace).task.runtime_defaults.model, `${provider}/${id}`);
    const r = runtime(f.taskPath, f.workspace);
    r.ctx.model = { provider, id };
    await r.emit("session_start");
    assert.ok((await r.emit("before_agent_start", { systemPrompt: "original" })).systemPrompt);
    assert.equal(r.ctx.aborted, 0);
    assert.deepEqual(events(f).at(-1).configuration, { provider, model: id, thinking: "high" });
    await r.emit("session_shutdown");
  }
});

test("qualified defaults reject malformed or overlong components without relaxing explicit options", (t) => {
  const base = { version: 2, operation: "run", run_options: {}, runtime_defaults: { model: "p/m", thinking: "high" } };
  for (const model of [null, "", "bare", "p/", "/m", "_p/m", "p/_m", "https://example/model", "p/m\n", "p/m\r\n", "p/bad model", "p".repeat(257) + "/m", "p/" + "m".repeat(257), "p".repeat(256) + "/" + "m".repeat(257)]) {
    const f = fixture(t, { ...base, runtime_defaults: { model, thinking: "high" } });
    assert.throws(() => loadTask(f.taskPath, f.workspace), /runtime defaults/);
    assert.deepEqual(fs.readdirSync(f.output), []);
  }
  for (const run_options of [{ provider: "p".repeat(257), model: "m" }, { provider: "p", model: "m".repeat(257) }, { provider: "p\n", model: "m" }, { provider: "p", model: "m\n" }]) {
    const f = fixture(t, { ...base, run_options });
    assert.throws(() => loadTask(f.taskPath, f.workspace), /run options/);
  }
});

test("each task kind injects context and returns a bound self-report without acceptance", async (t) => {
  for (const kind of ["implementation", "research", "review", "validation"]) {
    await t.test(kind, async (t) => {
      const writable = kind === "implementation" || kind === "research";
      const f = fixture(t, { kind, allowed_tools: writable ? ["read", "write"] : ["read"], writable_paths: writable ? ["answer.txt"] : [] });
      const r = runtime(f.taskPath, f.workspace);
      await r.emit("session_start");
      assert.deepEqual(r.active(), [...f.task.allowed_tools, "coordination_status", "coordination_handoff"]);
      const prompt = await r.emit("before_agent_start", { systemPrompt: "Original system" });
      assert.match(prompt.systemPrompt, /Original system/);
      assert.ok(prompt.systemPrompt.includes(f.task.instructions));
      await r.emit("turn_start");
      const read = await r.call("read", { path: "input.txt" });
      assert.equal(read.path, path.join(f.workspace, "input.txt"));
      if (writable) assert.equal((await r.call("write", { path: "answer.txt", content: "answer" })).permitted, true);
      const result = await r.call("coordination_handoff", handoff(writable ? ["answer.txt"] : []));
      assert.equal(result.details.acceptance, "not_granted");
      await r.emit("agent_settled");
      await r.emit("session_shutdown");
      const report = JSON.parse(fs.readFileSync(path.join(f.output, "model-report.json"), "utf8"));
      assert.equal(report.run_id, f.task.run_id);
      assert.equal(report.task_id, f.task.task_id);
      assert.equal(report.model_self_report, true);
      assert.equal(report.task_sha256, loadTask(f.taskPath, f.workspace).taskSha256);
      assert.deepEqual(events(f).filter((e) => ["task_loaded", "handoff", "agent_settled", "session_shutdown"].includes(e.type)).map((e) => e.type), ["task_loaded", "handoff", "agent_settled", "session_shutdown"]);
    });
  }
});

test("absent task is inert; invalid requested task refuses without a success artifact", async (t) => {
  const f = fixture(t);
  const idle = runtime(undefined, f.workspace);
  await idle.emit("session_start");
  assert.ok(!idle.active().includes("coordination_handoff"));
  assert.equal(idle.ctx.shutdowns, 0);
  assert.equal(await idle.emit("before_agent_start", { systemPrompt: "normal" }), undefined);
  assert.deepEqual(fs.readdirSync(f.output), []);
  fs.writeFileSync(f.taskPath, JSON.stringify({ ...f.task, allowed_tools: ["bash"] }));
  const invalid = runtime(f.taskPath, f.workspace);
  await invalid.emit("session_start");
  assert.equal(invalid.ctx.shutdowns, 1);
  assert.equal((await invalid.call("read", { path: "input.txt" })).block, true);
  assert.ok(!fs.existsSync(path.join(f.output, "model-report.json")));
  fs.writeFileSync(f.taskPath, JSON.stringify({ ...f.task, source: { kind: "git", commit: "not-an-object-id", files: {} } }));
  const invalidSource = runtime(f.taskPath, f.workspace);
  await invalidSource.emit("session_start");
  assert.equal(invalidSource.ctx.shutdowns, 1);
  assert.deepEqual(fs.readdirSync(f.output), []);
});

test("large source manifests stay in the control file while the prompt carries their identity", async (t) => {
  const files = Object.fromEntries(Array.from({ length: 1000 }, (_, index) => [`src/fixture-file-${index}.txt`, "a".repeat(64)]));
  const modes = Object.fromEntries(Object.keys(files).map((name) => [name, 0o644]));
  const source = { kind: "git", commit: "c".repeat(40), files, modes };
  const f = fixture(t, { source });
  assert.ok(fs.statSync(f.taskPath).size > 65536);
  const r = runtime(f.taskPath, f.workspace);
  await r.emit("session_start");
  assert.equal(r.ctx.shutdowns, 0);
  const { systemPrompt } = await r.emit("before_agent_start", { systemPrompt: "Original system" });
  const injected = JSON.parse(systemPrompt.split("\n").find((line) => line.startsWith("{")));
  const canonicalManifest = { files: Object.keys(files).sort().map((name) => [name, files[name]]), modes: Object.keys(modes).sort().map((name) => [name, modes[name]]) };
  assert.deepEqual(injected.source, { kind: "git", commit: source.commit, file_count: 1000, manifest_sha256: createHash("sha256").update(JSON.stringify(canonicalManifest)).digest("hex") });
  assert.ok(systemPrompt.length < 2000);
  assert.ok(!systemPrompt.includes("fixture-file-"));
  assert.deepEqual(JSON.parse(fs.readFileSync(f.taskPath, "utf8")).source, source);
  await r.emit("session_shutdown");
});

test("native CLI tool filtering refuses missing handoff tools before task execution", async (t) => {
  const f = fixture(t);
  const r = runtime(f.taskPath, f.workspace, f.task.allowed_tools);
  await r.emit("session_start");
  assert.equal(r.ctx.aborted, 1);
  assert.equal(r.ctx.shutdowns, 1);
  assert.equal(events(f)[0].code, "unavailable_tools");
  assert.match(events(f)[0].message, /coordination_status, coordination_handoff/);
  assert.equal(events(f).some((event) => event.type === "task_loaded"), false);
  assert.equal(await r.emit("before_agent_start", { systemPrompt: "normal" }), undefined);
  assert.equal((await r.call("read", { path: "input.txt" })).block, true);
  assert.equal(fs.existsSync(path.join(f.output, "model-report.json")), false);
  await r.emit("session_shutdown");
});

test("task controls and all tool reads/writes remain outside the model's path authority", async (t) => {
  const f = fixture(t, { allowed_tools: ["read", "write"], writable_paths: ["answer.txt"] });
  const task = loadTask(f.taskPath, f.workspace).task;
  for (const name of ["read", "grep", "find", "ls", "write", "edit"]) {
    assert.throws(() => checkToolPath(task, name, { path: f.taskPath }), /inside the assigned workspace/);
    assert.throws(() => checkToolPath(task, name, { path: "../output/model-report.json" }), /inside the assigned workspace/);
  }
  assert.throws(() => checkToolPath(task, "write", { path: "input.txt" }), /declared writable/);
  assert.equal(checkToolPath(task, "write", { path: "answer.txt" }), path.join(f.workspace, "answer.txt"));
  fs.symlinkSync(f.taskPath, path.join(f.workspace, "linked.json"));
  assert.throws(() => checkToolPath(task, "read", { path: "linked.json" }), /Symbolic-link/);
  assert.throws(() => checkToolPath(task, "read", { path: "input\u00a0.txt" }), /Unicode-space/);
  const r = runtime(f.taskPath, f.workspace);
  await r.emit("session_start");
  const denied = await r.call("read", { path: f.taskPath });
  assert.equal(denied.block, true);
  assert.equal(r.ctx.shutdowns, 1);
  await r.emit("session_shutdown");
  assert.equal(events(f).at(-2).code, "forbidden_path");
});

test("the checked absolute path is passed to Pi without alternate path expansion", async (t) => {
  const f = fixture(t, { allowed_tools: ["write"], writable_paths: ["~/answer.txt", "@answer.txt", "file:/answer.txt"] });
  const r = runtime(f.taskPath, f.workspace);
  await r.emit("session_start");
  for (const name of f.task.writable_paths) {
    const result = await r.call("write", { path: name });
    assert.equal(result.path, path.join(f.workspace, name));
    assert.ok(path.isAbsolute(result.path));
  }
  await r.emit("session_shutdown");
});

test("exclusive event and report files preserve prior evidence and forbid work after handoff", async (t) => {
  const f = fixture(t);
  const first = runtime(f.taskPath, f.workspace);
  await first.emit("session_start");
  const before = fs.readFileSync(path.join(f.output, "extension-events.jsonl"));
  const duplicate = runtime(f.taskPath, f.workspace);
  await duplicate.emit("session_start");
  assert.equal(duplicate.ctx.shutdowns, 1);
  assert.deepEqual(fs.readFileSync(path.join(f.output, "extension-events.jsonl")), before);
  await first.call("coordination_handoff", { ...handoff(), model_self_report: false, version: 99 });
  const original = fs.readFileSync(path.join(f.output, "model-report.json"));
  assert.equal(JSON.parse(original).model_self_report, true);
  assert.equal(JSON.parse(original).version, 1);
  assert.equal((await first.call("read", { path: "input.txt" })).block, true);
  await assert.rejects(() => first.tools.get("coordination_handoff").execute("again", handoff()), /No active unfinished/);
  assert.deepEqual(fs.readFileSync(path.join(f.output, "model-report.json")), original);
  await first.emit("session_shutdown");
});

test("tool and turn budgets abort instead of authorizing retries or a fabricated handoff", async (t) => {
  const f = fixture(t, { max_tool_calls: 1 });
  const r = runtime(f.taskPath, f.workspace);
  await r.emit("session_start");
  assert.equal((await r.call("read", { path: "input.txt" })).permitted, true);
  assert.equal((await r.call("coordination_status")).block, true);
  await r.emit("session_shutdown");
  assert.equal(events(f).at(-2).code, "tool_budget_exhausted");
  assert.ok(!fs.existsSync(path.join(f.output, "model-report.json")));
  const g = fixture(t, { max_turns: 1 });
  const s = runtime(g.taskPath, g.workspace);
  await s.emit("session_start");
  await s.emit("turn_start");
  await s.emit("turn_start");
  assert.equal(s.ctx.shutdowns, 1);
  await s.emit("session_shutdown");
  assert.equal(events(g).at(-2).code, "turn_budget_exhausted");
});

test("malformed and oversized task input cannot create a partial success", (t) => {
  const f = fixture(t);
  assert.throws(() => loadTask(f.taskPath, f.root), /cwd/);
  fs.writeFileSync(f.taskPath, JSON.stringify({ ...f.task, output_directory: f.workspace }));
  assert.throws(() => loadTask(f.taskPath, f.workspace), /outside the workspace/);
  fs.writeFileSync(f.taskPath, JSON.stringify({ ...f.task, max_tool_calls: true }));
  assert.throws(() => loadTask(f.taskPath, f.workspace), /max_tool_calls/);
  fs.writeFileSync(f.taskPath, "x".repeat(1024 * 1024 + 1));
  assert.throws(() => loadTask(f.taskPath, f.workspace), /bounded regular/);
  fs.writeFileSync(f.taskPath, Buffer.from([0xff, 0xfe]));
  assert.throws(() => loadTask(f.taskPath, f.workspace));
  assert.deepEqual(fs.readdirSync(f.output), []);
});
