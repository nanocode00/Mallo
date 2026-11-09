import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const apiUrlSource = fs.readFileSync(path.resolve("web/api-url.js"), "utf8");
const menuSource = fs.readFileSync(path.resolve("web/menu-metadata.js"), "utf8");

function setupApiSandbox() {
  const sandbox = {
    window: {
      location: { protocol: "http:" },
      sessionStorage: {
        getItem() { return null; },
        setItem() {},
      },
    },
    Headers: globalThis.Headers,
    console,
    Response: class {
      constructor(body, init = {}) {
        this._body = body;
        this.status = init.status || 200;
        this.ok = this.status >= 200 && this.status < 300;
      }
      async json() {
        return JSON.parse(this._body);
      }
    },
    fetch: async () => {
      throw new TypeError("Failed to fetch (offline network test)");
    },
  };
  sandbox.globalThis = sandbox;
  sandbox.window.globalThis = sandbox;
  sandbox.window.Response = sandbox.Response;
  sandbox.window.Headers = globalThis.Headers;

  vm.createContext(sandbox);
  vm.runInContext(menuSource, sandbox);
  vm.runInContext(apiUrlSource, sandbox);
  return sandbox;
}

test("DemoAdapter handles full standalone kiosk ordering flow when backend is offline", async () => {
  const sandbox = setupApiSandbox();
  const api = sandbox.window.MalloApi;

  // 1. Health check
  const healthResp = await api.apiFetch("/health");
  const health = await healthResp.json();
  assert.equal(health.status, "ready");
  assert.equal(health.is_demo, true);
  assert.equal(api.isDemoMode, true);

  // 2. Select Fulfillment
  const fulResp = await api.apiFetch("/api/fulfillment", {
    method: "POST",
    body: JSON.stringify({ fulfillment_type: "takeout" }),
  });
  const ful = await fulResp.json();
  assert.equal(ful.success, true);
  assert.equal(ful.fulfillment_type, "takeout");
  assert.equal(ful.response_text, "원하시는 메뉴를 말씀해 주세요.");

  // 3. Add Item (Americano, Iced, 2)
  const addResp = await api.apiFetch("/api/commands", {
    method: "POST",
    body: JSON.stringify({
      commands: [{
        intent: "ADD_ITEM",
        target_item_id: "americano",
        quantity: 2,
        temperature: "iced",
      }],
    }),
  });
  const addData = await addResp.json();
  assert.equal(addData.success, true);
  assert.equal(addData.cart.items.length, 1);
  assert.equal(addData.cart.items[0].quantity, 2);
  assert.equal(addData.cart.items[0].temperature, "iced");
  assert.equal(addData.cart.total_price, 9400); // 4700 * 2 from MalloMenuMetadata

  // 4. Update Temperature (Change to Hot)
  const tempResp = await api.apiFetch("/api/commands", {
    method: "POST",
    body: JSON.stringify({
      commands: [{
        intent: "UPDATE_OPTION",
        target_item_id: "americano",
        temperature: "hot",
      }],
    }),
  });
  const tempData = await tempResp.json();
  assert.equal(tempData.success, true);
  assert.equal(tempData.cart.items[0].temperature, "hot");

  // 5. Update Quantity (Change to 3)
  const qtyResp = await api.apiFetch("/api/commands", {
    method: "POST",
    body: JSON.stringify({
      commands: [{
        intent: "UPDATE_QUANTITY",
        target_item_id: "americano",
        quantity: 3,
      }],
    }),
  });
  const qtyData = await qtyResp.json();
  assert.equal(qtyData.success, true);
  assert.equal(qtyData.cart.items[0].quantity, 3);
  assert.equal(qtyData.cart.total_price, 14100); // 4700 * 3

  // 6. Confirm Order
  const confirmResp = await api.apiFetch("/api/commands", {
    method: "POST",
    body: JSON.stringify({
      commands: [{ intent: "CONFIRM_ORDER" }],
    }),
  });
  const confirmData = await confirmResp.json();
  assert.equal(confirmData.success, true);
  assert.equal(confirmData.cart.confirmed, true);

  // 7. Remove Item
  const removeResp = await api.apiFetch("/api/commands", {
    method: "POST",
    body: JSON.stringify({
      commands: [{
        intent: "REMOVE_ITEM",
        target_item_id: "americano",
      }],
    }),
  });
  const removeData = await removeResp.json();
  assert.equal(removeData.success, true);
  assert.equal(removeData.cart.items.length, 0);
  assert.equal(removeData.cart.total_price, 0);

  // 8. System Messages
  const msgResp = await api.apiFetch("/api/system-message", {
    method: "POST",
    body: JSON.stringify({ message_id: "PAYMENT" }),
  });
  const msgData = await msgResp.json();
  assert.equal(msgData.success, true);
  assert.match(msgData.response_text, /결제 방법/);

  // 9. Accessibility speed cycle
  const a11yResp = await api.apiFetch("/api/accessibility", {
    method: "POST",
    body: JSON.stringify({ action: "CYCLE_SPEED" }),
  });
  const a11yData = await a11yResp.json();
  assert.equal(a11yData.success, true);
  assert.equal(a11yData.tts_level, 1);

  // 10. Reset Session
  const resetResp = await api.apiFetch("/api/reset", { method: "POST" });
  const resetData = await resetResp.json();
  assert.equal(resetData.success, true);
  assert.equal(resetData.cart.items.length, 0);
});

test("LocalTouch keeps remote canonical wording and display/chunk contract", async () => {
  const sandbox = setupApiSandbox();
  const api = sandbox.window.MalloApi;
  const fulfillment = await (await api.apiFetch("/api/fulfillment", {
    method: "POST", body: JSON.stringify({ fulfillment_type: "dine_in" }),
  })).json();
  assert.equal(fulfillment.response_text, "원하시는 메뉴를 말씀해 주세요.");
  assert.deepEqual(fulfillment.display_segments, [fulfillment.response_text]);
  assert.equal(fulfillment.tts_segments[0].synthesis_text, fulfillment.response_text);
  assert.equal(fulfillment.tts_segments[0].segment_index, 0);

  const speed = await (await api.apiFetch("/api/accessibility", {
    method: "POST", body: JSON.stringify({ action: "CYCLE_SPEED" }),
  })).json();
  assert.equal(speed.response_text, "이 속도로 안내합니다.");
  assert.deepEqual(speed.display_segments, [speed.response_text]);
  assert.equal(speed.tts_segments[0].synthesis_text, speed.response_text);

  const home = await (await api.apiFetch("/api/system-message", {
    method: "POST", body: JSON.stringify({ message_id: "HOME_CONFIRM" }),
  })).json();
  assert.equal(home.response_text, "주문을 취소하고 처음으로 돌아갈까요? 담아둔 메뉴가 모두 사라집니다.");
  assert.deepEqual(home.display_segments, [
    "주문을 취소하고 처음으로 돌아갈까요?",
    "담아둔 메뉴가 모두 사라집니다.",
  ]);
});
