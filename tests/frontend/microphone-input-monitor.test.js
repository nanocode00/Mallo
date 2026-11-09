"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { MicrophoneInputMonitor } = require("../../web/microphone-input-monitor.js");

function analyserWith(sample) {
  return {
    fftSize: 0,
    smoothingTimeConstant: 0,
    disconnected: 0,
    getByteTimeDomainData(buffer) { buffer.fill(sample); },
    disconnect() { this.disconnected += 1; },
  };
}

function harness(sample = 128, options = {}) {
  const analyser = analyserWith(sample);
  const source = { disconnected: 0, connect() {}, disconnect() { this.disconnected += 1; } };
  const context = {
    closed: 0,
    createMediaStreamSource: () => source,
    createAnalyser: () => analyser,
    close() { this.closed += 1; },
  };
  const frames = [];
  const cancelled = [];
  const bars = Array.from({ length: 4 }, () => ({ style: {} }));
  let timestamp = 0;
  const monitor = new MicrophoneInputMonitor({
    AudioContextCtor: class { constructor() { return context; } },
    requestFrame(callback) { frames.push(callback); return frames.length; },
    cancelFrame(id) { cancelled.push(id); },
    now: () => timestamp,
    ...options,
  });
  return { monitor, analyser, source, context, frames, cancelled, bars, setTime(value) { timestamp = value; } };
}

test("waveform stays near rest for silence and grows with microphone amplitude", () => {
  const h = harness(128);
  h.monitor.start({}, h.bars);
  h.frames.shift()();
  assert.deepEqual(h.bars.map((bar) => bar.style.height), ["8%", "8%", "8%", "8%"]);

  h.analyser.getByteTimeDomainData = (buffer) => buffer.fill(180);
  h.frames.shift()();
  assert.ok(h.bars.some((bar) => Number.parseInt(bar.style.height, 10) > 30));
});

test("VAD keeps a 1.4 second senior pause open and ends after 1600ms of silence", () => {
  let ended = 0;
  const h = harness(180, { calibrationDurationMs: 0, onSpeechEnd: () => { ended += 1; } });
  h.monitor.start({}, h.bars);
  h.frames.shift()();
  assert.equal(h.monitor.hasDetectedSpeech, true);

  h.analyser.getByteTimeDomainData = (buffer) => buffer.fill(128);
  h.setTime(100);
  h.frames.shift()();
  h.setTime(1499);
  h.frames.shift()();
  assert.equal(ended, 0);
  h.setTime(1500);
  h.frames.shift()();
  assert.equal(ended, 0);
  h.setTime(1700);
  h.frames.shift()();
  assert.equal(ended, 1);
});

for (const silenceDurationMs of [1400, 1600, 1800]) {
  test(`VAD silence duration ${silenceDurationMs}ms remains configurable`, () => {
    let ended = 0;
    const h = harness(180, { calibrationDurationMs: 0, silenceDurationMs, onSpeechEnd: () => { ended += 1; } });
    h.monitor.start({}, h.bars);
    h.frames.shift()();
    h.analyser.getByteTimeDomainData = (buffer) => buffer.fill(128);
    h.setTime(100);
    h.frames.shift()();
    h.setTime(99 + silenceDurationMs);
    h.frames.shift()();
    assert.equal(ended, 0);
    h.setTime(100 + silenceDurationMs);
    h.frames.shift()();
    assert.equal(ended, 1);
  });
}

test("silence never counts as detected speech", () => {
  const h = harness(128);
  h.monitor.start({}, h.bars);
  h.frames.shift()();
  assert.equal(h.monitor.hasDetectedSpeech, false);
});

test("startup calibration learns a steady fan noise floor before detecting speech", () => {
  const h = harness(140, { calibrationDurationMs: 300, noiseMultiplier: 2.5 });
  h.monitor.start({}, h.bars);
  h.frames.shift()();
  h.setTime(200);
  h.frames.shift()();
  assert.equal(h.monitor.hasDetectedSpeech, false);
  h.setTime(350);
  h.frames.shift()();
  assert.equal(h.monitor.hasDetectedSpeech, false);
  h.analyser.getByteTimeDomainData = (buffer) => buffer.fill(220);
  h.setTime(400);
  h.frames.shift()();
  assert.equal(h.monitor.hasDetectedSpeech, true);
});

test("stop releases animation, graph nodes, and AudioContext", () => {
  const h = harness();
  h.monitor.start({}, h.bars);
  h.monitor.stop();
  assert.deepEqual(h.cancelled, [1]);
  assert.equal(h.source.disconnected, 1);
  assert.equal(h.analyser.disconnected, 1);
  assert.equal(h.context.closed, 1);
  assert.deepEqual(h.bars.map((bar) => bar.style.height), ["8%", "8%", "8%", "8%"]);
});
