(function (root, factory) {
  const MicrophoneInputMonitor = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = { MicrophoneInputMonitor };
  }
  root.MicrophoneInputMonitor = MicrophoneInputMonitor;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  return class MicrophoneInputMonitor {
    constructor({
      AudioContextCtor = globalThis.AudioContext || globalThis.webkitAudioContext,
      requestFrame = globalThis.requestAnimationFrame.bind(globalThis),
      cancelFrame = globalThis.cancelAnimationFrame.bind(globalThis),
      now = () => performance.now(),
      speechThreshold = 0.025,
      noiseMultiplier = 2.5,
      calibrationDurationMs = 350,
      diagnosticIntervalMs = 250,
      silenceDurationMs = 1600,
      onSpeechEnd = () => {},
    } = {}) {
      this._AudioContextCtor = AudioContextCtor;
      this._requestFrame = requestFrame;
      this._cancelFrame = cancelFrame;
      this._now = now;
      this._speechThreshold = speechThreshold;
      this._noiseMultiplier = noiseMultiplier;
      this._calibrationDurationMs = calibrationDurationMs;
      this._diagnosticIntervalMs = diagnosticIntervalMs;
      this._noiseFloor = null;
      this._silenceDurationMs = silenceDurationMs;
      this._onSpeechEnd = onSpeechEnd;
      this._frameId = null;
      this._context = null;
      this._source = null;
      this._analyser = null;
      this._samples = null;
      this._bars = [];
      this._heardSpeech = false;
      this._silenceStartedAt = null;
      this._speechEnded = false;
      this._startedAt = null;
      this._lastDiagnosticAt = null;
    }

    get hasDetectedSpeech() {
      return this._heardSpeech;
    }

    start(stream, bars = []) {
      this.stop();
      if (!this._AudioContextCtor) return false;
      this._bars = Array.from(bars);
      this._context = new this._AudioContextCtor();
      if (this._context && this._context.state === "suspended" && typeof this._context.resume === "function") {
        this._context.resume().catch(() => {});
      }
      this._source = this._context.createMediaStreamSource(stream);
      this._analyser = this._context.createAnalyser();
      this._analyser.fftSize = 256;
      this._analyser.smoothingTimeConstant = 0.65;
      this._samples = new Uint8Array(this._analyser.fftSize);
      this._source.connect(this._analyser);
      this._startedAt = this._now();
      console.debug("[Mallo VAD] start", { calibrationDurationMs: this._calibrationDurationMs, speechThreshold: this._speechThreshold, noiseMultiplier: this._noiseMultiplier });
      this._frameId = this._requestFrame(() => this._tick());
      return true;
    }

    _tick() {
      if (!this._analyser || !this._samples) return;
      this._analyser.getByteTimeDomainData(this._samples);
      let squareSum = 0;
      for (const sample of this._samples) {
        const normalized = (sample - 128) / 128;
        squareSum += normalized * normalized;
      }
      const amplitude = Math.sqrt(squareSum / this._samples.length);
      this._render(amplitude);
      const timestamp = this._now();
      const elapsedMs = timestamp - this._startedAt;
      const calibrating = elapsedMs < this._calibrationDurationMs;
      if (calibrating || (!this._heardSpeech && amplitude < this._releaseThreshold())) {
        this._noiseFloor = this._noiseFloor === null ? amplitude : (this._noiseFloor * 0.9 + amplitude * 0.1);
      }
      const threshold = this._speechThresholdForStart();
      const releaseThreshold = this._releaseThreshold();
      this._diagnose(timestamp, { elapsedMs, calibrating, amplitude, threshold, releaseThreshold });
      if (!calibrating && amplitude >= threshold) {
        this._heardSpeech = true;
        this._silenceStartedAt = null;
      } else if (this._heardSpeech && amplitude < releaseThreshold) {
        if (this._silenceStartedAt === null) this._silenceStartedAt = timestamp;
        if (!this._speechEnded && timestamp - this._silenceStartedAt >= this._silenceDurationMs) {
          this._speechEnded = true;
          this._onSpeechEnd();
          return;
        }
      }
      this._frameId = this._requestFrame(() => this._tick());
    }

    _speechThresholdForStart() {
      return Math.max(this._speechThreshold, (this._noiseFloor || 0) * this._noiseMultiplier);
    }

    _releaseThreshold() {
      return Math.max(this._speechThreshold * 0.6, this._speechThresholdForStart() * 0.65);
    }

    _diagnose(timestamp, values) {
      if (this._lastDiagnosticAt !== null && timestamp - this._lastDiagnosticAt < this._diagnosticIntervalMs) return;
      this._lastDiagnosticAt = timestamp;
      console.debug("[Mallo VAD] frame", {
        phase: values.calibrating ? "calibrating" : (this._heardSpeech ? "speech-or-silence" : "waiting-for-speech"),
        elapsedMs: Math.round(values.elapsedMs),
        rms: Number(values.amplitude.toFixed(5)),
        noiseFloor: this._noiseFloor === null ? null : Number(this._noiseFloor.toFixed(5)),
        startThreshold: Number(values.threshold.toFixed(5)),
        releaseThreshold: Number(values.releaseThreshold.toFixed(5)),
        heardSpeech: this._heardSpeech,
        silenceMs: this._silenceStartedAt === null ? 0 : Math.round(timestamp - this._silenceStartedAt),
      });
    }

    _render(amplitude) {
      if (amplitude <= 0.0001) {
        this._bars.forEach((bar) => {
          if (typeof bar.style?.setProperty === "function") {
            bar.style.setProperty("height", "8%", "important");
          }
          if (bar.style) bar.style.height = "8%";
        });
        return;
      }
      const effectiveAmp = Math.max(0, amplitude - 0.012);
      const strength = Math.min(1, Math.pow(effectiveAmp * 15, 0.9) * 1.6);
      const totalBars = this._bars.length || 28;
      this._bars.forEach((bar, index) => {
        const centerDist = Math.abs(index - (totalBars - 1) / 2) / Math.max(1, (totalBars - 1) / 2);
        const bellCurve = Math.cos(centerDist * Math.PI * 0.48);
        const wave = 0.65 + 0.35 * Math.sin((index + 1) * 1.85) ** 2;
        const heightPercent = Math.round(8 + strength * bellCurve * wave * 92);
        const heightStr = `${Math.min(100, Math.max(8, heightPercent))}%`;
        if (typeof bar.style?.setProperty === "function") {
          bar.style.setProperty("height", heightStr, "important");
        }
        if (bar.style) bar.style.height = heightStr;
      });
    }

    stop() {
      if (this._frameId !== null) this._cancelFrame(this._frameId);
      this._frameId = null;
      if (this._source && typeof this._source.disconnect === "function") this._source.disconnect();
      if (this._analyser && typeof this._analyser.disconnect === "function") this._analyser.disconnect();
      if (this._context && typeof this._context.close === "function") this._context.close();
      this._bars.forEach((bar) => { bar.style.height = "8%"; });
      this._context = null;
      this._source = null;
      this._analyser = null;
      this._samples = null;
      this._bars = [];
      this._heardSpeech = false;
      this._silenceStartedAt = null;
      this._speechEnded = false;
      this._noiseFloor = null;
      this._startedAt = null;
      this._lastDiagnosticAt = null;
    }
  };
});
