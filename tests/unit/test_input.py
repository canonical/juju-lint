from dataclasses import dataclass

import pytest

from jujulint import model_input


@pytest.mark.parametrize("input_file_type", ["juju-status", "juju-bundle"])
def test_file_inputs(input_files, input_file_type):
    """Test that files are mapping properties as expected."""
    input_file = input_files[input_file_type]
    expected_output = {
        "applications": {
            "elasticsearch",
            "ubuntu",
            "keystone",
            "nrpe-container",
            "nrpe-host",
        },
        "machines": {
            "juju-status": {"0", "1", "1/lxd/0"},
            "juju-bundle": {"0", "1", "lxd:1"},
        },
        "charms": {"elasticsearch", "ubuntu", "nrpe", "keystone"},
        "app_to_charm": {
            "elasticsearch": "elasticsearch",
            "ubuntu": "ubuntu",
            "keystone": "keystone",
            "nrpe-host": "nrpe",
            "nrpe-container": "nrpe",
        },
        "charm_to_app": {
            "nrpe": {"nrpe-container", "nrpe-host"},
            "ubuntu": {"ubuntu"},
            "elasticsearch": {"elasticsearch"},
            "keystone": {"keystone"},
        },
        "apps_to_machines": {
            "juju-status": {
                "nrpe-container": {"1/lxd/0"},
                "nrpe-host": {"0", "1"},
                "ubuntu": {"1"},
                "elasticsearch": {"0"},
                "keystone": {"1/lxd/0"},
            },
            "juju-bundle": {
                "nrpe-container": {"lxd:1"},
                "nrpe-host": {"0", "1"},
                "ubuntu": {"1"},
                "elasticsearch": {"0"},
                "keystone": {"lxd:1"},
            },
        },
        "machines_to_apps": {
            "juju-status": {
                "0": {"nrpe-host", "elasticsearch"},
                "1": {"ubuntu", "nrpe-host"},
                "1/lxd/0": {"nrpe-container", "keystone"},
            },
            "juju-bundle": {
                "0": {"nrpe-host", "elasticsearch"},
                "1": {"ubuntu", "nrpe-host"},
                "lxd:1": {"nrpe-container", "keystone"},
            },
        },
    }
    assert input_file.applications == expected_output["applications"]
    assert input_file.machines == expected_output["machines"][input_file_type]
    assert (
        input_file.apps_to_machines
        == expected_output["apps_to_machines"][input_file_type]
    )
    assert (
        input_file.machines_to_apps
        == expected_output["machines_to_apps"][input_file_type]
    )
    assert input_file.charms == expected_output["charms"]
    assert input_file.app_to_charm == expected_output["app_to_charm"]
    assert input_file.charm_to_app == expected_output["charm_to_app"]


@pytest.mark.parametrize(
    "app_endpoint, app_error, endpoint_error, input_file_type, expected_output",
    [
        # app doesn't exist
        ("foo:juju-info", True, False, "juju-status", ("", "")),
        ("foo:juju-info", True, False, "juju-bundle", ("", "")),
        # endpoint doesn't exist
        ("keystone:bar", False, True, "juju-status", ("", "")),
        ("keystone:bar", False, True, "juju-bundle", ("", "")),
        # app and endpoint exist
        (
            "keystone:nrpe-external-master",
            False,
            False,
            "juju-status",
            ("keystone", "nrpe-external-master"),
        ),
        (
            "keystone:nrpe-external-master",
            False,
            False,
            "juju-bundle",
            ("keystone", "nrpe-external-master"),
        ),
    ],
)
def test_check_app_endpoint_existence(
    app_endpoint,
    app_error,
    endpoint_error,
    mocker,
    input_files,
    input_file_type,
    expected_output,
):
    """Test the expected check_app_endpoint_existence method behavior."""
    input_file = input_files[input_file_type]
    logger_mock = mocker.patch.object(model_input, "LOGGER")
    app, endpoint = app_endpoint.split(":")
    expected_msg = ""
    if app_error:
        expected_msg = f"{app} not found on applications."
    elif endpoint_error:
        expected_msg = f"endpoint: {endpoint} not found on {app}"

    assert (
        input_file.check_app_endpoint_existence(app_endpoint, "nrpe") == expected_output
    )
    if expected_msg:
        logger_mock.warning.assert_has_calls([mocker.call(expected_msg)])


@pytest.mark.parametrize(
    "input_file_type, charm, app, endpoint, expected_output",
    [
        (
            "juju-status",
            "nrpe",
            "*",
            "nrpe-external-master",
            {"keystone", "elasticsearch"},
        ),  # all apps with nrpe-external-master
        (
            "juju-status-34",
            "nrpe",
            "*",
            "nrpe-external-master",
            {"keystone", "elasticsearch"},
        ),  # all apps with nrpe-external-master
        (
            "juju-bundle",
            "nrpe",
            "*",
            "nrpe-external-master",
            {"keystone", "elasticsearch"},
        ),  # all apps with nrpe-external-master
        (
            "juju-status",
            "nrpe",
            "keystone",
            "nrpe-external-master",
            {"keystone"},
        ),  # check if keystone has nrpe-external-master
        (
            "juju-status-34",
            "nrpe",
            "keystone",
            "nrpe-external-master",
            {"keystone"},
        ),  # check if keystone has nrpe-external-master
        (
            "juju-bundle",
            "nrpe",
            "keystone",
            "nrpe-external-master",
            {"keystone"},
        ),  # check if keystone has nrpe-external-master
        (
            "juju-status",
            "nrpe",
            "ubuntu",
            "nrpe-external-master",
            set(),
        ),  # check if ubuntu has nrpe-external-master
        (
            "juju-status-34",
            "nrpe",
            "ubuntu",
            "nrpe-external-master",
            set(),
        ),  # check if ubuntu has nrpe-external-master
        (
            "juju-bundle",
            "nrpe",
            "ubuntu",
            "nrpe-external-master",
            set(),
        ),  # check if ubuntu has nrpe-external-master
    ],
)
def test_filter_by_app_and_endpoint(
    input_files, input_file_type, charm, app, endpoint, expected_output
):
    """Test filter_by_app_and_endpoint method behave as expected."""
    input_file = input_files[input_file_type]
    assert (
        input_file.filter_by_app_and_endpoint(charm, app, endpoint) == expected_output
    )


@pytest.mark.parametrize(
    "input_file_type, endpoint, expected_output",
    [
        ("juju-status", "nrpe-external-master", {"keystone", "elasticsearch"}),
        ("juju-status-34", "nrpe-external-master", {"keystone", "elasticsearch"}),
        ("juju-bundle", "nrpe-external-master", {"keystone", "elasticsearch"}),
        ("juju-status", "general-info", {"ubuntu"}),
        ("juju-status-34", "general-info", {"ubuntu"}),
        ("juju-bundle", "general-info", {"ubuntu"}),
        ("juju-status", "monitors", set()),
        ("juju-status-34", "monitors", set()),
        ("juju-bundle", "monitors", set()),
    ],
)
def test_filter_by_relation(input_file_type, endpoint, expected_output, input_files):
    """Test filter_by_relation method behave as expected."""
    input_file = input_files[input_file_type]
    assert (
        input_file.filter_by_relation(input_file.charm_to_app["nrpe"], endpoint)
        == expected_output
    )


@pytest.mark.parametrize(
    "parsed_yaml, expected_output",
    [
        ("parsed_yaml_status", model_input.JujuStatusFile),
        ("parsed_yaml_bundle", model_input.JujuBundleFile),
    ],
)
def test_input_handler(parsed_yaml, expected_output, request):
    """Input handler return expected objects depending on the input."""
    input_file = request.getfixturevalue(parsed_yaml)
    assert isinstance(
        model_input.input_handler(input_file, "applications"), expected_output
    )


@pytest.mark.parametrize("input_file_type", ["juju-status", "juju-bundle"])
def test_filter_machines_by_charm(input_files, input_file_type):
    """Test filter_machines_by_charm method."""
    input_file = input_files[input_file_type]
    if input_file_type == "juju-status":
        expected_output = {
            "nrpe": {"0", "1", "1/lxd/0"},
            "keystone": {"1/lxd/0"},
            "ubuntu": {"1"},
            "elasticsearch": {"0"},
        }
    else:
        expected_output = {
            "nrpe": {"0", "1", "lxd:1"},
            "keystone": {"lxd:1"},
            "ubuntu": {"1"},
            "elasticsearch": {"0"},
        }
    for charm in input_file.charms:
        assert input_file.filter_machines_by_charm(charm) == expected_output[charm]


@pytest.mark.parametrize("input_file_type", ["juju-status", "juju-bundle"])
def test_filter_lxd_on_machine(input_files, input_file_type):
    """Test filter_lxd_on_machine method."""
    input_file = input_files[input_file_type]
    if input_file_type == "juju-status":
        expected_output = {
            "0": set(),
            "1": {"1/lxd/0"},
            "1/lxd/0": set(),
        }
    else:
        expected_output = {
            "0": set(),
            "1": {"lxd:1"},
            "lxd:1": set(),
        }
    for machine in input_file.machines:
        assert input_file.filter_lxd_on_machine(machine) == expected_output[machine]


def test_raise_not_implemented_methods(parsed_yaml_status):
    # declare a new input class
    @dataclass
    class MyNewInput(model_input.BaseFile):
        # overwrite parent method to map file
        def __post_init__(self):
            return 0

    new_input = MyNewInput(
        applications_data=parsed_yaml_status["applications"],
        machines_data=parsed_yaml_status["machines"],
    )

    with pytest.raises(NotImplementedError):
        new_input.map_machines()

    with pytest.raises(NotImplementedError):
        new_input.map_apps_to_machines()

    with pytest.raises(NotImplementedError):
        new_input.filter_by_relation({"nrpe"}, "nrpe-external-master")

    with pytest.raises(NotImplementedError):
        new_input.sorted_machines("0")

    with pytest.raises(NotImplementedError):
        new_input.filter_lxd_on_machine("0")
