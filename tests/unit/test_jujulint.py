#!/usr/bin/python3
"""Tests for jujulint."""
import logging
from datetime import datetime, timezone
from unittest import mock

import pytest
import yaml

from jujulint import lint
from jujulint.checks import relations, spaces
from jujulint.lint import VALID_LOG_LEVEL


class TestUtils:
    """Test the jujulint utilities."""

    def test_flatten_list(self, utils):
        """Test the utils flatten_list function."""
        unflattened_list = [1, [2, 3]]
        flattened_list = [1, 2, 3]
        assert flattened_list == utils.flatten_list(unflattened_list)

        unflattened_list = [1, [2, [3, 4]]]
        flattened_list = [1, 2, 3, 4]
        assert flattened_list == utils.flatten_list(unflattened_list)

    def test_flatten_list_non_list_iterable(self, utils):
        """Test the utils flatten_list function."""
        iterable = {1: 2}
        assert iterable == utils.flatten_list(iterable)

    def test_is_container(self, utils):
        """Test the utils is_container function."""
        assert utils.is_container("1/lxd/0") is True
        assert utils.is_container("0") is False

    def test_is_virtual_machine(self, utils):
        """Test the utils is_virtual_machine function."""
        machine = "0"
        machine_data = {
            "hardware": "arch=amd64 cores=2 mem=4096M tags=virtual,pod-console-logging,vault availability-zone=AZ3"
        }
        assert utils.is_virtual_machine(machine, machine_data) is True

        machine_data = {}
        assert utils.is_virtual_machine(machine, machine_data) is False

    def test_is_metal(self, utils):
        """Test the utils is_metal function."""
        # A VM should return false
        machine = "0"
        machine_data = {
            "hardware": "arch=amd64 cores=2 mem=4096M tags=virtual,pod-console-logging,vault availability-zone=AZ3"
        }
        assert utils.is_metal(machine, machine_data) is False

        # A container should return false
        assert utils.is_metal("1/lxd/0", {}) is False

        # A bare metal should return true
        machine = "1"
        machine_data = {
            "hardware": "arch=amd64 cores=128 mem=2093056M tags=foundation-nodes,hyper-converged-az2 "
            "availability-zone=AZ2"
        }
        assert utils.is_metal(machine, machine_data) is True


class TestLinter:
    """Test the main Linter class."""

    def test_minimal_rules(self, linter, juju_status):
        """Test that the base rules/status have no errors."""
        linter.do_lint(juju_status)
        assert len(linter.output_collector["errors"]) == 0

    def test_minimal_rules_without_subordinates(self, linter, juju_status):
        """Process rules with none of the applications having subordinate charms."""
        juju_status["applications"]["ubuntu"]["units"]["ubuntu/0"].pop("subordinates")
        juju_status["applications"].pop("ntp")
        linter.lint_rules["subordinates"] = {}

        linter.do_lint(juju_status)
        assert len(linter.output_collector["errors"]) == 0

    def test_minimal_rules_json_output(self, linter, juju_status, mocker):
        """Process rules and print output in json format."""
        expected_output = "{result: dict}"
        json_mock = mocker.patch.object(
            lint.json, "dumps", return_value=expected_output
        )
        print_mock = mocker.patch("builtins.print")

        linter.output_format = "json"
        linter.do_lint(juju_status)

        json_mock.assert_called_once_with(
            linter.output_collector, indent=2, sort_keys=True
        )
        print_mock.assert_called_once_with(expected_output)

    def test_charm_identification(self, linter, juju_status):
        """Test that applications are mapped to charms."""
        juju_status["applications"]["ubuntu2"] = {
            "application-status": {"current": "active"},
            "charm-name": "ubuntu",
            "relations": {"juju-info": ["ntp"]},
            "units": {
                "ubuntu2/0": {
                    "juju-status": {"current": "idle"},
                    "machine": "1",
                    "subordinates": {
                        "ntp/1": {
                            "juju-status": {"current": "idle"},
                            "workload-status": {"current": "error"},
                        }
                    },
                    "workload-status": {"current": "active"},
                }
            },
        }
        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]
        assert len(errors) == 1
        assert errors[0]["id"] == "charm-not-mapped"
        assert errors[0]["application"] == "ubuntu2"

    def test_map_charms(self, linter, utils):
        """Test the charm name validation code."""
        applications = {
            "test-app-1": {"charm": "cs:~USER/SERIES/TEST-CHARM12-123"},
            "test-app-2": {"charm": "cs:~USER/TEST-CHARM12-123"},
            "test-app-3": {"charm": "cs:TEST-CHARM12-123"},
            "test-app-4": {"charm": "local:SERIES/TEST-CHARM12"},
            "test-app-5": {"charm": "local:TEST-CHARM12"},
            "test-app-6": {"charm": "cs:~TEST-CHARMERS/TEST-CHARM12-123"},
            "test-app-7": {"charm": "ch:amd64/bionic/TEST-CHARM12-123"},
        }
        linter.map_charms(applications)
        for charm in linter.model.charms:
            assert "TEST-CHARM12" == charm
        applications = {
            "test-app1": {"charm": "cs:invalid-charm$"},
        }
        with pytest.raises(utils.InvalidCharmNameError):
            linter.map_charms(applications)

    def test_check_cloud_type(self, linter, mocker):
        """Test cloud_type detection on different scenarios."""
        mock_log = mocker.patch("jujulint.lint.Linter._log_with_header")
        #  test models with more or equal than two matches
        model_charms = {
            "openstack": {"keystone", "nova-compute", "glance", "foo"},
            "kubernetes": {"kubernetes-worker", "kubernetes-control-plane", "bar"},
        }
        # detect cloud_type depending on the deployment charms and
        # if it's not passe as an argument in the cli.
        for cloud_type, charms in model_charms.items():
            linter.cloud_type = None
            linter.check_cloud_type(charms)
            assert linter.cloud_type == cloud_type

        # in case cloud_type is passed doesn't change the value
        linter.cloud_type = "openstack"
        for cloud_type, charms in model_charms.items():
            linter.check_cloud_type(charms)
            assert linter.cloud_type == "openstack"

        # if it's an invalid cloud_type log warn to user
        linter.cloud_type = "foo-bar"
        linter.check_cloud_type({"foo", "bar"})
        mock_log.assert_called_with("Cloud type foo-bar is unknown", level=logging.WARN)

        # test models with less than 2 matches without passing cloud_type in the cli
        model_charms = {
            "openstack": {"keystone", "foo", "bar"},
            "kubernetes": {"foo", "bar"},
        }
        for cloud_type, charms in model_charms.items():
            linter.cloud_type = None
            linter.check_cloud_type(charms)
            assert linter.cloud_type is None

    def test_juju_status_unexpected(self, linter, juju_status):
        """Test that juju and workload status is expected."""
        # inject invalid status to the application
        juju_status["applications"]["ubuntu"]["units"]["ubuntu/0"][
            "workload-status"
        ].update(
            {
                "current": "executing",
                "since": "01 Apr 2021 05:14:13Z",
                "message": 'hook failed: "install"',
            }
        )
        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]
        assert len(errors) == 1
        assert errors[0]["id"] == "status-unexpected"
        assert errors[0]["status_current"] == "executing"
        assert errors[0]["status_since"] == "01 Apr 2021 05:14:13Z"
        assert errors[0]["status_msg"] == 'hook failed: "install"'

    def test_juju_status_ignore_recent_executing(self, linter, juju_status):
        """Test that recent executing status is ignored."""
        # inject a recent execution status to the unit
        since_datetime = datetime.now(timezone.utc)

        juju_status["applications"]["ubuntu"]["units"]["ubuntu/0"][
            "workload-status"
        ].update(
            {
                "current": "executing",
                "since": since_datetime.isoformat(),
                "message": 'hook failed: "install"',
            }
        )
        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]
        assert len(errors) == 0

    def test_az_parsing(self, linter, juju_status):
        """Test that the AZ parsing is working as expected."""
        # duplicate a AZ name so we have 2 AZs instead of the expected 3
        juju_status["machines"]["2"]["hardware"] = "availability-zone=rack-1"
        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]
        assert len(errors) == 1
        assert errors[0]["id"] == "AZ-invalid-number"
        assert errors[0]["num_azs"] == 2

    def test_az_missing(self, linter, juju_status, mocker):
        """Test that AZ parsing logs warning if AZ is not found."""
        # duplicate a AZ name so we have 2 AZs instead of the expected 3
        juju_status["machines"]["2"]["hardware"] = ""
        expected_msg = (
            "Machine 2 has no availability-zone info in hardware field; skipping."
        )
        logger_mock = mocker.patch.object(linter, "_log_with_header")

        linter.do_lint(juju_status)

        logger_mock.assert_any_call(expected_msg, level=logging.WARN)

    def test_az_balancing(self, linter, juju_status):
        """Test that applications are balanced across AZs."""
        # add an extra machine in an existing AZ
        juju_status["machines"].update(
            {
                "3": {
                    "hardware": "availability-zone=rack-3",
                    "juju-status": {"current": "started"},
                    "machine-status": {"current": "running"},
                    "modification-status": {"current": "applied"},
                }
            }
        )
        # add two more ubuntu units, but unbalanced (ubuntu/0 is in rack-1)
        juju_status["applications"]["ubuntu"]["units"].update(
            {
                "ubuntu/1": {
                    "juju-status": {"current": "idle"},
                    "machine": "2",
                    "subordinates": {
                        "ntp/1": {
                            "juju-status": {"current": "idle"},
                            "workload-status": {"current": "error"},
                        }
                    },
                    "workload-status": {"current": "active"},
                },
                "ubuntu/2": {
                    "juju-status": {"current": "idle"},
                    "machine": "3",
                    "subordinates": {
                        "ntp/2": {
                            "juju-status": {"current": "idle"},
                            "workload-status": {"current": "error"},
                        }
                    },
                    "workload-status": {"current": "active"},
                },
            }
        )
        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]
        assert len(errors) == 1
        assert errors[0]["id"] == "AZ-unbalance"
        assert errors[0]["application"] == "ubuntu"
        assert errors[0]["num_units"] == 3
        assert errors[0]["az_map"] == "rack-1: 1, rack-2: 0, rack-3: 2"

    def test_ops_charm_missing(self, linter, juju_status):
        """Test that missing ops mandatory charms are detected."""
        # add a new mandatory ops charm
        linter.lint_rules["operations mandatory"].append("telegraf")
        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]
        assert len(errors) == 1
        assert errors[0]["id"] == "ops-charm-missing"
        assert errors[0]["charm"] == "telegraf"

    def test_overlay_documents(self, linter, tmp_path):
        """Test offer overlay format for saas cross model offers."""
        # juju now exports two documents to exported files.
        #  We need to ignore the overlay document and still parse the main yaml doc
        yaml = """
applications:
  grafana:
    charm: cs:grafana-51
    channel: stable
    num_units: 1
    to:
    - 0
    options:
      install_method: snap
    bindings:
      "": oam-space
machines:
   0:
    constraints: tags=nagios spaces=oam-space
    series: bionic
--- # overlay.yaml
applications:
    grafana:
      offers:
       grafana:
         endpoints:
         - dashboards
         acl:
          admin: admin"""

        linter.lint_yaml_string(yaml)

        yaml_path = tmp_path / "bundle.yaml"
        yaml_path.write_text(yaml)

        linter.lint_yaml_file(yaml_path)

    def test_unrecognised_charm(self, linter, juju_status):
        """Test that unrecognised charms are detected."""
        # drop 'ubuntu' from the known charms
        linter.lint_rules["known charms"] = ["ntp"]
        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]
        assert len(errors) == 1
        assert errors[0]["id"] == "unrecognised-charm"
        assert errors[0]["charm"] == "ubuntu"

    def test_ops_subordinate_missing(self, linter, juju_status):
        """Test that missing ops subordinate charms are detected."""
        # drop the subordinate unit
        juju_status["applications"]["ubuntu"]["units"]["ubuntu/0"]["subordinates"] = {}
        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]
        assert len(errors) == 1
        assert errors[0]["id"] == "ops-subordinate-missing"
        assert errors[0]["principals"] == "ubuntu"
        assert errors[0]["subordinate"] == "ntp"

    def test_subordinate_extraneous(self, linter, juju_status):
        """Test that extraneous subordinate charms are detected."""
        # this check triggers on subordinates on containers that should only
        # be present in hosts
        linter.lint_rules["subordinates"]["ntp"]["where"] = "host only"
        juju_status["applications"]["ubuntu"]["units"]["ubuntu/0"][
            "machine"
        ] = "0/lxd/0"
        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]
        assert len(errors) == 1
        assert errors[0]["id"] == "subordinate-extraneous"
        assert errors[0]["principals"] == "ubuntu"
        assert errors[0]["subordinate"] == "ntp"

    def test_subordinate_duplicates(self, linter, juju_status):
        """Test that subordinate charms are not duplicated."""
        ntp0 = juju_status["applications"]["ubuntu"]["units"]["ubuntu/0"][
            "subordinates"
        ]["ntp/0"]
        juju_status["applications"]["ubuntu"]["units"]["ubuntu/0"]["subordinates"][
            "ntp/1"
        ] = ntp0
        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]
        assert len(errors) == 1
        assert errors[0]["id"] == "subordinate-duplicate"
        assert errors[0]["machines"] == "0"
        assert errors[0]["subordinate"] == "ntp"

    def test_subordinate_duplicates_allow(self, linter, juju_status):
        """
        Test the subordinate option "allow-multiple".

        Setting it to true will skip the duplicate check for subordinates
        """
        template_status = {
            "juju-status": {"current": "idle"},
            "workload-status": {"current": "active"},
        }

        # Drop the fixture ntp rule and add the nrpe rule with allowing duplicates
        linter.lint_rules["subordinates"].pop("ntp")
        linter.lint_rules["subordinates"]["nrpe"] = {
            "where": "container aware",
            "host-suffixes": "[host, physical, guest]",
            "allow-multiple": True,
        }

        # Add a nrpe-host subordinate application
        linter.lint_rules["known charms"].append("nrpe")
        juju_status["applications"]["nrpe-host"] = {
            "application-status": {"current": "active"},
            "charm": "cs:nrpe-74",
            "charm-name": "nrpe",
            "relations": {"juju-info": ["ubuntu", "ubuntu2"]},
        }

        # Add a nrpe-host subordinate unit to the 'ubuntu' app
        juju_status["applications"]["ubuntu"]["units"]["ubuntu/0"]["subordinates"] = {
            "nrpe-host/0": template_status
        }

        # Add a second 'ubuntu' app with nrpe subordinate
        juju_status["applications"]["ubuntu2"] = {
            "application-status": {"current": "active"},
            "charm": "cs:ubuntu-18",
            "charm-name": "ubuntu",
            "relations": {"juju-info": ["ntp", "nrpe-host"]},
            "units": {
                "ubuntu2/0": {
                    "juju-status": {"current": "idle"},
                    "machine": "0",
                    "subordinates": {"nrpe-host/1": template_status},
                    "workload-status": {"current": "active"},
                }
            },
        }

        linter.do_lint(juju_status)

        # Since we allow duplicates there should be no errors
        errors = linter.output_collector["errors"]
        assert not errors

    def test_ops_subordinate_metal_only1(self, linter, juju_status):
        """
        Test that missing ops subordinate charms are detected.

        Use the "metal only" rule in a bare metal machine, should report the
        missing subordinate
        """
        linter.lint_rules["subordinates"]["hw-health"] = {"where": "metal only"}
        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]
        assert len(errors) == 1
        assert errors[0]["id"] == "ops-subordinate-missing"
        assert errors[0]["principals"] == "ubuntu"
        assert errors[0]["subordinate"] == "hw-health"

    def test_ops_subordinate_metal_only2(self, linter, juju_status):
        """
        Test that missing ops subordinate charms are detected.

        Use the "metal only" rule in a VM, should ignore it
        """
        linter.lint_rules["subordinates"]["hw-health"] = {"where": "metal only"}

        # Turn machine "0" into a "VM"
        juju_status["machines"]["0"][
            "hardware"
        ] = "tags=virtual availability-zone=rack-1"
        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]
        assert not errors

    def test_openstack_charm_missing(self, linter, juju_status):
        """Test that missing openstack mandatory charms are detected."""
        linter.cloud_type = "openstack"
        linter.lint_rules["openstack mandatory"] = ["keystone"]
        linter.lint_rules["operations openstack mandatory"] = ["ubuntu"]
        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]
        assert len(errors) == 1
        assert errors[0]["id"] == "openstack-charm-missing"
        assert errors[0]["charm"] == "keystone"

    def test_openstack_ops_charm_missing(self, linter, juju_status):
        """Test that missing openstack mandatory ops charms are detected."""
        linter.cloud_type = "openstack"
        linter.lint_rules["openstack mandatory"] = ["ubuntu"]
        linter.lint_rules["operations openstack mandatory"] = [
            "openstack-service-checks"
        ]
        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]
        assert len(errors) == 1
        assert errors[0]["id"] == "openstack-ops-charm-missing"
        assert errors[0]["charm"] == "openstack-service-checks"

    def test_kubernetes_charm_missing(self, linter, juju_status):
        """Test that missing kubernetes mandatory charms are detected."""
        linter.cloud_type = "kubernetes"
        linter.lint_rules["kubernetes mandatory"] = ["kubernetes-control-plane"]
        linter.lint_rules["operations kubernetes mandatory"] = []
        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]
        assert len(errors) == 1
        assert errors[0]["id"] == "kubernetes-charm-missing"
        assert errors[0]["charm"] == "kubernetes-control-plane"

    def test_kubernetes_ops_charm_missing(self, linter, juju_status):
        """Test that missing kubernetes mandatory charms are detected."""
        linter.cloud_type = "kubernetes"
        linter.lint_rules["kubernetes mandatory"] = []
        linter.lint_rules["operations kubernetes mandatory"] = ["ntp"]
        juju_status["applications"].pop("ntp")  # drop the app from the model
        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]
        assert len(errors) == 1
        assert errors[0]["id"] == "kubernetes-ops-charm-missing"
        assert errors[0]["charm"] == "ntp"

    @pytest.mark.parametrize(
        "custom_message, log_level, generate_error",
        [
            ("", "", True),  # generate error, no custom message
            ("custom message", "", True),  # generate error with custom message
            ("", "foo", True),  # generate error, no custom message
            (
                "custom message",
                "warning",
                False,
            ),  # doesn't generate error with custom message
            (
                "custom message",
                "WARNING",
                False,
            ),  # doesn't generate error with custom message
            ("", "info", False),  # doesn't generate error, no custom message
            ("", "debug", False),  # doesn't generate error, no custom message
        ],
    )
    def test_config_eq(
        self, linter, juju_status, custom_message, log_level, generate_error
    ):
        """Test the config condition 'eq' with custom messages and log levels."""
        linter.lint_rules["config"] = {"ubuntu": {"fake-opt": {"eq": False}}}
        juju_status["applications"]["ubuntu"]["options"] = {"fake-opt": True}
        if custom_message:
            linter.lint_rules["config"]["ubuntu"]["fake-opt"][
                "custom-message"
            ] = custom_message
        if log_level:
            linter.lint_rules["config"]["ubuntu"]["fake-opt"]["log-level"] = log_level

        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]

        if log_level.lower() != "error" and log_level.lower() in VALID_LOG_LEVEL:
            assert not generate_error
            assert len(errors) == 0

        else:
            assert len(errors) == 1
            assert errors[0]["id"] == "config-eq-check"
            assert errors[0]["application"] == "ubuntu"
            assert errors[0]["rule"] == "fake-opt"
            assert errors[0]["expected_value"] is False
            assert errors[0]["actual_value"] is True

    @pytest.mark.parametrize(
        "custom_message, log_level, generate_error",
        [
            ("", "", True),  # generate error, no custom message
            ("custom message", "", True),  # generate error with custom message
            ("", "foo", True),  # generate error, no custom message
            (
                "custom message",
                "warning",
                False,
            ),  # doesn't generate error with custom message
            (
                "custom message",
                "WARNING",
                False,
            ),  # doesn't generate error with custom message
            ("", "info", False),  # doesn't generate error, no custom message
            ("", "debug", False),  # doesn't generate error, no custom message
        ],
    )
    def test_config_eq_suffix_match(
        self, linter, juju_status, custom_message, log_level, generate_error
    ):
        """Test the config condition 'eq'. when suffix matches with custom messages and log levels."""
        linter.lint_rules["config"] = {
            "ubuntu": {"fake-opt": {"eq": False, "suffixes": ["host", "physical"]}}
        }
        juju_status["applications"]["ubuntu"]["options"] = {"fake-opt": True}
        juju_status["applications"]["ubuntu-host"] = juju_status["applications"].pop(
            "ubuntu"
        )
        if custom_message:
            linter.lint_rules["config"]["ubuntu"]["fake-opt"][
                "custom-message"
            ] = custom_message
        if log_level:
            linter.lint_rules["config"]["ubuntu"]["fake-opt"]["log-level"] = log_level

        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]

        if log_level.lower() != "error" and log_level.lower() in VALID_LOG_LEVEL:
            assert not generate_error
            assert len(errors) == 0
        else:
            assert len(errors) == 1
            assert errors[0]["id"] == "config-eq-check"
            assert errors[0]["application"] == "ubuntu-host"
            assert errors[0]["rule"] == "fake-opt"
            assert errors[0]["expected_value"] is False
            assert errors[0]["actual_value"] is True
            if custom_message:
                assert errors[0]["message"] == custom_message
            else:
                assert errors[0]["message"] != custom_message

    @pytest.mark.parametrize(
        "custom_message, log_level, generate_error",
        [
            ("", "", True),  # generate error, no custom message
            ("custom message", "", True),  # generate error with custom message
            ("", "foo", True),  # generate error, no custom message
            (
                "custom message",
                "warning",
                False,
            ),  # doesn't generate error with custom message
            (
                "custom message",
                "WARNING",
                False,
            ),  # doesn't generate error with custom message
            ("", "info", False),  # doesn't generate error, no custom message
            ("", "debug", False),  # doesn't generate error, no custom message
        ],
    )
    def test_config_eq_suffix_match_charm_name(
        self, linter, juju_status, custom_message, log_level, generate_error
    ):
        """Test the config condition 'eq'. when suffix and base charm name."""
        linter.lint_rules["config"] = {
            "ubuntu": {"fake-opt": {"eq": False, "suffixes": ["host", "physical"]}}
        }
        juju_status["applications"]["ubuntu"]["options"] = {"fake-opt": True}
        if custom_message:
            linter.lint_rules["config"]["ubuntu"]["fake-opt"][
                "custom-message"
            ] = custom_message
        if log_level:
            linter.lint_rules["config"]["ubuntu"]["fake-opt"]["log-level"] = log_level

        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]

        if log_level.lower() != "error" and log_level.lower() in VALID_LOG_LEVEL:
            assert not generate_error
            assert len(errors) == 0

        else:
            assert len(errors) == 1
            assert errors[0]["id"] == "config-eq-check"
            assert errors[0]["application"] == "ubuntu"
            assert errors[0]["rule"] == "fake-opt"
            assert errors[0]["expected_value"] is False
            assert errors[0]["actual_value"] is True
            if custom_message:
                assert errors[0]["message"] == custom_message
            else:
                assert errors[0]["message"] != custom_message

    def test_config_eq_suffix_skip(self, linter, juju_status):
        """Test the config condition 'eq'. when suffix doesn't match."""
        linter.lint_rules["config"] = {
            "ubuntu": {"fake-opt": {"eq": False, "suffixes": ["host", "physical"]}}
        }
        juju_status["applications"]["ubuntu"]["options"] = {"fake-opt": True}
        juju_status["applications"]["ubuntu-container"] = juju_status[
            "applications"
        ].pop("ubuntu")
        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]
        assert not errors

    @pytest.mark.parametrize(
        "custom_message, log_level, generate_error",
        [
            ("", "", True),  # generate error, no custom message
            ("custom message", "", True),  # generate error with custom message
            ("", "foo", True),  # generate error, no custom message
            (
                "custom message",
                "warning",
                False,
            ),  # doesn't generate error with custom message
            (
                "custom message",
                "WARNING",
                False,
            ),  # doesn't generate error with custom message
            ("", "info", False),  # doesn't generate error, no custom message
            ("", "debug", False),  # doesn't generate error, no custom message
        ],
    )
    def test_config_eq_no_suffix_check_all(
        self, linter, juju_status, custom_message, log_level, generate_error
    ):
        """Test the config condition 'eq'. when no suffix all should be checked."""
        linter.lint_rules["config"] = {"ubuntu": {"fake-opt": {"eq": False}}}
        juju_status["applications"]["ubuntu"]["options"] = {"fake-opt": True}
        juju_status["applications"]["ubuntu-host"] = juju_status["applications"].pop(
            "ubuntu"
        )
        if custom_message:
            linter.lint_rules["config"]["ubuntu"]["fake-opt"][
                "custom-message"
            ] = custom_message
        if log_level:
            linter.lint_rules["config"]["ubuntu"]["fake-opt"]["log-level"] = log_level

        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]

        if log_level.lower() != "error" and log_level.lower() in VALID_LOG_LEVEL:
            assert not generate_error
            assert len(errors) == 0

        else:
            assert len(errors) == 1
            assert errors[0]["id"] == "config-eq-check"
            assert errors[0]["application"] == "ubuntu-host"
            assert errors[0]["rule"] == "fake-opt"
            assert errors[0]["expected_value"] is False
            assert errors[0]["actual_value"] is True
            if custom_message:
                assert errors[0]["message"] == custom_message
            else:
                assert errors[0]["message"] != custom_message

    def test_config_neq_valid(self, linter, juju_status):
        """Test the config condition 'neq'."""
        linter.lint_rules["config"] = {"ubuntu": {"fake-opt": {"neq": "foo"}}}
        juju_status["applications"]["ubuntu"]["options"] = {"fake-opt": "bar"}
        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]
        assert len(errors) == 0

    @pytest.mark.parametrize(
        "custom_message, log_level, generate_error",
        [
            ("", "", True),  # generate error, no custom message
            ("custom message", "", True),  # generate error with custom message
            ("", "foo", True),  # generate error, no custom message
            (
                "custom message",
                "warning",
                False,
            ),  # doesn't generate error with custom message
            (
                "custom message",
                "WARNING",
                False,
            ),  # doesn't generate error with custom message
            ("", "info", False),  # doesn't generate error, no custom message
            ("", "debug", False),  # doesn't generate error, no custom message
        ],
    )
    def test_config_neq_invalid(
        self, linter, juju_status, custom_message, log_level, generate_error
    ):
        """Test the config condition 'neq', invalid with custom messages and log levels."""
        linter.lint_rules["config"] = {"ubuntu": {"fake-opt": {"neq": ""}}}
        juju_status["applications"]["ubuntu"]["options"] = {"fake-opt": ""}
        if custom_message:
            linter.lint_rules["config"]["ubuntu"]["fake-opt"][
                "custom-message"
            ] = custom_message
        if log_level:
            linter.lint_rules["config"]["ubuntu"]["fake-opt"]["log-level"] = log_level

        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]

        if log_level.lower() != "error" and log_level.lower() in VALID_LOG_LEVEL:
            assert not generate_error
            assert len(errors) == 0

        else:
            assert len(errors) == 1
            assert errors[0]["id"] == "config-neq-check"
            assert errors[0]["application"] == "ubuntu"
            assert errors[0]["rule"] == "fake-opt"
            assert errors[0]["expected_value"] == ""
            assert errors[0]["actual_value"] == ""
            if custom_message:
                assert errors[0]["message"] == custom_message
            else:
                assert errors[0]["message"] != custom_message

    @pytest.mark.parametrize(
        "custom_message, log_level, generate_error",
        [
            ("", "", True),  # generate error, no custom message
            ("custom message", "", True),  # generate error with custom message
            ("", "foo", True),  # generate error, no custom message
            (
                "custom message",
                "warning",
                False,
            ),  # doesn't generate error with custom message
            (
                "custom message",
                "WARNING",
                False,
            ),  # doesn't generate error with custom message
            ("", "info", False),  # doesn't generate error, no custom message
            ("", "debug", False),  # doesn't generate error, no custom message
        ],
    )
    def test_config_gte(
        self, linter, juju_status, custom_message, log_level, generate_error
    ):
        """Test the config condition 'gte' with custom messages and log levels."""
        linter.lint_rules["config"] = {"ubuntu": {"fake-opt": {"gte": 3}}}
        juju_status["applications"]["ubuntu"]["options"] = {"fake-opt": 0}
        if custom_message:
            linter.lint_rules["config"]["ubuntu"]["fake-opt"][
                "custom-message"
            ] = custom_message
        if log_level:
            linter.lint_rules["config"]["ubuntu"]["fake-opt"]["log-level"] = log_level

        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]

        if log_level.lower() != "error" and log_level.lower() in VALID_LOG_LEVEL:
            assert not generate_error
            assert len(errors) == 0

        else:
            assert generate_error
            assert len(errors) == 1
            assert errors[0]["id"] == "config-gte-check"
            assert errors[0]["application"] == "ubuntu"
            assert errors[0]["rule"] == "fake-opt"
            assert errors[0]["expected_value"] == 3
            assert errors[0]["actual_value"] == 0
            if custom_message:
                assert errors[0]["message"] == custom_message
            else:
                assert errors[0]["message"] != custom_message

    @pytest.mark.parametrize(
        "custom_message, log_level, generate_error",
        [
            ("", "", True),  # generate error, no custom message
            ("custom message", "", True),  # generate error with custom message
            ("", "foo", True),  # generate error, no custom message
            (
                "custom message",
                "warning",
                False,
            ),  # doesn't generate error with custom message
            (
                "custom message",
                "WARNING",
                False,
            ),  # doesn't generate error with custom message
            ("", "info", False),  # doesn't generate error, no custom message
            ("", "debug", False),  # doesn't generate error, no custom message
        ],
    )
    def test_config_isset_false_fail(
        self, linter, juju_status, custom_message, log_level, generate_error
    ):
        """Test message handling if config condition 'isset'=false is not met."""
        linter.lint_rules["config"] = {"ubuntu": {"fake-opt": {"isset": False}}}
        juju_status["applications"]["ubuntu"]["options"] = {"fake-opt": 0}
        if custom_message:
            linter.lint_rules["config"]["ubuntu"]["fake-opt"][
                "custom-message"
            ] = custom_message
        if log_level:
            linter.lint_rules["config"]["ubuntu"]["fake-opt"]["log-level"] = log_level

        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]

        if log_level.lower() != "error" and log_level.lower() in VALID_LOG_LEVEL:
            assert not generate_error
            assert len(errors) == 0

        else:
            assert len(errors) == 1
            assert errors[0]["id"] == "config-isset-check-false"
            assert errors[0]["application"] == "ubuntu"
            assert errors[0]["rule"] == "fake-opt"
            assert errors[0]["actual_value"] == 0
            if custom_message:
                assert errors[0]["message"] == custom_message
            else:
                assert errors[0]["message"] != custom_message

    def test_config_isset_false_pass(self, linter, juju_status):
        """Test handling if config condition 'isset'=false is met."""
        linter.lint_rules["config"] = {"ubuntu": {"fake-opt": {"isset": False}}}
        juju_status["applications"]["ubuntu"]["options"] = {}
        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]
        assert len(errors) == 0

    @pytest.mark.parametrize(
        "custom_message, log_level, generate_error",
        [
            ("", "", True),  # generate error, no custom message
            ("custom message", "", True),  # generate error with custom message
            ("", "foo", True),  # generate error, no custom message
            (
                "custom message",
                "warning",
                False,
            ),  # doesn't generate error with custom message
            (
                "custom message",
                "WARNING",
                False,
            ),  # doesn't generate error with custom message
            ("", "info", False),  # doesn't generate error, no custom message
            ("", "debug", False),  # doesn't generate error, no custom message
        ],
    )
    def test_config_isset_true_fail(
        self, linter, juju_status, custom_message, log_level, generate_error
    ):
        """Test message handling if config condition 'isset'=true is not met."""
        linter.lint_rules["config"] = {"ubuntu": {"fake-opt": {"isset": True}}}
        juju_status["applications"]["ubuntu"]["options"] = {}
        if custom_message:
            linter.lint_rules["config"]["ubuntu"]["fake-opt"][
                "custom-message"
            ] = custom_message
        if log_level:
            linter.lint_rules["config"]["ubuntu"]["fake-opt"]["log-level"] = log_level

        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]

        if log_level.lower() != "error" and log_level.lower() in VALID_LOG_LEVEL:
            assert not generate_error
            assert len(errors) == 0

        else:
            assert len(errors) == 1
            assert errors[0]["id"] == "config-isset-check-true"
            assert errors[0]["application"] == "ubuntu"
            assert errors[0]["rule"] == "fake-opt"
            if custom_message:
                assert errors[0]["message"] == custom_message
            else:
                assert errors[0]["message"] != custom_message

    def test_config_isset_true_pass(self, linter, juju_status):
        """Test handling if config condition 'isset'=true is met."""
        linter.lint_rules["config"] = {"ubuntu": {"fake-opt": {"isset": True}}}
        juju_status["applications"]["ubuntu"]["options"] = {"fake-opt": 0}
        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]
        assert len(errors) == 0

    def test_config_search_valid(self, linter, juju_status):
        """Test the config condition 'search' when valid."""
        linter.lint_rules["config"] = {
            "ubuntu": {"fake_opt": {"search": "\\W\\*, \\W\\*, 25000, 27500"}}
        }
        juju_status["applications"]["ubuntu"]["options"] = {
            "fake_opt": "[[/, queue1, 10, 20], [\\*, \\*, 25000, 27500]]"
        }
        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]
        assert len(errors) == 0

    @pytest.mark.parametrize(
        "custom_message, log_level, generate_error",
        [
            ("", "", True),  # generate error, no custom message
            ("custom message", "", True),  # generate error with custom message
            ("", "foo", True),  # generate error, no custom message
            (
                "custom message",
                "warning",
                False,
            ),  # doesn't generate error with custom message
            (
                "custom message",
                "WARNING",
                False,
            ),  # doesn't generate error with custom message
            ("", "info", False),  # doesn't generate error, no custom message
            ("", "debug", False),  # doesn't generate error, no custom message
        ],
    )
    def test_config_search_invalid(
        self, linter, juju_status, custom_message, log_level, generate_error
    ):
        """Test the config condition 'search' when invalid."""
        linter.lint_rules["config"] = {
            "ubuntu": {"fake-opt": {"search": "\\W\\*, \\W\\*, 25000, 27500"}}
        }
        juju_status["applications"]["ubuntu"]["options"] = {
            "fake-opt": "[[/, queue1, 10, 20], [\\*, \\*, 10, 20]]"
        }
        if custom_message:
            linter.lint_rules["config"]["ubuntu"]["fake-opt"][
                "custom-message"
            ] = custom_message
        if log_level:
            linter.lint_rules["config"]["ubuntu"]["fake-opt"]["log-level"] = log_level

        linter.do_lint(juju_status)

        errors = linter.output_collector["errors"]

        if log_level.lower() != "error" and log_level.lower() in VALID_LOG_LEVEL:
            assert not generate_error
            assert len(errors) == 0

        else:
            assert len(errors) == 1
            assert errors[0]["id"] == "config-search-check"
            assert errors[0]["application"] == "ubuntu"
            assert errors[0]["rule"] == "fake-opt"
            assert errors[0]["expected_value"] == "\\W\\*, \\W\\*, 25000, 27500"
            assert (
                errors[0]["actual_value"] == "[[/, queue1, 10, 20], [\\*, \\*, 10, 20]]"
            )

    def test_config_search_missing(self, linter, mocker):
        """Test the config search method logs warning if the config option is missing."""
        app_name = "ubuntu"
        check_value = 0
        config_key = "missing-opt"
        app_config = {}
        expected_log = (
            "Application {} has no config for '{}', can't search the regex pattern "
            "{}."
        ).format(app_name, config_key, repr(check_value))

        logger_mock = mocker.patch.object(linter, "_log_with_header")

        result = linter.search(app_name, check_value, config_key, app_config)

        assert result is False
        logger_mock.assert_called_once_with(expected_log, level=logging.WARN)

    def test_check_config_generic_missing_option(self, linter, mocker):
        """Test behavior of check_config_generic() when config option is missing."""
        operator_ = lint.ConfigOperator(
            name="eq", repr="==", check=None, error_template=""
        )
        app_name = "ubuntu"
        check_value = 0
        config_key = "missing-opt"
        app_config = {}
        expected_log = (
            "Application {} has no config for '{}', cannot determine if {} " "{}."
        ).format(app_name, config_key, operator_.repr, repr(check_value))

        logger_mock = mocker.patch.object(linter, "_log_with_header")

        result = linter.check_config_generic(
            operator_, app_name, check_value, config_key, app_config
        )

        logger_mock.assert_called_once_with(expected_log, level=logging.WARN)
        assert result is False

    def test_check_config_unknown_check_operator(self, linter, mocker):
        """Test that warning is logged when unknown check operator is encountered."""
        app_name = "ubuntu"
        config = {}
        bad_rule = "bad_rule"
        bad_check = "bad_check"
        rules = {bad_rule: {bad_check: 0}}
        expected_log = (
            "Application {} has unknown check operation for {}: " "{}."
        ).format(app_name, bad_rule, bad_check)

        logger_mock = mocker.patch.object(linter, "_log_with_header")

        linter.check_config(app_name, config, rules)
        logger_mock.assert_any_call(expected_log, level=logging.WARN)

    def test_parse_cmr_apps_export_bundle(self, linter):
        """Test the charm CMR parsing for bundles."""
        parsed_yaml = {
            "saas": {
                "grafana": {"url": "foundations-maas:admin/lma.grafana"},
                "nagios": {"url": "foundations-maas:admin/lma.nagios-monitors"},
            }
        }
        linter.parse_cmr_apps(parsed_yaml)
        assert linter.model.cmr_apps == {"grafana", "nagios"}

    def test_parse_cmr_apps_jsfy(self, linter):
        """Test the charm CMR parsing for juju status."""
        parsed_yaml = {
            "application-endpoints": {
                "grafana": {"url": "foundations-maas:admin/lma.grafana"},
                "nagios": {"url": "foundations-maas:admin/lma.nagios-monitors"},
            }
        }
        linter.parse_cmr_apps(parsed_yaml)
        assert linter.model.cmr_apps == {"grafana", "nagios"}

    def test_parse_cmr_apps_libjuju(self, linter):
        """Test the charm CMR parsing for libjuju."""
        parsed_yaml = {
            "remote-applications": {
                "grafana": {"url": "foundations-maas:admin/lma.grafana"},
                "nagios": {"url": "foundations-maas:admin/lma.nagios-monitors"},
            }
        }
        linter.parse_cmr_apps(parsed_yaml)
        assert linter.model.cmr_apps == {"grafana", "nagios"}

    def test_parse_cmr_apps_graylog(self, linter):
        """Test the charm CMR parsing adds elasticsearch dependency if graylog is present."""
        parsed_yaml = {
            "saas": {
                "graylog": {"url": "foundations-maas:admin/lma.graylog"},
            }
        }
        linter.parse_cmr_apps(parsed_yaml)
        assert linter.model.cmr_apps == {"graylog", "elasticsearch"}

    def test_check_charms_ops_mandatory_crm_success(self, linter):
        """
        Test the logic for checking ops mandatory charms provided via CMR.

        The app is in the saas rules and has a CMR, no error is expected
        """
        linter.lint_rules["saas"] = ["grafana"]
        linter.model.cmr_apps.add("grafana")
        error = linter.check_charms_ops_mandatory("grafana")

        assert error is None

    def test_check_charms_ops_mandatory_crm_fail1(self, linter):
        """
        Test the logic for checking ops mandatory charms provided via CMR.

        The app is not in the saas rules, should report an error
        """
        linter.model.cmr_apps.add("grafana")
        error = linter.check_charms_ops_mandatory("grafana")

        # The app is not in the rules, should report an error
        assert error is not None
        assert error["id"] == "ops-charm-missing"
        assert error["charm"] == "grafana"

    def test_check_charms_ops_mandatory_crm_fail2(self, linter):
        """
        Test the logic for checking ops mandatory charms provided via CMR.

        The app is in the saas rules, but no CMR in place, should report error
        """
        linter.lint_rules["saas"] = ["grafana"]
        error = linter.check_charms_ops_mandatory("grafana")

        assert error is not None
        assert error["id"] == "ops-charm-missing"
        assert error["charm"] == "grafana"

    def test_read_rules_plain_yaml(self, linter, tmp_path):
        """Test that a simple rules YAML is imported as expected."""
        rules_path = tmp_path / "rules.yaml"
        rules_path.write_text('---\nkey:\n "value"')

        linter.filename = str(rules_path)
        result = linter.read_rules()
        assert linter.lint_rules == {"key": "value"}
        assert result

    def test_snap_rules_files(self, rules_files, linter):
        """Ensure that all standard rules in the snap is loading correctly."""
        for rule_file in rules_files:
            try:
                linter.filename = rule_file
                linter.read_rules()
            except yaml.YAMLError:
                pytest.fail(f"File: {rule_file} not loading")

    def test_wrong_rule_file_raise_error(self, rules_files, linter, mocker):
        """Test that bad formatted rules raise YAMLError."""
        rules_file = rules_files[0]
        linter.filename = rules_file
        mocker.patch(
            "jujulint.lint.Linter._process_includes_in_rules",
            side_effect=yaml.YAMLError,
        )
        with pytest.raises(yaml.YAMLError):
            linter.read_rules()

    def test_read_rules_include(self, linter, tmp_path):
        """Test that rules YAML with an include is imported as expected."""
        include_path = tmp_path / "include.yaml"
        include_path.write_text('key-inc:\n "value2"')

        rules_path = tmp_path / "rules.yaml"
        rules_path.write_text('---\n!include include.yaml\nkey:\n "value"')

        linter.filename = str(rules_path)
        result = linter.read_rules()
        assert linter.lint_rules == {"key": "value", "key-inc": "value2"}
        assert result

    def test_read_rules_overrides(self, linter, tmp_path):
        """Test application of override values to the rules."""
        rules_path = tmp_path / "rules.yaml"
        rules_path.write_text('---\nkey:\n "value"\nsubordinates: {}')

        linter.overrides = "override_1:value_1#override_2:value_2"

        linter.filename = str(rules_path)
        linter.read_rules()
        assert linter.lint_rules == {
            "key": "value",
            "subordinates": {
                "override_1": {"where": "value_1"},
                "override_2": {"where": "value_2"},
            },
        }

    def test_read_rules_fail(self, linter, mocker):
        """Test handling of a read_rules() failure."""
        rule_file = "rules.yaml"
        mocker.patch.object(lint.os.path, "isfile", return_value=False)
        logger_mock = mock.MagicMock()
        linter.logger = logger_mock
        linter.filename = rule_file

        result = linter.read_rules()

        assert not result
        logger_mock.error.assert_called_once_with(
            "Rules file {} does not exist.".format(rule_file)
        )

    check_spaces_example_bundle = {
        "applications": {
            "prometheus-app": {
                "bindings": {
                    "target": "internal-space",
                },
            },
            "telegraf-app": {
                "bindings": {
                    "prometheus-client": "external-space",
                },
            },
        },
        "relations": [
            ["telegraf-app:prometheus-client", "prometheus-app:target"],
        ],
    }

    check_spaces_example_app_charm_map = {
        "prometheus-app": "prometheus",
        "telegraf-app": "telegraf",
    }

    def test_check_spaces_detect_mismatches(self, linter, mocker):
        """Test that check spaces mismatch gives warning message."""
        mock_log: mock.MagicMock = mocker.patch("jujulint.lint.Linter._log_with_header")
        linter.model.app_to_charm = self.check_spaces_example_app_charm_map

        # Run the space check.
        # Based on the above bundle, we should have exactly one mismatch.
        linter.check_spaces(self.check_spaces_example_bundle)

        # By default the mismatch should only trigger a warning, not an error.
        errors = linter.output_collector["errors"]
        assert len(errors) == 0
        assert mock_log.call_count == 1
        assert mock_log.mock_calls[0].kwargs["level"] == logging.WARN
        assert mock_log.mock_calls[0].args[0] == (
            "Space binding mismatch: SpaceMismatch(prometheus-app:target "
            "(space internal-space) != telegraf-app:prometheus-client (space external-space))"
        )

    def test_check_spaces_enforce_endpoints(self, linter):
        """Test that check spaces enforce endpoints."""
        linter.model.app_to_charm = self.check_spaces_example_app_charm_map

        # Run the space check with prometheus:target endpoint enforced.
        # This should generate an error.
        linter.lint_rules["space checks"] = {"enforce endpoints": ["prometheus:target"]}
        linter.check_spaces(self.check_spaces_example_bundle)
        errors = linter.output_collector["errors"]
        assert len(errors) == 1

        # Enforce the opposite end of the relation.
        # This should also generate an error.
        linter.lint_rules["space checks"] = {
            "enforce endpoints": ["telegraf:prometheus-client"]
        }
        linter.check_spaces(self.check_spaces_example_bundle)
        errors = linter.output_collector["errors"]
        assert len(errors) == 2

    def test_check_spaces_enforce_relations(self, linter):
        """Test that check spaces enforce relations."""
        linter.model.app_to_charm = self.check_spaces_example_app_charm_map

        # Run the space check with prometheus:target endpoint enforced.
        # This should generate an error.
        linter.lint_rules["space checks"] = {
            "enforce relations": [["prometheus:target", "telegraf:prometheus-client"]]
        }
        linter.check_spaces(self.check_spaces_example_bundle)
        errors = linter.output_collector["errors"]
        assert len(errors) == 1

        # Reverse the relation's definition order.
        # This should work the same way and also generate an error.
        linter.lint_rules["space checks"] = {
            "enforce relations": [["telegraf:prometheus-client", "prometheus:target"]]
        }
        linter.check_spaces(self.check_spaces_example_bundle)
        errors = linter.output_collector["errors"]
        assert len(errors) == 2

    def test_check_spaces_ignore_endpoints(self, linter, mocker):
        """Test that check spaces can ignore endpoints."""
        mock_log: mock.MagicMock = mocker.patch("jujulint.lint.Linter._log_with_header")
        linter.model.app_to_charm = self.check_spaces_example_app_charm_map

        # Run the space check with prometheus:target endpoint ignored.
        # This should generate an error.
        linter.lint_rules["space checks"] = {"ignore endpoints": ["prometheus:target"]}
        linter.check_spaces(self.check_spaces_example_bundle)
        errors = linter.output_collector["errors"]
        assert len(errors) == 0
        assert mock_log.call_count == 0

        # Enforce the opposite end of the relation.
        # This should also generate an error.
        linter.lint_rules["space checks"] = {
            "ignore endpoints": ["telegraf:prometheus-client"]
        }
        linter.check_spaces(self.check_spaces_example_bundle)
        errors = linter.output_collector["errors"]
        assert len(errors) == 0
        assert mock_log.call_count == 0

    def test_check_spaces_ignore_relations(self, linter, mocker):
        """Test that check spaces can ignore relations."""
        mock_log: mock.MagicMock = mocker.patch("jujulint.lint.Linter._log_with_header")
        linter.model.app_to_charm = self.check_spaces_example_app_charm_map

        # Run the space check with prometheus:target endpoint ignored.
        # This should neither generate an error nor a warning.
        linter.lint_rules["space checks"] = {
            "ignore relations": [["prometheus:target", "telegraf:prometheus-client"]]
        }
        linter.check_spaces(self.check_spaces_example_bundle)
        errors = linter.output_collector["errors"]
        assert len(errors) == 0
        assert mock_log.call_count == 0

        # Reverse the relation's definition order.
        # This should work the same way and also not generate errors/warnings.
        linter.lint_rules["space checks"] = {
            "ignore relations": [["telegraf:prometheus-client", "prometheus:target"]]
        }
        linter.check_spaces(self.check_spaces_example_bundle)
        errors = linter.output_collector["errors"]
        assert len(errors) == 0
        assert mock_log.call_count == 0

    def test_check_spaces_missing_explicit_bindings(self, linter, mocker):
        """Test that check_spaces shows warning if some application are missing bindings.

        This warning should be triggerred if some applications have bindings and some
        dont.
        """
        logger_mock = mocker.patch.object(spaces, "LOGGER")

        app_without_binding = "prometheus-app"
        bundle = {
            "applications": {
                app_without_binding: {},
                "telegraf-app": {
                    "bindings": {
                        "": "alpha",
                        "prometheus-client": "alpha",
                    },
                },
            },
            "relations": [
                ["telegraf-app:prometheus-client", "prometheus-app:target"],
            ],
        }

        expected_warning_callings = [
            mock.call("Application %s is missing explicit bindings", "prometheus-app"),
            mock.call("Setting default binding of '%s' to alpha", "prometheus-app"),
        ]

        linter.check_spaces(bundle)
        assert logger_mock.warning.call_args_list == expected_warning_callings

    def test_check_spaces_missing_default_endpoint_binding(self, linter, mocker):
        """Raise warning if application is missing explicit default binding.

        Aside from specifying binding for each endpoint explicitly, bundle can also
        specify default space (represented by empty string ""). Any endpoint that's not
        mentioned explicitly will be bound to this default space.
        Juju lint should raise warning if bundles do not define default space.
        """
        logger_mock = mocker.patch.object(spaces, "LOGGER")
        app_without_default_space = "telegraf-app"

        bundle = {
            "applications": {
                "prometheus-app": {
                    "bindings": {
                        "": "alpha",
                        "target": "alpha",
                    },
                },
                app_without_default_space: {
                    "bindings": {
                        "prometheus-client": "alpha",
                    },
                },
            },
            "relations": [
                ["telegraf-app:prometheus-client", "prometheus-app:target"],
            ],
        }

        expected_warning = "Application %s does not define explicit default binding"

        linter.check_spaces(bundle)

        logger_mock.warning.assert_called_once_with(
            expected_warning, app_without_default_space
        )

    def test_check_spaces_multi_model_warning(self, linter, mocker):
        """Test that check_spaces shows warning if some application are from another model."""
        logger_mock = mocker.patch.object(spaces, "LOGGER")

        app_another_model = "prometheus-app"
        bundle = {
            "applications": {
                "telegraf-app": {
                    "bindings": {
                        "": "alpha",
                        "prometheus-client": "alpha",
                    },
                },
            },
            "relations": [
                ["telegraf-app:prometheus-client", "prometheus-app:target"],
            ],
        }

        expected_warning_callings = [
            mock.call(
                "Multi-model is not supported yet. Please check if '%s' is from another model",
                app_another_model,
            ),
        ]

        linter.check_spaces(bundle)
        assert logger_mock.warning.call_args_list == expected_warning_callings

    def test_check_spaces_exception_handling(self, linter, mocker):
        """Test exception handling during check_spaces() method."""
        logger_mock = mock.MagicMock()
        expected_traceback = "python traceback"
        expected_msg = (
            "Exception caught during space check; please check space "
            "by hand. {}".format(expected_traceback)
        )
        mocker.patch.object(linter, "_handle_space_mismatch", side_effect=RuntimeError)
        mocker.patch.object(
            lint.traceback, "format_exc", return_value=expected_traceback
        )
        linter.logger = logger_mock
        linter.model.app_to_charm = self.check_spaces_example_app_charm_map

        # Run the space check.
        # Based on the above bundle, we should have exactly one mismatch.
        linter.check_spaces(self.check_spaces_example_bundle)

        logger_mock.warn.assert_called_once_with(expected_msg)

    @pytest.mark.parametrize(
        "regex_error, check_value, actual_value",
        [
            (True, "same", "same"),
            (True, "same", "different"),
            (False, "same", "same"),
            (False, "same", "different"),
            (True, "", "foo"),
            (False, "", "foo"),
        ],
    )
    def test_helper_operator_check(
        self, regex_error, check_value, actual_value, mocker
    ):
        """Test comparing values using "helper_operator_check()" function."""
        if regex_error:
            mocker.patch.object(lint.re, "match", side_effect=lint.re.error(""))

        expected_result = check_value == actual_value

        result = lint.helper_operator_eq_check(check_value, actual_value)

        assert bool(result) == expected_result

    @pytest.mark.parametrize(
        "input_str, expected_int",
        [
            (1, 1),  # return non-strings unchanged
            ("not_number_1", "not_number_1"),  # return non-numbers unchanged
            ("not_number_g", "not_number_g"),  # invalid value with valid suffix
            ("2f", "2f"),  # unrecognized suffix returns value unchanged
            ("2k", 2000),  # convert kilo suffix with quotient 1000
            ("2K", 2048),  # convert Kilo suffix with quotient 1024
            ("2m", 2000000),  # convert mega suffix with quotient 1000
            ("2M", 2097152),  # convert Mega suffix with quotient 1024
            ("2g", 2000000000),  # convert giga suffix with quotient 1000
            ("2G", 2147483648),  # convert Giga suffix with quotient 1024
        ],
    )
    def test_linter_atoi(self, input_str, expected_int, linter):
        """Test conversion of string values (e.g. 2M (Megabytes)) to integers."""
        assert linter.atoi(input_str) == expected_int

    @pytest.mark.parametrize("input_file_type", ["juju-status", "juju-bundle"])
    def test_check_relations_no_rules(
        self, linter, input_files, mocker, input_file_type
    ):
        """Warn message if rule file doesn't pass relations to check."""
        mock_log = mocker.patch("jujulint.lint.Linter._log_with_header")
        linter.check_relations(input_files[input_file_type])
        mock_log.assert_called_with("No relation rules found. Skipping relation checks")

    @pytest.mark.parametrize("input_file_type", ["juju-status", "juju-bundle"])
    def test_check_relations(self, linter, input_files, mocker, input_file_type):
        """Ensure that check_relation pass."""
        mock_message_handler = mocker.patch("jujulint.lint.Linter.message_handler")
        linter.lint_rules["relations"] = [
            {"charm": "nrpe", "check": [["nrpe:juju-info", "ubuntu:juju-info"]]}
        ]
        linter.check_relations(input_files[input_file_type])
        mock_message_handler.assert_not_called()

    @pytest.mark.parametrize(
        "input_file_type",
        [
            "juju-status",
            "juju-bundle",
        ],
    )
    def test_check_relations_exception_handling(
        self, linter, mocker, input_file_type, input_files
    ):
        """Ensure that handle error if relation rules are in wrong format."""
        mock_log = mocker.patch("jujulint.lint.Linter._log_with_header")
        mock_message_handler = mocker.patch("jujulint.lint.Linter.message_handler")
        linter.lint_rules["relations"] = [
            {"charm": "ntp", "check": [["ntp", "ubuntu"]]}
        ]
        expected_msg = (
            "Relations rules has an unexpected format: not enough "
            "values to unpack (expected 2, got 1)"
        )
        expected_exception = relations.RelationError(expected_msg)

        linter.check_relations(input_files[input_file_type])
        mock_message_handler.assert_not_called()
        mock_log.assert_has_calls(
            [mocker.call(expected_exception.message, level=logging.ERROR)]
        )

    @pytest.mark.parametrize("input_file_type", ["juju-status", "juju-bundle"])
    def test_check_relations_missing_relations(
        self, linter, mocker, input_file_type, input_files
    ):
        """Ensure that check_relation handle missing relations."""
        mock_message_handler = mocker.patch("jujulint.lint.Linter.message_handler")
        # add a relation rule that doesn't happen in the model
        linter.lint_rules["relations"] = [
            {
                "charm": "nrpe",
                "check": [["nrpe-host:local-monitors", "ubuntu:certificates"]],
            }
        ]
        linter.check_relations(input_files[input_file_type])
        mock_message_handler.assert_called_with(
            {
                "id": "missing-relations",
                "tags": ["relation", "missing"],
                "message": "Endpoint '{}' is missing relations with: {}".format(
                    "nrpe:local-monitors", ["ubuntu"]
                ),
            }
        )

    @pytest.mark.parametrize("input_file_type", ["juju-status", "juju-bundle"])
    def test_check_relations_exist(self, linter, input_files, mocker, input_file_type):
        """Ensure that check_relation handle not exist error."""
        mock_message_handler = mocker.patch("jujulint.lint.Linter.message_handler")
        not_exist_relation = [
            "nrpe-host:nrpe-external-master",
            "elasticsearch:nrpe-external-master",
        ]
        # add a relation rule that happen in the model
        linter.lint_rules["relations"] = [
            {"charm": "nrpe", "not-exist": [not_exist_relation]}
        ]
        linter.check_relations(input_files[input_file_type])
        mock_message_handler.assert_called_with(
            {
                "id": "relation-exist",
                "tags": ["relation", "exist"],
                "message": "Relation(s) {} should not exist.".format(
                    not_exist_relation
                ),
            }
        )

    @pytest.mark.parametrize("input_file_type", ["juju-status", "juju-bundle"])
    def test_check_relations_missing_machine(
        self, linter, input_files, mocker, input_file_type
    ):
        """Ensure that check_relation handle missing machines when ubiquitous."""
        new_machines = {"3": {"series": "focal"}, "2": {"series": "bionic"}}
        input_file = input_files[input_file_type]
        # add two new machines
        input_file.machines_data.update(new_machines)
        # map file again
        input_file.map_file()
        mock_message_handler = mocker.patch("jujulint.lint.Linter.message_handler")
        linter.lint_rules["relations"] = [
            {
                "charm": "nrpe",
                "ubiquitous": True,
            }
        ]

        expected_missing_machines = ["2", "3"]
        linter.check_relations(input_file)
        mock_message_handler.assert_called_with(
            {
                "id": "missing-machine",
                "tags": ["missing", "machine"],
                "message": "Charm '{}' missing on machines: {}".format(
                    "nrpe",
                    expected_missing_machines,
                ),
            }
        )

    def test_path_mtu_for_ovs_ovn_rules(self, linter, rules_files):
        """Test that ovs and ovn rules set right value of path-mtu."""
        for rule in [rules_file for rules_file in rules_files if "fcb" in rules_file]:
            linter.filename = rule
            linter.read_rules()
            path_mtu = linter.lint_rules["openstack config"]["neutron-api"]["path-mtu"]
            if "ovs" in rule:
                assert path_mtu["gte"] == 1550
            else:
                assert path_mtu["gte"] == 1558

            assert path_mtu["log-level"] == "warning"
            assert path_mtu["custom-message"]

    @pytest.mark.parametrize(
        "message, log_level, error",
        [
            ({}, None, True),  # log wrong message_handler format as error message
            ({}, logging.INFO, True),  # log wrong message_handler format as error
            ({"message": "my message"}, None, True),  # log error message
            ({"message": "my message"}, logging.INFO, False),  # log info message
            ({"message": "my message"}, logging.DEBUG, False),  # log debug message
            ({"message": "my message"}, logging.WARNING, False),  # log warning message
            ({"message": "my message"}, logging.ERROR, True),  # log error message
        ],
    )
    def test_message_handler(self, linter, mocker, message, log_level, error):
        """Test message_handler method."""
        logger_mock = mocker.patch.object(linter, "_log_with_header")
        expected_message = message.get("message", "wrong message_handler format")
        if message and not error:
            linter.message_handler(message, log_level)
            logger_mock.assert_has_calls(
                [mocker.call(expected_message, level=log_level)]
            )
        else:
            linter.message_handler(message)
            logger_mock.assert_has_calls(
                [mocker.call(expected_message, level=logging.ERROR)]
            )

    @pytest.mark.parametrize(
        "input_file_type",
        ["juju-status-hyper-converged", "juju-bundle-parsed-hyper-converged"],
    )
    def test_check_hyper_converged(self, linter, input_files, mocker, input_file_type):
        """Test check_hyper_converged."""
        input_file = input_files[input_file_type]
        mock_message_handler = mocker.patch("jujulint.lint.Linter.message_handler")
        msg = (
            "Deployment has Masakari and the machine: '{}' "
            "has nova/osd and the lxd: '{}' with those services {}"
        )
        expected_output = [
            mocker.call(
                {
                    "id": "hyper-converged-masakari",
                    "tags": ["hyper-converged", "masakari"],
                    "message": msg.format(
                        "0",
                        "lxd:0",
                        ["ceilometer", "heat"],
                    ),
                },
                log_level=logging.WARNING,
            )
        ]
        if "juju-status" in input_file_type:
            expected_output = [
                mocker.call(
                    {
                        "id": "hyper-converged-masakari",
                        "tags": ["hyper-converged", "masakari"],
                        "message": msg.format(
                            "0",
                            "0/lxd/0",
                            ["ceilometer"],
                        ),
                    },
                    log_level=logging.WARNING,
                ),
                mocker.call(
                    {
                        "id": "hyper-converged-masakari",
                        "tags": ["hyper-converged", "masakari"],
                        "message": msg.format(
                            "0",
                            "0/lxd/1",
                            ["heat"],
                        ),
                    },
                    log_level=logging.WARNING,
                ),
            ]

        linter.check_hyper_converged(input_file)
        mock_message_handler.assert_has_calls(expected_output, any_order=True)
