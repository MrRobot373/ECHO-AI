"""Per-session permission store, updated from the UI menu toggles."""
from __future__ import annotations


class PermissionStore:
    def __init__(self) -> None:
        self._perms: dict[str, bool] = {}

    def update(self, perms: dict) -> None:
        for key, value in (perms or {}).items():
            self._perms[str(key)] = bool(value)

    def allowed(self, key: str | None) -> bool:
        # Default-allow: a permission is only off if explicitly toggled off.
        if not key:
            return True
        return self._perms.get(key, True)
