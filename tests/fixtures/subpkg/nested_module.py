"""A module nested inside a subpackage."""
from tests.fixtures.another_module import CONSTANT_ANOTHER

NESTED_CONSTANT = 42.0


def nested_function():
    """A function in a nested module, using an import."""
    # Uses NESTED_CONSTANT (local global) and CONSTANT_ANOTHER (imported)
    return f"Nested-{NESTED_CONSTANT}-{CONSTANT_ANOTHER}"


class NestedClass:
    """A class in a nested module."""

    def nested_method(self):
        """Calls a function within the same nested module."""
        return nested_function()
