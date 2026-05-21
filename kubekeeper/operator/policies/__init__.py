"""Policy package: re-exports base API and auto-registers all built-in policies."""
from .base import (  # noqa: F401
    Policy,
    Violation,
    RemediationTier,
    Severity,
    register,
    get_policy,
    all_policies,
)

# Each import triggers the module's @register decorator, populating the registry.
from . import resource_limits  # noqa: F401
from . import liveness_probe   # noqa: F401
from . import image_tag        # noqa: F401
from . import privileged       # noqa: F401
from . import hpa_zero         # noqa: F401
