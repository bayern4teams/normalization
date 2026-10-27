"""Wiring check on the real code (HEAD): every builder refuses a public host. Mutation runs showed no
repo test would notice if these checks were removed. Run: uv run --python 3.12 python .handoff/D15.attack_wiring_probe.py"""
import os
from cryptography.fernet import Fernet
os.environ.setdefault("NORM_SECRET_KEY", Fernet.generate_key().decode())
from normapi import clone_executor, secrets
from normapi.address_policy import AddressPolicyError
enc = secrets.encrypt("pw")
for engine in ("postgres", "clickhouse"):
    conn = {"connection_id": "x", "engine": engine, "host": "8.8.8.8", "port": 5432, "username": "u", "encrypted_password": enc}
    for fn, args in ((clone_executor.build_source_connector, (conn, "db")), (clone_executor.build_destination_writer, (conn,))):
        try:
            fn(*args); print("LEAK", engine, fn.__name__)
        except AddressPolicyError:
            print("OK refused", engine, fn.__name__)
