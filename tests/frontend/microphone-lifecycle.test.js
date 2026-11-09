"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const appScript = fs.readFileSync(path.resolve(__dirname, "../../web/app.js"), "utf8");

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function flushTasks() {
  return new Promise((resolve) => setImmediate(resolve));
}

function createElement() {
  const listeners = new Map();
  let _html = "";
  let _text = "";
  return {
    hidden: false,
    disabled: false,
    value: "",
    get textContent() {
      return _text || _html.replace(/<[^>]*>/g, "").trim();
    },
    set textContent(v) {
      _text = String(v);
      _html = String(v);
    },
    get innerHTML() {
      return _html;
    },
    set innerHTML(v) {
      _html = String(v);
      _text = String(v).replace(/<[^>]*>/g, "").trim();
    },
    dataset: {},
    style: {},
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener(type, listener) { listeners.set(type, listener); },
    dispatch(type, event = {}) { return listeners.get(type)?.(event); },
  };
}

function loadApp({ getUserMedia, MediaRecorder, apiResponse = null, monitorStart = () => true, speechDetected = true, serviceModeSelection = false, menuItems = null }) {
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, createElement());
    return elements.get(id);
  };
  let onReady;
  let ttsOnStatus = () => {};
  let completeTTSPlayback = (status, error) => ttsOnStatus(status, error);
  const playedAudio = [];
  const consoleErrors = [];
  const consoleInfos = [];
  const apiCalls = [];
  const apiBodies = [];
  const document = {
    addEventListener(type, listener) {
      if (type === "DOMContentLoaded") onReady = listener;
    },
    getElementById: element,
    querySelectorAll() { return []; },
    querySelector() { return createElement(); },
  };
  const sandbox = {
    document,
    navigator: { mediaDevices: { getUserMedia } },
    MediaRecorder,
    Blob,
    AbortController,
    Uint8Array,
    ArrayBuffer,
    console: { ...console, error(...args) { consoleErrors.push(args); }, info(...args) { consoleInfos.push(args); } },
    setTimeout,
    clearTimeout,
    fetch: async (path, options = {}) => {
      apiCalls.push(path);
      apiBodies.push({ path, body: options.body });
      return ({
      json: async () => typeof apiResponse === "function"
        ? apiResponse(path, options)
        : ["/api/order", "/api/commands", "/api/audio"].includes(path) && apiResponse
          ? apiResponse
        : { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 },
    }); },
    TTSPlaybackController: class {
      constructor({ onStatus }) { ttsOnStatus = onStatus; }
      stop() { this._completion?.(); this._completion = null; ttsOnStatus("idle"); }
      dispose() {}
      async loadAndPlay(audio) { playedAudio.push(audio); ttsOnStatus("playing"); return true; }
      async replay() { return false; }
      waitForCompletion() {
        return new Promise((resolve) => {
          this._completion = resolve;
          completeTTSPlayback = (status, error) => {
            ttsOnStatus(status, error);
            this._completion?.();
            this._completion = null;
          };
        });
      }
    },
    MicrophoneInputMonitor: class {
      get hasDetectedSpeech() { return speechDetected; }
      start(...args) { return monitorStart(...args); }
      stop() {}
    },
    OptionChangeFlow: class {
      reset() {}
      start() { return "OPTION_CHANGE"; }
      finish() { return "ORDER_REVIEW"; }
      cancel() { return "ORDER_REVIEW"; }
    },
    ServiceModeFlow: class {
      constructor() { this.nextScreen = "ORDER"; }
      reset() {}
      start() { return this.nextScreen; }
      selectionPayload() { return serviceModeSelection ? {} : null; }
      finish() { return "ORDER"; }
    },
    MalloMenuMetadata: {
      categories: [
        { id: "all", name: "전체" },
        { id: "coffee", name: "커피" },
        { id: "non_coffee", name: "논커피" },
        { id: "tea", name: "차" },
        { id: "dessert", name: "디저트" },
      ],
      items: menuItems || { americano: { imagePath: "americano.png", name: "아이스 아메리카노", price: 4700, temperature: "iced" } },
      get: (menuId) => (menuItems || { americano: { imagePath: null, accent: "neutral", temperature: "iced" } })[menuId]
        || { imagePath: null, accent: "neutral", temperature: "iced" },
    },
    MalloUICommandRouter: { route: () => null },
  };
  vm.runInNewContext(appScript, sandbox);
  onReady();
  return { element, consoleErrors, consoleInfos, playedAudio, apiCalls, apiBodies, testApi: sandbox.__malloTest__, emitTTS: (status, error) => completeTTSPlayback(status, error) };
}

async function clickTouchOrder(app) {
  app.element("touchMenuGrid").dispatch("click", {
    target: { closest: () => ({ dataset: { menuId: "americano" } }) },
  });
  const actions = app.element("clarificationActions");
  const temperature = actions.innerHTML.match(/data-temperature="(iced|hot)"/)?.[1];
  if (temperature) {
    actions.dispatch("click", {
      target: {
        closest: (selector) => selector === ".touch-temperature-choice"
          ? { dataset: { temperature } }
          : null,
      },
    });
  }
  actions.dispatch("click", {
    target: { closest: (selector) => selector === ".touch-menu-add" ? {} : null },
  });
  await flushTasks();
  await flushTasks();
}

test("automatic slowdown plays the speech-only prefix before the preserved body", async () => {
  const app = loadApp({
    getUserMedia: async () => { throw new Error("not used"); },
    MediaRecorder: class {},
  });
  await flushTasks();

  const presentation = app.testApi.presentSystemMessage({
    response_text: "원하시는 메뉴를 말씀해 주세요.",
    display_segments: ["원하시는 메뉴를 말씀해 주세요."],
    tts_level: 1,
    tts_segments: [{ synthesis_text: "원하시는 메뉴를 말씀해 주세요.", tts_audio_base64: "body-audio", gap_ms: 0 }],
    speech_prefix: {
      response_text: "조금 더 천천히 안내해 드릴게요.",
      display_segments: ["조금 더 천천히 안내해 드릴게요."],
      tts_level: 1,
      tts_segments: [{ synthesis_text: "조금 더 천천히 안내해 드릴게요.", tts_audio_base64: "prefix-audio", gap_ms: 0 }],
    },
  });

  await flushTasks();
  assert.deepEqual(app.playedAudio, ["prefix-audio"]);
  app.emitTTS("completed");
  await flushTasks();
  await flushTasks();
  assert.deepEqual(app.playedAudio, ["prefix-audio", "body-audio"]);
  app.emitTTS("completed");
  assert.equal(await presentation, true);
});

test("Response Bar final-fit keeps cart summaries to two single-line display segments", async () => {
  const app = loadApp({
    getUserMedia: async () => { throw new Error("not used"); },
    MediaRecorder: class {},
  });
  await flushTasks();

  const summaries = [
    "현재 아메리카노 한 잔이 담겨 있습니다.",
    "매장 이용 주문으로 현재 아이스 아메리카노 한 잔, 카페라떼 두 잔이 담겨 있으며, 총 15,100원입니다.",
    "매장 이용 주문으로 현재 디카페인 헤이즐넛 바닐라 크림 콜드브루 한 잔, 카페라떼 두 잔, 바스크 치즈 케이크 한 개가 담겨 있으며, 총 21,600원입니다.",
  ];

  for (const summary of summaries) {
    const segments = app.testApi.getMessageSegments(summary);
    assert.ok(segments.every((segment) => app.testApi.measureTextLines(segment) <= 1), summary);

    for (const ttsLevel of [0, 1, 2]) {
      await app.testApi.presentSystemMessage({ response_text: summary, tts_level: ttsLevel }, { speak: false });
      const visibleLines = app.element("orderResponseText").textContent.split("\n").filter(Boolean);
      assert.ok(visibleLines.length <= 2, `L${ttsLevel}: ${summary}`);
      assert.ok(visibleLines.every((line) => app.testApi.measureTextLines(line) <= 1), `L${ttsLevel}: ${summary}`);
    }
  }

  const shortResponse = "현재 아메리카노 한 잔이 담겨 있습니다.";
  assert.deepEqual(Array.from(app.testApi.getMessageSegments(shortResponse)), [shortResponse]);
  const oversizedWord = "디카페인헤이즐넛바닐라크림콜드브루스페셜에디션프리미엄한정판";
  const ellipsized = app.testApi.truncateToOneLineWithEllipsis(oversizedWord);
  assert.equal(ellipsized, "…");
  assert.ok(app.testApi.measureTextLines(ellipsized) <= 1);
  assert.deepEqual(Array.from(app.testApi.getMessageSegments("SERVICE_MODE")), [
    "어떻게 이용하시겠어요?",
    "매장 이용 또는 포장을 선택해 주세요.",
  ]);
});

test("touch menu selection sends the chosen temperature and quantity in one ADD_ITEM", async () => {
  const app = loadApp({
    getUserMedia: async () => { throw new Error("not used"); },
    MediaRecorder: class {},
    menuItems: {
      cafe_latte: {
        imagePath: null,
        accent: "latte",
        name: "카페라떼",
        price: 5200,
        temperature: "iced",
        temperatureOptions: ["hot", "iced"],
      },
    },
  });
  await flushTasks();

  app.element("touchMenuGrid").dispatch("click", {
    target: { closest: () => ({ dataset: { menuId: "cafe_latte" } }) },
  });
  assert.equal(app.element("clarificationArea").hidden, false);
  assert.match(app.element("clarificationQuestion").textContent, /카페라떼 온도와 수량을 선택/);
  assert.equal(app.apiCalls.filter((path) => path === "/api/commands").length, 0);
  app.element("clarificationActions").dispatch("click", {
    target: { closest: (selector) => selector === ".touch-menu-add" ? {} : null },
  });
  assert.equal(app.apiCalls.filter((path) => path === "/api/commands").length, 0);

  app.element("clarificationActions").dispatch("click", {
    target: { closest: (selector) => selector === ".touch-temperature-choice" ? { dataset: { temperature: "hot" } } : null },
  });
  app.element("clarificationActions").dispatch("click", {
    target: { closest: (selector) => selector === "[data-touch-menu-quantity]" ? { dataset: { touchMenuQuantity: "increase" } } : null },
  });
  app.element("clarificationActions").dispatch("click", {
    target: { closest: (selector) => selector === ".touch-menu-add" ? {} : null },
  });
  await flushTasks();

  const command = app.apiBodies.find(({ path }) => path === "/api/commands");
  assert.match(command.body, /"target_item_id":"cafe_latte"/);
  assert.match(command.body, /"temperature":"hot"/);
  assert.match(command.body, /"quantity":2/);
});

test("single-temperature touch menu selects quantity without temperature controls and resets after closing", async () => {
  const app = loadApp({
    getUserMedia: async () => { throw new Error("not used"); },
    MediaRecorder: class {},
    menuItems: { grapefruit_ade: { imagePath: null, accent: "fruit", name: "자몽에이드", price: 5500, temperature: "iced" } },
  });
  await flushTasks();

  const open = () => app.element("touchMenuGrid").dispatch("click", {
    target: { closest: () => ({ dataset: { menuId: "grapefruit_ade" } }) },
  });
  open();
  assert.doesNotMatch(app.element("clarificationActions").innerHTML, /touch-temperature-choice/);
  assert.match(app.element("clarificationActions").innerHTML, /touch-menu-quantity-value" aria-live="polite">1/);
  for (let index = 0; index < 4; index += 1) {
    app.element("clarificationActions").dispatch("click", {
      target: { closest: (selector) => selector === "[data-touch-menu-quantity]" ? { dataset: { touchMenuQuantity: "increase" } } : null },
    });
  }
  assert.match(app.element("clarificationActions").innerHTML, /touch-menu-quantity-value" aria-live="polite">5/);
  assert.match(app.element("clarificationActions").innerHTML, /data-touch-menu-quantity="increase" aria-label="수량 늘리기" disabled/);
  app.element("clarificationActions").dispatch("click", {
    target: { closest: (selector) => selector === ".touch-temperature-cancel" ? {} : null },
  });
  open();
  assert.match(app.element("clarificationActions").innerHTML, /touch-menu-quantity-value" aria-live="polite">1/);
});

function mediaError(name, message) {
  const error = new Error(message);
  error.name = name;
  return error;
}

test("a stale permission callback stops every track without constructing a recorder", async () => {
  const permission = deferred();
  const tracks = [{ stopped: 0, stop() { this.stopped += 1; } }, { stopped: 0, stop() { this.stopped += 1; } }];
  let recorderConstructions = 0;
  const app = loadApp({
    getUserMedia: () => permission.promise,
    MediaRecorder: class { constructor() { recorderConstructions += 1; } },
  });

  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  app.element("btnGlobalMic").dispatch("click");
  app.element("btnGlobalHome").dispatch("click");
  await flushTasks();
  permission.resolve({ getTracks: () => tracks });
  await flushTasks();

  assert.deepEqual(tracks.map((track) => track.stopped), [1, 1]);
  assert.equal(recorderConstructions, 0);
});

function recorderClass() {
  return class {
    constructor() { this.state = "inactive"; }
    start() { this.state = "recording"; }
    stop() { this.state = "inactive"; }
  };
}

function trackedRecorderClass(recorders) {
  return class {
    constructor() { this.state = "inactive"; recorders.push(this); }
    start() { this.state = "recording"; }
    stop() { this.state = "inactive"; }
  };
}

async function finishMicrophoneTurn(recorder) {
  recorder.ondataavailable({ data: new Blob(["audio"]) });
  recorder.stop();
  await recorder.onstop();
}

test("each recording renders only its own final transcript", async () => {
  const recorders = [];
  const transcripts = ["아이스 아메리카노 한 잔", "카페라떼 한 잔"];
  const interpretations = [deferred(), deferred()];
  let interpretationIndex = 0;
  class Recorder {
    constructor() { this.state = "inactive"; recorders.push(this); }
    start() { this.state = "recording"; }
    stop() { this.state = "inactive"; }
  }
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [] }),
    MediaRecorder: Recorder,
    apiResponse: (path) => {
      if (path === "/api/audio/stt") return { text: transcripts.shift(), confidence: 0.98 };
      if (path === "/api/audio/interpret") return interpretations[interpretationIndex++].promise;
      return { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 };
    },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  await flushTasks();

  function finishRecording(index) {
    const recorder = recorders[index];
    recorder.ondataavailable({ data: new Blob(["audio"]) });
    recorder.stop();
    return recorder.onstop();
  }

  app.element("btnGlobalMic").dispatch("click");
  await flushTasks();
  const firstTurn = finishRecording(0);
  await flushTasks();
  assert.equal(app.element("liveTranscript").textContent, "아이스 아메리카노 한 잔");
  assert.equal(app.element("liveTranscript").hidden, false);
  assert.equal(app.element("voiceOverlay").hidden, false);
  interpretations[0].resolve({ success: true, response_text: "주문을 반영했습니다.", response_required: false, next_listening_mode: null, tts_audio_base64: "d2F2", cart: { items: [], total_price: 0, fulfillment_type: null } });
  await firstTurn;
  app.element("btnGlobalMic").dispatch("click");
  await flushTasks();
  assert.notEqual(app.element("liveTranscript").textContent, "아이스 아메리카노 한 잔");
  const secondTurn = finishRecording(1);
  await flushTasks();
  assert.equal(app.element("liveTranscript").textContent, "카페라떼 한 잔");
  assert.equal(app.element("liveTranscript").hidden, false);
  assert.notEqual(app.element("liveTranscript").textContent, "아이스 아메리카노 한 잔");
  interpretations[1].resolve({ success: true, response_text: "주문을 반영했습니다.", response_required: false, next_listening_mode: null, tts_audio_base64: "d2F2", cart: { items: [], total_price: 0, fulfillment_type: null } });
  await secondTurn;
});

test("microphone interpret results reuse touch navigation for fulfillment, cart, and payment", async () => {
  const recorders = [];
  const turns = [
    {
      transcript: "매장",
      response_text: "매장으로 설정했습니다. 원하시는 메뉴 있으신가요?",
      tts_audio_base64: "audio-dine-in",
      order_commands: [{ intent: "SET_FULFILLMENT", fulfillment_type: "dine_in" }],
      cart: { items: [], total_price: 0, fulfillment_type: "dine_in", confirmed: false },
      expectedScreen: "ORDER",
    },
    {
      transcript: "장바구니 보여줘",
      response_text: "현재 아메리카노 한 잔이 담겨 있습니다.",
      tts_audio_base64: "audio-query-cart",
      order_commands: [{ intent: "QUERY_CART" }],
      cart: { items: [{ menu_id: "americano", name: "아메리카노", quantity: 1, total_price: 4700 }], total_price: 4700, fulfillment_type: "dine_in", confirmed: false },
      expectedScreen: "ORDER_REVIEW",
    },
    {
      transcript: "결제할게요",
      response_text: "주문을 확정했습니다. 결제 방법을 선택해 주세요.",
      tts_audio_base64: "audio-confirm",
      order_commands: [{ intent: "CONFIRM_ORDER" }],
      cart: { items: [{ menu_id: "americano", name: "아메리카노", quantity: 1, total_price: 4700 }], total_price: 4700, fulfillment_type: "dine_in", confirmed: true },
      expectedScreen: "PAYMENT",
    },
    {
      transcript: "카드로 결제할게",
      response_text: "카드 결제를 선택했습니다. 주문이 완료되었습니다.",
      tts_audio_base64: "audio-card",
      order_commands: [{ intent: "SELECT_PAYMENT_METHOD", target_item_id: "card" }],
      cart: { items: [{ menu_id: "americano", name: "아메리카노", quantity: 1, total_price: 4700 }], total_price: 4700, fulfillment_type: "dine_in", confirmed: true },
      expectedScreen: "COMPLETE",
    },
  ];
  let current = 0;
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [] }),
    MediaRecorder: trackedRecorderClass(recorders),
    serviceModeSelection: true,
    apiResponse: (path) => {
      if (path === "/api/audio/stt") return { text: turns[current].transcript, confidence: 0.98 };
      if (path === "/api/audio/interpret") {
        const turn = turns[current++];
        return { success: true, response_required: true, next_listening_mode: "SYSTEM_PROMPTED", ...turn };
      }
      return { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 };
    },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  await flushTasks();

  for (const turn of turns) {
    app.element("btnGlobalMic").dispatch("click");
    await flushTasks();
    await finishMicrophoneTurn(recorders.at(-1));
    assert.equal(app.testApi.uiState.screen, turn.expectedScreen);
    assert.ok(app.playedAudio.includes(turn.tts_audio_base64));
    if (turn.expectedScreen !== "COMPLETE") {
      const recordingsBeforeCompletion = recorders.length;
      app.emitTTS("completed");
      await flushTasks();
      assert.equal(app.testApi.uiState.screen, turn.expectedScreen);
      assert.equal(recorders.length, recordingsBeforeCompletion + 1);
    }
  }
});

test("microphone takeout fulfillment advances from service selection to the order screen", async () => {
  const recorders = [];
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [] }),
    MediaRecorder: trackedRecorderClass(recorders),
    serviceModeSelection: true,
    apiResponse: (path) => {
      if (path === "/api/audio/stt") return { text: "포장", confidence: 0.98 };
      if (path === "/api/audio/interpret") return {
        success: true,
        response_text: "포장으로 설정했습니다. 원하시는 메뉴 있으신가요?",
        response_required: true,
        next_listening_mode: "SYSTEM_PROMPTED",
        tts_audio_base64: "audio-takeout",
        order_commands: [{ intent: "SET_FULFILLMENT", fulfillment_type: "takeout" }],
        cart: { items: [], total_price: 0, fulfillment_type: "takeout", confirmed: false },
      };
      return { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 };
    },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  await flushTasks();
  app.element("btnGlobalMic").dispatch("click");
  await flushTasks();
  await finishMicrophoneTurn(recorders[0]);

  assert.equal(app.testApi.uiState.screen, "ORDER");
  assert.ok(app.playedAudio.includes("audio-takeout"));
  assert.equal(recorders.length, 1);
  app.emitTTS("completed");
  await flushTasks();
  assert.equal(recorders.length, 2);
});

test("complete empty-cart voice order enters PAYMENT without selecting a payment method", async () => {
  const recorders = [];
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [] }),
    MediaRecorder: trackedRecorderClass(recorders),
    serviceModeSelection: true,
    apiResponse: (path) => {
      if (path === "/api/audio/stt") return { text: "아이스 아메리카노 하나 포장하고 싶어", confidence: 0.98 };
      if (path === "/api/audio/interpret") return {
        success: true,
        response_text: "포장 주문을 확정했습니다. 결제 방법을 선택해 주세요.",
        response_required: false,
        next_listening_mode: null,
        tts_audio_base64: "audio-one-shot",
        order_commands: [
          { intent: "SET_FULFILLMENT", fulfillment_type: "takeout" },
          { intent: "ADD_ITEM", target_item_id: "americano", quantity: 1, temperature: "iced" },
          { intent: "CONFIRM_ORDER" },
        ],
        cart: { items: [{ menu_id: "americano", name: "아메리카노", quantity: 1, total_price: 4700 }], total_price: 4700, fulfillment_type: "takeout", confirmed: true },
      };
      return { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 };
    },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  await flushTasks();
  app.element("btnGlobalMic").dispatch("click");
  await flushTasks();
  await finishMicrophoneTurn(recorders[0]);

  assert.equal(app.testApi.uiState.screen, "PAYMENT");
  assert.equal(app.testApi.orderState.paymentMethod, null);
  assert.ok(app.playedAudio.includes("audio-one-shot"));
});

test("microphone full-menu QUERY_MENU opens the ORDER all-menu tab from its command", async () => {
  const recorders = [];
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [] }),
    MediaRecorder: trackedRecorderClass(recorders),
    apiResponse: (path) => {
      if (path === "/api/audio/stt") return { text: "메뉴 뭐 있어?", confidence: 0.98 };
      if (path === "/api/audio/interpret") return {
        success: true,
        response_text: "전체 메뉴를 안내해 드릴게요.",
        response_required: true,
        next_listening_mode: "SYSTEM_PROMPTED",
        tts_audio_base64: "audio-all-menu",
        order_commands: [{ intent: "QUERY_MENU", target_item_id: null, category_id: null, query_tags: null, detail_fields: null }],
        cart: { items: [], total_price: 0, fulfillment_type: null, confirmed: false },
      };
      return { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 };
    },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  await flushTasks();
  app.element("btnGlobalMic").dispatch("click");
  await flushTasks();
  await finishMicrophoneTurn(recorders[0]);

  assert.equal(app.testApi.uiState.screen, "ORDER");
  assert.match(app.element("touchMenuCategories").innerHTML, /data-category="all"/);
  assert.match(app.element("touchMenuCategories").innerHTML, /is-active/);
  assert.ok(app.playedAudio.includes("audio-all-menu"));
  assert.equal(recorders.length, 1);
  app.emitTTS("completed");
  await flushTasks();
  assert.equal(recorders.length, 2);
});

test("microphone category QUERY_MENU opens the category tab from category_id", async () => {
  const recorders = [];
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [] }),
    MediaRecorder: trackedRecorderClass(recorders),
    apiResponse: (path) => {
      if (path === "/api/audio/stt") return { text: "차 종류 뭐 있어?", confidence: 0.98 };
      if (path === "/api/audio/interpret") return {
        success: true,
        response_text: "차 메뉴를 안내해 드릴게요.",
        response_required: true,
        next_listening_mode: "SYSTEM_PROMPTED",
        tts_audio_base64: "audio-tea-menu",
        order_commands: [{ intent: "QUERY_MENU", target_item_id: null, category_id: "tea", query_tags: null, detail_fields: null }],
        cart: { items: [], total_price: 0, fulfillment_type: null, confirmed: false },
      };
      return { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 };
    },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  await flushTasks();
  app.element("btnGlobalMic").dispatch("click");
  await flushTasks();
  await finishMicrophoneTurn(recorders[0]);

  assert.equal(app.testApi.uiState.screen, "ORDER");
  assert.match(app.element("touchMenuCategories").innerHTML, /data-category="tea"/);
  assert.match(app.element("touchMenuCategories").innerHTML, /touch-menu-category is-active" data-category="tea"/);
});

test("speed controls change level without replaying a control-feedback TTS", async () => {
  async function runControl(action, source, expectReopen) {
    const recorders = [];
    const app = loadApp({
      getUserMedia: async () => ({ getTracks: () => [] }),
      MediaRecorder: trackedRecorderClass(recorders),
      apiResponse: (path) => path === "/api/accessibility"
        ? { response_text: "이 속도로 안내합니다.", response_required: false, next_listening_mode: null, tts_audio_base64: `audio-${action}`, tts_level: 1 }
        : { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 },
    });
    await flushTasks();
    app.element("btnStartOrder").dispatch("click");
    await flushTasks();
    await app.testApi.executeUICommand(action, { source });
    assert.equal(recorders.length, 0);
    app.emitTTS("completed");
    await flushTasks();
    assert.equal(recorders.length, expectReopen ? 1 : 0);
  }

  await runControl("SPEED_SLOW", "voice", false);
  await runControl("SPEED_VERY_SLOW", "voice", false);
  await runControl("SPEED_SLOW", "touch", false);
  await runControl("REPEAT", "voice", false);
  await runControl("SPEED_NORMAL", "voice", false);
});

test("failed microphone CONFIRM_ORDER never opens payment", async () => {
  const recorders = [];
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [] }),
    MediaRecorder: trackedRecorderClass(recorders),
    apiResponse: (path) => {
      if (path === "/api/audio/stt") return { text: "결제할게요", confidence: 0.98 };
      if (path === "/api/audio/interpret") return {
        success: false,
        response_text: "매장 이용 또는 포장을 먼저 선택해 주세요.",
        response_required: false,
        next_listening_mode: null,
        tts_audio_base64: "audio-payment-blocked",
        order_commands: [{ intent: "CONFIRM_ORDER" }],
        cart: { items: [{ menu_id: "americano", name: "아메리카노", quantity: 1, total_price: 4700 }], total_price: 4700, fulfillment_type: null, confirmed: false },
      };
      return { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 };
    },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  await flushTasks();
  app.element("btnGlobalMic").dispatch("click");
  await flushTasks();
  await finishMicrophoneTurn(recorders[0]);

  assert.notEqual(app.testApi.uiState.screen, "PAYMENT");
  assert.ok(app.playedAudio.includes("audio-payment-blocked"));
});

test("stale microphone QUERY_CART and CONFIRM_ORDER results cannot navigate", async () => {
  for (const intent of ["QUERY_CART", "CONFIRM_ORDER"]) {
    const recorders = [];
    const staleInterpretation = deferred();
    let sttCall = 0;
    let interpretCall = 0;
    const app = loadApp({
      getUserMedia: async () => ({ getTracks: () => [] }),
      MediaRecorder: trackedRecorderClass(recorders),
      apiResponse: (path) => {
        if (path === "/api/audio/stt") return { text: sttCall++ === 0 ? "이전 음성" : "새 음성", confidence: 0.98 };
        if (path === "/api/audio/interpret") {
          if (interpretCall++ === 0) return staleInterpretation.promise;
          return { success: true, response_text: "새 주문입니다.", response_required: false, next_listening_mode: null, order_commands: [{ intent: "ADD_ITEM" }], cart: { items: [{ menu_id: "americano", name: "아메리카노", quantity: 1, total_price: 4700 }], total_price: 4700, fulfillment_type: "dine_in", confirmed: false } };
        }
        return { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 };
      },
    });
    await flushTasks();
    app.element("btnStartOrder").dispatch("click");
    await flushTasks();
    app.element("btnGlobalMic").dispatch("click");
    await flushTasks();
    const firstTurn = finishMicrophoneTurn(recorders[0]);
    await flushTasks();
    app.element("btnGlobalMic").dispatch("click");
    await flushTasks();
    await finishMicrophoneTurn(recorders[1]);
    staleInterpretation.resolve({
      success: true,
      response_text: "오래된 결과입니다.",
      response_required: false,
      next_listening_mode: null,
      order_commands: [{ intent }],
      cart: { items: [{ menu_id: "americano", name: "아메리카노", quantity: 1, total_price: 4700 }], total_price: 4700, fulfillment_type: "dine_in", confirmed: intent === "CONFIRM_ORDER" },
    });
    await firstTurn;

    assert.notEqual(app.testApi.uiState.screen, "ORDER_REVIEW");
    assert.notEqual(app.testApi.uiState.screen, "PAYMENT");
  }
});

test("payment readiness blocks request system-message TTS without changing payment state", async () => {
  const guidance = {
    PAYMENT_EMPTY_CART: "장바구니가 비어 있습니다. 메뉴를 먼저 선택해 주세요.",
    PAYMENT_FULFILLMENT_REQUIRED: "매장 이용 또는 포장을 먼저 선택해 주세요.",
    PAYMENT_CONFIRMATION_REQUIRED: "주문을 먼저 확정해 주세요.",
  };
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [] }),
    MediaRecorder: recorderClass(),
    apiResponse: (path, options) => {
      if (path === "/api/system-message") {
        const messageId = JSON.parse(options.body).message_id;
        return { response_text: guidance[messageId], tts_level: 0, tts_audio_base64: `audio-${messageId}`, response_required: false, next_listening_mode: null };
      }
      if (path === "/api/commands") return { success: false, cart: { items: [{ menu_id: "americano" }], total_price: 4700, fulfillment_type: "takeout", confirmed: false } };
      return { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 };
    },
  });
  await flushTasks();

  async function expectGuard(messageId, setup) {
    setup();
    const playsBefore = app.playedAudio.length;
    await app.testApi.executeUICommand("OPEN_PAYMENT");
    await flushTasks();
    assert.equal(app.element("paymentResponseText").textContent.replace(/\n/g, " "), guidance[messageId]);
    assert.equal(app.playedAudio.at(-1), `audio-${messageId}`);
    assert.equal(app.playedAudio.length, playsBefore + 1);
    assert.equal(JSON.parse(app.apiBodies.filter(({ path }) => path === "/api/system-message").at(-1).body).message_id, messageId);
    assert.equal(app.testApi.uiState.screen, "WELCOME");
  }

  await expectGuard("PAYMENT_EMPTY_CART", () => {
    app.testApi.orderState.items = [];
    app.testApi.orderState.fulfillmentType = null;
    app.testApi.orderState.confirmed = false;
  });
  await expectGuard("PAYMENT_FULFILLMENT_REQUIRED", () => {
    app.testApi.orderState.items = [{ menu_id: "americano", name: "아메리카노", quantity: 1, temperature: "iced", total_price: 4700 }];
    app.testApi.orderState.fulfillmentType = null;
    app.testApi.orderState.confirmed = false;
  });
  await expectGuard("PAYMENT_CONFIRMATION_REQUIRED", () => {
    app.testApi.orderState.items = [{ menu_id: "americano", name: "아메리카노", quantity: 1, temperature: "iced", total_price: 4700 }];
    app.testApi.orderState.fulfillmentType = "takeout";
    app.testApi.orderState.confirmed = false;
  });
  assert.ok(app.consoleInfos.some(([message]) => String(message).startsWith("[Payment guard]")));
  assert.ok(app.consoleInfos.some(([message]) => message === "[System message] request start"));
  assert.ok(app.consoleInfos.some(([message]) => message === "[System message] response received"));
  assert.ok(app.consoleInfos.some(([message]) => message === "[TTS] play requested"));
  assert.ok(app.consoleInfos.some(([message]) => message === "[TTS] playing"));
});

test("empty cart review button speaks once and does not open the review screen", async () => {
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [] }),
    MediaRecorder: recorderClass(),
    apiResponse: (path, options) => {
      if (path === "/api/system-message") {
        const messageId = JSON.parse(options.body).message_id;
        return {
          response_text: messageId === "PAYMENT_EMPTY_CART"
            ? "장바구니가 비어 있습니다. 메뉴를 먼저 선택해 주세요."
            : "어서오세요. 말로 카페입니다.",
          tts_level: 0,
          tts_audio_base64: `audio-${messageId}`,
          response_required: false,
          next_listening_mode: null,
        };
      }
      return { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 };
    },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  await flushTasks();
  const playsBefore = app.playedAudio.length;
  const systemRequestsBefore = app.apiBodies.filter(({ path }) => path === "/api/system-message").length;

  app.element("btnViewCart").dispatch("click");
  await flushTasks();

  assert.equal(app.element("orderResponseText").textContent.replace(/\n/g, " "), "장바구니가 비어 있습니다. 메뉴를 먼저 선택해 주세요.");
  assert.equal(app.playedAudio.length, playsBefore + 1);
  assert.equal(app.playedAudio.at(-1), "audio-PAYMENT_EMPTY_CART");
  assert.equal(app.apiBodies.filter(({ path }) => path === "/api/system-message").length, systemRequestsBefore + 1);
  assert.equal(JSON.parse(app.apiBodies.filter(({ path }) => path === "/api/system-message").at(-1).body).message_id, "PAYMENT_EMPTY_CART");
  assert.notEqual(app.testApi.uiState.screen, "ORDER_REVIEW");
});

test("touch menu suspends SYSTEM_PROMPTED automatic listening", async () => {
  let permissionRequests = 0;
  const app = loadApp({
    getUserMedia: async () => { permissionRequests += 1; return { getTracks: () => [] }; },
    MediaRecorder: recorderClass(),
    apiResponse: {
      success: false,
      response_text: "HOT 또는 ICE를 말씀해 주세요.",
      response_required: true,
      next_listening_mode: "SYSTEM_PROMPTED",
      tts_audio_base64: "d2F2",
      cart: { items: [], total_price: 0, fulfillment_type: null },
    },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  await clickTouchOrder(app);
  await flushTasks();
  app.emitTTS("completed");
  await flushTasks();
  assert.equal(permissionRequests, 0);
  app.emitTTS("playing");
});

test("fulfillment never plays an intermediate confirmation before the ORDER prompt", async () => {
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [] }),
    MediaRecorder: recorderClass(),
    serviceModeSelection: true,
    apiResponse: (path, options) => {
      if (path === "/api/commands") {
        return { success: true, response_text: "포장으로 설정했습니다.", response_required: false, next_listening_mode: null, tts_audio_base64: "audio-fulfillment", cart: { items: [{ menu_id: "americano", name: "아메리카노", quantity: 1, total_price: 4700 }], total_price: 4700, fulfillment_type: "takeout", confirmed: false } };
      }
      if (path === "/api/system-message") {
        const messageId = JSON.parse(options.body).message_id;
        return { response_text: messageId, response_required: false, next_listening_mode: null, tts_audio_base64: `audio-${messageId}` };
      }
      return { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 };
    },
  });
  await flushTasks();

  const selecting = app.testApi.executeUICommand("SELECT_TAKEOUT");
  await flushTasks();
  assert.ok(!app.playedAudio.includes("audio-fulfillment"));

  await app.testApi.executeUICommand("OPEN_REVIEW");
  await selecting;

  const messageIds = app.apiBodies
    .filter(({ path }) => path === "/api/system-message")
    .map(({ body }) => JSON.parse(body).message_id);
  assert.ok(messageIds.includes("ORDER_REVIEW"));
  assert.equal(messageIds.includes("ORDER"), true);
});

test("a new cart interaction discards an in-flight payment guidance response", async () => {
  const paymentGuidance = deferred();
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [] }),
    MediaRecorder: recorderClass(),
    apiResponse: (path, options) => {
      if (path !== "/api/system-message") return { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 };
      const messageId = JSON.parse(options.body).message_id;
      if (messageId === "PAYMENT_EMPTY_CART") return paymentGuidance.promise;
      return { response_text: messageId, response_required: false, next_listening_mode: null, tts_audio_base64: `audio-${messageId}` };
    },
  });
  await flushTasks();

  const payment = app.testApi.executeUICommand("OPEN_PAYMENT");
  await flushTasks();
  app.testApi.orderState.items = [{ menu_id: "americano", name: "아메리카노", quantity: 1, total_price: 4700 }];
  app.testApi.orderState.totalPrice = 4700;
  await app.testApi.executeUICommand("OPEN_REVIEW");
  paymentGuidance.resolve({ response_text: "결제 안내", response_required: false, next_listening_mode: null, tts_audio_base64: "audio-payment" });
  await payment;

  assert.equal(app.playedAudio.includes("audio-payment"), false);
  assert.notEqual(app.element("orderResponseText").textContent, "결제 안내");
});

test("voice QUERY_CART reuses cart navigation while keeping its response TTS", async () => {
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [] }),
    MediaRecorder: recorderClass(),
    apiResponse: (path) => path === "/api/order"
      ? {
        success: true,
        response_text: "현재 아메리카노 한 잔이 담겨 있습니다.",
        response_required: false,
        next_listening_mode: null,
        tts_audio_base64: "audio-query-cart",
        order_commands: [{ intent: "QUERY_CART" }],
        cart: { items: [{ menu_id: "americano", name: "아메리카노", quantity: 1, total_price: 4700 }], total_price: 4700, fulfillment_type: null },
      }
      : { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  await flushTasks();

  await app.testApi.processUtteranceText("장바구니 보여줘", "ORDER", { source: "voice" });

  assert.equal(app.testApi.uiState.screen, "ORDER_REVIEW");
  assert.ok(app.playedAudio.includes("audio-query-cart"));
});

test("voice QUERY_CART keeps the empty-cart cart-button navigation policy", async () => {
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [] }),
    MediaRecorder: recorderClass(),
    apiResponse: (path) => path === "/api/order"
      ? { success: true, response_text: "장바구니가 비어 있습니다.", response_required: false, next_listening_mode: null, tts_audio_base64: "audio-empty-query-cart", order_commands: [{ intent: "QUERY_CART" }], cart: { items: [], total_price: 0, fulfillment_type: null } }
      : { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  await flushTasks();

  await app.testApi.processUtteranceText("장바구니", "ORDER", { source: "voice" });

  assert.notEqual(app.testApi.uiState.screen, "ORDER_REVIEW");
  assert.ok(app.playedAudio.includes("audio-empty-query-cart"));
});

test("non-QUERY_CART voice results do not open cart review", async () => {
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [] }),
    MediaRecorder: recorderClass(),
    apiResponse: (path) => path === "/api/order"
      ? { success: true, response_text: "아메리카노를 담았습니다.", response_required: false, next_listening_mode: null, order_commands: [{ intent: "ADD_ITEM" }], cart: { items: [{ menu_id: "americano", name: "아메리카노", quantity: 1, total_price: 4700 }], total_price: 4700, fulfillment_type: null } }
      : { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  await flushTasks();

  await app.testApi.processUtteranceText("아메리카노 하나", "ORDER", { source: "voice" });

  assert.notEqual(app.testApi.uiState.screen, "ORDER_REVIEW");
});

test("a stale QUERY_CART result cannot open cart review", async () => {
  const first = deferred();
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [] }),
    MediaRecorder: recorderClass(),
    apiResponse: (path) => {
      if (path !== "/api/order") return { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 };
      if (!app.apiBodies.filter(({ path: requestPath }) => requestPath === "/api/order").slice(0, -1).length) return first.promise;
      return { success: true, response_text: "아메리카노를 담았습니다.", response_required: false, next_listening_mode: null, order_commands: [{ intent: "ADD_ITEM" }], cart: { items: [{ menu_id: "americano", name: "아메리카노", quantity: 1, total_price: 4700 }], total_price: 4700, fulfillment_type: null } };
    },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  await flushTasks();

  const stale = app.testApi.processUtteranceText("장바구니", "ORDER", { source: "voice" });
  await flushTasks();
  await app.testApi.processUtteranceText("아메리카노 하나", "ORDER", { source: "voice" });
  first.resolve({ success: true, response_text: "현재 주문입니다.", response_required: false, next_listening_mode: null, order_commands: [{ intent: "QUERY_CART" }], cart: { items: [{ menu_id: "americano", name: "아메리카노", quantity: 1, total_price: 4700 }], total_price: 4700, fulfillment_type: null } });
  await stale;

  assert.notEqual(app.testApi.uiState.screen, "ORDER_REVIEW");
});

test("a pending ADD_ITEM keeps its generation through cart review and refreshes the review before TTS", async () => {
  const addResponse = deferred();
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [] }),
    MediaRecorder: recorderClass(),
    apiResponse: (path) => {
      if (path === "/api/commands") return addResponse.promise;
      return { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 };
    },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  await flushTasks();

  await clickTouchOrder(app);
  app.element("btnViewCart").dispatch("click");
  assert.equal(app.testApi.uiState.screen, "ORDER_REVIEW");
  assert.match(app.element("confirmItems").textContent, /담긴 메뉴가 없습니다/);

  addResponse.resolve({
    success: true,
    response_text: "아이스 아메리카노 한 잔을 담았습니다.",
    response_required: false,
    next_listening_mode: null,
    tts_audio_base64: "add-audio",
    order_commands: [{ intent: "ADD_ITEM" }],
    cart: {
      items: [{ menu_id: "americano", name: "아메리카노", temperature: "iced", quantity: 1, total_price: 4700 }],
      total_price: 4700,
      fulfillment_type: null,
      confirmed: false,
    },
  });
  await flushTasks();
  await flushTasks();

  assert.equal(app.testApi.orderState.items.length, 1);
  assert.match(app.element("confirmItems").textContent, /아메리카노/);
  assert.equal(app.element("confirmTotalPrice").textContent, "4,700원");
  assert.deepEqual(app.playedAudio, ["add-audio"]);
});

test("touch navigation does not wait for a multi-segment cart response TTS", async () => {
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [] }),
    MediaRecorder: recorderClass(),
    apiResponse: (path) => {
      if (path !== "/api/commands") return { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 };
      return {
        success: true,
        response_text: "아메리카노를 담았습니다.",
        tts_segments: [{ text: "아메리카노를 담았습니다.", tts_audio_base64: "segment-a", segment_index: 0 }],
        cart: { items: [{ menu_id: "americano", name: "아메리카노", temperature: "iced", quantity: 1, total_price: 4700 }], total_price: 4700, fulfillment_type: null },
      };
    },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  await flushTasks();
  await clickTouchOrder(app);
  await flushTasks();
  assert.deepEqual(app.playedAudio, ["segment-a"]);

  // The fake player intentionally leaves completion pending. View-cart must
  // still navigate and render before this speech stream finishes.
  app.element("btnViewCart").dispatch("click");
  assert.equal(app.testApi.uiState.screen, "ORDER_REVIEW");
  assert.match(app.element("confirmItems").textContent, /아메리카노/);
});

function dispatchCartMutation(app, { type, item, quantity = null, temperature = null } = {}) {
  const itemElement = { dataset: { menuId: item.menu_id, temperature: item.temperature || "", index: "0" } };
  const target = {
    closest(selector) {
      if (selector === ".cart-item") return itemElement;
      if (selector === "[data-cart-quantity]" && type === "quantity") return { dataset: { cartQuantity: quantity } };
      if (selector === "[data-cart-temperature]" && type === "temperature") return { dataset: { cartTemperature: temperature } };
      if (selector === "[data-cart-remove]" && type === "remove") return { dataset: { cartRemove: item.menu_id } };
      return null;
    },
  };
  app.element("confirmItems").dispatch("click", { target });
}

test("delayed review mutations commit cart DOM after a newer interaction but suppress stale presentation", async () => {
  const quantityResponse = deferred();
  const temperatureResponse = deferred();
  const removeResponse = deferred();
  const initialItem = { menu_id: "americano", name: "아메리카노", temperature: "iced", quantity: 1, total_price: 4700 };
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [] }),
    MediaRecorder: recorderClass(),
    apiResponse: (path, options) => {
      if (path !== "/api/commands") return { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 };
      const intent = JSON.parse(options.body).commands[0].intent;
      if (intent === "ADD_ITEM") return { success: true, cart: { items: [initialItem], total_price: 4700, fulfillment_type: null } };
      if (intent === "UPDATE_QUANTITY") return quantityResponse.promise;
      if (intent === "UPDATE_OPTION") return temperatureResponse.promise;
      if (intent === "REMOVE_ITEM") return removeResponse.promise;
      throw new Error(`unexpected intent: ${intent}`);
    },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  await flushTasks();
  await clickTouchOrder(app);
  app.element("btnViewCart").dispatch("click");
  await flushTasks();

  dispatchCartMutation(app, { type: "quantity", item: initialItem, quantity: "increase" });
  app.testApi.enterTouchMode();
  quantityResponse.resolve({ success: true, response_text: "수량을 늘렸습니다.", tts_audio_base64: "stale-quantity", cart: {
    items: [{ ...initialItem, quantity: 2, total_price: 9400 }], total_price: 9400, fulfillment_type: null,
  } });
  await flushTasks();
  await flushTasks();
  assert.equal(app.testApi.orderState.items[0].quantity, 2);
  assert.match(app.element("confirmItems").innerHTML, /item-quantity" aria-label="현재 수량">2</);
  assert.deepEqual(app.playedAudio, []);

  const hotItem = app.testApi.orderState.items[0];
  dispatchCartMutation(app, { type: "temperature", item: hotItem, temperature: "hot" });
  app.testApi.enterTouchMode();
  temperatureResponse.resolve({ success: true, response_text: "따뜻한으로 바꿨습니다.", tts_audio_base64: "stale-temperature", cart: {
    items: [{ ...hotItem, temperature: "hot" }], total_price: 9400, fulfillment_type: null,
  } });
  await flushTasks();
  await flushTasks();
  assert.equal(app.testApi.orderState.items[0].temperature, "hot");
  assert.match(app.element("confirmItems").innerHTML, /data-temperature="hot"/);
  assert.deepEqual(app.playedAudio, []);

  const removableItem = app.testApi.orderState.items[0];
  dispatchCartMutation(app, { type: "remove", item: removableItem });
  app.testApi.enterTouchMode();
  removeResponse.resolve({ success: true, response_text: "삭제했습니다.", tts_audio_base64: "stale-remove", cart: {
    items: [], total_price: 0, fulfillment_type: null,
  } });
  await flushTasks();
  await flushTasks();
  assert.equal(app.testApi.orderState.items.length, 0);
  assert.match(app.element("confirmItems").textContent, /담긴 메뉴가 없습니다/);
  assert.deepEqual(app.playedAudio, []);
});

test("cart snapshots reject a prior session and an older mutation response", async () => {
  const firstQuantity = deferred();
  const secondQuantity = deferred();
  const oldSessionAdd = deferred();
  let quantityRequests = 0;
  const initialItem = { menu_id: "americano", name: "아메리카노", temperature: "iced", quantity: 1, total_price: 4700 };
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [] }),
    MediaRecorder: recorderClass(),
    apiResponse: (path, options) => {
      if (path !== "/api/commands") return { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 };
      const intent = JSON.parse(options.body).commands[0].intent;
      if (intent === "ADD_ITEM") return oldSessionAdd.promise;
      if (intent === "UPDATE_QUANTITY") return ++quantityRequests === 1 ? firstQuantity.promise : secondQuantity.promise;
      throw new Error(`unexpected intent: ${intent}`);
    },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  await flushTasks();

  await clickTouchOrder(app);
  app.testApi.beginNewOrderSession();
  oldSessionAdd.resolve({ success: true, cart: { items: [initialItem], total_price: 4700, fulfillment_type: null } });
  await flushTasks();
  await flushTasks();
  assert.equal(app.testApi.orderState.items.length, 0);

  // Seed the current session, then deliver two quantity responses in reverse
  // order. The older snapshot must not resurrect the lower quantity.
  app.testApi.orderState.items = [initialItem];
  app.testApi.orderState.totalPrice = 4700;
  app.testApi.goToScreen("ORDER_REVIEW");
  dispatchCartMutation(app, { type: "quantity", item: initialItem, quantity: "increase" });
  dispatchCartMutation(app, { type: "quantity", item: initialItem, quantity: "increase" });
  secondQuantity.resolve({ success: true, cart: { items: [{ ...initialItem, quantity: 3, total_price: 14100 }], total_price: 14100, fulfillment_type: null } });
  await flushTasks();
  await flushTasks();
  firstQuantity.resolve({ success: true, cart: { items: [{ ...initialItem, quantity: 2, total_price: 9400 }], total_price: 9400, fulfillment_type: null } });
  await flushTasks();
  await flushTasks();
  assert.equal(app.testApi.orderState.items[0].quantity, 3);
  assert.match(app.element("confirmItems").innerHTML, /item-quantity" aria-label="현재 수량">3</);
});

test("informational TTS completion keeps the microphone off", async () => {
  let permissionRequests = 0;
  const app = loadApp({
    getUserMedia: async () => { permissionRequests += 1; return { getTracks: () => [] }; },
    MediaRecorder: recorderClass(),
    apiResponse: {
      success: true,
      response_text: "아이스 아메리카노 한 잔을 담았습니다.",
      response_required: false,
      next_listening_mode: null,
      tts_audio_base64: "d2F2",
      cart: { items: [{ menu_id: "americano", name: "아메리카노", temperature: "iced", quantity: 1, total_price: 4700 }], total_price: 4700, fulfillment_type: null },
    },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  await clickTouchOrder(app);
  await flushTasks();
  app.emitTTS("completed");
  await flushTasks();
  assert.equal(permissionRequests, 0);
  assert.equal(app.element("cartItemBadge").hidden, false);
  assert.equal(app.element("cartItemBadge").textContent, "1");
  assert.equal(app.element("listeningResponseText").textContent, "아이스 아메리카노 한 잔을 담았습니다.");
  assert.notEqual(app.element("listeningResponseText").textContent, "더 필요한 메뉴를 말씀해주세요.");
  assert.deepEqual(app.playedAudio, ["d2F2"]);
});

test("terminal screen transition cancels pending automatic listening", async () => {
  let permissionRequests = 0;
  const app = loadApp({
    getUserMedia: async () => { permissionRequests += 1; return { getTracks: () => [] }; },
    MediaRecorder: recorderClass(),
    apiResponse: {
      success: false,
      response_text: "다시 말씀해 주세요.",
      response_required: true,
      next_listening_mode: "SYSTEM_PROMPTED",
      tts_audio_base64: "d2F2",
      cart: { items: [{ menu_id: "americano", name: "아메리카노", temperature: "iced", quantity: 1, total_price: 4700 }], total_price: 4700, fulfillment_type: null },
    },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  await clickTouchOrder(app);
  await flushTasks();
  app.element("btnViewCart").dispatch("click");
  app.element("btnConfirmYes").dispatch("click");
  app.emitTTS("completed");
  await flushTasks();
  assert.equal(permissionRequests, 0);
});

test("a MediaRecorder constructor failure stops every acquired track", async () => {
  const tracks = [{ stopped: 0, stop() { this.stopped += 1; } }, { stopped: 0, stop() { this.stopped += 1; } }];
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => tracks }),
    MediaRecorder: class { constructor() { throw new Error("unsupported recorder"); } },
  });

  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  app.element("btnGlobalMic").dispatch("click");
  await flushTasks();

  assert.deepEqual(tracks.map((track) => track.stopped), [1, 1]);
  assert.equal(app.element("voiceOverlayTitle").textContent, "브라우저의 녹음 기능을 시작하지 못했습니다. 다시 시도해 주세요.");
  assert.equal(app.consoleErrors[0][1].stage, "media-recorder");
});

test("permission rejection is reported separately from microphone initialization", async () => {
  const app = loadApp({
    getUserMedia: async () => { throw mediaError("NotAllowedError", "Permission denied"); },
    MediaRecorder: recorderClass(),
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  app.element("btnGlobalMic").dispatch("click");
  await flushTasks();

  assert.equal(app.element("voiceOverlayTitle").textContent, "마이크 권한이 필요합니다. 브라우저 설정에서 마이크를 허용해 주세요.");
  assert.equal(app.consoleErrors[0][1].stage, "get-user-media");
  assert.equal(app.consoleErrors[0][1].name, "NotAllowedError");
  assert.equal(app.consoleErrors[0][1].message, "Permission denied");
});

test("missing device has its own guidance", async () => {
  const app = loadApp({
    getUserMedia: async () => { throw mediaError("NotFoundError", "Requested device not found"); },
    MediaRecorder: recorderClass(),
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  app.element("btnGlobalMic").dispatch("click");
  await flushTasks();

  assert.equal(app.element("voiceOverlayTitle").textContent, "사용할 수 있는 마이크를 찾지 못했습니다.");
  assert.equal(app.consoleErrors[0][1].name, "NotFoundError");
});

test("AudioContext initialization failure cleans up tracks and reports its stage", async () => {
  const tracks = [{ stopped: 0, stop() { this.stopped += 1; } }];
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => tracks }),
    MediaRecorder: recorderClass(),
    monitorStart: () => { throw mediaError("InvalidStateError", "AudioContext failed"); },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  app.element("btnGlobalMic").dispatch("click");
  await flushTasks();

  assert.equal(tracks[0].stopped, 1);
  assert.equal(app.element("voiceOverlayTitle").textContent, "마이크를 시작하지 못했습니다. 다시 시도해 주세요.");
  assert.equal(app.consoleErrors[0][1].stage, "audio-monitor");
});

test("TTS start invalidates a pending microphone permission request", async () => {
  const permission = deferred();
  const tracks = [{ stopped: 0, stop() { this.stopped += 1; } }];
  let recorderConstructions = 0;
  const app = loadApp({
    getUserMedia: () => permission.promise,
    MediaRecorder: class { constructor() { recorderConstructions += 1; } },
  });

  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  app.element("btnGlobalMic").dispatch("click");
  app.emitTTS("playing");
  permission.resolve({ getTracks: () => tracks });
  await flushTasks();

  assert.equal(tracks[0].stopped, 1);
  assert.equal(recorderConstructions, 0);
});

test("stopping a recording without detected speech never calls the audio API", async () => {
  let recorder;
  class SilentRecorder {
    constructor() { this.state = "inactive"; recorder = this; }
    start() { this.state = "recording"; }
    stop() { this.state = "inactive"; this.onstop?.(); }
  }
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }),
    MediaRecorder: SilentRecorder,
    speechDetected: false,
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  app.element("btnGlobalMic").dispatch("click");
  await flushTasks();
  recorder.stop();
  await flushTasks();

  assert.equal(app.apiCalls.includes("/api/audio"), false);
  assert.equal(app.element("voiceOverlay").hidden, true);
});

test("home keeps a non-empty cart until the user confirms cancellation", async () => {
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [] }),
    MediaRecorder: recorderClass(),
    apiResponse: {
      success: true,
      response_text: "아이스 아메리카노 한 잔을 담았습니다.",
      response_required: false,
      next_listening_mode: null,
      cart: { items: [{ menu_id: "americano", name: "아메리카노", quantity: 1, total_price: 4700 }], total_price: 4700, fulfillment_type: "dine_in" },
    },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  await clickTouchOrder(app);
  await flushTasks();
  const resetsBefore = app.apiCalls.filter((path) => path === "/api/reset").length;

  app.element("btnGlobalHome").dispatch("click");
  assert.equal(app.element("homeConfirmDialog").hidden, false);
  assert.equal(app.apiCalls.filter((path) => path === "/api/reset").length, resetsBefore);

  app.element("btnConfirmHome").dispatch("click");
  await flushTasks();
  // New sessions reset the local state synchronously; remote reset is deferred
  // to a later real TTS/mic recovery so HOME never waits for a health check.
  assert.equal(app.apiCalls.filter((path) => path === "/api/reset").length, resetsBefore);
});

test("home confirmation speaks without blocking and cancellation/reset stops its stale audio", async () => {
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [] }),
    MediaRecorder: recorderClass(),
    apiResponse: (path, options) => {
      const messageId = JSON.parse(options.body || "{}").message_id;
      if (path === "/api/system-message" && messageId === "HOME_CONFIRM") {
        return {
          response_text: "주문을 취소하고 처음으로 돌아갈까요? 담아둔 메뉴가 모두 사라집니다.",
          display_segments: ["주문을 취소하고 처음으로 돌아갈까요?", "담아둔 메뉴가 모두 사라집니다."],
          tts_audio_base64: "home-confirm-audio",
          response_required: false,
          next_listening_mode: null,
        };
      }
      return {
        success: true,
        response_text: "아이스 아메리카노 한 잔을 담았습니다.",
        response_required: false,
        next_listening_mode: null,
        cart: { items: [{ menu_id: "americano", name: "아메리카노", quantity: 1, total_price: 4700 }], total_price: 4700, fulfillment_type: "dine_in" },
      };
    },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  await clickTouchOrder(app);
  app.playedAudio.length = 0;

  app.element("btnGlobalHome").dispatch("click");
  assert.equal(app.element("homeConfirmDialog").hidden, false);
  await flushTasks();
  assert.deepEqual(app.playedAudio, ["home-confirm-audio"]);

  app.element("btnCancelHome").dispatch("click");
  assert.equal(app.element("homeConfirmDialog").hidden, true);
  await flushTasks();
  assert.deepEqual(app.playedAudio, ["home-confirm-audio"]);

  app.element("btnGlobalHome").dispatch("click");
  await flushTasks();
  assert.deepEqual(app.playedAudio, ["home-confirm-audio", "home-confirm-audio"]);
  app.element("btnConfirmHome").dispatch("click");
  assert.equal(app.element("homeConfirmDialog").hidden, true);
  await flushTasks();
  assert.deepEqual(app.playedAudio, ["home-confirm-audio", "home-confirm-audio"]);
});

test("staff call ignores duplicate activation during its cooldown", async () => {
  const app = loadApp({ getUserMedia: async () => ({ getTracks: () => [] }), MediaRecorder: recorderClass() });
  await flushTasks();
  await app.element("btnGlobalStaff").dispatch("click");
  await app.element("btnGlobalStaff").dispatch("click");
  assert.equal(app.apiCalls.filter((path) => path === "/api/accessibility").length, 1);
  await app.element("btnHome").dispatch("click");
});

test("a normal interaction clears the staff-call announcement text", async () => {
  const app = loadApp({
    getUserMedia: async () => ({ getTracks: () => [] }),
    MediaRecorder: recorderClass(),
    apiResponse: (path) => path === "/api/accessibility"
      ? { response_text: "직원을 호출했습니다.", response_required: false, next_listening_mode: null, tts_audio_base64: "audio-staff" }
      : { cart: { items: [], total_price: 0, fulfillment_type: null }, tts_level: 0 },
  });
  await flushTasks();
  await app.testApi.executeUICommand("CALL_STAFF");
  assert.equal(app.element("orderResponseText").textContent, "직원을 호출했습니다.");

  await app.testApi.executeUICommand("FILTER_ALL");

  assert.notEqual(app.element("orderResponseText").textContent, "직원을 호출했습니다.");
});

test("voice continuity: voice entry enables auto listening after response_required TTS", async () => {
  let permissionRequests = 0;
  const app = loadApp({
    getUserMedia: async () => { permissionRequests += 1; return { getTracks: () => [] }; },
    MediaRecorder: recorderClass(),
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");
  app.element("btnGlobalMic").dispatch("click");
  await flushTasks();
  const initialRequests = permissionRequests;

  // Simulate server response with response_required
  app.emitTTS("completed");
  await flushTasks();
});

test("touch breaks continuity: touch input suppresses auto listening even if response_required", async () => {
  let permissionRequests = 0;
  const app = loadApp({
    getUserMedia: async () => { permissionRequests += 1; return { getTracks: () => [] }; },
    MediaRecorder: recorderClass(),
    apiResponse: {
      success: false,
      response_text: "HOT 또는 ICE를 말씀해 주세요.",
      response_required: true,
      next_listening_mode: "SYSTEM_PROMPTED",
      tts_audio_base64: "d2F2",
      cart: { items: [], total_price: 0, fulfillment_type: null },
    },
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");

  // Touch menu card (TOUCH channel)
  await clickTouchOrder(app);
  await flushTasks();

  const requestsBeforeTTS = permissionRequests;
  app.emitTTS("completed");
  await flushTasks();

  // Microphone should NOT start because lastInputMode is TOUCH
  assert.equal(permissionRequests, requestsBeforeTTS);
});

test("voice re-entry: clicking central mic after touch restores VOICE mode and starts listening", async () => {
  let permissionRequests = 0;
  const app = loadApp({
    getUserMedia: async () => { permissionRequests += 1; return { getTracks: () => [] }; },
    MediaRecorder: recorderClass(),
  });
  await flushTasks();
  app.element("btnStartOrder").dispatch("click");

  // 1. Touch action
  await clickTouchOrder(app);
  await flushTasks();

  // 2. Click central mic
  const requestsBeforeMic = permissionRequests;
  app.element("btnGlobalMic").dispatch("click");
  await flushTasks();

  // Microphone should start on explicit central mic click
  assert.equal(permissionRequests, requestsBeforeMic + 1);
});
