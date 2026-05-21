"""Unit tests for all five built-in drift policies.

These tests are pure Python — no Kubernetes cluster required.
The kubernetes API clients are replaced with MagicMock objects.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from kubekeeper.operator.policies.base import RemediationTier, Severity
from kubekeeper.operator.policies.hpa_zero import HpaZeroPolicy
from kubekeeper.operator.policies.image_tag import ImageTagPolicy
from kubekeeper.operator.policies.liveness_probe import LivenessProbePolicy
from kubekeeper.operator.policies.privileged import PrivilegedPolicy
from kubekeeper.operator.policies.resource_limits import ResourceLimitsPolicy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _container(
    name: str = "app",
    image: str = "nginx:1.25",
    cpu_limit: str | None = None,
    mem_limit: str | None = None,
    liveness_probe=None,
    privileged: bool | None = None,
) -> MagicMock:
    c = MagicMock()
    c.name = name
    c.image = image
    c.liveness_probe = liveness_probe

    limits: dict = {}
    if cpu_limit:
        limits["cpu"] = cpu_limit
    if mem_limit:
        limits["memory"] = mem_limit
    c.resources = MagicMock()
    c.resources.limits = limits or None

    if privileged is not None:
        c.security_context = MagicMock()
        c.security_context.privileged = privileged
    else:
        c.security_context = None

    return c


def _deployment(name: str = "my-deploy", namespace: str = "default", containers=None) -> MagicMock:
    dep = MagicMock()
    dep.metadata.name = name
    dep.metadata.namespace = namespace
    dep.spec.template.spec.containers = containers or [_container()]
    return dep


def _hpa(name: str = "my-hpa", namespace: str = "default", min_replicas: int | None = 1) -> MagicMock:
    hpa = MagicMock()
    hpa.metadata.name = name
    hpa.metadata.namespace = namespace
    hpa.spec.min_replicas = min_replicas
    return hpa


def _apps_v1(deployments=(), statefulsets=()):
    api = MagicMock()
    api.list_deployment_for_all_namespaces.return_value = MagicMock(items=list(deployments))
    api.list_stateful_set_for_all_namespaces.return_value = MagicMock(items=list(statefulsets))
    return api


# ---------------------------------------------------------------------------
# ResourceLimitsPolicy
# ---------------------------------------------------------------------------

class TestResourceLimitsPolicy:
    def test_no_violation_when_both_limits_set(self):
        policy = ResourceLimitsPolicy()
        dep = _deployment(containers=[_container(cpu_limit="500m", mem_limit="512Mi")])
        clients = {"apps_v1": _apps_v1(deployments=[dep])}

        assert policy.check(clients) == []

    def test_violation_when_no_limits(self):
        policy = ResourceLimitsPolicy()
        dep = _deployment(containers=[_container()])
        clients = {"apps_v1": _apps_v1(deployments=[dep])}

        violations = policy.check(clients)
        assert len(violations) == 1
        v = violations[0]
        assert v.policy_name == "require-resource-limits"
        assert v.resource_kind == "Deployment"
        assert v.resource_name == "my-deploy"
        assert v.namespace == "default"
        assert v.tier == RemediationTier.AUTO
        assert v.severity == Severity.WARNING
        assert v.context["container_name"] == "app"

    def test_violation_when_only_cpu_limit_set(self):
        policy = ResourceLimitsPolicy()
        dep = _deployment(containers=[_container(cpu_limit="500m")])
        clients = {"apps_v1": _apps_v1(deployments=[dep])}

        violations = policy.check(clients)
        assert len(violations) == 1

    def test_violation_when_only_mem_limit_set(self):
        policy = ResourceLimitsPolicy()
        dep = _deployment(containers=[_container(mem_limit="512Mi")])
        clients = {"apps_v1": _apps_v1(deployments=[dep])}

        violations = policy.check(clients)
        assert len(violations) == 1

    def test_multiple_containers_each_produce_violation(self):
        policy = ResourceLimitsPolicy()
        dep = _deployment(containers=[
            _container(name="app"),
            _container(name="sidecar"),
        ])
        clients = {"apps_v1": _apps_v1(deployments=[dep])}

        violations = policy.check(clients)
        assert len(violations) == 2
        container_names = {v.context["container_name"] for v in violations}
        assert container_names == {"app", "sidecar"}

    def test_api_error_is_swallowed_gracefully(self):
        policy = ResourceLimitsPolicy()
        api = MagicMock()
        api.list_deployment_for_all_namespaces.side_effect = Exception("connection refused")
        api.list_stateful_set_for_all_namespaces.return_value = MagicMock(items=[])
        clients = {"apps_v1": api}

        violations = policy.check(clients)
        assert violations == []


# ---------------------------------------------------------------------------
# LivenessProbePolicy
# ---------------------------------------------------------------------------

class TestLivenessProbePolicy:
    def test_no_violation_when_probe_defined(self):
        policy = LivenessProbePolicy()
        probe = MagicMock()
        dep = _deployment(containers=[_container(liveness_probe=probe)])
        clients = {"apps_v1": _apps_v1(deployments=[dep])}

        assert policy.check(clients) == []

    def test_violation_when_no_probe(self):
        policy = LivenessProbePolicy()
        dep = _deployment(containers=[_container(liveness_probe=None)])
        clients = {"apps_v1": _apps_v1(deployments=[dep])}

        violations = policy.check(clients)
        assert len(violations) == 1
        v = violations[0]
        assert v.policy_name == "require-liveness-probes"
        assert v.tier == RemediationTier.ALERT_ONLY

    def test_remediate_is_noop(self):
        policy = LivenessProbePolicy()
        from kubekeeper.operator.policies.base import Violation
        v = Violation(
            policy_name=policy.name,
            resource_kind="Deployment",
            resource_name="x",
            namespace="default",
            message="",
            severity=Severity.WARNING,
            tier=RemediationTier.ALERT_ONLY,
        )
        assert policy.remediate(v, {}) is False


# ---------------------------------------------------------------------------
# ImageTagPolicy
# ---------------------------------------------------------------------------

class TestImageTagPolicy:
    @pytest.mark.parametrize("image", ["nginx:latest", "nginx", "myrepo/app"])
    def test_violation_for_unpinned_tag(self, image: str):
        policy = ImageTagPolicy()
        dep = _deployment(containers=[_container(image=image)])
        clients = {"apps_v1": _apps_v1(deployments=[dep])}

        violations = policy.check(clients)
        assert len(violations) == 1
        assert violations[0].policy_name == "no-latest-image-tag"
        assert violations[0].tier == RemediationTier.ALERT_ONLY

    @pytest.mark.parametrize("image", [
        "nginx:1.25",
        "nginx:1.25.3",
        "myrepo/app:v2.3.1",
        "ghcr.io/org/app:sha-abc1234",
    ])
    def test_no_violation_for_pinned_tag(self, image: str):
        policy = ImageTagPolicy()
        dep = _deployment(containers=[_container(image=image)])
        clients = {"apps_v1": _apps_v1(deployments=[dep])}

        assert policy.check(clients) == []


# ---------------------------------------------------------------------------
# PrivilegedPolicy
# ---------------------------------------------------------------------------

class TestPrivilegedPolicy:
    def test_no_violation_when_not_privileged(self):
        policy = PrivilegedPolicy()
        dep = _deployment(containers=[_container(privileged=False)])
        clients = {"apps_v1": _apps_v1(deployments=[dep])}

        assert policy.check(clients) == []

    def test_no_violation_when_security_context_absent(self):
        policy = PrivilegedPolicy()
        dep = _deployment(containers=[_container()])  # security_context=None
        clients = {"apps_v1": _apps_v1(deployments=[dep])}

        assert policy.check(clients) == []

    def test_violation_when_privileged_true(self):
        policy = PrivilegedPolicy()
        dep = _deployment(containers=[_container(privileged=True)])
        clients = {"apps_v1": _apps_v1(deployments=[dep])}

        violations = policy.check(clients)
        assert len(violations) == 1
        v = violations[0]
        assert v.policy_name == "no-privileged-containers"
        assert v.tier == RemediationTier.AUTO
        assert v.severity == Severity.ERROR
        assert v.context["container_name"] == "app"


# ---------------------------------------------------------------------------
# HpaZeroPolicy
# ---------------------------------------------------------------------------

class TestHpaZeroPolicy:
    def test_no_violation_when_min_replicas_is_one(self):
        policy = HpaZeroPolicy()
        api = MagicMock()
        api.list_horizontal_pod_autoscaler_for_all_namespaces.return_value = MagicMock(
            items=[_hpa(min_replicas=1)]
        )
        assert policy.check({"autoscaling_v2": api}) == []

    def test_no_violation_when_min_replicas_is_none(self):
        policy = HpaZeroPolicy()
        api = MagicMock()
        api.list_horizontal_pod_autoscaler_for_all_namespaces.return_value = MagicMock(
            items=[_hpa(min_replicas=None)]
        )
        assert policy.check({"autoscaling_v2": api}) == []

    def test_violation_when_min_replicas_is_zero(self):
        policy = HpaZeroPolicy()
        api = MagicMock()
        api.list_horizontal_pod_autoscaler_for_all_namespaces.return_value = MagicMock(
            items=[_hpa(min_replicas=0)]
        )
        violations = policy.check({"autoscaling_v2": api})
        assert len(violations) == 1
        v = violations[0]
        assert v.policy_name == "hpa-never-zero"
        assert v.resource_kind == "HorizontalPodAutoscaler"
        assert v.tier == RemediationTier.AUTO
        assert v.severity == Severity.ERROR

    def test_no_violation_when_min_replicas_above_one(self):
        policy = HpaZeroPolicy()
        api = MagicMock()
        api.list_horizontal_pod_autoscaler_for_all_namespaces.return_value = MagicMock(
            items=[_hpa(min_replicas=3)]
        )
        assert policy.check({"autoscaling_v2": api}) == []
