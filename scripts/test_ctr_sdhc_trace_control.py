#!/usr/bin/env python3
"""Regression for default-off SDHC success tracing and retained errors."""

import importlib.util
from pathlib import Path


PATCH_PATH = Path(__file__).with_name("patch_ctr_sdhc_trace_control.py")


def load_patcher():
    assert PATCH_PATH.is_file(), f"missing implementation: {PATCH_PATH.name}"
    spec = importlib.util.spec_from_file_location("sdhc_trace_patch", PATCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    patcher = load_patcher()
    model = patcher.PARAM_ANCHOR + patcher.ACTIVATION_OLD + patcher.ERROR_OLD
    patched = patcher.patch_source(model)

    assert patched.count(patcher.MARKER) == 1
    assert "static bool cmd53_success_trace;" in patched
    assert "module_param(cmd53_success_trace, bool, 0644);" in patched
    assert "if (cmd53_success_trace && mrq->cmd" in patched
    assert "host->transport_trace_count < 64" in patched
    assert "dev_err(host->dev" in patched
    assert "AR6002 SDHC CMD53 error status=" in patched
    assert "AR6002 SDHC request timeout" not in model  # patched elsewhere, untouched
    assert patcher.patch_source(patched) == patched
    print("ctr_sdhc_trace_control: PASS")


if __name__ == "__main__":
    main()
