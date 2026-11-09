"use strict";

const { test, expect } = require("@playwright/test");

const BASE_URL = process.env.MALLO_BASE_URL || "http://127.0.0.1:8000";

async function expectAboveFooterAndClickable(page, selector) {
  await expect(page.locator(selector)).toBeVisible();
  await page.waitForTimeout(250);
  const result = await page.locator(selector).evaluate((element) => {
    const footer = document.getElementById("globalA11yControls").getBoundingClientRect();
    const rect = element.getBoundingClientRect();
    const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    return {
      bottom: rect.bottom,
      footerTop: footer.top,
      hitSelf: hit === element || element.contains(hit),
    };
  });
  expect(result.bottom).toBeLessThanOrEqual(result.footerTop);
  expect(result.hitSelf, `${selector} must own its center hit target`).toBe(true);
}

async function expectNoShellScroll(page, screenSelector) {
  const state = await page.locator(screenSelector).evaluate((screen) => ({
    documentTop: document.documentElement.scrollTop,
    bodyTop: document.body.scrollTop,
    screenTop: screen.scrollTop,
    documentOverflow: document.documentElement.scrollHeight - document.documentElement.clientHeight,
    bodyOverflow: document.body.scrollHeight - document.body.clientHeight,
  }));
  expect(state).toEqual({ documentTop: 0, bodyTop: 0, screenTop: 0, documentOverflow: 0, bodyOverflow: 0 });
}

async function expectOnlyRegionScrolls(page, { screen, region, fixed }) {
  const before = await page.locator(fixed).boundingBox();
  const shellBefore = await page.locator(screen).evaluate((element) => element.scrollTop);
  await page.locator(region).evaluate((element) => { element.scrollTop = element.scrollHeight; });
  await page.waitForTimeout(150);
  const after = await page.locator(fixed).boundingBox();
  const state = await page.locator(region).evaluate((element) => ({
    top: element.scrollTop,
    overflow: element.scrollHeight > element.clientHeight,
  }));
  expect(state.overflow).toBe(true);
  expect(state.top).toBeGreaterThan(0);
  expect(await page.locator(screen).evaluate((element) => element.scrollTop)).toBe(shellBefore);
  expect(after).toEqual(before);
  await expectNoShellScroll(page, screen);
}

async function expectSpokenSystemMessage(page, selector, text) {
  const bar = page.locator(selector);
  await expect(bar).toContainText(text, { timeout: 90000 });
  await expect(bar).toHaveClass(/is-tts-playing/, { timeout: 60000 });
  const visual = await bar.evaluate((element) => {
    const barStyle = getComputedStyle(element);
    const textStyle = getComputedStyle(element.querySelector(".response-bar-text"));
    return {
      borderColor: barStyle.borderColor,
      textColor: textStyle.color,
      content: element.textContent,
    };
  });
  expect(visual.borderColor).toBe("rgb(0, 98, 65)");
  expect(visual.textColor).toBe("rgb(0, 98, 65)");
  expect(visual.content).not.toMatch(/말로가 (말하고|안내하고) 있어요/);
  await expect(bar).not.toHaveClass(/is-tts-playing/, { timeout: 60000 });
}

async function switchToTouchIfListening(page) {
  if (await page.locator("#voiceOverlay").isVisible()) {
    await page.locator("#btnVoiceDismiss").click();
    await expect(page.locator("#voiceOverlay")).toBeHidden();
  }
}

test.use({
  viewport: { width: 1080, height: 1920 },
  launchOptions: { channel: "msedge" },
  permissions: ["microphone"],
});

test.setTimeout(240000);

test("SERVICE_MODE부터 PAYMENT까지 footer가 CTA를 가리지 않는다", async ({ page }) => {
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(error.message));
  await page.goto(BASE_URL);
  await expect(page.locator("#screenWelcome")).toHaveClass(/active/);

  await page.locator("#btnStartOrder").click();
  await expectNoShellScroll(page, "#screenServiceMode");
  await expectSpokenSystemMessage(
    page,
    "#screenServiceMode .response-bar",
    "어떻게 이용하시겠어요? 매장 이용 또는 포장을 선택해 주세요.",
  );
  await switchToTouchIfListening(page);
  for (const selector of ["#btnDineIn", "#btnTakeout"]) {
    await expectAboveFooterAndClickable(page, selector);
  }

  await page.locator("#btnDineIn").click();
  await expect(page.locator("#screenOrder")).toHaveClass(/active/);
  await expectSpokenSystemMessage(page, "#listeningResponse", "원하시는 메뉴를 말씀해 주세요.");
  await expect(page.locator("#voiceOverlay")).toBeHidden();
  await expectNoShellScroll(page, "#screenOrder");
  for (const selector of ["#btnOrderMic", "#btnViewCart"]) {
    await expectAboveFooterAndClickable(page, selector);
  }

  await page.locator('.touch-menu-card[data-menu-id="americano"]').click();
  await expect(page.locator("#orderMiniCart")).toBeVisible({ timeout: 60000 });
  await expect(page.locator("#listeningResponseText")).toHaveText("아이스 아메리카노 한 잔을 담았습니다.");
  await expectSpokenSystemMessage(page, "#listeningResponse", "아이스 아메리카노 한 잔을 담았습니다.");
  await page.locator("#touchMenuGrid .touch-menu-card").first().evaluate((item) => {
    const list = item.parentElement;
    for (let index = 0; index < 10; index += 1) list.append(item.cloneNode(true));
  });
  await expectOnlyRegionScrolls(page, {
    screen: "#screenOrder", region: "#touchMenuGrid", fixed: "#btnViewCart",
  });
  await page.locator("#btnViewCart").click();
  await expect(page.locator("#screenOrderReview")).toHaveClass(/active/);
  await expectSpokenSystemMessage(page, "#confirmResponse", "주문 내용을 확인해 주세요.");
  await switchToTouchIfListening(page);
  await page.locator("#confirmItems .menu-card").first().evaluate((item) => {
    const list = item.parentElement;
    for (let index = 0; index < 10; index += 1) list.append(item.cloneNode(true));
  });
  await expectOnlyRegionScrolls(page, {
    screen: "#screenOrderReview", region: "#confirmItemsScroll", fixed: "#btnConfirmYes",
  });
  for (const selector of ["#btnConfirmYes", "#btnConfirmRetry"]) {
    await expectAboveFooterAndClickable(page, selector);
  }

  await page.locator("#btnConfirmYes").click();
  await expect(page.locator("#screenPayment")).toHaveClass(/active/);
  await expectSpokenSystemMessage(page, "#screenPayment .response-bar", "결제 방법을 선택해 주세요.");
  await switchToTouchIfListening(page);
  await expectNoShellScroll(page, "#screenPayment");
  await expectAboveFooterAndClickable(page, "#btnPaymentBack");
  for (const method of await page.locator(".payment-method-item").all()) {
    await expectAboveFooterAndClickable(page, `button[data-method="${await method.getAttribute("data-method")}"]`);
  }

  await page.locator('.payment-method-item[data-method="card"]').click();
  await expect(page.locator("#screenComplete")).toHaveClass(/active/, { timeout: 15000 });
  await expectSpokenSystemMessage(page, "#screenComplete .response-bar", "주문이 완료되었습니다.");
  await expect(page.locator("#voiceOverlay")).toBeHidden();
  await page.locator("#btnHome").click();
  await expect(page.locator("#screenWelcome")).toHaveClass(/active/);
  await expect(page.locator("#globalA11yControls")).toBeHidden();
  await expect(page.locator("#voiceOverlay")).toBeHidden();
  expect(runtimeErrors).toEqual([]);
});

test("제품 SVG가 올바른 MIME과 intrinsic size로 렌더링된다", async ({ page }, testInfo) => {
  const failedResources = [];
  const svgResponses = [];
  page.on("response", (response) => {
    if (response.status() >= 400) failedResources.push(`${response.status()} ${response.url()}`);
    if (response.url().endsWith(".svg")) svgResponses.push({
      url: response.url(), status: response.status(), contentType: response.headers()["content-type"],
    });
  });
  await page.goto(BASE_URL);
  await expect(page.locator(".welcome-mascot")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("welcome-mascot.png"), fullPage: true });
  await page.locator("#btnStartOrder").click();
  await expectSpokenSystemMessage(page, "#screenServiceMode .response-bar", "어떻게 이용하시겠어요?");
  await switchToTouchIfListening(page);

  const images = await page.locator('img[src$=".svg"]').evaluateAll((elements) => elements.map((image) => ({
    src: image.getAttribute("src"), complete: image.complete,
    naturalWidth: image.naturalWidth, naturalHeight: image.naturalHeight,
  })));
  expect(images.length).toBeGreaterThanOrEqual(6);
  for (const image of images) {
    expect(image.complete, image.src).toBe(true);
    expect(image.naturalWidth, image.src).toBeGreaterThan(0);
    expect(image.naturalHeight, image.src).toBeGreaterThan(0);
  }
  expect(svgResponses.length).toBeGreaterThanOrEqual(6);
  for (const response of svgResponses) {
    expect(response.status, response.url).toBe(200);
    expect(response.contentType, response.url).toContain("image/svg+xml");
  }
  expect(failedResources).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath("svg-render.png"), fullPage: true });
});

test("실제 browser microphone 초기화 결과를 구체적으로 노출한다", async ({ page }) => {
  const consoleErrors = [];
  const failedResources = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("response", (response) => {
    if (response.status() >= 400) failedResources.push(`${response.status()} ${response.url()}`);
  });
  await page.goto(BASE_URL);
  await page.locator("#btnStartOrder").click();
  await expectSpokenSystemMessage(
    page,
    "#screenServiceMode .response-bar",
    "어떻게 이용하시겠어요? 매장 이용 또는 포장을 선택해 주세요.",
  );
  await switchToTouchIfListening(page);
  await page.locator("#btnDineIn").click();
  await expectSpokenSystemMessage(page, "#listeningResponse", "원하시는 메뉴를 말씀해 주세요.");
  await page.locator("#btnOrderMic").click();
  await expect(page.locator("#voiceOverlay")).toBeVisible();
  await expect.poll(async () => page.locator("#voiceOverlayTitle").textContent()).not.toBe("말씀하신 내용을 확인하고 있어요");

  const title = await page.locator("#voiceOverlayTitle").textContent();
  const result = { title, consoleErrors, failedResources };
  console.log(`MICROPHONE_BROWSER_RESULT ${JSON.stringify(result)}`);
  if (title === "듣고 있어요") {
    await expect(page.locator("#waveform")).toBeVisible();
    await page.locator("#btnVoiceDismiss").click();
  } else {
    expect([
      "마이크 권한이 필요합니다. 브라우저 설정에서 마이크를 허용해 주세요.",
      "사용할 수 있는 마이크를 찾지 못했습니다.",
      "마이크를 사용할 수 없습니다. 다른 앱에서 사용 중인지 확인해 주세요.",
      "브라우저의 녹음 기능을 시작하지 못했습니다. 다시 시도해 주세요.",
      "마이크를 시작하지 못했습니다. 다시 시도해 주세요.",
    ]).toContain(title);
    expect(consoleErrors.some((message) => message.includes("Microphone initialization failed"))).toBe(true);
  }
});
