#!/usr/bin/env python3
"""Compatibility-named entry point for the loopback 3DS Telco PC service."""

from pathlib import Path
import importlib.util
import sys


TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

SPEC = importlib.util.spec_from_file_location(
    "n3ds_telco_client", TOOLS / "3ds_telco_client.py")
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load 3ds_telco_client.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["n3ds_telco_client"] = MODULE
SPEC.loader.exec_module(MODULE)
# Re-export the service surface from the service-named entry point.  The
# compatibility client module owns the shared implementation so old scripts
# keep working, but callers no longer need to import a watcher-named module to
# construct or inspect the PC server.
LatchState = MODULE.LatchState
LocalStatusServer = MODULE.LocalStatusServer
build_parser = MODULE.build_parser
run_service = MODULE.run_service
main = MODULE.main


if __name__ == "__main__":
    raise SystemExit(main())
