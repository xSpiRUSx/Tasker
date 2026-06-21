from __future__ import annotations

import argparse
import os

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the engineering assistant API.")
    parser.add_argument("--host", default=os.getenv("ENGINEERING_ASSISTANT_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("ENGINEERING_ASSISTANT_PORT", "8000")))
    parser.add_argument("--reload", action="store_true", default=os.getenv("ENGINEERING_ASSISTANT_RELOAD") == "1")
    args = parser.parse_args()

    uvicorn.run("engineering_assistant.api:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
