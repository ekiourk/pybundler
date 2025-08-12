import functools

class Command:
    """A mock command object that holds a callback."""
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args, **kwargs):
        """Makes the object callable, delegating to the callback."""
        return self.callback(*args, **kwargs)

def command_decorator(f):
    """A decorator that wraps a function in a Command object."""
    return Command(f)

def decorator_factory(cli_obj):
    """
    A decorator factory that returns a decorator. This simulates a complex
    scenario like `common_click_options` where a decorator is generated
    and applies other decorators.
    """
    def inner_decorator(f):
        # This wrapper function is decorated with @command_decorator,
        # which turns it into a Command object.
        @command_decorator
        # It also uses @functools.wraps to preserve the metadata of the
        # original function `f`.
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            """The innermost wrapper function."""
            print(f"CLI object was: {cli_obj}")
            return f(*args, **kwargs)
        return wrapper
    return inner_decorator

def final_dependency():
    """The final dependency that needs to be discovered."""
    return "final_dependency"

# This simulates a CLI group object.
class CliGroup:
    pass

cli_group = CliGroup()

@decorator_factory(cli_group)
def top_level_function():
    """The function decorated by the factory-generated decorator."""
    return final_dependency()
