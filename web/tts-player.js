(function (root, factory) {
  const TTSPlaybackController = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = { TTSPlaybackController };
  }
  root.TTSPlaybackController = TTSPlaybackController;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  return class TTSPlaybackController {
    constructor({
      AudioCtor = Audio,
      BlobCtor = Blob,
      createObjectURL = URL.createObjectURL.bind(URL),
      revokeObjectURL = URL.revokeObjectURL.bind(URL),
      decodeBase64 = (value) => globalThis.atob(value),
      onStatus = () => {},
      maxVolume = 0.75,
    } = {}) {
      this._AudioCtor = AudioCtor;
      this._BlobCtor = BlobCtor;
      this._createObjectURL = createObjectURL;
      this._revokeObjectURL = revokeObjectURL;
      this._decodeBase64 = decodeBase64;
      this._onStatus = onStatus;
      this._maxVolume = Math.max(0, Math.min(1, maxVolume));
      this._audio = null;
      this._audioUrl = null;
      this._playbackEpoch = 0;
      this._completion = null;
      // This is diagnostics only. A successful priming play does not prove
      // that a later TTS request can play, nor does a failed one mean TTS is
      // unavailable.
      this._userGestureUnlockState = "unknown";
      this.status = "idle";
    }

    get userGestureUnlockState() {
      return this._userGestureUnlockState;
    }

    unlockFromUserGesture() {
      this._userGestureActivated = true;
      this._userGestureUnlockState = "pending";
      // Called synchronously from a click handler. This primes browser audio
      // permission without changing current TTS playback state.
      try {
        const audio = new this._AudioCtor("data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=");
        audio.muted = true;
        const playing = audio.play();
        return Promise.resolve(playing).then(() => {
          audio.pause();
          audio.removeAttribute("src");
          audio.load();
          this._userGestureUnlockState = "unlocked";
          console.debug("[Mallo TTS] user-gesture unlock succeeded");
          return true;
        }).catch((error) => {
          this._userGestureUnlockState = "blocked";
          console.debug("[Mallo TTS] user-gesture unlock unavailable", { name: error?.name });
          return false;
        });
      } catch (error) {
        this._userGestureUnlockState = "blocked";
        console.debug("[Mallo TTS] user-gesture unlock unavailable", { name: error?.name });
        return Promise.resolve(false);
      }
    }

    _setStatus(status, error = null) {
      this.status = status;
      this._onStatus(status, error);
      if (["completed", "error", "idle"].includes(status) && this._completion) {
        this._completion(); this._completion = null;
      }
    }

    _disposeAudio() {
      if (this._audio) {
        this._audio.pause();
        this._audio.onplay = null;
        this._audio.onended = null;
        this._audio.onerror = null;
        this._audio.removeAttribute("src");
        this._audio.load();
      }
      if (this._audioUrl) this._revokeObjectURL(this._audioUrl);
      this._audio = null;
      this._audioUrl = null;
    }

    async loadAndPlay(audioBase64) {
      const epoch = ++this._playbackEpoch;
      this._completion = null;
      this._setStatus("loading");
      this._disposeAudio();

      if (typeof audioBase64 !== "string" || !audioBase64.trim()) {
        this._setStatus("error", new Error("TTS audio가 없습니다."));
        return false;
      }

      try {
        const binary = this._decodeBase64(audioBase64);
        const bytes = new Uint8Array(binary.length);
        for (let index = 0; index < binary.length; index += 1) {
          bytes[index] = binary.charCodeAt(index);
        }
        const blob = new this._BlobCtor([bytes], { type: "audio/wav" });
        this._audioUrl = this._createObjectURL(blob);
        this._audio = new this._AudioCtor(this._audioUrl);
        const audio = this._audio;
        audio.volume = this._maxVolume;
        audio.onplay = () => { if (epoch === this._playbackEpoch) this._setStatus("playing"); };
        audio.onended = () => { if (epoch === this._playbackEpoch) this._setStatus("completed"); };
        audio.onerror = () => { if (epoch === this._playbackEpoch) this._setStatus("error", new Error("TTS audio 재생에 실패했습니다.")); };
        console.debug("[Mallo TTS] start", { epoch, volume: audio.volume, maxVolume: this._maxVolume, audioContext: "none", gain: "none", atMs: Math.round(performance.now()) });
        await audio.play();
        if (epoch !== this._playbackEpoch || audio !== this._audio) { audio.pause(); return false; }
        return true;
      } catch (error) {
        if (error?.name === "NotAllowedError") {
          console.debug("[Mallo TTS] autoplay blocked", { epoch, name: error.name });
          this._setStatus("autoplay-blocked", error);
          return false;
        }
        this._setStatus("error", error);
        return false;
      }
    }

    waitForCompletion() {
      if (this.status !== "loading" && this.status !== "playing") return Promise.resolve();
      return new Promise((resolve) => { this._completion = resolve; });
    }

    async replay() {
      if (!this._audio) {
        this._setStatus("error", new Error("다시 재생할 TTS audio가 없습니다."));
        return false;
      }
      try {
        const epoch = this._playbackEpoch;
        this._setStatus("loading");
        this._audio.currentTime = 0;
        this._audio.volume = this._maxVolume;
        console.debug("[Mallo TTS] replay", { epoch, volume: this._audio.volume, maxVolume: this._maxVolume, audioContext: "none", gain: "none", atMs: Math.round(performance.now()) });
        await this._audio.play();
        return true;
      } catch (error) {
        if (error?.name === "NotAllowedError") {
          console.debug("[Mallo TTS] replay blocked by browser policy", { name: error.name });
          this._setStatus("autoplay-blocked", error);
          return false;
        }
        this._setStatus("error", error);
        return false;
      }
    }

    stop() {
      this._playbackEpoch += 1;
      if (this._audio) {
        this._audio.pause();
        this._audio.currentTime = 0;
      }
      this._setStatus("idle");
    }

    dispose() {
      this._disposeAudio();
      this._setStatus("idle");
    }
  };
});
