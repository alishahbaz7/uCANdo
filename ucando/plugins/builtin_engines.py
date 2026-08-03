"""Register the built-in reverse-engineering engines.

Imported by :func:`ucando.registry.load_plugins` at startup (and lazily by
``reverse.analyze_log``), so the engines are discoverable by name without any
core module importing them directly.
"""

from __future__ import annotations

from ..registry import RE_ENGINES
from ..reverse import BasicEngine
from ..re_engines.read import ReadEngine

RE_ENGINES.add("read", ReadEngine(),
               description="Bit-flip-rate tokenizer with endianness, counter/CRC/"
                           "physical classification and multiplexor detection")
RE_ENGINES.add("basic", BasicEngine(),
               description="Toggle-count contiguous-bit candidate finder (legacy)")
