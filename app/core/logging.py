"""Logging setup cho CrawlerGithubService.

Format đồng bộ với QualityService để console toàn hệ thống nhất quán:
[timestamp] [LEVEL] [name] message
"""

import logging
import sys

_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Trả về logger ghi stdout, tránh add handler trùng khi reload."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False

    return logger
