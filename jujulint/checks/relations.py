#!/usr/bin/python3
"""Checks relations between applications."""
from logging import getLogger
from typing import Any, Dict, List, Set, Union

from jujulint.model_input import JujuBundleFile, JujuStatusFile

LOGGER = getLogger(__name__)


class RelationError(Exception):
    """Special exception for relations errors."""

    def __init__(self, msg: str):
        """Relation error message format.

        :param msg: Message of the exception found.
        :type msg: str
        """
        self.message = f"{self.__class__.__name__}: {msg}"


class RelationRule:
    """Object to check the relations rules."""

    def __init__(
        self,
        input_file: Union[JujuBundleFile, JujuStatusFile],
        charm: str,
        relations: List[List[str]],
        not_exist: List[List[str]],
        exception: Set,
        ubiquitous: bool,
    ):
        """Relation Rule object.

        :param input_file: mapped content of the input file.
        :type input_file: Union[JujuBundleFile, JujuStatusFile]
        :param charm: Name of the charm to check the relations rules.
        :type charm: str
        :param relations: Relations that should be checked of a given charm
            having the following format:
            [[<app_1>:<endpoint_1>], [<app_2>:<endpoint_2>]]
            If <application> == "*" it will check the relation using the endpoint
            on all applications form the file passed.
        :type relations: List[List[str]]
        :param not_exist: Relation that should not exist in the presence of the
            relations passed to be checked. This parameter has the following format:
            [[<app_1>:<endpoint_1>], [<app_2>:<endpoint_2>]]
        :type not_exist: List[List[str]],
        :param exception: Set of applications that the rule doesn't apply to.
        :type exception: Set
        :param ubiquitous: Check if charm is present on all machines.
        :type ubiquitous: bool
        """
        self.input_file = input_file
        self.charm = charm
        self.relations = relations
        self.not_exist = not_exist
        self.exception = exception
        self.ubiquitous = ubiquitous
        # remove all possible app names from the subordinate app to not check itself
        # self.apps_to_check = (
        #     self.input_file.applications - self.input_file.charm_to_app[self.charm]
        # )
        self.missing_relations = dict()
        self.not_exist_error = list()
        self.missing_machines = set()

    @property
    def relations(self) -> List[List[str]]:
        """Relations to be checked in a charm.

        :return: List of list containing the app and endpoint to check,
            with the following format: [[app_to_check, endpoint_to_check]]
        :rtype: List[List[str]]
        """
        return self._relations

    @relations.setter
    def relations(self, raw_relations_rules: List[List[str]]) -> None:
        """Relation setter of a rule.

        :param raw_relations_rules: Relations that should be checked of a given charm
            having the following format:
            [[<application_1>:<endpoint>], [<application_2>:<endpoint>]]
        :type raw_relations_rules: List[List[str]]
        :raises RelationError:  Raises RelationError if not in expected format.
        """
        self._relations = []
        if not all(raw_relations_rules):
            return
        for relation_rule in raw_relations_rules:
            try:
                app_0, endpoint_0 = self.input_file.check_app_endpoint_existence(
                    relation_rule[0], self.charm
                )
                app_1, endpoint_1 = self.input_file.check_app_endpoint_existence(
                    relation_rule[1], self.charm
                )
                if not all([app_0, endpoint_0, app_1, endpoint_1]):
                    # means that app or endpoint was not found
                    return
                if app_0 == self.charm or app_0 in self.input_file.charm_to_app[self.charm]:
                    self.endpoint = endpoint_0
                    app_to_check = app_1
                    endpoint_to_check = endpoint_1
                elif app_1 == self.charm or app_1 in self.input_file.charm_to_app[self.charm]:
                    self.endpoint = endpoint_1
                    app_to_check = app_0
                    endpoint_to_check = endpoint_0
                else:
                    msg = (
                        "Relations rules has an unexpected format. "
                        f"It was not possible to find {self.charm} on rules"
                    )
                    LOGGER.warning(msg)
                    return

                # check if all apps variations has the endpoint
                for app in self.input_file.charm_to_app[self.charm]:
                    self.input_file.check_app_endpoint_existence(
                        f"{app}:{self.endpoint}", self.charm
                    )
                self._relations.append([app_to_check, endpoint_to_check])
            except (IndexError, ValueError) as e:
                raise RelationError(f"Relations rules has an unexpected format: {e}")

    def __repr__(self) -> str:
        """Representation of the RelationRule object.

        :return: representation.
        :rtype: str
        """
        return f"{self.__class__.__name__}({self.charm} -> {self.endpoint})"

    def check(self) -> None:
        """Apply the relations rules check."""
        try:
            self.missing_machines = self.ubiquitous_check()
            self.relation_exist_check()
            self.relation_not_exist_check()
        except NotImplementedError as e:
            LOGGER.debug(e)

    def relation_exist_check(self) -> None:
        """Check if app(s) are relating with an endpoint."""
        for relation in self.relations:
            app_to_check, endpoint_to_check = relation
            # applications in the bundle that have the endpoint to relate
            apps_with_endpoint_to_check = self.input_file.filter_by_app_and_endpoint(
                self.charm,
                app_to_check,
                endpoint_to_check,
            )
            # applications that are relating using the endpoint from the relation rule
            apps_related_with_relation_rule = self.input_file.filter_by_relation(
                self.input_file.charm_to_app[self.charm],
                self.endpoint,
            )
            self.missing_relations[f"{self.charm}:{self.endpoint}"] = sorted(
                apps_with_endpoint_to_check - apps_related_with_relation_rule - self.exception
            )

    def relation_not_exist_check(self) -> None:
        """Check if a relation happens when it shouldn't.

        :raises RelationError: raise RelationError if it has wrong format.
        """
        for relation in self.not_exist:
            if relation:
                app_endpoint_splitted = []
                try:
                    for app_endpoint in relation:
                        app, endpoint = self.input_file.check_app_endpoint_existence(
                            app_endpoint, self.charm
                        )
                        app_endpoint_splitted.extend([app, endpoint])
                    (
                        app_to_check_0,
                        endpoint_to_check_0,
                        app_to_check_1,
                        _,
                    ) = app_endpoint_splitted
                    relations_app_endpoint_0 = self.input_file.filter_by_relation(
                        {app_to_check_0}, endpoint_to_check_0
                    )
                    if app_to_check_1 in relations_app_endpoint_0:
                        self.not_exist_error.append(relation)

                except (IndexError, ValueError) as e:
                    raise RelationError(f"Problem during check_relation_not_exist: {e}")

    def ubiquitous_check(self) -> List[str]:
        """Check if charm from relation rule is present on all machines.

        :return: Sorted list of machines missing the charm. If is present on
            all machines, returns an empty list.
        :rtype: List[str]
        """
        if self.ubiquitous:
            machines_with_charm = set()
            for app in self.input_file.charm_to_app[self.charm]:
                machines_with_charm.update(self.input_file.apps_to_machines[app])

            return sorted(
                self.input_file.machines - machines_with_charm,
                key=self.input_file.sorted_machines,
            )
        return []


class RelationsRulesBootStrap:
    """Bootstrap all relations rules to be checked."""

    def __init__(
        self,
        relations_rules: List[Dict[str, Any]],
        input_file: Union[JujuBundleFile, JujuStatusFile],
    ):
        """Relations rules bootStrap object.

        :param relations_rules: Relations rules from the rule file.
        :type relations_rules: List[Dict[str, Any]]
        :param input_file: mapped content of the input file.
        :type input_file: Union[JujuBundleFile, JujuStatusFile]
        """
        self.relations_rules = relations_rules
        self.input_file = input_file

    def check(self) -> List[RelationRule]:
        """Check all RelationRule objects.

        :return: List containing all RelationRule objects.
        :rtype: List[RelationRule]
        """
        relations_rules = [
            RelationRule(
                input_file=self.input_file,
                charm=rule.get("charm"),
                relations=rule.get("check", [[]]),
                not_exist=rule.get("not-exist", [[]]),
                exception=set(rule.get("exception", set())),
                ubiquitous=rule.get("ubiquitous", False),
            )
            for rule in self.relations_rules
        ]

        for rule in relations_rules:
            rule.check()
        return relations_rules
