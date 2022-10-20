from collections import defaultdict

import pytest

from jujulint.checks import hyper_converged


@pytest.mark.parametrize(
    "masakari, input_file_type",
    [
        (True, "juju-status-hyper-converged"),
        (False, "juju-status-hyper-converged"),
        (True, "juju-bundle-parsed-hyper-converged"),
        (False, "juju-bundle-parsed-hyper-converged"),
    ],
)
def test_check_hyper_converged(input_files, masakari, input_file_type):
    """Test hyper_converged models."""
    input_file = input_files[input_file_type]
    expected_result = defaultdict(lambda: defaultdict(set))
    if masakari and "juju-status" in input_file_type:
        expected_result["0"]["0/lxd/0"] = {"ceilometer"}
        expected_result["0"]["0/lxd/1"] = {"heat"}
    elif masakari and "juju-bundle" in input_file_type:
        expected_result["0"]["lxd:0"] = {"ceilometer", "heat"}
    else:
        # remove masakari from input file
        del input_file.applications_data["masakari"]
        del input_file.machines_data["3"]
        input_file.charms = set()
        input_file.map_file()
    assert hyper_converged.check_hyper_converged(input_file) == expected_result
