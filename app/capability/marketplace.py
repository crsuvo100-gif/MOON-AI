"""Capability Marketplace (V13 section 38) -- additive capability catalog.

The marketplace is a *catalog and approval boundary*, not an execution engine.
It reuses the existing CapabilityRegistry and PermissionManager and never
replaces or bypasses them.

Design rules (V13 38, 29-31):
  * Every entry carries publisher, version, requirements, permissions,
    dependencies, compatibility, security review status, test status and docs.
  * Unreviewed, rejected or untested entries can be listed but NOT installed.
  * NEVER-level permissions can never be granted; confirmation-level scopes
    require an explicit granted scope from the operator.
  * Installation is delegated to a supplied callback; this module never
    executes downloaded code itself.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from app.capability.permission_manager import PermissionManager, PolicyLevel
from app.capability.registry import CapabilityRecord, CapabilityRegistry

_REVIEWED = {"reviewed"}
_TESTED = {"passed"}
_VALID_REVIEW = {"unreviewed", "reviewed", "rejected"}
_VALID_TEST = {"not_tested", "passed", "failed"}


@dataclass(frozen=True)
class MarketplaceEntry:
    id: str
    name: str
    version: str = "unknown"
    publisher: str = "unknown"
    description: str = ""
    requirements: tuple[str, ...] = field(default_factory=tuple)
    permissions: tuple[str, ...] = field(default_factory=tuple)
    dependencies: tuple[str, ...] = field(default_factory=tuple)
    compatibility: str = "unknown"
    security_review_status: str = "unreviewed"
    test_status: str = "not_tested"
    documentation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MarketplaceEntry":
        known = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        payload = dict(data)
        for key in ("requirements", "permissions", "dependencies"):
            if key in payload and isinstance(payload[key], list):
                payload[key] = tuple(payload[key])
        return cls(**{k: v for k, v in payload.items() if k in known})

    def validate(self) -> None:
        if not self.id or not self.name:
            raise ValueError("marketplace entry requires id and name")
        if self.security_review_status not in _VALID_REVIEW:
            raise ValueError(f"invalid security_review_status: {self.security_review_status}")
        if self.test_status not in _VALID_TEST:
            raise ValueError(f"invalid test_status: {self.test_status}")


class CapabilityMarketplace:
    """Read-only-until-approved catalog backed by the existing registry."""

    def __init__(
        self,
        registry: CapabilityRegistry | None = None,
        permissions: PermissionManager | None = None,
    ) -> None:
        self.registry = registry or CapabilityRegistry()
        self.permissions = permissions or PermissionManager()
        self._entries: dict[str, MarketplaceEntry] = {}

    # -------------------------------------------------------------- catalog
    def publish(self, entry: MarketplaceEntry) -> MarketplaceEntry:
        entry.validate()
        if entry.id in self._entries:
            raise ValueError(f"duplicate marketplace id: {entry.id}")
        self._entries[entry.id] = entry
        return entry

    def get(self, entry_id: str) -> MarketplaceEntry | None:
        return self._entries.get(entry_id)

    def list(
        self,
        *,
        reviewed_only: bool = False,
        tested_only: bool = False,
    ) -> list[dict[str, Any]]:
        items = []
        for entry in self._entries.values():
            if reviewed_only and entry.security_review_status not in _REVIEWED:
                continue
            if tested_only and entry.test_status not in _TESTED:
                continue
            data = entry.to_dict()
            record = self.registry.get(entry.id)
            data["installation_status"] = record.status if record else "available"
            data["installable"] = self.can_install(entry.id, ())
            items.append(data)
        return sorted(items, key=lambda item: item["id"])

    def import_registry(self) -> int:
        """Expose existing registry records conservatively as unreviewed entries."""
        imported = 0
        for record in self.registry.all():
            if record.name in self._entries:
                continue
            self.publish(
                MarketplaceEntry(
                    id=record.name,
                    name=record.name,
                    version=record.version,
                    publisher=record.source,
                    description=record.notes or "Imported from capability registry",
                    permissions=record.permissions,
                    dependencies=record.dependencies,
                    compatibility=record.runtime,
                    security_review_status="unreviewed",
                    test_status="not_tested",
                    documentation="capabilities/registry.json",
                )
            )
            imported += 1
        return imported

    # ------------------------------------------------------------ approval
    def can_install(self, entry_id: str, granted_permissions: tuple[str, ...]) -> bool:
        entry = self._entries.get(entry_id)
        if entry is None:
            return False
        if entry.security_review_status not in _REVIEWED:
            return False
        if entry.test_status not in _TESTED:
            return False
        if any(
            self.permissions.level_for(p) is PolicyLevel.NEVER
            for p in entry.permissions
        ):
            return False
        return self.permissions.is_granted(entry.permissions, tuple(granted_permissions))

    def installation_decision(self, entry_id: str) -> dict[str, Any]:
        """Explain *why* an entry is blocked without exposing secrets."""
        entry = self._entries.get(entry_id)
        if entry is None:
            return {"allowed": False, "reason": "unknown entry"}
        reasons = []
        if entry.security_review_status not in _REVIEWED:
            reasons.append(f"security review status={entry.security_review_status}")
        if entry.test_status not in _TESTED:
            reasons.append(f"test status={entry.test_status}")
        for permission in entry.permissions:
            level = self.permissions.level_for(permission)
            if level is PolicyLevel.NEVER:
                reasons.append(f"permission '{permission}' is never allowed")
        return {
            "allowed": not reasons,
            "requires_confirmation": any(
                self.permissions.level_for(p) is PolicyLevel.CONFIRMATION
                for p in entry.permissions
            ),
            "reasons": reasons,
        }

    def install(
        self,
        entry_id: str,
        granted_permissions: tuple[str, ...],
        installer: Callable[[MarketplaceEntry], Any],
    ) -> Any:
        """Install through an explicit callback only after all gates pass."""
        if not self.can_install(entry_id, granted_permissions):
            raise PermissionError(
                f"installation of '{entry_id}' denied: "
                f"{self.installation_decision(entry_id)['reasons']}"
            )
        result = installer(self._entries[entry_id])
        self.registry.upsert(
            CapabilityRecord(
                name=entry_id,
                version=self._entries[entry_id].version,
                status="installed",
                source="marketplace",
                permissions=self._entries[entry_id].permissions,
                dependencies=self._entries[entry_id].dependencies,
            )
        )
        return result
