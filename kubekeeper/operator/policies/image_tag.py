"""Policy: no-latest-image-tag — alert-only, no auto-fix."""
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
class ImageTagPolicy(Policy):
    name = "no-latest-image-tag"
    description = "Container images must not use 'latest' or an untagged reference"
    default_tier = RemediationTier.ALERT_ONLY
    default_severity = Severity.WARNING

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
                    image = container.image or ""
                    tag = image.split(":")[-1] if ":" in image else ""
                    if not tag or tag == "latest":
                        violations.append(
                            Violation(
                                policy_name=self.name,
                                resource_kind=kind,
                                resource_name=res.metadata.name,
                                namespace=res.metadata.namespace,
                                message=(
                                    f"Container '{container.name}' uses image '{image}' "
                                    "with an unpinned tag"
                                ),
                                severity=self.default_severity,
                                tier=self.default_tier,
                                context={"container_name": container.name, "image": image},
                            )
                        )
        return violations
