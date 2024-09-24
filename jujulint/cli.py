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
"""Main entrypoint for the juju-lint CLI."""
import errno
import logging
import os.path
import sys
import tempfile
from importlib.metadata import PackageNotFoundError, version

import yaml

from jujulint.config import Config
from jujulint.lint import Linter
from jujulint.logging import Logger
from jujulint.openstack import OpenStack
from jujulint.util import is_url


class Cli:
    """Core class of the CLI for juju-lint."""

    clouds = {}

    def __init__(self):
        """Create new CLI and configure runtime environment."""
        self.config = Config()
        self.logger = Logger(self.config["logging"]["loglevel"].get())
        self.output_format = self.config["format"].get()

        # disable logging for non-text output formats
        if self.output_format != "text":
            logging.disable(level=logging.CRITICAL)

        # get the version of the current package if available
        # this will fail if not running from an installed package
        # e.g. during unit tests
        try:
            self.version = version("jujulint")
        except PackageNotFoundError:
            self.version = "unknown"

        self.rules_files = self.validate_rules_file_args()

    @property
    def cloud_type(self):
        """Get the cloud type passed in the CLI.

        :return: cloud-type of the deployment or None.
        :rtype: str
        """
        cloud_type = None
        if "cloud-type" in self.config:
            cloud_type = self.config["cloud-type"].get()
        return cloud_type

    @property
    def manual_file(self):
        """Get the manual file passed in the CLI.

        :return: path to manual file to lint or None.
        :rtype: str
        """
        manual_file = None
        if "manual-file" in self.config:
            manual_file = self.config["manual-file"].get()
        return manual_file

    def validate_rules_file_args(self):
        """Validate the given rules file arguments.

        :return: a list of validated and slightly adjusted
                 paths/urls to the rules files.
        :rtype: list
        """
        rules_file_args = [
            rules_file.strip()
            for rules_file in self.config["rules"]["file"].get().split(",")
            if rules_file.strip()
        ]
        validated_rules_file_args = []

        for arg in rules_file_args:
            # does not say anything about accessibility of the resource
            # pointed to by the url. we are just checking if the url
            # is well formed.
            if is_url(arg):
                validated_rules_file_args.append(arg)

            # absolute path provided
            elif os.path.isfile(arg):
                validated_rules_file_args.append(arg)

            # default to relative path
            elif os.path.isfile("{}/{}".format(self.config.config_dir(), arg)):
                validated_rules_file_args.append(
                    "{}/{}".format(self.config.config_dir(), arg)
                )
            else:
                self.logger.error("Cloud not locate rules file {}".format(arg))
                sys.exit(1)

        return validated_rules_file_args

    def startup_message(self):
        """Print startup message to log."""
        self.logger.info(
            (
                "juju-lint version {} starting...\n"
                "\t* Config directory: {}\n"
                "\t* Cloud type: {}\n"
                "\t* Manual file: {}\n"
                "\t* Rules files: {}\n"
                "\t* Log level: {}\n"
            ).format(
                self.version,
                self.config.config_dir(),
                self.cloud_type or "Unknown",
                self.manual_file or False,
                self.rules_files,
                self.config["logging"]["loglevel"].get(),
            )
        )

    def usage(self):
        """Print program usage."""
        self.config.parser.print_help()

    def audit_file(self, filename, cloud_type=None):
        """Directly audit a YAML file."""
        self.logger.debug("Starting audit of file {}".format(filename))
        linter = Linter(
            filename,
            self.rules_files,
            cloud_type=cloud_type,
            output_format=self.output_format,
        )
        if not linter.read_rules():
            Logger.fubar("Error while reading the rules. Exiting...")
        self.logger.info("[{}] Linting manual file...".format(filename))
        linter.lint_yaml_file(filename)

    def audit_all(self):
        """Iterate over clouds and run audit."""
        self._check_output_folder()
        self.logger.debug("Starting audit")
        for cloud_name in self.config["clouds"].get():
            self.audit(cloud_name)
        # serialise state
        if self.clouds:
            self.write_yaml(self.clouds, "all-data.yaml")

    def audit(self, cloud_name):
        """Run the main audit process process each cloud."""
        # load clouds and loop through each defined cloud
        if cloud_name not in self.clouds.keys():
            self.clouds[cloud_name] = {}
        cloud = self.config["clouds"][cloud_name].get()
        access_method = "local"
        ssh_host = None
        sudo_user = None
        if "access" in cloud:
            access_method = cloud["access"]
        if "sudo" in cloud:
            sudo_user = cloud["sudo"]
        if "host" in cloud:
            ssh_host = cloud["host"]
        self.logger.debug(cloud)
        # load correct handler (OpenStack)
        if cloud["type"] == "openstack":
            cloud_instance = OpenStack(
                cloud_name,
                access_method=access_method,
                ssh_host=ssh_host,
                sudo_user=sudo_user,
                lint_rules=self.rules_files,
            )
        # refresh information
        result = cloud_instance.refresh()
        if result:
            self.clouds[cloud_name] = cloud_instance.cloud_state
            self.logger.debug(
                "Cloud state for {} after refresh: {}".format(
                    cloud_name, cloud_instance.cloud_state
                )
            )
            self.write_yaml(
                cloud_instance.cloud_state, "{}-state.yaml".format(cloud_name)
            )
            # run audit checks
            cloud_instance.audit()
        else:
            self.logger.error("[{}] Failed getting cloud state".format(cloud_name))

    def write_yaml(self, data, file_name):
        """Write collected information to YAML."""
        folder_name = self.config["output"]["folder"].get()
        if folder_name:
            file_handle = open("{}/{}".format(folder_name, file_name), "w")
            yaml.dump(data, file_handle)

    def _check_output_folder(self):
        """Check the output folder for permission and existence."""
        outdir = self.config["output"]["folder"].get()
        if outdir:
            try:
                with tempfile.TemporaryFile(dir=outdir):
                    pass  # pragma: no cover
            except FileNotFoundError as err:
                err.filename = outdir
                Logger.fubar(msg=str(err), exit_code=errno.ENOENT)
            except PermissionError as err:
                err.filename = outdir
                Logger.fubar(msg=str(err), exit_code=errno.EACCES)
            except Exception as err:
                err.filename = outdir
                Logger.fubar(msg=str(err))


def main():
    """Program entry point."""
    cli = Cli()
    cli.startup_message()
    if cli.manual_file:
        cli.audit_file(cli.manual_file, cloud_type=cli.cloud_type)
    elif "clouds" in cli.config:
        cli.audit_all()
    else:
        cli.usage()


if __name__ == "__main__":  # pragma: no cover
    main()
