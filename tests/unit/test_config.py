#!/usr/bin/python3
"""Test correct reading of the all config files."""

from unittest.mock import mock_open, patch

import yaml

from jujulint.config import Config


def test_pytest():
    """Test that pytest itself works."""
    assert True


def test_config_file():
    """Tests if the config entries set in the .config/juju-lint/config.yaml are correctly applied."""
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

    # create a mock open function that only intercepts calls to the config file
    builtin_open = open
    config_file = f"{Config().config_dir()}/config.yaml"

    def my_mock_open(*args, **kwargs):
        if args[0] == config_file:
            return mock_open(read_data=mock_file_config)(*args, **kwargs)
        return builtin_open(*args, **kwargs)

    expected_config = yaml.safe_load(mock_file_config)
    with patch("builtins.open", my_mock_open):
        config = Config()
        # you cannot do config.get(), so we iterate over the toplevel keys
        for key in expected_config.keys():
            assert config[key].get() == expected_config[key]


def test_default_config():
    """Tests if the default values are correctly read from config_default.yaml."""
    config = Config()
    default_config = {
        "logging": {"loglevel": "INFO", "file": "jujulint.log"},
        "rules": {"file": "lint-rules.yaml"},
        "output": {"folder": None},
        "format": "text",
    }
    for key in default_config.keys():
        assert config[key].get() == default_config[key]
