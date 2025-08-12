class ComplexCommand:
    """A mock command object similar to one created by a complex decorator."""
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args, **kwargs):
        """Makes the object callable."""
        return self.callback(*args, **kwargs)

def complex_decorator(f):
    """
    A decorator that wraps a function in a ComplexCommand object,
    simulating decorators like @click.command().
    """
    return ComplexCommand(f)

def complex_dependency():
    """A dependency for the complex decorated function."""
    return "complex_dependency"

@complex_decorator
def complex_decorated_function():
    """A function decorated with the complex decorator."""
    return complex_dependency()
