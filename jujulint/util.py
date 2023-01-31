#! /usr/bin/env python3
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
"""Utility library for all helpful functions this project uses."""

import argparse
import collections
import re
from copy import deepcopy
from urllib.parse import urlparse

from jujulint.logging import Logger


class InvalidCharmNameError(Exception):
    """Represents an invalid charm name being processed."""

    pass


def flatten_list(lumpy_list):
    """Flatten a list potentially containing other lists."""
    # Ensure we only operate on lists, otherwise will affect other iterables
    if not isinstance(lumpy_list, list):
        return lumpy_list

    flat_list = []
    for item in lumpy_list:
        if not isinstance(item, list):
            flat_list.append(item)
        else:
            flat_list.extend(flatten_list(item))
    return flat_list


def deep_update(existing, new):
    """Deep update an existing dictionary with new dictionary."""
    result = deepcopy(existing)

    def _deep_update_inplace(_existing, _new):
        """Perform an in-place recursive deep update of two dictionaries."""
        for key, val in _new.items():
            if isinstance(val, collections.abc.Mapping):
                _existing[key] = _deep_update_inplace(_existing.get(key, {}), val)
            else:
                _existing[key] = val
        return _existing

    return _deep_update_inplace(result, new)


def is_url(string):
    """Determine if a string is a url."""
    result = urlparse(string)
    return result.scheme and result.netloc


def is_container(machine):
    """Check if a provided machine is a container."""
    if "lxd/" in machine:
        return True
    else:
        return False


def is_virtual_machine(machine, machine_data):
    """
    Check if a provided machine is a VM.

    It is not straightforward to determine if a machine is a VM from juju data
    (bundle/juju status). In some cases a "hardware" key is provided (jsfy),
    and in those cases we can check for the keyword "virtual" since some
    provisioners include a tag there (FCE). We use that criteria as a best
    effort attempt to determine if the machine is a VM.
    """
    hardware = machine_data.get("hardware")
    return bool(hardware and "virtual" in hardware)


def is_metal(machine, machine_data):
    """
    Check if a provided machine is a bare metal host.

    Leverages the other detection methods, if the others fail (e.g. not a
    container or VM), we consider the machine to be bare metal.
    """
    return not (is_container(machine) or is_virtual_machine(machine, machine_data))


def extract_charm_name(charm):
    """Extract the charm name using regex."""
    match = re.match(
        r"^(?:\w+:)?(?:~[\w\.-]+/)?(?:\w+/)*([a-zA-Z0-9-]+?)(?:-\d+)?$", charm
    )
    if not match:
        raise InvalidCharmNameError("charm name '{}' is invalid".format(charm))
    return match.group(1)


class DeprecateAction(argparse.Action):  # pragma: no cover
    """Custom deprecation action to be used with ArgumentParser."""

    def __call__(self, parser, namespace, values, option_string=None):
        """Print a deprecation warning and remove the attribute from the namespace."""
        Logger().warn(
            "The argument {} is deprecated and will be ignored. ".format(option_string)
        )
        delattr(namespace, self.dest)
