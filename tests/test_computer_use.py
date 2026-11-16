"""Phase-2 computer-use adapter tests (no display server required)."""

import pytest

from app.tools.computer_use import (
    ActionRejectedError,
    NoDisplayAdapter,
    NoDisplayServerError,
    PlaywrightComputerUseAdapter,
    compute_preflight,
    parse_target,
    validate_action,
)


class _FakePermissions:
    """Permission manager stub used to exercise the preflight policy."""

    def __init__(self, *, egress: dict[str, bool] | None = None) -> None:
        self._egress = egress or {}

    def egress_decision(self, host: str, scope: str = "network.egress"):
        allowed = self._egress.get(host, False)
        return type(  # noqa: E272
            "Decision",
            (),
            {"allowed": allowed, "tier": "SAFE" if allowed else "CONFIRMATION", "reason": "ok"},
        )()


@pytest.mark.parametrize(
    "target, expected_kind, expected_id",
    [
        ("url/https://example.org/page", "url", "https://example.org/page"),
        ("view/button/Submit", "view", "button/Submit"),
        ("screen/0", "screen", "0"),
        ("window/terminal/foo", "window", "terminal/foo"),
        ("https://example.org", "url", "https://example.org"),
    ],
)
def test_parse_target(target, expected_kind, expected_id):
    assert parse_target(target) == {"kind": expected_kind, "id": expected_id}


def test_parse_target_rejects_unknown_shape():
    with pytest.raises(ActionRejectedError):
        parse_target("not-a-target")


@pytest.mark.parametrize("action", ["take_screenshot", "read_screen_text", "scroll", "click", "hover"])
def test_validate_action_accepts_allowed(action):
    assert validate_action(action) == action


def test_validate_action_rejects_unsafe():
    with pytest.raises(ActionRejectedError):
        validate_action("press_key")
    with pytest.raises(ActionRejectedError):
        validate_action("close_window")
    with pytest.raises(ActionRejectedError):
        validate_action("drag")


@pytest.mark.asyncio
async def test_compute_preflight_rejects_keyboard_without_confirmation():
    with pytest.raises(ActionRejectedError):
        compute_preflight("press_key", "screen/0", _FakePermissions())


@pytest.mark.asyncio
async def test_preflight_allows_screenshot_without_confirmation():
    result = compute_preflight("take_screenshot", "screen/0", _FakePermissions())
    assert result.allowed and result.confirmed is False


@pytest.mark.asyncio
async def test_preflight_allows_allowlisted_target_without_confirmation():
    perms = _FakePermissions(egress={"example.org": True})
    result = compute_preflight("click", "url/https://example.org/page", perms)
    assert result.allowed and result.confirmed is False


@pytest.mark.asyncio
async def test_preflight_rejects_unknown_target():
    with pytest.raises(ActionRejectedError):
        compute_preflight("click", "bogus/target", _FakePermissions())


@pytest.mark.asyncio
async def test_no_display_adapter_is_configured_not_verified():
    adapter = NoDisplayAdapter()
    assert adapter.supported["note"] == "no display server in this sandbox"
    result = await adapter.preflight_action("click", "screen/0")
    assert not result.allowed
    action_result = await adapter.execute_action("take_screenshot", "screen/0")
    assert not action_result.success
    with pytest.raises(NoDisplayServerError):
        await adapter.inspect_screen()


async def test_playwright_adapter_property_reports_capabilities():
    adapter = PlaywrightComputerUseAdapter()
    try:
        await adapter._connect()
        assert adapter.supported["web_pointer"] is True
        assert adapter.supported["accessibility_tree"] is True
        # Desktop-screen actions are NOT reported as available.
        assert adapter.supported["desktop_screen_read"] is False
    finally:
        await adapter.close()
