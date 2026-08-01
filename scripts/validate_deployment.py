from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import yaml

_BASE = Path("deploy/kubernetes/base")


def _yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain one YAML object")
    return cast(dict[str, Any], payload)


def _named(items: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for item in items:
        if item.get("name") == name:
            return item
    raise ValueError(f"required named item is missing: {name}")


def validate() -> dict[str, object]:
    deployment = _yaml(_BASE / "deployment.yaml")
    service_account = _yaml(_BASE / "service-account.yaml")
    network_policy = _yaml(_BASE / "network-policy.yaml")
    pdb = _yaml(_BASE / "pdb.yaml")
    hpa = _yaml(_BASE / "hpa.yaml")
    collector = _yaml(Path("deploy/observability/otel-collector.yaml"))
    rules = _yaml(Path("deploy/observability/prometheus-rules.yaml"))
    dashboard = json.loads(
        Path("deploy/observability/grafana-dashboard.json").read_text(encoding="utf-8")
    )

    spec = deployment["spec"]
    pod_spec = spec["template"]["spec"]
    container = _named(pod_spec["containers"], "api")
    container_security = container["securityContext"]
    pod_security = pod_spec["securityContext"]
    image = str(container["image"])

    assert deployment["kind"] == "Deployment"
    assert spec["replicas"] >= 2
    assert image != "" and not image.endswith(":latest")
    assert pod_spec["automountServiceAccountToken"] is False
    assert pod_security["runAsNonRoot"] is True
    assert pod_security["seccompProfile"]["type"] == "RuntimeDefault"
    assert container_security["allowPrivilegeEscalation"] is False
    assert container_security["readOnlyRootFilesystem"] is True
    assert "ALL" in container_security["capabilities"]["drop"]
    assert {"startupProbe", "livenessProbe", "readinessProbe"} <= set(container)
    assert {"requests", "limits"} <= set(container["resources"])
    assert service_account["automountServiceAccountToken"] is False
    assert set(network_policy["spec"]["policyTypes"]) == {"Ingress", "Egress"}
    assert pdb["spec"]["minAvailable"] >= 1
    assert hpa["spec"]["minReplicas"] >= 2
    assert hpa["spec"]["maxReplicas"] >= hpa["spec"]["minReplicas"]

    privacy_actions = collector["processors"]["attributes/privacy"]["actions"]
    deleted_attributes = {action["key"] for action in privacy_actions}
    assert {"http.request.header.authorization", "enduser.id"} <= deleted_attributes
    alert_names = {
        rule["alert"] for group in rules["groups"] for rule in group["rules"] if "alert" in rule
    }
    assert {
        "OpsPilotAvailabilityBurnRateHigh",
        "OpsPilotWorkflowErrors",
        "OpsPilotLeaseRecoveries",
    } <= alert_names
    assert len(dashboard["panels"]) >= 6

    return {
        "container_image": image,
        "replicas": spec["replicas"],
        "alerts": sorted(alert_names),
        "dashboard_panels": len(dashboard["panels"]),
        "status": "passed",
    }


def main() -> None:
    print(json.dumps(validate(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
