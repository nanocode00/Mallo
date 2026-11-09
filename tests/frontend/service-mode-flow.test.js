"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { ServiceModeFlow } = require("../../web/service-mode-flow.js");

test("welcome order action enters service mode", () => {
  const flow = new ServiceModeFlow();
  assert.equal(flow.start(), "SERVICE_MODE");
  assert.equal(flow.active, true);
});

for (const fulfillmentType of ["dine_in", "takeout"]) {
  test(`${fulfillmentType} selection enters listening only after backend success`, () => {
    const flow = new ServiceModeFlow();
    flow.start();
    assert.deepEqual(flow.selectionPayload(fulfillmentType), {
      fulfillment_type: fulfillmentType,
    });
    assert.equal(
      flow.finish(
        { success: true, cart: { fulfillment_type: fulfillmentType } },
        fulfillmentType,
      ),
      "ORDER",
    );
    assert.equal(flow.active, false);
  });
}

test("failed or mismatched save stays in service mode", () => {
  const flow = new ServiceModeFlow();
  flow.start();
  assert.equal(flow.finish({ success: false }, "dine_in"), "SERVICE_MODE");
  assert.equal(
    flow.finish({ success: true, cart: { fulfillment_type: "takeout" } }, "dine_in"),
    "SERVICE_MODE",
  );
  assert.equal(flow.active, true);
});
