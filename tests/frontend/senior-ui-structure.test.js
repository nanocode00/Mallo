"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { get } = require("../../web/menu-metadata.js");

const webDir = path.resolve(__dirname, "../../web");
const page = fs.readFileSync(path.join(webDir, "index.html"), "utf8");
const script = fs.readFileSync(path.join(webDir, "app.js"), "utf8");
const menuMetadata = fs.readFileSync(path.join(webDir, "menu-metadata.js"), "utf8");
const styles = [
  "styles.css",
  "styles/senior-foundation.css",
  "styles/senior-layout.css",
  "styles/senior-portrait.css",
  "styles/senior-context.css",
  "styles/senior-ux-polish.css",
].map((file) => fs.readFileSync(path.join(webDir, file), "utf8")).join("\n");
const finalStyles = ["styles/senior-context.css", "styles/senior-ux-polish.css"]
  .map((file) => fs.readFileSync(path.join(webDir, file), "utf8")).join("\n");

test("major senior-first screens and shared regions exist", () => {
  for (const id of [
    "screenWelcome",
    "screenServiceMode",
    "screenOrder",
    "screenOrderReview",
    "screenOptionChange",
    "screenPayment",
    "screenComplete",
    "globalA11yControls",
  ]) assert.match(page, new RegExp(`id="${id}"`));
  assert.match(page, /id="voiceOverlay"[^>]*hidden/);
  assert.match(page, /id="contextMenuArea"[^>]*hidden/);
  assert.match(page, /id="clarificationArea"[^>]*hidden/);
});

test("order review keeps the item list before its actions", () => {
  assert.ok(page.indexOf('id="confirmItemsScroll"') < page.indexOf('id="btnConfirmYes"'));
});

test("cart cards keep menu names pure while the review advances to payment", () => {
  assert.match(page, /id="btnConfirmYes">\s*<span class="payment-cta-label">결제할게요<\/span>\s*<span class="payment-fulfillment-badge" id="paymentFulfillmentBadge" hidden><\/span>/);
  assert.match(script, /const fulfillmentLabel = fulfillmentText\(orderState\.fulfillmentType\);[\s\S]*paymentFulfillmentBadge\.hidden = !fulfillmentLabel;[\s\S]*paymentFulfillmentBadge\.textContent = fulfillmentLabel;/);
  assert.match(script, /function beginNewOrderSession\(\)[\s\S]*orderState\.fulfillmentType = null;[\s\S]*paymentFulfillmentBadge\.hidden = true;[\s\S]*paymentFulfillmentBadge\.textContent = "";/);
  assert.match(finalStyles, /\.payment-fulfillment-badge\s*\{[\s\S]*position:\s*absolute/);
  assert.match(script, /const temperatureLabel = item\.temperature === "iced" \? "아이스"/);
  assert.match(script, /temperature-badge temperature-badge--\$\{item\.temperature\}/);
  assert.match(styles, /\.temperature-badge--hot\s*\{\s*background:\s*#fff0e8;\s*color:\s*#c2410c;/);
  assert.match(script, /hasSuccessfulVoiceIntent\(result, "RESET_ORDER"\)[\s\S]*goToScreen\("SERVICE_MODE"\)/);
});

test("cart review uses server commands for large quantity and dual-temperature controls", () => {
  assert.match(script, /function renderCartItems\(items\)[\s\S]*data-cart-quantity="decrease"[\s\S]*data-cart-quantity="increase"/);
  assert.match(script, /item\.quantity <= 1 \? " disabled" : ""/);
  assert.match(script, /temperatureOptions\.length === 2[\s\S]*data-cart-temperature/);
  assert.match(script, /UPDATE_QUANTITY[\s\S]*quantity, temperature: item\.temperature/);
  assert.match(script, /UPDATE_OPTION[\s\S]*quantity: item\.quantity, temperature/);
  assert.match(script, /function refreshCurrentOrderScreen\(\)[\s\S]*uiState\.screen === "ORDER_REVIEW"[\s\S]*refreshConfirmScreen\(\)/);
  assert.match(script, /function commitCartSnapshot\(cart, \{ sessionGeneration, mutationSequence = null \} = \{\}\)[\s\S]*applyCartSnapshot\(cart\)[\s\S]*refreshCurrentOrderScreen\(\)/);
  assert.match(script, /async function sendCommands[\s\S]*commitCartSnapshot\(data\.cart,[\s\S]*if \(!isCurrentInteraction\(generation\)\) return data;[\s\S]*await presentSystemMessage/);
  assert.match(styles, /\.cart-quantity-button,[\s\S]*min-height:\s*4\.8cqh/);
  assert.match(styles, /\.cart-temperature-button--iced\.is-selected\s*\{\s*background:\s*#2563eb/);
  assert.match(styles, /\.cart-temperature-button--hot\.is-selected\s*\{\s*background:\s*#c2410c/);
});

test("touch-menu labels omit temperature prefixes but retain temperature data", () => {
  assert.match(menuMetadata, /americano:[\s\S]*name: "아메리카노"[\s\S]*temperature: "iced"/);
  assert.match(menuMetadata, /cafe_latte:[\s\S]*name: "카페라떼"[\s\S]*temperature: "iced"/);
  assert.match(menuMetadata, /chamomile_tea:[\s\S]*name: "캐모마일티"[\s\S]*temperature: "hot"/);
  assert.doesNotMatch(menuMetadata, /name: "(?:아이스|따뜻한) (?:아메리카노|카페라떼|바닐라라떼|말차라떼|밀크티|캐모마일티)"/);
});

test("all touch menus select quantity before adding, with temperature only for dual-temperature menus", () => {
  assert.deepEqual(get("americano").temperatureOptions, ["hot", "iced"]);
  assert.deepEqual(get("cafe_latte").temperatureOptions, ["hot", "iced"]);
  assert.deepEqual(get("grapefruit_ade").temperatureOptions, ["iced"]);
  assert.match(script, /function showTouchMenuSelection\(menuId\)[\s\S]*quantity: 1/);
  assert.match(script, /needsTemperature \? `\<div class="touch-menu-temperature-controls"/);
  assert.match(script, /data-touch-menu-quantity="decrease"[\s\S]*data-touch-menu-quantity="increase"/);
  assert.match(script, /quantity <= 1 \? " disabled" : ""/);
  assert.match(script, /quantity >= 5 \? " disabled" : ""/);
  assert.match(script, /class="btn-primary touch-menu-add"\$\{needsTemperature && !temperature \? " disabled" : ""\}/);
});

test("voice processing is an overlay state and payment cleanup is wired", () => {
  assert.match(script, /setVoiceState\("PROCESSING"\)/);
  assert.doesNotMatch(script, /goToScreen\("PROCESSING"\)/);
  assert.match(script, /prepareForPayment\(\{ stopTTS: announce \}\)/);
  assert.match(script, /ttsPlayer\.dispose\(\)/);
  assert.match(script, /discardNextRecording = true/);
});

test("order accumulation and explicit review transitions are wired", () => {
  for (const id of ["btnViewCart", "cartItemBadge"])
    assert.match(page, new RegExp(`id="${id}"`));
  assert.doesNotMatch(page, /id="orderMiniCart"/);
  assert.match(script, /orderState\.items\.reduce\(\(sum, item\) => sum \+ \(item\.quantity \|\| 0\), 0\)/);
  assert.match(finalStyles, /\.cart-item-badge\s*\{[\s\S]*font-size:\s*2\.8cqw/);
  assert.match(page, /id="btnGlobalMic"/);
  assert.match(script, /goToScreen\("ORDER"\);\s*refreshOrderScreen/);
  assert.match(script, /btnViewCart[\s\S]*goToScreen\("ORDER_REVIEW"\)/);
  assert.match(script, /async function editOrder\(\)[\s\S]*goToScreen\("ORDER"\)/);
  assert.match(script, /async function openPayment\(\{ announce = true \} = \{\}\)[\s\S]*goToScreen\("PAYMENT"\)/);
  assert.match(script, /btnPaymentBack[\s\S]*goToScreen\("ORDER_REVIEW"\)/);
  assert.doesNotMatch(page, /btnReturnOrder|주문으로 돌아가기/);
});

test("empty cart cannot enter cart, payment, or completion flows", () => {
  assert.match(script, /async function openOrderReview\(\{ announce = true, preserveResponse = false \} = \{\}\) \{\s*const generation = interactionGeneration;\s*if \(!hasCartItems\(\) && !hasPendingCartMutation\(\)\) \{[\s\S]*?return;\s*\}\s*goToScreen\("ORDER_REVIEW"\)/);
  assert.match(script, /async function openPayment\(\{ announce = true \} = \{\}\) \{[\s\S]*if \(!hasCartItems\(\)\)[\s\S]*return;[\s\S]*if \(!orderState\.fulfillmentType\)[\s\S]*return;/);
  assert.match(script, /if \(!orderState\.confirmed && !\(await confirmOrder\(\)\)\) \{[\s\S]*PAYMENT_CONFIRMATION_REQUIRED[\s\S]*return;/);
  assert.match(script, /async function selectPaymentMethod\(method, \{ announce = true \} = \{\}\) \{[\s\S]*if \(!orderState\.confirmed\)[\s\S]*return;/);
  assert.match(script, /매장 이용 또는 포장을 먼저 선택해 주세요\./);
  assert.match(script, /function presentPaymentReadinessFailure\([\s\S]*startSystemMessage\(messageId/);
  assert.match(script, /PAYMENT_EMPTY_CART/);
});

test("only cart items scroll while total and actions remain outside", () => {
  assert.match(page, /id="confirmItemsScroll"[\s\S]*id="confirmItems"/);
  assert.ok(page.indexOf('id="confirmItemsScroll"') < page.indexOf('class="cart-total-row"'));
  assert.ok(page.indexOf('class="cart-total-row"') < page.indexOf('id="btnConfirmYes"'));
  assert.match(styles, /\.screen-confirm\s*\{[^}]*overflow:\s*hidden/);
  assert.match(styles, /\.cart-items-scroll\s*\{[\s\S]*overflow-y:\s*auto/);
  assert.match(styles, /\.cart-items-scroll\s*\{[\s\S]*scrollbar-width:\s*none/);
  assert.match(styles, /\.cart-items-scroll::-webkit-scrollbar\s*\{\s*display:\s*none/);
  assert.doesNotMatch(page, /id="btnConfirmMore"|＋ 더 주문할게요/);
});

test("voice overlay is guarded by screen policy and terminal lifecycle cleanup", () => {
  assert.match(script, /VOICE_ENABLED_SCREENS = new Set\(\["SERVICE_MODE", "ORDER", "ORDER_REVIEW", "OPTION_CHANGE", "PAYMENT"\]\)/);
  assert.match(script, /status !== "IDLE" && !isVoiceAllowed\(\)/);
  assert.match(script, /status === "playing"\) silenceMicrophoneForTTS\(\)/);
  assert.match(script, /function deactivateVoiceInput\(\)[\s\S]*clearTimeout\(recordingStopTimer\)/);
  assert.match(script, /function silenceMicrophoneForTTS\(\)[\s\S]*sttState\.isListening = false;[\s\S]*setVoiceState\("IDLE"\)/);
  assert.match(script, /requestEpoch !== voiceLifecycleEpoch \|\| !isVoiceAllowed\(\)/);
  assert.match(script, /function prepareForPayment\(\{ stopTTS = true \} = \{\}\) \{\s*deactivateVoiceInput\(\);\s*if \(stopTTS\) ttsPlayer\.stop\(\)/);
});

test("stale microphone permissions and recorder failures release acquired tracks", () => {
  assert.match(
    script,
    /const stream = await navigator\.mediaDevices\.getUserMedia\(\{\s*audio: \{ echoCancellation: true, noiseSuppression: true, autoGainControl: false \},\s*\}\);\s*if \(interactionEpoch !== voiceLifecycleEpoch \|\| !isVoiceAllowed\(\)\) \{\s*stream\.getTracks\(\)\.forEach\(\(t\) => t\.stop\(\)\);\s*return;\s*\}/,
  );
  assert.match(
    script,
    /try \{\s*failureStage = "media-recorder";\s*mediaRecorder = new MediaRecorder\(stream\);\s*\} catch \(err\) \{\s*stream\.getTracks\(\)\.forEach\(\(t\) => t\.stop\(\)\);\s*if \(activeMediaStream === stream\) activeMediaStream = null;\s*throw err;\s*\}/,
  );
});

test("screen state and voice state are independent", () => {
  assert.match(script, /screen:\s*"WELCOME"/);
  assert.match(script, /const voiceState = \{/);
  assert.match(script, /IDLE \| LISTENING \| PROCESSING \| ERROR/);
  assert.doesNotMatch(page, /id="screenListening"|id="screenProcessing"/);
});

test("accessibility footer is a 5-button control grid with central mic", () => {
  for (const id of ["btnGlobalRepeat", "btnGlobalSpeed", "btnGlobalStaff", "btnGlobalHome", "btnGlobalMic"]) assert.match(page, new RegExp(`id="${id}"`));
  assert.doesNotMatch(page, /id="btnGlobalDefault"/);
  assert.match(page, /id="ttsSpeedStatus"[^>]*>[\s\S]*기본/);
  assert.match(styles, /\.a11y-control-grid\s*\{[\s\S]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/);
  assert.match(script, /btnGlobalSpeed[\s\S]*CYCLE_SPEED/);
  assert.match(script, /const labels = \["기본", "천천히", "더 천천히"\]/);
  assert.match(script, /controls\.hidden = \["WELCOME", "COMPLETE"\]\.includes\(name\)/);
});

test("every WELCOME entry requests its TTS once, while autoplay blocking stays non-visible", () => {
  const welcomeStart = page.indexOf('id="screenWelcome"'), serviceModeStart = page.indexOf('id="screenServiceMode"');
  const welcomeMarkup = page.slice(welcomeStart, serviceModeStart);
  assert.match(welcomeMarkup, /response-bar[\s\S]*어서오세요\. 말로 카페입니다\./);
  const bootstrap = script.slice(script.lastIndexOf("renderTouchMenu();"));
  assert.match(bootstrap, /resetSession\(\)\.then\(\(\) => \{\s*enterWelcome\(\)/);
  assert.match(script, /function enterWelcome\(\) \{[\s\S]*startSystemMessage\("WELCOME"\)/);
  assert.match(script, /async function returnHome\(\) \{\s*await resetSession\(\);\s*return enterWelcome\(\);/);
  assert.match(script, /if \(welcomeEntryActive\) return welcomeEntryInFlight \|\| Promise\.resolve\(\)/);
  assert.match(script, /if \(name !== "WELCOME"\) welcomeEntryActive = false/);
  assert.match(script, /status === "autoplay-blocked"[\s\S]*console\.debug\("\[TTS\] autoplay blocked by browser policy"/);
  assert.doesNotMatch(script, /status === "autoplay-blocked"[\s\S]{0,250}console\.warn/);
  assert.match(script, /function unlockTTSFromTrustedGesture\(source\)[\s\S]*ttsPlayer\.unlockFromUserGesture\?\.\(\)/);
  for (const id of ["btnStartOrder", "btnGlobalMic", "btnOptionSpeak", "btnGlobalHome", "btnConfirmHome", "btnHome"]) {
    assert.match(script, new RegExp(`${id}[\\s\\S]*unlockTTSFromTrustedGesture`));
  }
  assert.match(script, /ttsPlayer\.dispose\(\);[\s\S]*ttsState\.hasAudio = false/);
});

test("fulfillment success advances with an order prompt instead of storage wording", () => {
  assert.doesNotMatch(page, /id="orderFulfillmentLabel"/);
  assert.match(script, /startSystemMessage\("ORDER", \{ inputContext: "ORDER" \}\)/);
  assert.match(script, /itemCount \? "무엇을 더 주문하시겠어요\?" : "무엇을 주문하시겠어요\?"/);
  assert.doesNotMatch(script, /저장했습니다|저장하고 있어요/);
});

test("TTS playback belongs to system messages and never the voice overlay", () => {
  assert.match(script, /classList\.toggle\("is-tts-playing", isPlaying\)/);
  assert.match(finalStyles, /\.response-bar\.is-tts-playing\s*\{[^}]*border-color:\s*var\(--color-primary\)/);
  assert.match(finalStyles, /\.response-bar\.is-tts-playing \.response-bar-text\s*\{\s*color:\s*var\(--color-primary\)/);
  assert.doesNotMatch(finalStyles, /말로가 (말하고|안내하고) 있어요|\.response-bar\.is-tts-playing::before/);
  assert.doesNotMatch(page, /tts-playback-status|음성 안내를 재생하지 못했어요/);
  assert.doesNotMatch(script, /setVoiceState\("TTS_PLAYING"\)|음성 안내를 재생하지 못했어요/);
});

test("Response Bar preserves explicit display lines and prevents fallback wrapping", () => {
  assert.match(finalStyles, /\.response-bar-text\s*\{[^}]*overflow:\s*hidden\s*!important;[^}]*white-space:\s*pre\s*!important;/);
  assert.match(script, /function truncateToOneLineWithEllipsis\([\s\S]*const ellipsis = "…"/);
});

test("screen transition prompts share the system message presentation path", () => {
  for (const messageId of ["SERVICE_MODE", "ORDER_REVIEW", "PAYMENT", "COMPLETE"]) {
    assert.match(script, new RegExp(`startSystemMessage\\("${messageId}"`));
  }
  assert.match(script, /callApi\("\/api\/system-message"/);
  assert.match(script, /async function presentSystemMessage[\s\S]*renderResponseBars\(orderState\.lastResponse\)[\s\S]*playTTSFromResponse\(data/);
});

test("cart and navigation lifecycles start presentation without awaiting speech completion", () => {
  assert.match(script, /function startSystemPresentation\(data, options = \{\}\)[\s\S]*speechDone\.catch/);
  assert.match(script, /function startSystemMessage\(messageId, options = \{\}\)[\s\S]*request\.catch/);
  assert.match(script, /async function sendCommands[\s\S]*startSystemPresentation\(data, \{ inputContext: "ORDER", generation \}\)/);
  assert.match(script, /async function openPayment[\s\S]*await waitForPendingCartMutations\(\)[\s\S]*goToScreen\("PAYMENT"\)/);
  assert.match(script, /async function waitForPendingCartMutations\(\)[\s\S]*Promise\.allSettled\(pending\)/);
  // Completion remains in the speech pipeline, which owns automatic
  // post-prompt listening through pendingSystemPromptListening.
  assert.match(script, /pendingSystemPromptListening = \(isLast[\s\S]*await ttsPlayer\.waitForCompletion\(\)/);
  assert.match(script, /pending &&[\s\S]*startListening\(pending\.inputContext, "SYSTEM_PROMPTED"\)/);
});

test("transcript UI is owned by the voice overlay only", () => {
  assert.match(page, /id="voiceOverlay"[\s\S]*id="liveTranscript"/);
  assert.doesNotMatch(page, /confirmTranscript|optionTranscript|내가 말한 내용/);
  assert.match(script, /const transcript = document\.getElementById\("liveTranscript"\)/);
  assert.match(script, /sttState\.transcript = typeof stt\.transcript === "string"/);
  assert.match(script, /callApi\("\/api\/audio\/stt"/);
  assert.match(script, /callApi\("\/api\/audio\/interpret"/);
});

test("typography and footer use enlarged container-relative tokens", () => {
  assert.match(finalStyles, /--font-display:\s*5\.6cqw/);
  assert.match(finalStyles, /--font-action:\s*4\.15cqw/);
  assert.match(finalStyles, /--font-body:\s*3\.15cqw/);
  assert.match(finalStyles, /--a11y-footer-height:\s*15\.5cqh/);
  assert.match(styles, /grid-template-rows:\s*var\(--kiosk-header-height\) minmax\(0, 1fr\) auto/);
  assert.match(finalStyles, /\.btn-a11y small\s*\{[^}]*font-size:\s*2\.15cqw/);
});

test("menu metadata uses assets and a safe placeholder fallback", () => {
  assert.equal(get("americano").imagePath, "assets/menu/americano.png");
  assert.equal(get("unknown_menu").imagePath, null);
  assert.match(script, /menu-media-placeholder/);
});

test("senior typography and touch targets are explicit", () => {
  assert.match(styles, /--font-display:\s*48px/);
  assert.match(styles, /min-height:\s*76px/);
});

test("responsive portrait kiosk container uses shared layout tokens and wide primary areas", () => {
  assert.match(styles, /canonical viewport\s*1080 x 1920/i);
  assert.match(styles, /--kiosk-header-height:/);
  assert.match(styles, /--kiosk-content-width:/);
  assert.match(styles, /--kiosk-section-gap:/);
  assert.match(styles, /--touch-target-min:\s*76px/);
  assert.match(page, /class="kiosk-stage"/);
  assert.match(styles, /\.kiosk-shell\s*\{[\s\S]*aspect-ratio:\s*9 \/ 16/);
  assert.match(styles, /container-type:\s*size/);
  assert.match(styles, /\.service-mode-actions[\s\S]*width:\s*min\(92%, 960px\)/);
  assert.match(styles, /\.voice-interaction-area[\s\S]*min-height:\s*35\.4cqh/);
});

test("CSS sizes one container without transform scaling or landscape rearrangement", () => {
  assert.match(styles, /width:\s*min\(100vw, calc\(100dvh \* 9 \/ 16\)\)/);
  assert.match(styles, /height:\s*min\(100dvh, calc\(100vw \* 16 \/ 9\)\)/);
  assert.doesNotMatch(styles, /\.kiosk-shell\s*\{[^}]*transform:/);
  assert.doesNotMatch(script, /fitKioskCanvas|LOGICAL_KIOSK_WIDTH|LOGICAL_KIOSK_HEIGHT/);
  assert.doesNotMatch(styles, /@media \(orientation:\s*landscape\)/);
  assert.match(styles, /\.screen\s*\{[\s\S]*overflow:\s*hidden/);
  assert.doesNotMatch(finalStyles, /\.screen\s*\{[^}]*overflow-y:\s*auto/);
  assert.match(styles, /\.screen-order > \.order-context-card,[\s\S]*overflow-y:\s*auto/);
  assert.match(styles, /\.cart-items-scroll\s*\{[\s\S]*overflow-y:\s*auto/);
  assert.match(styles, /\.screen-payment \.payment-list\s*\{[\s\S]*overflow-y:\s*auto/);
});

test("major kiosk proportions use container-relative units", () => {
  assert.match(styles, /--kiosk-header-height:\s*6\.2cqh/);
  assert.match(finalStyles, /--font-display:\s*5\.6cqw/);
  assert.match(styles, /grid-template-columns:\s*38% minmax\(0, 1fr\) auto/);
  assert.match(styles, /\.global-a11y-controls\s*\{[\s\S]*height:\s*var\(--a11y-footer-height\)/);
});

test("turn metadata gates automatic SYSTEM_PROMPTED listening", () => {
  assert.match(script, /data\.response_required === true[\s\S]*data\.next_listening_mode === "SYSTEM_PROMPTED"/);
  assert.match(script, /status === "completed"[\s\S]*startListening\(pending\.inputContext, "SYSTEM_PROMPTED"\)/);
  assert.doesNotMatch(script, /status === "completed"\)\s*startListening\(/);
});

test("microphone waveform uses the acquired stream and cleanup is shared", () => {
  assert.match(page, /microphone-input-monitor\.js/);
  assert.match(script, /microphoneMonitor\.start\(stream, document\.querySelectorAll\("#waveform \.bar"\)\)/);
  assert.match(script, /function stopMicrophoneMonitor\(\)[\s\S]*microphoneMonitor\.stop\(\)/);
  assert.match(styles, /\.voice-overlay-panel \.waveform \.bar\s*\{[\s\S]*animation:\s*none/);
});

test("voice overlay and order touch fallback follow the polished contract", () => {
  for (const id of ["btnMicActive", "btnVoiceDismiss", "touchMenuGrid"]) assert.match(page, new RegExp(`id="${id}"`));
  assert.match(page, /말하기 끝내기/);
  assert.match(page, /화면으로 조작하기/);
  assert.doesNotMatch(page, /이렇게 들었어요|말씀이 끝나면 마이크를 눌러주세요|id="textInputListening"|id="btnSendListening"/);
  assert.match(script, /speechDetected[\s\S]*if \(!speechDetected\)[\s\S]*return;/);
  assert.match(script, /async function sendCommands\(commands, \{ present = true \} = \{\}\)[\s\S]*callApi\("\/api\/commands"/);
  assert.match(script, /const item = MalloMenuMetadata\.get\(card\.dataset\.menuId\);/);
  assert.match(script, /showTouchMenuSelection\(card\.dataset\.menuId\)/);
  assert.match(script, /function addTouchMenuItem\(\{ menuId, temperature, quantity \}\) \{[\s\S]*sendCommands\(\[\{ intent: "ADD_ITEM", target_item_id: menuId, category_id: null, quantity, temperature/);
  assert.doesNotMatch(script, /processUtteranceText\(card\.dataset\.orderText/);
  assert.match(finalStyles, /\.touch-menu-grid\s*\{[\s\S]*grid-template-columns:\s*repeat\(2/);
  assert.match(finalStyles, /\.touch-menu-grid\s*\{[\s\S]*overflow-y:\s*auto/);
});

test("accessibility speed preview is isolated from conversation message and visual state", () => {
  assert.match(script, /const isPreview = action === "CYCLE_SPEED"/);
  assert.match(script, /const isControlFeedback = isPreview \|\| action === "CALL_STAFF"/);
  assert.match(script, /presentSystemMessage\(data, \{\s*remember: !isControlFeedback,\s*isControlFeedback,\s*resumeListeningAfterPlayback,\s*generation,?\s*\}\)/);
  assert.match(script, /currentTTSCategory = isControlFeedback \? "CONTROL_FEEDBACK" : "CONVERSATION"/);
  assert.match(script, /activeTTSMessageStreamId === activeTTSStreamId/);
  assert.match(script, /function completeTTSMessageStream\(streamId\)/);
  assert.match(script, /const replaySource = lastReplayableMessage \? \{/);
  assert.match(script, /json: \{ action: "REPEAT", level: currentSpeedLevel, replay_source: replaySource \}/);
  assert.match(script, /rejected non-canonical replay response/);
});

test("automatic slowdown notice is speech-only and ordered before the preserved message", () => {
  assert.match(script, /async function presentSystemMessage\(data, options = \{\}\) \{[\s\S]*\} = options;/);
  assert.match(script, /if \(data\.speech_prefix\) \{[\s\S]*renderAccessibilityControls\(\);/);
  assert.match(script, /delete body\.speech_prefix;[\s\S]*await presentSystemMessage\(data\.speech_prefix, \{[\s\S]*remember: false,[\s\S]*isControlFeedback: true,[\s\S]*updateResponseBar: false/);
  assert.match(script, /await presentSystemMessage\(data\.speech_prefix,[\s\S]*return presentSystemMessage\(body, options\);/);
  assert.match(script, /function startSystemPresentation\(data, options = \{\}\) \{[\s\S]*const speechDone = presentSystemMessage\(data, options\);[\s\S]*return speechDone;/);
});

test("ORDER_REVIEW summary fills height and CTA hierarchy is explicit", () => {
  assert.match(finalStyles, /\.screen-confirm \.confirm-summary\s*\{[\s\S]*height:\s*100%/);
  assert.match(finalStyles, /\.screen-confirm \.confirm-actions \.btn-primary\s*\{[\s\S]*min-height:\s*7\.4cqh/);
  assert.match(finalStyles, /\.screen-confirm \.confirm-actions \.btn-secondary\s*\{[\s\S]*min-height:\s*5\.8cqh/);
});

test("PAYMENT screen cards and total are prominent and properly scroll-bounded", () => {
  assert.match(finalStyles, /\.payment-total\s*\{[\s\S]*width:\s*90cqw/);
  assert.match(finalStyles, /\.screen-payment \.payment-method-item\s*\{[\s\S]*min-height:\s*12\.8cqh/);
  assert.match(finalStyles, /\.screen-payment \.payment-list\s*\{[\s\S]*grid-template-columns:\s*repeat\(2/);
  assert.match(finalStyles, /\.payment-card-sub\s*\{[\s\S]*font-size:\s*3\.0cqw[\s\S]*line-height:\s*1\.25/);
  assert.match(finalStyles, /\.screen-payment #btnPaymentBack\s*\{[\s\S]*font-size:\s*3\.4cqw[\s\S]*line-height:\s*1\.25/);
});

test("COMPLETE supporting labels remain below their values while becoming more legible", () => {
  assert.match(finalStyles, /\.complete-order-number\s*\{[\s\S]*font-size:\s*clamp\(14px, 3\.7cqw, 17px\)[\s\S]*line-height:\s*1\.25/);
  assert.match(finalStyles, /\.complete-wait-label\s*\{[\s\S]*font-size:\s*clamp\(13px, 3\.5cqw, 16px\)[\s\S]*line-height:\s*1\.25/);
  assert.match(finalStyles, /\.complete-receipt-hint\s*\{[\s\S]*font-size:\s*clamp\(13px, 3\.3cqw, 15px\)[\s\S]*line-height:\s*1\.35/);
  assert.match(finalStyles, /\.complete-order-num\s*\{[\s\S]*font-size:\s*clamp\(36px, 9\.2cqw, 44px\)/);
  assert.match(finalStyles, /\.complete-wait-time\s*\{[\s\S]*font-size:\s*clamp\(20px, 5\.0cqw, 24px\)/);
});
