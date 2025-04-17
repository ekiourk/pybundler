import sys
import os

import pytest


@pytest.fixture(scope="session")
def tests_root():
    """Set up fixture paths for all tests."""

    # dynamically add the project root to sys.path to find 'dependency_bundler'
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # dynamically add the tests directory to sys.path to find 'fixtures' package
    tests_root = os.path.abspath(os.path.dirname(__file__))
    if tests_root not in sys.path:
        sys.path.insert(0, tests_root)

    return tests_root
