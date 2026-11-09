(function (root, factory) {
  const OptionChangeFlow = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = { OptionChangeFlow };
  }
  root.OptionChangeFlow = OptionChangeFlow;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  return class OptionChangeFlow {
    constructor() {
      this.active = false;
    }

    start() {
      this.active = true;
      return "OPTION_CHANGE";
    }

    finish(result) {
      if (result && result.success === true) {
        this.active = false;
        return "ORDER_REVIEW";
      }
      return "OPTION_CHANGE";
    }

    cancel() {
      this.active = false;
      return "ORDER_REVIEW";
    }
  };
});
