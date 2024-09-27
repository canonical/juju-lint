# Contributing

## Overview

This documents explains the processes and practices recommended for contributing enhancements to
this project.

- Generally, before developing enhancements to this project, you should consider [reporting a bug
  ](https://github.com/canonical/juju-lint/issues/) explaining your use case.
- All enhancements require review before being merged. Code review typically examines
  - code quality
  - test coverage
  - documentation
- Please help us out in ensuring easy to review branches by rebasing your pull request branch onto
  the `main` branch. This also avoids merge commits and creates a linear Git commit history.

### Developing

Clone this repository:
```shell
git clone git@github.com:canonical/juju-lint.git
cd juju-lint/
```

After making your changes you can run juju-lint without the need of building and installing the snap by using:

```shell
python3 -m jujulint.cli <PATH_TO_YAML> -c <PATH_TO_RULE_FILE> -l debug
```


### Testing

```shell
tox -e lint          # check code style
tox -e reformat      # reformat the code using black and isort
tox -e unit          # run unit tests
tox -e func          # run functional tests (using the source code package directly)
snapcraft --use-lxd  # build the snap
TEST_SNAP=/path/to/juju-lint.snap tox -e func  # run functional tests (using the built snap)
```

### Functional Tests

`TEST_SNAP=/path/to/juju-lint.snap tox -e func` install the snap locally and run the tests against the installed snap.
Since this action involves installing a snap package, passwordless `sudo` privileges are needed.

## Canonical Contributor Agreement

Canonical welcomes contributions to the juju-lint. Please check out our [contributor agreement](https://ubuntu.com/legal/contributors) if you're interested in contributing to the solution.
