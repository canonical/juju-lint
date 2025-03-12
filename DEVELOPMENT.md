# Development

## Developing

Clone this repository:
```shell
git clone git@github.com:canonical/juju-lint.git
cd juju-lint/
```

After making your changes you can run juju-lint without the need of building and installing the snap by using:

```shell
python3 -m jujulint.cli <PATH_TO_YAML> -c <PATH_TO_RULE_FILE> -l debug
```


## Testing

```shell
tox -e lint          # check code style
tox -e reformat      # reformat the code using black and isort
tox -e unit          # run unit tests
tox -e func          # run functional tests (using the source code package directly)
snapcraft --use-lxd  # build the snap
TEST_SNAP=/path/to/juju-lint.snap tox -e func  # run functional tests (using the built snap)
```

## Functional Tests

`TEST_SNAP=/path/to/juju-lint.snap tox -e func` install the snap locally and run the tests against the installed snap.
Since this action involves installing a snap package, passwordless `sudo` privileges are needed.
