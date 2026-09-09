"""Process-wide logging configuration.

Replaces diyHue's ``logManager`` package (which wired logging into a Flask
app + file rotation) with a plain stdlib setup — this service has no web
framework logging to integrate with.
"""

from __future__ import annotations

import logging
import os
import sys


def configure_logging() -> None:
    level_name = os.environ.get("HEMERA_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
