"""Tests for OpenStack cloud module."""

from unittest.mock import MagicMock

from jujulint.openstack import Cloud, OpenStack


def test_init():
    """Test Openstack cloud class initiation."""
    cloud = OpenStack(name="foo")
    assert cloud.cloud_type == "openstack"


def test_audit(mocker):
    """Test openstack-specific steps of audit method.

    Note: Currently this method does not do anything different than its
    parent method.
    """
    audit_mock = mocker.patch.object(Cloud, "audit")
    logger_mock = MagicMock()

    name = "foo"
    cloud = OpenStack(name=name)
    cloud.logger = logger_mock
    expected_msg = "[{}] Running OpenStack-specific audit steps.".format(name)
    cloud.audit()

    logger_mock.info.assert_called_once_with(expected_msg)
    audit_mock.assert_called_once()
