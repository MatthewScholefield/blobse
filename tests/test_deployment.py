"""Offline deployment checks: never invoke setup, Docker, or lifecycle commands."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
DKS = shutil.which("dks")
pytestmark = pytest.mark.skipif(DKS is None, reason="Dockstride CLI not installed")


@pytest.fixture
def project(tmp_path):
    for name in ("compose.ncl", "deployment.ncl"):
        shutil.copyfile(ROOT / name, tmp_path / name)
    shutil.copytree(ROOT / "libs", tmp_path / "libs")
    return tmp_path


def invoke(project, settings, *args):
    # JSON is valid YAML; isolate every candidate from the checkout's env.yaml.
    (project / "env.yaml").write_text(json.dumps({"project": "blobse-test", **settings}))
    return subprocess.run(
        [DKS, "-C", str(project), *args, "--json", "--non-interactive"],
        capture_output=True, text=True, timeout=30,
    )


def render(project, settings, target):
    result = invoke(project, settings, "render", "--target", target)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["result"]


def test_development_wiring(project):
    model = render(project, {}, "compose")
    service = model["services"]["blobse-backend"]
    assert service["environment"] == {
        "DEBUG": "true", "REDIS_HOST": "redis", "SERVER_URL": "http://localhost:7330",
    }
    assert service["ports"] == ["127.0.0.1:7330:7330"]
    assert service["depends_on"]["redis"]["condition"] == "service_healthy"
    assert service["develop"]["watch"][0]["path"] == "./blobse"
    assert service["healthcheck"]["test"][:2] == ["CMD", "python"]
    assert model["services"]["redis"]["volumes"] == ["blobse-redis-volume:/data"]
    assert "dockstride" not in model


def test_production_swarm_and_build(project):
    settings = {
        "prod": True, "serverUrl": "https://blobse.example.com",
        "image": "registry.example.com/blobse:test",
    }
    swarm = render(project, settings, "swarm")
    assert swarm["version"] == "3.8"
    assert "name" not in swarm
    service = swarm["services"]["blobse-backend"]
    assert service["environment"]["DEBUG"] == "false"
    assert service["image"] == settings["image"]
    for key in ("build", "develop", "depends_on", "restart", "ports"):
        assert key not in service
    build = render(project, settings, "build")
    assert build["services"]["blobse-backend"]["build"]["context"] == "."
    assert "develop" not in build["services"]["blobse-backend"]


def test_external_redis_does_not_create_data_resources(project):
    model = render(project, {"redisHost": "shared-redis"}, "compose")
    assert set(model["services"]) == {"blobse-backend"}
    assert model["volumes"] == {}
    service = model["services"]["blobse-backend"]
    assert service["environment"]["REDIS_HOST"] == "shared-redis"
    assert "depends_on" not in service


@pytest.mark.parametrize("settings", [
    {"backend": "swarm"},
    {"prod": True},
])
def test_invalid_or_incomplete_environment_is_rejected(project, settings):
    result = invoke(project, settings, "render", "--target", "compose")
    assert result.returncode != 0


@pytest.mark.parametrize("prod", [False, True])
def test_parent_import_owns_network_proxy_and_redis(tmp_path, prod):
    shutil.copytree(ROOT / "libs", tmp_path / "blobse" / "libs")
    shutil.copyfile(ROOT / "deployment.ncl", tmp_path / "blobse" / "deployment.ncl")
    (tmp_path / "compose.ncl").write_text('''
let lib = import "blobse/libs/dockstride.ncl" in
let cfg = { project | String, backend | lib.Backend, prod | Bool } in
let env | cfg = import "env.yaml" in
let dc = lib.forEnvironment env in
let app = (import "blobse/deployment.ncl") {
  backend = env.backend, prod = env.prod,
  serverUrl = "https://blobse.example.com", redisHost = "redis",
  image = "registry.example.com/blobse:test", buildContext = "./blobse",
} in
dc.ComposeFile (app & {
  dockstride | not_exported = { Config = cfg },
  services."blobse-backend" = {
    networks = ["machazat-network"],
    labels.caddy = "blobse.example.com",
  },
  networks."machazat-network" = {},
})
''')
    model = render(tmp_path, {"prod": prod, "backend": "swarm" if prod else "compose"},
                   "swarm" if prod else "compose")
    assert set(model["services"]) == {"blobse-backend"}
    assert model["volumes"] == {}
    service = model["services"]["blobse-backend"]
    assert service["networks"] == ["machazat-network"]
    assert service["labels"]["caddy"] == "blobse.example.com"
    assert "ports" not in service
    if not prod:
        assert service["build"]["context"] == "./blobse"
        assert service["develop"]["watch"][0]["path"] == "./blobse/blobse"
