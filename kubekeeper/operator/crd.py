"""Operations on KubeKeeper custom resources (RemediationHistory, DriftPolicy)."""
from __future__ import annotations

import datetime
import logging
import re
from typing import Optional

from kubernetes import client as k8s

from kubekeeper.operator.policies.base import Violation

log = logging.getLogger(__name__)

GROUP = "kubekeeper.io"
VERSION = "v1alpha1"
REMEDIATION_HISTORY_PLURAL = "remediationhistories"
DRIFT_POLICY_PLURAL = "driftpolicies"

OPERATOR_NAMESPACE = "kubekeeper-system"


def record_remediation(
    violation: Violation,
    action: str,
    status: str,
    custom_objects: k8s.CustomObjectsApi,
    namespace: str = OPERATOR_NAMESPACE,
) -> None:
    """Create a RemediationHistory custom resource for one remediation event."""
    name = _history_name(violation)
    body = {
        "apiVersion": f"{GROUP}/{VERSION}",
        "kind": "RemediationHistory",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "policyName": violation.policy_name,
            "resourceKind": violation.resource_kind,
            "resourceName": violation.resource_name,
            "resourceNamespace": violation.namespace,
            "violationMessage": violation.message,
            "severity": violation.severity.value,
            "action": action,
            "status": status,
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        },
    }
    try:
        custom_objects.create_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            namespace=namespace,
            plural=REMEDIATION_HISTORY_PLURAL,
            body=body,
        )
        log.info("Recorded RemediationHistory %s (status=%s)", name, status)
    except k8s.exceptions.ApiException as exc:
        log.error("Failed to create RemediationHistory %s: %s", name, exc)
    except Exception as exc:
        log.error("Unexpected error writing RemediationHistory %s: %s", name, exc)


def list_remediations(
    custom_objects: k8s.CustomObjectsApi,
    namespace: str = OPERATOR_NAMESPACE,
) -> list[dict]:
    """Return all RemediationHistory records from the given namespace."""
    try:
        result = custom_objects.list_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            namespace=namespace,
            plural=REMEDIATION_HISTORY_PLURAL,
        )
        items = result.get("items", [])
        # Sort newest-first by timestamp field.
        items.sort(key=lambda r: r.get("spec", {}).get("timestamp", ""), reverse=True)
        return items
    except Exception as exc:
        log.error("Failed to list RemediationHistory resources: %s", exc)
        return []


def list_drift_policies(
    custom_objects: k8s.CustomObjectsApi,
    namespace: str = OPERATOR_NAMESPACE,
) -> list[dict]:
    """Return all DriftPolicy resources from the given namespace."""
    try:
        result = custom_objects.list_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            namespace=namespace,
            plural=DRIFT_POLICY_PLURAL,
        )
        return result.get("items", [])
    except Exception as exc:
        log.error("Failed to list DriftPolicy resources: %s", exc)
        return []


def _history_name(violation: Violation) -> str:
    """Generate a unique, RFC-1123-compliant name for a RemediationHistory record."""
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    policy_slug = _slugify(violation.policy_name)[:20]
    resource_slug = _slugify(violation.resource_name)[:20]
    name = f"{policy_slug}-{resource_slug}-{timestamp}"
    return name[:63].strip("-")


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9-]", "-", value.lower())
