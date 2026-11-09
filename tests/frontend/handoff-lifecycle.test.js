import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const apiUrlSource = fs.readFileSync(path.resolve("web/api-url.js"), "utf8");
const menuSource = fs.readFileSync(path.resolve("web/menu-metadata.js"), "utf8");

class MockResponse {
  constructor(body, init = {}) {
    this._body = body;
    this.status = init.status || 200;
    this.ok = this.status >= 200 && this.status < 300;
  }
  async json() {
    return typeof this._body === "string" ? JSON.parse(this._body) : this._body;
  }
}

function setupApiSandbox(mockFetch) {
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
    setTimeout: globalThis.setTimeout,
    clearTimeout: globalThis.clearTimeout,
    AbortController: globalThis.AbortController,
    Response: MockResponse,
    fetch: mockFetch || (async () => {
      throw new TypeError("Failed to fetch (offline network test)");
    }),
  };
  sandbox.globalThis = sandbox;
  sandbox.window.globalThis = sandbox;
  sandbox.window.Response = MockResponse;
  sandbox.window.Headers = globalThis.Headers;
  sandbox.window.setTimeout = globalThis.setTimeout;
  sandbox.window.clearTimeout = globalThis.clearTimeout;
  sandbox.window.fetch = sandbox.fetch;

  vm.createContext(sandbox);
  vm.runInContext(menuSource, sandbox);
  vm.runInContext(apiUrlSource, sandbox);
  return sandbox;
}

test("attemptHandoffToServer succeeds and promotes to REMOTE on ORDER screen", async () => {
  let handoffCalled = false;
  let receivedPayload = null;

  const mockFetch = async (url, options = {}) => {
    const urlStr = String(url);
    if (urlStr.includes("/health")) {
      return new MockResponse(JSON.stringify({ status: "ready" }), { status: 200 });
    }
    if (urlStr.includes("/api/session/handoff")) {
      handoffCalled = true;
      receivedPayload = JSON.parse(options.body);
      return new MockResponse(JSON.stringify({
        success: true,
        cart: {
          items: [
            {
              menu_id: "americano",
              quantity: 2,
              temperature: "iced",
              unit_price: 4700,
              total_price: 9400,
              options: {},
            },
          ],
          total_price: 9400,
          fulfillment_type: "dine_in",
          confirmed: false,
        },
      }), { status: 200 });
    }
    throw new Error("Unhandled route " + urlStr);
  };

  const sandbox = setupApiSandbox(mockFetch);
  const api = sandbox.window.MalloApi;

  // Set local state
  api.setLocalTouchMode(true);
  const localState = api.getLocalTouchState();
  localState.cart.fulfillment_type = "dine_in";
  localState.cart.items = [
    { menu_id: "americano", quantity: 2, temperature: "iced", unit_price: 4700, total_price: 9400, options: {} },
  ];
  localState.cart.total_price = 9400;

  assert.equal(api.adapterMode, "LOCAL_TOUCH");

  // Execute handoff
  const resultCart = await api.attemptHandoffToServer("ORDER");
  assert.equal(handoffCalled, true);
  assert.equal(receivedPayload.fulfillment_type, "dine_in");
  assert.equal(receivedPayload.items.length, 1);
  assert.equal(receivedPayload.items[0].menu_id, "americano");
  assert.equal(receivedPayload.items[0].quantity, 2);

  // Assert mode promoted to REMOTE
  assert.equal(api.adapterMode, "REMOTE");
  assert.equal(resultCart.total_price, 9400);
});

test("attemptHandoffToServer permits real TTS recovery on PAYMENT and COMPLETE screens", async () => {
  let handoffCalled = false;
  const mockFetch = async (url) => {
    handoffCalled = true;
    return new MockResponse(JSON.stringify({ status: "ready" }), { status: 200 });
  };

  const sandbox = setupApiSandbox(mockFetch);
  const api = sandbox.window.MalloApi;
  api.setLocalTouchMode(true);

  // Real canonical TTS may be needed on either terminal ordering screen.
  const payResult = await api.attemptHandoffToServer("PAYMENT");
  assert.equal(payResult, false);
  assert.equal(handoffCalled, true);
  assert.equal(api.adapterMode, "LOCAL_TOUCH");

  handoffCalled = false;
  const compResult = await api.attemptHandoffToServer("COMPLETE");
  assert.equal(compResult, false);
  assert.equal(handoffCalled, true);
  assert.equal(api.adapterMode, "LOCAL_TOUCH");
});

test("attemptHandoffToServer maintains LOCAL_TOUCH if server health or handoff fails", async () => {
  const mockFetch = async (url) => {
    const urlStr = String(url);
    if (urlStr.includes("/health")) {
      return new MockResponse(JSON.stringify({ status: "degraded" }), { status: 503 });
    }
    throw new Error("Server down");
  };

  const sandbox = setupApiSandbox(mockFetch);
  const api = sandbox.window.MalloApi;
  api.setLocalTouchMode(true);
  const localState = api.getLocalTouchState();
  localState.cart.items = [{ menu_id: "americano", quantity: 1, temperature: "hot", unit_price: 4700, total_price: 4700, options: {} }];

  const result = await api.attemptHandoffToServer("ORDER");
  assert.equal(result, false);
  assert.equal(api.adapterMode, "LOCAL_TOUCH");
  // Cart preserved
  assert.equal(api.getLocalTouchState().cart.items.length, 1);
});

test("attemptHandoffToServer prevents race condition when local cart is dirtied in-flight", async () => {
  let resolveHandoff;
  const handoffPromise = new Promise((resolve) => {
    resolveHandoff = resolve;
  });

  const mockFetch = async (url) => {
    const urlStr = String(url);
    if (urlStr.includes("/health")) {
      return new MockResponse(JSON.stringify({ status: "ready" }), { status: 200 });
    }
    if (urlStr.includes("/api/session/handoff")) {
      await handoffPromise;
      return new MockResponse(JSON.stringify({
        success: true,
        cart: { items: [], total_price: 0, fulfillment_type: "dine_in", confirmed: false },
      }), { status: 200 });
    }
    throw new Error("Unhandled route");
  };

  const sandbox = setupApiSandbox(mockFetch);
  const api = sandbox.window.MalloApi;
  api.setLocalTouchMode(true);

  // Start handoff in-flight
  const handoffTask = api.attemptHandoffToServer("ORDER");

  // User modifies cart while handoff is in flight
  api.markLocalCartDirty();

  // Complete network handoff
  resolveHandoff();
  const resultCart = await handoffTask;

  // Stale handoff should be rejected and mode kept as LOCAL_TOUCH
  assert.equal(resultCart, false);
  assert.equal(api.adapterMode, "LOCAL_TOUCH");
});

test("stale handoff discard is followed by successful re-handoff syncing latest local cart", async () => {
  let resolveHandoff1;
  let onHandoff1Sent;
  const handoffSentPromise1 = new Promise((resolve) => {
    onHandoff1Sent = resolve;
  });
  const handoffPromise1 = new Promise((resolve) => {
    resolveHandoff1 = resolve;
  });

  const recordedRequests = [];

  const mockFetch = async (url, options = {}) => {
    const urlStr = String(url);
    if (urlStr.includes("/health")) {
      return new MockResponse(JSON.stringify({ status: "ready" }), { status: 200 });
    }
    if (urlStr.includes("/api/session/handoff")) {
      const payload = JSON.parse(options.body);
      recordedRequests.push(payload);
      if (recordedRequests.length === 1) {
        onHandoff1Sent();
        await handoffPromise1;
        return new MockResponse(JSON.stringify({
          success: true,
          cart: {
            items: payload.items,
            total_price: 4700,
            fulfillment_type: "dine_in",
            confirmed: false,
          },
        }), { status: 200 });
      }
      // Second handoff with 2 items
      return new MockResponse(JSON.stringify({
        success: true,
        cart: {
          items: payload.items,
          total_price: 9900,
          fulfillment_type: "dine_in",
          confirmed: false,
        },
      }), { status: 200 });
    }
    throw new Error("Unhandled route: " + urlStr);
  };

  const sandbox = setupApiSandbox(mockFetch);
  const api = sandbox.window.MalloApi;
  api.setLocalTouchMode(true);
  const localState = api.getLocalTouchState();
  localState.cart.fulfillment_type = "dine_in";
  localState.cart.items = [
    { menu_id: "americano", quantity: 1, temperature: "iced", unit_price: 4700, total_price: 4700, options: {} },
  ];
  localState.cart.total_price = 4700;

  // 1. First handoff starts
  const handoffTask1 = api.attemptHandoffToServer("ORDER");
  await handoffSentPromise1;

  // 2. User adds Cafe Latte while handoff 1 is in-flight
  api.markLocalCartDirty();
  localState.cart.items.push({
    menu_id: "cafe_latte",
    quantity: 1,
    temperature: "hot",
    unit_price: 5200,
    total_price: 5200,
    options: {},
  });
  localState.cart.total_price = 9900;

  // 3. Complete handoff 1 -> discarded because dirtied
  resolveHandoff1();
  const res1 = await handoffTask1;
  assert.equal(res1, false);
  assert.equal(api.adapterMode, "LOCAL_TOUCH");
  assert.equal(recordedRequests.length, 1);
  assert.equal(recordedRequests[0].items.length, 1);

  // 4. Re-handoff with latest snapshot
  const res2 = await api.attemptHandoffToServer("ORDER");
  assert.notEqual(res2, false);
  assert.equal(api.adapterMode, "REMOTE");
  assert.equal(recordedRequests.length, 2);
  assert.equal(recordedRequests[1].items.length, 2);
  assert.equal(recordedRequests[1].items[0].menu_id, "americano");
  assert.equal(recordedRequests[1].items[1].menu_id, "cafe_latte");
  assert.equal(res2.total_price, 9900);
});

test("LOCAL_TOUCH merges identical items on temperature change and preserves +/- and delete operations", async () => {
  const sandbox = setupApiSandbox();
  const api = sandbox.window.MalloApi;
  api.setLocalTouchMode(true);

  const postApi = async (path, bodyObj) => {
    const resp = await api.apiFetch(path, {
      method: "POST",
      body: JSON.stringify(bodyObj),
    });
    return resp.json();
  };

  // 1. Add Hot Cafe Latte (1)
  const r1 = await postApi("/api/commands", {
    commands: [{ intent: "ADD_ITEM", target_item_id: "cafe_latte", quantity: 1, temperature: "hot" }],
  });
  assert.equal(r1.cart.items.length, 1);
  assert.equal(r1.cart.items[0].quantity, 1);
  assert.equal(r1.cart.items[0].temperature, "hot");
  assert.equal(r1.cart.total_price, 5200);

  // 2. Add Iced Cafe Latte (1)
  const r2 = await postApi("/api/commands", {
    commands: [{ intent: "ADD_ITEM", target_item_id: "cafe_latte", quantity: 1, temperature: "iced" }],
  });
  assert.equal(r2.cart.items.length, 2);
  assert.equal(r2.cart.total_price, 10400);

  // 3. Change Hot Cafe Latte to Iced -> must merge into single Iced Cafe Latte (2)
  const r3 = await postApi("/api/commands", {
    commands: [{
      intent: "UPDATE_OPTION",
      target_item_id: "cafe_latte",
      quantity: 1,
      temperature: "iced",
      previous_temperature: "hot",
    }],
  });
  assert.equal(r3.cart.items.length, 1, "Should merge into 1 item row");
  assert.equal(r3.cart.items[0].menu_id, "cafe_latte");
  assert.equal(r3.cart.items[0].temperature, "iced");
  assert.equal(r3.cart.items[0].quantity, 2);
  assert.equal(r3.cart.total_price, 10400);

  // 4. Increase quantity (+) -> 3
  const r4 = await postApi("/api/commands", {
    commands: [{ intent: "UPDATE_QUANTITY", target_item_id: "cafe_latte", quantity: 3, temperature: "iced" }],
  });
  assert.equal(r4.cart.items.length, 1);
  assert.equal(r4.cart.items[0].quantity, 3);
  assert.equal(r4.cart.total_price, 15600);

  // 5. Decrease quantity (-) -> 2
  const r5 = await postApi("/api/commands", {
    commands: [{ intent: "UPDATE_QUANTITY", target_item_id: "cafe_latte", quantity: 2, temperature: "iced" }],
  });
  assert.equal(r5.cart.items.length, 1);
  assert.equal(r5.cart.items[0].quantity, 2);
  assert.equal(r5.cart.total_price, 10400);

  // 6. Delete item
  const r6 = await postApi("/api/commands", {
    commands: [{ intent: "REMOVE_ITEM", target_item_id: "cafe_latte", temperature: "iced" }],
  });
  assert.equal(r6.cart.items.length, 0);
  assert.equal(r6.cart.total_price, 0);

  // 7. Reverse: Iced 1 + Hot 1 -> change Iced to Hot -> Hot (2)
  await postApi("/api/commands", { commands: [{ intent: "ADD_ITEM", target_item_id: "cafe_latte", quantity: 1, temperature: "iced" }] });
  await postApi("/api/commands", { commands: [{ intent: "ADD_ITEM", target_item_id: "cafe_latte", quantity: 1, temperature: "hot" }] });
  const rReverse = await postApi("/api/commands", {
    commands: [{
      intent: "UPDATE_OPTION",
      target_item_id: "cafe_latte",
      quantity: 1,
      temperature: "hot",
      previous_temperature: "iced",
    }],
  });
  assert.equal(rReverse.cart.items.length, 1);
  assert.equal(rReverse.cart.items[0].temperature, "hot");
  assert.equal(rReverse.cart.items[0].quantity, 2);
  assert.equal(rReverse.cart.total_price, 10400);
});

test("LOCAL_TOUCH accessibility actions return dedicated feedback without exposing server state", async () => {
  const sandbox = setupApiSandbox();
  const api = sandbox.window.MalloApi;
  api.setLocalTouchMode(true);

  const postApi = async (path, bodyObj) => {
    const resp = await api.apiFetch(path, {
      method: "POST",
      body: JSON.stringify(bodyObj),
    });
    return resp.json();
  };

  const staffResp = await postApi("/api/accessibility", { action: "CALL_STAFF" });
  assert.equal(staffResp.success, true);
  assert.equal(staffResp.response_text, "직원을 호출했습니다. 잠시만 기다려 주세요.");

  const receiptResp = await postApi("/api/accessibility", { action: "RECEIPT" });
  assert.equal(receiptResp.success, true);
  assert.equal(receiptResp.response_text, "영수증을 출력하고 있습니다.");
});

test("LOCAL_TOUCH ADD_ITEM response text applies temperature prefix only to multi-temperature selectable items", async () => {
  const sandbox = setupApiSandbox();
  const api = sandbox.window.MalloApi;
  api.setLocalTouchMode(true);

  const postAdd = async (itemId, temp) => {
    const resp = await api.apiFetch("/api/commands", {
      method: "POST",
      body: JSON.stringify({
        commands: [{
          intent: "ADD_ITEM",
          target_item_id: itemId,
          quantity: 1,
          temperature: temp,
        }],
      }),
    });
    return resp.json();
  };

  // 1. Grapefruit Ade (single temp "iced") -> No prefix
  const r1 = await postAdd("grapefruit_ade", "iced");
  assert.equal(r1.response_text, "자몽에이드를 장바구니에 담았습니다.");

  // 2. Iced Tea (single temp "iced") -> No prefix
  const r2 = await postAdd("iced_tea", "iced");
  assert.equal(r2.response_text, "아이스티를 장바구니에 담았습니다.");

  // 3. Americano (multi temp) + iced -> Prefix "아이스 "
  const r3 = await postAdd("americano", "iced");
  assert.equal(r3.response_text, "아이스 아메리카노를 장바구니에 담았습니다.");

  // 4. Cafe Latte (multi temp) + hot -> Prefix "따뜻한 "
  const r4 = await postAdd("cafe_latte", "hot");
  assert.equal(r4.response_text, "따뜻한 카페라떼를 장바구니에 담았습니다.");

  // 5. Basque Cheesecake (no temp) -> No prefix
  const r5 = await postAdd("basque_cheesecake", null);
  assert.equal(r5.response_text, "바스크 치즈 케이크를 장바구니에 담았습니다.");
});

test("Session Boundary Scenario A: OFF -> ON ensures stale local items do not re-emerge and remote reset occurs", async () => {
  let resetCalledOnServer = false;
  let handoffPayload = null;

  const mockFetch = async (url, options = {}) => {
    const urlStr = String(url);
    if (urlStr.includes("/health")) {
      return new MockResponse(JSON.stringify({ status: "ready" }), { status: 200 });
    }
    if (urlStr.includes("/api/reset")) {
      resetCalledOnServer = true;
      return new MockResponse(JSON.stringify({ success: true }), { status: 200 });
    }
    if (urlStr.includes("/api/session/handoff")) {
      handoffPayload = JSON.parse(options.body);
      return new MockResponse(JSON.stringify({
        success: true,
        cart: {
          items: [],
          total_price: 0,
          fulfillment_type: null,
          confirmed: false,
        },
      }), { status: 200 });
    }
    throw new Error("Unhandled " + urlStr);
  };

  const sandbox = setupApiSandbox(mockFetch);
  const api = sandbox.window.MalloApi;
  api.setLocalTouchMode(true);

  // 1. Add item in LOCAL_TOUCH
  const localState = api.getLocalTouchState();
  localState.cart.items = [{ menu_id: "americano", quantity: 2, temperature: "iced", unit_price: 4700, total_price: 9400, options: {} }];
  localState.cart.total_price = 9400;

  // 2. Trigger reset (e.g. return home / start new session)
  api.resetLocalTouchState();
  assert.equal(localState.cart.items.length, 0);
  assert.equal(api.remoteResetPending, true);

  // 3. Server turns ON -> handoff triggered
  const cart = await api.attemptHandoffToServer("SERVICE_MODE");
  assert.equal(resetCalledOnServer, true, "Remote reset must be called before handoff");
  assert.equal(api.remoteResetPending, false, "remoteResetPending must be cleared after successful reset");
  assert.deepEqual(handoffPayload.items, [], "Handoff payload must contain clean empty cart");
  assert.equal(api.adapterMode, "REMOTE");
  assert.equal(cart.items.length, 0);
});

test("Session Boundary Scenario B: ON -> OFF ensures clean local cart when server drops during session boundary", async () => {
  const mockFetch = async () => {
    throw new TypeError("Failed to fetch (server dropped offline)");
  };

  const sandbox = setupApiSandbox(mockFetch);
  const api = sandbox.window.MalloApi;
  api.setLocalTouchMode(false); // start in REMOTE

  // Populate previous local state
  const localState = api.getLocalTouchState();
  localState.cart.items = [{ menu_id: "cafe_latte", quantity: 1, temperature: "hot", unit_price: 5200, total_price: 5200, options: {} }];

  // Reset session while server is offline
  await api.apiFetch("/api/reset", { method: "POST" });
  assert.equal(api.adapterMode, "LOCAL_TOUCH");
  assert.equal(localState.cart.items.length, 0, "Local cart must be completely empty");
  assert.equal(api.remoteResetPending, true, "remoteResetPending must be marked true");
});

test("Session Boundary Scenario C: ON -> OFF -> ON resets stale server session and hands off only newly added local item", async () => {
  let resetCount = 0;
  let handoffPayload = null;

  const mockFetch = async (url, options = {}) => {
    const urlStr = String(url);
    if (urlStr.includes("/health")) {
      return new MockResponse(JSON.stringify({ status: "ready" }), { status: 200 });
    }
    if (urlStr.includes("/api/reset")) {
      resetCount++;
      return new MockResponse(JSON.stringify({ success: true }), { status: 200 });
    }
    if (urlStr.includes("/api/session/handoff")) {
      handoffPayload = JSON.parse(options.body);
      return new MockResponse(JSON.stringify({
        success: true,
        cart: {
          items: [
            { menu_id: "matcha_latte", quantity: 1, temperature: "iced", unit_price: 3500, total_price: 3500, options: {} },
          ],
          total_price: 3500,
          fulfillment_type: "takeout",
          confirmed: false,
        },
      }), { status: 200 });
    }
    throw new Error("Unhandled " + urlStr);
  };

  const sandbox = setupApiSandbox(mockFetch);
  const api = sandbox.window.MalloApi;
  api.setLocalTouchMode(true);

  // 1. Reset local session while in LOCAL_TOUCH
  api.resetLocalTouchState();
  assert.equal(api.remoteResetPending, true);

  // 2. Add only 1 new item in LOCAL_TOUCH
  await api.apiFetch("/api/commands", {
    method: "POST",
    body: JSON.stringify({
      commands: [
        { intent: "SET_FULFILLMENT", fulfillment_type: "takeout" },
        { intent: "ADD_ITEM", target_item_id: "matcha_latte", quantity: 1, temperature: "iced" },
      ],
    }),
  });

  const localState = api.getLocalTouchState();
  assert.equal(localState.cart.items.length, 1);
  assert.equal(localState.cart.items[0].menu_id, "matcha_latte");

  // 3. Server comes ON -> attempt handoff
  const handedOffCart = await api.attemptHandoffToServer("ORDER");
  assert.equal(resetCount, 1, "Server must be reset to discard stale previous session");
  assert.equal(api.remoteResetPending, false);
  assert.equal(handoffPayload.items.length, 1);
  assert.equal(handoffPayload.items[0].menu_id, "matcha_latte");
  assert.equal(handedOffCart.items.length, 1);
  assert.equal(api.adapterMode, "REMOTE");
});

test("Session Boundary Scenario D: OFF -> ON -> OFF maintains clean boundary without re-emergence of old items", async () => {
  let serverOnline = true;
  const mockFetch = async (url) => {
    if (!serverOnline) throw new TypeError("Offline");
    const urlStr = String(url);
    if (urlStr.includes("/health")) return new MockResponse(JSON.stringify({ status: "ready" }));
    if (urlStr.includes("/api/reset")) return new MockResponse(JSON.stringify({ success: true }));
    if (urlStr.includes("/api/session/handoff")) {
      return new MockResponse(JSON.stringify({
        success: true,
        cart: { items: [], total_price: 0, fulfillment_type: null, confirmed: false },
      }));
    }
    throw new Error("Unhandled " + urlStr);
  };

  const sandbox = setupApiSandbox(mockFetch);
  const api = sandbox.window.MalloApi;

  // 1. Start in OFF
  serverOnline = false;
  api.setLocalTouchMode(true);
  const localState = api.getLocalTouchState();
  localState.cart.items = [{ menu_id: "americano", quantity: 1, temperature: "iced", unit_price: 4700, total_price: 4700, options: {} }];

  // 2. Reset session in OFF
  api.resetLocalTouchState();
  assert.equal(localState.cart.items.length, 0);

  // 3. Server comes ON
  serverOnline = true;
  await api.attemptHandoffToServer("SERVICE_MODE");
  assert.equal(api.adapterMode, "REMOTE");

  // 4. Server goes OFF again -> reset session
  serverOnline = false;
  await api.apiFetch("/api/reset", { method: "POST" });
  assert.equal(api.adapterMode, "LOCAL_TOUCH");
  assert.equal(localState.cart.items.length, 0);
});

test("Session Boundary Scenario E: Remote reset failure keeps LOCAL_TOUCH and preserves current local cart without remote promotion", async () => {
  let handoffCalled = false;
  const mockFetch = async (url) => {
    const urlStr = String(url);
    if (urlStr.includes("/health")) return new MockResponse(JSON.stringify({ status: "ready" }));
    if (urlStr.includes("/api/reset")) {
      return new MockResponse(JSON.stringify({ error: "server error during reset" }), { status: 500 });
    }
    if (urlStr.includes("/api/session/handoff")) {
      handoffCalled = true;
      return new MockResponse(JSON.stringify({ success: true }));
    }
    throw new Error("Unhandled " + urlStr);
  };

  const sandbox = setupApiSandbox(mockFetch);
  const api = sandbox.window.MalloApi;
  api.setLocalTouchMode(true);

  api.resetLocalTouchState();
  assert.equal(api.remoteResetPending, true);

  // Add local item
  const localState = api.getLocalTouchState();
  localState.cart.items = [{ menu_id: "vanilla_latte", quantity: 1, temperature: "iced", unit_price: 3400, total_price: 3400, options: {} }];

  // Attempt handoff
  const result = await api.attemptHandoffToServer("ORDER");
  assert.equal(result, false, "Handoff must fail when remote reset fails");
  assert.equal(handoffCalled, false, "Handoff endpoint must NOT be called if reset fails");
  assert.equal(api.adapterMode, "LOCAL_TOUCH", "Must remain in LOCAL_TOUCH mode");
  assert.equal(localState.cart.items.length, 1, "Local cart items must be preserved");
  assert.equal(localState.cart.items[0].menu_id, "vanilla_latte");
  assert.equal(api.remoteResetPending, true, "remoteResetPending must remain true for future retry");
});
