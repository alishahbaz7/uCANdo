"""Plugin registry behaviour."""

import pytest

from canforge.registry import Registry, load_plugins, describe_all


def test_register_and_get():
    reg = Registry("thing")

    @reg.register("alpha", description="first")
    class Alpha:
        pass

    assert "alpha" in reg
    assert reg.get("alpha") is Alpha
    assert reg.require("alpha") is Alpha
    assert reg.describe()[0]["description"] == "first"
    assert reg.describe()[0]["kind"] == "thing"


def test_duplicate_without_override_raises():
    reg = Registry("thing")
    reg.add("x", 1)
    with pytest.raises(ValueError):
        reg.add("x", 2)
    reg.add("x", 2, override=True)
    assert reg.get("x") == 2


def test_require_unknown_raises():
    reg = Registry("thing")
    with pytest.raises(KeyError):
        reg.require("missing")


def test_load_plugins_empty_package_is_safe():
    # The plugins package exists but is empty; must not raise.
    assert isinstance(load_plugins(), list)


def test_describe_all_has_all_kinds():
    d = describe_all()
    assert {"re_engine", "decoder", "exporter", "oem_pack"} <= set(d)
