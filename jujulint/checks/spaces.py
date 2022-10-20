#!/usr/bin/python3
"""Checks for space mismatches between relation endpoints."""
from logging import getLogger

LOGGER = getLogger(__name__)


class Relation:
    """Relation object."""

    def __init__(self, endpoint1, endpoint2):
        """Object for representing relations."""
        self.endpoint1 = endpoint1
        self.endpoint2 = endpoint2

    def __str__(self):
        """Stringify the object."""
        return "Relation({} - {})".format(self.endpoint1, self.endpoint2)

    def __eq__(self, other):
        """Compare relations.

        While Juju does define separate provider and requirer roles, we'll ignore
        those here.
        """
        return {self.endpoint1, self.endpoint2} == {other.endpoint1, other.endpoint2}

    @property
    def endpoints(self):
        """Return list of endpoints."""
        return [self.endpoint1, self.endpoint2]


class SpaceMismatch:
    """Object for representing relation space mismatches."""

    def __init__(self, endpoint1, space1, endpoint2, space2):
        """Create the object."""
        if endpoint2 < endpoint1:
            # Let's keep things lexicographically ordered
            endpoint1, endpoint2 = endpoint2, endpoint1
            space1, space2 = space2, space1
        self.endpoint1 = endpoint1
        self.endpoint2 = endpoint2
        self.space1 = space1
        self.space2 = space2

    def __str__(self):
        """Stringify the object."""
        return "SpaceMismatch({} (space {}) != {} (space {}))".format(
            self.endpoint1, self.space1, self.endpoint2, self.space2
        )

    @property
    def relation(self):
        """Return a relation object based upon application endpoints."""
        return Relation(self.endpoint1, self.endpoint2)

    def get_charm_relation(self, app_to_charm_map):
        """Return a relation object, mapping applications to charms."""
        app1, endpoint1 = self.endpoint1.split(":")
        app2, endpoint2 = self.endpoint2.split(":")
        charm1 = app_to_charm_map.get(app1, "")
        charm2 = app_to_charm_map.get(app2, "")
        return Relation(":".join([charm1, endpoint1]), ":".join([charm2, endpoint2]))


def find_space_mismatches(parsed_yaml, debug=False):
    """Enumerate relations and detect space mismatches.

    Returns a list of objects representing the mismatches.

    """
    application_list = get_juju_applications(parsed_yaml)
    app_spaces = get_application_spaces(application_list, parsed_yaml)

    if debug:
        print("APP_SPACES")
        for app, map in app_spaces.items():
            print(app)
            for key, value in map.items():
                print("    " + key + " " + value)
        print("\n")

    relations_list = get_application_relations(parsed_yaml)

    if debug:
        print("APP_RELATIONS")
        for relation in relations_list:
            print(relation)
        print("\n")

    mismatches = []

    for relation in relations_list:
        space1 = get_relation_space(relation.endpoint1, app_spaces)
        space2 = get_relation_space(relation.endpoint2, app_spaces)
        if space1 != space2 and all([space1 != "XModel", space2 != "XModel"]):
            mismatch = SpaceMismatch(
                relation.endpoint1, space1, relation.endpoint2, space2
            )
            mismatches.append(mismatch)

    if debug:
        print("\nHere are the mismatched relations\n")
        for mismatch in mismatches:
            print("Mismatch:", mismatch)
    return mismatches


def get_juju_applications(parsed_yaml):
    """Return a list of applications in the bundle."""
    return [name for name in parsed_yaml["applications"]]


def get_application_spaces(application_list, parsed_yaml):
    """Return a dictionary with app.binding=space mappings."""
    app_spaces = {}
    for app in application_list:
        bindings = parsed_yaml["applications"][app].get("bindings", {})
        app_spaces.setdefault(app, {})
        if not bindings:
            # this probably means that is a single space binding. See LP#1949883
            LOGGER.warning("Application %s is missing explicit bindings", app)
            LOGGER.warning("Setting default binding of '%s' to alpha", app)
            app_spaces[app][""] = "alpha"
            continue
        if not bindings.get(""):
            LOGGER.warning(
                "Application %s does not define explicit default binding", app
            )
        for name, value in bindings.items():
            app_spaces[app][name] = value
    return app_spaces


def get_application_relations(parsed_yaml):
    """Return a list of relations extracted from the bundle."""
    relation_list = []
    for provider, requirer in parsed_yaml["relations"]:
        relation = Relation(provider, requirer)
        relation_list.append(relation)
    return relation_list


def get_relation_space(endpoint, app_spaces):
    """Get space for specified app and service."""
    app, service = endpoint.split(":")
    if app in app_spaces:
        if service not in app_spaces[app]:
            return app_spaces[app][""]
        else:
            return app_spaces[app][service]
    else:
        LOGGER.warning(
            "Multi-model is not supported yet. Please check if '%s' is from another model",
            app,
        )
        return "XModel"
