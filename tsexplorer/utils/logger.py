'''
This file defines a simple helper function for using common logging
configuration
'''
import logging
import datetime
import warnings
import os
import pathlib

_TIMESTAMP_FMT: str = "%m-%d %H:%M:%S"
_LOG_FILE: str = "tsexplorer_{ts}.log".format(
        ts=datetime.datetime.now().strftime("%m-%dT%H_%M_%S")
)

_LOG_LEVEL: int = logging.INFO


def get_logger(name: str, log_to_file: bool = True) -> logging.Logger:
    '''
    Creates a new logger with the given name.
    NOTE: Expects a unique name, but this is not ensured! If duplicate name
    is used, the previous logger is overridden.

    Parameters
    ----------
    name: str
        The name of the logger. Should be unique, and describe the module
        that uses it.
    log_to_file: bool, optional
        If set to True, will be logging also to file. Useful in cases where
        some modules cannot log to a file (e.g. uses a threading model).
        Default True
    '''
    logger = logging.getLogger(name)
    logger.setLevel(_LOG_LEVEL)
    ch = logging.StreamHandler()
    ch.setLevel(_LOG_LEVEL)
    formatter = logging.Formatter(
        "%(threadName)s[%(module)s|%(funcName)s][%(levelname)s]-> %(message)s"
    )
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    if log_to_file:
        logdir = pathlib.Path("log")
        # Ensure that the 'log' dir is created when the logging process starts
        if not logdir.exists():
            logdir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(logdir / _LOG_FILE)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger


def set_logging_config() -> None:
    '''Sets up the configuration for the logger '''
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(module)-10s:%(funcName)-25s %(levelname)-8s %(message)s",
        datefmt=_TIMESTAMP_FMT,
        filename="tsexplorer.log",
        filemode="w"
    )

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(module)-10s:%(funcName)-25s %(levelname)-8s %(message)s")
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)


def _get_log_level():
    '''
    Determine the logging level based on the user set environment variable
    '''
    global _LOG_LEVEL
    log_level = os.environ.get("TSEXPLORER_LOG_LEVEL", None)

    # Info is used as default level
    if log_level is None:
        _LOG_LEVEL = logging.INFO
        return

    # Set the level to one higher than the max level -> nothing gets logged
    log_level = log_level.upper()
    if log_level == "DISABLED":
        _LOG_LEVEL = logging.CRITICAL + 1
        return

    num_level = getattr(logging, log_level, None)
    if num_level is None:
        warnings.warn((f"Unknown log-level {log_level!r}! To disable logging, "
                       " use DISABLED. For other possible values, see "
                       "https://docs.python.org/3/howto/logging.html for "
                       "possible values"))
        _LOG_LEVEL = logging.INFO
    else:
        _LOG_LEVEL = num_level


_get_log_level()
