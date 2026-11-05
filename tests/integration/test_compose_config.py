import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

BASE = "deploy/compose.yaml"
DEV = "deploy/compose.dev.yaml"
CORE_SERVICES = {"postgres", "api", "web"}
OPTIONAL_SERVICES = {"keycloak", "prometheus", "grafana"}

# The VM itself needs about 1 GiB, so the containers may use the other 5 of its 6 GiB.
CONTAINER_BUDGET_BYTES = 5 * 1024**3

DOCKERFILES = ["api.Dockerfile", "web.Dockerfile"]


def compose_config(*files: str, all_profiles: bool = True) -> dict[str, Any]:
    command = ["docker", "compose", "--env-file", ".env.example"]
    for file in files:
        command += ["--file", file]
    if all_profiles:
        command += ["--profile", "*"]
    result = subprocess.run(
        [*command, "config", "--format", "json"], check=True, capture_output=True, text=True
    )
    config: dict[str, Any] = json.loads(result.stdout)
    return config


def dockerfile_lines(name: str) -> list[str]:
    return Path("deploy", name).read_text(encoding="utf-8").splitlines()


@pytest.fixture(params=[(BASE,), (BASE, DEV)], ids=["up", "dev"])
def services(request: pytest.FixtureRequest) -> dict[str, Any]:
    result: dict[str, Any] = compose_config(*request.param)["services"]
    return result


def test_optional_services_stay_off_by_default() -> None:
    assert set(compose_config(BASE, DEV, all_profiles=False)["services"]) == CORE_SERVICES


def test_the_profiles_add_auth_and_dashboards(services: dict[str, Any]) -> None:
    assert set(services) == CORE_SERVICES | OPTIONAL_SERVICES


def test_every_service_has_a_memory_limit(services: dict[str, Any]) -> None:
    assert [name for name, service in services.items() if not service.get("mem_limit")] == []


def test_the_whole_stack_fits_the_container_budget(services: dict[str, Any]) -> None:
    total = sum(int(service["mem_limit"]) for service in services.values())

    assert total <= CONTAINER_BUDGET_BYTES


def test_every_service_has_a_health_check(services: dict[str, Any]) -> None:
    assert [name for name, service in services.items() if "healthcheck" not in service] == []


def test_every_port_binds_to_localhost(services: dict[str, Any]) -> None:
    host_ips = {port["host_ip"] for service in services.values() for port in service["ports"]}

    assert host_ips == {"127.0.0.1"}


def test_every_pulled_image_is_pinned(services: dict[str, Any]) -> None:
    images = [service["image"] for service in services.values() if "build" not in service]

    assert images
    assert [image for image in images if ":" not in image or image.endswith(":latest")] == []


@pytest.mark.parametrize("dockerfile", DOCKERFILES)
def test_every_base_image_is_pinned(dockerfile: str) -> None:
    stage_names: set[str] = set()
    unpinned = []
    for line in dockerfile_lines(dockerfile):
        if line.startswith("FROM "):
            words = line.split()
            image = words[1]
            if image not in stage_names and (":" not in image or image.endswith(":latest")):
                unpinned.append(image)
            stage_names.add(words[-1])

    assert unpinned == []


@pytest.mark.parametrize("dockerfile", DOCKERFILES)
def test_the_final_image_does_not_run_as_root(dockerfile: str) -> None:
    lines = dockerfile_lines(dockerfile)
    final_from = max(index for index, line in enumerate(lines) if line.startswith("FROM "))
    final_stage = lines[final_from:]
    users = [line.split()[1] for line in final_stage if line.startswith("USER ")]

    assert "root" not in users
    assert users or "nginx-unprivileged" in final_stage[0]


def test_only_named_paths_reach_the_docker_build() -> None:
    rules = Path(".dockerignore").read_text(encoding="utf-8").splitlines()
    active = [rule for rule in rules if rule and not rule.startswith("#")]

    assert active[0] == "*"
    assert not {"!.env", "!data/", "!private/", "!docs/"} & set(active)
