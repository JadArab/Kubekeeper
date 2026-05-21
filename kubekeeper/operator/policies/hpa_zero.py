"""Policy: hpa-never-zero — auto-patches HPA minReplicas < 1 to 1."""
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
class HpaZeroPolicy(Policy):
    name = "hpa-never-zero"
    description = "HorizontalPodAutoscalers must have minReplicas >= 1"
    default_tier = RemediationTier.AUTO
    default_severity = Severity.ERROR

    def check(self, api_clients: dict) -> list[Violation]:
        autoscaling_v2: k8s.AutoscalingV2Api = api_clients["autoscaling_v2"]
        violations: list[Violation] = []
        try:
            hpas = autoscaling_v2.list_horizontal_pod_autoscaler_for_all_namespaces()
        except Exception as exc:
            log.warning("Failed to list HorizontalPodAutoscalers: %s", exc)
            return violations

        for hpa in hpas.items:
            min_replicas = hpa.spec.min_replicas
            # None means the field is unset, which Kubernetes treats as 1 — not a violation.
            if min_replicas is not None and min_replicas < 1:
                violations.append(
                    Violation(
                        policy_name=self.name,
                        resource_kind="HorizontalPodAutoscaler",
                        resource_name=hpa.metadata.name,
                        namespace=hpa.metadata.namespace,
                        message=f"HPA minReplicas={min_replicas}, must be >= 1",
                        severity=self.default_severity,
                        tier=self.default_tier,
                    )
                )
        return violations

    def remediate(self, violation: Violation, api_clients: dict) -> bool:
        autoscaling_v2: k8s.AutoscalingV2Api = api_clients["autoscaling_v2"]
        try:
            autoscaling_v2.patch_namespaced_horizontal_pod_autoscaler(
                name=violation.resource_name,
                namespace=violation.namespace,
                body={"spec": {"minReplicas": 1}},
            )
            return True
        except Exception as exc:
            log.error(
                "Failed to patch HPA %s/%s minReplicas: %s",
                violation.namespace,
                violation.resource_name,
                exc,
            )
            return False
