import logging


def get_default_logger(log_level: int | str | None = None) -> logging.Logger:
    """Return the standard library logger the SDK uses when none is supplied.

    Configure it like any other logger::

        logging.getLogger("configdirector").setLevel(logging.DEBUG)
    """
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.WARNING if log_level is None else log_level)
    return logger
