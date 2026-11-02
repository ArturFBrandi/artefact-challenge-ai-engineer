"""`make run`: start the chat app."""

import logging
import sys

import uvicorn

from emporio.bootstrap import build_service
from emporio.config import Settings
from emporio.llm.factory import ConfigurationError
from emporio.web.app import create_app


def main() -> int:
    settings = Settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")
    try:
        service = build_service(settings)
    except ConfigurationError as error:
        print(f"Cannot start: {error}", file=sys.stderr)
        return 1
    print(f"Chat at http://{settings.web_host}:{settings.web_port}")
    uvicorn.run(
        create_app(service),
        host=settings.web_host,
        port=settings.web_port,
        log_level=settings.log_level.lower(),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
