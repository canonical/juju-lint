#! /usr/bin/env python
# -*- coding: utf-8 -*-
# vim:fenc=utf-8
#
# Copyright © 2020 James Hebden <james.hebden@canonical.com>
#
# Distributed under terms of the GPL license.

"""Test fixtures for juju-lint tool."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import mock
import pytest

from jujulint import cloud  # noqa: E402
from jujulint.model_input import JujuBundleFile, JujuStatusFile

# bring in top level library to path
test_path = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, test_path + "/../")


@pytest.fixture
def mocked_pkg_resources(monkeypatch):
    """Mock the pkg_resources library."""
    import pkg_resources

    monkeypatch.setattr(pkg_resources, "require", mock.Mock())


@pytest.fixture
def cli_instance(monkeypatch):
    """Provide a test instance of the CLI class."""
    monkeypatch.setattr(sys, "argv", ["juju-lint", "-c", "contrib/canonical-rules.yaml"])

    from jujulint.cli import Cli

    cli = Cli()

    return cli


@pytest.fixture
def utils():
    """Provide a test instance of the CLI class."""
    from jujulint import util

    return util


@pytest.fixture
def parser(monkeypatch):
    """Mock the configuration parser."""
    monkeypatch.setattr("jujulint.config.ArgumentParser", mock.Mock())


@pytest.fixture
def linter(parser):
    """Provide test fixture for the linter class."""
    from jujulint.lint import Linter

    rules = {
        "known charms": ["ntp", "ubuntu"],
        "operations mandatory": ["ubuntu"],
        "subordinates": {
            "ntp": {"where": "all"},
        },
    }

    linter = Linter("mockcloud", "mockrules.yaml")
    linter.lint_rules = rules
    linter.collect_errors = True

    return linter


@pytest.fixture
def cloud_instance():
    """Provide a Cloud instance to test."""
    from jujulint.cloud import Cloud

    rules = {
        "known charms": ["nrpe", "ubuntu", "nagios"],
        "operations mandatory": ["nagios"],
    }
    cloud = Cloud(name="test_cloud", lint_rules=rules)
    # set initial cloud state
    cloud.cloud_state = {"my_controller": {"models": {"my_model_1": {}, "my_model_2": {}}}}
    cloud.logger = MagicMock()
    return cloud


@pytest.fixture
def juju_status():
    """Provide a base juju status for testing."""
    return {
        "applications": {
            "ubuntu": {
                "application-status": {"current": "active"},
                "charm": "cs:ubuntu-18",
                "charm-name": "ubuntu",
                "relations": {"juju-info": ["ntp"]},
                "endpoint-bindings": {
                    "": "external-space",
                    "certificates": "external-space",
                },
                "units": {
                    "ubuntu/0": {
                        "juju-status": {"current": "idle"},
                        "machine": "0",
                        "subordinates": {
                            "ntp/0": {
                                "juju-status": {"current": "idle"},
                                "workload-status": {"current": "active"},
                            }
                        },
                        "workload-status": {"current": "active"},
                    }
                },
            },
            "ntp": {
                "application-status": {"current": "active"},
                "charm": "cs:ntp-47",
                "charm-name": "ntp",
                "relations": {"juju-info": ["ubuntu"]},
                "subordinate-to": ["ubuntu"],
                "endpoint-bindings": {
                    "": "external-space",
                    "certificates": "external-space",
                },
            },
        },
        "machines": {
            "0": {
                "hardware": "availability-zone=rack-1",
                "juju-status": {"current": "started"},
                "machine-status": {"current": "running"},
                "modification-status": {"current": "applied"},
            },
            "1": {
                "hardware": "availability-zone=rack-2",
                "juju-status": {"current": "started"},
                "machine-status": {"current": "running"},
            },
            "2": {
                "hardware": "availability-zone=rack-3",
                "juju-status": {"current": "started"},
                "machine-status": {"current": "running"},
            },
        },
    }


@pytest.fixture
def juju_export_bundle():
    """Simulate a cloud with one controller and two bundles.

    my_model_1 nrpe offers the monitors endpoint
    my_model_2 nagios consumes the monitors endpoint from my_model_1
    """
    return {
        "my_model_1": [
            {
                "series": "focal",
                "saas": {"remote-2290e64ea1ac41858eb06a69b6a9d8cc": {}},
                "applications": {
                    "nrpe": {"charm": "nrpe", "channel": "stable", "revision": 86},
                    "ubuntu": {
                        "charm": "ubuntu",
                        "channel": "stable",
                        "revision": 19,
                        "num_units": 1,
                        "to": ["0"],
                        "constraints": "arch=amd64",
                    },
                },
                "machines": {"0": {"constraints": "arch=amd64"}},
                "relations": [
                    ["nrpe:general-info", "ubuntu:juju-info"],
                    [
                        "nrpe:monitors",
                        "remote-2290e64ea1ac41858eb06a69b6a9d8cc:monitors",
                    ],
                ],
            },
            {
                "applications": {
                    "nrpe": {
                        "offers": {
                            "nrpe": {
                                "endpoints": ["monitors"],
                                "acl": {"admin": "admin"},
                            }
                        }
                    }
                }
            },
        ],
        "my_model_2": [
            {
                "series": "bionic",
                "saas": {"nrpe": {"url": "my_controller:admin/my_model_1.nrpe"}},
                "applications": {
                    "nagios": {
                        "charm": "nagios",
                        "channel": "stable",
                        "revision": 49,
                        "num_units": 1,
                        "to": ["0"],
                        "constraints": "arch=amd64",
                    }
                },
                "machines": {"0": {"constraints": "arch=amd64"}},
                "relations": [["nagios:monitors", "nrpe:monitors"]],
            }
        ],
    }


@pytest.fixture()
def patch_cloud_init(mocker):
    """Patch objects needed in Cloud.__init__() method."""
    mocker.patch.object(cloud, "Logger")
    mocker.patch.object(cloud, "Connection")
    mocker.patch.object(cloud.socket, "getfqdn", return_value="localhost")


@pytest.fixture
def rules_files():
    """Get all standard rules files that comes with the snap."""
    return [str(rule.resolve()) for rule in Path("./contrib").iterdir() if rule.is_file()]


@pytest.fixture
def input_files(
    parsed_yaml_status,
    parsed_yaml_status_juju34,
    parsed_yaml_bundle,
    parsed_hyper_converged_yaml_status,
    parsed_hyper_converged_yaml_bundle,
):
    return {
        "juju-status": JujuStatusFile(
            applications_data=parsed_yaml_status["applications"],
            machines_data=parsed_yaml_status["machines"],
        ),
        "juju-status-34": JujuStatusFile(
            applications_data=parsed_yaml_status_juju34["applications"],
            machines_data=parsed_yaml_status_juju34["machines"],
        ),
        "juju-status-hyper-converged": JujuStatusFile(
            applications_data=parsed_hyper_converged_yaml_status["applications"],
            machines_data=parsed_hyper_converged_yaml_status["machines"],
        ),
        "juju-bundle": JujuBundleFile(
            applications_data=parsed_yaml_bundle["applications"],
            machines_data=parsed_yaml_bundle["machines"],
            relations_data=parsed_yaml_bundle["relations"],
        ),
        "juju-bundle-parsed-hyper-converged": JujuBundleFile(
            applications_data=parsed_hyper_converged_yaml_bundle["applications"],
            machines_data=parsed_hyper_converged_yaml_bundle["machines"],
            relations_data=parsed_hyper_converged_yaml_bundle["relations"],
        ),
    }


@pytest.fixture
def parsed_yaml_status():
    """Representation of juju status input to test relations checks."""
    return {
        "applications": {
            "nrpe-container": {
                "charm": "cs:nrpe-61",
                "charm-name": "nrpe",
                "relations": {
                    "nrpe-external-master": [
                        "keystone",
                    ],
                },
                "endpoint-bindings": {
                    "general-info": "",
                    "local-monitors": "",
                    "monitors": "oam-space",
                    "nrpe": "",
                    "nrpe-external-master": "",
                },
                "subordinate-to": ["keystone"],
            },
            "nrpe-host": {
                "charm": "cs:nrpe-67",
                "charm-name": "nrpe",
                "relations": {
                    "nrpe-external-master": [
                        "elasticsearch",
                    ],
                    "general-info": ["ubuntu"],
                },
                "endpoint-bindings": {
                    "general-info": "",
                    "local-monitors": "",
                    "monitors": "oam-space",
                    "nrpe": "",
                    "nrpe-external-master": "",
                },
                "subordinate-to": ["elasticsearch", "ubuntu"],
            },
            "ubuntu": {
                "application-status": {"current": "active"},
                "charm": "cs:ubuntu-18",
                "charm-name": "ubuntu",
                "relations": {"juju-info": ["nrpe-host"]},
                "endpoint-bindings": {
                    "": "external-space",
                    "certificates": "external-space",
                },
                "units": {
                    "ubuntu/0": {
                        "machine": "1",
                        "workload-status": {"current": "active"},
                        "subordinates": {
                            "nrpe-host/0": {
                                "workload-status": {
                                    "current": "active",
                                }
                            }
                        },
                    }
                },
            },
            "keystone": {
                "charm": "cs:keystone-309",
                "charm-name": "keystone",
                "relations": {
                    "nrpe-external-master": ["nrpe-container"],
                },
                "endpoint-bindings": {
                    "": "oam-space",
                    "admin": "external-space",
                    "certificates": "oam-space",
                    "cluster": "oam-space",
                    "domain-backend": "oam-space",
                    "ha": "oam-space",
                    "identity-admin": "oam-space",
                    "identity-credentials": "oam-space",
                    "identity-notifications": "oam-space",
                    "identity-service": "oam-space",
                    "internal": "internal-space",
                    "keystone-fid-service-provider": "oam-space",
                    "keystone-middleware": "oam-space",
                    "nrpe-external-master": "oam-space",
                    "public": "external-space",
                    "shared-db": "internal-space",
                    "websso-trusted-dashboard": "oam-space",
                },
                "units": {
                    "keystone/0": {
                        "machine": "1/lxd/0",
                        "subordinates": {
                            "nrpe-container/0": {
                                "workload-status": {
                                    "current": "active",
                                }
                            }
                        },
                    }
                },
            },
            "elasticsearch": {
                "charm": "cs:elasticsearch-39",
                "charm-name": "elasticsearch",
                "relations": {
                    "nrpe-external-master": ["nrpe-host"],
                },
                "endpoint-bindings": {
                    "": "oam-space",
                    "client": "oam-space",
                    "data": "oam-space",
                    "logs": "oam-space",
                    "nrpe-external-master": "oam-space",
                    "peer": "oam-space",
                },
                "units": {
                    "elasticsearch/0": {
                        "machine": "0",
                        "subordinates": {
                            "nrpe-host/0": {
                                "workload-status": {
                                    "current": "active",
                                }
                            }
                        },
                    }
                },
            },
        },
        "machines": {
            "0": {
                "series": "focal",
            },
            "1": {
                "series": "focal",
                "containers": {
                    "1/lxd/0": {
                        "series": "focal",
                    }
                },
            },
        },
    }


@pytest.fixture
def parsed_yaml_status_juju34():
    """Representation of juju 3.4 status input to test relations checks."""
    return {
        "applications": {
            "nrpe-container": {
                "charm": "cs:nrpe-61",
                "charm-name": "nrpe",
                "relations": {
                    "nrpe-external-master": [
                        {
                            "related-application": "keystone",
                            "interface": "nrpe-external-master",
                            "scope": "container",
                        },
                    ],
                },
                "endpoint-bindings": {
                    "general-info": "",
                    "local-monitors": "",
                    "monitors": "oam-space",
                    "nrpe": "",
                    "nrpe-external-master": "",
                },
                "subordinate-to": ["keystone"],
            },
            "nrpe-host": {
                "charm": "cs:nrpe-67",
                "charm-name": "nrpe",
                "relations": {
                    "nrpe-external-master": [
                        {
                            "related-application": "elasticsearch",
                            "interface": "nrpe-external-master",
                            "scope": "container",
                        },
                    ],
                    "general-info": ["ubuntu"],
                },
                "endpoint-bindings": {
                    "general-info": "",
                    "local-monitors": "",
                    "monitors": "oam-space",
                    "nrpe": "",
                    "nrpe-external-master": "",
                },
                "subordinate-to": ["elasticsearch", "ubuntu"],
            },
            "ubuntu": {
                "application-status": {"current": "active"},
                "charm": "cs:ubuntu-18",
                "charm-name": "ubuntu",
                "relations": {
                    "juju-info": [
                        {
                            "related-application": "nrpe-host",
                            "interface": "juju-info",
                            "scope": "container",
                        },
                    ]
                },
                "endpoint-bindings": {
                    "": "external-space",
                    "certificates": "external-space",
                },
                "units": {
                    "ubuntu/0": {
                        "machine": "1",
                        "workload-status": {"current": "active"},
                        "subordinates": {
                            "nrpe-host/0": {
                                "workload-status": {
                                    "current": "active",
                                }
                            }
                        },
                    }
                },
            },
            "keystone": {
                "charm": "cs:keystone-309",
                "charm-name": "keystone",
                "relations": {
                    "nrpe-external-master": [
                        {
                            "related-application": "nrpe-container",
                            "interface": "nrpe-external-master",
                            "scope": "container",
                        },
                    ],
                },
                "endpoint-bindings": {
                    "": "oam-space",
                    "admin": "external-space",
                    "certificates": "oam-space",
                    "cluster": "oam-space",
                    "domain-backend": "oam-space",
                    "ha": "oam-space",
                    "identity-admin": "oam-space",
                    "identity-credentials": "oam-space",
                    "identity-notifications": "oam-space",
                    "identity-service": "oam-space",
                    "internal": "internal-space",
                    "keystone-fid-service-provider": "oam-space",
                    "keystone-middleware": "oam-space",
                    "nrpe-external-master": "oam-space",
                    "public": "external-space",
                    "shared-db": "internal-space",
                    "websso-trusted-dashboard": "oam-space",
                },
                "units": {
                    "keystone/0": {
                        "machine": "1/lxd/0",
                        "subordinates": {
                            "nrpe-container/0": {
                                "workload-status": {
                                    "current": "active",
                                }
                            }
                        },
                    }
                },
            },
            "elasticsearch": {
                "charm": "cs:elasticsearch-39",
                "charm-name": "elasticsearch",
                "relations": {
                    "nrpe-external-master": [
                        {
                            "related-application": "nrpe-host",
                            "interface": "nrpe-external-master",
                            "scope": "container",
                        },
                    ],
                },
                "endpoint-bindings": {
                    "": "oam-space",
                    "client": "oam-space",
                    "data": "oam-space",
                    "logs": "oam-space",
                    "nrpe-external-master": "oam-space",
                    "peer": "oam-space",
                },
                "units": {
                    "elasticsearch/0": {
                        "machine": "0",
                        "subordinates": {
                            "nrpe-host/0": {
                                "workload-status": {
                                    "current": "active",
                                }
                            }
                        },
                    }
                },
            },
        },
        "machines": {
            "0": {
                "series": "focal",
            },
            "1": {
                "series": "focal",
                "containers": {
                    "1/lxd/0": {
                        "series": "focal",
                    }
                },
            },
        },
    }


@pytest.fixture
def parsed_yaml_bundle():
    """Representation of juju bundle input to test relations checks."""
    return {
        "series": "focal",
        "applications": {
            "elasticsearch": {
                "bindings": {
                    "nrpe-external-master": "internal-space",
                },
                "charm": "elasticsearch",
                "channel": "stable",
                "revision": 59,
                "num_units": 1,
                "to": ["0"],
                "constraints": "arch=amd64 mem=4096",
            },
            "keystone": {
                "bindings": {
                    "nrpe-external-master": "internal-space",
                    "public": "internal-space",
                },
                "charm": "keystone",
                "channel": "stable",
                "revision": 539,
                "resources": {"policyd-override": 0},
                "num_units": 1,
                "to": ["lxd:1"],
                "constraints": "arch=amd64",
            },
            "nrpe-container": {
                "bindings": {
                    "nrpe-external-master": "internal-space",
                    "local-monitors": "",
                },
                "charm": "nrpe",
                "channel": "stable",
                "revision": 94,
            },
            "nrpe-host": {
                "bindings": {
                    "nrpe-external-master": "internal-space",
                    "local-monitors": "",
                },
                "charm": "nrpe",
                "channel": "stable",
                "revision": 94,
            },
            "ubuntu": {
                "bindings": {"": "internal-space", "certificates": "external-space"},
                "charm": "ubuntu",
                "channel": "stable",
                "revision": 21,
                "num_units": 1,
                "to": ["1"],
                "options": {"hostname": ""},
                "constraints": "arch=amd64 mem=4096",
            },
        },
        "machines": {
            "0": {"constraints": "arch=amd64 mem=4096"},
            "1": {"constraints": "arch=amd64 mem=4096"},
        },
        "relations": [
            [
                "nrpe-container:nrpe-external-master",
                "keystone:nrpe-external-master",
            ],
            ["nrpe-host:general-info", "ubuntu:juju-info"],
            [
                "elasticsearch:nrpe-external-master",
                "nrpe-host:nrpe-external-master",
            ],
        ],
    }


@pytest.fixture
def parsed_hyper_converged_yaml_status():
    """Representation of a hyper converged model with masakari."""
    return {
        "machines": {
            "0": {
                "juju-status": {"current": "started"},
                "machine-status": {"current": "running"},
                "modification-status": {
                    "current": "idle",
                },
                "containers": {
                    "0/lxd/0": {
                        "juju-status": {"current": "started"},
                        "machine-status": {"current": "running"},
                        "modification-status": {"current": "applied"},
                        "constraints": "arch=amd64 spaces=",
                        "hardware": "availability-zone=nova",
                    },
                    "0/lxd/1": {
                        "juju-status": {"current": "started"},
                        "machine-status": {"current": "running"},
                        "modification-status": {"current": "applied"},
                        "constraints": "arch=amd64 spaces=",
                        "hardware": "availability-zone=nova",
                    },
                },
                "constraints": "arch=amd64 mem=4096M",
                "hardware": "arch=amd64 cores=2 mem=4096M root-disk=40960M availability-zone=nova",
            },
            "1": {
                "juju-status": {"current": "started"},
                "machine-status": {"current": "running"},
                "modification-status": {"current": "idle"},
                "constraints": "arch=amd64 mem=4096M",
                "hardware": "arch=amd64 cores=2 mem=4096M root-disk=40960M availability-zone=nova",
            },
            "2": {
                "juju-status": {"current": "started"},
                "machine-status": {"current": "running"},
                "modification-status": {"current": "idle"},
                "constraints": "arch=amd64 mem=4096M",
                "hardware": "arch=amd64 cores=2 mem=4096M root-disk=40960M availability-zone=nova",
            },
            "3": {
                "juju-status": {"current": "started"},
                "machine-status": {"current": "running"},
                "modification-status": {"current": "idle"},
                "constraints": "arch=amd64",
                "hardware": "arch=amd64 cores=1 mem=2048M root-disk=20480M availability-zone=nova",
            },
        },
        "applications": {
            "ceilometer": {
                "charm": "ceilometer",
                "charm-name": "ceilometer",
                "application-status": {"current": "active"},
                "relations": {"cluster": ["ceilometer"]},
                "units": {
                    "ceilometer/0": {
                        "workload-status": {"current": "active"},
                        "juju-status": {"current": "idle"},
                        "machine": "0/lxd/0",
                    }
                },
                "endpoint-bindings": {
                    "": "alpha",
                    "admin": "alpha",
                    "amqp": "alpha",
                    "amqp-listener": "alpha",
                    "ceilometer-service": "alpha",
                    "certificates": "alpha",
                    "cluster": "alpha",
                    "event-service": "alpha",
                    "ha": "alpha",
                    "identity-credentials": "alpha",
                    "identity-notifications": "alpha",
                    "identity-service": "alpha",
                    "internal": "alpha",
                    "metric-service": "alpha",
                    "nrpe-external-master": "alpha",
                    "public": "alpha",
                    "shared-db": "alpha",
                },
            },
            "ceph-mon": {
                "charm": "ceph-mon",
                "charm-name": "ceph-mon",
                "application-status": {"current": "active"},
                "relations": {
                    "client": ["nova-compute"],
                    "mon": ["ceph-mon"],
                    "osd": ["ceph-osd"],
                },
                "units": {
                    "ceph-mon/0": {
                        "workload-status": {"current": "idle"},
                        "juju-status": {"current": "idle"},
                        "machine": "0",
                    },
                    "ceph-mon/1": {
                        "workload-status": {"current": "idle"},
                        "juju-status": {"current": "idle"},
                        "machine": "1",
                    },
                    "ceph-mon/2": {
                        "workload-status": {"current": "idle"},
                        "juju-status": {"current": "idle"},
                        "machine": "2",
                    },
                },
                "endpoint-bindings": {
                    "": "alpha",
                    "admin": "alpha",
                    "bootstrap-source": "alpha",
                    "client": "alpha",
                    "cluster": "alpha",
                    "dashboard": "alpha",
                    "mds": "alpha",
                    "mon": "alpha",
                    "nrpe-external-master": "alpha",
                    "osd": "alpha",
                    "prometheus": "alpha",
                    "public": "alpha",
                    "radosgw": "alpha",
                    "rbd-mirror": "alpha",
                },
            },
            "ceph-osd": {
                "charm": "ceph-osd",
                "charm-name": "ceph-osd",
                "application-status": {"current": "active"},
                "relations": {"mon": ["ceph-mon"]},
                "units": {
                    "ceph-osd/0": {
                        "workload-status": {"current": "idle"},
                        "juju-status": {"current": "idle"},
                        "machine": "0",
                    },
                    "ceph-osd/1": {
                        "workload-status": {"current": "idle"},
                        "juju-status": {"current": "idle"},
                        "machine": "1",
                    },
                    "ceph-osd/2": {
                        "workload-status": {"current": "idle"},
                        "juju-status": {"current": "idle"},
                        "machine": "2",
                    },
                },
                "endpoint-bindings": {
                    "": "alpha",
                    "cluster": "alpha",
                    "mon": "alpha",
                    "nrpe-external-master": "alpha",
                    "public": "alpha",
                    "secrets-storage": "alpha",
                },
            },
            "heat": {
                "charm": "heat",
                "series": "focal",
                "charm-name": "heat",
                "application-status": {"current": "active"},
                "relations": {"cluster": ["heat"]},
                "units": {
                    "heat/0": {
                        "workload-status": {"current": "idle"},
                        "juju-status": {"current": "idle"},
                        "machine": "0/lxd/1",
                    }
                },
                "endpoint-bindings": {
                    "": "alpha",
                    "admin": "alpha",
                    "amqp": "alpha",
                    "certificates": "alpha",
                    "cluster": "alpha",
                    "ha": "alpha",
                    "heat-plugin-subordinate": "alpha",
                    "identity-service": "alpha",
                    "internal": "alpha",
                    "nrpe-external-master": "alpha",
                    "public": "alpha",
                    "shared-db": "alpha",
                },
            },
            "masakari": {
                "charm": "masakari",
                "charm-name": "masakari",
                "application-status": {"current": "active"},
                "relations": {"cluster": ["masakari"]},
                "units": {
                    "masakari/0": {
                        "workload-status": {"current": "idle"},
                        "juju-status": {"current": "idle"},
                        "machine": "3",
                    }
                },
                "endpoint-bindings": {
                    "": "alpha",
                    "admin": "alpha",
                    "amqp": "alpha",
                    "certificates": "alpha",
                    "cluster": "alpha",
                    "ha": "alpha",
                    "identity-service": "alpha",
                    "internal": "alpha",
                    "public": "alpha",
                    "shared-db": "alpha",
                },
            },
            "nova-compute": {
                "charm": "nova-compute",
                "charm-name": "nova-compute",
                "application-status": {"current": "active"},
                "relations": {"ceph": ["ceph-mon"], "compute-peer": ["nova-compute"]},
                "units": {
                    "nova-compute/0": {
                        "workload-status": {"current": "idle"},
                        "juju-status": {"current": "idle"},
                        "machine": "0",
                    },
                    "nova-compute/1": {
                        "workload-status": {"current": "idle"},
                        "juju-status": {"current": "idle"},
                        "machine": "1",
                    },
                    "nova-compute/2": {
                        "workload-status": {"current": "idle"},
                        "juju-status": {"current": "idle"},
                        "machine": "2",
                    },
                },
                "endpoint-bindings": {
                    "": "alpha",
                    "amqp": "alpha",
                    "ceph": "alpha",
                    "ceph-access": "alpha",
                    "cloud-compute": "alpha",
                    "cloud-credentials": "alpha",
                    "compute-peer": "alpha",
                    "ephemeral-backend": "alpha",
                    "image-service": "alpha",
                    "internal": "alpha",
                    "ironic-api": "alpha",
                    "lxd": "alpha",
                    "migration": "alpha",
                    "neutron-plugin": "alpha",
                    "nova-ceilometer": "alpha",
                    "nrpe-external-master": "alpha",
                    "secrets-storage": "alpha",
                },
            },
        },
    }


@pytest.fixture
def parsed_hyper_converged_yaml_bundle():
    """Representation of a hyper converged model with masakari."""
    return {
        "series": "focal",
        "applications": {
            "ceilometer": {
                "charm": "ceilometer",
                "num_units": 1,
                "to": ["lxd:0"],
                "constraints": "arch=amd64",
            },
            "ceph-mon": {
                "charm": "ceph-mon",
                "num_units": 3,
                "to": ["0", "1", "2"],
                "constraints": "arch=amd64",
            },
            "ceph-osd": {
                "charm": "ceph-osd",
                "num_units": 3,
                "to": ["0", "1", "2"],
                "constraints": "arch=amd64 mem=4096",
                "storage": {
                    "bluestore-db": "loop,0,1024",
                    "bluestore-wal": "loop,0,1024",
                    "osd-devices": "loop,0,1024",
                    "osd-journals": "loop,0,1024",
                },
            },
            "heat": {
                "charm": "heat",
                "resources": {"policyd-override": 0},
                "num_units": 1,
                "to": ["lxd:0"],
                "constraints": "arch=amd64",
            },
            "masakari": {
                "charm": "masakari",
                "num_units": 1,
                "to": ["3"],
                "constraints": "arch=amd64",
            },
            "nova-compute": {
                "charm": "nova-compute",
                "num_units": 3,
                "to": ["0", "1", "2"],
                "constraints": "arch=amd64",
                "storage": {"ephemeral-device": "loop,0,10240"},
            },
        },
        "machines": {
            "0": {"constraints": "arch=amd64 mem=4096"},
            "1": {"constraints": "arch=amd64 mem=4096"},
            "2": {"constraints": "arch=amd64 mem=4096"},
            "3": {"constraints": "arch=amd64"},
        },
        "relations": [
            ["ceph-mon:client", "nova-compute:ceph"],
            ["ceph-mon:osd", "ceph-osd:mon"],
        ],
    }
