#!/usr/bin/env python3
"""Start the dashboard backend.

    python run.py
"""

from __future__ import annotations

import uvicorn

from app.config import settings


def main() -> int:
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
