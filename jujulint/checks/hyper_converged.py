#!/usr/bin/python3
"""Checks if nodes can be Hyper-Converged."""

from collections import defaultdict
from typing import DefaultDict, Union

from jujulint.model_input import JujuBundleFile, JujuStatusFile


# see LP#1990885
def check_hyper_converged(
    input_file: Union[JujuBundleFile, JujuStatusFile],
) -> DefaultDict[str, DefaultDict[str, set]]:
    """Check if other services are collocated with nova/osd with masakari.

    Hyperconvered is nova/osd collocated with openstack services.
    Masakari uses ha-cluster to monitor nodes. If the node is not responsive then the
    node is taken down. This is fine for nova/osd units, but if there are collocated
    with openstack services this can be problematic.


    :param input_file: mapped content of the input file.
    :type input_file: Union[JujuBundleFile, JujuStatusFile]
    :return: Services on lxds that are on nova/osd machines.
    :rtype: DefaultDict[str, DefaultDict[str, set]]
    """
    hyper_converged_warning = defaultdict(lambda: defaultdict(set))
    if "masakari" in input_file.charms:
        nova_machines = input_file.filter_machines_by_charm("nova-compute")
        ods_machines = input_file.filter_machines_by_charm("ceph-osd")
        nova_osd_machines = nova_machines.intersection(ods_machines)
        if nova_osd_machines:
            for machine in nova_osd_machines:
                lxds = input_file.filter_lxd_on_machine(machine)
                for lxd in lxds:
                    apps = input_file.machines_to_apps[lxd]
                    hyper_converged_warning[machine][lxd] = apps
    return hyper_converged_warning
