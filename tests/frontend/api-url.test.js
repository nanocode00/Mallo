"use strict";

const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");

const webDir = path.resolve(__dirname, "../../web");
const runtimeConfig = fs.readFileSync(path.join(webDir, "runtime-config.js"), "utf8");
const apiUrlScript = fs.readFileSync(path.join(webDir, "api-url.js"), "utf8");
let uuidCounter = 0;

function loadConfig({ hostname, protocol = "https:", base, storage, fetchImpl } = {}) {
  const calls = [];
  const window = {
    location: { hostname, protocol },
    crypto: { randomUUID: () => `${String(++uuidCounter).padStart(8, "0")}-2222-4333-8444-555555555555` },
    sessionStorage: storage || new Map(),
    fetch: (...args) => {
      calls.push(args);
      return fetchImpl ? fetchImpl(...args) : Promise.resolve({ ok: true, status: 200 });
    },
  };
  window.sessionStorage.getItem ||= (key) => window.sessionStorage.get(key) || null;
  window.sessionStorage.setItem ||= (key, value) => window.sessionStorage.set(key, value);
  if (base !== undefined) window.MALLO_API_BASE_URL = base;
  const context = vm.createContext({ window, URL, Headers });
  vm.runInContext(runtimeConfig, context);
  vm.runInContext(apiUrlScript, context);
  return { window, calls };
}

test("localhost keeps existing same-origin API paths", () => {
  const { window } = loadConfig({ hostname: "localhost", protocol: "http:" });
  assert.equal(window.MALLO_API_BASE_URL, "");
  assert.equal(window.MalloApi.apiUrl("/api/audio"), "/api/audio");
});

test("static deployment uses the configured HTTPS gateway", () => {
  const { window } = loadConfig({ hostname: "mallo-kiosk.vercel.app" });
  const expectedGateway = window.MALLO_RUNTIME_CONFIG?.apiBaseUrl || "";
  assert.equal(
    window.MalloApi.apiUrl("/api/state"),
    `${expectedGateway}/api/state`,
  );
});

test("preconfigured Named Tunnel base overrides the Quick Tunnel default", () => {
  const { window } = loadConfig({
    hostname: "mallo-kiosk.vercel.app",
    base: "https://gateway.example.com/",
  });
  assert.equal(window.MalloApi.apiUrl("/health"), "https://gateway.example.com/health");
});

test("HTTPS static pages reject an HTTP gateway", () => {
  const { window } = loadConfig({
    hostname: "mallo-kiosk.vercel.app",
    base: "http://127.0.0.1:8000",
  });
  assert.throws(() => window.MalloApi.apiUrl("/api/state"), /HTTPS Mallo web/);
});

test("all /api requests share one sessionStorage UUID and health stays sessionless", async () => {
  const { window, calls } = loadConfig({ hostname: "mallo-kiosk.vercel.app" });
  await window.MalloApi.apiFetch("/api/order", { method: "POST" });
  await window.MalloApi.apiFetch("/api/reset", { method: "POST" });
  await window.MalloApi.apiFetch("/health");

  assert.equal(calls[0][1].headers.get("X-Mallo-Session-ID"), calls[1][1].headers.get("X-Mallo-Session-ID"));
  assert.match(calls[0][1].headers.get("X-Mallo-Session-ID"), /^[0-9a-f-]{36}$/);
  assert.equal(calls[2][1].headers.get("X-Mallo-Session-ID"), null);
});

test("separate sessionStorage instances produce independent tab sessions", () => {
  const first = loadConfig({ hostname: "mallo-kiosk.vercel.app", storage: new Map() });
  const second = loadConfig({ hostname: "mallo-kiosk.vercel.app", storage: new Map() });
  assert.notEqual(first.window.MalloApi.sessionId(), second.window.MalloApi.sessionId());
});

test("safe GET retries once with one traceable request ID, while mutation does not retry", async () => {
  const responses = [
    { ok: false, status: 503 },
    { ok: true, status: 200 },
    { ok: false, status: 503 },
  ];
  const { window, calls } = loadConfig({
    hostname: "mallo-kiosk.vercel.app",
    fetchImpl: () => Promise.resolve(responses.shift()),
  });

  await window.MalloApi.apiFetch("/api/state");
  await window.MalloApi.apiFetch("/api/order", { method: "POST" });

  assert.equal(calls.length, 3);
  assert.equal(calls[0][1].headers.get("X-Mallo-Request-ID"), calls[1][1].headers.get("X-Mallo-Request-ID"));
  assert.notEqual(calls[1][1].headers.get("X-Mallo-Request-ID"), calls[2][1].headers.get("X-Mallo-Request-ID"));
});

test("safe paths are retried only for GET requests", async () => {
  const { window, calls } = loadConfig({
    hostname: "mallo-kiosk.vercel.app",
    fetchImpl: () => Promise.resolve({ ok: false, status: 503 }),
  });

  await window.MalloApi.apiFetch("/api/state", { method: "POST" });

  assert.equal(calls.length, 1);
});
