"""A simple module with a function and a class."""

GLOBAL_VAR_SIMPLE = 'simple_global'


def simple_function(x):
    """A basic function using a global."""
    # This uses GLOBAL_VAR_SIMPLE from this module's scope
    y = (x * 2) + len(GLOBAL_VAR_SIMPLE)
    return y


class SimpleClass:
    """A basic class with a method."""
    INSTANCE_VAR = 10

    def __init__(self, val):
        self.val = val + self.INSTANCE_VAR

    def simple_method(self, factor):
        """A basic method using instance and global variables."""
        # This uses self.val (instance) and GLOBAL_VAR_SIMPLE (module global)
        return (self.val + len(GLOBAL_VAR_SIMPLE)) * factor


# Another function in the same module
def calls_simple_function(z):
    return simple_function(z + 1)
