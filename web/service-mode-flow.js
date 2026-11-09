(function (root, factory) {
  const exported = factory();
  if (typeof module === "object" && module.exports) module.exports = exported;
  else root.ServiceModeFlow = exported.ServiceModeFlow;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  class ServiceModeFlow {
    constructor() {
      this.active = false;
    }

    start() {
      this.active = true;
      return "SERVICE_MODE";
    }

    selectionPayload(fulfillmentType) {
      if (!['dine_in', 'takeout'].includes(fulfillmentType)) return null;
      return { fulfillment_type: fulfillmentType };
    }

    finish(result, expectedFulfillmentType) {
      const savedType = result && result.cart && result.cart.fulfillment_type;
      if (result && result.success === true && savedType === expectedFulfillmentType) {
        this.active = false;
        return "ORDER";
      }
      return "SERVICE_MODE";
    }

    reset() {
      this.active = false;
    }
  }

  return { ServiceModeFlow };
});
