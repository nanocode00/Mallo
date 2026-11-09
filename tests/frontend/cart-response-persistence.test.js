import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const appSource = fs.readFileSync(path.resolve("web/app.js"), "utf8");

test("refreshConfirmScreen does not hardcode confirmResponseText overwrite", () => {
  // Verify that refreshConfirmScreen preserves orderState.lastResponse
  assert.ok(!appSource.includes('document.getElementById("confirmResponseText").textContent = "주문 내용을 확인해주세요.";'),
    "refreshConfirmScreen should not overwrite confirmResponseText with a hardcoded string");
  assert.match(appSource, /function refreshConfirmScreen\(\)\s*\{[\s\S]*renderCartScreen\(\);[\s\S]*orderState\.lastResponse/);
});

test("openOrderReview sets initial response text when preserveResponse is false", () => {
  assert.match(appSource, /async function openOrderReview\(\{[\s\S]*if \(!preserveResponse\) renderResponseBars\("주문 내용을 확인해 주세요\."\);/);
});
