"""Export the public contract and fail CI when a route/schema change leaves it stale."""

import argparse
import json
import tempfile
from pathlib import Path

from metaforge_verification.api import create_app
from metaforge_verification.config import Settings

parser = argparse.ArgumentParser()
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
with tempfile.TemporaryDirectory() as directory:
    app = create_app(Settings(database_url=f"sqlite:///{directory}/schema.db", auth_mode="local"))
    schema = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    app.state.store.engine.dispose()
path = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"
if args.check:
    if not path.exists() or path.read_text() != schema:
        raise SystemExit("OpenAPI changed: run python scripts/export_openapi.py")
else:
    path.write_text(schema)
