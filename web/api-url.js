/* Shared API URL builder for both same-origin development and static hosting. */
(() => {
  const SESSION_STORAGE_KEY = "mallo-session-id";
  const SAFE_RETRY_PATHS = new Set(["/health", "/api/state"]);
  let fallbackSessionId;

  function createSessionId() {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (token) => {
      const random = Math.floor(Math.random() * 16);
      return (token === "x" ? random : (random & 0x3) | 0x8).toString(16);
    });
  }

  function createRequestId() {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID().slice(0, 8);
    return `req-${Math.random().toString(36).slice(2, 10)}`;
  }

  function requestErrorKind(error) {
    if (error?.name === "AbortError") return "aborted";
    if (error?.name === "TimeoutError") return "timeout";
    return "network";
  }

  function sessionId() {
    try {
      const existing = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
      if (existing) return existing;
      const created = createSessionId();
      window.sessionStorage.setItem(SESSION_STORAGE_KEY, created);
      return created;
    } catch {
      fallbackSessionId ??= createSessionId();
      return fallbackSessionId;
    }
  }

  function apiUrl(path) {
    if (typeof path !== "string" || !path.startsWith("/")) {
      throw new TypeError("Mallo API path must start with '/'");
    }

    const base = String(
      window.MALLO_RUNTIME_CONFIG?.apiBaseUrl ||
      window.MALLO_API_BASE_URL ||
      ""
    ).trim().replace(/\/+$/, "");
    if (!base) return path;

    let parsed;
    try {
      parsed = new URL(base);
    } catch {
      throw new Error("MALLO_API_BASE_URL must be an absolute HTTP(S) URL");
    }
    if (!["http:", "https:"].includes(parsed.protocol)) {
      throw new Error("MALLO_API_BASE_URL must use HTTP(S)");
    }
    if (window.location.protocol === "https:" && parsed.protocol !== "https:") {
      throw new Error("HTTPS Mallo web cannot call an HTTP gateway");
    }

    return `${base}${path}`;
  }

  /* ======================================================================
     LocalTouchAdapter — In-browser deterministic engine for touch orders
     Used when backend server is offline. No fake NLU/STT/TTS.
     ====================================================================== */
  let adapterMode = "UNINITIALIZED"; // "UNINITIALIZED" | "REMOTE" | "LOCAL_TOUCH"
  let remoteResetPending = false;

  function notifyAdapterMode() {
    if (typeof window.CustomEvent !== "function" || typeof window.dispatchEvent !== "function") return;
    window.dispatchEvent(new window.CustomEvent("mallo:adapter-mode", { detail: { mode: adapterMode } }));
  }

  const localState = {
    cart: {
      items: [],
      total_price: 0,
      fulfillment_type: null,
      confirmed: false,
    },
    tts_level: 0,
    last_response: "어서오세요. 말로 카페입니다.",
    order_number: "A-37",
    payment_method: null,
  };

  function resetLocalTouchState() {
    localState.cart.items = [];
    localState.cart.total_price = 0;
    localState.cart.fulfillment_type = null;
    localState.cart.confirmed = false;
    localState.tts_level = 0;
    localState.last_response = "어서오세요. 말로 카페입니다.";
    localState.order_number = "A-37";
    localState.payment_method = null;
    handoffInFlight = false;
    localCartDirtiedDuringHandoff = false;
    remoteResetPending = true;
  }

  function getMenuMetadata(menuId) {
    const metaSource = (typeof globalThis !== "undefined" && globalThis.MalloMenuMetadata) ||
      (typeof window !== "undefined" && window.MalloMenuMetadata) ||
      null;
    return metaSource?.get?.(menuId) || { name: menuId || "", price: 4500 };
  }

  function koreanParticle(word, particleType = "을를") {
    if (!word) return "";
    const lastChar = String(word).trim().slice(-1);
    if (lastChar >= "가" && lastChar <= "힣") {
      const code = lastChar.charCodeAt(0) - 0xac00;
      const jong = code % 28;
      const hasJongseong = jong > 0;
      if (particleType === "을를") return hasJongseong ? "을" : "를";
      if (particleType === "이가") return hasJongseong ? "이" : "가";
      if (particleType === "은는") return hasJongseong ? "은" : "는";
      if (particleType === "으로") return (jong === 0 || jong === 8) ? "로" : "으로";
    }
    return particleType === "을를" ? "를" : "가";
  }

  function formatTouchItemName(meta, temperature) {
    const rawName = meta?.name || "";
    const options = Array.isArray(meta?.temperatureOptions) ? meta.temperatureOptions : [];
    const isSelectable = options.length >= 2;
    const tempLabel = isSelectable
      ? (temperature === "iced" ? "아이스 " : temperature === "hot" ? "따뜻한 " : "")
      : "";
    return `${tempLabel}${rawName}`;
  }

  function formatTouchAddResponse(meta, temperature) {
    const fullName = formatTouchItemName(meta, temperature);
    const particle = koreanParticle(fullName, "을를");
    return `${fullName}${particle} 장바구니에 담았습니다.`;
  }

  function touchQuantityLabel(quantity) {
    return ({ 1: "한", 2: "두", 3: "세", 4: "네", 5: "다섯" })[quantity] || String(quantity);
  }

  function formatTouchItemPhrase(meta, temperature, quantity) {
    const unit = meta?.category === "dessert" ? "개" : "잔";
    return `${formatTouchItemName(meta, temperature)} ${touchQuantityLabel(quantity)} ${unit}`;
  }

  function hasTouchOptions(options) {
    return Boolean(options) && Object.values(options).some((value) => value != null && value !== 0 && value !== false);
  }

  // The offline adapter has no TTS, but its displayed canonical message must
  // stay in parity with the remote semantic Level 2 realization.
  function realizeLocalAddResponse(commands, fallbackText) {
    if (commands.length < 2 || !commands.every((cmd) => cmd.intent === "ADD_ITEM") || commands.some((cmd) => hasTouchOptions(cmd.options))) {
      return fallbackText;
    }
    const phrases = commands.map((cmd) => {
      const meta = getMenuMetadata(cmd.target_item_id);
      const quantity = Math.max(1, Number(cmd.quantity) || 1);
      const temperature = cmd.temperature || (meta.temperatureOptions?.[0] || meta.temperature || null);
      return formatTouchItemPhrase(meta, temperature, quantity);
    });
    if (localState.tts_level === 2) {
      return `${phrases.map((phrase) => `${phrase}입니다.`).join(" ")} 장바구니에 담았습니다.`;
    }
    return `${phrases.slice(0, -1).join("과 ")}과 ${phrases.at(-1)}${koreanParticle(phrases.at(-1), "을를")} 장바구니에 담았습니다.`;
  }

  function canonicalItemKey(item) {
    const menuId = item.menu_id || "";
    const temp = item.temperature || "default";
    const optStr = JSON.stringify(item.options || {});
    return `${menuId}__${temp}__${optStr}`;
  }

  function canonicalizeLocalCart() {
    const merged = [];
    for (const item of localState.cart.items) {
      const key = canonicalItemKey(item);
      const existing = merged.find((m) => canonicalItemKey(m) === key);
      if (existing) {
        existing.quantity = (Number(existing.quantity) || 1) + (Number(item.quantity) || 1);
        existing.total_price = (Number(existing.unit_price) || 0) * existing.quantity;
      } else {
        const qty = Math.max(1, Number(item.quantity) || 1);
        const unitPrice = Number(item.unit_price) || 0;
        merged.push({
          ...item,
          quantity: qty,
          unit_price: unitPrice,
          total_price: unitPrice * qty,
        });
      }
    }
    localState.cart.items = merged;
    recalculateLocalCart();
  }

  function recalculateLocalCart() {
    let total = 0;
    localState.cart.items.forEach((item) => {
      item.total_price = (item.unit_price || 0) * (item.quantity || 1);
      total += item.total_price;
    });
    localState.cart.total_price = total;
  }

  const SYSTEM_MESSAGES = {
    WELCOME: "어서오세요. 말로 카페입니다.",
    SERVICE_MODE: "어떻게 이용하시겠어요? 매장 이용 또는 포장을 선택해 주세요.",
    ORDER: "원하시는 메뉴를 말씀해 주세요.",
    ORDER_REVIEW: "주문 내용을 확인해 주세요.",
    PAYMENT: "결제 방법을 선택해 주세요.",
    COMPLETE: "주문이 완료되었습니다.",
    STAFF: "직원을 호출했습니다. 잠시만 기다려 주세요.",
    RECEIPT: "영수증을 출력하고 있습니다.",
    PAYMENT_EMPTY_CART: "장바구니가 비어 있습니다. 메뉴를 먼저 선택해 주세요.",
    PAYMENT_FULFILLMENT_REQUIRED: "매장 이용 또는 포장을 먼저 선택해 주세요.",
    PAYMENT_CONFIRMATION_REQUIRED: "주문을 먼저 확정해 주세요.",
    HOME_CONFIRM: "주문을 취소하고 처음으로 돌아갈까요? 담아둔 메뉴가 모두 사라집니다.",
  };

  const PREDEFINED_SEGMENTS = {
    SERVICE_MODE: [
      "어떻게 이용하시겠어요?",
      "매장 이용 또는 포장을 선택해 주세요.",
    ],
    HOME_CONFIRM: [
      "주문을 취소하고 처음으로 돌아갈까요?",
      "담아둔 메뉴가 모두 사라집니다.",
    ],
    PAYMENT: [
      "결제 방법을 선택해 주세요.",
    ],
  };

  function localDisplaySegments(text, messageId = null) {
    const predefined = PREDEFINED_SEGMENTS[messageId] || PREDEFINED_SEGMENTS[text];
    if (predefined) return [...predefined];
    if (localState.tts_level === 2) {
      const sentences = String(text).split(/(?<=[.?!])\s+/).filter(Boolean);
      if (sentences.length > 1) return sentences;
    }
    return [text];
  }

  function localTTSContract(text, messageId = null) {
    const displaySegments = localDisplaySegments(text, messageId);
    return {
      display_segments: displaySegments,
      // Offline mode does not synthesize audio, but keeps the remote payload
      // shape so Response Bar rendering cannot drift by adapter mode.
      tts_segments: displaySegments.map((segment, index) => ({
        chunk_id: `${messageId || "local"}:${index}`,
        chunk_index: index,
        segment_index: index,
        text: segment,
        display_text: segment,
        tts_text: segment,
        synthesis_text: segment,
        tts_audio_base64: null,
        gap_ms: 0,
      })),
    };
  }

  function handleLocalTouchRequest(path, options = {}) {
    let body = {};
    if (typeof options.body === "string" && options.body) {
      try { body = JSON.parse(options.body); } catch {}
    }

    if (path === "/health") {
      return { status: "ready", is_demo: true, is_local_touch: true, backend: "offline" };
    }

    if (path === "/api/state") {
      return {
        cart: localState.cart,
        tts_level: localState.tts_level,
        last_response: localState.last_response,
        order_number: localState.order_number,
      };
    }

    if (path === "/api/fulfillment") {
      const fulfillmentType = body.fulfillment_type || "dine_in";
      localState.cart.fulfillment_type = fulfillmentType;
      const text = "원하시는 메뉴를 말씀해 주세요.";
      localState.last_response = text;
      return {
        success: true,
        fulfillment_type: fulfillmentType,
        cart: localState.cart,
        response_text: text,
        response_required: false,
        next_listening_mode: null,
        tts_level: localState.tts_level,
        tts_audio_base64: null,
        ...localTTSContract(text),
      };
    }

    if (path === "/api/commands") {
      const commands = Array.isArray(body.commands) ? body.commands : [];
      let responseText = "처리했습니다.";
      for (const cmd of commands) {
        if (cmd.intent === "SET_FULFILLMENT") {
          const fulfillmentType = cmd.fulfillment_type || "dine_in";
          localState.cart.fulfillment_type = fulfillmentType;
          responseText = fulfillmentType === "dine_in"
            ? "매장 이용으로 설정했습니다."
            : "포장으로 설정했습니다.";
        } else if (cmd.intent === "ADD_ITEM") {
          const menuId = cmd.target_item_id;
          const meta = getMenuMetadata(menuId);
          const quantity = Math.max(1, Number(cmd.quantity) || 1);
          const temperature = cmd.temperature || (meta.temperatureOptions?.[0] || meta.temperature || null);
          const candidate = {
            menu_id: menuId,
            name: meta.name || menuId,
            quantity,
            temperature,
            unit_price: meta.price || 4500,
            total_price: (meta.price || 4500) * quantity,
            options: cmd.options || {},
          };
          const targetKey = canonicalItemKey(candidate);
          const existing = localState.cart.items.find((i) => canonicalItemKey(i) === targetKey);
          if (existing) {
            existing.quantity += quantity;
          } else {
            localState.cart.items.push(candidate);
          }
          canonicalizeLocalCart();
          responseText = formatTouchAddResponse(meta, temperature);
        } else if (cmd.intent === "UPDATE_QUANTITY") {
          const menuId = cmd.target_item_id;
          const meta = getMenuMetadata(menuId);
          const target = localState.cart.items.find(
            (i) => i.menu_id === menuId && (cmd.temperature == null || (i.temperature || null) === (cmd.temperature || null)),
          );
          if (target) {
            target.quantity = Math.max(1, Number(cmd.quantity) || 1);
            canonicalizeLocalCart();
            const fullName = formatTouchItemName(meta, target.temperature);
            const p = koreanParticle(fullName, "을를");
            const unitLabel = `${target.quantity}개`;
            const dirP = koreanParticle(unitLabel, "으로");
            responseText = `${fullName}${p} ${unitLabel}${dirP} 변경했습니다.`;
          }
        } else if (cmd.intent === "UPDATE_OPTION") {
          const menuId = cmd.target_item_id;
          const meta = getMenuMetadata(menuId);
          const rawName = meta?.name || menuId;
          const target = localState.cart.items.find(
            (i) => i.menu_id === menuId && (i.temperature || null) !== (cmd.temperature || null),
          ) || localState.cart.items.find((i) => i.menu_id === menuId);
          if (target) {
            if (cmd.temperature) {
              target.temperature = cmd.temperature;
            }
            if (cmd.quantity) target.quantity = Math.max(1, Number(cmd.quantity) || 1);
            canonicalizeLocalCart();
            const p = koreanParticle(rawName, "을를");
            const tempLabel = target.temperature === "iced" ? "아이스 음료" : "따뜻한 음료";
            responseText = `${rawName}${p} ${tempLabel}로 변경했습니다.`;
          }
        } else if (cmd.intent === "REMOVE_ITEM") {
          const menuId = cmd.target_item_id;
          const meta = getMenuMetadata(menuId);
          const targetIndex = localState.cart.items.findIndex(
            (i) => i.menu_id === menuId && (cmd.temperature == null || (i.temperature || null) === (cmd.temperature || null)),
          );
          let removedItem = null;
          if (targetIndex >= 0) {
            removedItem = localState.cart.items.splice(targetIndex, 1)[0];
          } else {
            removedItem = localState.cart.items.find((i) => i.menu_id === menuId);
            localState.cart.items = localState.cart.items.filter((i) => i.menu_id !== menuId);
          }
          canonicalizeLocalCart();
          const fullName = removedItem ? formatTouchItemName(meta, removedItem.temperature) : (meta?.name || menuId);
          const p = koreanParticle(fullName, "을를");
          responseText = `${fullName}${p} 장바구니에서 삭제했습니다.`;
        } else if (cmd.intent === "CONFIRM_ORDER") {
          localState.cart.confirmed = true;
          responseText = "주문 내용을 확인해 주세요.";
        } else if (cmd.intent === "RESET_ORDER") {
          localState.cart.items = [];
          localState.cart.total_price = 0;
          localState.cart.fulfillment_type = null;
          localState.cart.confirmed = false;
          responseText = "주문을 초기화했습니다.";
        }
      }
      responseText = realizeLocalAddResponse(commands, responseText);
      localState.last_response = responseText;
      return {
        success: true,
        cart: localState.cart,
        response_text: responseText,
        response_required: false,
        next_listening_mode: null,
        tts_audio_base64: null,
        order_commands: commands,
        tts_level: localState.tts_level,
        ...localTTSContract(responseText),
      };
    }

    if (path === "/api/system-message") {
      const messageId = body.message_id || "";
      const text = SYSTEM_MESSAGES[messageId] || "원하시는 메뉴를 말씀해 주세요.";
      localState.last_response = text;
      const segments = PREDEFINED_SEGMENTS[messageId] || [text];
      return {
        success: true,
        response_text: text,
        message_id: messageId,
        tts_level: localState.tts_level,
        tts_audio_base64: null,
        ...localTTSContract(text, messageId),
      };
    }

    if (path === "/api/accessibility") {
      const action = body.action || "REPEAT";
      if (action === "CALL_STAFF") {
        const text = "직원을 호출했습니다. 잠시만 기다려 주세요.";
        return {
          success: true,
          action,
          tts_level: localState.tts_level,
          response_text: text,
          tts_audio_base64: null,
          ...localTTSContract(text),
        };
      }
      if (action === "RECEIPT") {
        const text = "영수증을 출력하고 있습니다.";
        return {
          success: true,
          action,
          tts_level: localState.tts_level,
          response_text: text,
          tts_audio_base64: null,
          ...localTTSContract(text),
        };
      }
      if (action === "CYCLE_SPEED") {
        localState.tts_level = (localState.tts_level + 1) % 3;
        const text = "이 속도로 안내합니다.";
        return {
          success: true,
          action,
          tts_level: localState.tts_level,
          response_text: text,
          tts_audio_base64: null,
          ...localTTSContract(text),
        };
      }
      if (typeof body.level === "number") localState.tts_level = body.level;
      const text = localState.last_response || "다시 말씀해 주세요.";
      return {
        success: true,
        action,
        tts_level: localState.tts_level,
        response_text: text,
        tts_audio_base64: null,
        ...localTTSContract(text),
      };
    }

    if (path === "/api/order") {
      return {
        success: false,
        cart: localState.cart,
        response_text: "지금은 음성 주문을 사용할 수 없습니다. 화면을 눌러 주문해 주세요.",
        tts_level: localState.tts_level,
        tts_audio_base64: null,
      };
    }

    if (path === "/api/tts" || path === "/api/synthesize") {
      const text = body && body.text ? body.text : "";
      const tts_level = typeof body?.tts_level === "number" ? body.tts_level : localState.tts_level;
      return {
        success: true,
        text,
        tts_level,
        tts_audio_base64: null,
      };
    }

    if (path === "/api/reset") {
      resetLocalTouchState();
      remoteResetPending = true;
      return { success: true, cart: localState.cart };
    }

    return { error: "not found" };
  }

  function createMockResponse(data, status = 200) {
    const jsonStr = JSON.stringify(data);
    return new Response(jsonStr, {
      status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  }

  let handoffInFlight = false;
  let localCartDirtiedDuringHandoff = false;

  function markLocalCartDirty() {
    if (handoffInFlight) {
      localCartDirtiedDuringHandoff = true;
    }
  }

  async function checkServerHealth() {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 1200);
      const url = apiUrl("/health");
      const resp = await window.fetch(url, { signal: controller.signal });
      clearTimeout(timeoutId);
      if (resp.ok) {
        adapterMode = "REMOTE";
        notifyAdapterMode();
        return true;
      }
    } catch {
      // offline
    }
    adapterMode = "LOCAL_TOUCH";
    notifyAdapterMode();
    return false;
  }

  async function initSessionAdapter(forceRecheck = false) {
    if (adapterMode === "UNINITIALIZED" || forceRecheck) {
      await checkServerHealth();
    }
    return adapterMode;
  }

  async function attemptHandoffToServer(currentScreen = "") {
    if (adapterMode !== "LOCAL_TOUCH") return false;
    const ALLOWED_SCREENS = new Set(["WELCOME", "SERVICE_MODE", "ORDER", "ORDER_REVIEW", "OPTION_CHANGE", "PAYMENT", "COMPLETE"]);
    if (currentScreen && !ALLOWED_SCREENS.has(currentScreen)) {
      return false;
    }
    if (handoffInFlight) return false;

    handoffInFlight = true;
    localCartDirtiedDuringHandoff = false;

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 1200);
      const healthResp = await window.fetch(apiUrl("/health"), { signal: controller.signal });
      clearTimeout(timeoutId);
      if (!healthResp.ok) {
        return false;
      }

      const headers = new Headers({ "Content-Type": "application/json; charset=utf-8" });
      headers.set("X-Mallo-Request-ID", createRequestId());
      headers.set("X-Mallo-Session-ID", sessionId());

      // If remoteResetPending is true, MUST reset remote server session before handoff!
      if (remoteResetPending) {
        try {
          const resetCtrl = new AbortController();
          const resetTimeoutId = setTimeout(() => resetCtrl.abort(), 1200);
          const resetResp = await window.fetch(apiUrl("/api/reset"), {
            method: "POST",
            headers,
            body: JSON.stringify({}),
            signal: resetCtrl.signal,
          });
          clearTimeout(resetTimeoutId);
          if (!resetResp.ok) {
            console.warn("[Mallo Handoff] Remote reset failed before handoff; keeping LOCAL_TOUCH.");
            return false;
          }
          remoteResetPending = false;
        } catch (resetErr) {
          console.warn("[Mallo Handoff] Remote reset error before handoff:", resetErr);
          return false;
        }
      }

      const payload = {
        fulfillment_type: localState.cart.fulfillment_type || null,
        confirmed: Boolean(localState.cart.confirmed),
        items: (localState.cart.items || []).map((item) => ({
          menu_id: item.menu_id,
          quantity: Number(item.quantity) || 1,
          temperature: item.temperature || null,
          options: item.options || {},
        })),
      };

      const handoffCtrl = new AbortController();
      const handoffTimeoutId = setTimeout(() => handoffCtrl.abort(), 1500);
      const handoffResp = await window.fetch(apiUrl("/api/session/handoff"), {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
        signal: handoffCtrl.signal,
      });
      clearTimeout(handoffTimeoutId);

      if (!handoffResp.ok) {
        return false;
      }

      const result = await handoffResp.json();
      if (!result || !result.success || !result.cart) {
        return false;
      }

      if (localCartDirtiedDuringHandoff) {
        console.debug("[Mallo Handoff] Local cart dirtied during in-flight handoff; keeping LOCAL_TOUCH.");
        return false;
      }

      adapterMode = "REMOTE";
      notifyAdapterMode();
      console.info("[Mallo Handoff] Promoted to REMOTE mode after successful reset & handoff.", result.cart);
      return result.cart;
    } catch (err) {
      console.debug("[Mallo Handoff] Handoff attempt failed:", err);
      return false;
    } finally {
      handoffInFlight = false;
      localCartDirtiedDuringHandoff = false;
    }
  }

  async function apiFetch(path, options = {}) {
    if (path === "/api/reset") {
      resetLocalTouchState();
      remoteResetPending = true;
      if (adapterMode === "LOCAL_TOUCH") {
        console.debug("[Mallo API] LocalTouchAdapter serving reset", { path });
        return createMockResponse(handleLocalTouchRequest(path, options));
      }
    }

    if (adapterMode === "LOCAL_TOUCH") {
      console.debug("[Mallo API] LocalTouchAdapter serving", { path });
      return createMockResponse(handleLocalTouchRequest(path, options));
    }

    const requestId = createRequestId();
    const method = String(options.method || "GET").toUpperCase();
    const attempts = method === "GET" && SAFE_RETRY_PATHS.has(path) && !options.signal ? 2 : 1;
    const url = apiUrl(path);
    for (let attempt = 1; attempt <= attempts; attempt += 1) {
      const headers = new Headers(options.headers || {});
      headers.set("X-Mallo-Request-ID", requestId);
      if (path.startsWith("/api/")) {
        headers.set("X-Mallo-Session-ID", sessionId());
      }
      const startedAt = window.performance?.now?.() ?? Date.now();
      console.debug("[Mallo API] request start", { requestId, path, method, attempt });
      try {
        const response = await window.fetch(url, { ...options, headers });
        const elapsedMs = Math.round((window.performance?.now?.() ?? Date.now()) - startedAt);
        console.debug("[Mallo API] request end", { requestId, path, attempt, status: response.status, elapsedMs });
        if (response.ok || attempt === attempts || (response.status < 500 && response.status !== 404)) {
          if (path === "/api/reset" && response.ok) {
            remoteResetPending = false;
          }
          adapterMode = "REMOTE";
          notifyAdapterMode();
          return response;
        }
        console.debug("[Mallo API] safe request retry", { requestId, path, status: response.status });
      } catch (error) {
        const elapsedMs = Math.round((window.performance?.now?.() ?? Date.now()) - startedAt);
        const kind = requestErrorKind(error);
        console.debug("[Mallo API] request failed", { requestId, path, attempt, kind, elapsedMs });
        if (kind === "aborted") throw error;
        if (attempt === attempts) {
          console.warn("[Mallo API] Server offline. Using LocalTouchAdapter for current session.", { path });
          adapterMode = "LOCAL_TOUCH";
          notifyAdapterMode();
          if (path === "/api/reset") {
            remoteResetPending = true;
          }
          return createMockResponse(handleLocalTouchRequest(path, options));
        }
      }
    }
    adapterMode = "LOCAL_TOUCH";
    notifyAdapterMode();
    if (path === "/api/reset") {
      remoteResetPending = true;
    }
    return createMockResponse(handleLocalTouchRequest(path, options));
  }

  function setLocalTouchMode(enabled) {
    adapterMode = enabled ? "LOCAL_TOUCH" : "REMOTE";
    notifyAdapterMode();
  }

  function beginNewLocalSession() {
    resetLocalTouchState();
    adapterMode = "LOCAL_TOUCH";
    notifyAdapterMode();
  }

  function getLocalTouchState() {
    return localState;
  }

  function syncLocalCartFromRemote(cart) {
    if (!cart) return;
    localState.cart.fulfillment_type = cart.fulfillment_type || null;
    localState.cart.confirmed = Boolean(cart.confirmed);
    localState.cart.items = Array.isArray(cart.items) ? JSON.parse(JSON.stringify(cart.items)) : [];
    recalculateLocalCart();
  }

  window.MalloApi = {
    apiUrl,
    apiFetch,
    sessionId,
    createRequestId,
    get isDemoMode() { return adapterMode === "LOCAL_TOUCH"; },
    get isLocalTouchMode() { return adapterMode === "LOCAL_TOUCH"; },
    get adapterMode() { return adapterMode; },
    get isHandoffInFlight() { return handoffInFlight; },
    get remoteResetPending() { return remoteResetPending; },
    setRemoteResetPending: (val) => { remoteResetPending = Boolean(val); },
    setDemoMode: setLocalTouchMode,
    setLocalTouchMode,
    beginNewLocalSession,
    getDemoState: getLocalTouchState,
    getLocalTouchState,
    handleDemoRequest: handleLocalTouchRequest,
    handleLocalTouchRequest,
    resetLocalTouchState,
    initSessionAdapter,
    attemptHandoffToServer,
    markLocalCartDirty,
    syncLocalCartFromRemote,
  };
})();
