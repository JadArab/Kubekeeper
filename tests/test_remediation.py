"""Unit tests for remediation logic — verifies correct Kubernetes API calls."""
from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from kubekeeper.operator.policies.base import RemediationTier, Severity, Violation
from kubekeeper.operator.policies.hpa_zero import HpaZeroPolicy
from kubekeeper.operator.policies.privileged import PrivilegedPolicy
from kubekeeper.operator.policies.resource_limits import ResourceLimitsPolicy


def _violation(
    policy_name: str,
    resource_kind: str = "Deployment",
    resource_name: str = "my-deploy",
    namespace: str = "default",
    tier: RemediationTier = RemediationTier.AUTO,
    severity: Severity = Severity.WARNING,
    context: dict | None = None,
) -> Violation:
    return Violation(
        policy_name=policy_name,
        resource_kind=resource_kind,
        resource_name=resource_name,
        namespace=namespace,
        message="test violation",
        severity=severity,
        tier=tier,
        context=context or {},
    )


# ---------------------------------------------------------------------------
# ResourceLimitsPolicy.remediate
# ---------------------------------------------------------------------------

class TestResourceLimitsRemediate:
    def test_patches_deployment_with_default_limits(self):
        policy = ResourceLimitsPolicy()
        v = _violation(
            policy_name="require-resource-limits",
            resource_kind="Deployment",
            context={"container_name": "app"},
        )
        apps_v1 = MagicMock()
        assert policy.remediate(v, {"apps_v1": apps_v1}) is True
        apps_v1.patch_namespaced_deployment.assert_called_once()
        _, kwargs = apps_v1.patch_namespaced_deployment.call_args
        assert kwargs["name"] == "my-deploy"
        assert kwargs["namespace"] == "default"
        containers = kwargs["body"]["spec"]["template"]["spec"]["containers"]
        assert containers[0]["name"] == "app"
        assert containers[0]["resources"]["limits"]["cpu"] == "500m"
        assert containers[0]["resources"]["limits"]["memory"] == "512Mi"

    def test_patches_statefulset(self):
        policy = ResourceLimitsPolicy()
        v = _violation(
            policy_name="require-resource-limits",
            resource_kind="StatefulSet",
            context={"container_name": "db"},
        )
        apps_v1 = MagicMock()
        assert policy.remediate(v, {"apps_v1": apps_v1}) is True
        apps_v1.patch_namespaced_stateful_set.assert_called_once()
        apps_v1.patch_namespaced_deployment.assert_not_called()

    def test_returns_false_on_api_error(self):
        policy = ResourceLimitsPolicy()
        v = _violation("require-resource-limits", context={"container_name": "app"})
        apps_v1 = MagicMock()
        apps_v1.patch_namespaced_deployment.side_effect = Exception("forbidden")
        assert policy.remediate(v, {"apps_v1": apps_v1}) is False


# ---------------------------------------------------------------------------
# PrivilegedPolicy.remediate
# ---------------------------------------------------------------------------

class TestPrivilegedRemediate:
    def test_patches_deployment_to_non_privileged(self):
        policy = PrivilegedPolicy()
        v = _violation(
            policy_name="no-privileged-containers",
            resource_kind="Deployment",
            severity=Severity.ERROR,
            context={"container_name": "app"},
        )
        apps_v1 = MagicMock()
        assert policy.remediate(v, {"apps_v1": apps_v1}) is True
        apps_v1.patch_namespaced_deployment.assert_called_once()
        _, kwargs = apps_v1.patch_namespaced_deployment.call_args
        containers = kwargs["body"]["spec"]["template"]["spec"]["containers"]
        assert containers[0]["name"] == "app"
        assert containers[0]["securityContext"]["privileged"] is False

    def test_returns_false_on_api_error(self):
        policy = PrivilegedPolicy()
        v = _violation("no-privileged-containers", severity=Severity.ERROR, context={"container_name": "app"})
        apps_v1 = MagicMock()
        apps_v1.patch_namespaced_deployment.side_effect = Exception("forbidden")
        assert policy.remediate(v, {"apps_v1": apps_v1}) is False


# ---------------------------------------------------------------------------
# HpaZeroPolicy.remediate
# ---------------------------------------------------------------------------

class TestHpaZeroRemediate:
    def test_patches_min_replicas_to_one(self):
        policy = HpaZeroPolicy()
        v = _violation(
            policy_name="hpa-never-zero",
            resource_kind="HorizontalPodAutoscaler",
            severity=Severity.ERROR,
        )
        autoscaling_v2 = MagicMock()
        assert policy.remediate(v, {"autoscaling_v2": autoscaling_v2}) is True
        autoscaling_v2.patch_namespaced_horizontal_pod_autoscaler.assert_called_once_with(
            name="my-deploy",
            namespace="default",
            body={"spec": {"minReplicas": 1}},
        )

    def test_returns_false_on_api_error(self):
        policy = HpaZeroPolicy()
        v = _violation("hpa-never-zero", resource_kind="HorizontalPodAutoscaler", severity=Severity.ERROR)
        autoscaling_v2 = MagicMock()
        autoscaling_v2.patch_namespaced_horizontal_pod_autoscaler.side_effect = Exception("forbidden")
        assert policy.remediate(v, {"autoscaling_v2": autoscaling_v2}) is False
