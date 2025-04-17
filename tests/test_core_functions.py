import os
import sys
from types import FunctionType, ModuleType
from unittest.mock import MagicMock

import pytest

from pybundler import core_functions


@pytest.fixture(scope="session")
def fixture_paths(tests_root):
    """Set up paths valid for all tests."""

    # Base directory for fixture files
    fixtures_dir = os.path.join(tests_root, 'fixtures')

    paths = {
        'fixtures_dir': fixtures_dir,
        'simple_module_path': os.path.join(fixtures_dir, 'simple_module.py'),
        'imports_module_path': os.path.join(fixtures_dir, 'module_with_imports.py'),
        'another_module_path': os.path.join(fixtures_dir, 'another_module.py'),
        'nested_module_path': os.path.join(fixtures_dir, 'subpkg', 'nested_module.py'),
        'non_existent_path': os.path.join(fixtures_dir, 'non_existent.py')
    }

    # Ensure fixtures directory is in path for intra-fixture imports to work during load
    if fixtures_dir not in sys.path:
        sys.path.insert(0, fixtures_dir)
    # Ensure parent of fixtures ('tests') is in path for 'import tests.fixtures...'
    if tests_root not in sys.path:
        sys.path.insert(0, tests_root)

    return paths


@pytest.fixture(autouse=True)
def clean_modules():
    """Clean previously imported fixture modules from sys.modules for isolation."""
    # Clean up before test
    mods_to_remove = [m for m in sys.modules if
                      m.startswith('fixtures.') or m.startswith('tests.fixtures') or
                      m in ['simple_module', 'another_module', 'module_with_imports', 'nested_module']]
    for mod_name in mods_to_remove:
        if mod_name in sys.modules:
            del sys.modules[mod_name]

    yield  # Let the test run

    # Clean up after test (if needed)
    for mod_name in mods_to_remove:
        if mod_name in sys.modules:
            del sys.modules[mod_name]


# --- Tests for parse_target_string ---

def test_parse_target_string_valid():
    # Use a relative path typical for command line usage
    path_str = os.path.join('tests', 'fixtures', 'simple_module.py')
    target = f"{path_str}:simple_function"
    abs_path_expected = os.path.abspath(path_str)

    # Assuming the script is run from project root, parse_target_string should find it
    path, name = core_functions.parse_target_string(target)
    assert path is not None, "Parsing failed for valid relative path"
    # Use abspath for comparison as parse_target_string should return absolute
    assert os.path.abspath(path) == abs_path_expected
    assert name == "simple_function"


def test_parse_target_string_absolute_path(fixture_paths):
    abs_path = os.path.abspath(os.path.join(fixture_paths['fixtures_dir'], 'simple_module.py'))
    target = f"{abs_path}:SimpleClass"
    path, name = core_functions.parse_target_string(target)
    assert path == abs_path
    assert name == "SimpleClass"


def test_parse_target_string_invalid_format():
    assert core_functions.parse_target_string("no_colon_in_string") == (None, None)
    # Test with multiple colons - rsplit behavior
    path, name = core_functions.parse_target_string("too:many:colons")
    assert path == os.path.abspath("too:many")  # Will likely make path absolute
    assert name == "colons"


# --- Tests for load_target_function ---

def test_load_target_function_valid_function(fixture_paths):
    func = core_functions.load_target_function(fixture_paths['simple_module_path'], "simple_function")
    assert func is not None
    assert isinstance(func, FunctionType)
    assert func.__name__ == "simple_function"
    assert hasattr(func, '__module__')


def test_load_target_function_valid_class(fixture_paths):
    cls = core_functions.load_target_function(fixture_paths['simple_module_path'], "SimpleClass")
    assert cls is not None
    assert isinstance(cls, type)
    assert cls.__name__ == "SimpleClass"
    assert hasattr(cls, '__module__')


def test_load_target_function_target_not_found(fixture_paths):
    obj = core_functions.load_target_function(fixture_paths['simple_module_path'], "non_existent_target")
    assert obj is None


def test_load_target_function_module_not_found(fixture_paths):
    obj = core_functions.load_target_function(fixture_paths['non_existent_path'], "any_function")
    assert obj is None


def test_load_target_function_target_not_callable_or_class(fixture_paths):
    # GLOBAL_VAR_SIMPLE is not a function or class
    obj = core_functions.load_target_function(fixture_paths['simple_module_path'], "GLOBAL_VAR_SIMPLE")
    # The refined implementation checks isinstance(obj, (FunctionType, MethodType, type))
    assert obj is None


# --- Tests for is_standard_library ---

def test_is_standard_library_true():
    assert core_functions.is_standard_library(sys)
    # 'os' might be tricky depending on implementation, but often treated as builtin
    import os
    assert core_functions.is_standard_library(os)
    import math  # another core builtin
    assert core_functions.is_standard_library(math)


def test_is_standard_library_false_stdlib_py():
    import json
    import datetime
    import collections
    assert core_functions.is_standard_library(json), "json should be detected as stdlib"
    assert core_functions.is_standard_library(datetime), "datetime should be detected as stdlib"
    assert core_functions.is_standard_library(collections), "collections should be detected as stdlib"


def test_is_standard_library_false_custom(fixture_paths):
    # Need to load the module object first using the bundler's loader
    # Use a known valid target within the module to load it
    _ = core_functions.load_target_function(fixture_paths['simple_module_path'], "simple_function")
    # Find the loaded module in sys.modules (name might vary based on loader impl)
    mod_name = os.path.splitext(os.path.basename(fixture_paths['simple_module_path']))[0]
    simple_mod = sys.modules.get(mod_name)
    assert simple_mod is not None, f"Module {mod_name} not found in sys.modules after loading"
    assert not core_functions.is_standard_library(simple_mod)


def test_is_standard_library_on_non_module():
    assert not core_functions.is_standard_library(123)
    assert not core_functions.is_standard_library(len)  # a builtin function, not module


def test_no_inclusion_exclusion():
    """Test with no inclusion or exclusion lists"""
    assert core_functions.is_package_included("requests.models") is True
    assert core_functions.is_package_included("pandas") is True
    assert core_functions.is_package_included("mypackage.module") is True


def test_inclusion_list():
    """Test inclusion list functionality"""
    include_list = ["requests", "pandas"]

    # Should include packages in the list
    assert core_functions.is_package_included("requests.models", include_list=include_list) is True
    assert core_functions.is_package_included("requests", include_list=include_list) is True
    assert core_functions.is_package_included("pandas.core", include_list=include_list) is True

    # Should exclude packages not in the list
    assert core_functions.is_package_included("flask", include_list=include_list) is False
    assert core_functions.is_package_included("django.http", include_list=include_list) is False
    assert core_functions.is_package_included("mypackage.module", include_list=include_list) is False


def test_exclusion_list():
    """Test exclusion list functionality"""
    exclude_list = ["django", "flask"]

    # Should exclude packages in the list
    assert core_functions.is_package_included("django.http", exclude_list=exclude_list) is False
    assert core_functions.is_package_included("django", exclude_list=exclude_list) is False
    assert core_functions.is_package_included("flask.app", exclude_list=exclude_list) is False

    # Should include packages not in the list
    assert core_functions.is_package_included("requests.models", exclude_list=exclude_list) is True
    assert core_functions.is_package_included("pandas", exclude_list=exclude_list) is True
    assert core_functions.is_package_included("mypackage.module", exclude_list=exclude_list) is True


def test_submodule_handling():
    """Test that submodules are handled correctly based on top-level package"""
    include_list = ["requests"]

    # All submodules of 'requests' should be included
    assert core_functions.is_package_included("requests.models.Response", include_list=include_list) is True
    assert core_functions.is_package_included("requests.auth", include_list=include_list) is True
    assert core_functions.is_package_included("requests_mock", include_list=include_list) is False  # Different package


def test_both_lists_error():
    """Test that providing both lists raises a ValueError"""
    with pytest.raises(ValueError) as excinfo:
        core_functions.is_package_included("module", include_list=["requests"], exclude_list=["django"])
    assert "Cannot specify both include_list and exclude_list" in str(excinfo.value)


def test_empty_lists():
    """Test behavior with empty lists"""
    # Empty include list means nothing is included
    assert core_functions.is_package_included("requests", include_list=[]) is False

    # Empty exclude list means everything is included
    assert core_functions.is_package_included("requests", exclude_list=[]) is True


# Tests for should_include_module function

# Fixture for creating mock modules
@pytest.fixture
def mock_module():
    module = MagicMock(spec=ModuleType)
    module.__name__ = "requests"
    return module


# Use parametrize to test multiple scenarios
@pytest.mark.parametrize("is_stdlib, include_list, exclude_list, expected", [
    (True, None, None, False),  # stdlib modules always excluded
    (True, ["requests"], None, False),  # stdlib excluded even if in include list
    (True, None, ["django"], False),  # stdlib excluded even if not in exclude list
    (False, ["requests"], None, True),  # non-stdlib in include list
    (False, ["django"], None, False),  # non-stdlib not in include list
    (False, None, ["requests"], False),  # non-stdlib in exclude list
    (False, None, ["django"], True),  # non-stdlib not in exclude list
    (False, None, None, True),  # non-stdlib with no lists
])
def test_should_include_module(mock_module, is_stdlib, include_list, exclude_list, expected, monkeypatch):
    """Test various scenarios for should_include_module"""

    # Create a mock version of is_standard_library
    def mock_is_standard_library(module):
        return is_stdlib

    # Apply the mock to is_standard_library
    monkeypatch.setattr("pybundler.core_functions.is_standard_library", mock_is_standard_library)

    # Test the function
    result = core_functions.should_include_module(mock_module, include_list=include_list, exclude_list=exclude_list)
    assert result is expected


def test_non_module_obj():
    """Test handling of non-module objects"""
    # Test with various non-module objects
    assert core_functions.should_include_module("not_a_module") is False
    assert core_functions.should_include_module(42) is False
    assert core_functions.should_include_module(None) is False
    assert core_functions.should_include_module({}) is False


# --- Tests for get_object_source ---

def test_get_object_source_function(fixture_paths):
    func = core_functions.load_target_function(fixture_paths['simple_module_path'], "simple_function")
    assert func is not None
    source, path, line = core_functions.get_object_source(func)
    assert source is not None
    assert source.startswith("def simple_function(x):")
    assert "GLOBAL_VAR_SIMPLE" in source  # Check content
    assert os.path.abspath(path) == os.path.abspath(fixture_paths['simple_module_path'])
    assert isinstance(line, int)
    assert line > 0


def test_get_object_source_class(fixture_paths):
    cls = core_functions.load_target_function(fixture_paths['simple_module_path'], "SimpleClass")
    assert cls is not None
    source, path, line = core_functions.get_object_source(cls)
    assert source is not None
    assert source.startswith("class SimpleClass:")
    assert "def simple_method(self, factor):" in source  # Check method inside
    assert os.path.abspath(path) == os.path.abspath(fixture_paths['simple_module_path'])
    assert isinstance(line, int)
    assert line > 0


def test_get_object_source_method(fixture_paths):
    cls = core_functions.load_target_function(fixture_paths['simple_module_path'], "SimpleClass")
    method = getattr(cls, 'simple_method', None)
    assert method is not None
    assert isinstance(method, FunctionType)  # Methods are functions before binding

    source, path, line = core_functions.get_object_source(method)
    assert source is not None
    # Strip leading whitespace which inspect.getsource might include
    assert source.strip().startswith("def simple_method(self, factor):")
    assert os.path.abspath(path) == os.path.abspath(fixture_paths['simple_module_path'])
    assert isinstance(line, int)
    assert line > 0


def test_get_object_source_builtin_function():
    source, path, line = core_functions.get_object_source(len)
    assert source is None
    assert path is None
    assert line is None


def test_get_object_source_builtin_module():
    source, path, line = core_functions.get_object_source(sys)
    assert source is None
    assert path is None
    assert line is None
