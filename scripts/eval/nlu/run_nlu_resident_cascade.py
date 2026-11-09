"""Deprecated compatibility entrypoint for the Qwen3-1.7B reference cascade.

This filename is kept only so older local orchestration scripts do not break after
PR #209 renamed the 1.7B benchmark to make its reference-only scope explicit.
New code should invoke ``run_nlu_qwen3_1p7b_reference_cascade.py`` directly.
"""

from __future__ import annotations

from run_nlu_qwen3_1p7b_reference_cascade import main


if __name__ == "__main__":
    raise SystemExit(main())
