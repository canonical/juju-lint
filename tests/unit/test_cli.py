#!/usr/bin/python3
"""Test the CLI."""
import errno
from logging import WARN
from unittest.mock import MagicMock, call

import pytest

from jujulint import cli


def test_pytest():
    """Test that pytest itself works."""
    assert True


def test_cli_fixture(cli_instance):
    """Test if the CLI fixture works."""
    assert isinstance(cli_instance, cli.Cli)


@pytest.mark.parametrize("output_format_value", ["text", "json"])
def test_cli_init(output_format_value, mocker):
    """Test initiation of CLI class."""
    logging_mock = mocker.patch.object(cli, "logging")

    loglevel_value = "warn"
    loglevel = MagicMock()
    loglevel.get.return_value = loglevel_value

    output_format = MagicMock()
    output_format.get.return_value = output_format_value

    rules_file_value = "/tmp/rules.yaml"
    rules_file = MagicMock()
    rules_file.get.return_value = rules_file_value

    config = {
        "logging": {"loglevel": loglevel},
        "format": output_format,
        "rules": {"file": rules_file},
    }

    mocker.patch.object(cli, "Config", return_value=config)
    mocker.patch.object(cli.os.path, "isfile", return_value=True)

    cli_instance = cli.Cli()

    assert cli_instance.logger.logger.level == WARN
    assert cli_instance.output_format == output_format_value
    assert cli_instance.rules_files == [rules_file_value]

    if output_format_value != "text":
        logging_mock.disable.assert_called_once_with(level=logging_mock.CRITICAL)


def test_cli_version(mocker):
    """Test detection of juju-lint version on Cli init."""
    mocker.patch.object(cli, "Config")
    version_mock = mocker.patch.object(cli, "version", return_value="1.2")

    cli_instance = cli.Cli()

    version_mock.assert_called_once_with("jujulint")
    assert cli_instance.version == "1.2"


def test_cli_version_fallback(mocker):
    """Test graceful fallback of juju-lint version on Cli init."""
    mocker.patch.object(cli, "Config")

    cli_instance = cli.Cli()

    # detecting version fails in unit tests,
    # so we can test that it gracefully falls back to unknown
    assert cli_instance.version == "unknown"


@pytest.mark.parametrize("rules_path", ["absolute", "relative", "url", None])
def test_cli_init_rules_path(rules_path, mocker):
    """Test different methods of loading rules file on Cli init.

    methods:
      * via absolut path
      * via path relative to config dir
      * rules file could not be found
    """
    config_dir = "/tmp/foo"
    file_path = "rules.yaml"
    rule_file = MagicMock()
    rule_file.get.return_value = file_path

    config_dict = {
        "logging": {"loglevel": MagicMock()},
        "format": MagicMock(),
        "rules": {"file": rule_file},
    }
    config = MagicMock()
    config.__getitem__.side_effect = config_dict.__getitem__
    config.config_dir.return_value = config_dir
    mocker.patch.object(cli, "Config", return_value=config)
    exit_mock = mocker.patch.object(cli.sys, "exit")

    if rules_path == "absolute":
        mocker.patch.object(cli.os.path, "isfile", return_value=True)
    elif rules_path == "relative":
        mocker.patch.object(cli.os.path, "isfile", side_effect=[False, True])
    elif rules_path == "url":
        mocker.patch.object(cli, "is_url", return_value=True)
    else:
        mocker.patch.object(cli.os.path, "isfile", return_value=False)

    cli_instance = cli.Cli()

    if rules_path == "absolute" or rules_path == "url":
        assert cli_instance.rules_files == [file_path]
        exit_mock.assert_not_called()
    elif rules_path == "relative":
        assert cli_instance.rules_files == ["{}/{}".format(config_dir, file_path)]
        exit_mock.assert_not_called()
    else:
        exit_mock.assert_called_once_with(1)


@pytest.mark.parametrize(
    "rules_file_value",
    (
        "/rule1.yaml, /rule2.yaml",
        ",,,/rule1.yaml,/rule2.yaml",
        "/rule1.yaml,/rule2.yaml,,,",
        " /rule1.yaml,, /rule2.yaml ",
        "/rule1.yaml,,,,,/rule2.yaml",
    ),
)
def test_cli_init_rules_file_comma_separated_values(rules_file_value, mocker):
    """Test that comma separated rules file values handle commas and spaces well."""
    rules_file = MagicMock()
    rules_file.get.return_value = rules_file_value

    config = {
        "logging": {"loglevel": MagicMock()},
        "format": MagicMock(),
        "rules": {"file": rules_file},
    }

    mocker.patch.object(cli, "Config", return_value=config)
    mocker.patch.object(cli.os.path, "isfile", return_value=True)

    cli_instance = cli.Cli()

    assert cli_instance.rules_files == ["/rule1.yaml", "/rule2.yaml"]


@pytest.mark.parametrize("is_cloud_set", [True, False])
def test_cli_cloud_type(cli_instance, is_cloud_set):
    """Test cloud_type() property of Cli class."""
    cloud_type_value = "openstack"
    cloud_type = MagicMock()
    cloud_type.get.return_value = cloud_type_value

    config = {"cloud-type": cloud_type} if is_cloud_set else {}
    cli_instance.config = config

    if is_cloud_set:
        assert cli_instance.cloud_type == cloud_type_value
    else:
        assert cli_instance.cloud_type is None


@pytest.mark.parametrize("is_file_set", [True, False])
def test_cli_manual_file(cli_instance, is_file_set):
    """Test manual_file() property of Cli class."""
    manual_file_value = "./rules.yaml"
    manual_file = MagicMock()
    manual_file.get.return_value = manual_file_value

    config = {"manual-file": manual_file} if is_file_set else {}
    cli_instance.config = config

    if is_file_set:
        assert cli_instance.manual_file == manual_file_value
    else:
        assert cli_instance.manual_file is None


@pytest.mark.parametrize(
    "cloud_type_value, manual_file_value",
    [
        ("openstack", "rules.yaml"),
        (None, None),
    ],
)
def test_cli_startup_message(cli_instance, cloud_type_value, manual_file_value, mocker):
    """Test output of a startup message."""
    version = "1.0"
    config_dir = "/tmp/"
    rules_files = ["rules.yaml"]

    log_level_value = "debug"
    log_level = MagicMock()
    log_level.get.return_value = log_level_value

    cloud_type = MagicMock()
    cloud_type.get.return_value = cloud_type_value

    manual_file = MagicMock()
    manual_file.get.return_value = manual_file_value

    config_data = {
        "logging": {"loglevel": log_level},
        "cloud-type": cloud_type,
        "manual-file": manual_file,
    }

    config = MagicMock()
    config.config_dir.return_value = config_dir
    config.__getitem__.side_effect = config_data.__getitem__
    config.__contains__.side_effect = config_data.__contains__

    expected_msg = (
        "juju-lint version {} starting...\n\t* Config directory: {}\n"
        "\t* Cloud type: {}\n\t* Manual file: {}\n\t* Rules files: {}\n"
        "\t* Log level: {}\n"
    ).format(
        version,
        config_dir,
        cloud_type_value or "Unknown",
        manual_file_value or False,
        rules_files,
        log_level_value,
    )

    cli_instance.version = version
    cli_instance.config = config
    cli_instance.rules_files = rules_files
    log_mock = mocker.patch.object(cli_instance, "logger")

    assert cli_instance.cloud_type == cloud_type_value
    cli_instance.startup_message()

    log_mock.info.assert_called_once_with(expected_msg)


def test_cli_usage(cli_instance):
    """Test usage() method of Cli class."""
    config_mock = MagicMock()
    cli_instance.config = config_mock

    cli_instance.usage()

    config_mock.parser.print_help.assert_called_once()


def test_cli_audit_file(cli_instance, mocker):
    """Test method audit_file() from Cli class."""
    filename = "/tmp/bundle.yaml"
    rules = ["/tmp/rules.yaml"]
    cloud_type = "openstack"
    output_format = "text"
    linter_object = MagicMock()

    mock_linter = mocker.patch.object(cli, "Linter", return_value=linter_object)
    cli_instance.rules_files = rules
    cli_instance.output_format = output_format

    cli_instance.audit_file(filename, cloud_type)

    mock_linter.assert_called_once_with(
        filename, rules, cloud_type=cloud_type, output_format=output_format
    )
    linter_object.read_rules.assert_called_once()
    linter_object.lint_yaml_file.assert_called_once_with(filename)


def test_cli_audit_file_exits_when_read_rule_fails(cli_instance, mocker):
    """Test method audit_file() from Cli class terminates when cannot read rules."""
    filename = "/tmp/bundle.yaml"
    rules = ["/tmp/rules.yaml"]
    cloud_type = "openstack"
    output_format = "text"
    linter_object = MagicMock()
    linter_object.read_rules.return_value = False

    mock_linter = mocker.patch.object(cli, "Linter", return_value=linter_object)
    cli_instance.rules_files = rules
    cli_instance.output_format = output_format

    with pytest.raises(SystemExit) as mock_exception:
        cli_instance.audit_file(filename, cloud_type)

    assert mock_exception.value.code == 1
    mock_linter.assert_called_once_with(
        filename, rules, cloud_type=cloud_type, output_format=output_format
    )
    linter_object.read_rules.assert_called_once()
    linter_object.lint_yaml_file.assert_not_called()


def test_cli_audit_all(cli_instance, mocker):
    """Test audit_all() method from Cli class."""
    audit_mock = mocker.patch.object(cli_instance, "audit")
    write_yaml_mock = mocker.patch.object(cli_instance, "write_yaml")

    cloud_data = "cloud data"
    clouds_value = ["cloud_1", "cloud_2"]
    clouds = MagicMock()
    clouds.get.return_value = clouds_value

    folder_value = ""
    folder = MagicMock()
    folder.get.return_value = folder_value

    config_data = {"clouds": clouds, "output": {"folder": folder}}
    config = MagicMock()
    config.__getitem__.side_effect = config_data.__getitem__

    cli_instance.clouds = cloud_data
    cli_instance.config = config

    cli_instance.audit_all()

    audit_mock.assert_has_calls([call(cloud) for cloud in clouds_value])
    write_yaml_mock.assert_called_once_with(cloud_data, "all-data.yaml")


@pytest.mark.parametrize("success", [True, False])
def test_cli_audit(cli_instance, success, mocker):
    """Test audit() method from Cli class."""
    cloud_name = "test cloud"
    rules_files = ["rules.yaml"]
    cloud_data = {
        "access": "ssh",
        "sudo": "root",
        "host": "juju.host",
        "type": "openstack",
    }

    cloud = MagicMock()
    cloud.get.return_value = cloud_data

    config_data = {"clouds": {cloud_name: cloud}}

    cloud_state = {"key": "value"}
    mock_openstack_instance = MagicMock()
    mock_openstack_instance.refresh.return_value = success
    mock_openstack_instance.cloud_state = cloud_state
    mock_openstack = mocker.patch.object(cli, "OpenStack", return_value=mock_openstack_instance)

    mock_yaml = mocker.patch.object(cli_instance, "write_yaml")

    mock_logger = MagicMock()
    cli_instance.logger = mock_logger

    cli_instance.config = config_data
    cli_instance.rules_files = rules_files

    # assert cli_instance.config["clouds"]
    cli_instance.audit(cloud_name=cloud_name)

    mock_openstack.assert_called_once_with(
        cloud_name,
        access_method=cloud_data["access"],
        ssh_host=cloud_data["host"],
        sudo_user=cloud_data["sudo"],
        lint_rules=rules_files,
    )

    if success:
        assert cli_instance.clouds[cloud_name] == cloud_state
        mock_yaml.assert_called_once_with(cloud_state, "{}-state.yaml".format(cloud_name))
        mock_openstack_instance.audit.assert_called_once()
    else:
        mock_logger.error.assert_called_once_with(
            "[{}] Failed getting cloud state".format(cloud_name)
        )


def test_cli_write_yaml(cli_instance, mocker):
    """Test write_yaml() method from Cli class."""
    yaml_mock = mocker.patch.object(cli, "yaml")
    data = "{'yaml': 'data'}"
    file_name = "dump.yaml"

    output_folder_value = "/tmp"
    output_folder = MagicMock()
    output_folder.get.return_value = output_folder_value

    opened_file = MagicMock()
    mock_open = mocker.patch("builtins.open", return_value=opened_file)

    config = {"output": {"folder": output_folder}}

    cli_instance.config = config
    cli_instance.write_yaml(data, file_name)

    mock_open.assert_called_once_with("{}/{}".format(output_folder_value, file_name), "w")
    yaml_mock.dump.assert_called_once_with(data, opened_file)


def test_check_output_folder(cli_instance, mocker):
    """Test _check_output_folder() method from Cli class."""
    folder_value = "/a/non/empty/path/string"
    folder = MagicMock()
    folder.get.return_value = folder_value

    config = {"output": {"folder": folder}}
    cli_instance.config = config

    mock_temporary_file = mocker.patch("tempfile.TemporaryFile")
    mock_sys_exit = mocker.patch("sys.exit")

    mock_temporary_file.return_value.__enter__.side_effect = FileNotFoundError()
    cli_instance._check_output_folder()
    mock_sys_exit.assert_called_once_with(errno.ENOENT)

    mock_temporary_file.reset_mock(return_value=True)
    mock_sys_exit.reset_mock()

    mock_temporary_file.return_value.__enter__.side_effect = PermissionError()
    cli_instance._check_output_folder()
    mock_sys_exit.assert_called_once_with(errno.EACCES)

    mock_temporary_file.reset_mock(return_value=True)
    mock_sys_exit.reset_mock()

    mock_temporary_file.return_value.__enter__.side_effect = Exception()
    cli_instance._check_output_folder()
    mock_sys_exit.assert_called_once_with(1)


@pytest.mark.parametrize("audit_type", ["file", "all", None])
def test_main(cli_instance, audit_type, mocker):
    """Test main entrypoint of jujulint."""
    mocker.patch.object(cli_instance, "startup_message")
    mocker.patch.object(cli_instance, "usage")
    mocker.patch.object(cli_instance, "audit_file")
    mocker.patch.object(cli_instance, "audit_all")

    manual_file_value = "bundle.yaml"
    manual_file = MagicMock()
    manual_file.get.return_value = manual_file_value

    cloud_type_value = "openstack"
    cloud_type = MagicMock()
    cloud_type.get.return_value = cloud_type_value

    cli_instance.config = {"cloud-type": cloud_type}

    if audit_type == "file":
        cli_instance.config["manual-file"] = manual_file
    elif audit_type == "all":
        cli_instance.config["clouds"] = ["cloud_1", "cloud_2"]

    mocker.patch.object(cli, "Cli", return_value=cli_instance)

    cli.main()

    if audit_type == "file":
        cli_instance.audit_file.assert_called_once_with(
            manual_file_value, cloud_type=cloud_type_value
        )
        cli_instance.audit_all.assert_not_called()
    elif audit_type == "all":
        cli_instance.audit_all.assert_called_once()
        cli_instance.audit_file.assert_not_called()
    else:
        cli_instance.usage.assert_called_once()
        cli_instance.audit_all.assert_not_called()
        cli_instance.audit_file.assert_not_called()
