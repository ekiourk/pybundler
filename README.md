# pybundler

Finds all non-standard-library Python dependencies of a function/class and bundles their source code.
## Installation

To install pybundler, you can use pip:

```bash
pip install .
```

Try the bundler on itself:
```bash
 pybundle pybundler/main.py:main > logs.txt
```

A file called bundler_output.py should be created.

Run tests (assuming tox is installed):

```bash
tox
```

For development install the required packages

```bash
pip install -r requirements-dev.txt
```