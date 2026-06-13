"""Reverse-engineering engines (Pillar B).

Each engine turns grouped CAN frames into candidate signal definitions. They are
pure-stdlib and side-effect free so they're trivial to unit-test, and they
register into :data:`canforge.registry.RE_ENGINES` (via ``canforge/plugins``) so
the rest of the app discovers them by name.

Engines share the **frames-by-id** input shape produced by
``canforge.reverse.load_log_frames``::

    { (arbitration_id, is_extended): {
          "timestamps": [float, ...],
          "payloads":   [bytes,  ...],
      }, ... }

and return the analysis dict shape consumed by ``web/app.js`` (see
``canforge.reverse.analyze_log``).
"""
