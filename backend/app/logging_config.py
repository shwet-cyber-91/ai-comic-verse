"""Logging setup. One place, called once from ``main`` and from the worker
thread that runs the pipeline, so graph logs and API logs share a format."""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False
_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-28s | %(message)s"
_DATEFMT = "%H:%M:%S"

# Chatty third-party loggers we never want at INFO in a local dev run.
_NOISY = ("httpx", "httpcore", "urllib3", "chromadb", "PIL", "asyncio", "watchfiles")


def configure_logging(level: str | int | None = None) -> None:
    global _CONFIGURED

    from .config import get_settings

    if level is None:
        level = logging.DEBUG if get_settings().debug else logging.INFO
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    if not _CONFIGURED:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
        root.handlers = [handler]
        _CONFIGURED = True
    root.setLevel(level)

    for name in _NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger("comicverse").setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Namespaced logger: ``get_logger("nodes.dialogue")`` -> comicverse.nodes.dialogue"""
    return logging.getLogger(f"comicverse.{name}")
