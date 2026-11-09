"use strict";

const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests/e2e",
  outputDir: "/tmp/mallo-playwright-results",
});
