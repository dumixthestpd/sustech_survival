"""
SUSTech Course Grid — DEPRECATED.

This module is superseded by the unified web UI
(``sustech_survival.webui``, single port 61019). Running this file
launches the unified app instead.

The old Flask course-grid solver (:8765) has been removed; the
solver logic now lives in ``webui/blueprints/tis.py:api_solve``.
"""
if __name__ == "__main__":
    import sys, warnings
    warnings.warn(
        "tis/grid_server.py (port 8765) is superseded by the unified web UI "
        "(sustech_survival.webui, single port 61019). Delegating…",
        DeprecationWarning, stacklevel=1,
    )
    print("\u26a0 grid_server is deprecated \u2192 launching unified web UI on :61019",
          file=sys.stderr)
    from sustech_survival.webui.app import run as _run
    _run(port=61019, debug=False)
