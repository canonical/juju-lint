#!/usr/bin/env python3

# This file is part of juju-lint, a tool for validating that Juju
# deloyments meet configurable site policies.
#
# Copyright 2018-2020 Canonical Limited.
# License granted by Canonical Limited.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3, as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranties of
# MERCHANTABILITY, SATISFACTORY QUALITY, or FITNESS FOR A PARTICULAR
# PURPOSE.  See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
"""Lint operations and rule processing engine."""
import collections
import json
import logging
import os.path
import pprint
import re
import traceback
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import attr
import dateutil.parser
import yaml
from attr import attrib, attrs
from dateutil import relativedelta

import jujulint.checks.hyper_converged as hyper_converged
import jujulint.util as utils
from jujulint.checks.relations import RelationError, RelationsRulesBootStrap
from jujulint.checks.spaces import Relation, find_space_mismatches
from jujulint.logging import Logger
from jujulint.model_input import input_handler

VALID_CONFIG_CHECKS = ("isset", "eq", "neq", "gte", "search")
VALID_LOG_LEVEL = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}

# Generic named tuple to represent the binary config operators (eq, neq, gte)
ConfigOperator = collections.namedtuple(
    "ConfigOperator", "name repr check error_template"
)

# TODO:
#  - missing relations for mandatory subordinates
#  - info mode, e.g. num of machines, version (e.g. look at ceph), architecture


def helper_operator_eq_check(check_value, actual_value):
    """Perform the actual equality check for the eq/neq rules."""
    # An empty string regex matches any string. Therefore
    # we are handling the empty string as a special case for now
    # as a workaround.
    # The overloaded regex matching behavior will be removed in a
    # future version.
    #
    # See LP #1993735
    if check_value == "":
        return check_value == actual_value

    match = False
    try:
        match = re.match(re.compile(str(check_value)), str(actual_value))
    except re.error:
        match = check_value == actual_value

    return match


@attrs
class ModelInfo(object):
    """Represent information obtained from juju status data."""

    charms = attrib(default=attr.Factory(set))
    cmr_apps = attrib(default=attr.Factory(set))
    app_to_charm = attrib(default=attr.Factory(dict))
    charm_to_app = attrib(default=attr.Factory(dict))
    subs_on_machines = attrib(default=attr.Factory(dict))
    apps_on_machines = attrib(default=attr.Factory(dict))
    machines_to_az = attrib(default=attr.Factory(dict))

    # Output of our linting
    missing_subs = attrib(default=attr.Factory(dict))
    extraneous_subs = attrib(default=attr.Factory(dict))
    duelling_subs = attrib(default=attr.Factory(dict))
    az_unbalanced_apps = attrib(default=attr.Factory(dict))


class Linter:
    """Linter for a Juju model, instantiate a new class for each model."""

    MAX_UNIT_EXECUTION_SECONDS = 3600  # 1 hr

    def __init__(
        self,
        name,
        rules_files,
        controller_name="manual",
        model_name="manual",
        overrides=None,
        cloud_type=None,
        output_format="text",
    ):
        """Instantiate linter."""
        self.logger = Logger()
        self.lint_rules = {}
        self.model = ModelInfo()
        self.rules_files = rules_files
        self.overrides = overrides
        self.cloud_name = name
        self.cloud_type = cloud_type
        self.controller_name = controller_name
        self.model_name = model_name

        # output
        self.output_format = output_format
        self.output_collector = {
            "name": name,
            "controller": controller_name,
            "model": model_name,
            "rules": rules_files,
            "errors": [],
        }

        # collect errors only for non-text output (e.g. json)
        self.collect_errors = True if self.output_format != "text" else False
        self.logger.warn(
            "Regex autodetection feature of the eq operator is deprecated. "
            "It will only check for equality in the future. "
            "Please use the search operator for regex checks."
        )

    def read_rules(self):
        """Read and parse rules from YAML, optionally processing provided overrides."""
        for rules_file in self.rules_files:
            if utils.is_url(rules_file):
                try:
                    with urlopen(rules_file) as response:
                        raw_rules_txt = response.read().decode()
                except (HTTPError, URLError) as error:
                    self.logger.error(
                        "Failed to fetch url: {} reason: {}".format(
                            rules_file, error.reason
                        )
                    )
                    return False
                except TimeoutError:
                    self.logger.error(
                        "Failed to fetch url: {} reason: TimeoutError".format(
                            rules_file
                        )
                    )
                    return False
            elif os.path.isfile(rules_file):
                with open(rules_file, "r") as f:
                    raw_rules_txt = f.read()
            else:
                self.logger.error("Rules file {} does not exist.".format(rules_file))
                return False

            lint_rules = self._process_includes_in_rules(raw_rules_txt, rules_file)

            # Flatten all entries (to account for nesting due to YAML anchors (templating)
            lint_rules = {k: utils.flatten_list(v) for k, v in lint_rules.items()}

            # Update the current rules with the new ones
            self.lint_rules = utils.deep_update(self.lint_rules, lint_rules)

        self._log_with_header("Lint Rules: {}".format(pprint.pformat(self.lint_rules)))
        if self.overrides:
            for override in self.overrides.split("#"):
                (name, where) = override.split(":")
                self._log_with_header(
                    "Overriding {} with {}".format(name, where), level=logging.INFO
                )
                self.lint_rules["subordinates"][name] = dict(where=where)

        return True

    def process_subordinates(self, app_d, app_name):
        """Iterate over subordinates and run subordinate checks."""
        # If this is a subordinate we have nothing else to do ATM
        if "units" not in app_d:
            return
        for unit in app_d["units"]:
            if "subordinates" in app_d["units"][unit]:
                subordinates = app_d["units"][unit]["subordinates"].keys()
                subordinates = [i.split("/")[0] for i in subordinates]
            else:
                subordinates = []
            self._log_with_header("{}: {}".format(unit, subordinates))
            machine = app_d["units"][unit]["machine"]
            self.model.subs_on_machines.setdefault(machine, set())
            for sub in subordinates:
                if sub in self.model.subs_on_machines[machine]:
                    charm = self.model.app_to_charm[sub]
                    allow_multiple = self.lint_rules["subordinates"][charm].get(
                        "allow-multiple"
                    )
                    if not allow_multiple:
                        self.model.duelling_subs.setdefault(sub, set())
                        self.model.duelling_subs[sub].add(machine)
                self.model.subs_on_machines[machine].add(sub)
            self.model.subs_on_machines[machine] = (
                set(subordinates) | self.model.subs_on_machines[machine]
            )
            self.model.apps_on_machines.setdefault(machine, set())
            self.model.apps_on_machines[machine].add(app_name)

        return

    @staticmethod
    def atoi(val):
        """Deal with complex number representations as strings.

        This method attempts to convert string containing number and a
        supported suffix (k,m,g,K,M,G) into a int with appropriate value.
        e.g.: "2k" -> 2000
              "2K" -> 2048

        If the input value does not match the expected format, it is returned
        without the change.
        """
        if type(val) != str:
            return val

        try:
            _int = int(val[0:-1])
        except Exception:
            return val

        suffix = val[-1]
        quotient = 1024
        if suffix.islower():
            quotient = 1000

        conv = {"g": quotient**3, "m": quotient**2, "k": quotient}

        if suffix.lower() not in conv:
            return val

        return _int * conv[suffix.lower()]

    def isset(
        self,
        name,
        check_value,
        rule,
        config,
        log_level=logging.ERROR,
        custom_message="",
    ):
        """Check if value is set per rule constraints."""
        if rule in config:
            if check_value is True:
                self._log_with_header(
                    "(PASS) Application {} correctly has config for '{}': {}.".format(
                        name,
                        rule,
                        config[rule],
                    )
                )
                return True
            actual_value = config[rule]
            self.message_handler(
                {
                    "id": "config-isset-check-false",
                    "tags": ["config", "isset"],
                    "description": "Checks for config condition 'isset'",
                    "application": name,
                    "rule": rule,
                    "actual_value": actual_value,
                    "message": custom_message
                    or "Application {} has config for {}: {}.".format(
                        name, rule, actual_value
                    ),
                },
                log_level=log_level,
            )
            return False
        elif check_value is False:
            self._log_with_header(
                "(PASS) Application {} correctly had no config for '{}'.".format(
                    name,
                    rule,
                )
            )
            return True
        self.message_handler(
            {
                "id": "config-isset-check-true",
                "tags": ["config", "isset"],
                "description": "Checks for config condition 'isset' true",
                "application": name,
                "rule": rule,
                "message": custom_message
                or "Application {} has no config for {}.".format(name, rule),
            },
            log_level=log_level,
        )
        return False

    def eq(
        self,
        app_name,
        check_value,
        config_key,
        app_config,
        log_level=logging.ERROR,
        custom_message="",
    ):
        """Check if value matches the provided value or regex, autodetecting regex."""
        operator = ConfigOperator(
            name="eq",
            repr="==",
            check=helper_operator_eq_check,
            error_template="Application {} has incorrect setting for '{}': Expected {}, got {}",
        )

        return self.check_config_generic(
            operator,
            app_name,
            check_value,
            config_key,
            app_config,
            log_level,
            custom_message,
        )

    def neq(
        self,
        app_name,
        check_value,
        config_key,
        app_config,
        log_level=logging.ERROR,
        custom_message="",
    ):
        """Check if value does not match a the config."""
        operator = ConfigOperator(
            name="neq",
            repr="!=",
            check=lambda check_value, actual_value: check_value != actual_value,
            error_template="Application {} has incorrect setting for '{}': Should not be {}",
        )

        return self.check_config_generic(
            operator,
            app_name,
            check_value,
            config_key,
            app_config,
            log_level,
            custom_message,
        )

    def gte(
        self,
        app_name,
        check_value,
        config_key,
        app_config,
        log_level=logging.ERROR,
        custom_message="",
    ):
        """Check if value is greater than or equal to the check value."""

        def operator_gte_check(check_value, actual_value):
            """Perform the actual gte check."""
            current = self.atoi(actual_value)
            expected = self.atoi(check_value)
            return current >= expected

        operator = ConfigOperator(
            name="gte",
            repr=">=",
            check=operator_gte_check,
            error_template="Application {} has config for '{}' which is less than {}: {}",
        )

        return self.check_config_generic(
            operator,
            app_name,
            check_value,
            config_key,
            app_config,
            log_level,
            custom_message,
        )

    def search(
        self,
        app_name,
        check_value,
        config_key,
        app_config,
        log_level=logging.ERROR,
        custom_message="",
    ):
        """Scan through the charm config looking for a match using the regex pattern."""
        if config_key in app_config:
            actual_value = app_config.get(config_key)
            if re.search(str(check_value), str(actual_value)):
                self._log_with_header(
                    "Application {} has a valid config for '{}': regex {} found at {}".format(
                        app_name,
                        config_key,
                        repr(check_value),
                        repr(actual_value),
                    )
                )
                return True
            self.message_handler(
                {
                    "id": "config-search-check",
                    "tags": ["config", "search"],
                    "description": "Checks for config condition 'search'",
                    "application": app_name,
                    "rule": config_key,
                    "expected_value": check_value,
                    "actual_value": actual_value,
                    "message": custom_message
                    or "Application {} has an invalid config for '{}': regex {} not found at {}".format(
                        app_name,
                        config_key,
                        repr(check_value),
                        repr(actual_value),
                    ),
                },
                log_level=log_level,
            )
            return False

        self._log_with_header(
            "Application {} has no config for '{}', can't search the regex pattern {}.".format(
                app_name,
                config_key,
                repr(check_value),
            ),
            level=logging.WARN,
        )
        return False

    def check_config_generic(
        self,
        operator,
        app_name,
        check_value,
        config_key,
        app_config,
        log_level=logging.ERROR,
        custom_message="",
    ):
        """Apply the provided config operator to the configuration."""
        # First check if the config key is present
        if config_key not in app_config:
            self._log_with_header(
                "Application {} has no config for '{}', cannot determine if {} {}.".format(
                    app_name,
                    config_key,
                    operator.repr,
                    repr(check_value),
                ),
                level=logging.WARN,
            )
            return False

        actual_value = app_config[config_key]

        # Apply the check callable and handle the possible cases
        if operator.check(check_value, actual_value):
            self._log_with_header(
                "Application {} has a valid config for '{}': {} ({} {})".format(
                    app_name,
                    config_key,
                    repr(check_value),
                    operator.repr,
                    repr(actual_value),
                )
            )
            return True
        else:
            self.message_handler(
                {
                    "id": "config-{}-check".format(operator.name),
                    "tags": ["config", operator.name],
                    "description": "Checks for config condition '{}'".format(
                        operator.name
                    ),
                    "application": app_name,
                    "rule": config_key,
                    "expected_value": check_value,
                    "actual_value": actual_value,
                    "message": custom_message
                    or operator.error_template.format(
                        app_name,
                        config_key,
                        repr(check_value),
                        repr(actual_value),
                    ),
                },
                log_level=log_level,
            )
        return False

    def check_config(self, app_name, config, rules):
        """Check application against provided rules."""
        rules = dict(rules)
        for rule in rules:
            self._log_with_header(
                "Checking {} for configuration {}".format(app_name, rule)
            )

            # Handle app suffix for config checks. If the suffix is provided
            # and it does not match, then we skip the check. LP#1944406
            # The base charm name is always checked if present.
            suffixes = rules[rule].pop("suffixes", [])
            if suffixes:
                charm_name = self.model.app_to_charm[app_name]
                target_app_names = [
                    "{}-{}".format(charm_name, suffix) for suffix in suffixes
                ]
                target_app_names.append(charm_name)

                if app_name not in target_app_names:
                    self._log_with_header(
                        "The app name didn't match any name target for this charm: '{}' (skipping check)".format(
                            app_name
                        )
                    )
                    continue

            custom_message = rules[rule].pop("custom-message", "")
            log_level = rules[rule].pop("log-level", "error").lower()

            for check_op, check_value in rules[rule].items():
                # check_op should be the operator name, e.g. (eq, neq, gte, isset)
                if check_op in VALID_CONFIG_CHECKS:
                    check_method = getattr(self, check_op)
                    check_method(
                        app_name,
                        check_value,
                        rule,
                        config,
                        VALID_LOG_LEVEL.get(log_level, logging.ERROR),
                        custom_message,
                    )
                else:
                    self._log_with_header(
                        "Application {} has unknown check operation for {}: {}.".format(
                            app_name,
                            rule,
                            check_op,
                        ),
                        level=logging.WARN,
                    )

    def check_configuration(self, applications):
        """Check application configs in the model."""
        for application in applications.keys():
            # look for config rules for this application
            lint_rules = []
            if "charm" not in applications[application]:
                self._log_with_header(
                    "Application {} has no charm.".format(
                        application,
                    ),
                    level=logging.WARN,
                )
                continue

            charm_name = utils.extract_charm_name(applications[application]["charm"])
            if "config" in self.lint_rules:
                if charm_name in self.lint_rules["config"]:
                    lint_rules = self.lint_rules["config"][charm_name].items()

            if self.cloud_type == "openstack":
                # process openstack config rules
                if "openstack config" in self.lint_rules:  # pragma: no cover
                    if charm_name in self.lint_rules["openstack config"]:
                        lint_rules.extend(
                            self.lint_rules["openstack config"][charm_name].items()
                        )

            if lint_rules:
                if "options" in applications[application]:
                    self.check_config(
                        application,
                        applications[application]["options"],
                        lint_rules,
                    )

    def check_subs(self, machines_data):  # pragma: no cover
        """Check the subordinates in the model."""
        all_or_nothing = set()
        for machine in self.model.subs_on_machines:
            for sub in self.model.subs_on_machines[machine]:
                all_or_nothing.add(sub)

        for required_sub in self.lint_rules["subordinates"]:
            self.model.missing_subs.setdefault(required_sub, set())
            self.model.extraneous_subs.setdefault(required_sub, set())
            self._log_with_header("Checking for sub {}".format(required_sub))
            where = self.lint_rules["subordinates"][required_sub]["where"]
            for machine in self.model.subs_on_machines:
                self._log_with_header("Checking on {}".format(machine))
                present_subs = self.model.subs_on_machines[machine]
                apps = self.model.apps_on_machines[machine]
                if where.startswith("on "):  # only on specific apps
                    required_on = where[3:]
                    self._log_with_header(
                        "Requirement {} is = from...".format(required_on)
                    )
                    if required_on not in apps:
                        self._log_with_header("... NOT matched")
                        continue
                    self._log_with_header("... matched")
                # TODO this needs to be not just one app, but a list
                elif where.startswith("all except "):  # not next to this app
                    self._log_with_header("requirement is != form...")
                    not_on = where[11:]
                    if not_on in apps:
                        self._log_with_header("... matched, not wanted on this host")
                        continue
                elif where == "host only":
                    self._log_with_header("requirement is 'host only' form....")
                    if utils.is_container(machine):
                        self._log_with_header("... and we are a container, checking")
                        # XXX check alternate names?
                        if required_sub in present_subs:
                            self._log_with_header("... found extraneous sub")
                            for app in self.model.apps_on_machines[machine]:
                                self.model.extraneous_subs[required_sub].add(app)
                        continue
                    self._log_with_header("... and we are a host, will fallthrough")
                elif where == "metal only":
                    self._log_with_header("requirement is 'metal only' form....")
                    if not utils.is_metal(machine, machines_data.get(machine, {})):
                        self._log_with_header("... and we are not a metal, checking")
                        if required_sub in present_subs:
                            self._log_with_header("... found extraneous sub")
                            for app in self.model.apps_on_machines[machine]:
                                self.model.extraneous_subs[required_sub].add(app)
                        continue
                    self._log_with_header("... and we are a metal, will fallthrough")

                elif where == "all or nothing" and required_sub not in all_or_nothing:
                    self._log_with_header(
                        "requirement is 'all or nothing' and was 'nothing'."
                    )
                    continue
                # At this point we know we require the subordinate - we might just
                # need to change the name we expect to see it as
                elif where == "container aware":
                    self._log_with_header("requirement is 'container aware'.")
                    if utils.is_container(machine):
                        suffixes = self.lint_rules["subordinates"][required_sub][
                            "container-suffixes"
                        ]
                    else:
                        suffixes = self.lint_rules["subordinates"][required_sub][
                            "host-suffixes"
                        ]
                    self._log_with_header("-> suffixes == {}".format(suffixes))
                    exceptions = []
                    if "exceptions" in self.lint_rules["subordinates"][required_sub]:
                        exceptions = self.lint_rules["subordinates"][required_sub][
                            "exceptions"
                        ]
                        self._log_with_header("-> exceptions == {}".format(exceptions))
                    found = False
                    for suffix in suffixes:
                        looking_for = "{}-{}".format(required_sub, suffix)
                        self._log_with_header("-> Looking for {}".format(looking_for))
                        if looking_for in present_subs:
                            self._log_with_header("-> FOUND!!!")
                            found = True
                    if not found:
                        for sub in present_subs:
                            if self.model.app_to_charm[sub] == required_sub:
                                self._log_with_header(
                                    "Winner winner, chicken dinner! 🍗 {}".format(sub)
                                )
                                found = True
                    if not found:
                        for exception in exceptions:
                            if exception in apps:
                                self._log_with_header(
                                    "continuing as found exception: {}".format(
                                        exception
                                    )
                                )
                                found = True
                    if not found:
                        self._log_with_header("-> NOT FOUND")
                        for app in self.model.apps_on_machines[machine]:
                            self.model.missing_subs[required_sub].add(app)
                    self._log_with_header("-> continue-ing back out...")
                    continue
                elif where not in ["all", "all or nothing"]:
                    self.logger.fubar(
                        "[{}] [{}/{}] Invalid requirement '{}' on {}".format(
                            self.cloud_name,
                            self.controller_name,
                            self.model_name,
                            where,
                            required_sub,
                        )
                    )
                self._log_with_header("requirement is 'all' OR we fell through.")
                if required_sub not in present_subs:
                    for sub in present_subs:
                        if self.model.app_to_charm[sub] == required_sub:
                            self._log_with_header(
                                "Winner winner, chicken dinner! 🍗 {}".format(sub)
                            )
                            continue
                    self._log_with_header("not found.")
                    for app in self.model.apps_on_machines[machine]:
                        self.model.missing_subs[required_sub].add(app)

        for sub in list(self.model.missing_subs.keys()):
            if not self.model.missing_subs[sub]:
                del self.model.missing_subs[sub]
        for sub in list(self.model.extraneous_subs.keys()):
            if not self.model.extraneous_subs[sub]:
                del self.model.extraneous_subs[sub]

    def check_relations(self, input_file):
        """Check the relations in the rules file.

        :param input_file: mapped content of the input file.
        :type input_file: Union[JujuBundleFile, JujuStatusFile]
        """
        if "relations" not in self.lint_rules:
            self._log_with_header("No relation rules found. Skipping relation checks")
            return
        try:
            relations_rules = RelationsRulesBootStrap(
                relations_rules=self.lint_rules["relations"],
                input_file=input_file,
            ).check()
        except RelationError as e:
            relations_rules = []
            self._log_with_header(e.message, level=logging.ERROR)

        for rule in relations_rules:
            for endpoint, applications in rule.missing_relations.items():
                if applications:
                    self.message_handler(
                        {
                            "id": "missing-relations",
                            "tags": ["relation", "missing"],
                            "message": "Endpoint '{}' is missing relations with: {}".format(
                                endpoint, applications
                            ),
                        }
                    )
            if rule.not_exist_error:
                for relation in rule.not_exist_error:
                    self.message_handler(
                        {
                            "id": "relation-exist",
                            "tags": ["relation", "exist"],
                            "message": "Relation(s) {} should not exist.".format(
                                relation
                            ),
                        }
                    )

            if rule.missing_machines:
                self.message_handler(
                    {
                        "id": "missing-machine",
                        "tags": ["missing", "machine"],
                        "message": "Charm '{}' missing on machines: {}".format(
                            rule.charm,
                            rule.missing_machines,
                        ),
                    }
                )

    def check_hyper_converged(self, input_file):
        """Check hyper converged deployments.

        :param input_file: mapped content of the input file.
        :type input_file: Union[JujuBundleFile, JujuStatusFile]
        """
        hyper_converged_warning = hyper_converged.check_hyper_converged(input_file)

        if hyper_converged_warning:
            for machine in hyper_converged_warning:
                for lxd in hyper_converged_warning[machine]:
                    self.message_handler(
                        {
                            "id": "hyper-converged-masakari",
                            "tags": ["hyper-converged", "masakari"],
                            "message": (
                                "Deployment has Masakari and the machine: '{}' "
                                "has nova/osd and the lxd: '{}' with those services {}"
                            ).format(
                                machine,
                                lxd,
                                sorted(list(hyper_converged_warning[machine][lxd])),
                            ),
                        },
                        log_level=logging.WARNING,
                    )

    def check_charms_ops_mandatory(self, charm):
        """
        Check if a mandatory ops charms is present in the model.

        First check if the charm is installed in the model, if not
        then check the CMRs. If no errors, returns None
        """
        if charm in self.model.charms:
            return None

        rules_saas = self.lint_rules.get("saas", {})
        for cmr_app in self.model.cmr_apps:
            # the remote might not be called exactly as the charm, e.g. prometheus
            # or prometheus2, so we naively check the beginning for a start.
            if charm in rules_saas and charm.startswith(cmr_app):
                return None

        return {
            "id": "ops-charm-missing",
            "tags": ["missing", "ops", "charm", "mandatory", "principal"],
            "description": "An Ops charm is missing",
            "charm": charm,
            "message": "Ops charm '{}' is missing".format(charm),
        }

    def check_charms(self):
        """Check we recognise the charms which are in the model."""
        for charm in self.model.charms:
            if charm not in self.lint_rules["known charms"]:
                self.message_handler(
                    {
                        "id": "unrecognised-charm",
                        "tags": ["charm", "unrecognised"],
                        "description": "An unrecognised charm is present in the model",
                        "charm": charm,
                        "message": "Charm '{}' not recognised".format(charm),
                    }
                )
        # Then look for charms we require
        for charm in self.lint_rules["operations mandatory"]:
            error = self.check_charms_ops_mandatory(charm)
            if error:
                self.message_handler(error)
        if self.cloud_type == "openstack":
            for charm in self.lint_rules["openstack mandatory"]:
                if charm not in self.model.charms:
                    self.message_handler(
                        {
                            "id": "openstack-charm-missing",
                            "tags": [
                                "missing",
                                "openstack",
                                "charm",
                                "mandatory",
                                "principal",
                            ],
                            "description": "An Openstack charm is missing",
                            "charm": charm,
                            "message": "Openstack charm '{}' is missing".format(charm),
                        }
                    )
            for charm in self.lint_rules["operations openstack mandatory"]:
                if charm not in self.model.charms:
                    self.message_handler(
                        {
                            "id": "openstack-ops-charm-missing",
                            "tags": [
                                "missing",
                                "openstack",
                                "ops",
                                "charm",
                                "mandatory",
                                "principal",
                            ],
                            "description": "An Openstack ops charm is missing",
                            "charm": charm,
                            "message": "Openstack ops charm '{}' is missing".format(
                                charm
                            ),
                        }
                    )
        elif self.cloud_type == "kubernetes":
            for charm in self.lint_rules["kubernetes mandatory"]:
                if charm not in self.model.charms:
                    self.message_handler(
                        {
                            "id": "kubernetes-charm-missing",
                            "tags": [
                                "missing",
                                "kubernetes",
                                "charm",
                                "mandatory",
                                "principal",
                            ],
                            "description": "An Kubernetes charm is missing",
                            "charm": charm,
                            "message": "Kubernetes charm '{}' is missing".format(charm),
                        }
                    )
            for charm in self.lint_rules["operations kubernetes mandatory"]:
                if charm not in self.model.charms:
                    self.message_handler(
                        {
                            "id": "kubernetes-ops-charm-missing",
                            "tags": [
                                "missing",
                                "openstack",
                                "ops",
                                "charm",
                                "mandatory",
                                "principal",
                            ],
                            "description": "An Kubernetes ops charm is missing",
                            "charm": charm,
                            "message": "Kubernetes ops charm '{}' is missing".format(
                                charm
                            ),
                        }
                    )

    def check_cloud_type(self, deployment_charms):
        """Check cloud_type or detect depending on the deployed charms.

        :param deployment_charms: charms present in the bundle and/or status.
        :type deployment_charms: Set
        """
        typical_cloud_charms = {
            "openstack": {
                "keystone",
                "nova-compute",
                "nova-cloud-controller",
                "glance",
                "openstack-dashboard",
                "neutron-api",
            },
            "kubernetes": {
                "kubernetes-worker",
                "kubernetes-control-plane",
                "containerd",
                "calico",
                "canal",
                "etcd",
            },
        }
        if self.cloud_type:
            if self.cloud_type not in typical_cloud_charms.keys():
                self._log_with_header(
                    "Cloud type {} is unknown".format(self.cloud_type),
                    level=logging.WARN,
                )
            return

        for cloud_type, charms in typical_cloud_charms.items():
            match = deployment_charms.intersection(charms)
            if len(match) >= 2:
                self._log_with_header(
                    (
                        "Setting cloud-type to '{}'. "
                        "Deployment has these charms: {} that are typically from {}."
                    ).format(cloud_type, match, cloud_type),
                    level=logging.WARN,
                )
                self.cloud_type = cloud_type
                return

    def check_spaces(self, parsed_yaml):
        """Check that relations end with the same endpoint."""
        space_checks = self.lint_rules.get("space checks", {})
        enforce_endpoints = space_checks.get("enforce endpoints", [])
        enforce_relations = [
            Relation(*relation)
            for relation in space_checks.get("enforce relations", [])
        ]
        ignore_endpoints = space_checks.get("ignore endpoints", [])
        ignore_relations = [
            Relation(*relation) for relation in space_checks.get("ignore relations", [])
        ]

        mismatches = find_space_mismatches(parsed_yaml)
        for mismatch in mismatches:
            try:
                self._handle_space_mismatch(
                    mismatch,
                    enforce_endpoints,
                    enforce_relations,
                    ignore_endpoints,
                    ignore_relations,
                )
            except Exception:
                # FOR NOW: super quick and dirty
                self.logger.warn(
                    "Exception caught during space check; please check space by hand. {}".format(
                        traceback.format_exc()
                    )
                )

    def _handle_space_mismatch(
        self,
        mismatch,
        enforce_endpoints,
        enforce_relations,
        ignore_endpoints,
        ignore_relations,
    ):
        # By default: treat mismatches as warnings.
        # If we have a matching enforcement rule, treat as an error.
        # If we have a matching ignore rule, do not warn.
        # (Enforcement rules win over ignore rules.)
        error = False
        warning = True
        mismatch_relation = mismatch.get_charm_relation(self.model.app_to_charm)

        for enforce_endpoint in enforce_endpoints:
            if enforce_endpoint in mismatch_relation.endpoints:
                error = True
        for ignore_endpoint in ignore_endpoints:
            if ignore_endpoint in mismatch_relation.endpoints:
                warning = False
        for enforce_relation in enforce_relations:
            if enforce_relation == mismatch_relation:
                error = True
        for ignore_relation in ignore_relations:
            if ignore_relation == mismatch_relation:
                warning = False

        message = "Space binding mismatch: {}".format(mismatch)
        if error:
            self.message_handler(
                {
                    "id": "space-binding-mismatch",
                    "tags": ["mismatch", "space", "binding"],
                    "description": "Unhandled space binding mismatch",
                    "message": message,
                }
            )
        elif warning:
            # DEFAULT: not a critical error, so just warn
            self._log_with_header(message, level=logging.WARN)

    def results(self):
        """Provide results of the linting process."""
        if self.model.missing_subs:
            for sub in self.model.missing_subs:
                principals = ", ".join(sorted(self.model.missing_subs[sub]))
                self.message_handler(
                    {
                        "id": "ops-subordinate-missing",
                        "tags": ["missing", "ops", "charm", "mandatory", "subordinate"],
                        "description": "Checks for mandatory Ops subordinates",
                        "principals": principals,
                        "subordinate": sub,
                        "message": "Subordinate '{}' is missing for application(s): '{}'".format(
                            sub, principals
                        ),
                    }
                )

        if self.model.extraneous_subs:
            for sub in self.model.extraneous_subs:
                principals = ", ".join(sorted(self.model.extraneous_subs[sub]))
                self.message_handler(
                    {
                        "id": "subordinate-extraneous",
                        "tags": ["extraneous", "charm", "subordinate"],
                        "description": "Checks for extraneous subordinates in containers",
                        "principals": principals,
                        "subordinate": sub,
                        "message": "Application(s) '{}' has extraneous subordinate '{}'".format(
                            principals, sub
                        ),
                    }
                )
        if self.model.duelling_subs:
            for sub in self.model.duelling_subs:
                machines = ", ".join(sorted(self.model.duelling_subs[sub]))
                self.message_handler(
                    {
                        "id": "subordinate-duplicate",
                        "tags": ["duplicate", "charm", "subordinate"],
                        "description": "Checks for duplicate subordinates in a machine",
                        "machines": machines,
                        "subordinate": sub,
                        "message": "Subordinate '{}' is duplicated on machines: '{}'".format(
                            sub,
                            machines,
                        ),
                    }
                )
        if self.model.az_unbalanced_apps:
            for app in self.model.az_unbalanced_apps:
                (num_units, az_counter) = self.model.az_unbalanced_apps[app]
                az_map = ", ".join(
                    ["{}: {}".format(az, az_counter[az]) for az in sorted(az_counter)]
                )
                self.message_handler(
                    {
                        "id": "AZ-unbalance",
                        "tags": ["AZ"],
                        "description": "Checks for application balance across AZs",
                        "application": app,
                        "num_units": num_units,
                        "az_map": az_map,
                        "message": "Application '{}' is unbalanced across AZs: {} units, deployed as: {}".format(
                            app, num_units, az_map
                        ),
                    }
                )
        if self.output_format == "json":
            print(json.dumps(self.output_collector, indent=2, sort_keys=True))

    def map_charms(self, applications):
        """Process applications in the model, validating and normalising the names."""
        for app in applications:
            if "charm" in applications[app]:
                charm_name = utils.extract_charm_name(applications[app]["charm"])
                self.model.charms.add(charm_name)
                self.model.app_to_charm[app] = charm_name
                self.model.charm_to_app.setdefault(charm_name, set()).add(app)
            else:
                self.message_handler(
                    {
                        "id": "charm-not-mapped",
                        "tags": ["charm", "mapped", "parsing"],
                        "description": "Detect the charm used by an application",
                        "application": app,
                        "message": "Could not detect which charm is used for application {}".format(
                            app
                        ),
                    }
                )

    def parse_cmr_apps(self, parsed_yaml):
        """Parse the apps from cross-model relations."""
        cmr_keys = (
            "saas",  # Pattern used by juju export-bundle
            "application-endpoints",  # Pattern used by jsfy
            "remote-applications",  # Pattern used by libjuju (charm-lint-juju)
        )

        for key in cmr_keys:
            if key in parsed_yaml:
                for name in parsed_yaml[key]:
                    self.model.cmr_apps.add(name)

                    # Handle the special case of dependencies for graylog
                    if name.startswith("graylog"):
                        self.model.cmr_apps.add("elasticsearch")
                return

    def map_machines_to_az(self, machines):
        """Map machines in the model to their availability zone."""
        for machine in machines:
            if "hardware" not in machines[machine]:
                self._log_with_header(
                    "Machine {} has no hardware info; skipping.".format(machine),
                    level=logging.WARN,
                )
                continue

            hardware = machines[machine]["hardware"]
            found_az = False
            for entry in hardware.split():
                if entry.startswith("availability-zone="):
                    found_az = True
                    az = entry.split("=")[1]
                    self.model.machines_to_az[machine] = az
                    break
            if not found_az:
                self._log_with_header(
                    "Machine {} has no availability-zone info in hardware field; skipping.".format(
                        machine
                    ),
                    level=logging.WARN,
                )

    def check_status(self, what, status, expected):
        """Lint the status of a unit."""
        current_status = status.get("current")
        if isinstance(expected, str):
            expected = [expected]

        if current_status not in expected:
            status_since = status.get("since")

            since_datetime = dateutil.parser.parse(status_since)
            ref_datetime = datetime.now(timezone.utc) - relativedelta.relativedelta(
                seconds=self.MAX_UNIT_EXECUTION_SECONDS
            )
            if current_status == "executing" and since_datetime > ref_datetime:
                return

            status_msg = status.get("message")
            self.message_handler(
                {
                    "id": "status-unexpected",
                    "tags": ["status"],
                    "description": "Checks for unexpected status in juju and workload",
                    "what": what,
                    "status_current": current_status,
                    "status_since": status_since,
                    "status_msg": status_msg,
                    "message": "{} has status '{}' (since: {}, message: {}); (We expected: {})".format(
                        what, current_status, status_since, status_msg, expected
                    ),
                }
            )

    def check_status_pair(self, name, status_type, data_d):
        """Cross reference satus of paired constructs, like machines and units."""
        if status_type in ["machine", "container"]:
            primary = "machine-status"
            primary_expected = "running"
            juju_expected = "started"
        elif status_type in ["unit", "subordinate"]:
            primary = "workload-status"
            primary_expected = ["active", "unknown"]
            juju_expected = "idle"
        elif status_type in ["application"]:
            primary = "application-status"
            primary_expected = ["active", "unknown"]
            juju_expected = None

        if primary in data_d:
            self.check_status(
                "{} {}".format(status_type.title(), name),
                data_d[primary],
                expected=primary_expected,
            )
            if juju_expected:
                if "juju-status" in data_d:
                    self.check_status(
                        "Juju on {} {}".format(status_type, name),
                        data_d["juju-status"],
                        expected=juju_expected,
                    )
                else:  # pragma: no cover
                    self._log_with_header(
                        "Could not determine Juju status for {}.".format(name),
                        level=logging.WARN,
                    )
        else:
            self._log_with_header(
                "Could not determine appropriate status key for {}.".format(
                    name,
                ),
                level=logging.WARN,
            )

    def check_statuses(self, juju_status, applications):
        """Check all statuses in juju status output."""
        for machine_name in juju_status["machines"]:
            self.check_status_pair(
                machine_name, "machine", juju_status["machines"][machine_name]
            )
            for container_name in juju_status["machines"][machine_name].get(
                "container", []
            ):  # pragma: no cover
                self.check_status_pair(
                    container_name,
                    "container",
                    juju_status["machines"][machine_name][container_name],
                )

        for app_name in juju_status[applications]:
            self.check_status_pair(
                app_name, "application", juju_status[applications][app_name]
            )
            for unit_name in juju_status[applications][app_name].get("units", []):
                self.check_status_pair(
                    unit_name,
                    "unit",
                    juju_status[applications][app_name]["units"][unit_name],
                )

    # This is noisy and only covers a very theoretical corner case
    # where a misbehaving or malicious leader unit sets the
    # application-status to OK despite one or more units being in error
    # state.
    #
    # We could revisit this later by splitting it into two passes and
    # only warning about individual subordinate units if the
    # application-status for the subordinate claims to be OK.
    #
    # for subordinate_name in juju_status[applications][app_name]["units"][unit_name].get("subordinates", []):
    #     check_status_pair(subordinate_name, "subordinate",
    #                       juju_status[applications][app_name]["units"][unit_name]["subordinates"][subordinate_name])

    def check_azs(self, applications):
        """Lint AZ distribution."""
        azs = set()
        for machine in self.model.machines_to_az:
            azs.add(self.model.machines_to_az[machine])
        num_azs = len(azs)
        if num_azs != 3:
            self.message_handler(
                {
                    "id": "AZ-invalid-number",
                    "tags": ["AZ"],
                    "description": "Checks for a valid number or AZs (currently 3)",
                    "num_azs": num_azs,
                    "message": "Invalid number of AZs: '{}', expecting 3".format(
                        num_azs
                    ),
                }
            )
            return

        for app_name in applications:
            az_counter = collections.Counter()
            for az in azs:
                az_counter[az] = 0
            num_units = len(applications[app_name].get("units", []))
            if num_units <= 1:
                continue
            min_per_az = num_units // num_azs
            for unit in applications[app_name]["units"]:
                machine = applications[app_name]["units"][unit]["machine"]
                machine = machine.split("/")[0]
                if machine not in self.model.machines_to_az:  # pragma: no cover
                    self._log_with_header(
                        "{}: Can't find machine {} in machine to AZ mapping data".format(
                            app_name,
                            machine,
                        ),
                        level=logging.ERROR,
                    )
                    continue
                az_counter[self.model.machines_to_az[machine]] += 1
            for az in az_counter:
                num_this_az = az_counter[az]
                if num_this_az < min_per_az:
                    self.model.az_unbalanced_apps[app_name] = [num_units, az_counter]

    # Juju now creates multiple documents within a single export-bundle file
    #   This is to support offer overlays
    #   This occurs with the format string "--- # overlay.yaml"
    def get_main_bundle_doc(self, parsed_yaml_docs):
        """Get main bundle document from yaml input that may contain mutiple documents."""
        parsed_yaml = None

        parsed_doc_list = list(parsed_yaml_docs)
        for doc in parsed_doc_list:
            offer_overlay = False
            applications = doc["applications"]
            for app in applications:
                if "offers" in doc["applications"][app]:
                    offer_overlay = True
            if parsed_yaml is None or not offer_overlay:
                parsed_yaml = doc
        return parsed_yaml

    def lint_yaml_string(self, yaml_string):
        """Lint provided YAML string."""
        parsed_yaml_docs = yaml.safe_load_all(yaml_string)
        parsed_yaml = self.get_main_bundle_doc(parsed_yaml_docs)
        return self.do_lint(parsed_yaml)

    def lint_yaml_file(self, filename):
        """Load and lint provided YAML file."""
        if filename:
            with open(filename, "r") as infile:
                parsed_yaml_docs = yaml.safe_load_all(infile.read())
                parsed_yaml = self.get_main_bundle_doc(parsed_yaml_docs)
                if parsed_yaml:
                    return self.do_lint(parsed_yaml)
        self.logger.fubar(
            "Failed to parse YAML from file {}".format(filename)
        )  # pragma: no cover

    def do_lint(self, parsed_yaml):  # pragma: no cover
        """Lint parsed YAML."""
        # Handle Juju 2 vs Juju 1
        applications = "applications" if "applications" in parsed_yaml else "services"
        input_file = input_handler(parsed_yaml, applications)

        if applications in parsed_yaml:

            # Build a list of deployed charms and mapping of charms <-> applications
            self.map_charms(parsed_yaml[applications])

            # Automatically detects cloud type if it's not passed as argument
            self.check_cloud_type(self.model.charms)

            # Parse SAAS / remote-applications
            self.parse_cmr_apps(parsed_yaml)

            # Check configuration
            self.check_configuration(parsed_yaml[applications])

            # Then map out subordinates to applications
            for app in parsed_yaml[applications]:
                self.process_subordinates(parsed_yaml[applications][app], app)

            self.check_subs(parsed_yaml["machines"])
            self.check_relations(input_file)
            self.check_hyper_converged(input_file)
            self.check_charms()

            if "relations" in parsed_yaml:
                # "bindings" *should* be in exported bundles, *unless* no custom bindings exist,
                # in which case "juju export-bundle" omits them. See LP#1949883.
                bindings = any(
                    "bindings" in app for app in parsed_yaml[applications].values()
                )
                if bindings:
                    # try:
                    self.check_spaces(parsed_yaml)
                    # except Exception as e:
                    #     self._log_with_header(
                    #         "Encountered error while checking spaces: {}".format(e),
                    #         level=logging.WARN
                    #     )
                else:
                    self._log_with_header(
                        "Relations detected but explicit bindings not found; "
                        "Not specifying explicit bindings may cause problems on models"
                        " with multiple network spaces.",
                        level=logging.WARNING,
                    )
            else:
                self._log_with_header(
                    "Bundle relations data not found; skipping space binding checks."
                )

            if "relations" not in parsed_yaml:
                self.map_machines_to_az(parsed_yaml["machines"])
                self.check_azs(parsed_yaml[applications])
                self.check_statuses(parsed_yaml, applications)
            else:
                self._log_with_header(
                    "Relations data found; assuming a bundle and skipping AZ and status checks."
                )

            self.results()
        else:
            self._log_with_header(
                "Model contains no applications, skipping.", level=logging.WARN
            )

    def collect(self, message):
        """Collect an error and add it to the collector."""
        self.output_collector["errors"].append(message)

    def message_handler(self, message, log_level=logging.ERROR):
        """Handle message from checks and append error messages to the collector."""
        if "message" not in message:
            log_level = logging.ERROR
            message = {"message": "wrong message_handler format"}

        self._log_with_header(message["message"], level=log_level)

        if self.collect_errors and log_level == logging.ERROR:
            self.collect(message)

    def _process_includes_in_rules(self, yaml_txt, filename):
        """
        Process any includes in the rules file.

        Only top level includes are supported (without recursion), with relative paths.

        Example syntax:

        !include foo.yaml
        """
        collector = []
        for line in yaml_txt.splitlines():
            if line.startswith("!include"):
                try:
                    _, rel_path = line.split()
                except ValueError:  # pragma: no cover
                    self.logger.warn(
                        "invalid include in rules, ignored: '{}'".format(line)
                    )
                    continue

                include_path = os.path.join(os.path.dirname(filename), rel_path)

                if os.path.isfile(include_path):
                    with open(include_path, "r") as f:
                        collector.append(f.read())
            else:
                collector.append(line)

        return yaml.safe_load("\n".join(collector))

    def _log_with_header(self, msg, level=logging.DEBUG):
        """Log a message with the cloud/controller/model header."""
        self.logger.log(
            "[{}] [{}/{}] {}".format(
                self.cloud_name, self.controller_name, self.model_name, msg
            ),
            level=level,
        )
