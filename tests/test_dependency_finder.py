import ast
import importlib
import os
import sys
import textwrap
from types import FunctionType

import pytest

from pybundler.dependency_bundler import DependencyFinder


@pytest.fixture(scope="module")
def fixture_modules(tests_root):
    """Load fixture modules for tests."""

    # Base directory for fixture files
    fixtures_dir = os.path.join(tests_root, 'fixtures')
    if fixtures_dir not in sys.path:
        sys.path.insert(0, fixtures_dir)

    # Prepare fixture paths and modules
    fixture_data = {}
    fixture_data["simple_module_path"] = os.path.join(fixtures_dir, 'simple_module.py')
    fixture_data["imports_module_path"] = os.path.join(fixtures_dir, 'module_with_imports.py')
    fixture_data["another_module_path"] = os.path.join(fixtures_dir, 'another_module.py')

    try:
        # Load leaf dependencies first
        fixture_data["another_mod"] = importlib.import_module("tests.fixtures.another_module")
        fixture_data["simple_mod"] = importlib.import_module("tests.fixtures.simple_module")
        # Load module that imports others
        fixture_data["imports_mod"] = importlib.import_module("tests.fixtures.module_with_imports")
        # Load nested module
        fixture_data["nested_mod"] = importlib.import_module("tests.fixtures.subpkg.nested_module")
    except ImportError as e:
        pytest.fail(f"Failed to import fixture modules. Error: {e}\nCurrent sys.path: {sys.path}")

    return fixture_data


# --- Helper function for running visitor ---

def run_visitor_on_source(source_code, global_vars):
    """
    Helper function to parse source code, run DependencyFinder, and return found objects.

    Args:
        source_code (str): The Python source code snippet to analyze.
        global_vars (dict): The dictionary simulating the global namespace for the source code.

    Returns:
        set: A set containing the potential dependency objects found by the visitor.
    """
    try:
        tree = ast.parse(textwrap.dedent(source_code))
        # Instantiate the visitor from the bundler script
        finder = DependencyFinder(global_vars=global_vars)
        finder.visit(tree)
        return finder.potential_dependencies
    except Exception as e:
        pytest.fail(f"run_visitor_on_source failed: {type(e).__name__}: {e}\nSource:\n{source_code}")


# --- Individual Test Functions ---

def test_find_direct_global_function_call(fixture_modules):
    """Test that visitor finds functions called directly via global name."""
    source = """
    # Simulates calls_simple_function
    def caller(z):
        res = simple_function(z + 1) # simple_function is global here
        return res
    """
    # The globals need to contain simple_function
    globals_dict = fixture_modules["simple_mod"].__dict__

    assert 'simple_function' in globals_dict, "simple_function key missing from simple_module.__dict__"
    assert isinstance(globals_dict.get('simple_function'), FunctionType), \
        "simple_module.__dict__['simple_function'] is not a function"

    found_deps = run_visitor_on_source(source, globals_dict)

    expected_obj = fixture_modules["simple_mod"].simple_function
    assert expected_obj in found_deps, "simple_function object was not found"
    # Verify only the expected object is found
    assert len(found_deps) == 1, "Only simple_function should be found"


def test_find_direct_global_class_usage(fixture_modules):
    """Test that visitor finds classes used directly via global name."""
    source = """
    # Simulates using SimpleClass
    def class_user(v):
        instance = SimpleClass(v) # SimpleClass is global here
        return instance.simple_method(2)
    """
    globals_dict = fixture_modules["simple_mod"].__dict__
    found_deps = run_visitor_on_source(source, globals_dict)

    expected_obj = fixture_modules["simple_mod"].SimpleClass
    assert expected_obj in found_deps, "SimpleClass object was not found"
    # Note: The current simple visitor doesn't analyze inside simple_method,
    # nor does it resolve 'instance.simple_method'. It only finds 'SimpleClass'.
    assert len(found_deps) == 1, "Only SimpleClass should be found by this visitor"


def test_find_aliased_module_attribute_function(fixture_modules):
    """Test that visitor finds function accessed via module alias attribute."""
    source = """
    # Simulates complex_function using am.utility_function
    import tests.fixtures.another_module as am # Assume 'am' is setup in globals
    def alias_user():
        result = am.utility_function() # Access attribute on 'am'
        return result
    """
    # Globals need 'am' mapped to the another_module object
    globals_dict = {'am': fixture_modules["another_mod"]}  # Simulate the import alias
    found_deps = run_visitor_on_source(source, globals_dict)

    # Expect the module object 'am' itself (via visit_Name)
    # And the function 'utility_function' (via visit_Attribute)
    expected_mod_obj = fixture_modules["another_mod"]
    expected_func_obj = fixture_modules["another_mod"].utility_function

    assert expected_mod_obj in found_deps, "Module alias 'am' was not found"
    assert expected_func_obj in found_deps, "utility_function via attribute access was not found"
    assert len(found_deps) == 2, "Should find the module and the function"


def test_find_aliased_module_attribute_class(fixture_modules):
    """Test that visitor finds class accessed via module alias attribute."""
    source = """
    # Simulates using am.AnotherClass
    import tests.fixtures.another_module as am
    def alias_class_user():
        instance = am.AnotherClass() # Access attribute on 'am'
        return instance.get_name()
    """
    globals_dict = {'am': fixture_modules["another_mod"]}
    found_deps = run_visitor_on_source(source, globals_dict)

    expected_mod_obj = fixture_modules["another_mod"]
    expected_class_obj = fixture_modules["another_mod"].AnotherClass

    assert expected_mod_obj in found_deps, "Module alias 'am' was not found"
    assert expected_class_obj in found_deps, "AnotherClass via attribute access was not found"
    assert len(found_deps) == 2, "Should find the module and the class"


def test_ignore_local_variables_shadowing_globals(fixture_modules):
    """Test that visitor ignores local assignments, even if name matches global."""
    source = """
    simple_function = lambda x: x # Local variable shadows global
    def shadow_user():
        result = simple_function(5) # Should resolve to local lambda
        return result
    """
    # Globals include the *real* simple_function
    globals_dict = fixture_modules["simple_mod"].__dict__.copy()  # Use copy
    found_deps = run_visitor_on_source(source, globals_dict)

    # The simple visitor's local name tracking is basic. It sees `simple_function = ...`
    # in the source snippet, adds 'simple_function' to local_names for that snippet.
    # When it sees `simple_function(5)`, resolve_name checks local_names and returns None.
    # Therefore, the *global* simple_function should NOT be found here.
    expected_global_obj = fixture_modules["simple_mod"].simple_function
    assert expected_global_obj not in found_deps, "Global simple_function should be ignored due to local shadow"
    assert len(found_deps) == 0, "No external dependencies should be found"


def test_find_dependency_in_class_body(fixture_modules):
    """Test that visitor finds dependencies used in class body assignments."""
    source = """
    # Depends on utility_function from another_module
    class ClassUsingGlobal:
        DEFAULT_NAME = utility_function() # Global function call in class body

        def __init__(self):
            self.name = self.DEFAULT_NAME
    """
    # Globals need utility_function
    globals_dict = fixture_modules["another_mod"].__dict__
    found_deps = run_visitor_on_source(source, globals_dict)

    # Expect utility_function to be found via visit_Name inside the class body.
    expected_func_obj = fixture_modules["another_mod"].utility_function
    assert expected_func_obj in found_deps, "utility_function used in class body not found"
    # The visitor doesn't currently analyze inside __init__ deeply
    assert len(found_deps) == 1
