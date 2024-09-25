#!/usr/bin/python3
"""Test the relations module."""
import pytest

from jujulint.checks import relations

CHARM_TO_APP = {"nrpe-host", "nrpe-container"}
CHARM = "nrpe"
# rule to check all charms with nrpe-external-master endpoint.
RELATIONS = [["*:nrpe-external-master", "nrpe:nrpe-external-master"]]


@pytest.mark.parametrize(
    "correct_relation, input_file_type",
    [
        (RELATIONS, "juju-status"),
        (RELATIONS, "juju-status-34"),
        (RELATIONS, "juju-bundle"),
        (
            [["nrpe:nrpe-external-master", "*:nrpe-external-master"]],
            "juju-status",
        ),  # inverting sequence doesn't change the endpoint
        (
            [["nrpe:nrpe-external-master", "*:nrpe-external-master"]],
            "juju-status-34",
        ),  # inverting sequence doesn't change the endpoint
        (
            [["nrpe:nrpe-external-master", "*:nrpe-external-master"]],
            "juju-bundle",
        ),  # inverting sequence doesn't change the endpoint
        (
            [["nrpe:nrpe-external-master", "keystone:nrpe-external-master"]],
            "juju-status",
        ),  # able to find specific app relation
        (
            [["nrpe:nrpe-external-master", "keystone:nrpe-external-master"]],
            "juju-status-34",
        ),  # able to find specific app relation
        (
            [["nrpe:nrpe-external-master", "keystone:nrpe-external-master"]],
            "juju-bundle",
        ),  # able to find specific app relation
    ],
)
def test_relation_rule_valid(correct_relation, input_file_type, input_files):
    """Missing rules have empty set for endpoints with expected relations."""
    relation_rule = relations.RelationRule(
        input_file=input_files[input_file_type],
        charm=CHARM,
        relations=correct_relation,
        not_exist=[[]],
        exception=set(),
        ubiquitous=True,
    )
    relation_rule.check()
    assert relation_rule.missing_relations == {"nrpe:nrpe-external-master": list()}
    assert relation_rule.not_exist_error == list()
    assert relation_rule.missing_machines == list()
    assert relation_rule.__repr__() == "RelationRule(nrpe -> nrpe-external-master)"
    assert relation_rule.endpoint == "nrpe-external-master"


@pytest.mark.parametrize("input_file_type", ["juju-status", "juju-bundle"])
def test_relation_not_exist(input_file_type, input_files):
    """Ensure that finds a relation that shouldn't happen."""
    wrong_relation = ["keystone:foo-endpoint", "foo-charm:foo-endpoint"]
    input_file = input_files[input_file_type]
    if input_file_type == "juju-status":
        input_file.applications_data["foo-charm"] = {
            "charm": "cs:foo-charm-7",
            "charm-name": "foo-charm",
            "relations": {
                "foo-endpoint": ["keystone"],
            },
            "endpoint-bindings": {
                "": "oam-space",
                "foo-endpoint": "oam-space",
            },
        }
        input_file.applications_data["keystone"]["relations"]["foo-endpoint"] = [
            "foo-charm"
        ]
        input_file.applications_data["keystone"]["endpoint-bindings"][
            "foo-endpoint"
        ] = "oam-space"

    elif input_file_type == "juju-bundle":
        input_file.applications_data["foo-charm"] = {
            "charm": "cs:foo-charm-7",
            "charm-name": "foo-charm",
            "bindings": {
                "": "oam-space",
                "foo-endpoint": "oam-space",
            },
        }
        input_file.applications_data["keystone"]["bindings"][
            "foo-endpoint"
        ] = "oam-space"
        input_file.relations_data.append(wrong_relation)

    relation_rule = relations.RelationRule(
        input_file=input_file,
        charm=CHARM,
        relations=RELATIONS,
        not_exist=[wrong_relation],
        exception=set(),
        ubiquitous=True,
    )
    relation_rule.check()
    assert relation_rule.not_exist_error == [wrong_relation]


@pytest.mark.parametrize("input_file_type", ["juju-status", "juju-bundle"])
def test_relation_not_exist_raise(input_file_type, input_files):
    """Test that raise exception when not_exist has wrong format."""
    input_file = input_files[input_file_type]

    if input_file_type == "juju-status":
        input_file.applications_data["foo-charm"] = {
            "charm": "cs:foo-charm-7",
            "charm-name": "foo-charm",
            "relations": {
                "bar-endpoint": ["keystone"],
            },
            "endpoint-bindings": {
                "": "oam-space",
                "bar-endpoint": "oam-space",
            },
        }

    elif input_file_type == "juju-bundle":
        input_file.applications_data["foo-charm"] = {
            "charm": "cs:foo-charm-7",
            "charm-name": "foo-charm",
            "bindings": {
                "": "oam-space",
                "bar-endpoint": "oam-space",
            },
        }

    with pytest.raises(relations.RelationError):
        relation_rule = relations.RelationRule(
            input_file=input_file,
            charm=CHARM,
            relations=RELATIONS,
            not_exist=[["keystone", "foo-charm:foo-endpoint"]],
            exception=set(),
            ubiquitous=True,
        )
        relation_rule.check()


@pytest.mark.parametrize(
    "expected_missing, exception, input_file_type",
    [
        ({"nrpe:nrpe-external-master": ["foo-charm"]}, set(), "juju-status"),
        ({"nrpe:nrpe-external-master": list()}, {"foo-charm"}, "juju-bundle"),
    ],
)
def test_missing_relation_and_exception(
    expected_missing, exception, input_files, input_file_type
):
    """Assert that exception rule field is able to remove apps missing the relation."""
    # add a charm in apps that has the endpoint nrpe-external-master,
    # but it's not relating with nrpe.
    input_file = input_files[input_file_type]
    if input_file_type == "juju-status":
        input_file.applications_data["foo-charm"] = {
            "charm": "cs:foo-charm-7",
            "charm-name": "foo-charm",
            "relations": {
                "foo-endpoint": ["bar-charm"],
            },
            "endpoint-bindings": {
                "": "oam-space",
                "nrpe-external-master": "oam-space",
            },
        }
    elif input_file_type == "juju-bundle":
        input_file.applications_data["foo-charm"] = {
            "charm": "cs:foo-charm-7",
            "charm-name": "foo-charm",
            "bindings": {
                "": "oam-space",
                "nrpe-external-master": "oam-space",
            },
        }
        input_file.relations_data.append(
            ["foo-charm:nrpe-external-master", "nrpe-host:nrpe-external-master"]
        )

    relation_rule = relations.RelationRule(
        input_file=input_file,
        charm=CHARM,
        relations=RELATIONS,
        not_exist=[[]],
        exception=exception,
        ubiquitous=True,
    )
    relation_rule.check()
    assert relation_rule.missing_relations == expected_missing


@pytest.mark.parametrize("input_file_type", ["juju-status", "juju-bundle"])
def test_relation_rule_unknown_charm(mocker, input_files, input_file_type):
    """Empty relation for a unknown charm in rules and gives warning message."""
    input_file = input_files[input_file_type]
    charm = "foo_charm"
    warning_msg = (
        "Relations rules has an unexpected format. "
        f"It was not possible to find {charm} on rules"
    )
    logger_mock = mocker.patch.object(relations, "LOGGER")
    relation_rule = relations.RelationRule(
        input_file=input_file,
        charm="foo_charm",
        relations=[["*:public", "keystone:public"]],
        not_exist=[[]],
        exception=set(),
        ubiquitous=False,
    )
    assert relation_rule.relations == []
    logger_mock.warning.assert_has_calls([mocker.call(warning_msg)])


@pytest.mark.parametrize(
    "fake_relations, app_error, endpoint_error, input_file_type",
    [
        (
            [["foo:juju-info", "bar:juju-info"]],
            True,
            False,
            "juju-status",
        ),  # app doesn't exist
        (
            [["foo:juju-info", "bar:juju-info"]],
            True,
            False,
            "juju-status-34",
        ),  # app doesn't exist
        (
            [["foo:juju-info", "bar:juju-info"]],
            True,
            False,
            "juju-bundle",
        ),  # app doesn't exist
        (
            [["keystone:bar", "nrpe-host:foo"]],
            False,
            True,
            "juju-status",
        ),  # endpoint doesn't exist
        (
            [["keystone:bar", "nrpe-host:foo"]],
            False,
            True,
            "juju-status-34",
        ),  # endpoint doesn't exist
        (
            [["keystone:bar", "nrpe-host:foo"]],
            False,
            True,
            "juju-bundle",
        ),  # endpoint doesn't exist
    ],
)
def test_relation_rule_unknown_app_endpoint(
    fake_relations, app_error, endpoint_error, input_files, input_file_type
):
    """Ensure warning message and empty relations if app or endpoint is unknown."""
    input_file = input_files[input_file_type]

    relations_rule = relations.RelationRule(
        input_file=input_file,
        charm=CHARM,
        relations=fake_relations,
        not_exist=[[]],
        exception=set(),
        ubiquitous=False,
    )
    # assert that relations is empty
    assert relations_rule.relations == []


@pytest.mark.parametrize(
    "machines, missing_machines, relations_to_check, input_file_type",
    # adding new machines that nrpe is not relating
    [
        (
            {"3": {"series": "focal"}, "2": {"series": "bionic"}},
            ["2", "3"],
            RELATIONS,
            "juju-status",
        ),
        (
            {"3": {"series": "focal"}, "2": {"series": "bionic"}},
            ["2", "3"],
            RELATIONS,
            "juju-status-34",
        ),
        (
            {"3": {"series": "focal"}, "2": {"series": "bionic"}},
            ["2", "3"],
            RELATIONS,
            "juju-bundle",
        ),
        # empty relations is able to run ubiquitous check
        (
            {"3": {"series": "focal"}, "2": {"series": "bionic"}},
            ["2", "3"],
            [[]],
            "juju-status",
        ),
        (
            {"3": {"series": "focal"}, "2": {"series": "bionic"}},
            ["2", "3"],
            [[]],
            "juju-status-34",
        ),
        (
            {"3": {"series": "focal"}, "2": {"series": "bionic"}},
            ["2", "3"],
            [[]],
            "juju-bundle",
        ),
        (
            {
                "3": {
                    "series": "focal",
                    "containers": {
                        "3/lxd/0": {"series": "focal"},
                        "3/lxd/10": {"series": "focal"},
                        "3/lxd/1": {"series": "focal"},
                        "3/lxd/5": {"series": "focal"},
                    },
                }
            },
            # result of missing machines is sorted
            ["3", "3/lxd/0", "3/lxd/1", "3/lxd/5", "3/lxd/10"],
            RELATIONS,
            "juju-status",
        ),
        # bundles pass the machine to deploy the containers
        (
            {
                "3": {
                    "series": "focal",
                    "containers": ["lxd:0", "lxd:3"],
                }
            },
            # result of missing machines is sorted
            ["lxd:0", "3", "lxd:3"],
            RELATIONS,
            "juju-bundle",
        ),
    ],
)
def test_ubiquitous_missing_machine(
    input_files, machines, missing_machines, relations_to_check, input_file_type
):
    """Test that find missing machines for an ubiquitous charm."""
    input_file = input_files[input_file_type]
    if input_file_type == "juju-bundle":
        for machine in machines:
            containers = machines[machine].pop("containers", None)
            if containers:
                # pass new machines and containers to deploy keystone
                input_file.applications_data["keystone"]["to"].extend(containers)
    input_file.machines_data.update(machines)
    # map machines again
    input_file.map_file()
    relation_rule = relations.RelationRule(
        input_file=input_file,
        charm=CHARM,
        relations=relations_to_check,
        not_exist=[[]],
        exception=set(),
        ubiquitous=True,
    )
    relation_rule.check()
    assert relation_rule.missing_machines == missing_machines


def test_relations_raise_not_implemented(input_files, mocker):
    """Ensure that a new class that not implement mandatory methods raises error."""
    logger_mock = mocker.patch.object(relations, "LOGGER")
    mocker.patch(
        "jujulint.checks.relations.RelationRule.relation_exist_check",
        side_effect=NotImplementedError(),
    )
    input_file = input_files["juju-status"]
    relation_rule = relations.RelationRule(
        input_file=input_file,
        charm=CHARM,
        relations=RELATIONS,
        not_exist=[[]],
        exception=set(),
        ubiquitous=False,
    )
    relation_rule.check()
    logger_mock.debug.assert_called_once()


@pytest.mark.parametrize("input_file_type", ["juju-status", "juju-bundle"])
def test_relations_rules_bootstrap(input_files, input_file_type):
    """Test RelationsRulesBootStrap object."""
    input_file = input_files[input_file_type]
    relations_rules = [
        {
            "charm": "nrpe",
            "check": [["*:nrpe-external-master", "nrpe:nrpe-external-master"]],
        },
        {
            "charm": "elasticsearch",
            "check": [
                ["elasticsearch:nrpe-external-master", "nrpe-host:nrpe-external-master"]
            ],
        },
    ]
    relations_rules = relations.RelationsRulesBootStrap(
        relations_rules=relations_rules,
        input_file=input_file,
    ).check()
    assert len(relations_rules) == 2
    assert all(
        isinstance(relation_rule, relations.RelationRule)
        for relation_rule in relations_rules
    )
