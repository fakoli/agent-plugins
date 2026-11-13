import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";

const nativeTools = new Set(["read", "grep", "find", "ls", "write", "edit"]);
const coordinationTools = ["coordination_status", "coordination_handoff"];
const taskKinds = new Set(["implementation", "research", "review", "validation"]);
const maximumManifestBytes = 1024 * 1024;

function fail(code, message) {
  const error = new Error(message);
  error.code = code;
  throw error;
}

function boundedString(value, name, maximum = 16000) {
  if (typeof value !== "string" || !value.trim() || value.length > maximum || value.includes("\0")) {
    fail("invalid_task", `${name} must be a nonempty bounded string`);
  }
  return value;
}

function relativeFile(value) {
  boundedString(value, "relative file", 1024);
  if (Buffer.from(value, "utf8").toString("utf8") !== value) fail("invalid_task", "Relative file contains invalid Unicode");
  if (path.isAbsolute(value) || value.includes("\\") || /[\u00A0\u2000-\u200A\u202F\u205F\u3000]/.test(value) || value.split("/").some((part) => !part || part === "." || part === "..")) {
    fail("invalid_task", "File paths must be normalized workspace-relative paths");
  }
  return value;
}

function contains(directory, candidate) {
  const relative = path.relative(directory, candidate);
  return relative === "" || (!path.isAbsolute(relative) && relative !== ".." && !relative.startsWith(`..${path.sep}`));
}

function noSymlinks(directory, candidate, allowMissing) {
  let current = directory;
  for (const part of path.relative(directory, candidate).split(path.sep).filter(Boolean)) {
    current = path.join(current, part);
    let stat;
    try {
      stat = fs.lstatSync(current);
    } catch (error) {
      if (error.code === "ENOENT" && allowMissing) return;
      throw error;
    }
    if (stat.isSymbolicLink()) fail("forbidden_path", "Symbolic-link traversal is not allowed");
  }
}

export function loadTask(taskPath, cwd) {
  if (!path.isAbsolute(taskPath)) fail("invalid_task", "Task path must be absolute");
  const descriptor = fs.openSync(taskPath, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0));
  let raw;
  try {
    const stat = fs.fstatSync(descriptor);
    if (!stat.isFile() || stat.size > maximumManifestBytes) fail("invalid_task", "Task must be a bounded regular JSON file");
    const buffer = Buffer.alloc(maximumManifestBytes + 1);
    let length = 0;
    while (length < buffer.length) {
      const count = fs.readSync(descriptor, buffer, length, buffer.length - length);
      if (!count) break;
      length += count;
    }
    raw = buffer.subarray(0, length);
    if (raw.length > maximumManifestBytes) fail("invalid_task", "Task exceeds the manifest limit");
  } finally {
    fs.closeSync(descriptor);
  }
  const task = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw));
  if (!task || typeof task !== "object" || Array.isArray(task) || ![1, 2, 3].includes(task.version) || !taskKinds.has(task.kind)) {
    fail("invalid_task", "Expected a supported versioned coordination task and kind");
  }
  for (const key of ["run_id", "task_id"]) {
    const pattern = key === "task_id" && task.version === 1
      ? /^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$/
      : /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
    const value = boundedString(task[key], key, 128);
    if (pattern.exec(value)?.[0] !== value) fail("invalid_task", `Invalid ${key}`);
  }
  if (task.version === 1 && "run_options" in task) fail("invalid_task", "Version 1 cannot contain run_options");
  if ([2, 3].includes(task.version)) {
    const options = task.run_options;
    const levels = ["off", "minimal", "low", "medium", "high", "xhigh", "max"];
    const identifierPattern = "[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}";
    const matchesIdentifier = (value, pattern) => typeof value === "string" && !value.includes("://") && new RegExp(`^${pattern}$`).exec(value)?.[0] === value;
    const identifier = (value) => matchesIdentifier(value, identifierPattern);
    // Each component may contain slashes; only the exact runtime catalog picks a pair.
    const qualifiedDefault = (value) => matchesIdentifier(value, `${identifierPattern}/${identifierPattern}`);
    if (!options || typeof options !== "object" || Array.isArray(options) || Object.keys(options).some((key) => !["provider", "model", "thinking"].includes(key)) || (("provider" in options) !== ("model" in options)) || ("provider" in options && (!identifier(options.provider) || !identifier(options.model))) || ("thinking" in options && !levels.includes(options.thinking))) fail("invalid_task", "Invalid version 2 run options");
    if (!(task.version === 2 ? task.operation === "run" : ["run", "continue"].includes(task.operation)) || !task.runtime_defaults || Object.keys(task.runtime_defaults).sort().join(",") !== "model,thinking" || !qualifiedDefault(task.runtime_defaults.model) || !levels.includes(task.runtime_defaults.thinking)) fail("invalid_task", "Invalid versioned runtime defaults");
  }
  boundedString(task.instructions, "instructions", 48000);
  for (const key of ["workspace", "output_directory"]) {
    if (!path.isAbsolute(boundedString(task[key], key, 4096))) fail("invalid_task", `${key} must be absolute`);
    if (!fs.lstatSync(task[key]).isDirectory()) fail("invalid_task", `${key} must be an existing directory`);
    task[key] = fs.realpathSync(task[key]);
    if (/[\u00A0\u2000-\u200A\u202F\u205F\u3000]/.test(task[key])) fail("invalid_task", "Control paths must not require Pi Unicode-space normalization");
  }
  if (fs.realpathSync(cwd) !== task.workspace) fail("invalid_task", "Pi cwd must match the assigned workspace");
  if (contains(task.workspace, fs.realpathSync(taskPath)) || contains(task.workspace, task.output_directory) || contains(task.output_directory, task.workspace)) {
    fail("invalid_task", "Task and output controls must be outside the workspace; output must not contain it");
  }
  if (task.version === 3) {
    const session = task.session;
    if (!session || Object.keys(session).sort().join(",") !== "conversation_id,directory,file,prior,prior_sha256" || typeof session.conversation_id !== "string" || /^[0-9a-f]{32}$/.exec(session.conversation_id)?.[0] !== session.conversation_id) fail("invalid_task", "Invalid saved conversation descriptor");
    const dispatch = path.dirname(task.output_directory);
    const directory = path.join(path.dirname(dispatch), "conversations", session.conversation_id);
    if (path.basename(dispatch) !== task.run_id || session.directory !== directory || session.file !== path.join(directory, "session.jsonl") || task.workspace !== path.join(directory, "workspace")) fail("invalid_task", "Saved paths differ from owned dispatch");
    if (task.operation === "run" ? session.prior !== null || session.prior_sha256 !== null || session.conversation_id !== task.run_id : !session.prior || session.prior.conversation_id !== session.conversation_id || session.prior.run_id === task.run_id || typeof session.prior_sha256 !== "string" || /^[0-9a-f]{64}$/.exec(session.prior_sha256)?.[0] !== session.prior_sha256) fail("invalid_task", "Invalid previous saved dispatch");
    noSymlinks(path.dirname(dispatch), directory, false);
    noSymlinks(directory, session.file, task.operation === "run");
  }
  if (!Array.isArray(task.allowed_tools) || task.allowed_tools.length > nativeTools.size || new Set(task.allowed_tools).size !== task.allowed_tools.length || task.allowed_tools.some((tool) => !nativeTools.has(tool))) {
    fail("invalid_task", "allowed_tools must contain unique supported native tools; shell execution is not supported");
  }
  if (!Array.isArray(task.writable_paths) || task.writable_paths.length > 128) fail("invalid_task", "writable_paths must be a bounded list");
  task.writable_paths = task.writable_paths.map(relativeFile);
  if (new Set(task.writable_paths).size !== task.writable_paths.length) fail("invalid_task", "Duplicate writable path");
  if (task.allowed_tools.some((tool) => tool === "write" || tool === "edit") && !task.writable_paths.length) fail("invalid_task", "Write tools need explicit writable paths");
  task.max_turns ??= 32;
  for (const [key, maximum] of [["max_tool_calls", 1000], ["max_turns", 200]]) {
    if (!Number.isInteger(task[key]) || task[key] < 1 || task[key] > maximum) fail("invalid_task", `Invalid ${key}`);
  }
  return { task, taskSha256: createHash("sha256").update(raw).digest("hex"), sourceSummary: summarizeSource(task.source) };
}

export function checkToolPath(task, toolName, input) {
  const supplied = input?.path ?? (["grep", "find", "ls"].includes(toolName) ? "." : undefined);
  boundedString(supplied, "tool path", 4096);
  if (/[\u00A0\u2000-\u200A\u202F\u205F\u3000]/.test(supplied)) fail("forbidden_path", "Use exact filesystem paths without Unicode-space normalization");
  const candidate = path.resolve(task.workspace, supplied);
  if (!contains(task.workspace, candidate)) fail("forbidden_path", "Tool paths must remain inside the assigned workspace");
  const writes = toolName === "write" || toolName === "edit";
  if (writes && !task.writable_paths.includes(path.relative(task.workspace, candidate).split(path.sep).join("/"))) {
    fail("forbidden_path", "This file is outside the declared writable paths");
  }
  noSymlinks(task.workspace, candidate, toolName === "write");
  return candidate;
}

function savedSessionIdentity(task, ctx) {
  const manager = ctx.sessionManager;
  const header = manager?.getHeader();
  const identity = { id: manager?.getSessionId(), file: manager?.getSessionFile(), cwd: manager?.getCwd(), version: header?.version };
  if (identity.version !== 3 || typeof identity.id !== "string" || /^[A-Za-z0-9_.-]{1,128}$/.exec(identity.id)?.[0] !== identity.id || identity.file !== task.session.file || identity.cwd !== task.workspace || header?.type !== "session" || header.id !== identity.id || header.cwd !== task.workspace || task.session.prior && identity.id !== task.session.prior.session?.id) fail("session_mismatch", "Official Pi session does not match the current saved assignment");
  return identity;
}

function toolResult(value) {
  return { content: [{ type: "text", text: JSON.stringify(value) }], details: value };
}

function summarizeSource(source) {
  if (source === undefined || source === null) return null;
  if (typeof source !== "object" || Array.isArray(source)) fail("invalid_task", "Source identity must be an object");
  boundedString(source.kind, "source kind", 128);
  const commit = source.commit ?? null;
  if (commit !== null && (typeof commit !== "string" || !/^[a-f0-9]{40,64}$/.test(commit))) fail("invalid_task", "Source commit must be a Git object ID");
  const manifest = {};
  for (const key of ["files", "modes"]) {
    const values = source[key] ?? {};
    if (typeof values !== "object" || values === null || Array.isArray(values)) fail("invalid_task", `Source ${key} must be an object`);
    manifest[key] = Object.keys(values).sort().map((name) => [name, values[name]]);
  }
  return { kind: source.kind, commit, file_count: manifest.files.length, manifest_sha256: createHash("sha256").update(JSON.stringify(manifest)).digest("hex") };
}

const stringArraySchema = { type: "array", maxItems: 128, items: { type: "string", maxLength: 1024 } };

export default function coordinationExtension(pi) {
  let loaded;
  let failure;
  let eventDescriptor;
  let toolCalls = 0;
  let turns = 0;
  let handedOff = false;
  let configurationRecorded = false;
  let savedIdentity;
  const requested = () => pi.getFlag("coordination-task");
  const status = () => ({ active: Boolean(loaded), run_id: loaded?.task.run_id, task_id: loaded?.task.task_id, task_sha256: loaded?.taskSha256, tool_calls: toolCalls, turns, handed_off: handedOff, failure, ...(savedIdentity ? { session: savedIdentity } : {}) });
  const record = (type, fields = {}) => {
    if (eventDescriptor !== undefined) fs.writeSync(eventDescriptor, JSON.stringify({ type, at: new Date().toISOString(), ...status(), ...fields }) + "\n");
  };
  const stop = (ctx, code, message) => {
    failure = { code, message };
    record("refused", { code, message });
    ctx.abort();
    ctx.shutdown();
    return { block: true, reason: `${code}: ${message}` };
  };

  pi.registerFlag("coordination-task", { type: "string", description: "Absolute path to an external coordinator's versioned task manifest" });
  pi.registerCommand("coordination-status", {
    description: "Show the current delegated task and bounds",
    handler: async (_args, ctx) => { if (ctx.hasUI) ctx.ui.notify(JSON.stringify(status()), "info"); },
  });
  pi.registerTool({
    name: "coordination_status", label: "Coordination status", description: "Read the current task counters and handoff state; grants no additional authority.",
    parameters: { type: "object", properties: {}, additionalProperties: false },
    async execute() { return toolResult(status()); },
  });
  pi.registerTool({
    name: "coordination_handoff", label: "Coordination handoff", description: "Return one final model self-report to Codex. This is not verification, approval, or acceptance. No further work is permitted after handoff.",
    parameters: {
      type: "object", additionalProperties: false,
      properties: { status: { type: "string", enum: ["completed", "blocked", "failed"] }, summary: { type: "string", minLength: 1, maxLength: 16000 }, evidence: stringArraySchema, changed_files: stringArraySchema, limitations: stringArraySchema },
      required: ["status", "summary", "evidence", "changed_files", "limitations"],
    },
    async execute(_callId, report) {
      if (!loaded || failure || handedOff) fail("handoff_refused", "No active unfinished coordination task");
      if (!["completed", "blocked", "failed"].includes(report.status)) fail("handoff_refused", "Unsupported handoff status");
      boundedString(report.summary, "summary");
      for (const key of ["evidence", "changed_files", "limitations"]) {
        if (!Array.isArray(report[key]) || report[key].length > 128) fail("handoff_refused", `Invalid ${key}`);
        report[key].forEach((value) => boundedString(value, key, 1024));
      }
      if (report.changed_files.some((name) => !loaded.task.writable_paths.includes(relativeFile(name)))) fail("handoff_refused", "Reported changes exceed the declared writable paths");
      const result = { version: 1, run_id: loaded.task.run_id, task_id: loaded.task.task_id, task_sha256: loaded.taskSha256, model_self_report: true, status: report.status, summary: report.summary, evidence: report.evidence, changed_files: report.changed_files, limitations: report.limitations };
      fs.writeFileSync(path.join(loaded.task.output_directory, "model-report.json"), JSON.stringify(result, null, 2) + "\n", { flag: "wx", mode: 0o600 });
      handedOff = true;
      record("handoff", { reported_status: report.status });
      return toolResult({ recorded: true, model_self_report: true, acceptance: "not_granted" });
    },
  });

  pi.on("session_start", async (_event, ctx) => {
    if (!requested()) {
      pi.setActiveTools(pi.getActiveTools().filter((name) => !coordinationTools.includes(name)));
      return;
    }
    try {
      if (loaded) fail("task_reloaded", "A fresh dispatch requires a fresh Pi process");
      loaded = loadTask(requested(), ctx.cwd);
      toolCalls = 0; turns = 0; handedOff = false; configurationRecorded = false;
      if (loaded.task.version === 3) savedIdentity = savedSessionIdentity(loaded.task, ctx);
      eventDescriptor = fs.openSync(path.join(loaded.task.output_directory, "extension-events.jsonl"), "wx", 0o600);
      const requiredTools = [...loaded.task.allowed_tools, ...coordinationTools];
      pi.setActiveTools(requiredTools);
      // Pi's CLI allowlist also filters registered extension tools; unknown names are ignored.
      const activeTools = new Set(pi.getActiveTools());
      const missingTools = requiredTools.filter((name) => !activeTools.has(name));
      if (missingTools.length) fail("unavailable_tools", `Pi did not activate required tools: ${missingTools.join(", ")}. Include them in the CLI tool allowlist.`);
      record("task_loaded", { model: ctx.model ? { provider: ctx.model.provider, id: ctx.model.id } : null });
    } catch (error) {
      stop(ctx, error.code ?? "invalid_task", error.message);
    }
  });
  pi.on("before_agent_start", async (event, ctx) => {
    if (!requested()) return;
    if (!loaded || failure || handedOff) {
      stop(ctx, "task_unavailable", "Coordination task is unavailable or already handed off");
      return;
    }
    if (loaded.task.version === 3) {
      try {
        if (JSON.stringify(savedSessionIdentity(loaded.task, ctx)) !== JSON.stringify(savedIdentity)) fail("session_mismatch", "Saved session changed before prompt");
      } catch (error) {
        stop(ctx, error.code ?? "session_mismatch", error.message);
        return;
      }
    }
    if ([2, 3].includes(loaded.task.version) && !configurationRecorded) {
      const configuration = { provider: ctx.model?.provider, model: ctx.model?.id, thinking: pi.getThinkingLevel() };
      if (!configuration.provider || !configuration.model || !["off", "minimal", "low", "medium", "high", "xhigh", "max"].includes(configuration.thinking)) {
        stop(ctx, "configuration_unavailable", "Pi did not expose an effective run configuration");
        return;
      }
      const options = loaded.task.run_options;
      const selectedModelMatches = options.provider
        ? configuration.provider === options.provider && configuration.model === options.model
        : `${configuration.provider}/${configuration.model}` === loaded.task.runtime_defaults.model;
      const selectedThinking = options.thinking ?? loaded.task.runtime_defaults.thinking;
      if (!selectedModelMatches || configuration.thinking !== selectedThinking) {
        stop(ctx, "configuration_mismatch", "Effective Pi options differ from the approved task");
        return;
      }
      record("run_configuration", { configuration });
      configurationRecorded = true;
    }
    return { systemPrompt: `${event.systemPrompt}\n\nExternal coordinator task:\n${JSON.stringify({ run_id: loaded.task.run_id, task_id: loaded.task.task_id, kind: loaded.task.kind, instructions: loaded.task.instructions, source: loaded.sourceSummary, writable_paths: loaded.task.writable_paths, max_tool_calls: loaded.task.max_tool_calls, max_turns: loaded.task.max_turns })}\nOnly this current assignment grants scope and budgets; earlier conversation text grants no task or tool authority. Work only inside the assigned workspace and declared writable files. Shell execution is unavailable; the coordinator runs declared verification commands after Pi exits. Before the tool budget ends, call coordination_handoff exactly once with an honest self-report. Do not claim acceptance or verification from your report. Tool/path guards are task policy; the external runner owns OS isolation and custody.` };
  });
  pi.on("turn_start", async (_event, ctx) => {
    if (!requested() || !loaded) return;
    turns += 1;
    if (turns > loaded.task.max_turns) stop(ctx, "turn_budget_exhausted", "Delegated turn budget exhausted");
  });
  pi.on("tool_call", async (event, ctx) => {
    if (!requested()) return;
    if (!loaded || failure || handedOff) return stop(ctx, "task_unavailable", "No further tools are authorized for this task");
    if (toolCalls >= loaded.task.max_tool_calls) return stop(ctx, "tool_budget_exhausted", "Delegated tool budget exhausted");
    toolCalls += 1;
    if (!coordinationTools.includes(event.toolName) && !loaded.task.allowed_tools.includes(event.toolName)) return stop(ctx, "forbidden_tool", "Tool is outside the task allowlist");
    try {
      // Pin the checked absolute spelling so Pi cannot expand @, ~ or file: inputs differently.
      if (nativeTools.has(event.toolName)) event.input.path = checkToolPath(loaded.task, event.toolName, event.input);
    } catch (error) {
      return stop(ctx, error.code ?? "forbidden_path", error.message);
    }
    record("tool_call", { tool_name: event.toolName, tool_call_id: event.toolCallId });
  });
  pi.on("agent_settled", async () => { record("agent_settled"); });
  pi.on("session_shutdown", async () => {
    if (eventDescriptor !== undefined) {
      record("session_shutdown");
      fs.closeSync(eventDescriptor);
      eventDescriptor = undefined;
    }
  });
}
