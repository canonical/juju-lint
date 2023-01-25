"""Functional tests for juju-lint."""
import json
import socket
from subprocess import PIPE, check_call, check_output, run

import pytest


@pytest.mark.smoke
def test_juju_lint_startup():
    """Test starting juju-lint and print help string."""
    assert check_call("juju-lint --help".split()) == 0


@pytest.mark.smoke
def test_load_rules_file_from_path(rules_file, manual_file):
    """Test loading the rules file via command line argument."""
    assert check_call(f"juju-lint -c {rules_file} {manual_file}".split()) == 0


@pytest.mark.smoke
def test_load_default_rules_file(lint_rules_yaml, manual_file):
    """Test loading the default rules file."""
    assert check_call(f"juju-lint {manual_file}".split()) == 0


@pytest.mark.smoke
def test_json_output(rules_file, manual_file):
    """Test json output."""
    assert json.loads(
        check_output(
            f"juju-lint --format json -c {rules_file} {manual_file}".split()
        ).decode()
    )


@pytest.mark.smoke
def test_only_bad_url_causes_crash(manual_file):
    """Test that a bad url causes a crash."""
    bad_url = "foo://bad.url"
    process = run(
        f"juju-lint -c {bad_url} {manual_file}".split(),
        universal_newlines=True,
        stderr=PIPE,
    )
    assert not process.returncode == 0
    assert "urlopen error" in process.stderr


@pytest.mark.smoke
def test_bad_url_with_valid_rules_file_causes_crash(rules_file, manual_file):
    """Test that a bad url with a valid rules file causes a crash."""
    bad_url = "foo://bad.url"
    process = run(
        f"juju-lint -c {rules_file} -c {bad_url} {manual_file}".split(),
        universal_newlines=True,
        stderr=PIPE,
    )
    assert not process.returncode == 0
    assert "urlopen error" in process.stderr


@pytest.mark.smoke
def test_url(rules_file, rules_file_url, manual_file):
    error_string = "Application mysql-innodb-cluster has config for 'max-connections' which is less than"
    process = run(
        f"juju-lint -c {rules_file} {manual_file}".split(),
        universal_newlines=True,
        stderr=PIPE,
    )
    assert process.returncode == 0
    assert error_string not in process.stderr

    process = run(
        f"juju-lint -c {rules_file} -c {rules_file_url} {manual_file}".split(),
        universal_newlines=True,
        stderr=PIPE,
    )
    assert process.returncode == 0
    assert error_string in process.stderr


@pytest.mark.cloud
async def test_audit_local_cloud(ops_test, local_cloud, rules_file):
    """Test running juju-lint against a live local cloud."""
    await ops_test.model.deploy("ubuntu")
    await ops_test.model.wait_for_idle()
    returncode, stdout, stderr = await ops_test.run(
        *f"juju-lint -c {rules_file}".split()
    )
    assert (
        f"[{local_cloud}] Linting model information for {socket.getfqdn()}, "
        f"controller {ops_test.controller_name}, model {ops_test.model_name}" in stderr
    )
    assert returncode == 0


@pytest.mark.cloud
async def test_output_folder(ops_test, local_cloud, rules_file, tmp_path):
    """Test juju-lint state output to folder."""
    all_data_yaml = tmp_path / "all-data.yaml"
    cloudstate_yaml = tmp_path / f"{local_cloud}-state.yaml"
    assert not all_data_yaml.exists() and not cloudstate_yaml.exists()

    await ops_test.model.wait_for_idle()
    returncode, _, stderr = await ops_test.run(
        *f"juju-lint -d {tmp_path} -c {rules_file}".split()
    )

    assert (
        f"[{local_cloud}] Linting model information for {socket.getfqdn()}, "
        f"controller {ops_test.controller_name}, model {ops_test.model_name}" in stderr
    )
    assert returncode == 0
    assert all_data_yaml.exists() and cloudstate_yaml.exists()


@pytest.mark.parametrize(
    "bad_output_folder, expected_error",
    [
        ("non_existent_directory", "No such file or directory"),
        ("non_writable_directory", "Permission denied"),
    ],
)
@pytest.mark.cloud
async def test_bad_output_folder_error(
    ops_test, local_cloud, rules_file, bad_output_folder, expected_error, request
):
    """Test juju-lint fails gracefully for bad output folder values."""
    output_folder = request.getfixturevalue(bad_output_folder)

    await ops_test.model.wait_for_idle()
    returncode, _, stderr = await ops_test.run(
        *f"juju-lint -d {output_folder} -c {rules_file}".split()
    )
    assert returncode != 0
    assert (
        f"[{local_cloud}] Linting model information for {socket.getfqdn()}, "
        f"controller {ops_test.controller_name}, model {ops_test.model_name}"
        not in stderr
    )
    assert expected_error in stderr
