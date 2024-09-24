#!/usr/bin/python3
"""Tests for cloud.py module."""
from subprocess import CalledProcessError
from unittest.mock import MagicMock, call, patch

import pytest

from jujulint import cloud


@patch("jujulint.cloud.check_output")
def test_get_bundle_no_apps(mock_check_out, cloud_instance):
    """Models with no apps raises CalledProcessError to export bundle."""
    cmd = ["juju", "export-bundle", "-m", "my_controller:controller"]
    e = CalledProcessError(1, cmd)
    mock_check_out.side_effect = e
    cloud_instance.get_juju_bundle("my_controller", "controller")
    expected_error_msg = call.error(e)

    expected_warn_msg = call.warn(
        (
            "An error happened to get the bundle on my_controller:controller. "
            "If the model doesn't have apps, disconsider this message."
        )
    )
    assert expected_error_msg in cloud_instance.logger.method_calls
    assert expected_warn_msg in cloud_instance.logger.method_calls


@patch("jujulint.cloud.Cloud.parse_yaml")
@patch("jujulint.cloud.Cloud.run_command")
def test_get_bundle_offer_side(
    mock_run, mock_parse, cloud_instance, juju_export_bundle
):
    """Test the bundle generated in the offer side."""
    # simulate cloud_state with info that came from "get_juju_status"
    cloud_instance.cloud_state = {
        "my_controller": {
            "models": {
                "my_model_1": {
                    "applications": {
                        "nrpe": {
                            "charm-origin": "charmhub",
                            "os": "ubuntu",
                            "endpoint-bindings": {"": "alpha", "monitors": "alpha"},
                        }
                    }
                },
                "my_model_2": {},
            }
        }
    }
    mock_parse.return_value = juju_export_bundle["my_model_1"]
    # "offers" field exists inside nrpe because of the overlay bundle.
    # saas field doesn't exist in the offer side because there is no url.
    # don't overwrite information that came from "get_juju_status".
    expected_cloud_state = {
        "my_controller": {
            "models": {
                "my_model_1": {
                    "applications": {
                        "nrpe": {
                            "charm": "nrpe",
                            "charm-origin": "charmhub",
                            "os": "ubuntu",
                            "endpoint-bindings": {"": "alpha", "monitors": "alpha"},
                            "channel": "stable",
                            "revision": 86,
                            "offers": {
                                "nrpe": {
                                    "endpoints": ["monitors"],
                                    "acl": {"admin": "admin"},
                                }
                            },
                        },
                        "ubuntu": {
                            "charm": "ubuntu",
                            "channel": "stable",
                            "revision": 19,
                            "num_units": 1,
                            "to": ["0"],
                            "constraints": "arch=amd64",
                        },
                    }
                },
                "my_model_2": {},
            }
        }
    }
    cloud_instance.get_juju_bundle("my_controller", "my_model_1")
    mock_run.assert_called_once_with("juju export-bundle -m my_controller:my_model_1")
    assert cloud_instance.cloud_state == expected_cloud_state


@patch("jujulint.cloud.Cloud.parse_yaml")
@patch("jujulint.cloud.Cloud.run_command")
def test_get_bundle_consumer_side(
    mock_run, mock_parse, cloud_instance, juju_export_bundle
):
    """Test the bundle generated in the consumer side."""
    mock_parse.return_value = juju_export_bundle["my_model_2"]
    # "offers" field won't exist in the consumer side
    # saas field exists because the consumer side shows url
    expected_cloud_state = {
        "my_controller": {
            "models": {
                "my_model_1": {},
                "my_model_2": {
                    "applications": {
                        "nagios": {
                            "charm": "nagios",
                            "channel": "stable",
                            "revision": 49,
                            "num_units": 1,
                            "to": ["0"],
                            "constraints": "arch=amd64",
                        }
                    },
                    "saas": {"nrpe": {"url": "my_controller:admin/my_model_1.nrpe"}},
                },
            }
        }
    }
    cloud_instance.get_juju_bundle("my_controller", "my_model_2")
    mock_run.assert_called_once_with("juju export-bundle -m my_controller:my_model_2")
    assert cloud_instance.cloud_state == expected_cloud_state


@pytest.mark.parametrize(
    "sudo_user, access_method, ssh_host",
    [("", "local", ""), ("root", "ssh", "juju.host")],
)
def test_cloud_init(sudo_user, access_method, ssh_host, mocker):
    """Test Cloud class initialization."""
    logger_mock = MagicMock()
    mocker.patch.object(cloud, "Logger", return_value=logger_mock)
    connection_mock = MagicMock()
    mocker.patch.object(cloud, "Connection", return_value=connection_mock)
    local_fqdn = "localhost"
    mocker.patch.object(cloud.socket, "getfqdn", return_value=local_fqdn)

    name = "Foo Cloud"
    lint_rules = {"Custom": "ruleset"}
    lint_overrides = {"Override": "rule"}
    cloud_type = "test"

    cloud_instance = cloud.Cloud(
        name=name,
        lint_rules=lint_rules,
        access_method=access_method,
        ssh_host=ssh_host,
        sudo_user=sudo_user,
        lint_overrides=lint_overrides,
        cloud_type=cloud_type,
    )

    assert cloud_instance.cloud_state == {}
    assert cloud_instance.access_method == access_method
    assert cloud_instance.sudo_user == sudo_user or ""
    assert cloud_instance.lint_rules == lint_rules
    assert cloud_instance.lint_overrides == lint_overrides

    if sudo_user:
        assert cloud_instance.fabric_config.get("sudo") == {"user": sudo_user}
    else:
        assert cloud_instance.fabric_config == {}

    if access_method == "local":
        assert cloud_instance.hostname == local_fqdn
        connection_mock.assert_not_called()
    else:
        assert cloud_instance.hostname == ssh_host
        assert cloud_instance.connection == connection_mock


def test_run_local_command(patch_cloud_init, mocker):
    """Test running command when the cloud access method is 'local'."""
    expected_result = ".\n.."
    check_output_mock = mocker.patch.object(
        cloud, "check_output", return_value=expected_result
    )

    command = "ls -la"
    command_split = command.split()

    cloud_instance = cloud.Cloud(
        name="local test cloud", access_method="local", cloud_type="test"
    )
    result = cloud_instance.run_command(command)

    # command is executed locally
    check_output_mock.assert_called_once_with(command_split)
    assert result == expected_result


@pytest.mark.parametrize("sudo", [True, False])
def test_run_remote_command(patch_cloud_init, sudo, mocker):
    """Test running command when the cloud access method is 'ssh'.

    This test has two variants. Executing commands as regular user
    and executing them as root.
    """
    expected_result = MagicMock()
    expected_result.stdout = ".\n.."

    executor_method = "sudo" if sudo else "run"

    command = "ls -la"

    cloud_instance = cloud.Cloud(
        name="remote test cloud",
        access_method="ssh",
        ssh_host="juju.host",
        sudo_user="root" if sudo else "",
        cloud_type="test",
    )

    mocker.patch.object(
        cloud_instance.connection, executor_method, return_value=expected_result
    )

    result = cloud_instance.run_command(command)

    # command was executed remotely as root
    if sudo:
        cloud_instance.connection.sudo.assert_called_once_with(
            command, hide=True, warn=True
        )
    else:
        cloud_instance.connection.run.assert_called_once_with(
            command, hide=True, warn=True
        )
    assert result == expected_result.stdout


@pytest.mark.parametrize("sudo", [True, False])
def test_run_remote_command_fail(patch_cloud_init, sudo, mocker):
    """Test error logging when remote command fails.

    This test has two variants. Executing commands as regular user
    and executing them as root.
    """
    command = "ls -la"
    cloud_name = "remote test cloud"
    executor_method = "sudo" if sudo else "run"
    exception = cloud.SSHException()
    expected_message = "[{}] SSH command {} failed: {}".format(
        cloud_name, command, exception
    )

    cloud_instance = cloud.Cloud(
        name=cloud_name,
        access_method="ssh",
        ssh_host="juju.host",
        sudo_user="root" if sudo else "",
        cloud_type="test",
    )

    mocker.patch.object(
        cloud_instance.connection, executor_method, side_effect=exception
    )

    # reset logger mock to wipe any previous calls
    cloud_instance.logger.reset_mock()

    result = cloud_instance.run_command(command)

    # remote command failure was logged
    cloud_instance.logger.error.assert_called_once_with(expected_message)
    assert result is None


def test_yaml_loading():
    """Test loading yaml documents into list of dictionaries."""
    yaml_string = "controllers:\n" "  ctrl1:\n" "    current-model: test-model\n"
    expected_output = [{"controllers": {"ctrl1": {"current-model": "test-model"}}}]

    assert cloud.Cloud.parse_yaml(yaml_string) == expected_output


@pytest.mark.parametrize("success", [True, False])
def test_get_juju_controllers(patch_cloud_init, success, mocker):
    """Test method that retrieves a list of juju controllers.

    This test also verifies behavior in case the command to fetch controllers fails.
    """
    controller_name = "foo"
    controller_config = {
        "current-model": "default",
        "user": "admin",
        "access": "superuser",
    }
    controller_list = [{"controllers": {controller_name: controller_config}}]

    mocker.patch.object(cloud.Cloud, "run_command", return_value=success)
    mocker.patch.object(cloud.Cloud, "parse_yaml", return_value=controller_list)

    cloud_instance = cloud.Cloud(name="Test cloud")

    result = cloud_instance.get_juju_controllers()

    if success:
        assert result
        assert (
            cloud_instance.cloud_state[controller_name]["config"] == controller_config
        )
    else:
        assert not result
        assert controller_name not in cloud_instance.cloud_state
        cloud_instance.logger.error.assert_called_once_with(
            "[{}] Could not get controller list".format(cloud_instance.name)
        )


@pytest.mark.parametrize("success", [True, False])
def test_get_juju_models(patch_cloud_init, success, mocker):
    """Test methods that retrieves a list of juju models."""
    model_foo = {"name": "admin/foo", "short-name": "foo", "uuid": "129bd0f0"}
    model_bar = {"name": "admin/bar", "short-name": "bar", "uuid": "b513b5e3"}
    model_list = [{"models": [model_foo, model_bar]}] if success else []

    controller_name = "controller_1"
    controllers = {controller_name: {}} if success else {}

    run_cmd_mock = mocker.patch.object(cloud.Cloud, "run_command", return_value=success)
    mocker.patch.object(cloud.Cloud, "parse_yaml", return_value=model_list)
    mocker.patch.object(cloud.Cloud, "get_juju_controllers", return_value=controllers)

    cloud_instance = cloud.Cloud(name="Test cloud")
    cloud_instance.cloud_state = controllers

    result = cloud_instance.get_juju_models()

    if success:
        assert result
        run_cmd_mock.assert_called_once_with(
            "juju models -c {} --format yaml".format(controller_name)
        )
        for model in [model_foo, model_bar]:
            model_name = model["short-name"]
            model_config = cloud_instance.cloud_state[controller_name]["models"][
                model_name
            ]["config"]
            assert model_config == model
    else:
        assert not result
        for model in [model_foo, model_bar]:
            model_name = model["short-name"]
            assert model_name not in cloud_instance.cloud_state.get(
                controller_name, {}
            ).get("models", {})


@pytest.mark.parametrize("success", [True, False])
def test_get_juju_state(cloud_instance, success, mocker):
    """Test function "get_juju_state" that updates local juju state."""
    controller_foo = {
        "models": {"foo_1": "foo_1_model_data", "foo_2": "foo_2_model_data"}
    }
    controller_bar = {
        "models": {"bar_1": "bar_1_model_data", "bar_2": "bar_2_model_data"}
    }
    cloud_state = {"controller_foo": controller_foo, "controller_bar": controller_bar}

    expected_calls = [
        call("controller_foo", "foo_1"),
        call("controller_foo", "foo_2"),
        call("controller_bar", "bar_1"),
        call("controller_bar", "bar_2"),
    ]

    mocker.patch.object(cloud_instance, "get_juju_models", return_value=success)
    get_status_mock = mocker.patch.object(cloud_instance, "get_juju_status")
    get_bundle_mock = mocker.patch.object(cloud_instance, "get_juju_bundle")

    cloud_instance.cloud_state = cloud_state

    result = cloud_instance.get_juju_state()

    if success:
        assert result
        get_status_mock.assert_has_calls(expected_calls)
        get_bundle_mock.assert_has_calls(expected_calls)
    else:
        assert not result
        get_status_mock.assert_not_called()
        get_bundle_mock.assert_not_called()


def test_get_juju_status(cloud_instance, mocker):
    """Test updating status of a selected model."""
    model_version = "1"
    model_name = "foo model"
    controller_name = "foo controller"
    machine_1_implicit_name = "1"
    machine_2_implicit_name = "2"
    machine_2_explicit_name = "explicit_machine - 2"
    cmd_output_mock = "foo data"
    model_status = {
        "model": {"version": model_version},
        "machines": {
            machine_1_implicit_name: {"arch": "x86"},
            machine_2_implicit_name: {
                "arch": "armv7",
                "display-name": machine_2_explicit_name,
            },
        },
        "applications": {
            "ubuntu": {"application-status": {"current": "ready"}},
            "ntp": {"application-status": {"current": "waiting"}},
        },
    }

    run_cmd_mock = mocker.patch.object(
        cloud_instance, "run_command", return_value=cmd_output_mock
    )
    mocker.patch.object(cloud_instance, "parse_yaml", return_value=[model_status])

    cloud_instance.cloud_state = {controller_name: {"models": {model_name: {}}}}

    cloud_instance.get_juju_status(controller_name, model_name)

    # assert that correct command was called
    run_cmd_mock.assert_called_with(
        "juju status -m {}:{} --format yaml".format(controller_name, model_name)
    )

    model_data = cloud_instance.cloud_state[controller_name]["models"][model_name]
    # assert that application data was loaded to the model
    assert model_data["applications"] == model_status["applications"]
    # assert that both implicitly and explicitly named machines are loaded in the model
    expected_machines = {
        machine_1_implicit_name: {"arch": "x86", "machine_id": machine_1_implicit_name},
        machine_2_explicit_name: {
            "arch": "armv7",
            "display-name": machine_2_explicit_name,
            "machine_id": machine_2_implicit_name,
        },
    }
    assert model_data["machines"] == expected_machines


def test_refresh(cloud_instance, mocker):
    """Test refresh method."""
    expected_result = True
    get_state_mock = mocker.patch.object(
        cloud_instance, "get_juju_state", return_value=expected_result
    )

    result = cloud_instance.refresh()

    get_state_mock.assert_called_once()
    assert result == expected_result


def test_audit(patch_cloud_init, mocker):
    """Test execution of Audits for all models in cloud."""
    cloud_name = "Test Cloud"
    lint_rules = "some lint rules"
    override_rules = "some overrides"
    cloud_type = "openstack"
    cloud_state = {
        "controller_foo": {
            "models": {
                "model_foo_1": {"name": "foo_1"},
                "model_foo_2": {"name": "foo_2"},
            }
        },
        "controller_bar": {
            "models": {
                "model_bar_1": {"name": "bar_1"},
                "model_bar_2": {"name": "bar_2"},
            }
        },
    }
    expected_linter_init_calls = []
    expected_do_lint_calls = []
    expected_read_rules_calls = []
    for controller, controller_data in cloud_state.items():
        for model, model_data in controller_data["models"].items():
            expected_linter_init_calls.append(
                call(
                    cloud_name,
                    lint_rules,
                    overrides=override_rules,
                    cloud_type=cloud_type,
                    controller_name=controller,
                    model_name=model,
                )
            )
            expected_do_lint_calls.append(call(model_data))
            expected_read_rules_calls.append(call())

    linter_object_mock = MagicMock()

    linter_class_mock = mocker.patch.object(
        cloud, "Linter", return_value=linter_object_mock
    )

    cloud_instance = cloud.Cloud(
        name=cloud_name,
        lint_rules=lint_rules,
        lint_overrides=override_rules,
        cloud_type=cloud_type,
    )
    cloud_instance.cloud_state = cloud_state

    cloud_instance.audit()

    linter_class_mock.assert_has_calls(expected_linter_init_calls)
    linter_object_mock.read_rules.assert_has_calls(expected_read_rules_calls)
    linter_object_mock.do_lint.assert_has_calls(expected_do_lint_calls)
