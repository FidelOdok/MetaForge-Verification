import argparse
import asyncio


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=["api", "worker", "run-once", "openapi", "temporal-worker", "temporal-dispatch"],
    )
    args = parser.parse_args()
    if args.command == "api":
        import uvicorn

        uvicorn.run(
            "metaforge_verification.api:create_app", factory=True, host="127.0.0.1", port=8000
        )
    elif args.command == "openapi":
        import json

        from metaforge_verification.api import create_app
        from metaforge_verification.config import Settings

        app = create_app(Settings(auth_mode="local"))
        print(json.dumps(app.openapi(), indent=2, sort_keys=True))
        app.state.store.engine.dispose()
    elif args.command.startswith("temporal-"):
        from metaforge_verification import temporal_runtime

        asyncio.run(
            temporal_runtime.serve()
            if args.command == "temporal-worker"
            else temporal_runtime.dispatch()
        )
    else:
        from metaforge_verification.config import Settings
        from metaforge_verification.store import Store
        from metaforge_verification.worker import run_once, serve

        store = Store(Settings.from_env())
        try:
            if args.command == "run-once":
                run_once(store)
            else:
                serve(store)
        finally:
            store.engine.dispose()
