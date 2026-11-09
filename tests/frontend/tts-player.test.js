"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { TTSPlaybackController } = require("../../web/tts-player.js");

class FakeBlob {
  constructor(parts, options) {
    this.parts = parts;
    this.type = options.type;
  }
}

class FakeAudio {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.currentTime = 5;
    this.playCalls = 0;
    this.pauseCalls = 0;
    FakeAudio.instances.push(this);
  }

  async play() {
    this.playCalls += 1;
    if (this.onplay) this.onplay();
  }

  pause() {
    this.pauseCalls += 1;
  }

  removeAttribute(name) {
    if (name === "src") this.url = null;
  }

  load() {}
}

function createHarness({ decodeBase64 = () => "wav" } = {}) {
  const statuses = [];
  const revoked = [];
  let urlIndex = 0;
  FakeAudio.instances = [];
  const player = new TTSPlaybackController({
    AudioCtor: FakeAudio,
    BlobCtor: FakeBlob,
    createObjectURL: () => `blob:tts-${++urlIndex}`,
    revokeObjectURL: (url) => revoked.push(url),
    decodeBase64,
    onStatus: (status) => statuses.push(status),
  });
  return { player, statuses, revoked };
}

test("audio lifecycle transitions loading, playing, completed", async () => {
  const { player, statuses } = createHarness();
  assert.equal(await player.loadAndPlay("d2F2"), true);
  assert.deepEqual(statuses, ["loading", "playing"]);
  FakeAudio.instances[0].onended();
  assert.equal(player.status, "completed");
  assert.deepEqual(statuses, ["loading", "playing", "completed"]);
  assert.equal(FakeAudio.instances[0].volume, 0.75);
});

test("new audio disposes and revokes the previous resource", async () => {
  const { player, revoked } = createHarness();
  await player.loadAndPlay("Zmlyc3Q=");
  const first = FakeAudio.instances[0];
  await player.loadAndPlay("c2Vjb25k");
  assert.equal(first.pauseCalls, 1);
  assert.deepEqual(revoked, ["blob:tts-1"]);
});

test("missing or invalid audio enters error fallback", async () => {
  const missing = createHarness();
  assert.equal(await missing.player.loadAndPlay(null), false);
  assert.equal(missing.player.status, "error");

  const invalid = createHarness({ decodeBase64: () => { throw new Error("invalid base64"); } });
  assert.equal(await invalid.player.loadAndPlay("invalid"), false);
  assert.equal(invalid.player.status, "error");
});

test("NotAllowedError is classified as autoplay blocked rather than TTS failure", async () => {
  class AutoplayBlockedAudio extends FakeAudio {
    async play() {
      const error = new Error("user gesture required");
      error.name = "NotAllowedError";
      throw error;
    }
  }
  const statuses = [];
  const player = new TTSPlaybackController({
    AudioCtor: AutoplayBlockedAudio,
    BlobCtor: FakeBlob,
    createObjectURL: () => "blob:blocked",
    revokeObjectURL: () => {},
    onStatus: (status) => statuses.push(status),
  });

  assert.equal(await player.loadAndPlay("d2F2"), false);
  assert.equal(player.status, "autoplay-blocked");
  assert.deepEqual(statuses, ["loading", "autoplay-blocked"]);
});

test("trusted gesture unlock is diagnostic-only and leaves TTS playback state untouched", async () => {
  const { player, statuses } = createHarness();

  assert.equal(await player.unlockFromUserGesture(), true);
  const unlockAudio = FakeAudio.instances[0];
  assert.equal(unlockAudio.muted, true);
  assert.equal(unlockAudio.pauseCalls, 1);
  assert.equal(player.userGestureUnlockState, "unlocked");
  assert.equal(player.status, "idle");
  assert.deepEqual(statuses, []);
});

test("trusted gesture unlock failure is not classified as a TTS server failure", async () => {
  class UnlockBlockedAudio extends FakeAudio {
    async play() {
      const error = new Error("user gesture required");
      error.name = "NotAllowedError";
      throw error;
    }
  }
  const player = new TTSPlaybackController({
    AudioCtor: UnlockBlockedAudio,
    BlobCtor: FakeBlob,
    createObjectURL: () => "blob:unlock-blocked",
    revokeObjectURL: () => {},
  });

  assert.equal(await player.unlockFromUserGesture(), false);
  assert.equal(player.userGestureUnlockState, "blocked");
  assert.equal(player.status, "idle");
});

test("replay restarts the latest audio", async () => {
  const { player } = createHarness();
  await player.loadAndPlay("d2F2");
  const audio = FakeAudio.instances[0];
  assert.equal(await player.replay(), true);
  assert.equal(audio.currentTime, 0);
  assert.equal(audio.playCalls, 2);
  assert.equal(player.status, "playing");
});

test("replay classifies NotAllowedError as autoplay blocked", async () => {
  class ReplayBlockedAudio extends FakeAudio {
    async play() {
      this.playCalls += 1;
      if (this.playCalls > 1) {
        const error = new Error("user gesture required");
        error.name = "NotAllowedError";
        throw error;
      }
      if (this.onplay) this.onplay();
    }
  }
  const statuses = [];
  const player = new TTSPlaybackController({
    AudioCtor: ReplayBlockedAudio,
    BlobCtor: FakeBlob,
    createObjectURL: () => "blob:replay-blocked",
    revokeObjectURL: () => {},
    onStatus: (status) => statuses.push(status),
  });

  await player.loadAndPlay("d2F2");
  assert.equal(await player.replay(), false);
  assert.equal(player.status, "autoplay-blocked");
  assert.deepEqual(statuses, ["loading", "playing", "loading", "autoplay-blocked"]);
});

test("stop pauses audio and resets status without revoking the resource", async () => {
  const { player, revoked } = createHarness();
  await player.loadAndPlay("d2F2");
  const audio = FakeAudio.instances[0];
  player.stop();
  assert.equal(player.status, "idle");
  assert.equal(audio.currentTime, 0);
  assert.equal(audio.pauseCalls, 1);
  assert.deepEqual(revoked, []);
});

test("dispose releases audio without starting another interaction", async () => {
  const { player, revoked } = createHarness();
  await player.loadAndPlay("d2F2");
  player.dispose();
  assert.equal(player.status, "idle");
  assert.deepEqual(revoked, ["blob:tts-1"]);
});

test("default browser atob is called with the global receiver", async () => {
  const originalAtob = globalThis.atob;
  let receiver = null;
  globalThis.atob = function () {
    receiver = this;
    return "wav";
  };
  try {
    const player = new TTSPlaybackController({
      AudioCtor: FakeAudio,
      BlobCtor: FakeBlob,
      createObjectURL: () => "blob:default-atob",
      revokeObjectURL: () => {},
    });
    assert.equal(await player.loadAndPlay("d2F2"), true);
    assert.equal(receiver, globalThis);
  } finally {
    globalThis.atob = originalAtob;
  }
});
