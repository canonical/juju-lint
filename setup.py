# This file is part of juju-lint, a tool for validating that Juju
# deloyments meet configurable site policies.
#
# Copyright 2018 Canonical Limited.
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
"""Setuptools packaging metadata for juju-lint."""
import warnings

import setuptools

warnings.simplefilter("ignore", UserWarning)  # Older pips complain about newer options.

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="jujulint",
    use_scm_version={"local_scheme": "node-and-date"},
    author="Canonical",
    author_email="juju@lists.ubuntu.com",
    description="Linter for Juju models to compare deployments with configurable policy",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://launchpad.net/juju-lint",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Development Status :: 2 - Beta",
        "Environment :: Plugins",
        "Intended Audience :: System Administrators",
    ],
    python_requires=">=3.7",
    packages=setuptools.find_packages(include=("jujulint*")),
    entry_points={"console_scripts": ["juju-lint=jujulint.cli:main"]},
    setup_requires=["setuptools_scm"],
    include_package_data=True,
)
