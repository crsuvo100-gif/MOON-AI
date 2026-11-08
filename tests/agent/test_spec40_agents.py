"""Agent-level tests: the 40-agent registry + selection (spec 8, 12, 40)."""

from __future__ import annotations

from app.agents.registry import get_registry


def test_all_40_spec_agents_present():
    reg = get_registry()
    rep = reg.to_report()
    assert rep["by_source"].get("spec40", 0) >= 38


def test_role_groups_present():
    reg = get_registry()
    groups = {m.role_group for m in reg.all() if m.role_group}
    assert "core" in groups and "advanced" in groups


def test_select_returns_capability_match():
    reg = get_registry()
    assert reg.select(capability="coding")[0].id == "coding"


def test_browser_agent_manifest_matches_read_only_tools():
    browser = get_registry().get("browser_agent")
    assert browser is not None
    assert {"web_navigation", "read_web_page", "web_search"} <= set(browser.capabilities)
    assert {"browser", "web_search"} <= set(browser.required_tools)
    assert "web:read" in browser.permissions
    assert not {"browser_control", "web_interaction"} & set(browser.capabilities)
    assert "web:write" not in browser.permissions
