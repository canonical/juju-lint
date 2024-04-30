"""Pytest configuration file for juju-lint tests."""

import logging
import os
import shutil
from pathlib import Path
from subprocess import check_call, check_output
from tempfile import TemporaryDirectory
from textwrap import dedent

import pytest


def pytest_configure(config):
    """Pytest configuration."""
    config.addinivalue_line("markers", "smoke: mark test as a smoke test")
    config.addinivalue_line("markers", "cloud: mark test as a cloud test")


@pytest.fixture(scope="session", autouse=True)
def install_package():
    """Install the package to the system and cleanup afterwards.

    Depending on the environment variable TEST_SNAP,
    it will install the snap or the python package.
    """
    jujulint_test_snap = os.environ.get("TEST_SNAP", None)
    if jujulint_test_snap:
        # change directory to not import from local modules and force using the snap package
        cwd = os.getcwd()
        os.chdir("/tmp")
        logging.info(f"Installing {jujulint_test_snap}")
        assert os.path.isfile(jujulint_test_snap)
        assert (
            check_call(
                f"sudo snap install --dangerous --classic {jujulint_test_snap}".split()
            )
            == 0  # noqa
        )
        assert check_output("which juju-lint".split()).decode().strip() == os.path.join(
            "/snap/bin/juju-lint"
        )
    else:
        logging.warning("Installing python package")
        assert check_call("python3 -m pip install .".split()) == 0
        assert (
            check_output("which juju-lint".split())
            .decode()
            .strip()
            .startswith(os.path.join(os.getcwd(), ".tox"))
        )

    yield jujulint_test_snap

    if jujulint_test_snap:
        # return to the previous working directory
        os.chdir(cwd)
        logging.info("Removing snap package juju-lint")
        check_call("sudo snap remove juju-lint".split())
    else:
        logging.info("Uninstalling python package jujulint")
        check_call("python3 -m pip uninstall --yes jujulint".split())


@pytest.fixture
def basedir():
    """Return the basedir for the installation.

    This will ease testing the rules files that we ship
    with the juju-lint snap.
    """
    if os.environ.get("TEST_SNAP", None):
        basedir = "/snap/juju-lint/current/"
    else:
        basedir = os.getcwd()
    return basedir


@pytest.fixture
def rules_file(basedir):
    """Return the rules file for testing."""
    return os.path.join(basedir, "contrib/fcb-yoga-focal.yaml")


@pytest.fixture
def rules_file_url(httpserver):
    """Return a http url for a rules file.

    This fixture will make use of the pytest-httpserver
    plugin and fire up a HTTP server locally for the juju-lint
    application to call urlopen() against. It also temporarily
    makes necessary changes to bypass the proxy if necessary.
    """
    saved_no_proxy = os.environ.get("no_proxy", "")
    if "localhost" not in saved_no_proxy.split(","):
        os.environ["no_proxy"] = saved_no_proxy + ",localhost"

    endpoint = "/rules.yaml"
    rules_file_content = dedent(
        """
        openstack config:
            mysql-innodb-cluster:
                max-connections:
                    gte: 99999
        """
    )
    httpserver.expect_request(endpoint).respond_with_data(
        response_data=rules_file_content
    )

    yield httpserver.url_for(endpoint)

    if saved_no_proxy:
        os.environ["no_proxy"] = saved_no_proxy
    else:
        del os.environ["no_proxy"]


@pytest.fixture
def manual_file():
    """Return the bundle file for testing."""
    return os.path.join(
        os.path.dirname(__file__), "../resources/fcb-yoga-focal-bundle.yaml"
    )


@pytest.fixture
def lint_rules_yaml(basedir, rules_file):
    """Return the default lint-rules.yaml file and cleanup."""
    lint_rules_yaml_file = os.path.join(os.getcwd(), "lint-rules.yaml")
    shutil.copy(rules_file, lint_rules_yaml_file)

    includes_dir = os.path.join(os.getcwd(), "includes")
    os.symlink(os.path.join(basedir, "contrib/includes"), includes_dir)

    yield lint_rules_yaml_file

    os.unlink(lint_rules_yaml_file)
    os.unlink(includes_dir)


@pytest.fixture
def local_cloud():
    """Prepare the local configuration file for juju-lint.

    If there's an existing configuration directory, back it up
    first and then recover.
    """
    local_cloud_name = "test"
    backup = False
    local_config_dir = os.path.join(os.path.expanduser("~"), ".config/juju-lint")
    local_config_file = os.path.join(local_config_dir, "config.yaml")
    if os.path.isdir(local_config_dir):
        logging.info("Backing up existing config directory")
        shutil.move(local_config_dir, local_config_dir + ".bak")
        backup = True
    os.makedirs(local_config_dir)
    with open(local_config_file, "w") as config_yaml:
        config_yaml_str = f"""\
            clouds:
              {local_cloud_name}:
                type: openstack
            """
        config_yaml.write(dedent(config_yaml_str))

    yield local_cloud_name

    shutil.rmtree(local_config_dir)
    if backup:
        logging.info("Restoring backup")
        shutil.move(local_config_dir + ".bak", local_config_dir)


@pytest.fixture
def non_existent_directory():
    """Return a non-existent directory."""
    dir = Path("/a/path/that/does/not/exist")
    assert not dir.exists()
    return dir


@pytest.fixture
def non_writable_directory():
    """Return a non-writable directory."""
    dir = TemporaryDirectory()
    os.chmod(dir.name, mode=0o555)

    yield dir.name

    dir.cleanup()
