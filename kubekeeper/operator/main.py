"""KubeKeeper operator — kopf entry point and reconciliation timer.

The operator watches ``DriftPolicy`` custom resources.  For each active
DriftPolicy, kopf calls ``reconcile_policy`` every 60 seconds.  The handler
looks up the named built-in policy, runs its check against the live cluster,
and — for ``auto`` tier violations — applies the remediation and records the
result as a ``RemediationHistory`` custom resource.
"""
from __future__ import annotations

import logging

import kopf
import kubernetes

from kubekeeper.operator import policies as _policies_pkg  # noqa: F401 – triggers @register
from kubekeeper.operator.crd import GROUP, VERSION, DRIFT_POLICY_PLURAL, record_remediation
from kubekeeper.operator.policies.base import RemediationTier, get_policy

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Kubernetes client initialisation
# ---------------------------------------------------------------------------

def _load_kubeconfig() -> None:
    try:
        kubernetes.config.load_incluster_config()
        log.info("Loaded in-cluster kubeconfig")
    except kubernetes.config.ConfigException:
        kubernetes.config.load_kube_config()
        log.info("Loaded local kubeconfig")


def _api_clients() -> dict:
    return {
        "apps_v1": kubernetes.client.AppsV1Api(),
        "autoscaling_v2": kubernetes.client.AutoscalingV2Api(),
        "core_v1": kubernetes.client.CoreV1Api(),
        "custom_objects": kubernetes.client.CustomObjectsApi(),
    }


# ---------------------------------------------------------------------------
# Lifecycle hooks
# ---------------------------------------------------------------------------

@kopf.on.startup()
def on_startup(settings: kopf.OperatorSettings, logger, **_kwargs) -> None:
    _load_kubeconfig()
    settings.persistence.finalizer = "kubekeeper.io/finalizer"
    logger.info("KubeKeeper operator started — watching DriftPolicy resources")


# ---------------------------------------------------------------------------
# DriftPolicy reconciliation timer
# ---------------------------------------------------------------------------

@kopf.timer(
    GROUP,
    VERSION,
    DRIFT_POLICY_PLURAL,
    interval=60.0,
    initial_delay=5.0,
    idle_timeout=None,
)
def reconcile_policy(spec: kopf.Spec, name: str, namespace: str, logger, **_kwargs) -> None:
    """Run one DriftPolicy's check and remediate any auto-tier violations."""
    check_name: str = spec.get("check", "")
    tier_override: str = spec.get("remediation", {}).get("tier", "")

    policy = get_policy(check_name)
    if policy is None:
        logger.warning("DriftPolicy %r references unknown built-in: %r", name, check_name)
        return

    clients = _api_clients()

    try:
        violations = policy.check(clients)
    except Exception as exc:
        logger.error("Policy check %r failed: %s", check_name, exc)
        return

    if not violations:
        logger.debug("Policy %r: no violations found", check_name)
        return

    logger.info("Policy %r: %d violation(s) found", check_name, len(violations))

    for violation in violations:
        effective_tier = RemediationTier(tier_override) if tier_override else violation.tier

        if effective_tier != RemediationTier.AUTO:
            logger.info(
                "Violation %s/%s [tier=%s] — no action taken",
                violation.resource_kind,
                violation.resource_name,
                effective_tier.value,
            )
            continue

        logger.info(
            "Auto-remediating %s %s/%s for policy %r",
            violation.resource_kind,
            violation.namespace,
            violation.resource_name,
            check_name,
        )
        try:
            success = policy.remediate(violation, clients)
        except Exception as exc:
            logger.error("Remediation raised an exception for %s: %s", violation.resource_name, exc)
            success = False

        record_remediation(
            violation=violation,
            action="auto-patch",
            status="success" if success else "failed",
            custom_objects=clients["custom_objects"],
            namespace=namespace,
        )
