"""Disposable loopback-only fixture for browser UI qualification; not a service route."""

import json
import socket
import tempfile

import uvicorn

from metaforge_verification.api import create_app
from metaforge_verification.config import Settings
from metaforge_verification.contracts import VerificationRequest
from metaforge_verification.worker import run_once

with tempfile.TemporaryDirectory() as directory:
    settings = Settings(database_url=f"sqlite:///{directory}/jobs.db", auth_mode="local")
    app = create_app(settings)
    from pathlib import Path

    payload = json.loads((Path(__file__).parents[1] / "examples/lamp.json").read_text())
    row, _ = app.state.store.submit("local", "fixture", VerificationRequest.model_validate(payload))
    run_once(app.state.store, row["id"])
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    print(json.dumps({"port": listener.getsockname()[1], "job_id": row["id"]}), flush=True)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    server.run(sockets=[listener])
