"""Tests for V13 section 38 capability marketplace (additive, isolated store)."""

from __future__ import annotations

from typing import Any

import pytest

from app.capability.marketplace import CapabilityMarketplace, MarketplaceEntry
from app.capability.registry import CapabilityRecord, CapabilityRegistry


def _market(tmp_path):
    return CapabilityMarketplace(registry=CapabilityRegistry(root=tmp_path))


def _entry(**overrides):  # type: ignore[no-untyped-def]
    base: dict[str, Any] = dict(
        id="demo.tool",
        name="Demo Tool",
        version="1.0.0",
        publisher="unit-test",
        description="A reviewed demonstration capability",
        requirements=("python>=3.10",),
        permissions=("workspace.read",),
        dependencies=("std-lib",),
        compatibility="python",
        security_review_status="reviewed",
        test_status="passed",
        documentation="docs/demo.md",
    )
    base.update(overrides)
    return MarketplaceEntry(**base)


def test_catalog_metadata_and_filters(tmp_path):
    market = _market(tmp_path)
    market.publish(_entry())
    market.publish(_entry(id="unreviewed.tool", security_review_status="unreviewed"))
    items = market.list()
    assert len(items) == 2
    assert items[0]["publisher"] == "unit-test"
    assert items[0]["requirements"] == ("python>=3.10",)
    assert items[0]["documentation"] == "docs/demo.md"
    assert len(market.list(reviewed_only=True, tested_only=True)) == 1


def test_unreviewed_or_untested_cannot_be_installed(tmp_path):
    market = _market(tmp_path)
    market.publish(_entry(security_review_status="unreviewed"))
    market.publish(_entry(id="untested", test_status="not_tested"))
    called = []
    with pytest.raises(PermissionError):
        market.install("demo.tool", (), lambda e: called.append(e.id))
    with pytest.raises(PermissionError):
        market.install("untested", (), lambda e: called.append(e.id))
    assert called == []
    assert market.installation_decision("demo.tool")["allowed"] is False


def test_never_permission_is_always_blocked(tmp_path):
    market = _market(tmp_path)
    market.publish(_entry(id="dangerous", permissions=("security.bypass",)))
    decision = market.installation_decision("dangerous")
    assert decision["allowed"] is False
    assert any("never allowed" in reason for reason in decision["reasons"])
    assert market.can_install("dangerous", ("security.bypass",)) is False


def test_confirmation_scope_requires_explicit_grant(tmp_path):
    market = _market(tmp_path)
    market.publish(_entry(id="installer", permissions=("system.package_install",)))
    assert market.can_install("installer", ()) is False
    assert market.installation_decision("installer")["requires_confirmation"] is True
    assert market.can_install("installer", ("system.package_install",)) is True


def test_install_delegates_and_records_without_executing_code(tmp_path):
    market = _market(tmp_path)
    market.publish(_entry())
    calls = []
    out = market.install("demo.tool", ("workspace.read",), lambda e: calls.append(e.id) or "ok")
    assert out == "ok"
    assert calls == ["demo.tool"]
    record = market.registry.get("demo.tool")
    assert record is not None
    assert record.status == "installed"
    assert record.source == "marketplace"


def test_import_existing_registry_is_conservative(tmp_path):
    registry = CapabilityRegistry(root=tmp_path)
    registry.upsert(
        CapabilityRecord(name="existing", version="2.0", status="verified", health="healthy")
    )
    market = CapabilityMarketplace(registry=registry)
    assert market.import_registry() == 1
    assert market.get("existing").security_review_status == "unreviewed"
    assert market.can_install("existing", ()) is False


def test_validation_rejects_duplicate_and_bad_metadata(tmp_path):
    market = _market(tmp_path)
    market.publish(_entry())
    with pytest.raises(ValueError):
        market.publish(_entry())
    with pytest.raises(ValueError):
        market.publish(_entry(id="bad", security_review_status="trusted-by-default"))
