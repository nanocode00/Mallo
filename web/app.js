/**
 * 말로(Mallo) — Voice-first Kiosk GUI
 * 8-screen state machine with backend API integration.
 *
 * State is separated per spec:
 *   uiState     — current screen, transitions
 *   orderState  — cart, order number, payment, status
 *   sttState    — microphone / recognition status
 *   ttsState    — speech playback status & rate
 */

document.addEventListener("DOMContentLoaded", () => {
  /* ======================================================================
     State — Separated per spec §24-28
     ====================================================================== */

  // UIState — screen navigation only
  const uiState = {
    screen: "WELCOME", // WELCOME | SERVICE_MODE | ORDER | ORDER_REVIEW | OPTION_CHANGE | PAYMENT | COMPLETE
  };

  const voiceState = {
    status: "IDLE", // IDLE | LISTENING | PROCESSING | ERROR
    message: "",
  };
  const VOICE_ENABLED_SCREENS = new Set(["SERVICE_MODE", "ORDER", "ORDER_REVIEW", "OPTION_CHANGE", "PAYMENT"]);
  let pendingSystemPromptListening = null;
  let interactionMode = "VOICE"; // VOICE | TOUCH
  let lastInputMode = "TOUCH"; // VOICE | TOUCH
  let staffCallCooldownTimer = null;
  let staffCallAnnouncementActive = false;
  let activeTouchMenuCategory = "all";
  let touchMenuSelection = null;
  let repeatRequestController = null;
  let nextRecordingId = 0;
  let activeRecordingId = null;
  let transcriptRecordingId = null;
  let interactionGeneration = 0;
  // A cart response belongs to an order session, whereas a response bar/TTS
  // belongs to one interaction in that session. Do not use the latter to
  // discard an authoritative cart snapshot after a navigation.
  let orderSessionGeneration = 0;
  let nextCartMutationSequence = 0;
  let lastAppliedCartMutationSequence = 0;
  let activeTTSStreamId = 0;
  // A message stream spans its audio clips *and* their adaptive silence gaps.
  // It deliberately does not mirror TTSPlaybackController's per-clip status.
  let activeTTSMessageStreamId = null;
  let activeTTSMessageStarted = false;
  let lastReplayableMessage = null;
  let sessionResetRequest = Promise.resolve();

  function beginUserInteraction({ preservePendingCartMutation = false } = {}) {
    if (!preservePendingCartMutation) interactionGeneration += 1;
    activeTTSStreamId += 1;
    activeTTSMessageStreamId = null;
    activeTTSMessageStarted = false;
    pendingSystemPromptListening = null;
    ttsPlayer.stop();
    if (staffCallAnnouncementActive) {
      staffCallAnnouncementActive = false;
      orderState.lastResponse = "";
      renderResponseBars("", { remember: false });
    }
    return interactionGeneration;
  }

  function isCurrentInteraction(generation) {
    return generation === interactionGeneration;
  }

  function logAudioTimeline(event, details = {}) {
    const clock = globalThis.performance && typeof globalThis.performance.now === "function"
      ? globalThis.performance.now() : Date.now();
    console.debug("[Mallo audio timeline]", { event, atMs: Math.round(clock), ...details });
  }

  function audioTrackStates(stream) {
    const tracks = typeof stream.getAudioTracks === "function"
      ? stream.getAudioTracks() : stream.getTracks();
    return tracks.map((track) => ({ readyState: track.readyState, enabled: track.enabled, muted: track.muted }));
  }

  // OrderState — cart, order data, payment
  const orderState = {
    items: [],
    totalPrice: 0,
    fulfillmentType: null,
    confirmed: false,
    orderNumber: generateOrderNumber(),
    waitingTime: null,
    paymentMethod: null,
    status: "empty", // empty | building | confirmed | payment_pending | paid | completed | cancelled
    lastResponse: "어서오세요. 말로 카페입니다.",
  };

  // STTState
  const sttState = {
    status: "idle", // idle | requesting_permission | listening | processing | success | error | cancelled
    transcript: "",
    confidence: null,
    error: null,
    isListening: false,
    listeningMode: null,
  };

  // TTSState
  const ttsState = {
    status: "idle", // idle | loading | playing | paused | completed | error
    rate: 1.0,
    currentText: "",
    ttsLevel: 0,
    hasAudio: false,
    available: true,
    error: null,
  };

  let currentTTSCategory = "CONVERSATION"; // "CONVERSATION" | "CONTROL_FEEDBACK"

  function renderTTSPlaybackStatus() {
    const isPlaying = activeTTSMessageStarted
      && activeTTSMessageStreamId === activeTTSStreamId
      && currentTTSCategory === "CONVERSATION";
    document.querySelectorAll(".response-bar").forEach((element) => {
      element.classList.toggle("is-tts-playing", isPlaying);
      element.setAttribute("aria-busy", String(isPlaying));
    });
  }

  function renderAccessibilityControls() {
    const level = ttsState.ttsLevel;
    const repeatButton = document.getElementById("btnGlobalRepeat");
    const speedButton = document.getElementById("btnGlobalSpeed");
    const localOnly = globalThis.MalloApi?.isLocalTouchMode || globalThis.MalloApi?.adapterMode === "LOCAL_TOUCH";
    const remoteTTSAvailable = !localOnly && ttsState.available;
    const hasReplaySource = Boolean(lastReplayableMessage?.response_text);
    repeatButton.disabled = !remoteTTSAvailable || !hasReplaySource;
    speedButton.disabled = !remoteTTSAvailable;
    repeatButton.setAttribute("aria-disabled", String(repeatButton.disabled));
    speedButton.setAttribute("aria-disabled", String(speedButton.disabled));
    const labels = ["기본", "천천히", "더 천천히"];
    document.getElementById("ttsSpeedStatus").textContent = labels[level] || labels[0];
    const headerFulfillment = document.getElementById("kioskStatus");
    const label = fulfillmentText(orderState.fulfillmentType);
    headerFulfillment.hidden = !label;
    headerFulfillment.textContent = label;
  }

  const ttsPlayer = new TTSPlaybackController({
    onStatus(status, error) {
      logAudioTimeline("tts-status", { status, error: error ? error.message : null });
      if (status === "playing") console.info("[TTS] playing");
      ttsState.status = status;
      ttsState.error = error ? error.message : null;
      if (status === "playing" && activeTTSMessageStreamId === activeTTSStreamId) {
        activeTTSMessageStarted = true;
      }
      if (["idle", "error", "autoplay-blocked"].includes(status)) {
        activeTTSMessageStreamId = null;
        activeTTSMessageStarted = false;
      }
      renderTTSPlaybackStatus();
      if (status === "playing") silenceMicrophoneForTTS();
      if (status === "completed") {
        // An adaptive message may have another clip after its silence gap.
        // Its stream owner performs final completion below.
        if (activeTTSMessageStreamId === activeTTSStreamId) return;
        const pending = pendingSystemPromptListening;
        pendingSystemPromptListening = null;
        currentTTSCategory = "CONVERSATION";
        renderTTSPlaybackStatus();
        setVoiceState("IDLE");
        if (
          pending &&
          lastInputMode === "VOICE" &&
          pending.screen === uiState.screen &&
          isVoiceAllowed()
        ) {
          startListening(pending.inputContext, "SYSTEM_PROMPTED");
        }
      }
      if (status === "error") {
        pendingSystemPromptListening = null;
        currentTTSCategory = "CONVERSATION";
        renderTTSPlaybackStatus();
        console.warn("TTS playback failed", error || "unknown error");
        setVoiceState("IDLE");
      }
      if (status === "autoplay-blocked") {
        pendingSystemPromptListening = null;
        currentTTSCategory = "CONVERSATION";
        renderTTSPlaybackStatus();
        console.debug("[TTS] autoplay blocked by browser policy", { name: error?.name });
        setVoiceState("IDLE");
      }
    },
  });

  function completeTTSMessageStream(streamId) {
    if (activeTTSMessageStreamId !== streamId) return;
    activeTTSMessageStreamId = null;
    activeTTSMessageStarted = false;
    renderTTSPlaybackStatus();
    const pending = pendingSystemPromptListening;
    pendingSystemPromptListening = null;
    currentTTSCategory = "CONVERSATION";
    setVoiceState("IDLE");
    if (
      pending &&
      lastInputMode === "VOICE" &&
      pending.screen === uiState.screen &&
      isVoiceAllowed()
    ) {
      startListening(pending.inputContext, "SYSTEM_PROMPTED");
    }
  }
  const optionChangeFlow = new OptionChangeFlow();
  const serviceModeFlow = new ServiceModeFlow();

  function generateOrderNumber() {
    const letters = "ABCDEFGHJKLMNPQRSTUVWXYZ";
    const letter = letters[Math.floor(Math.random() * letters.length)];
    const num = Math.floor(Math.random() * 90) + 10;
    return `${letter}-${num}`;
  }

  /* ======================================================================
     Screen references
     ====================================================================== */
  const screens = {
    WELCOME: document.getElementById("screenWelcome"),
    SERVICE_MODE: document.getElementById("screenServiceMode"),
    ORDER: document.getElementById("screenOrder"),
    ORDER_REVIEW: document.getElementById("screenOrderReview"),
    OPTION_CHANGE: document.getElementById("screenOptionChange"),
    PAYMENT: document.getElementById("screenPayment"),
    COMPLETE: document.getElementById("screenComplete"),
  };

  /* ======================================================================
     Screen transition
     ====================================================================== */
  let completeAutoHomeTimer = null;
  // One WELCOME transition owns exactly one system-message/TTS attempt.
  let welcomeEntryActive = false;
  let welcomeEntryInFlight = null;

  function clearCompleteAutoHomeTimer() {
    if (completeAutoHomeTimer) {
      clearTimeout(completeAutoHomeTimer);
      completeAutoHomeTimer = null;
    }
  }

  function startCompleteAutoHomeTimer() {
    clearCompleteAutoHomeTimer();
    completeAutoHomeTimer = setTimeout(async () => {
      completeAutoHomeTimer = null;
      if (uiState.screen === "COMPLETE") {
        await returnHome();
      }
    }, 10000);
  }

  function goToScreen(name) {
    if (name !== "ORDER" && touchMenuSelection !== null) {
      hideTouchMenuSelection();
    }
    if (name !== "WELCOME") welcomeEntryActive = false;
    if (name !== "COMPLETE") {
      clearCompleteAutoHomeTimer();
    }
    hideResponseBarText();
    Object.values(screens).forEach((el) => el.classList.remove("active"));
    if (screens[name]) {
      screens[name].classList.add("active");
    }
    uiState.screen = name;
    if (!isVoiceAllowed(name)) deactivateVoiceInput();
    const labels = {
      WELCOME: "어서오세요",
      SERVICE_MODE: "이용 방법 선택",
      ORDER: "메뉴 주문",
      ORDER_REVIEW: "주문 확인",
      OPTION_CHANGE: "주문 수정",
      PAYMENT: "결제",
      COMPLETE: "주문 완료",
    };
    document.getElementById("kioskStatus").textContent = labels[name] || "말로 카페";
    const controls = document.getElementById("globalA11yControls");
    controls.hidden = ["WELCOME", "COMPLETE"].includes(name);
    if (name === "WELCOME") {
      const welcomeEl = document.getElementById("welcomeResponseText");
      if (welcomeEl) welcomeEl.textContent = "어서오세요. 말로 카페입니다.";
    }
    renderAccessibilityControls();
    if (name === "COMPLETE") {
      startCompleteAutoHomeTimer();
    }
  }

  function hideResponseBarText() {
    document.querySelectorAll(".response-bar-text").forEach((element) => {
      element.classList.add("is-transition-hidden");
    });
  }

  function isVoiceAllowed(screen = uiState.screen) {
    return VOICE_ENABLED_SCREENS.has(screen);
  }

  function enterTouchMode({ preservePendingCartMutation = false } = {}) {
    beginUserInteraction({ preservePendingCartMutation });
    lastInputMode = "TOUCH";
    interactionMode = "TOUCH";
    deactivateVoiceInput();
  }

  function enterVoiceMode() {
    lastInputMode = "VOICE";
    interactionMode = "VOICE";
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function setVoiceState(status, message = "") {
    if (status !== "IDLE" && !isVoiceAllowed()) status = "IDLE";
    voiceState.status = status;
    voiceState.message = message;
    const overlay = document.getElementById("voiceOverlay");
    const title = document.getElementById("voiceOverlayTitle");
    const waveform = document.getElementById("waveform");
    const mic = document.getElementById("btnMicActive");
    const dismiss = document.getElementById("btnVoiceDismiss");
    const transcript = document.getElementById("liveTranscript");
    const globalMic = document.getElementById("btnGlobalMic");

    if (globalMic) {
      globalMic.classList.toggle("is-listening", status === "LISTENING");
      globalMic.classList.toggle("is-processing", status === "PROCESSING");
    }

    const finalTranscript = (sttState.transcript || "").trim();
    overlay.hidden = !["LISTENING", "PROCESSING", "ERROR"].includes(status);

    if (status === "LISTENING") {
      title.textContent = "듣고 있어요";
      waveform.hidden = false;
      transcript.hidden = true;
      mic.hidden = false;
      mic.disabled = false;
      mic.classList.remove("is-disabled");
      const micSpan = mic?.querySelector?.("span");
      if (micSpan) micSpan.textContent = "말하기 끝내기";
      dismiss.hidden = false;
      dismiss.disabled = false;
      dismiss.classList.remove("is-disabled");
      dismiss.textContent = "화면으로 조작하기";
    } else if (status === "PROCESSING") {
      waveform.hidden = true;
      transcript.hidden = false;
      mic.hidden = false;
      mic.disabled = true;
      mic.classList.add("is-disabled");
      const micSpan = mic?.querySelector?.("span");
      if (micSpan) micSpan.textContent = "처리 중...";
      dismiss.hidden = false;
      dismiss.disabled = true;
      dismiss.classList.add("is-disabled");
      dismiss.textContent = "화면으로 조작하기";

      if (finalTranscript) {
        title.textContent = "말씀하신 내용을 확인하고 있어요";
        transcript.innerHTML = `<span class="voice-transcript-text">${escapeHtml(finalTranscript)}</span>`;
      } else {
        title.textContent = "잠시만 기다려주세요";
        transcript.innerHTML = '<div class="voice-processing-indicator" role="progressbar" aria-label="음성 처리 중"><div class="processing-progress-bar"><div class="processing-progress-fill"></div></div><span class="processing-status-text">음성을 처리하고 있어요...</span></div>';
      }
    } else if (status === "ERROR") {
      title.textContent = message || "잘 듣지 못했어요";
      waveform.hidden = true;
      transcript.hidden = false;
      mic.hidden = false;
      mic.disabled = false;
      mic.classList.remove("is-disabled");
      const micSpan = mic?.querySelector?.("span");
      if (micSpan) micSpan.textContent = "다시 말하기";
      dismiss.hidden = false;
      dismiss.disabled = false;
      dismiss.classList.remove("is-disabled");
      dismiss.textContent = "화면으로 조작하기";
      transcript.innerHTML = '<span class="transcript-error-text">다시 한 번 말씀해 주세요</span>';
    }
  }

  /* ======================================================================
     API helpers
     ====================================================================== */
  function apiFetch(path, options) {
    return globalThis.MalloApi?.apiFetch
      ? globalThis.MalloApi.apiFetch(path, options)
      : fetch(path, options);
  }

  async function callApi(path, { json, raw, method, signal } = {}) {
    const opts = { method: method || "POST", headers: {}, signal };
    if (raw !== undefined) {
      opts.body = raw;
    } else {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(json || {});
    }
    const resp = await apiFetch(path, opts);
    return resp.json();
  }

  function orderPayload() {
    return {
      session_id: orderState.sessionId,
      items: orderState.items,
      total_price: orderState.totalPrice,
      fulfillment_type: orderState.fulfillmentType,
    };
  }

  function getCart() {
    return {
      items: orderState.items,
      total_price: orderState.totalPrice,
      fulfillment_type: orderState.fulfillmentType,
    };
  }

  let responseBarCycleInterval = null;

  function measureTextLines(text, referenceElement) {
    if (typeof document === "undefined" || !document.createElement || !document.body?.appendChild) {
      return text.length > 25 ? 2 : 1;
    }
    let measurer = document.getElementById("responseBarMeasurer");
    if (!measurer) {
      measurer = document.createElement("div");
      measurer.id = "responseBarMeasurer";
      measurer.style.cssText = "position:absolute;left:-9999px;top:-9999px;visibility:hidden;pointer-events:none;white-space:normal;word-break:keep-all;overflow-wrap:break-word;box-sizing:border-box;margin:0;padding:0;";
      document.body.appendChild(measurer);
    }

    const activeScreen = document.querySelector(".screen.active") || document.getElementById("screenOrder") || document.body;
    const ref = referenceElement || activeScreen.querySelector(".response-bar-text") || document.querySelector(".response-bar-text");
    const parentBar = ref?.closest ? ref.closest(".response-bar") : document.querySelector(".response-bar");

    let barWidth = 320;
    if (parentBar && parentBar.clientWidth > 0) {
      const parentComputed = window.getComputedStyle ? window.getComputedStyle(parentBar) : null;
      const paddingX = parentComputed
        ? (parseFloat(parentComputed.paddingLeft) || 0) + (parseFloat(parentComputed.paddingRight) || 0)
        : 28;
      barWidth = Math.max(120, parentBar.clientWidth - paddingX);
    } else {
      const kiosk = document.getElementById("kioskContainer") || document.querySelector(".kiosk-container");
      const kioskWidth = kiosk && kiosk.clientWidth > 0 ? kiosk.clientWidth : 390;
      barWidth = Math.max(120, kioskWidth * 0.9 - 28);
    }

    measurer.style.width = `${barWidth}px`;

    const computed = ref && window.getComputedStyle ? window.getComputedStyle(ref) : null;
    if (computed) {
      measurer.style.fontFamily = computed.fontFamily || "sans-serif";
      measurer.style.fontSize = computed.fontSize || "14px";
      measurer.style.fontWeight = computed.fontWeight || "700";
      measurer.style.letterSpacing = computed.letterSpacing || "normal";
      measurer.style.lineHeight = computed.lineHeight || "1.35";
    } else {
      measurer.style.fontSize = "14px";
      measurer.style.lineHeight = "1.35";
      measurer.style.fontWeight = "700";
    }

    measurer.textContent = text;
    const computedMeasurer = window.getComputedStyle ? window.getComputedStyle(measurer) : null;
    const fontSize = parseFloat(computedMeasurer?.fontSize) || 14;
    const lineHeightVal = parseFloat(computedMeasurer?.lineHeight);
    const singleLineHeight = (!isNaN(lineHeightVal) && lineHeightVal > 0) ? lineHeightVal : (fontSize * 1.35);
    const height = measurer.offsetHeight || measurer.scrollHeight || 0;
    if (height === 0) {
      return text.length > 25 ? 2 : 1;
    }
    return Math.max(1, Math.round(height / singleLineHeight));
  }

  function splitIntoOneLineWordSegments(text, referenceElement) {
    const words = (text || "").trim().split(/\s+/).filter(Boolean);
    if (!words.length) return [""];

    const segments = [];
    let current = "";
    for (const word of words) {
      const candidate = current ? `${current} ${word}` : word;
      if (measureTextLines(candidate, referenceElement) <= 1) {
        current = candidate;
      } else {
        if (current) segments.push(current);
        current = word;
      }
    }
    if (current) segments.push(current);
    return segments;
  }

  function truncateToOneLineWithEllipsis(text, referenceElement) {
    const trimmed = (text || "").trim();
    if (!trimmed || measureTextLines(trimmed, referenceElement) <= 1) return trimmed;

    const ellipsis = "…";
    let visible = "";
    for (const word of trimmed.split(/\s+/).filter(Boolean)) {
      const candidate = visible ? `${visible} ${word}` : word;
      if (measureTextLines(`${candidate}${ellipsis}`, referenceElement) > 1) break;
      visible = candidate;
    }
    return visible ? `${visible}${ellipsis}` : ellipsis;
  }

  function finalFitDisplaySegments(segments, referenceElement) {
    return segments.flatMap((segment) => {
      const trimmed = (segment || "").trim();
      if (!trimmed || measureTextLines(trimmed, referenceElement) <= 1) return trimmed ? [trimmed] : [];
      return splitIntoOneLineWordSegments(trimmed, referenceElement)
        .map((wordSegment) => truncateToOneLineWithEllipsis(wordSegment, referenceElement));
    });
  }

  function splitIntoOneLineSemanticSegments(text, referenceElement) {
    const trimmed = (text || "").trim();
    if (!trimmed) return [""];
    if (measureTextLines(trimmed, referenceElement) <= 1) {
      return [trimmed];
    }

    const rawSentences = trimmed.split(/(?<=[.?!])\s+/).filter(Boolean);
    const atomicUnits = [];

    for (const sentence of rawSentences) {
      if (measureTextLines(sentence, referenceElement) <= 1) {
        atomicUnits.push(sentence);
      } else {
        const rawClauses = sentence.split(/(?<=[,])\s+/).filter(Boolean);
        for (const clause of rawClauses) {
          if (measureTextLines(clause, referenceElement) <= 1) {
            atomicUnits.push(clause);
          } else {
            atomicUnits.push(...splitIntoOneLineWordSegments(clause, referenceElement));
          }
        }
      }
    }

    if (atomicUnits.length <= 1) return atomicUnits.length ? atomicUnits : [trimmed];

    const finalSegments = [];
    let curMerged = "";
    for (const unit of atomicUnits) {
      if (!curMerged) {
        curMerged = unit;
      } else {
        const candidate = `${curMerged} ${unit}`;
        if (measureTextLines(candidate, referenceElement) <= 1) {
          curMerged = candidate;
        } else {
          finalSegments.push(curMerged);
          curMerged = unit;
        }
      }
    }
    if (curMerged) finalSegments.push(curMerged);

    return finalFitDisplaySegments(finalSegments.length ? finalSegments : [trimmed], referenceElement);
  }

  const PREDEFINED_MESSAGE_SEGMENTS = {
    SERVICE_MODE: [
      "어떻게 이용하시겠어요?",
      "매장 이용 또는 포장을 선택해 주세요.",
    ],
    "어떻게 이용하시겠어요? 매장 이용 또는 포장을 선택해 주세요.": [
      "어떻게 이용하시겠어요?",
      "매장 이용 또는 포장을 선택해 주세요.",
    ],
    "커피 메뉴는 아메리카노 4,700원, 카페라떼 5,200원, 바닐라라떼 3,400원입니다. 논커피 메뉴는 자몽에이드 3,500원, 말차라떼 3,500원입니다. 티 메뉴는 밀크티 3,500원, 캐모마일티 3,700원, 아이스티 4,700원입니다. 디저트 메뉴는 크로플 아이스크림 5,500원, 바스크 치즈 케이크 6,500원입니다.": [
      "커피 메뉴는 아메리카노 4,700원,",
      "카페라떼 5,200원, 바닐라라떼 3,400원입니다.",
      "논커피 메뉴는 자몽에이드 3,500원,",
      "말차라떼 3,500원입니다.",
      "티 메뉴는 밀크티 3,500원,",
      "캐모마일티 3,700원, 아이스티 4,700원입니다.",
      "디저트 메뉴는 크로플 아이스크림 5,500원,",
      "바스크 치즈 케이크 6,500원입니다.",
    ],
    "커피 메뉴는 아메리카노 4,700원, 카페라떼 5,200원, 바닐라라떼 3,400원입니다.": [
      "커피 메뉴는 아메리카노 4,700원,",
      "카페라떼 5,200원, 바닐라라떼 3,400원입니다.",
    ],
    "논커피 메뉴는 자몽에이드 3,500원, 말차라떼 3,500원입니다.": [
      "논커피 메뉴는 자몽에이드 3,500원,",
      "말차라떼 3,500원입니다.",
    ],
    "티 메뉴는 밀크티 3,500원, 캐모마일티 3,700원, 아이스티 4,700원입니다.": [
      "티 메뉴는 밀크티 3,500원,",
      "캐모마일티 3,700원, 아이스티 4,700원입니다.",
    ],
    "디저트 메뉴는 크로플 아이스크림 5,500원, 바스크 치즈 케이크 6,500원입니다.": [
      "디저트 메뉴는 크로플 아이스크림 5,500원,",
      "바스크 치즈 케이크 6,500원입니다.",
    ],
    "포장 주문입니다. 총 결제 금액은 4,700원입니다. 결제를 진행해 주세요.": [
      "포장 주문입니다.",
      "총 결제 금액은 4,700원입니다.",
      "결제를 진행해 주세요.",
    ],
    "매장 주문입니다. 총 결제 금액은 4,700원입니다. 결제를 진행해 주세요.": [
      "매장 주문입니다.",
      "총 결제 금액은 4,700원입니다.",
      "결제를 진행해 주세요.",
    ],
    "주문을 취소하고 처음으로 돌아갈까요? 담아둔 메뉴가 모두 사라집니다.": [
      "주문을 취소하고 처음으로 돌아갈까요?",
      "담아둔 메뉴가 모두 사라집니다.",
    ],
    "HOME_CONFIRM": [
      "주문을 취소하고 처음으로 돌아갈까요?",
      "담아둔 메뉴가 모두 사라집니다.",
    ],
    "아이스 아메리카노를 장바구니에 담았습니다. 무엇을 더 주문하시겠어요?": [
      "아이스 아메리카노를 장바구니에 담았습니다.",
      "무엇을 더 주문하시겠어요?",
    ],
    "잘 이해하지 못했어요. 화면에서 메뉴를 선택하시거나 직원을 불러드릴 수 있습니다.": [
      "잘 이해하지 못했어요.",
      "화면에서 메뉴를 선택하시거나 직원을 불러드릴 수 있습니다.",
    ],
  };

  function getMessageSegments(text, messageId = null, referenceElement = null) {
    if (messageId && PREDEFINED_MESSAGE_SEGMENTS[messageId]) {
      return finalFitDisplaySegments(PREDEFINED_MESSAGE_SEGMENTS[messageId], referenceElement);
    }
    const trimmed = (text || "").trim();
    if (!trimmed) return [""];
    if (PREDEFINED_MESSAGE_SEGMENTS[trimmed]) {
      return finalFitDisplaySegments(PREDEFINED_MESSAGE_SEGMENTS[trimmed], referenceElement);
    }
    return splitIntoOneLineSemanticSegments(trimmed, referenceElement);
  }

  function getActiveResponseBarText() {
    const activeScreen = document.querySelector(".screen.active");
    return activeScreen?.querySelector?.(".response-bar-text")
      || document.querySelector(".response-bar-text");
  }

  function renderResponseBarsWindow(currentSegment, nextSegment = null, { remember = true } = {}) {
    const bars = [
      "welcomeResponseText",
      "serviceModeResponseText",
      "listeningResponseText",
      "orderResponseText",
      "confirmResponseText",
      "optionChangeResponseText",
      "paymentResponseText",
      "completeResponseText",
    ];
    const referenceElement = getActiveResponseBarText();
    const fitted = finalFitDisplaySegments([currentSegment, nextSegment], referenceElement);
    const current = (fitted[0] || "").trim();
    const next = (fitted[1] || "").trim();
    const isTwoLines = Boolean(current && next);
    const displayText = isTwoLines ? `${current}\n${next}` : (current || next || "");

    bars.forEach((id) => {
      const el = document.getElementById(id);
      if (el) {
        el.textContent = displayText;
        el.classList.remove("is-transition-hidden");
        const barParent = typeof el.closest === "function" ? el.closest(".response-bar") : (el.parentElement || null);
        if (barParent && barParent.classList && typeof barParent.classList.toggle === "function") {
          barParent.classList.toggle("is-two-lines", isTwoLines);
          barParent.classList.toggle("is-single-line", !isTwoLines);
        }
      }
    });
  }

  function renderResponseBars(text, { remember = true, cycle = false } = {}) {
    if (text && remember) orderState.lastResponse = text;
    if (responseBarCycleInterval && typeof clearInterval === "function") {
      clearInterval(responseBarCycleInterval);
      responseBarCycleInterval = null;
    }

    const referenceElement = getActiveResponseBarText();
    const segments = finalFitDisplaySegments(getMessageSegments(text, null, referenceElement), referenceElement);

    if (segments.length <= 2) {
      const line1 = segments[0] || (text || "");
      const line2 = segments.length > 1 ? segments[1] : null;
      renderResponseBarsWindow(line1, line2, { remember: false });
      return;
    }

    if (cycle && segments.length > 2 && typeof setInterval === "function") {
      let currentIndex = 0;
      const showCurrent = () => {
        let line1 = "";
        let line2 = null;
        if (currentIndex < segments.length - 1) {
          line1 = segments[currentIndex] || "";
          line2 = segments[currentIndex + 1] || null;
        } else {
          line1 = segments[currentIndex - 1] || "";
          line2 = segments[currentIndex] || null;
        }
        renderResponseBarsWindow(line1, line2, { remember: false });
        currentIndex = (currentIndex + 1) % segments.length;
      };
      showCurrent();
      responseBarCycleInterval = setInterval(showCurrent, 3000);
    } else {
      const line1 = segments[0] || (text || "");
      const line2 = segments.length > 1 ? segments[1] : null;
      renderResponseBarsWindow(line1, line2, { remember: false });
    }
  }

  async function fetchState() {
    const sessionGeneration = orderSessionGeneration;
    try {
      const data = await apiFetch("/api/state").then((r) => r.json());
      if (data.cart) {
        commitCartSnapshot(data.cart, { sessionGeneration });
      }
      if (typeof data.tts_level === "number") ttsState.ttsLevel = data.tts_level;
      if (data.last_response) orderState.lastResponse = data.last_response;
    } catch (e) {
      /* keep current state */
    }
  }

  /* ======================================================================
     Render helpers
     ====================================================================== */
  function formatPrice(n) {
    return n.toLocaleString() + "원";
  }

  async function fetchSegmentTTS(synthesisText, streamId, level) {
    if (!synthesisText || typeof synthesisText !== "string") return null;
    if (streamId !== activeTTSStreamId) return null;
    try {
      const requestedLevel = typeof level === "number" ? level : ttsState.ttsLevel;
      console.debug("[Adaptive TTS prefetch]", { synthesisText, tts_level: requestedLevel });
      const data = await callApi("/api/tts", { json: { text: synthesisText, already_chunked: true, tts_level: requestedLevel } });
      if (streamId !== activeTTSStreamId) return null;
      return (data && typeof data.tts_audio_base64 === "string" && data.tts_audio_base64) ? data.tts_audio_base64 : null;
    } catch (err) {
      if (streamId !== activeTTSStreamId) return null;
      console.warn("[TTS Prefetch] failed for synthesis text:", synthesisText, err);
      return null;
    }
  }

  async function presentSystemMessage(data, options = {}) {
    const {
      speak = true,
      inputContext = "ORDER",
      remember = true,
      isControlFeedback = false,
      resumeListeningAfterPlayback = false,
      updateResponseBar = true,
      generation = interactionGeneration,
    } = options;
    if (!isCurrentInteraction(generation)) return false;
    if (!data || typeof data.response_text !== "string") return false;
    // Sync tts level from server response to ensure prefetch uses correct level
    if (typeof data.tts_level === "number") ttsState.ttsLevel = data.tts_level;
    // An automatic speed-change notice belongs to the speech presentation,
    // never the Response Bar or replay source.  Awaiting here orders just the
    // two audio streams; callers still use startSystemPresentation and never
    // await the lifecycle for touch/navigation work.
    if (data.speech_prefix) {
      renderAccessibilityControls();
      const body = { ...data };
      delete body.speech_prefix;
      await presentSystemMessage(data.speech_prefix, {
        ...options,
        remember: false,
        isControlFeedback: true,
        updateResponseBar: false,
        resumeListeningAfterPlayback: false,
        generation,
      });
      if (!isCurrentInteraction(generation)) return false;
      return presentSystemMessage(body, options);
    }
    if (!(globalThis.MalloApi?.isLocalTouchMode || globalThis.MalloApi?.adapterMode === "LOCAL_TOUCH")) {
      const advertisedAudio = Boolean(data.tts_audio_base64)
        || Boolean(data.tts_segments?.some((segment) => segment.tts_audio_base64));
      if (advertisedAudio) ttsState.available = true;
    }
    const rawDisplayText = data.display_text || data.response_text || "";
    const authoritativeDisplaySegments = Array.isArray(data.display_segments) && data.display_segments.length
      ? data.display_segments.map((segment) => String(segment || "").trim()).filter(Boolean)
      : getMessageSegments(rawDisplayText, data.message_id);
    const isMultiSegment = Array.isArray(data.tts_segments) && data.tts_segments.length > 0;

    if (remember && !isControlFeedback) {
      if (updateResponseBar) orderState.lastResponse = data.response_text;
      const replaySegments = (isMultiSegment && data.tts_segments)
        ? data.tts_segments.map((s, idx) => ({
            chunk_id: s.chunk_id || `replay:${idx}`,
            chunk_index: typeof s.chunk_index === "number" ? s.chunk_index : idx,
            segment_index: typeof s.segment_index === "number" ? s.segment_index : idx,
            text: s.text || s.display_text || rawDisplayText,
            display_text: s.display_text || s.text || rawDisplayText,
            tts_text: s.tts_text || s.synthesis_text || s.text || rawDisplayText,
            synthesis_text: s.synthesis_text || s.tts_text || s.text || rawDisplayText,
            tts_audio_base64: null,
            gap_ms: typeof s.gap_ms === "number" ? s.gap_ms : (typeof data.gap_ms === "number" ? data.gap_ms : 0),
          }))
        : getMessageSegments(rawDisplayText, data.message_id).map((t, idx) => ({
            chunk_id: `replay:${idx}`,
            chunk_index: idx,
            segment_index: idx,
            text: t,
            display_text: t,
            tts_text: t,
            synthesis_text: t,
            tts_audio_base64: data.tts_audio_base64 || null,
            gap_ms: typeof data.gap_ms === "number" ? data.gap_ms : 0,
          }));

      lastReplayableMessage = {
        response_text: data.response_text,
        display_text: rawDisplayText,
        display_segments: authoritativeDisplaySegments,
        message_id: data.message_id || null,
        tts_level: typeof data.tts_level === "number" ? data.tts_level : ttsState.ttsLevel,
        gap_ms: typeof data.gap_ms === "number" ? data.gap_ms : 0,
        tts_segments: replaySegments,
        tts_audio_base64: data.tts_audio_base64 || null,
      };
      // Replay becomes valid when its canonical source is fixed; it does not
      // need to wait for every audio chunk to finish.
      renderAccessibilityControls();
    }

    if (isMultiSegment) {
      const definedChunks = data.tts_segments.map((s, idx) => ({
        chunk_id: s.chunk_id || `chunk:${idx}`,
        chunk_index: typeof s.chunk_index === "number" ? s.chunk_index : idx,
        segment_index: typeof s.segment_index === "number" ? s.segment_index : idx,
        display_text: s.display_text || s.text || rawDisplayText,
        tts_text: s.tts_text || s.synthesis_text || s.text || rawDisplayText,
        synthesis_text: s.synthesis_text || s.tts_text || s.text || rawDisplayText,
        tts_audio_base64: s.tts_audio_base64 || null,
        gap_ms: typeof s.gap_ms === "number" ? s.gap_ms : (typeof data.gap_ms === "number" ? data.gap_ms : (ttsState.ttsLevel === 1 ? 280 : ttsState.ttsLevel === 2 ? 480 : 0)),
      }));
      const totalChunks = definedChunks.length;

      // Response Bar uses the complete server-provided display list. TTS
      // chunks are audio units only and must never reconstruct this list.
      const displaySegments = authoritativeDisplaySegments.length
        ? authoritativeDisplaySegments
        : [rawDisplayText];
      const totalDisplaySegs = displaySegments.length;

      // 1. Initial display setup on Response Bar
      if (updateResponseBar) {
        const line1 = displaySegments[0];
        const line2 = totalDisplaySegs > 1 ? displaySegments[1] : null;
        renderResponseBarsWindow(line1, line2, { remember });
      }

      if (!speak) return true;

      // 2. Producer/Consumer Prefetch & Playback Pipeline
      const streamId = ++activeTTSStreamId;
      currentTTSCategory = isControlFeedback ? "CONTROL_FEEDBACK" : "CONVERSATION";
      activeTTSMessageStreamId = streamId;
      activeTTSMessageStarted = false;
      renderTTSPlaybackStatus();

      const prefetchPromises = new Array(totalChunks);

      // Seed initial prefetch for C1
      if (definedChunks[0].tts_audio_base64) {
        prefetchPromises[0] = Promise.resolve(definedChunks[0].tts_audio_base64);
      } else {
        prefetchPromises[0] = fetchSegmentTTS(definedChunks[0].synthesis_text, streamId, typeof data.tts_level === "number" ? data.tts_level : ttsState.ttsLevel);
      }

      // Prefetch C2 in parallel immediately
      if (totalChunks > 1) {
        if (definedChunks[1].tts_audio_base64) {
          prefetchPromises[1] = Promise.resolve(definedChunks[1].tts_audio_base64);
        } else {
          prefetchPromises[1] = fetchSegmentTTS(definedChunks[1].synthesis_text, streamId, typeof data.tts_level === "number" ? data.tts_level : ttsState.ttsLevel);
        }
      }

      let playedAnyAudio = false;
      let currentRenderedSegmentIndex = -1;

      for (let i = 0; i < totalChunks; i++) {
        if (streamId !== activeTTSStreamId || !isCurrentInteraction(generation)) return false;

        const currentChunk = definedChunks[i];
        const sIdx = currentChunk.segment_index;

        // 3. Sliding Window Update (Driven strictly by entry into display segment sIdx)
        if (updateResponseBar && sIdx !== currentRenderedSegmentIndex) {
          currentRenderedSegmentIndex = sIdx;
          if (totalDisplaySegs <= 2) {
            const s1 = displaySegments[0];
            const s2 = totalDisplaySegs > 1 ? displaySegments[1] : null;
            renderResponseBarsWindow(s1, s2, { remember: sIdx === 0 && i === 0 });
          } else {
            if (sIdx === 0 || sIdx === 1) {
              const s1 = displaySegments[0];
              const s2 = displaySegments[1];
              renderResponseBarsWindow(s1, s2, { remember: sIdx === 0 && i === 0 });
            } else {
              const prevSeg = displaySegments[sIdx - 1];
              const currSeg = displaySegments[sIdx];
              renderResponseBarsWindow(prevSeg, currSeg, { remember: false });
            }
          }
        }

        // 4. Prefetch upcoming chunks in background while current chunk plays
        if (i + 1 < totalChunks && !prefetchPromises[i + 1]) {
          prefetchPromises[i + 1] = definedChunks[i + 1].tts_audio_base64
            ? Promise.resolve(definedChunks[i + 1].tts_audio_base64)
            : fetchSegmentTTS(definedChunks[i + 1].synthesis_text, streamId, typeof data.tts_level === "number" ? data.tts_level : ttsState.ttsLevel);
        }
        if (i + 2 < totalChunks && !prefetchPromises[i + 2]) {
          prefetchPromises[i + 2] = definedChunks[i + 2].tts_audio_base64
            ? Promise.resolve(definedChunks[i + 2].tts_audio_base64)
            : fetchSegmentTTS(definedChunks[i + 2].synthesis_text, streamId, typeof data.tts_level === "number" ? data.tts_level : ttsState.ttsLevel);
        }

        // 5. Await audio for current chunk i
        let audioBase64 = null;
        if (prefetchPromises[i]) {
          audioBase64 = await prefetchPromises[i];
        } else if (definedChunks[i].tts_audio_base64) {
          audioBase64 = definedChunks[i].tts_audio_base64;
        } else {
          audioBase64 = await fetchSegmentTTS(currentChunk.synthesis_text, streamId, typeof data.tts_level === "number" ? data.tts_level : ttsState.ttsLevel);
        }

        if (audioBase64 && lastReplayableMessage && lastReplayableMessage.tts_segments && lastReplayableMessage.tts_segments[i]) {
          lastReplayableMessage.tts_segments[i].tts_audio_base64 = audioBase64;
        }

        if (streamId !== activeTTSStreamId || !isCurrentInteraction(generation)) return false;

        // 6. Play current chunk audio
        if (audioBase64) {
          const isLast = (i === totalChunks - 1);
          pendingSystemPromptListening = (isLast && (resumeListeningAfterPlayback || (!isControlFeedback && data.response_required === true && data.next_listening_mode === "SYSTEM_PROMPTED")))
            ? { screen: uiState.screen, inputContext }
            : null;

          const played = await ttsPlayer.loadAndPlay(audioBase64);
          if (played) {
            playedAnyAudio = true;
            await ttsPlayer.waitForCompletion();

            // Apply actual silence gap before next chunk (if not last chunk)
            if (!isLast) {
              const gap = typeof currentChunk.gap_ms === "number" ? currentChunk.gap_ms : 0;
              if (gap > 0) {
                await new Promise((resolve) => setTimeout(resolve, gap));
              }
            }
          }
        }
      }

      // 7. End of stream: maintain final window state
      if (updateResponseBar) {
        if (totalDisplaySegs <= 2) {
          renderResponseBarsWindow(
            displaySegments[0],
            totalDisplaySegs > 1 ? displaySegments[1] : null,
            { remember: false }
          );
        } else {
          renderResponseBarsWindow(
            displaySegments[totalDisplaySegs - 2],
            displaySegments[totalDisplaySegs - 1],
            { remember: false }
          );
        }
      }

      if (!isControlFeedback && playedAnyAudio) ttsState.hasAudio = true;
      completeTTSMessageStream(streamId);
      renderAccessibilityControls();
      return true;
    }

    // Single utterance fallback
    const textSegments = getMessageSegments(rawDisplayText, data.message_id);
    if (updateResponseBar) {
      const line1 = textSegments[0] || rawDisplayText;
      const line2 = textSegments.length > 1 ? textSegments[1] : null;
      renderResponseBarsWindow(line1, line2, { remember });
    }

    if (!speak) return true;
    return playTTSFromResponse(data, { inputContext, isControlFeedback, resumeListeningAfterPlayback, generation });
  }

  // Presentation owns its own async failure/cancellation. Callers that change
  // the cart, screen, or session must not wait for synthesis or playback.
  function startSystemPresentation(data, options = {}) {
    const speechDone = presentSystemMessage(data, options);
    speechDone.catch((error) => {
      console.warn("시스템 안내 음성을 재생하지 못했습니다.", error);
    });
    return speechDone;
  }

  function startSystemMessage(messageId, options = {}) {
    const request = requestSystemMessage(messageId, options);
    request.catch((error) => {
      console.warn("시스템 안내를 요청하지 못했습니다.", error);
    });
    return request;
  }

  async function tryRecoverRemoteSession(currentScreen = uiState.screen) {
    if (!globalThis.MalloApi?.isLocalTouchMode && globalThis.MalloApi?.adapterMode !== "LOCAL_TOUCH") {
      return false;
    }
    const ALLOWED_SCREENS = ["WELCOME", "SERVICE_MODE", "ORDER", "ORDER_REVIEW", "OPTION_CHANGE", "PAYMENT", "COMPLETE"];
    if (!ALLOWED_SCREENS.includes(currentScreen)) return false;
    if (!globalThis.MalloApi?.attemptHandoffToServer) return false;

    const sessionGeneration = orderSessionGeneration;
    const handoffCart = await globalThis.MalloApi.attemptHandoffToServer(currentScreen);
    if (handoffCart) {
      return commitCartSnapshot(handoffCart, { sessionGeneration });
    }
    return false;
  }

  async function requestSystemMessage(messageId, { inputContext = "ORDER", updateResponseBar = true } = {}) {
    const generation = interactionGeneration;
    console.info("[System message] request start", { messageId });
    const isLocal = globalThis.MalloApi?.isLocalTouchMode || globalThis.MalloApi?.adapterMode === "LOCAL_TOUCH";
    if (isLocal) {
      // LocalTouch already has canonical fixed text. Render it before a
      // best-effort recovery so offline networking never blocks the screen.
      const localData = await callApi("/api/system-message", { json: { message_id: messageId } });
      if (!isCurrentInteraction(generation)) return null;
      startSystemPresentation(localData, {
        speak: false,
        inputContext,
        generation,
        updateResponseBar,
        isControlFeedback: !updateResponseBar,
      });

      if (!await tryRecoverRemoteSession(uiState.screen)) return localData;
      if (!isCurrentInteraction(generation)) return null;
      const recoveredData = await callApi("/api/system-message", { json: { message_id: messageId } });
      if (!isCurrentInteraction(generation)) return null;
      // Same canonical text is already visible; the retry is speech-only.
      startSystemPresentation(recoveredData, {
        inputContext,
        generation,
        updateResponseBar: false,
        isControlFeedback: !updateResponseBar,
      });
      return recoveredData;
    }

    const data = await callApi("/api/system-message", { json: { message_id: messageId } });
    console.info("[System message] response received", {
      messageId,
      responseText: data && data.response_text,
      hasAudio: Boolean(data && data.tts_audio_base64),
      audioBase64Length: typeof data?.tts_audio_base64 === "string" ? data.tts_audio_base64.length : 0,
    });
    if (!isCurrentInteraction(generation)) return null;
    startSystemPresentation(data, { inputContext, generation, updateResponseBar, isControlFeedback: !updateResponseBar });
    return data;
  }

  function presentPaymentReadinessFailure(messageId, fallbackText) {
    console.info(`[Payment guard] message="${fallbackText}"`, { messageId });
    renderResponseBars(fallbackText);
    startSystemMessage(messageId, { inputContext: "ORDER" });
  }

  function refreshOrderScreen({ added = false } = {}) {
    const itemCount = orderState.items.length;
    const totalQuantity = orderState.items.reduce((sum, item) => sum + (item.quantity || 0), 0);
    const cartItemBadge = document.getElementById("cartItemBadge");
    cartItemBadge.hidden = totalQuantity === 0;
    cartItemBadge.textContent = totalQuantity ? String(totalQuantity) : "";
    document.getElementById("listeningTitle").textContent = added
      ? "메뉴를 담았어요"
      : itemCount ? "무엇을 더 주문하시겠어요?" : "무엇을 주문하시겠어요?";
    document.getElementById("listeningResponseText").textContent = orderState.lastResponse || (itemCount
      ? "원하시는 메뉴를 말씀해 주세요."
      : "원하시는 메뉴를 말씀해 주세요.");
  }

  function refreshConfirmScreen() {
    renderCartScreen();
  }

  function renderTouchMenu(category = "all") {
    activeTouchMenuCategory = category;
    const grid = document.getElementById("touchMenuGrid");
    document.getElementById("touchMenuCategories").innerHTML = MalloMenuMetadata.categories.map((item) =>
      `<button class="touch-menu-category${item.id === category ? " is-active" : ""}" data-category="${item.id}">${item.name}</button>`,
    ).join("");
    grid.innerHTML = Object.entries(MalloMenuMetadata.items)
      .filter(([, item]) => category === "all" || item.category === category)
      .map(([menuId, item]) => `
      <button class="touch-menu-card" data-menu-id="${menuId}">
        ${item.imagePath
          ? `<img src="${item.imagePath}" alt="${item.name}" />`
          : `<span class="touch-menu-placeholder touch-menu-placeholder--${item.accent}" aria-hidden="true">${item.name.slice(0, 1)}</span>`}
        <span class="touch-menu-name">${item.name}</span>
        <strong>${formatPrice(item.price)}</strong>
      </button>`).join("");
  }

  function touchTemperatureOptions(item) {
    if (Array.isArray(item.temperatureOptions)) return item.temperatureOptions;
    return item.temperature ? [item.temperature] : [];
  }

  function touchTemperatureLabel(temperature) {
    return temperature === "hot" ? "따뜻하게" : "아이스";
  }

  function renderTouchMenuSelection() {
    if (!touchMenuSelection) return;
    const { menuId, quantity, temperature } = touchMenuSelection;
    const item = MalloMenuMetadata.get(menuId) || { name: menuId || "", price: 4500, accent: "coffee" };
    const options = touchTemperatureOptions(item);
    const needsTemperature = options.length > 1;
    const itemName = item.name || menuId || "";
    const itemPrice = (item.price || 4500) * quantity;
    document.getElementById("clarificationQuestion").textContent = needsTemperature
      ? `${itemName} 온도와 수량을 선택해 주세요.`
      : `${itemName} 수량을 선택해 주세요.`;
    document.getElementById("clarificationActions").innerHTML = `
      <div class="option-modal-preview">
        ${item.imagePath
          ? `<img class="option-modal-image" src="${item.imagePath}" alt="${itemName}" />`
          : `<div class="option-modal-placeholder touch-menu-placeholder--${item.accent || "coffee"}">${itemName ? itemName.slice(0, 1) : "☕"}</div>`}
        <div class="option-modal-info">
          <span class="option-modal-name">${itemName}</span>
          <span class="option-modal-price">${formatPrice(itemPrice)}</span>
        </div>
      </div>
      ${needsTemperature ? `<div class="touch-menu-temperature-controls" aria-label="${itemName} 온도 선택">${options.map((option) =>
        `<button type="button" class="touch-temperature-choice touch-temperature-choice--${option}${option === temperature ? " is-selected" : ""}" data-temperature="${option}" aria-pressed="${option === temperature}">${touchTemperatureLabel(option)}</button>`,
      ).join("")}</div>` : ""}
      <div class="touch-menu-quantity-controls" aria-label="${itemName} 수량 선택">
        <button type="button" class="touch-menu-quantity-button" data-touch-menu-quantity="decrease" aria-label="수량 줄이기"${quantity <= 1 ? " disabled" : ""}>−</button>
        <strong class="touch-menu-quantity-value" aria-live="polite">${quantity}</strong>
        <button type="button" class="touch-menu-quantity-button" data-touch-menu-quantity="increase" aria-label="수량 늘리기"${quantity >= 5 ? " disabled" : ""}>+</button>
      </div>
      <button type="button" class="btn-primary touch-menu-add"${needsTemperature && !temperature ? " disabled" : ""}>장바구니에 담기</button>
      <button class="btn-secondary touch-temperature-cancel" type="button">취소</button>`;
  }

  function showTouchMenuSelection(menuId) {
    const options = touchTemperatureOptions(MalloMenuMetadata.get(menuId));
    touchMenuSelection = { menuId, temperature: options.length === 1 ? (options[0] || null) : null, quantity: 1 };
    renderTouchMenuSelection();
    document.getElementById("clarificationArea").hidden = false;
  }

  function hideTouchMenuSelection() {
    touchMenuSelection = null;
    document.getElementById("clarificationArea").hidden = true;
    document.getElementById("clarificationActions").innerHTML = "";
  }

  function addTouchMenuItem({ menuId, temperature, quantity }) {
    hideTouchMenuSelection();
    sendCommands([{ intent: "ADD_ITEM", target_item_id: menuId, category_id: null, quantity, temperature, query_tags: null, detail_fields: null, options: null, fulfillment_type: null }]).then((result) => afterUtterance(result, "ORDER", Boolean(result && result.success)));
  }

  function hasCartItems() {
    return Array.isArray(orderState.items) && orderState.items.length > 0;
  }

  const CART_MUTATION_INTENTS = new Set(["ADD_ITEM", "UPDATE_QUANTITY", "UPDATE_OPTION", "REMOVE_ITEM"]);
  const pendingCartMutations = new Set();

  function hasPendingCartMutation() {
    return [...pendingCartMutations].some((mutation) => mutation.sessionGeneration === orderSessionGeneration);
  }

  async function waitForPendingCartMutations() {
    const sessionGeneration = orderSessionGeneration;
    while (sessionGeneration === orderSessionGeneration) {
      const pending = [...pendingCartMutations]
        .filter((mutation) => mutation.sessionGeneration === sessionGeneration)
        .map((mutation) => mutation.settled);
      if (!pending.length) return true;
      await Promise.allSettled(pending);
    }
    return false;
  }

  function applyCartSnapshot(cart) {
    orderState.items = cart.items || [];
    orderState.totalPrice = cart.total_price || 0;
    orderState.fulfillmentType = cart.fulfillment_type || null;
    orderState.confirmed = cart.confirmed === true;
    orderState.status = cart.confirmed ? "confirmed" : (orderState.items.length ? "building" : "empty");
  }

  function refreshCurrentOrderScreen() {
    if (uiState.screen === "ORDER") {
      refreshOrderScreen();
    } else if (uiState.screen === "ORDER_REVIEW") {
      refreshConfirmScreen();
    } else if (uiState.screen === "PAYMENT") {
      refreshPaymentScreen();
    }
  }

  function commitCartSnapshot(cart, { sessionGeneration, mutationSequence = null } = {}) {
    // A previous order must never refill a newly started order. Within the
    // current order, however, navigation/TTS generations are presentation
    // concerns and must not prevent the cart or its active screen from
    // updating.
    if (sessionGeneration !== orderSessionGeneration) return false;
    if (mutationSequence !== null && mutationSequence < lastAppliedCartMutationSequence) return false;

    applyCartSnapshot(cart);
    globalThis.MalloApi?.syncLocalCartFromRemote?.(cart);
    if (mutationSequence !== null) lastAppliedCartMutationSequence = mutationSequence;

    // Render from the same authoritative snapshot immediately. In
    // particular, do not defer ORDER_REVIEW to presentation/TTS completion.
    refreshCurrentOrderScreen();
    return true;
  }

  function showEmptyCartGuidance() {
    orderState.status = "empty";
    renderResponseBars("장바구니가 비어 있습니다. 메뉴를 먼저 선택해 주세요.");
  }

  function presentEmptyCartReviewGuidance() {
    showEmptyCartGuidance();
    startSystemMessage("PAYMENT_EMPTY_CART", { inputContext: "ORDER" });
  }

  function renderOrderSummaryCard(container, cart) {
    if (!cart || !cart.items || cart.items.length === 0) {
      container.innerHTML = '<p style="text-align:center;color:#666;">담긴 메뉴가 없습니다.</p>';
      return;
    }
    const itemsHtml = renderMenuItems(cart.items);

    const fulfillmentLabel = fulfillmentText(cart.fulfillment_type);
    container.innerHTML = `
      ${fulfillmentLabel ? `<div class="fulfillment-label">${fulfillmentLabel}</div>` : ""}
      ${itemsHtml}
      <div class="total-row">
        <span class="total-label">총 금액</span>
        <span class="total-price">${formatPrice(cart.total_price)}</span>
      </div>`;
  }

  function renderMenuItems(items) {
    return items
      .map((item) => {
        const temperatureLabel = item.temperature === "iced" ? "아이스" : item.temperature === "hot" ? "따뜻한" : "";
        const sizeLabel = item.options?.size ? item.options.size.toUpperCase() : "";
        const metadata = MalloMenuMetadata.get(item.menu_id);
        const media = metadata.imagePath
          ? `<img class="menu-media-image" src="${metadata.imagePath}" alt="${item.name}" />`
          : `<div class="menu-media-placeholder menu-media-placeholder--${metadata.accent}" aria-hidden="true">${item.name.slice(0, 1)}</div>`;
        return `
          <article class="menu-card">
            <div class="menu-media">${media}</div>
            <div class="menu-card-body">
              <div class="menu-card-heading">
                <span class="item-name">${item.name}</span>
                <span class="item-quantity">× ${item.quantity}</span>
              </div>
              ${temperatureLabel ? `<span class="temperature-badge temperature-badge--${item.temperature}">${temperatureLabel}</span>` : ""}
              ${sizeLabel ? `<span style="font-size:15px;color:#666;">${sizeLabel}</span>` : ""}
            </div>
            <span class="item-price">${formatPrice(item.total_price)}</span>
          </article>`;
      })
      .join("");
  }

  function fulfillmentText(fulfillmentType) {
    return fulfillmentType === "takeout"
      ? "포장"
      : fulfillmentType === "dine_in"
        ? "매장"
        : "";
  }

  function renderCartScreen() {
    const items = orderState.items;
    const fulfillmentLabel = fulfillmentText(orderState.fulfillmentType);
    document.getElementById("confirmFulfillmentLabel").textContent = fulfillmentLabel;
    const paymentFulfillmentBadge = document.getElementById("paymentFulfillmentBadge");
    paymentFulfillmentBadge.hidden = !fulfillmentLabel;
    paymentFulfillmentBadge.textContent = fulfillmentLabel;
    document.getElementById("confirmItems").innerHTML = items.length
      ? renderCartItems(items)
      : '<p class="empty-cart-message">담긴 메뉴가 없습니다.</p>';
    document.getElementById("confirmTotalPrice").textContent = formatPrice(orderState.totalPrice);
  }

  function renderCartItems(items) {
    return items.map((item, index) => {
      const metadata = MalloMenuMetadata.get(item.menu_id) || { name: item.name, price: item.unit_price, accent: "coffee" };
      const media = metadata.imagePath
        ? `<img class="menu-media-image" src="${metadata.imagePath}" alt="${item.name}" />`
        : `<div class="menu-media-placeholder menu-media-placeholder--${metadata.accent || "coffee"}" aria-hidden="true">${item.name.slice(0, 1)}</div>`;
      const temperatureOptions = touchTemperatureOptions(metadata);
      const isDualTemp = temperatureOptions.length === 2;
      const temperatureControls = isDualTemp
        ? `<div class="cart-temperature-controls" aria-label="${item.name} 온도 선택">${temperatureOptions.map((temperature) =>
          `<button type="button" class="cart-temperature-button cart-temperature-button--${temperature}${temperature === item.temperature ? " is-selected" : ""}" data-cart-temperature="${temperature}" aria-pressed="${temperature === item.temperature}">${temperature === "hot" ? "따뜻한" : "아이스"}</button>`,
        ).join("")}</div>`
        : "";
      return `
        <article class="menu-card cart-item${isDualTemp ? " has-temp-controls" : ""}" data-index="${index}" data-menu-id="${item.menu_id}" data-temperature="${item.temperature || ""}">
          <div class="menu-media">${media}</div>
          <div class="cart-item-info">
            <span class="item-name">${item.name}</span>
            <div class="cart-item-controls-row">
              <div class="cart-controls-stack">
                <div class="cart-quantity-controls" aria-label="${item.name} 수량 조절">
                  <button type="button" class="cart-quantity-button" data-cart-quantity="decrease" aria-label="${item.name} 수량 줄이기"${item.quantity <= 1 ? " disabled" : ""}>−</button>
                  <span class="item-quantity" aria-label="현재 수량">${item.quantity}</span>
                  <button type="button" class="cart-quantity-button" data-cart-quantity="increase" aria-label="${item.name} 수량 늘리기">+</button>
                </div>
                ${temperatureControls}
              </div>
              <button type="button" class="cart-remove-button" data-cart-remove="${item.menu_id}" aria-label="${item.name} 삭제">삭제</button>
            </div>
          </div>
          <div class="cart-item-price-area">
            <span class="item-price">${formatPrice(item.total_price)}</span>
          </div>
        </article>`;
    }).join("");
  }

  function cartCommand(intent, item, { quantity = null, temperature = null } = {}) {
    return {
      intent, target_item_id: item.menu_id, category_id: null, quantity, temperature,
      query_tags: null, detail_fields: null, options: null, fulfillment_type: null,
    };
  }

  async function updateCartQuantity(item, quantity) {
    await sendCommands([cartCommand("UPDATE_QUANTITY", item, { quantity, temperature: item.temperature })]);
  }

  async function updateCartTemperature(item, temperature) {
    if (temperature === item.temperature) return;
    await sendCommands([cartCommand("UPDATE_OPTION", item, { quantity: item.quantity, temperature })]);
  }

  async function updateCartRemove(item) {
    await sendCommands([cartCommand("REMOVE_ITEM", item, { quantity: item.quantity, temperature: item.temperature })]);
  }

  /* ======================================================================
     API call + result handling
     ====================================================================== */
  async function sendUtterance(text, requestEpoch = null, { speak = true, present = true, source = "touch" } = {}) {
    if (!text || !text.trim()) return;
    if (source === "voice") {
      lastInputMode = "VOICE";
      interactionMode = "VOICE";
    } else {
      lastInputMode = "TOUCH";
      interactionMode = "TOUCH";
    }
    const generation = interactionGeneration;
    const sessionGeneration = orderSessionGeneration;
    let result = null;
    try {
      const data = await callApi("/api/order", { json: { text } });
      result = data;
      if (data.cart) {
        commitCartSnapshot(data.cart, { sessionGeneration });
      }
      if (!isCurrentInteraction(generation) || (requestEpoch !== null
          && (requestEpoch !== voiceLifecycleEpoch || !isVoiceAllowed()))) return null;
      if (present) startSystemPresentation(data, { speak, inputContext: currentInputContext, generation });
    } catch (err) {
      if (err?.name === "AbortError") {
        console.debug("[Mallo API] order request cancelled");
        return null;
      }
      orderState.lastResponse = "서버와 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.";
      sttState.transcript = "";
      sttState.confidence = null;
    }
    if (!present) renderResponseBars(orderState.lastResponse);
    return result;
  }

  async function sendCommands(commands, { present = true } = {}) {
    globalThis.MalloApi?.markLocalCartDirty?.();
    const generation = interactionGeneration;
    const isCartMutation = commands.some((command) => CART_MUTATION_INTENTS.has(command.intent));
    const sessionGeneration = orderSessionGeneration;
    const mutation = isCartMutation
      ? (() => {
          let settle;
          const settled = new Promise((resolve) => { settle = resolve; });
          return { sessionGeneration, sequence: ++nextCartMutationSequence, settled, settle };
        })()
      : null;
    if (mutation) pendingCartMutations.add(mutation);
    let data;
    try {
      data = await callApi("/api/commands", { json: { commands } });
      if (data.cart) {
        const committed = commitCartSnapshot(data.cart, {
          sessionGeneration,
          mutationSequence: mutation?.sequence ?? null,
        });
        // A reset began another order while this request was in flight.
        // Neither its cart snapshot nor its presentation may cross that
        // session boundary.
        if (!committed) return null;
      }
      // A newer interaction can supersede response text/TTS, but never the
      // cart commit above when it is still the same order session.
      if (!isCurrentInteraction(generation)) return data;
    } finally {
      if (mutation) {
        pendingCartMutations.delete(mutation);
        mutation.settle();
      }
    }
    if (present) startSystemPresentation(data, { inputContext: "ORDER", generation });
    if (!present && !commands.some((command) => command.intent === "SET_FULFILLMENT")) {
      renderResponseBars(orderState.lastResponse);
    }
    return data;
  }

  async function sendAudio(blob, requestEpoch = voiceLifecycleEpoch, recordingId = activeRecordingId) {
    const generation = interactionGeneration;
    const sessionGeneration = orderSessionGeneration;
    let result = null;
    try {
      const buffer = blob ? await blob.arrayBuffer() : new ArrayBuffer(0);
      logAudioTimeline("audio-stt-request", { recordingId, bytes: buffer.byteLength });
      const stt = await callApi("/api/audio/stt", { raw: new Uint8Array(buffer) });
      if (!isCurrentInteraction(generation) || requestEpoch !== voiceLifecycleEpoch || recordingId !== activeRecordingId || !isVoiceAllowed()) return null;
      if (globalThis.MalloApi?.isDemoMode || !stt || stt.error) {
        throw new Error("Server disconnected");
      }
      logAudioTimeline("audio-stt-response", { recordingId });
      sttState.transcript = typeof stt.transcript === "string" ? stt.transcript : (typeof stt.text === "string" ? stt.text : "");
      sttState.confidence = typeof stt.confidence === "number" ? stt.confidence : null;
      transcriptRecordingId = recordingId;
      logAudioTimeline("transcript-rendered", { recordingId, transcript: sttState.transcript });
      setVoiceState("PROCESSING");

      const isHomeConfirmOpen = !document.getElementById("homeConfirmDialog").hidden;
      const screenForRouting = isHomeConfirmOpen ? "HOME_CONFIRM" : uiState.screen;

      const routed = MalloUICommandRouter.route(screenForRouting, sttState.transcript);
      const command = routed && ["GO_HOME", "CALL_STAFF", "REPEAT", "SPEED_NORMAL", "SPEED_SLOW", "SPEED_VERY_SLOW", "CYCLE_SPEED"].includes(routed.action) ? routed : null;
      if (command) {
        lastInputMode = "VOICE";
        setVoiceState("IDLE");
        await executeUICommand(command.action, { source: "voice" });
        return { success: true, ui_action: command.action };
      }
      if (!isCurrentInteraction(generation) || requestEpoch !== voiceLifecycleEpoch || recordingId !== activeRecordingId || !isVoiceAllowed()) return null;
      lastInputMode = "VOICE";
      logAudioTimeline("audio-interpret-request", { recordingId });
      result = await callApi("/api/audio/interpret", { json: { transcript: sttState.transcript } });
      if (globalThis.MalloApi?.isDemoMode || !result || result.error) {
        throw new Error("Server disconnected");
      }
      if (result.cart) {
        commitCartSnapshot(result.cart, { sessionGeneration });
      }
      if (!isCurrentInteraction(generation) || requestEpoch !== voiceLifecycleEpoch || recordingId !== activeRecordingId || !isVoiceAllowed()) return null;
      logAudioTimeline("audio-interpret-response", { recordingId });
      setVoiceState("IDLE");
    } catch (err) {
      if (err?.name === "AbortError") {
        console.debug("[Mallo API] audio request cancelled", { recordingId });
        return null;
      }
      orderState.lastResponse = "서버 연결이 불안정하여 음성 주문을 사용할 수 없습니다. 화면을 눌러 주문해 주세요.";
      sttState.transcript = "";
      transcriptRecordingId = null;
      sttState.confidence = null;
      deactivateVoiceInput();
      setVoiceState("IDLE");
    }
    renderResponseBars(orderState.lastResponse);
    return result;
  }

  async function sendAccessibilityAction(action, { resumeListeningAfterPlayback = false } = {}) {
    const generation = interactionGeneration;
    const isPreview = action === "CYCLE_SPEED" || action.startsWith("SET_SPEED_");
    if (isPreview && (
      !ttsState.available
      || globalThis.MalloApi?.isLocalTouchMode
      || globalThis.MalloApi?.adapterMode === "LOCAL_TOUCH"
    )) return;
    const isLocal = globalThis.MalloApi?.isLocalTouchMode || globalThis.MalloApi?.adapterMode === "LOCAL_TOUCH";
    // Disabled repeat/speed controls must not become recovery triggers.
    if (isLocal && (isPreview || action === "REPEAT")) return;
    if (isLocal) {
      await tryRecoverRemoteSession(uiState.screen);
    }
    let signal;
    if (action === "REPEAT") {
      ttsPlayer.stop();
      if (repeatRequestController) repeatRequestController.abort();
      repeatRequestController = new AbortController();
      signal = repeatRequestController.signal;
    }
    ttsState.status = "loading";
    ttsState.error = null;
    // Staff acknowledgement is control feedback too: it may be spoken and
    // displayed, but must not replace the current screen's replay source.
    const isControlFeedback = isPreview || action === "CALL_STAFF";
    currentTTSCategory = isControlFeedback ? "CONTROL_FEEDBACK" : "CONVERSATION";
    renderTTSPlaybackStatus();
    try {
      if (action === "REPEAT") {
        const currentSpeedLevel = ttsState.ttsLevel;
        if (lastReplayableMessage && lastReplayableMessage.tts_level === currentSpeedLevel
            && lastReplayableMessage.response_text === orderState.lastResponse) {
          const hasCachedAudio = Boolean(
            lastReplayableMessage.tts_audio_base64 ||
            lastReplayableMessage.tts_segments?.some((s) => Boolean(s.tts_audio_base64))
          );
          if (hasCachedAudio) {
            console.info("[TTS Replay] Reusing cached audio at level", currentSpeedLevel);
            if (typeof signal?.aborted === "boolean" && signal.aborted) return;
            renderAccessibilityControls();
            await presentSystemMessage({
              ...lastReplayableMessage,
              tts_level: currentSpeedLevel,
            }, {
              remember: false,
              isControlFeedback: false,
              resumeListeningAfterPlayback,
              generation,
            });
            return;
          }
        }

        console.info("[TTS Replay] Re-synthesizing at speed level", currentSpeedLevel);
        const replaySource = lastReplayableMessage ? {
          message_id: lastReplayableMessage.message_id,
          response_text: lastReplayableMessage.response_text,
        } : null;
        const data = await callApi("/api/accessibility", {
          json: { action: "REPEAT", level: currentSpeedLevel, replay_source: replaySource },
          signal,
        });
        if (!isCurrentInteraction(generation) || signal !== repeatRequestController?.signal) return;
        // Fixed system messages have one immutable canonical text. Dynamic
        // order results intentionally realize a different Level 2 canonical
        // text from the same semantic replay source, so only enforce text
        // equality for a named fixed system message.
        if (replaySource?.message_id && data.response_text !== replaySource.response_text) {
          console.error("[TTS Replay] rejected non-canonical replay response", {
            expected: replaySource.response_text, actual: data.response_text,
          });
          return;
        }
        if (typeof data.tts_level === "number") ttsState.ttsLevel = data.tts_level;
        renderAccessibilityControls();
        await presentSystemMessage(data, {
          remember: true,
          isControlFeedback: false,
          resumeListeningAfterPlayback,
          generation,
        });
        return;
      }

      const data = await callApi("/api/accessibility", { json: { action }, signal });
      if (!isCurrentInteraction(generation) || (action === "REPEAT" && signal !== repeatRequestController?.signal)) return;
      if (typeof data.tts_level === "number") ttsState.ttsLevel = data.tts_level;
      renderAccessibilityControls();
      if (isPreview) {
        await presentSystemMessage(data, {
          speak: true,
          remember: false,
          isControlFeedback: true,
          updateResponseBar: false,
          generation,
        });
        return;
      }
      await presentSystemMessage(data, {
        remember: !isControlFeedback,
        isControlFeedback,
        resumeListeningAfterPlayback,
        generation,
      });
    } catch (err) {
      if (err && err.name === "AbortError") return;
      console.warn("접근성 음성 안내를 재생하지 못했습니다.", err);
    } finally { if (action === "REPEAT" && repeatRequestController?.signal === signal) repeatRequestController = null; }
  }

  async function playTTSFromResponse(data, { replayPrevious = false, inputContext = "ORDER", isControlFeedback = false, resumeListeningAfterPlayback = false, generation = interactionGeneration } = {}) {
    if (!isCurrentInteraction(generation)) return false;
    currentTTSCategory = isControlFeedback ? "CONTROL_FEEDBACK" : "CONVERSATION";
    renderTTSPlaybackStatus();
    if (typeof data.tts_audio_base64 === "string" && data.tts_audio_base64) {
      pendingSystemPromptListening = (resumeListeningAfterPlayback || (!isControlFeedback && data.response_required === true && data.next_listening_mode === "SYSTEM_PROMPTED"))
        ? { screen: uiState.screen, inputContext }
        : null;
      console.info("[TTS] play requested", { audioBase64Length: data.tts_audio_base64.length });
      const played = await ttsPlayer.loadAndPlay(data.tts_audio_base64);
      if (!isCurrentInteraction(generation)) return false;
      if (!isControlFeedback) ttsState.hasAudio = played;
      renderAccessibilityControls();
      return played;
    }
    if (replayPrevious) {
      pendingSystemPromptListening = null;
      return ttsPlayer.replay();
    }
    pendingSystemPromptListening = null;
    ttsState.status = "idle";
    ttsState.error = null;
    ttsState.hasAudio = false;
    ttsState.available = false;
    renderTTSPlaybackStatus();
    renderAccessibilityControls();
    return false;
  }

  async function confirmOrder({ present = false } = {}) {
    const result = await sendCommands(
      [{ intent: "CONFIRM_ORDER", target_item_id: null, category_id: null, quantity: null, temperature: null, query_tags: null, detail_fields: null, options: null, fulfillment_type: null }],
      { present },
    );
    return Boolean(result && result.success && result.cart && result.cart.confirmed);
  }

  function beginNewOrderSession() {
    orderSessionGeneration += 1;
    lastAppliedCartMutationSequence = 0;
    pendingCartMutations.clear();
    activeTTSStreamId += 1;
    interactionGeneration += 1;
    pendingSystemPromptListening = null;
    clearCompleteAutoHomeTimer();
    deactivateVoiceInput();
    ttsPlayer.dispose();
    interactionMode = "VOICE";
    document.getElementById("homeConfirmDialog").hidden = true;
    if (staffCallCooldownTimer !== null) {
      clearTimeout(staffCallCooldownTimer);
      staffCallCooldownTimer = null;
    }
    document.getElementById("btnGlobalStaff").disabled = false;
    document.getElementById("btnCallStaffWelcome").disabled = false;
    document.querySelector("#btnGlobalStaff span").textContent = "직원 호출";
    document.getElementById("btnCallStaffWelcome").textContent = "직원 호출";

    // 1. Immediately & synchronously reset local adapter and local frontend state
    if (globalThis.MalloApi?.beginNewLocalSession) {
      globalThis.MalloApi.beginNewLocalSession();
    } else {
      globalThis.MalloApi?.resetLocalTouchState?.();
    }
    orderState.items = [];
    orderState.totalPrice = 0;
    orderState.orderNumber = generateOrderNumber();
    orderState.status = "empty";
    orderState.fulfillmentType = null;
    orderState.confirmed = false;
    orderState.paymentMethod = null;
    orderState.waitingTime = null;
    const paymentFulfillmentBadge = document.getElementById("paymentFulfillmentBadge");
    paymentFulfillmentBadge.hidden = true;
    paymentFulfillmentBadge.textContent = "";
    orderState.lastResponse = "어서오세요. 말로 카페입니다.";
    sttState.transcript = "";
    sttState.confidence = null;
    sttState.status = "idle";
    sttState.error = null;
    sttState.isListening = false;
    ttsState.status = "idle";
    ttsState.rate = 1;
    ttsState.currentText = "";
    ttsState.error = null;
    ttsState.hasAudio = false;
    ttsState.available = true;
    ttsState.ttsLevel = 0;
    lastReplayableMessage = null;
    serviceModeFlow.reset();
    const receiptButton = document.getElementById("btnReceipt");
    receiptRequestInFlight = false;
    if (receiptButton) {
      receiptButton.disabled = false;
      receiptButton.textContent = "영수증 출력";
    }
    setVoiceState("IDLE");
    renderResponseBars(orderState.lastResponse);

    // The next genuine TTS/mic recovery owns reset -> handoff. No health
    // check or remote reset is allowed to delay WELCOME/SERVICE_MODE UI.
    sessionResetRequest = Promise.resolve();
  }

  async function resetSession() {
    beginNewOrderSession();
    await sessionResetRequest;
  }

  /* ======================================================================
     Screen-specific refreshers
     ====================================================================== */
  function refreshConfirmScreen() {
    renderCartScreen();
    const el = document.getElementById("confirmResponseText");
    if (el && orderState.lastResponse) {
      el.textContent = orderState.lastResponse;
    }
  }

  function refreshOptionChangeScreen() {
    renderOrderSummaryCard(document.getElementById("currentOrderDisplay"), getCart());
  }

  function refreshCompleteScreen() {
    document.getElementById("completeOrderNum").textContent = orderState.orderNumber;
  }

  function refreshPaymentScreen() {
    document.querySelectorAll(".payment-method-item").forEach((btn) => {
      btn.classList.remove("selected");
      if (typeof btn.blur === "function") btn.blur();
    });
    document.getElementById("paymentTotalPrice").textContent = formatPrice(orderState.totalPrice);
  }

  /* ======================================================================
     Listening flow (microphone)
     ====================================================================== */
  let mediaRecorder = null;
  let recordedChunks = [];
  let currentInputContext = "ORDER";
  let discardNextRecording = false;
  let recordingStopTimer = null;
  let voiceLifecycleEpoch = 0;
  let activeMediaStream = null;
  let microphoneMonitor = null;

  function stopMicrophoneMonitor() {
    if (microphoneMonitor) microphoneMonitor.stop();
    microphoneMonitor = null;
  }

  function stopActiveMediaStream() {
    if (activeMediaStream) {
      activeMediaStream.getTracks().forEach((track) => track.stop());
      logAudioTimeline("microphone-tracks-stopped", {
        tracks: audioTrackStates(activeMediaStream),
      });
    }
    activeMediaStream = null;
  }

  function deactivateVoiceInput() {
    voiceLifecycleEpoch += 1;
    pendingSystemPromptListening = null;
    if (recordingStopTimer !== null) {
      clearTimeout(recordingStopTimer);
      recordingStopTimer = null;
    }
    if (mediaRecorder && mediaRecorder.state === "recording") {
      discardNextRecording = true;
      mediaRecorder.stop();
    }
    stopMicrophoneMonitor();
    stopActiveMediaStream();
    logAudioTimeline("microphone-deactivated");
    sttState.status = "idle";
    sttState.isListening = false;
    setVoiceState("IDLE");
    renderResponseBars(orderState.lastResponse, { remember: false });
  }

  function silenceMicrophoneForTTS() {
    voiceLifecycleEpoch += 1;
    if (recordingStopTimer !== null) {
      clearTimeout(recordingStopTimer);
      recordingStopTimer = null;
    }
    if (mediaRecorder && mediaRecorder.state === "recording") {
      discardNextRecording = true;
      mediaRecorder.stop();
    }
    stopMicrophoneMonitor();
    stopActiveMediaStream();
    logAudioTimeline("tts-playback-microphone-stopped");
    sttState.status = "idle";
    sttState.isListening = false;
    setVoiceState("IDLE");
  }

  function microphoneErrorMessage(error, stage) {
    if (error && (error.name === "NotAllowedError" || error.name === "SecurityError")) {
      return "마이크 권한이 필요합니다. 브라우저 설정에서 마이크를 허용해 주세요.";
    }
    if (error && error.name === "NotFoundError") {
      return "사용할 수 있는 마이크를 찾지 못했습니다.";
    }
    if (error && error.name === "NotReadableError") {
      return "마이크를 사용할 수 없습니다. 다른 앱에서 사용 중인지 확인해 주세요.";
    }
    if (stage === "media-recorder") {
      return "브라우저의 녹음 기능을 시작하지 못했습니다. 다시 시도해 주세요.";
    }
    return "마이크를 시작하지 못했습니다. 다시 시도해 주세요.";
  }

  function reportMicrophoneError(error, stage) {
    console.error("Microphone initialization failed", {
      stage,
      name: error && error.name ? error.name : "Error",
      message: error && error.message ? error.message : String(error),
    }, error);
  }

  async function startListening(inputContext = "ORDER", listeningMode = "USER_INITIATED_FALLBACK") {
    if (!isVoiceAllowed()) return;
    if (globalThis.MalloApi?.isLocalTouchMode || globalThis.MalloApi?.adapterMode === "LOCAL_TOUCH") {
      if (listeningMode === "SYSTEM_PROMPTED") {
        // Do not retry recovery automatically after the preceding TTS failed.
        setVoiceState("IDLE");
        return;
      }
      const recovered = await tryRecoverRemoteSession(uiState.screen);
      if (recovered) {
        return startListening(inputContext, listeningMode);
      }
      orderState.lastResponse = "지금은 음성 주문을 사용할 수 없습니다. 화면을 눌러 주문해 주세요.";
      renderResponseBars(orderState.lastResponse);
      setVoiceState("IDLE");
      return;
    }
    if (listeningMode !== "SYSTEM_PROMPTED") {
      beginUserInteraction();
      enterVoiceMode();
    }
    const interactionEpoch = ++voiceLifecycleEpoch;
    const recordingId = ++nextRecordingId;
    activeRecordingId = recordingId;
    discardNextRecording = false;
    currentInputContext = inputContext;
    sttState.listeningMode = listeningMode;
    sttState.transcript = "";
    transcriptRecordingId = null;
    logAudioTimeline("recording-started", { recordingId });
    sttState.status = "requesting_permission";
    setVoiceState("PROCESSING");
    renderResponseBars("음성 인식을 준비하고 있습니다...", { remember: false });
    let failureStage = "get-user-media";
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: false },
      });
      if (interactionEpoch !== voiceLifecycleEpoch || !isVoiceAllowed()) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      activeMediaStream = stream;
      logAudioTimeline("microphone-stream-created", {
        tracks: audioTrackStates(stream),
      });
      sttState.status = "listening";
      sttState.isListening = true;
      setVoiceState("LISTENING");
      recordedChunks = [];
      try {
        failureStage = "media-recorder";
        mediaRecorder = new MediaRecorder(stream);
      } catch (err) {
        stream.getTracks().forEach((t) => t.stop());
        if (activeMediaStream === stream) activeMediaStream = null;
        throw err;
      }
      failureStage = "audio-monitor";
      microphoneMonitor = new MicrophoneInputMonitor({
        onSpeechEnd: () => {
          logAudioTimeline("vad-speech-end");
          if (mediaRecorder && mediaRecorder.state === "recording") mediaRecorder.stop();
        },
      });
      if (microphoneMonitor.start(stream, document.querySelectorAll("#waveform .bar")) !== true) {
        throw new Error("Web Audio microphone monitor is unavailable");
      }
      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) recordedChunks.push(e.data);
      };
      mediaRecorder.onstop = async () => {
        if (recordingStopTimer !== null) {
          clearTimeout(recordingStopTimer);
          recordingStopTimer = null;
        }
        const speechDetected = Boolean(microphoneMonitor && microphoneMonitor.hasDetectedSpeech);
        sttState.status = "processing";
        sttState.isListening = false;
        stopMicrophoneMonitor();
        stream.getTracks().forEach((t) => t.stop());
        logAudioTimeline("microphone-tracks-stopped", {
          tracks: audioTrackStates(stream),
        });
        if (activeMediaStream === stream) activeMediaStream = null;
        if (discardNextRecording || interactionEpoch !== voiceLifecycleEpoch || !isVoiceAllowed()) {
          discardNextRecording = false;
          renderResponseBars(orderState.lastResponse, { remember: false });
          return;
        }
        if (!speechDetected) {
          sttState.status = "idle";
          setVoiceState("IDLE");
          renderResponseBars(orderState.lastResponse, { remember: false });
          return;
        }
        const blob = new Blob(recordedChunks, { type: "audio/webm" });
        await processUtterance(blob, inputContext, interactionEpoch, recordingId);
      };
      mediaRecorder.start();
      recordingStopTimer = setTimeout(() => {
        recordingStopTimer = null;
        if (mediaRecorder && mediaRecorder.state === "recording") mediaRecorder.stop();
      }, 10000);
    } catch (err) {
      stopMicrophoneMonitor();
      stopActiveMediaStream();
      if (interactionEpoch !== voiceLifecycleEpoch || !isVoiceAllowed()) return;
      reportMicrophoneError(err, failureStage);
      const userMessage = microphoneErrorMessage(err, failureStage);
      sttState.status = "error";
      sttState.error = err.message;
      sttState.isListening = false;
      if (inputContext === "OPTION_CHANGE") {
        setVoiceState("ERROR", userMessage);
        renderResponseBars(`${userMessage} 아래 텍스트 입력으로 바꿀 내용을 알려주세요.`);
        refreshOptionChangeScreen();
      } else {
        setVoiceState("ERROR", userMessage);
        renderResponseBars(`${userMessage} 화면에서 메뉴를 누르거나 다시 말씀해 주세요.`);
      }
    }
  }

  async function processUtterance(blob, inputContext = "ORDER", requestEpoch = voiceLifecycleEpoch, recordingId = activeRecordingId) {
    const generation = interactionGeneration;
    sttState.status = "processing";
    setVoiceState("PROCESSING");
    const cartBefore = JSON.stringify(getCart());
    const result = await sendAudio(blob, requestEpoch, recordingId);
    if (!result || !isVoiceAllowed()) return;
    if (result.ui_action) return;
    sttState.status = "success";
    await afterUtterance(result, inputContext, cartBefore !== JSON.stringify(getCart()), { voice: true });
    if (!isCurrentInteraction(generation)) return;
    startSystemPresentation(result, { inputContext, generation });
  }

  async function processUtteranceText(text, inputContext = "ORDER", { source = "voice" } = {}) {
    if (!isVoiceAllowed()) return;
    beginUserInteraction();
    const isVoice = source === "voice";
    if (isVoice) {
      lastInputMode = "VOICE";
      interactionMode = "VOICE";
    } else {
      lastInputMode = "TOUCH";
      interactionMode = "TOUCH";
    }
    const requestEpoch = ++voiceLifecycleEpoch;
    sttState.status = isVoice ? "processing" : "idle";
    sttState.transcript = isVoice ? text : "";
    if (isVoice) {
      setVoiceState("PROCESSING");
    } else {
      setVoiceState("IDLE");
    }

    const isHomeConfirmOpen = !document.getElementById("homeConfirmDialog").hidden;
    const screenForRouting = isHomeConfirmOpen ? "HOME_CONFIRM" : uiState.screen;

      const routed = MalloUICommandRouter.route(screenForRouting, text);
      const command = routed && ["GO_HOME", "CALL_STAFF", "REPEAT", "SPEED_NORMAL", "SPEED_SLOW", "SPEED_VERY_SLOW", "CYCLE_SPEED"].includes(routed.action) ? routed : null;
    if (command) {
      await executeUICommand(command.action, { source });
      return { success: true, ui_action: command.action };
    }

    const cartBefore = JSON.stringify(getCart());
    const generation = interactionGeneration;
    const result = await sendUtterance(text, requestEpoch, { source, present: false });
    if (isVoice) setVoiceState("IDLE");
    if (!result || !isVoiceAllowed()) return;
    sttState.status = isVoice ? "success" : "idle";
    await afterUtterance(result, inputContext, cartBefore !== JSON.stringify(getCart()), { voice: isVoice });
    if (!isCurrentInteraction(generation)) return;
    startSystemPresentation(result, { inputContext, generation });
    return result;
  }

  async function afterUtterance(result, inputContext = "ORDER", cartChanged = false, { voice = false } = {}) {
    if (hasSuccessfulVoiceIntent(result, "RESET_ORDER")) {
      await applyVoiceCommandNavigation(result);
      return;
    }
    if (voice && await applyVoiceCommandNavigation(result)) {
      return;
    }
    if (inputContext === "OPTION_CHANGE") {
      const nextScreen = optionChangeFlow.finish(result);
      goToScreen(nextScreen);
      setVoiceState("IDLE");
      if (nextScreen === "ORDER_REVIEW") {
        refreshConfirmScreen();
      } else {
        refreshOptionChangeScreen();
      }
      sttState.status = "idle";
      return;
    }
    orderState.status = orderState.items.length > 0 ? "building" : "empty";
    setVoiceState("IDLE");
    sttState.status = "idle";
  }

  function hasSuccessfulVoiceIntent(result, intent) {
    return result?.success === true
      && Array.isArray(result.order_commands)
      && result.order_commands.some((command) => command.intent === intent);
  }

  function successfulVoiceMenuTab(result) {
    const command = result?.success === true && Array.isArray(result.order_commands)
      ? result.order_commands.find((item) => item.intent === "QUERY_MENU")
      : null;
    if (!(command
      && command.target_item_id == null
      && command.query_tags == null
      && command.detail_fields == null)) return null;
    return command.category_id == null ? "all" : command.category_id;
  }

  async function applyVoiceCommandNavigation(result) {
    // The /api/audio/interpret OrderCommand[] is authoritative; raw STT text
    // is intentionally not inspected on the client.
    if (hasSuccessfulVoiceIntent(result, "RESET_ORDER")) {
      serviceModeFlow.reset();
      orderState.status = "empty";
      orderState.fulfillmentType = null;
      orderState.confirmed = false;
      goToScreen("SERVICE_MODE");
      renderResponseBars(result.response_text);
      return true;
    }
    if (hasSuccessfulVoiceIntent(result, "CONFIRM_ORDER") && result.cart?.confirmed === true) {
      await openPayment({ announce: false });
      return true;
    }
    if (hasSuccessfulVoiceIntent(result, "SET_FULFILLMENT")
        && uiState.screen === "SERVICE_MODE"
        && result.cart?.fulfillment_type) {
      return completeFulfillmentSelection(result, result.cart.fulfillment_type, { announce: false });
    }
    if (hasSuccessfulVoiceIntent(result, "QUERY_CART")) {
      await openOrderReview({ announce: false, preserveResponse: true });
      return true;
    }
    const menuTab = successfulVoiceMenuTab(result);
    if (menuTab !== null) {
      if (uiState.screen !== "ORDER") {
        goToScreen("ORDER");
        refreshOrderScreen();
      }
      renderTouchMenu(menuTab);
      return true;
    }
    const paymentCommand = result?.success === true && Array.isArray(result.order_commands)
      ? result.order_commands.find((command) => command.intent === "SELECT_PAYMENT_METHOD")
      : null;
    if (paymentCommand && uiState.screen === "PAYMENT") {
      await selectPaymentMethod(paymentCommand.target_item_id, { announce: false });
      return true;
    }
    return false;
  }

  /* ======================================================================
     Event bindings
     ====================================================================== */

  // Keep this as the first statement of trusted click handlers. Do not await
  // it: browser activation is consumed by the synchronous play() call inside
  // the controller, while its result is diagnostics only.
  function unlockTTSFromTrustedGesture(source) {
    const unlock = ttsPlayer.unlockFromUserGesture?.();
    Promise.resolve(unlock).then((success) => {
      console.debug("[Mallo TTS] trusted-gesture unlock", { source, success: Boolean(success) });
    });
  }

  /* --- WELCOME screen --- */
  document.getElementById("btnStartOrder").addEventListener("click", async () => {
    unlockTTSFromTrustedGesture("start-order");
    beginUserInteraction();
    beginNewOrderSession();
    goToScreen(serviceModeFlow.start());
    renderResponseBars("어떻게 이용하시겠어요? 매장 이용 또는 포장을 선택해 주세요.");
    startSystemMessage("SERVICE_MODE").catch(() => {
      renderResponseBars("매장 이용 또는 포장을 선택해 주세요.");
    });
  });

  async function selectFulfillment(fulfillmentType) {
    const generation = interactionGeneration;
    const payload = serviceModeFlow.selectionPayload(fulfillmentType);
    if (!payload) return;
    try {
      const data = await sendCommands([{ intent: "SET_FULFILLMENT", target_item_id: null, category_id: null, quantity: null, temperature: null, query_tags: null, detail_fields: null, options: null, fulfillment_type: fulfillmentType }], { present: false });
      if (!data || !isCurrentInteraction(generation)) return;
      await completeFulfillmentSelection(data, fulfillmentType, { generation });
    } catch (error) {
      document.getElementById("serviceModeResponseText").textContent = "선택을 저장하지 못했어요. 잠시 후 다시 선택해 주세요.";
      goToScreen("SERVICE_MODE");
    }
  }

  async function completeFulfillmentSelection(data, fulfillmentType, { announce = true, generation = interactionGeneration } = {}) {
    const response = document.getElementById("serviceModeResponseText");
    const nextScreen = serviceModeFlow.finish(data, fulfillmentType);
    if (nextScreen !== "ORDER") {
      response.textContent = data.response_text || "선택을 저장하지 못했어요. 다시 선택해 주세요.";
      goToScreen("SERVICE_MODE");
      return false;
    }
    orderState.items = data.cart.items || [];
    orderState.totalPrice = data.cart.total_price || 0;
    orderState.fulfillmentType = data.cart.fulfillment_type;
    goToScreen("ORDER");
    refreshOrderScreen();
    if (!announce) return true;
    if (!isCurrentInteraction(generation)) return false;
    startSystemMessage("ORDER", { inputContext: "ORDER" });
    return true;
  }

  document.getElementById("btnDineIn").addEventListener("click", () => {
    enterTouchMode();
    selectFulfillment("dine_in");
  });

  document.getElementById("btnTakeout").addEventListener("click", () => {
    enterTouchMode();
    selectFulfillment("takeout");
  });

  document.getElementById("btnCallStaffWelcome").addEventListener("click", async () => {
    await callStaff();
  });

  /* --- Global Footer Central Mic + shared voice overlay --- */
  const globalMicBtn = document.getElementById("btnGlobalMic");
  if (globalMicBtn) {
    globalMicBtn.addEventListener("click", () => {
      unlockTTSFromTrustedGesture("global-mic");
      ttsPlayer.stop();
      enterVoiceMode();
      lastInputMode = "VOICE";
      const context = uiState.screen === "OPTION_CHANGE" ? "OPTION_CHANGE" : "ORDER";
      startListening(context, "USER_INITIATED_FALLBACK");
    });
  }

  document.getElementById("btnMicActive").addEventListener("click", () => {
    if (mediaRecorder && mediaRecorder.state === "recording") {
      mediaRecorder.stop();
    }
  });

  document.getElementById("btnVoiceDismiss").addEventListener("click", () => {
    enterTouchMode();
    deactivateVoiceInput();
    setVoiceState("IDLE");
    renderResponseBars(orderState.lastResponse, { remember: false });
  });

  document.getElementById("touchMenuGrid").addEventListener("click", (event) => {
    const card = event.target.closest(".touch-menu-card");
    if (!card) return;
    enterTouchMode();
    ttsPlayer.stop();
    const item = MalloMenuMetadata.get(card.dataset.menuId);
    showTouchMenuSelection(card.dataset.menuId);
  });

  document.getElementById("clarificationActions").addEventListener("click", (event) => {
    const temperatureChoice = event.target.closest(".touch-temperature-choice");
    if (temperatureChoice && touchMenuSelection) {
      enterTouchMode();
      touchMenuSelection.temperature = temperatureChoice.dataset.temperature;
      renderTouchMenuSelection();
      return;
    }
    const quantityButton = event.target.closest("[data-touch-menu-quantity]");
    if (quantityButton && touchMenuSelection) {
      const delta = quantityButton.dataset.touchMenuQuantity === "increase" ? 1 : -1;
      touchMenuSelection.quantity = Math.min(5, Math.max(1, touchMenuSelection.quantity + delta));
      renderTouchMenuSelection();
      return;
    }
    if (event.target.closest(".touch-menu-add") && touchMenuSelection) {
      if (touchTemperatureOptions(MalloMenuMetadata.get(touchMenuSelection.menuId)).length > 1 && !touchMenuSelection.temperature) return;
      enterTouchMode();
      addTouchMenuItem(touchMenuSelection);
      return;
    }
    if (event.target.closest(".touch-temperature-cancel")) {
      hideTouchMenuSelection();
      renderTouchMenu(activeTouchMenuCategory);
    }
  });

  document.getElementById("touchMenuCategories").addEventListener("click", (event) => {
    const category = event.target.closest(".touch-menu-category");
    if (!category) return;
    enterTouchMode();
    renderTouchMenu(category.dataset.category);
  });

  async function openOrderReview({ announce = true, preserveResponse = false } = {}) {
    const generation = interactionGeneration;
    if (!hasCartItems() && !hasPendingCartMutation()) {
      if (announce) presentEmptyCartReviewGuidance();
      return;
    }
    goToScreen("ORDER_REVIEW");
    refreshConfirmScreen();
    if (!preserveResponse) renderResponseBars("주문 내용을 확인해 주세요.");
    if (announce && isCurrentInteraction(generation)) {
      startSystemMessage("ORDER_REVIEW");
    }
  }

  document.getElementById("btnViewCart").addEventListener("click", () => {
    enterTouchMode({ preservePendingCartMutation: hasPendingCartMutation() });
    openOrderReview();
  });

  /* --- ORDER_REVIEW screen --- */

  async function openPayment({ announce = true } = {}) {
    const generation = interactionGeneration;
    // Payment needs an authoritative cart, but it never needs to wait for
    // synthesis or playback from the mutation that produced that cart.
    if (!(await waitForPendingCartMutations())) return;
    if (!hasCartItems()) {
      presentPaymentReadinessFailure(
        "PAYMENT_EMPTY_CART", "장바구니가 비어 있습니다. 메뉴를 먼저 선택해 주세요.",
      );
      refreshConfirmScreen();
      return;
    }
    if (!orderState.fulfillmentType) {
      presentPaymentReadinessFailure(
        "PAYMENT_FULFILLMENT_REQUIRED", "매장 이용 또는 포장을 먼저 선택해 주세요.",
      );
      refreshConfirmScreen();
      return;
    }
    if (!orderState.confirmed && !(await confirmOrder())) {
      if (!isCurrentInteraction(generation)) return;
      presentPaymentReadinessFailure(
        "PAYMENT_CONFIRMATION_REQUIRED", "주문을 먼저 확정해 주세요.",
      );
      return;
    }
    if (!isCurrentInteraction(generation)) return;
    prepareForPayment({ stopTTS: announce });
    orderState.status = "payment_pending";
    goToScreen("PAYMENT");
    refreshPaymentScreen();
    if (announce) {
      renderResponseBars("결제 방법을 선택해 주세요.");
      startSystemMessage("PAYMENT");
    }
  }

  document.getElementById("btnConfirmYes").addEventListener("click", () => {
    enterTouchMode();
    openPayment();
  });

  async function editOrder() {
    const generation = interactionGeneration;
    goToScreen("ORDER");
    refreshOrderScreen();
    renderResponseBars("원하시는 메뉴를 말씀해 주세요.");
    if (!isCurrentInteraction(generation)) return;
    startSystemMessage("ORDER", { inputContext: "ORDER" });
  }

  document.getElementById("btnConfirmRetry").addEventListener("click", () => {
    enterTouchMode();
    editOrder();
  });

  function startOptionChangeFlow(item) {
    optionChangeFlow.start(item);
    renderOptionChangeItem(item);
    goToScreen("OPTION_CHANGE");
    refreshOptionChangeScreen();
    renderResponseBars("바꾸고 싶은 내용을 편하게 말씀해주세요.");
  }

  document.getElementById("confirmItems").addEventListener("click", (event) => {
    const itemEl = event.target.closest(".cart-item");
    if (!itemEl) return;
    const menuId = itemEl.dataset.menuId;
    const temp = itemEl.dataset.temperature || null;
    const item = (menuId
      ? orderState.items.find((i) => i.menu_id === menuId && (temp == null || (i.temperature || null) === temp))
      : null) || orderState.items[parseInt(itemEl.dataset.index, 10)];
    if (!item) return;
    const quantityButton = event.target.closest("[data-cart-quantity]");
    if (quantityButton) {
      enterTouchMode();
      if (quantityButton.dataset.cartQuantity === "decrease" && item.quantity > 1) {
        updateCartQuantity(item, item.quantity - 1);
      } else if (quantityButton.dataset.cartQuantity === "increase") {
        updateCartQuantity(item, item.quantity + 1);
      }
      return;
    }
    const removeButton = event.target.closest("[data-cart-remove]");
    if (removeButton) {
      enterTouchMode();
      updateCartRemove(item);
      return;
    }
    const temperatureButton = event.target.closest("[data-cart-temperature]");
    if (temperatureButton) {
      enterTouchMode();
      updateCartTemperature(item, temperatureButton.dataset.cartTemperature);
      return;
    }
    enterTouchMode();
    startOptionChangeFlow(item);
  });

  /* --- OPTION_CHANGE screen --- */
  document.getElementById("btnOptionSpeak").addEventListener("click", () => {
    unlockTTSFromTrustedGesture("option-mic");
    ttsPlayer.stop();
    enterVoiceMode();
    startListening("OPTION_CHANGE");
  });

  document.getElementById("btnSendOption").addEventListener("click", () => {
    const input = document.getElementById("textInputOption");
    const val = input.value;
    input.value = "";
    processUtteranceText(val, "OPTION_CHANGE");
  });

  document.getElementById("textInputOption").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const input = document.getElementById("textInputOption");
      const val = input.value;
      input.value = "";
      processUtteranceText(val, "OPTION_CHANGE");
    }
  });

  document.getElementById("btnCancelOption").addEventListener("click", async () => {
    enterTouchMode();
    goToScreen(optionChangeFlow.cancel());
    refreshConfirmScreen();
    renderResponseBars("주문 내용을 확인해 주세요.");
    startSystemMessage("ORDER_REVIEW");
  });

  /* --- PAYMENT screen --- */
  async function selectPaymentMethod(method, { announce = true } = {}) {
      const btn = document.querySelector(`.payment-method-item[data-method="${method}"]`);
      if (!btn) return false;
      if (!hasCartItems()) {
        presentPaymentReadinessFailure(
          "PAYMENT_EMPTY_CART", "장바구니가 비어 있습니다. 메뉴를 먼저 선택해 주세요.",
        );
        goToScreen("ORDER_REVIEW");
        refreshConfirmScreen();
        return false;
      }
      if (!orderState.fulfillmentType) {
        presentPaymentReadinessFailure(
          "PAYMENT_FULFILLMENT_REQUIRED", "매장 이용 또는 포장을 먼저 선택해 주세요.",
        );
        return false;
      }
      orderState.paymentMethod = method;
      if (!orderState.confirmed) {
        presentPaymentReadinessFailure(
          "PAYMENT_CONFIRMATION_REQUIRED", "주문을 먼저 확정해 주세요.",
        );
        return false;
      }
      orderState.status = "paid";
      orderState.status = "completed";
      orderState.waitingTime = "5분";
      refreshCompleteScreen();
      goToScreen("COMPLETE");
      if (announce) {
        renderResponseBars("주문이 완료되었습니다.");
        startSystemMessage("COMPLETE");
      }
      return true;
  }

  document.querySelectorAll(".payment-method-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      enterTouchMode();
      selectPaymentMethod(btn.dataset.method);
    });
  });

  document.getElementById("btnPaymentBack").addEventListener("click", async () => {
    enterTouchMode();
    orderState.status = "building";
    goToScreen("ORDER_REVIEW");
    refreshConfirmScreen();
    renderResponseBars("주문 내용을 확인해 주세요.");
    startSystemMessage("ORDER_REVIEW");
  });

  function prepareForPayment({ stopTTS = true } = {}) {
    deactivateVoiceInput();
    if (stopTTS) ttsPlayer.stop();
  }

  document.getElementById("btnGlobalRepeat").addEventListener("click", async () => {
    beginUserInteraction();
    await sendAccessibilityAction("REPEAT");
  });

  document.getElementById("btnGlobalSpeed").addEventListener("click", async () => {
    if (document.getElementById("btnGlobalSpeed").disabled) return;
    beginUserInteraction();
    await sendAccessibilityAction("CYCLE_SPEED");
  });

  document.getElementById("btnGlobalStaff").addEventListener("click", async () => {
    await callStaff();
  });

  async function callStaff() {
    const generation = beginUserInteraction();
    const buttons = [document.getElementById("btnGlobalStaff"), document.getElementById("btnCallStaffWelcome")];
    if (buttons.some((button) => button.disabled)) return;
    buttons.forEach((button) => { button.disabled = true; button.dataset.originalLabel = button.textContent.trim(); });
    document.querySelector("#btnGlobalStaff span").textContent = "직원 호출됨";
    document.getElementById("btnCallStaffWelcome").textContent = "직원 호출됨";
    await sendAccessibilityAction("CALL_STAFF");
    if (!isCurrentInteraction(generation)) return;
    staffCallAnnouncementActive = true;
    clearTimeout(staffCallCooldownTimer);
    staffCallCooldownTimer = setTimeout(() => {
      buttons.forEach((button) => { button.disabled = false; });
      document.querySelector("#btnGlobalStaff span").textContent = "직원 호출";
      document.getElementById("btnCallStaffWelcome").textContent = "직원 호출";
    }, 8000);
  }

  async function returnHome() {
    await resetSession();
    return enterWelcome();
  }

  function enterWelcome() {
    if (welcomeEntryActive) return welcomeEntryInFlight || Promise.resolve();
    goToScreen("WELCOME");
    renderResponseBars("어서오세요. 말로 카페입니다.");
    welcomeEntryActive = true;
    welcomeEntryInFlight = startSystemMessage("WELCOME").catch((error) => {
      // This is a gateway/TTS-generation request failure. Browser autoplay
      // blocking is handled separately by TTSPlaybackController as debug only.
      console.debug("[WELCOME] system message request failed", { name: error?.name, message: error?.message });
    }).finally(() => {
      welcomeEntryInFlight = null;
    });
    return welcomeEntryInFlight;
  }

  async function requestHome({ source = "touch" } = {}) {
    ttsPlayer.dispose();
    if (!hasCartItems()) {
      returnHome();
    } else {
      document.getElementById("homeConfirmDialog").hidden = false;
      if (!globalThis.MalloApi?.isDemoMode) {
        startSystemMessage("HOME_CONFIRM", { inputContext: "ORDER", updateResponseBar: false });
      }
      if (source === "voice" && !globalThis.MalloApi?.isDemoMode) {
        lastInputMode = "VOICE";
        startListening("ORDER", "SYSTEM_PROMPTED");
      }
    }
  }

  async function executeUICommand(action, { source = "touch" } = {}) {
    beginUserInteraction();
    if (source === "voice") lastInputMode = "VOICE";
    const actions = {
      SELECT_DINE_IN: () => {
        return selectFulfillment("dine_in");
      },
      SELECT_TAKEOUT: () => {
        return selectFulfillment("takeout");
      },
      OPEN_REVIEW: openOrderReview,
      EDIT_ORDER: editOrder,
      OPEN_PAYMENT: openPayment,
      PAY_CARD: () => selectPaymentMethod("card"),
      PAY_SAMSUNG: () => selectPaymentMethod("samsung"),
      PAY_KAKAO: () => selectPaymentMethod("kakao"),
      PAY_CASH: () => selectPaymentMethod("cash"),
      GO_HOME: () => requestHome({ source }),
      CALL_STAFF: callStaff,
      REPEAT: () => sendAccessibilityAction("REPEAT"),
      SPEED_NORMAL: () => sendAccessibilityAction("SET_SPEED_0"),
      SPEED_SLOW: () => sendAccessibilityAction("SET_SPEED_1", { resumeListeningAfterPlayback: source === "voice" }),
      SPEED_VERY_SLOW: () => sendAccessibilityAction("SET_SPEED_2", { resumeListeningAfterPlayback: source === "voice" }),
      CYCLE_SPEED: () => sendAccessibilityAction("CYCLE_SPEED"),
      FILTER_COFFEE: () => renderTouchMenu("coffee"),
      FILTER_NON_COFFEE: () => renderTouchMenu("non_coffee"),
      FILTER_TEA: () => renderTouchMenu("tea"),
      FILTER_DESSERT: () => renderTouchMenu("dessert"),
      FILTER_ALL: () => renderTouchMenu("all"),
      CANCEL_HOME: () => {
        document.getElementById("homeConfirmDialog").hidden = true;
      },
      CONFIRM_HOME: async () => {
        document.getElementById("homeConfirmDialog").hidden = true;
        await returnHome();
      },
      CANCEL_OPTION: () => {
        goToScreen("ORDER_REVIEW");
        refreshConfirmScreen();
      },
    };
    if (actions[action]) await actions[action]();
  }

  document.getElementById("btnGlobalHome").addEventListener("click", () => {
    unlockTTSFromTrustedGesture("global-home");
    enterTouchMode();
    requestHome({ source: "touch" });
  });
  document.getElementById("btnCancelHome").addEventListener("click", () => {
    enterTouchMode();
    document.getElementById("homeConfirmDialog").hidden = true;
  });
  document.getElementById("btnConfirmHome").addEventListener("click", async () => {
    unlockTTSFromTrustedGesture("confirm-home");
    enterTouchMode();
    document.getElementById("homeConfirmDialog").hidden = true;
    await returnHome();
  });

  let receiptRequestInFlight = false;
  async function requestReceipt() {
    if (receiptRequestInFlight) return;
    receiptRequestInFlight = true;
    enterTouchMode();
    const btnReceipt = document.getElementById("btnReceipt");
    if (btnReceipt) {
      btnReceipt.disabled = true;
      btnReceipt.textContent = "영수증 출력 중...";
    }
    try {
      const data = await callApi("/api/accessibility", { json: { action: "RECEIPT" } });
      await presentSystemMessage(data, { remember: true, isControlFeedback: false });
    } catch (err) {
      console.warn("영수증 안내 음성을 재생하지 못했습니다.", err);
    } finally {
      if (btnReceipt) {
        btnReceipt.textContent = "영수증 출력됨";
      }
    }
  }

  /* --- COMPLETE screen --- */
  document.getElementById("btnReceipt").addEventListener("click", () => {
    if (receiptRequestInFlight || document.getElementById("btnReceipt").disabled) return;
    requestReceipt();
  });

  document.getElementById("btnHome").addEventListener("click", () => {
    unlockTTSFromTrustedGesture("complete-home");
    enterTouchMode();
    returnHome();
  });

  /* ======================================================================
     Initialize
     ====================================================================== */
  renderTouchMenu();
  (typeof window !== "undefined" ? window : globalThis).addEventListener?.("mallo:adapter-mode", (event) => {
    if (event.detail?.mode === "REMOTE") ttsState.available = true;
    if (event.detail?.mode === "LOCAL_TOUCH") ttsState.available = false;
    renderAccessibilityControls();
  });
  resetSession().then(() => {
    enterWelcome();
  });

  (typeof window !== "undefined" ? window : globalThis).__malloTest__ = {
    get uiState() { return uiState; },
    get orderState() { return orderState; },
    get interactionMode() { return interactionMode; },
    get lastInputMode() { return lastInputMode; },
    get ttsPlayer() { return ttsPlayer; },
    get pendingSystemPromptListening() { return pendingSystemPromptListening; },
    get completeAutoHomeTimer() { return completeAutoHomeTimer; },
    clearCompleteAutoHomeTimer,
    startCompleteAutoHomeTimer,
    setVoiceState,
    executeUICommand,
    processUtteranceText,
    sendUtterance,
    enterTouchMode,
    goToScreen,
    getMessageSegments,
    measureTextLines,
    splitIntoOneLineSemanticSegments,
    truncateToOneLineWithEllipsis,
    finalFitDisplaySegments,
    renderResponseBarsWindow,
    renderResponseBars,
    presentSystemMessage,
    beginNewOrderSession,
    resetSession,
  };
});
