"""Drop-in plugins for CANForge.

Any module placed in this package is auto-imported by
:func:`canforge.registry.load_plugins` at startup, letting it self-register an
RE engine, decoder, exporter or OEM pack without any change to core modules.

This package is intentionally empty for now; Phase 1+ adds engines here.
"""
