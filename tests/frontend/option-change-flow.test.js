"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { OptionChangeFlow } = require("../../web/option-change-flow.js");

test("order confirmation enters option change", () => {
  const flow = new OptionChangeFlow();
  assert.equal(flow.start(), "OPTION_CHANGE");
  assert.equal(flow.active, true);
});

test("successful quantity or option update returns to confirmation", () => {
  const flow = new OptionChangeFlow();
  flow.start();
  assert.equal(flow.finish({ success: true }), "ORDER_REVIEW");
  assert.equal(flow.active, false);
});

test("unsupported or ambiguous update stays in option change", () => {
  const flow = new OptionChangeFlow();
  flow.start();
  assert.equal(flow.finish({ success: false, error_code: "UNSUPPORTED_UTTERANCE" }), "OPTION_CHANGE");
  assert.equal(flow.finish(null), "OPTION_CHANGE");
  assert.equal(flow.active, true);
});

test("cancel returns to confirmation without a mutation", () => {
  const flow = new OptionChangeFlow();
  flow.start();
  assert.equal(flow.cancel(), "ORDER_REVIEW");
  assert.equal(flow.active, false);
});
