"""Policy: no-privileged-containers — auto-patches privileged=true to false."""
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
class PrivilegedPolicy(Policy):
    name = "no-privileged-containers"
    description = "Containers must not run with securityContext.privileged=true"
    default_tier = RemediationTier.AUTO
    default_severity = Severity.ERROR

    def check(self, api_clients: dict) -> list[Violation]:
        apps_v1: k8s.AppsV1Api = api_clients["apps_v1"]
        violations: list[Violation] = []

        workloads = [
            ("Deployment", apps_v1.list_deployment_for_all_namespaces),
            ("StatefulSet", apps_v1.list_stateful_set_for_all_namespaces),
        ]
        for kind, list_fn in workloads:
            try:
                resources = list_fn()
            except Exception as exc:
                log.warning("Failed to list %ss: %s", kind, exc)
                continue

            for res in resources.items:
                for container in res.spec.template.spec.containers or []:
                    is_privileged = (
                        container.security_context is not None
                        and container.security_context.privileged is True
                    )
                    if is_privileged:
                        violations.append(
                            Violation(
                                policy_name=self.name,
                                resource_kind=kind,
                                resource_name=res.metadata.name,
                                namespace=res.metadata.namespace,
                                message=(
                                    f"Container '{container.name}' has "
                                    "securityContext.privileged=true"
                                ),
                                severity=self.default_severity,
                                tier=self.default_tier,
                                context={"container_name": container.name},
                            )
                        )
        return violations

    def remediate(self, violation: Violation, api_clients: dict) -> bool:
        apps_v1: k8s.AppsV1Api = api_clients["apps_v1"]
        container_name = violation.context.get("container_name", "")
        patch = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": container_name,
                                "securityContext": {"privileged": False},
                            }
                        ]
                    }
                }
            }
        }
        try:
            if violation.resource_kind == "Deployment":
                apps_v1.patch_namespaced_deployment(
                    name=violation.resource_name,
                    namespace=violation.namespace,
                    body=patch,
                )
            else:
                apps_v1.patch_namespaced_stateful_set(
                    name=violation.resource_name,
                    namespace=violation.namespace,
                    body=patch,
                )
            return True
        except Exception as exc:
            log.error(
                "Failed to remove privileged mode from %s/%s: %s",
                violation.namespace,
                violation.resource_name,
                exc,
            )
            return False
