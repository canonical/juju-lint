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
"""Kubernetes checks module.

This module provides checks for Kubernetes clouds.

Attributes:
     access (string): Set the access method (local/ssh)
     ssh_host (string, optional): Configuration to pass to Cloud module for accessing the cloud via SSH
     ssh_jump (string, optional): Jump/Bastion configuration to pass to Cloud module for access the cloud via SSH
     sudo_user (string, optional): User to switch to via sudo when accessing the cloud, passed to the Cloud module

Todo:
    * Add processing of kubectl information
    * Pass cloud type back to lint module
    * Add rules for k8s
    * Check OpenStack integrator charm configuration
    * Check distribution of k8s workloads to workers

"""  # noqa: W505

from jujulint.cloud import Cloud


class Kubernetes(Cloud):
    """Specialized subclass of Cloud with helpers related to Kubernetes."""

    def __init__(self, *args, **kwargs):
        """Initialise class-local variables and configuration and pass to super."""
        super(Kubernetes, self).__init__(*args, **kwargs)
        self.cloud_type = "kubernetes"

    def audit(self):
        """Audit OpenStack cloud and run base Cloud audits."""
        # add specific Kubernetes checks here
        self.logger.info("[{}] Running Kubernetes-specific audit steps.".format(self.name))
        super(Kubernetes, self).audit()
