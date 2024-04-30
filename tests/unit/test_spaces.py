"""Tests for spaces.py module."""

from unittest.mock import call

import pytest

from jujulint.checks import spaces


def test_relation_init():
    """Test initiation of Relation instance."""
    ep_1 = "Endpoint 1"
    ep_2 = "Endpoint 2"

    relation = spaces.Relation(ep_1, ep_2)

    assert relation.endpoint1 == ep_1
    assert relation.endpoint2 == ep_2


def test_relation_str():
    """Test expected string representation of a Relation class."""
    ep_1 = "Endpoint 1"
    ep_2 = "Endpoint 2"
    expected_str = "Relation({} - {})".format(ep_1, ep_2)

    relation = spaces.Relation(ep_1, ep_2)

    assert str(relation) == expected_str


@pytest.mark.parametrize(
    "rel_1_ep_1, rel_1_ep_2, rel_2_ep_1, rel_2_ep_2, expected_result",
    [
        (
            "same endpoint 1",
            "same endpoint 2",
            "same endpoint 1",
            "same endpoint 2",
            True,
        ),
        (
            "same endpoint 1",
            "same endpoint 2",
            "same endpoint 1",
            "different endpoint 2",
            False,
        ),
        (
            "same endpoint 1",
            "same endpoint 2",
            "different endpoint 1",
            "different endpoint 2",
            False,
        ),
        (
            "same endpoint 1",
            "same endpoint 2",
            "different endpoint 1",
            "same endpoint 2",
            False,
        ),
    ],
)
def test_relation_eq(rel_1_ep_1, rel_1_ep_2, rel_2_ep_1, rel_2_ep_2, expected_result):
    """Test equality operator of Relation class. Only return true if both endpoints match."""
    relation_1 = spaces.Relation(rel_1_ep_1, rel_1_ep_2)
    relation_2 = spaces.Relation(rel_2_ep_1, rel_2_ep_2)

    assert (relation_1 == relation_2) == expected_result


def test_relation_endpoints_prop():
    """Test "endpoints" property of a Relation class."""
    ep_1 = "Endpoint 1"
    ep_2 = "Endpoint 2"

    relation = spaces.Relation(ep_1, ep_2)

    assert relation.endpoints == [ep_1, ep_2]


@pytest.mark.parametrize(
    "input_order, output_order",
    [
        # Input endpoints are already in alphabetical order, output unchanged
        (
            ["A EP", "A Space", "Z EP", "Z Space"],
            ["A EP", "A Space", "Z EP", "Z Space"],
        ),
        # Input endpoints are not in order, output is alphabetically reordered
        (
            ["Z EP", "Z Space", "A EP", "A Space"],
            ["A EP", "A Space", "Z EP", "Z Space"],
        ),
        # Input endpoints are the same, no reordering occurs on output
        (
            ["Z EP", "A Space", "Z EP", "Z Space"],
            ["Z EP", "A Space", "Z EP", "Z Space"],
        ),
    ],
)
def test_space_mismatch_init(input_order, output_order):
    """Test initiation of SpaceMismatch class.

    This test also verifies that spaces in SpaceMismatch instance are ordered
    alphabetically based on the endpoint name.
    """
    mismatch_instance = spaces.SpaceMismatch(*input_order)

    # Assert that endpoints are alphabetically reordered
    assert mismatch_instance.endpoint1 == output_order[0]
    assert mismatch_instance.space1 == output_order[1]
    assert mismatch_instance.endpoint2 == output_order[2]
    assert mismatch_instance.space2 == output_order[3]


def test_space_mismatch_str():
    """Test string representation of a SpaceMismatch class."""
    ep_1 = "Endpoint 1"
    ep_2 = "Endpoint 2"
    space_1 = "Space 1"
    space_2 = "Space 2"
    expected_str = "SpaceMismatch({} (space {}) != {} (space {}))".format(
        ep_1, space_1, ep_2, space_2
    )

    mismatch_instance = spaces.SpaceMismatch(ep_1, space_1, ep_2, space_2)

    assert str(mismatch_instance) == expected_str


def test_space_mismatch_relation_prop():
    """Test relation property of a SpaceMismatch class."""
    ep_1 = "Endpoint 1"
    ep_2 = "Endpoint 2"
    space_1 = "Space 1"
    space_2 = "Space 2"

    expected_relation = spaces.Relation(ep_1, ep_2)

    mismatch_instance = spaces.SpaceMismatch(ep_1, space_1, ep_2, space_2)

    assert mismatch_instance.relation == expected_relation


def test_space_mismatch_get_charm_relation():
    """Test get_charm_relation method of SpaceMismatch."""
    app_1 = "ubuntu_server"
    charm_1 = "ubuntu"
    app_2 = "ubuntu_nrpe"
    charm_2 = "nrpe"
    ep_1 = app_1 + ":endpoint_1"
    ep_2 = app_2 + ":endpoint_2"
    space_1 = "Space 1"
    space_2 = "Space 2"

    app_map = {app_1: charm_1, app_2: charm_2}

    expected_relation = spaces.Relation("ubuntu:endpoint_1", "nrpe:endpoint_2")

    mismatch_instance = spaces.SpaceMismatch(ep_1, space_1, ep_2, space_2)

    assert mismatch_instance.get_charm_relation(app_map) == expected_relation


@pytest.mark.parametrize("use_cmr", [True, False])
def test_find_space_mismatches(use_cmr, mocker):
    """Test function find_space_mismatches()."""
    sample_yaml = "sample yaml"
    app_1 = "ubuntu_server"
    app_2 = "ubuntu_nrpe"
    space_1 = "space 1"
    space_2 = "space 2"
    app_endpoint_1 = app_1 + ":endpoint"
    app_endpoint_2 = app_2 + ":endpoint"
    relation = spaces.Relation(app_endpoint_1, "XModel" if use_cmr else app_endpoint_2)
    app_list = [app_1, app_2]
    app_spaces = {app_1: {space_1: "foo"}, app_2: {space_2: "bar"}}

    app_list_mock = mocker.patch.object(
        spaces, "get_juju_applications", return_value=app_list
    )
    app_spaces_mock = mocker.patch.object(
        spaces, "get_application_spaces", return_value=app_spaces
    )
    rel_list_mock = mocker.patch.object(
        spaces, "get_application_relations", return_value=[relation]
    )
    rel_space_mock = mocker.patch.object(
        spaces, "get_relation_space", side_effect=[space_1, space_2]
    )

    expected_mismatch = [
        spaces.SpaceMismatch(relation.endpoint1, space_1, relation.endpoint2, space_2)
    ]

    mismatch = spaces.find_space_mismatches(sample_yaml, True)
    result_pairs = zip(expected_mismatch, mismatch)

    app_list_mock.assert_called_once_with(sample_yaml)
    app_spaces_mock.assert_called_once_with(app_list, sample_yaml)
    rel_list_mock.assert_called_once_with(sample_yaml)
    rel_space_mock.assert_has_calls(
        [
            call(relation.endpoint1, app_spaces),
            call(relation.endpoint2, app_spaces),
        ]
    )
    for expected_result, actual_result in result_pairs:
        assert str(expected_result) == str(actual_result)


def test_get_juju_applications():
    """Test parsing applications from yaml status."""
    app_1 = "ubuntu"
    app_2 = "nrpe"
    sample_yaml = {
        "applications": {app_1: {"charm-url": "ch:foo"}, app_2: {"charm-url": "ch:bar"}}
    }

    expected_apps = [app_1, app_2]

    apps = spaces.get_juju_applications(sample_yaml)

    assert apps == expected_apps


def test_get_application_spaces(mocker):
    """Test function that returns map of applications and their bindings.

    This test also verifies that default binding to space "alpha" is added to applications
    that do not specify any bindings.
    """
    logger_mock = mocker.patch.object(spaces, "LOGGER")
    default_binding = ""
    default_space = "custom_default_space"
    public_binding = "public"
    public_space = "public_space"
    app_list = ["ubuntu", "nrpe", "mysql"]
    sample_yaml = {
        "applications": {
            # App with proper bindings
            app_list[0]: {
                "bindings": {
                    default_binding: default_space,
                    public_binding: public_space,
                }
            },
            # App with missing default bindings
            app_list[1]: {
                "bindings": {
                    public_binding: public_space,
                }
            },
            # App without any bindings defined
            app_list[2]: {},
        }
    }

    expected_app_spaces = {
        app_list[0]: {default_binding: default_space, public_binding: public_space},
        app_list[1]: {
            public_binding: public_space,
        },
        app_list[2]: {default_binding: "alpha"},
    }

    app_spaces = spaces.get_application_spaces(app_list, sample_yaml)

    # Verify that all the bindings for properly defined app were returned
    # Verify that default binding was added to app that did not have any bindings defined
    # Verify that Warning was logged for app without explicit default binding
    # Verify that Warnings were logged for app without any bindings

    assert app_spaces == expected_app_spaces
    logger_mock.warning.assert_has_calls(
        [
            call(
                "Application %s does not define explicit default binding", app_list[1]
            ),
            call("Application %s is missing explicit bindings", app_list[2]),
            call("Setting default binding of '%s' to alpha", app_list[2]),
        ]
    )


def test_get_application_relations():
    """Test function that returns list of relations."""
    sample_yaml = {
        "relations": [
            ["ubuntu:juju-info", "nrpe:general-info"],
            ["vault:shared-db", "mysql-innodb-cluster:shared-db"],
        ]
    }

    expected_relations = [
        spaces.Relation("ubuntu:juju-info", "nrpe:general-info"),
        spaces.Relation("vault:shared-db", "mysql-innodb-cluster:shared-db"),
    ]

    relations = spaces.get_application_relations(sample_yaml)

    assert relations == expected_relations


@pytest.mark.parametrize("use_explicit_binding", [True, False])
def test_get_relation_space(use_explicit_binding):
    """Test getting space for a specific binding."""
    app_name = "ubuntu"
    interface = "juju_info"
    default_space = "alpha"
    endpoint = app_name + ":" + interface

    app_spaces = {"ubuntu": {"": default_space}}

    if use_explicit_binding:
        expected_space = "custom_space"
        app_spaces["ubuntu"][interface] = expected_space
    else:
        expected_space = default_space

    space = spaces.get_relation_space(endpoint, app_spaces)

    assert space == expected_space


def test_get_relation_space_cmr(mocker):
    """Test getting space for cross model relation."""
    logger_mock = mocker.patch.object(spaces, "LOGGER")
    app_name = "ubuntu"
    interface = "juju_info"
    endpoint = app_name + ":" + interface

    app_spaces = {}

    space = spaces.get_relation_space(endpoint, app_spaces)

    assert space == "XModel"
    logger_mock.warning.assert_called_once_with(
        "Multi-model is not supported yet. Please check "
        "if '%s' is from another model",
        app_name,
    )
