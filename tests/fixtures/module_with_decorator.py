def simple_decorator(f):
    """A simple decorator that wraps a function, but without functools.wraps."""
    def wrapper(*args, **kwargs):
        print("Decorator was here!")
        return f(*args, **kwargs)
    return wrapper

def undecorated_dependency():
    """A dependency for the decorated function."""
    return "undecorated_dependency"

@simple_decorator
def decorated_function():
    """A function that is decorated."""
    print("I am a decorated function.")
    return undecorated_dependency()
