"""Shows the compose api container cannot accept its own LAN address as Host: compose.yaml passes
only the keys under api.environment, so NORM_BIND_ADDR / NORM_ALLOWED_HOSTS / NORM_ALLOWED_NETWORKS
from .env never reach the app. Run: uv run --python 3.12 python .handoff/D15.attack_compose_env_probe.py"""
import os, pathlib, yaml
from starlette.testclient import TestClient
from normapi.app import create_app
env = yaml.safe_load(pathlib.Path("compose.yaml").read_text())["services"]["api"]["environment"]
keys = set(env)
print("api.environment has NORM_BIND_ADDR:", "NORM_BIND_ADDR" in keys, "| NORM_ALLOWED_HOSTS:", "NORM_ALLOWED_HOSTS" in keys,
      "| NORM_ALLOWED_NETWORKS:", "NORM_ALLOWED_NETWORKS" in keys, "| env_file:", "env_file" in yaml.safe_load(pathlib.Path("compose.yaml").read_text())["services"]["api"])
for k in ("NORM_BIND_ADDR", "NORM_ALLOWED_HOSTS"):
    os.environ.pop(k, None)   # what the container sees
c = TestClient(create_app(), client=("192.168.1.20", 5000), base_url="http://192.168.1.5:8080")
print("LAN caller 192.168.1.20, Host 192.168.1.5:8080 ->", c.get("/openapi.json").status_code, "(want 200 for the Q-B LAN use case)")
