from __future__ import annotations

import uvicorn

from brain.api.server import app
from shared.settings import load_settings


def main() -> None:
    settings = load_settings()
    uvicorn.run(app, host=settings.api.host, port=settings.api.port)


if __name__ == "__main__":
    main()
