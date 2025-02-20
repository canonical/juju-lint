"""Test for jujulint logging module."""

import sys
from unittest.mock import MagicMock, call

import pytest

from jujulint import logging


def test_logger_init_with_handlers(mocker):
    """Test initiation of a Logger instance with handlers already present."""
    color_logger_mock = mocker.patch.object(logging, "colorlog")
    color_logger_instance_mock = MagicMock()
    color_logger_instance_mock.handlers = ["handler1", "handler2"]
    color_logger_mock.getLogger.return_value = color_logger_instance_mock
    set_level_mock = mocker.patch.object(logging.Logger, "set_level")

    level = "Debug"
    _ = logging.Logger(level=level)

    color_logger_mock.getLogger.assert_called_once()
    set_level_mock.assert_called_once_with(level)
    # No new logger handlers were added since the logger instance already had some.
    color_logger_instance_mock.addHandler.assert_not_called()


@pytest.mark.parametrize("setup_file_logger", (False, True))
def test_logger_init_without_handlers(setup_file_logger, mocker):
    """Test initiation of a Logger instance that needs to create its own handlers.

    This test has two variants, with and without setting up a file logger as well.
    """
    logfile = "/tmp/foo" if setup_file_logger else None
    # Mock getLogger and resulting object
    console_logger_mock = MagicMock()
    file_logger_mock = MagicMock()
    get_logger_mock = mocker.patch.object(
        logging.colorlog,
        "getLogger",
        side_effect=[
            console_logger_mock,
            file_logger_mock,
        ],
    )
    console_logger_mock.handlers = []

    # Mock FileHandler and FileFormatter
    filehandler_mock = MagicMock()
    mocker.patch.object(logging.logging, "FileHandler", return_value=filehandler_mock)

    file_formatter_mock = MagicMock()
    mocker.patch.object(logging.logging, "Formatter", return_value=file_formatter_mock)

    # Mock StreamHandler and resulting object
    streamhandler_mock = MagicMock()
    mocker.patch.object(logging.colorlog, "StreamHandler", return_value=streamhandler_mock)

    set_level_mock = mocker.patch.object(logging.Logger, "set_level")
    # Mock TTYColorFormatter
    color_formatter_instance = MagicMock()
    color_formatter_mock = mocker.patch.object(
        logging.colorlog, "TTYColoredFormatter", return_value=color_formatter_instance
    )
    level = "Debug"
    logformat_string = "%(log_color)s%(asctime)s [%(levelname)s] %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    _ = logging.Logger(level=level, logfile=logfile)

    # Test creation of new log handler
    set_level_mock.assert_called_once_with(level)
    color_formatter_mock.assert_called_once_with(
        logformat_string,
        datefmt=date_format,
        log_colors={
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        },
        stream=sys.stdout,
    )
    streamhandler_mock.setFormatter.assert_called_once_with(color_formatter_instance)

    if not setup_file_logger:
        # getLogger and addHandler are called only once if we are not setting up file
        # logger
        get_logger_mock.assert_called_once()
        console_logger_mock.addHandler.assert_called_once_with(streamhandler_mock)
    else:
        # These steps need to be verified when __init__ sets up file logger as well
        get_logger_mock.assert_has_calls([call(), call("file")])

        logging.logging.Formatter.assert_called_once_with(logformat_string, datefmt=date_format)
        assert not file_logger_mock.propagate
        logging.logging.FileHandler.assert_called_once_with(logfile)
        filehandler_mock.setFormatter.assert_called_once_with(file_formatter_mock)

        console_logger_mock.addHandler.assert_has_calls(
            [
                call(streamhandler_mock),
                call(filehandler_mock),
            ]
        )
        file_logger_mock.addHandler.assert_called_once_with(filehandler_mock)


@pytest.mark.parametrize("exit_code", [None, 0, 1, 2])
def test_fubar(exit_code, mocker):
    """Test method that prints to STDERR and ends program execution."""
    err_msg = "foo bar"
    expected_error = "E: {}\n".format(err_msg)

    mocker.patch.object(logging.sys.stderr, "write")
    mocker.patch.object(logging.sys, "exit")

    if exit_code is None:
        expected_exit_code = 1
        logging.Logger.fubar(err_msg)
    else:
        expected_exit_code = exit_code
        logging.Logger.fubar(err_msg, exit_code)

    logging.sys.stderr.write.assert_called_once_with(expected_error)
    logging.sys.exit.assert_called_once_with(expected_exit_code)


@pytest.mark.parametrize(
    "loglevel, expected_level",
    [
        ("DEBUG", logging.logging.DEBUG),
        ("INFO", logging.logging.INFO),
        ("WARN", logging.logging.WARN),
        ("ERROR", logging.logging.ERROR),
        ("Foo", logging.logging.INFO),
    ],
)
def test_set_level(loglevel, expected_level, mocker):
    """Test setting various log levels."""
    bound_logger_mock = MagicMock()
    mocker.patch.object(logging.colorlog, "getLogger", return_value=bound_logger_mock)
    basic_config_mock = mocker.patch.object(logging.logging, "basicConfig")

    logger = logging.Logger()
    logger.set_level(loglevel)

    if loglevel.lower() == "debug":
        basic_config_mock.assert_called_once_with(level=expected_level)
    else:
        bound_logger_mock.setLevel.assert_called_once_with(expected_level)


def test_debug_method(mocker):
    """Test behavior of Logger.debug() method."""
    message = "Log message"
    bound_logger_mock = MagicMock()
    mocker.patch.object(logging.colorlog, "getLogger", return_value=bound_logger_mock)

    logger = logging.Logger()
    logger.debug(message)

    bound_logger_mock.debug.assert_called_once_with(message)


def test_warn_method(mocker):
    """Test behavior of Logger.warn() method."""
    message = "Log message"
    bound_logger_mock = MagicMock()
    mocker.patch.object(logging.colorlog, "getLogger", return_value=bound_logger_mock)

    logger = logging.Logger()
    logger.warn(message)

    bound_logger_mock.warn.assert_called_once_with(message)


def test_info_method(mocker):
    """Test behavior of Logger.info() method."""
    message = "Log message"
    bound_logger_mock = MagicMock()
    mocker.patch.object(logging.colorlog, "getLogger", return_value=bound_logger_mock)

    logger = logging.Logger()
    logger.info(message)

    bound_logger_mock.info.assert_called_once_with(message)


def test_error_method(mocker):
    """Test behavior of Logger.error() method."""
    message = "Log message"
    bound_logger_mock = MagicMock()
    mocker.patch.object(logging.colorlog, "getLogger", return_value=bound_logger_mock)

    logger = logging.Logger()
    logger.error(message)

    bound_logger_mock.error.assert_called_once_with(message)


def test_log_method(mocker):
    """Test behavior of Logger.log() method."""
    message = "Log message"
    level = logging.logging.INFO
    bound_logger_mock = MagicMock()
    mocker.patch.object(logging.colorlog, "getLogger", return_value=bound_logger_mock)

    logger = logging.Logger()
    logger.log(message, level)

    bound_logger_mock.log.assert_called_once_with(level, message)
