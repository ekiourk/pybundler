import importlib.util
import inspect
import os
import sys
import sysconfig
from types import ModuleType, FunctionType, MethodType


def is_virtualenv_path(path):
    """Return True if the given path is inside a virtual environment."""
    # Check if it's inside a known virtualenv folder
    real_prefix = getattr(sys, 'real_prefix', None)
    base_prefix = getattr(sys, 'base_prefix', sys.prefix)
    return (hasattr(sys, 'real_prefix') or base_prefix != sys.prefix) and path.startswith(sys.prefix)


def get_stdlib_paths():
    """
    Return a set of paths where standard Python library modules reside.

    This function caches its results - the calculation is only performed once,
    and subsequent calls return the cached result.
    """
    # If we already calculated the paths, return the cached result
    if hasattr(get_stdlib_paths, "_stdlib_paths_cache"):
        return get_stdlib_paths.stdlib_paths_cache

    # First-time calculation
    stdlib_paths = set()

    # Step 1: Use sysconfig for stdlib and platstdlib
    for path_name in ['stdlib', 'platstdlib']:
        try:
            path = sysconfig.get_path(path_name)
            if path and os.path.exists(path):
                norm_path = os.path.normpath(path)
                # Filter out site-packages and virtualenvs
                if 'site-packages' not in norm_path and not is_virtualenv_path(norm_path):
                    stdlib_paths.add(norm_path)
        except KeyError:
            continue

    # Step 2: Fallback - use location of built-in 'os' module
    try:
        os_path = inspect.getfile(os)
        os_dir = os.path.normpath(os.path.dirname(os_path))
        if 'site-packages' not in os_dir and not is_virtualenv_path(os_dir):
            stdlib_paths.add(os_dir)
    except (TypeError, AttributeError):
        pass

    if not stdlib_paths:
        print("Warning: Could not reliably determine standard library path(s). Filtering might be inaccurate.",
              file=sys.stderr)
    else:
        print(f"DEBUG: Identified standard library paths for exclusion: {stdlib_paths}")

    # Cache the result in the function object itself
    get_stdlib_paths.stdlib_paths_cache = stdlib_paths

    return stdlib_paths


def get_module_file_path(module_obj):
    """
    Get the file path for a module object.
    Returns the normalized absolute path if available, None otherwise.
    """
    if not isinstance(module_obj, ModuleType):
        return None

    try:
        # Use inspect.getfile which is generally better for modules than getsourcefile
        mod_file = inspect.getfile(module_obj)
        if not mod_file:
            # E.g., namespace packages might not have a file
            print(f"DEBUG: Module '{module_obj.__name__}' has no discernible file path.")
            return None
        return os.path.normpath(os.path.abspath(mod_file))
    except TypeError:
        # This often happens for built-in modules or C extensions without clear file paths
        print(f"DEBUG: Module '{module_obj.__name__}' likely built-in or C extension (TypeError on getfile).")
        return None


def is_standard_library(module_obj):
    """
    Checks if a module is likely part of the Python standard library installation
    or a built-in module.
    Returns True if it IS part of stdlib/builtin, False otherwise (local/third-party).
    """
    if not isinstance(module_obj, ModuleType):
        return False  # Not a module we can analyze this way

    mod_name = module_obj.__name__

    # 1. Check true built-ins first (most reliable)
    if mod_name in sys.builtin_module_names:
        print(f"DEBUG: Module '{mod_name}' is built-in.")
        return True

    # 2. Get the module's file path
    mod_file_abs = get_module_file_path(module_obj)
    if mod_file_abs is None:
        return False  # Cannot determine path, assume not stdlib

    stdlib_paths = get_stdlib_paths()
    # 3. Check if the module's file path is within any of the identified stdlib directories
    if not stdlib_paths:
        print(f"Warning: Cannot check stdlib paths for {mod_name}. Assuming non-stdlib.")
        return False  # Cannot perform check

    for std_path in stdlib_paths:
        # Check if the module file is *inside* the standard library path
        # Using startswith is generally safe and efficient
        if mod_file_abs.startswith(std_path + os.sep):
            print(f"DEBUG: Module '{mod_name}' ({mod_file_abs}) is within standard library path '{std_path}'.")
            return True

    # 4. If not built-in and not in standard library paths, assume it's local or third-party
    print(f"DEBUG: Module '{mod_name}' ({mod_file_abs}) considered local or third-party.")
    return False


def is_package_included(module_name, include_list=None, exclude_list=None):
    """
    Determines if a module should be included based on its name
    and inclusion/exclusion lists.

    Args:
        module_name: The module name as a string
        include_list: Optional list of package names to include
        exclude_list: Optional list of package names to exclude

    Returns:
        bool: True if the module should be included, False otherwise
    """
    # Validate input parameters
    if include_list and exclude_list:
        raise ValueError("Cannot specify both include_list and exclude_list")

    # Get the top-level package name (first part before any dots)
    top_package = module_name.split('.')[0]

    # Apply inclusion/exclusion rules
    if include_list is not None:
        # Include only if the module belongs to a package in the include list
        return top_package in include_list
    elif exclude_list is not None:
        # Include only if the module does NOT belong to a package in the exclude list
        return top_package not in exclude_list
    else:
        # No filtering, include all modules
        return True


def should_include_module(module_obj, include_list=None, exclude_list=None):
    """
    Determines if a module should be included based on standard library status
    and inclusion/exclusion lists.

    Args:
        module_obj: The module object to check
        include_list: Optional list of package names to include
        exclude_list: Optional list of package names to exclude

    Returns:
        bool: True if the module should be included, False otherwise

    Note:
        - Standard library modules are always excluded (returns False)
        - Cannot have both include_list and exclude_list defined simultaneously
        - If include_list is provided, only modules from those packages are included
        - If exclude_list is provided, modules from those packages are excluded
        - If neither list is provided, all non-stdlib modules are included
    """
    if not isinstance(module_obj, ModuleType):
        return False

    # First check if it's a standard library module - always exclude these
    if is_standard_library(module_obj):
        return False

    # Apply the inclusion/exclusion logic
    return is_package_included(module_obj.__name__, include_list, exclude_list)


def parse_target_string(target_str):
    """
    Parses 'path/to/module.py:function_name' into (absolute_path, function_name).
    Returns (None, None) on error.
    """
    print(f"DEBUG: Parsing target string: {target_str}")
    if ':' not in target_str:
        print(f"Error: Target format invalid. Expected 'path/to/module.py:function_name'. Got: {target_str}",
              file=sys.stderr)
        return None, None

    path_str, name = target_str.rsplit(':', 1)
    abs_path = os.path.abspath(path_str)

    # Basic validation - check if path exists *as a file* (can be relaxed if needed)
    # if not os.path.isfile(abs_path):
    #      print(f"Warning: Module path '{abs_path}' does not exist or is not a file.", file=sys.stderr)
    # Decide if this is a hard error or handled during loading
    # return None, None # Make it an error for now

    if not abs_path.endswith(".py"):
        print(f"Warning: Module path '{abs_path}' does not end with .py.", file=sys.stderr)
        # Allow non-.py files? Probably not for source analysis.
        # return None, None # Make it an error for now

    print(f"DEBUG: Parsed path='{abs_path}', name='{name}'")
    return abs_path, name


def load_target_function(module_path, function_name):
    """
    Dynamically loads a module from its path and returns the specified function object.
    Returns None on error. Assumes module_path is absolute.
    """
    print(f"DEBUG: Loading function '{function_name}' from module '{module_path}'")
    if not os.path.isfile(module_path):
        print(f"Error: Module file not found at {module_path}", file=sys.stderr)
        return None

    try:
        # Create a unique module name (e.g., based on path) to avoid conflicts
        # Using filename without extension is common but can collide.
        # Hashing the path could work, or replacing path separators.
        module_name_from_path = os.path.splitext(os.path.basename(module_path))[0]
        # A potentially more unique name:
        # unique_module_name = f"dynload_{module_name_from_path}_{hash(module_path)}"
        unique_module_name = module_name_from_path  # Keep it simple for now

        spec = importlib.util.spec_from_file_location(unique_module_name, module_path)
        if spec is None:
            print(f"Error: Could not create module spec for {module_path}", file=sys.stderr)
            return None

        module = importlib.util.module_from_spec(spec)
        if module is None:
            print(f"Error: Could not create module from spec for {module_path}", file=sys.stderr)
            return None

        # Add module to sys.modules BEFORE executing, crucial for relative imports within the module
        # if unique_module_name in sys.modules:
        # print(f"Warning: Module name {unique_module_name} already in sys.modules. Overwriting.")
        sys.modules[unique_module_name] = module

        # Add module's directory to sys.path temporarily to allow imports within that module
        module_dir = os.path.dirname(module_path)
        path_needs_cleanup = False
        if module_dir not in sys.path:
            sys.path.insert(0, module_dir)
            path_needs_cleanup = True

        # Execute the module's code
        spec.loader.exec_module(module)

        # Clean up sys.path if added
        if path_needs_cleanup and sys.path[0] == module_dir:
            sys.path.pop(0)

        target_obj = getattr(module, function_name, None)
        if target_obj is None:
            print(f"Error: Target '{function_name}' not found in module '{module_path}'", file=sys.stderr)
            # Maybe remove from sys.modules?
            # if unique_module_name in sys.modules: del sys.modules[unique_module_name]
            return None

        # Add check if it's a function or class (or maybe method directly?)
        if not isinstance(target_obj, (FunctionType, MethodType, type)):
            print(f"Error: Target '{function_name}' in module '{module_path}' is not a function, method, or class.",
                  file=sys.stderr)
            # if unique_module_name in sys.modules: del sys.modules[unique_module_name]
            return None

        print(f"DEBUG: Successfully loaded {target_obj}")
        return target_obj

    except FileNotFoundError:  # Should be caught by initial check, but belt-and-suspenders
        print(f"Error: Module file not found at {module_path}", file=sys.stderr)
        return None
    except SyntaxError as e:
        print(f"Error: Syntax error in module {module_path}: {e}", file=sys.stderr)
        # if unique_module_name in sys.modules: del sys.modules[unique_module_name] # Clean up failed load
        return None
    except Exception as e:
        print(f"Error loading module or function from {module_path}: {type(e).__name__} - {e}", file=sys.stderr)
        # if unique_module_name in sys.modules: del sys.modules[unique_module_name] # Clean up failed load
        return None


def get_object_source(obj):
    """
    Safely retrieves the source code for a Python object (function, method, class).
    Returns (source_code, absolute_file_path, start_line) or (None, None, None).
    """
    try:
        source_code = inspect.getsource(obj)
        file_path = inspect.getsourcefile(obj)
        start_line = inspect.getsourcelines(obj)[1]

        # Ensure file path is valid and absolute
        if not file_path or not os.path.exists(file_path):
            print(f"DEBUG: Skipping object {obj} - source file path '{file_path}' not found or invalid.")
            return None, None, None

        return source_code, os.path.abspath(file_path), start_line
    except (TypeError, OSError, IOError) as e:
        # TypeError: Built-ins, C extensions, dynamically created etc.
        # OSError/IOError: Source file not found/readable
        print(f"DEBUG: Could not get source for {obj}: {type(e).__name__} - {e}")
        return None, None, None
