"""KubeKeeper CLI — Phase 1 commands: violations and history."""
from __future__ import annotations

import sys
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="kubekeeper",
    help="KubeKeeper — Kubernetes drift detection and auto-remediation.",
    no_args_is_help=True,
)
console = Console()
err_console = Console(stderr=True)


def _load_k8s() -> None:
    """Configure the kubernetes client (in-cluster or local kubeconfig)."""
    from kubernetes import config
    try:
        config.load_incluster_config()
    except config.ConfigException:
        try:
            config.load_kube_config()
        except config.ConfigException as exc:
            err_console.print(f"[red]Could not load kubeconfig: {exc}[/red]")
            raise typer.Exit(code=1)


def _build_api_clients() -> dict:
    from kubernetes import client
    return {
        "apps_v1": client.AppsV1Api(),
        "autoscaling_v2": client.AutoscalingV2Api(),
        "core_v1": client.CoreV1Api(),
        "custom_objects": client.CustomObjectsApi(),
    }


# ---------------------------------------------------------------------------
# violations
# ---------------------------------------------------------------------------

@app.command()
def violations(
    namespace: Optional[str] = typer.Option(
        None, "--namespace", "-n",
        help="Limit scan to a specific namespace (default: all namespaces).",
    ),
    policy: Optional[str] = typer.Option(
        None, "--policy", "-p",
        help="Only run the named built-in policy.",
    ),
) -> None:
    """Scan the cluster and print all active policy violations."""
    _load_k8s()

    # Import here so kubernetes client is configured first.
    from kubekeeper.operator import policies as _  # noqa: F401 — registers built-ins
    from kubekeeper.operator.policies.base import all_policies

    active_policies = all_policies()
    if policy:
        active_policies = [p for p in active_policies if p.name == policy]
        if not active_policies:
            err_console.print(f"[red]Unknown policy: {policy!r}[/red]")
            raise typer.Exit(code=1)

    clients = _build_api_clients()
    all_violations = []
    for p in active_policies:
        try:
            found = p.check(clients)
            all_violations.extend(found)
        except Exception as exc:
            err_console.print(f"[yellow]Warning: policy '{p.name}' check failed: {exc}[/yellow]")

    if namespace:
        all_violations = [v for v in all_violations if v.namespace == namespace]

    if not all_violations:
        console.print("[green]No violations found.[/green]")
        return

    table = Table(title=f"Active Violations ({len(all_violations)})", show_lines=False)
    table.add_column("Policy", style="cyan", no_wrap=True)
    table.add_column("Kind", no_wrap=True)
    table.add_column("Namespace")
    table.add_column("Resource")
    table.add_column("Sev", style="yellow")
    table.add_column("Tier")
    table.add_column("Message", overflow="fold")

    severity_color = {"error": "red", "critical": "bold red", "warning": "yellow", "info": "dim"}
    tier_color = {"auto": "green", "alert-only": "blue", "approval": "magenta"}

    for v in all_violations:
        sc = severity_color.get(v.severity.value, "")
        tc = tier_color.get(v.tier.value, "")
        table.add_row(
            v.policy_name,
            v.resource_kind,
            v.namespace,
            v.resource_name,
            f"[{sc}]{v.severity.value}[/{sc}]",
            f"[{tc}]{v.tier.value}[/{tc}]",
            v.message,
        )

    console.print(table)
    sys.exit(1)  # non-zero exit so CI pipelines can detect violations


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------

@app.command()
def history(
    namespace: Optional[str] = typer.Option(
        None, "--namespace", "-n",
        help="Namespace to read history from (default: kubekeeper-system).",
    ),
    limit: int = typer.Option(
        50, "--limit", "-l",
        help="Maximum number of records to display.",
    ),
) -> None:
    """Show the remediation audit trail."""
    _load_k8s()

    from kubernetes import client
    from kubekeeper.operator.crd import list_remediations, OPERATOR_NAMESPACE

    ns = namespace or OPERATOR_NAMESPACE
    custom_objects = client.CustomObjectsApi()
    records = list_remediations(custom_objects, namespace=ns)

    if not records:
        console.print(f"No remediation history found in namespace '{ns}'.")
        return

    records = records[:limit]
    table = Table(title=f"Remediation History — {ns} (latest {len(records)})", show_lines=False)
    table.add_column("Timestamp", no_wrap=True)
    table.add_column("Policy", style="cyan", no_wrap=True)
    table.add_column("Kind")
    table.add_column("Namespace")
    table.add_column("Resource")
    table.add_column("Action")
    table.add_column("Status")

    for record in records:
        spec = record.get("spec", {})
        status = spec.get("status", "unknown")
        status_markup = f"[green]{status}[/green]" if status == "success" else f"[red]{status}[/red]"
        table.add_row(
            spec.get("timestamp", "")[:19],
            spec.get("policyName", ""),
            spec.get("resourceKind", ""),
            spec.get("resourceNamespace", ""),
            spec.get("resourceName", ""),
            spec.get("action", ""),
            status_markup,
        )

    console.print(table)


# ---------------------------------------------------------------------------
# policy list
# ---------------------------------------------------------------------------

@app.command(name="policy")
def policy_list(
    subcommand: str = typer.Argument("list", help="Subcommand: list"),
) -> None:
    """Manage policies. Use 'policy list' to show all registered built-in policies."""
    if subcommand != "list":
        err_console.print(f"[red]Unknown subcommand: {subcommand!r}. Use 'list'.[/red]")
        raise typer.Exit(code=1)

    from kubekeeper.operator import policies as _  # noqa: F401
    from kubekeeper.operator.policies.base import all_policies

    table = Table(title="Built-in Policies", show_lines=False)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Default Tier")
    table.add_column("Default Severity")
    table.add_column("Description", overflow="fold")

    tier_color = {"auto": "green", "alert-only": "blue", "approval": "magenta"}
    for p in sorted(all_policies(), key=lambda x: x.name):
        tc = tier_color.get(p.default_tier.value, "")
        console.print  # silence unused import warning
        table.add_row(
            p.name,
            f"[{tc}]{p.default_tier.value}[/{tc}]",
            p.default_severity.value,
            p.description,
        )

    console.print(table)


if __name__ == "__main__":
    app()
