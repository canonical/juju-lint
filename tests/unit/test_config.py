#!/usr/bin/python3
"""Test correct reading of the all config files."""

import os
import sys

import yaml

from jujulint.config import Config

config_file = f"{Config().config_dir()}/config.yaml"
builtin_open = open
builtin_isfile = os.path.isfile

mock_file_config = """
logging:
  loglevel: WARN
  file: test.log

rules:
  file: file-test.yaml


output:
  folder: folder-test
  dump: dump-test

format: json
"""


def patch_user_config(mocker):
    # confuse only reads a config file in .config, if it exists. We have to mock the os.isfile call
    # and create a mock open function that only intercepts calls to the config file
    def my_mock_open(*args, **kwargs):
        if args[0] == config_file:
            return mocker.mock_open(read_data=mock_file_config)(*args, **kwargs)
        return builtin_open(*args, **kwargs)

    def side_effect(filename):
        if filename == config_file:
            return True
        else:
            return builtin_isfile(filename)

    mocker.patch("os.path.isfile", side_effect=side_effect)
    mocker.patch("builtins.open", my_mock_open)
    return mocker


def test_config_file(mocker):
    """Tests if the config entries set in the .config/juju-lint/config.yaml are correctly applied.

    The values in .config/juju-lint/config.yaml should overwrite the fileds in config_default.yaml
    """
    expected_config = yaml.safe_load(mock_file_config)
    patch_user_config(mocker)
    config = Config()
    # you cannot do config.get(), so we iterate over the toplevel keys
    for key in expected_config.keys():
        assert config[key].get() == expected_config[key]


def test_default_config(mocker):
    """Tests if the default values are correctly read from config_default.yaml."""
    default_config = {
        "logging": {"loglevel": "INFO", "file": "jujulint.log"},
        "rules": {"file": "lint-rules.yaml"},
        "output": {"folder": None},
        "format": "text",
    }

    # Don't use the .config/juju-ling/config.yaml!
    def side_effect(filename):
        if filename == config_file:
            return False
        else:
            return builtin_isfile(filename)

    mocker.patch("os.path.isfile", side_effect=side_effect)

    config = Config()
    for key in default_config.keys():
        assert config[key].get() == default_config[key]


def test_parser_options(mocker):
    """Tests if cli options overwrite the options in config files."""
    cli_config = {
        "logging": {"loglevel": "DEBUG", "file": "cli.log"},
        "rules": {"file": "cli-rules.yaml"},
        "output": {"folder": "cli/folder"},
        "format": "json",
    }
    test_args = sys.argv + [
        "-F",
        cli_config["format"],
        "-l",
        cli_config["logging"]["loglevel"],
        "-d",
        cli_config["output"]["folder"],
        "-c",
        cli_config["rules"]["file"],
        "-L",
        cli_config["logging"]["file"],
    ]

    mocker.patch.object(sys, "argv", test_args)
    patch_user_config(mocker)
    config = Config()
    for key in cli_config.keys():
        assert config[key].get() == cli_config[key]
