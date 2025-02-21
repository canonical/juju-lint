#! /usr/bin/env python3
from __future__ import annotations  # type annotations are lazy-evaluated

"""Treat input formats to lint."""

from collections import defaultdict
from dataclasses import dataclass, field
from functools import partialmethod
from logging import getLogger
from typing import Any, Dict, List, Set, Tuple, Union

from jujulint.util import extract_charm_name

LOGGER = getLogger(__name__)


@dataclass
class BaseFile:
    """BaseFile to define common properties and methods."""

    applications_data: Dict
    machines_data: Dict
    charms: Set = field(default_factory=set)
    machines: Set = field(default_factory=set)
    app_to_charm: Dict = field(default_factory=dict)
    charm_to_app: defaultdict[set] = field(default_factory=lambda: defaultdict(set))
    apps_to_machines: defaultdict[set] = field(default_factory=lambda: defaultdict(set))
    machines_to_apps: defaultdict[set] = field(default_factory=lambda: defaultdict(set))

    def __post_init__(self):
        """Dunder method to map file after instantiating."""
        self.map_file()

    @property
    def applications(self) -> Set:
        """Applications present in the file."""
        return set(self.applications_data.keys())

    @staticmethod
    def split_relation(relation: List[List[str]]) -> Tuple[str, str]:
        """Split relations into apps and endpoints.

        :param relation: Relation having the following format:
            [[<app_1>:<endpoint_1>], [<app_2>:<endpoint_2>]]
        :type relation: List[List[str]]
        :return: Relation and endpoint.
        :rtype: Tuple[str, str]
        """
        return *relation[0].split(":"), *relation[1].split(":")

    def map_file(self) -> None:
        """Process the input file."""
        for app in self.applications:
            if "charm" in self.applications_data[app]:
                charm_name = extract_charm_name(self.applications_data[app]["charm"])
                self.charms.add(charm_name)
                self.app_to_charm[app] = charm_name
                self.charm_to_app[charm_name].add(app)
                self.map_machines()
                self.map_apps_to_machines()

    def check_app_endpoint_existence(
        self, app_endpoint: str, charm: str, endpoints_key: str
    ) -> Tuple[str, str]:
        """Check if app and endpoint exist on the object to lint.

        :param app_endpoint: app and endpoint separated by ":" with the following format:
            <app>:<endpoint>. When app is equal to "*", it's considered as ALL possible apps
        :type app_endpoint: str
        :param charm: charm to not check itself.
        :type charm: str
        :param endpoints_key: dictionary key to access endpoints.
        :type endpoints_key: str
        :return: application and endpoint
        :rtype: Tuple[str, str]
        """
        app, endpoint = app_endpoint.split(":")
        # app == "*" means all apps
        # a charm from relation rule can have different app names.
        if app != "*" and app != charm:
            if app not in self.applications:
                LOGGER.warning(f"{app} not found on applications.")
                return "", ""

            # NOTE(gabrielcocenza) it's not always that a bundle will contain all endpoints under "bindings".  # noqa: W505
            # See LP#1949883 and LP#1990017
            # juju-info is represented by "" on endpoint-bindings
            if endpoint != "juju-info" and endpoint not in self.applications_data[app].get(
                endpoints_key, {}
            ):
                LOGGER.warning(f"endpoint: {endpoint} not found on {app}")
                return "", ""
        return app, endpoint

    def filter_by_app_and_endpoint(
        self, charm: str, app: str, endpoint: str, endpoints_key: str
    ) -> Set:
        """Filter applications by the presence of an endpoint.

        :param charm: Charm to not filter itself.
        :type charm: str
        :param app: Application to be filtered. When app is equal to "*", filters ALL apps
            that have the endpoint passed.
        :type app: str
        :param endpoint: Endpoint of an application.
        :type endpoint: str
        :param endpoints_key: dictionary key to access endpoint.
        :type endpoints_key: str
        :return:  Applications that matches with the endpoint passed.
        :rtype: Set
        """
        # when app == "*", filters all apps that have the endpoint passed.
        if app == "*":
            #  remove all possible app names to not check itself.
            apps_to_check = self.applications - self.charm_to_app[charm]
            return {
                app
                for app in apps_to_check
                if endpoint in self.applications_data.get(app, {}).get(endpoints_key, {})
            }
        return (
            set([app])
            if endpoint in self.applications_data.get(app, {}).get(endpoints_key, {})
            else set()
        )

    def filter_machines_by_charm(self, charm: str) -> Set:
        """Filter machines that has a specific charm.

        :param charm: Charm name.
        :type charm: str
        :return: Machines that contains the charm.
        :rtype: Set
        """
        charm_machines = set()
        charm_apps = self.charm_to_app[charm]
        for charm_app in charm_apps:
            charm_machines.update(self.apps_to_machines[charm_app])
        return charm_machines

    def map_machines(self):
        """Map machines method to be implemented.

        :raises NotImplementedError: Raise if not implemented on child classes.
        """
        raise NotImplementedError(f"{self.__class__.__name__} missing: map_machines")

    def map_apps_to_machines(self):
        """Map apps to machines method to be implemented.

        :raises NotImplementedError: Raise if not implemented on child classes.
        """
        raise NotImplementedError(f"{self.__class__.__name__} missing: map_apps_to_machines")

    def filter_by_relation(self, apps: Set, endpoint: str) -> Set:
        """Filter apps by relation to be implemented.

        :raises NotImplementedError: Raise if not implemented on child classes.
        """
        raise NotImplementedError(f"{self.__class__.__name__} missing: filter_by_relation")

    def sorted_machines(self, machine: str):
        """Sort machines.

        :param machine: machine id.
        :type machine: str
        :raises NotImplementedError: Raise if not implemented on child classes.
        """
        raise NotImplementedError(f"{self.__class__.__name__} missing: sorted_machines")

    def filter_lxd_on_machine(self, machine: str):
        """Lxd containers on a machine.

        :param machine: machine id.
        :type machine: str
        :raises NotImplementedError: Raise if not implemented on child classes.
        """
        raise NotImplementedError(f"{self.__class__.__name__} missing: filter_lxd_on_machine")


@dataclass
class JujuStatusFile(BaseFile):
    """Juju status file input representation."""

    def map_machines(self) -> None:
        """Map machines passed on the file."""
        self.machines.update(self.machines_data.keys())
        for machine in self.machines_data:
            self.machines.update(self.machines_data[machine].get("containers", []))

    def map_apps_to_machines(self) -> None:
        """Map applications on machines."""
        for app in self.applications_data:
            units = self.applications_data[app].get("units", {})
            for unit in units:
                machine = units[unit].get("machine")
                self.apps_to_machines[app].add(machine)
                self.machines_to_apps[machine].add(app)
                subordinates = units[unit].get("subordinates", {})
                for sub in subordinates:
                    sub_name = sub.split("/")[0]
                    self.apps_to_machines[sub_name].add(machine)
                    self.machines_to_apps[machine].add(sub_name)

    @staticmethod
    def sorted_machines(machine: str) -> Tuple[int, str, int]:
        """Sort machines by number and/or containers.

        :param machine: name of the machine
            E.g of expected input: "1", "1/lxd/3"
        :type machine: str
        :return: tuple with sort keys
        :rtype: Tuple[int, str, int]
        """
        # way to be sure that a machine have at least 3 key values to sort
        key_1, key_2, key_3, *_ = machine.split("/") + ["", 0]
        return int(key_1), key_2, int(key_3)

    # overwrite parent method passing "endpoint-bindings" as endpoints_key
    filter_by_app_and_endpoint = partialmethod(
        BaseFile.filter_by_app_and_endpoint, endpoints_key="endpoint-bindings"
    )
    check_app_endpoint_existence = partialmethod(
        BaseFile.check_app_endpoint_existence, endpoints_key="endpoint-bindings"
    )

    def filter_by_relation(self, apps: Set, endpoint: str) -> Set:
        """Filter applications that relate with an endpoint.

        :param apps: Applications to filter relations using the endpoint.
        :type apps: Set
        :param endpoint: endpoint of the applications.
        :type endpoint: str
        :return: Applications that has a relation with the apps using the endpoint.
        :rtype: Set
        """
        apps_related = set()
        for app in apps:
            relations = self.applications_data.get(app, {}).get("relations", {})
            endpoints = relations.get(endpoint, [])
            # since juju 3.4, this is a dict instead of a string,
            # so convert to a string.
            for i in range(len(endpoints)):
                if isinstance(endpoints[i], dict):
                    endpoints[i] = endpoints[i]["related-application"]
            apps_related.update(endpoints)
        return apps_related

    def filter_lxd_on_machine(self, machine: str) -> Set:
        """Lxd containers on a machine.

        :param machine: machine id.
        :type machine: str
        :return: lxd containers in the machine.
        :rtype: Set
        """
        return {
            lxd_machine
            for lxd_machine in self.machines
            if "lxd" in lxd_machine and lxd_machine.split("/")[0] == machine
        }


@dataclass
class JujuBundleFile(BaseFile):
    """Juju bundle file input representation."""

    relations_data: List = field(default_factory=list)

    def map_machines(self) -> None:
        """Map machines passed on the file."""
        self.machines.update(self.machines_data.keys())
        for app in self.applications_data:
            deploy_to_machines = self.applications_data[app].get("to", [])
            # openstack bundles can have corner cases e.g: to: - designate-bind/0
            # in this case the application is deployed where designate-bind/0 is located
            # See https://launchpad.net/bugs/1965256
            machines = [machine for machine in deploy_to_machines if "/" not in machine]
            self.machines.update(machines)

    def map_apps_to_machines(self) -> None:
        """Map applications on machines."""
        for app in self.applications_data:
            machines = self.applications_data[app].get("to", [])
            self.apps_to_machines[app].update(machines)
            for machine in machines:
                self.machines_to_apps[machine].add(app)
        # NOTE(gabrielcocenza) subordinates won't have the 'to' field because
        # they are deployed thru relations.
        subordinates = {
            sub for sub, machines in self.apps_to_machines.items() if machines == set()
        }
        for relation in self.relations_data:
            app_1, _, app_2, _ = self.split_relation(relation)
            # update with the machines of the application that the subordinate charm relate.
            if app_1 in subordinates:
                sub_machines = self.apps_to_machines[app_2]
                self.apps_to_machines[app_1].update(sub_machines)
                for sub_machine in sub_machines:
                    self.machines_to_apps[sub_machine].add(app_1)
            elif app_2 in subordinates:
                sub_machines = self.apps_to_machines[app_1]
                self.apps_to_machines[app_2].update(self.apps_to_machines[app_1])
                for sub_machine in sub_machines:
                    self.machines_to_apps[sub_machine].add(app_2)

    @staticmethod
    def sorted_machines(machine: str) -> Tuple[int, str]:
        """Sort machines by number and/or containers.

        :param machine: name of the machine
            E.g of expected input: "1", "lxd:1"
        :type machine: str
        :return: tuple with sort keys
        :rtype: Tuple[int, str]
        """
        # way to be sure that a machine have at least 2 key values to sort
        key_1, key_2, *_ = machine.split(":") + [""]

        if key_1.isdigit():
            # not container machines comes first.
            return int(key_1), "0"
        # in a container from a bundle, the machine number it's in the end. E.g: lxd:1
        else:
            return int(key_2), key_1

    # overwrite parent method passing "bindings" as endpoints_key
    filter_by_app_and_endpoint = partialmethod(
        BaseFile.filter_by_app_and_endpoint, endpoints_key="bindings"
    )
    check_app_endpoint_existence = partialmethod(
        BaseFile.check_app_endpoint_existence, endpoints_key="bindings"
    )

    def filter_by_relation(self, apps: Set, endpoint: str) -> Set:
        """Filter applications that relate with an endpoint.

        :param apps: Applications to filter relations using the endpoint.
        :type apps: Set
        :param endpoint: endpoint of the applications.
        :type endpoint: str
        :return: Applications that has a relation with the apps using the endpoint.
        :rtype: Set
        """
        apps_related = set()
        for relation in self.relations_data:
            for app in apps:
                app_ep = f"{app}:{endpoint}"
                app_1_ep_1, app_2_ep_2 = relation
                if app_1_ep_1 == app_ep:
                    apps_related.add(app_2_ep_2.split(":")[0])
                elif app_2_ep_2 == app_ep:
                    apps_related.add(app_1_ep_1.split(":")[0])
        return apps_related

    def filter_lxd_on_machine(self, machine: str) -> Set:
        """Lxd containers on a machine.

        :param machine: machine id.
        :type machine: str
        :return: lxd containers in the machine.
        :rtype: Set
        """
        return {
            lxd_machine
            for lxd_machine in self.machines
            if "lxd" in lxd_machine and lxd_machine.split(":")[1] == machine
        }


def input_handler(
    parsed_yaml: Dict[str, Any], applications_key: str
) -> Union[JujuStatusFile, JujuBundleFile]:
    """Input handler to set right methods and fields.

    :param parsed_yaml: input file that came from juju status or bundle.
    :type parsed_yaml: Dict[str, Any]
    :param applications_key: key to access applications or services (Juju v1)
    :type applications_key: str
    :return: Data Class from juju status or bundle.
    :rtype: Union[JujuStatus, JujuBundle]
    """
    # relations key field is present just on bundles
    if applications_key in parsed_yaml:
        if "relations" in parsed_yaml:
            return JujuBundleFile(
                applications_data=parsed_yaml[applications_key],
                machines_data=parsed_yaml["machines"],
                relations_data=parsed_yaml["relations"],
            )
        else:
            return JujuStatusFile(
                applications_data=parsed_yaml[applications_key],
                machines_data=parsed_yaml["machines"],
            )
