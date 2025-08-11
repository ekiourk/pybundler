import importlib
import inspect
import os
import sys

import pytest

from pybundler.dependency_bundler import DependencyBundler
from pybundler.core_functions import load_target_function


@pytest.fixture(scope="session")
def fixture_paths(tests_root):
    """Set up fixture paths for all tests."""
    import _pytest

    # Base directory for fixture files
    fixtures_dir = os.path.join(tests_root, 'fixtures')

    paths = {
        'simple_module_path': os.path.join(fixtures_dir, 'simple_module.py'),
        'imports_module_path': os.path.join(fixtures_dir, 'module_with_imports.py'),
        'another_module_path': os.path.join(fixtures_dir, 'another_module.py'),
        'nested_module_path': os.path.join(fixtures_dir, 'subpkg', 'nested_module.py'),
        'module_with_third_party_imports': os.path.join(fixtures_dir, 'module_with_third_party_imports.py'),
        'pytest_config_path': os.path.join(os.path.dirname(inspect.getfile(_pytest)), 'config')
    }

    # Ensure paths are set up for imports within fixtures and tests
    if fixtures_dir not in sys.path:
        sys.path.insert(0, fixtures_dir)
    if tests_root not in sys.path:
        sys.path.insert(0, tests_root)
    project_root_for_bundler = os.path.abspath(os.path.join(tests_root, '..'))
    if project_root_for_bundler not in sys.path:
        sys.path.insert(0, project_root_for_bundler)

    # Make sure bundler is loaded correctly after path setup
    importlib.reload(sys.modules['pybundler.dependency_bundler'])

    return paths


@pytest.fixture(autouse=True)
def reset_module_imports():
    """Clean previously imported fixture modules before each test."""
    mods_to_remove = [m for m in sys.modules if
                      m.startswith('fixtures.') or m.startswith('tests.fixtures') or
                      m in ['simple_module', 'another_module', 'module_with_imports', 'nested_module']]
    for mod_name in mods_to_remove:
        if mod_name in sys.modules:
            del sys.modules[mod_name]
    yield


def get_collected_qualnames(collected_sources):
    """Helper to extract qualnames from the source fragment headers."""
    qualnames = set()
    obj_prefix = "# --- Source from: .* Object: "
    import re
    for (path, line), source in collected_sources.items():
        match = re.search(obj_prefix + r"(\S+)", source.splitlines()[0])
        if match:
            qualnames.add((os.path.abspath(path), match.group(1)))
        else:
            # Fallback or warning if header format changes
            print(f"Warning: Could not parse object name from header in {path}:{line}")
            qualnames.add((os.path.abspath(path), "UnknownObject"))  # Add path at least
    return qualnames


def test_simple_function(fixture_paths):
    """Target: simple_function. Expected: Only simple_function source."""
    target_obj = load_target_function(fixture_paths['simple_module_path'], "simple_function")
    assert target_obj is not None

    bundler = DependencyBundler()
    collected = bundler.run_dependency_analysis(target_obj)
    collected_qualnames = get_collected_qualnames(collected)

    expected_qualnames = {
        (fixture_paths['simple_module_path'], "simple_function")
    }
    assert collected_qualnames == expected_qualnames


def test_calls_same_module_function(fixture_paths):
    """Target: calls_simple_function. Expected: Both functions from simple_module."""
    target_obj = load_target_function(fixture_paths['simple_module_path'], "calls_simple_function")
    assert target_obj is not None

    bundler = DependencyBundler()
    collected = bundler.run_dependency_analysis(target_obj)
    collected_qualnames = get_collected_qualnames(collected)

    expected_qualnames = {
        (fixture_paths['simple_module_path'], "calls_simple_function"),
        (fixture_paths['simple_module_path'], "simple_function"),
    }
    assert collected_qualnames == expected_qualnames


def test_target_simple_class(fixture_paths):
    """Target: SimpleClass. Expected: Class definition and its method."""
    target_obj = load_target_function(fixture_paths['simple_module_path'], "SimpleClass")
    assert target_obj is not None

    bundler = DependencyBundler()
    collected = bundler.run_dependency_analysis(target_obj)
    collected_qualnames = get_collected_qualnames(collected)

    expected_qualnames = {
        (fixture_paths['simple_module_path'], "SimpleClass"),
        (fixture_paths['simple_module_path'], "SimpleClass.__init__"),
        (fixture_paths['simple_module_path'], "SimpleClass.simple_method"),
    }
    assert collected_qualnames == expected_qualnames


def test_complex_function_with_imports(fixture_paths):
    """Target: complex_function. Expected: Relevant functions/classes from fixtures, exclude stdlib."""
    target_obj = load_target_function(fixture_paths['imports_module_path'], "complex_function")
    assert target_obj is not None

    bundler = DependencyBundler()
    collected = bundler.run_dependency_analysis(target_obj)
    collected_qualnames = get_collected_qualnames(collected)

    expected_qualnames = {
        # From module_with_imports.py
        (fixture_paths['imports_module_path'], "complex_function"),
        (fixture_paths['imports_module_path'], "_helper_function"),  # Called locally
        # From another_module.py
        (fixture_paths['another_module_path'], "utility_function"),  # via am.utility_function()
        # From simple_module.py
        (fixture_paths['simple_module_path'], "simple_function"),  # via aliased_simple()
        (fixture_paths['simple_module_path'], "SimpleClass"),  # via SimpleClass()
        (fixture_paths['simple_module_path'], "SimpleClass.__init__"),
        (fixture_paths['simple_module_path'], "SimpleClass.simple_method"),  # Queued via SimpleClass analysis
        # From subpkg/nested_module.py
        (fixture_paths['nested_module_path'], "nested_function"),  # via nested_function()
        (fixture_paths['nested_module_path'], "NestedClass"),  # via NestedClass()
        (fixture_paths['nested_module_path'], "NestedClass.nested_method"),  # Queued via NestedClass analysis
    }

    assert collected_qualnames == expected_qualnames

    # Assert standard library / builtins were NOT collected by checking paths
    import json, datetime, os, sys
    for mod in [json, datetime, os, sys]:
        try:
            mod_path = inspect.getfile(mod)
            # Check if any collected source came from this path
            found_stdlib = any(p == os.path.abspath(mod_path) for p, _ in collected.keys())
            assert not found_stdlib, f"Standard library module {mod.__name__} source was unexpectedly collected"
        except TypeError:
            pass  # OK if module has no file (e.g., sys)


def test_function_using_local_class(fixture_paths):
    """Target: function_using_local_class. Expected: Func, the class, its method, and their dependencies."""
    target_obj = load_target_function(fixture_paths['imports_module_path'], "function_using_local_class")
    assert target_obj is not None

    bundler = DependencyBundler()
    collected = bundler.run_dependency_analysis(target_obj)
    collected_qualnames = get_collected_qualnames(collected)

    expected_qualnames = {
        # From module_with_imports.py
        (fixture_paths['imports_module_path'], "function_using_local_class"),
        (fixture_paths['imports_module_path'], "ImportingClass"),  # Instantiated locally
        (fixture_paths['imports_module_path'], "ImportingClass.__init__"),  # Instantiated locally
        (fixture_paths['imports_module_path'], "ImportingClass.process"),  # Method called + queued by class analysis
        # From simple_module.py
        (fixture_paths['simple_module_path'], "SimpleClass"),
        (fixture_paths['simple_module_path'], "SimpleClass.__init__"),
        (fixture_paths['simple_module_path'], "SimpleClass.simple_method"),
        # From subpkg/nested_module.py
        (fixture_paths['nested_module_path'], "NestedClass"),
        (fixture_paths['nested_module_path'], "NestedClass.nested_method"),
        (fixture_paths['nested_module_path'], "nested_function"),  # Used by nested_method
        # From another_module.py
        (fixture_paths['another_module_path'], "utility_function"),  # Used by ImportingClass.process
    }

    assert collected_qualnames == expected_qualnames

    # Check stdlib exclusion (datetime used in ImportingClass.__init__)
    import datetime
    try:
        mod_path = inspect.getfile(datetime)
        found_stdlib = any(p == os.path.abspath(mod_path) for p, _ in collected.keys())
        assert not found_stdlib, f"Standard library module {datetime.__name__} source was unexpectedly collected"
    except TypeError:
        pass


def test_target_class_with_imports(fixture_paths):
    """Target: ImportingClass. Expected: Class, its methods, and their dependencies."""
    target_obj = load_target_function(fixture_paths['imports_module_path'], "ImportingClass")
    assert target_obj is not None

    bundler = DependencyBundler()
    collected = bundler.run_dependency_analysis(target_obj)
    collected_qualnames = get_collected_qualnames(collected)

    # Expected dependencies: Class, its methods (__init__, process), and items used by them.
    expected_qualnames = {
        # From module_with_imports.py
        (fixture_paths['imports_module_path'], "ImportingClass"),
        (fixture_paths['imports_module_path'], "ImportingClass.process"),  # Method defined in class
        (fixture_paths['imports_module_path'], "ImportingClass.__init__"),
        # Also defined (implicitly analyzed via class)
        # From simple_module.py
        (fixture_paths['simple_module_path'], "SimpleClass"),  # Used in __init__
        (fixture_paths['simple_module_path'], "SimpleClass.__init__"),  # Used in __init__
        (fixture_paths['simple_module_path'], "SimpleClass.simple_method"),  # Queued by SimpleClass analysis
        # From subpkg/nested_module.py
        (fixture_paths['nested_module_path'], "NestedClass"),  # Used in __init__
        (fixture_paths['nested_module_path'], "NestedClass.nested_method"),
        # Used by process + Queued by NestedClass analysis
        (fixture_paths['nested_module_path'], "nested_function"),  # Used by nested_method
        # From another_module.py
        (fixture_paths['another_module_path'], "utility_function"),  # Used by process
    }

    assert collected_qualnames == expected_qualnames

    # Check stdlib exclusion
    import datetime
    try:
        mod_path = inspect.getfile(datetime)
        found_stdlib = any(p == os.path.abspath(mod_path) for p, _ in collected.keys())
        assert not found_stdlib, f"Standard library module {datetime.__name__} source was unexpectedly collected"
    except TypeError:
        pass


def test_function_with_third_party_dependency(fixture_paths):
    """Test function that imports from a third-party library."""
    target_obj = load_target_function(fixture_paths['module_with_third_party_imports'],
                                      "function_with_third_party_dependency")
    assert target_obj is not None

    bundler = DependencyBundler()
    collected = bundler.run_dependency_analysis(target_obj)
    collected_qualnames = get_collected_qualnames(collected)

    all_found_qualnames = {q for _, q in collected_qualnames}

    expected_qualnames = {
        "function_with_third_party_dependency",
        'filename_arg',
        'UsageError'
    }
    assert all_found_qualnames == expected_qualnames


def test_function_with_third_party_dependency_excluded(fixture_paths):
    """Test that third-party dependencies are excluded when the flag is set."""
    target_obj = load_target_function(fixture_paths['module_with_third_party_imports'],
                                      "function_with_third_party_dependency")
    assert target_obj is not None

    # Enable the exclusion of third-party modules
    bundler = DependencyBundler(exclude_third_party=True)
    collected = bundler.run_dependency_analysis(target_obj)
    collected_qualnames = get_collected_qualnames(collected)

    # The only thing collected should be the target function itself,
    # as its only dependency is a third-party module which should be excluded.
    expected_qualnames = {
        (fixture_paths['module_with_third_party_imports'], "function_with_third_party_dependency"),
    }

    assert collected_qualnames == expected_qualnames

    # Explicitly check that no modules from 'site-packages' were included
    for path, _ in collected.keys():
        assert 'site-packages' not in path
