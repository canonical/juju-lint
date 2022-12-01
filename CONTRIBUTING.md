# Contributing

## Overview

This documents explains the processes and practices recommended for contributing enhancements to
this project.

- Generally, before developing enhancements to this project, you should consider [report a bug
  ](https://bugs.launchpad.net/juju-lint) explaining your use case.
- All enhancements require review before being merged. Code review typically examines
  - code quality
  - test coverage
  - documentation
- Please help us out in ensuring easy to review branches by rebasing your pull request branch onto
  the `master` branch. This also avoids merge commits and creates a linear Git commit history.

### Developing

Clone this repository:
```shell
git clone git+ssh://<LAUNCHPAD_USER>@git.launchpad.net/juju-lint
cd juju-lint/
```

Create and activate a virtualenv with the development requirements:

```shell
make dev-environment
```

This step is mandatory, otherwise a message like this will appear if you try to commit:

```shell
$ git commit
`pre-commit` not found.  Did you forget to activate your virtualenv?
```

After making your changes you can run the CI without the need of building and installing the snap by using:

```shell
python3 -m jujulint.cli <PATH_TO_YAML> -c <PATH_TO_RULE_FILE> -l debug
```


### Testing

```shell
make lint            # check code style
make reformat        # reformat the code using black and isort
make unittests       # run unit tests
make functional      # run functional tests
make test            # run lint, unittests and functional
make build           # build the snap
make clean           # clean the snapcraft lxd containers and the snap files created
```
### Functional Tests

`make functional` will build the snap, rename it, install it locally and run the tests against the installed snap package. Since this action involves installing a snap package, passwordless `sudo` privileges are needed.
However for development purposes, the testing infrastructure also allows for installing `juju-lint` as a python package to a tox environment
and running tests against it.
In order to invoke:
- development smoke suite, which deselects tests running against a live lxd cloud
  - `$ tox -e func -- -m smoke -v`
- development full suite, which runs all the functional tests
  - `$ tox -e func`


## Canonical Contributor Agreement

Canonical welcomes contributions to the juju-lint. Please check out our [contributor agreement](https://ubuntu.com/legal/contributors) if you're interested in contributing to the solution.
