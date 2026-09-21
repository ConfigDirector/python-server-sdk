import logging

__all__ = ["LOGGER_NAME", "get_default_logger"]

LOGGER_NAME = __package__ or "configdirector"


def get_default_logger(log_level: int | str | None = None) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if log_level is not None:
        logger.setLevel(log_level)
    return logger
