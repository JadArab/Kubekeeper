"""Base classes and registry for KubeKeeper drift policies."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class RemediationTier(str, Enum):
    AUTO = "auto"
    APPROVAL = "approval"
    ALERT_ONLY = "alert-only"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Violation:
    policy_name: str
    resource_kind: str
    resource_name: str
    namespace: str
    message: str
    severity: Severity
    tier: RemediationTier
    # Arbitrary per-violation data needed by remediate() (e.g. container_name).
    context: dict = field(default_factory=dict)


class Policy:
    """Base class for all built-in drift policies.

    Subclasses must set class-level ``name``, ``description``,
    ``default_tier``, and ``default_severity``, then implement ``check()``.
    Policies that support auto-remediation also implement ``remediate()``.
    """

    name: str
    description: str
    default_tier: RemediationTier
    default_severity: Severity

    def check(self, api_clients: dict) -> list[Violation]:
        """Scan the cluster and return any violations found."""
        raise NotImplementedError

    def remediate(self, violation: Violation, api_clients: dict) -> bool:
        """Apply the fix for a violation. Returns True on success."""
        return False


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, Policy] = {}


def register(cls: type[Policy]) -> type[Policy]:
    """Class decorator that adds a Policy subclass to the registry."""
    instance = cls()
    _REGISTRY[instance.name] = instance
    return cls


def get_policy(name: str) -> Optional[Policy]:
    return _REGISTRY.get(name)


def all_policies() -> list[Policy]:
    return list(_REGISTRY.values())
