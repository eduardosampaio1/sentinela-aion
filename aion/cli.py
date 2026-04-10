"""AION CLI — simple entry point."""

import uvicorn
from aion.config import get_settings


def main():
    settings = get_settings()
    uvicorn.run(
        "aion.main:app",
        host="0.0.0.0",
        port=settings.port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
