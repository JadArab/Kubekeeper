"""Policy: require-liveness-probes — alert-only, no auto-fix."""
from __future__ import annotations

import logging

from kubernetes import client as k8s

from kubekeeper.operator.policies.base import (
    Policy,
    RemediationTier,
    Severity,
    Violation,
    register,
)

log = logging.getLogger(__name__)


@register
class LivenessProbePolicy(Policy):
    name = "require-liveness-probes"
    description = "All containers in Deployments must define a livenessProbe"
    default_tier = RemediationTier.ALERT_ONLY
    default_severity = Severity.WARNING

    def check(self, api_clients: dict) -> list[Violation]:
        apps_v1: k8s.AppsV1Api = api_clients["apps_v1"]
        violations: list[Violation] = []
        try:
            deployments = apps_v1.list_deployment_for_all_namespaces()
        except Exception as exc:
            log.warning("Failed to list Deployments: %s", exc)
            return violations

        for dep in deployments.items:
            for container in dep.spec.template.spec.containers or []:
                if not container.liveness_probe:
                    violations.append(
                        Violation(
                            policy_name=self.name,
                            resource_kind="Deployment",
                            resource_name=dep.metadata.name,
                            namespace=dep.metadata.namespace,
                            message=f"Container '{container.name}' has no livenessProbe defined",
                            severity=self.default_severity,
                            tier=self.default_tier,
                            context={"container_name": container.name},
                        )
                    )
        return violations
