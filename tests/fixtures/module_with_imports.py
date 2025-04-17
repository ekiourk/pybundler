"""A module demonstrating various import styles."""

# 1. Built-in module import
import os
import sys  # Another builtin for testing filter

# 2. Standard library (non-builtin) module import
import json
from datetime import datetime

# 3. Import from sibling module in the same package ('fixtures')
import tests.fixtures.another_module as am
from tests.fixtures.simple_module import simple_function as aliased_simple
from tests.fixtures.simple_module import SimpleClass
from tests.fixtures.subpkg.nested_module import nested_function, NestedClass


# Define a function that uses various dependencies
def complex_function(value):
    """Uses imports and local calls."""
    # Use built-in
    cwd = os.getcwd()
    is_win = sys.platform == 'win32'

    # Use standard library non-builtin
    timestamp = datetime.now().isoformat()
    json_data = json.dumps({'value': value, 'cwd': cwd})

    # Use sibling module import (alias)
    util_result = am.utility_function()

    # Use sibling function import (alias)
    simple_result = aliased_simple(value)

    # Use sibling class import
    simple_instance = SimpleClass(value * 2)
    method_result = simple_instance.simple_method(3)

    # Use subpackage function import
    nested_result = nested_function()

    # Use subpackage class import
    nested_instance = NestedClass()
    nested_method_result = nested_instance.nested_method()

    # Call another function in *this* module
    local_call_result = _helper_function(simple_result)

    return {
        "platform": is_win,
        "time": timestamp,
        "config": json_data,
        "utility": util_result,
        "simple": simple_result,
        "method": method_result,
        "nested_func": nested_result,
        "nested_method": nested_method_result,
        "local_helper": local_call_result
    }


def _helper_function(input_val):
    """A local helper function."""
    # Uses a class from this module indirectly via caller perhaps?
    # Let's keep it simple for now.
    return f"Helper received: {input_val}"


class ImportingClass:
    """A class that uses imports in its methods."""

    def __init__(self):
        # Uses stdlib
        self.created_at = datetime.now()
        # Uses sibling class
        self.simple_obj = SimpleClass(100)
        # Uses subpackage class
        self.nested_obj = NestedClass()

    def process(self):
        # Uses sibling utility function
        util = am.utility_function().upper()
        # Uses nested method
        nested_info = self.nested_obj.nested_method()
        return f"Processed: {util} // {nested_info}"


def function_using_local_class():
    """Instantiates and uses ImportingClass from this module."""
    instance = ImportingClass()
    return instance.process()
