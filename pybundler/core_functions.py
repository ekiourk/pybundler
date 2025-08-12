import importlib.util
import inspect
import logging
import os
import sys
import sysconfig
from types import ModuleType, FunctionType, MethodType

log = logging.getLogger(__name__)


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
        log.warning("Could not reliably determine standard library path(s). Filtering might be inaccurate.")
    else:
        log.debug("Identified standard library paths for exclusion: %s", stdlib_paths)

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
            log.debug("Module '%s' has no discernible file path.", module_obj.__name__)
            return None
        return os.path.normpath(os.path.abspath(mod_file))
    except TypeError:
        # This often happens for built-in modules or C extensions without clear file paths
        log.debug("Module '%s' likely built-in or C extension (TypeError on getfile).", module_obj.__name__)
        return None


def is_standard_library(module_obj):
    """
    Checks if a module is likely part of the Python standard library installation
    or a built-in module.
    Returns True if it IS part of stdlib/builtin, False otherwise (local/third-party).
    """
    if not isinstance(module_obj, ModuleType):
        return False

    mod_name = module_obj.__name__

    if mod_name in sys.builtin_module_names:
        log.debug("Module '%s' is built-in.", mod_name)
        return True

    mod_file_abs = get_module_file_path(module_obj)
    if mod_file_abs is None:
        return False

    stdlib_paths = get_stdlib_paths()
    if not stdlib_paths:
        log.warning("Cannot check stdlib paths for %s. Assuming non-stdlib.", mod_name)
        return False

    for std_path in stdlib_paths:
        if mod_file_abs.startswith(std_path + os.sep):
            log.debug("Module '%s' (%s) is within standard library path '%s'.", mod_name, mod_file_abs, std_path)
            return True

    log.debug("Module '%s' (%s) considered local or third-party.", mod_name, mod_file_abs)
    return False


def is_third_party_module(module_obj):
    """
    Checks if a module is a third-party module (i.e., installed in site-packages).
    """
    if not isinstance(module_obj, ModuleType):
        return False

    mod_file_abs = get_module_file_path(module_obj)
    if mod_file_abs is None:
        return False

    is_third_party = 'site-packages' in mod_file_abs
    if is_third_party:
        log.debug("Module '%s' (%s) is a third-party module.", module_obj.__name__, mod_file_abs)
    return is_third_party


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


def should_include_module(module_obj, include_list=None, exclude_list=None, exclude_third_party=False):
    """
    Determines if a module should be included based on standard library status,
    third-party status, and inclusion/exclusion lists.
    """
    if not isinstance(module_obj, ModuleType):
        return False

    if is_standard_library(module_obj):
        return False

    if exclude_third_party and is_third_party_module(module_obj):
        return False

    return is_package_included(module_obj.__name__, include_list, exclude_list)


def parse_target_string(target_str):
    """
    Parses 'path/to/module.py:function_name' into (absolute_path, function_name).
    Returns (None, None) on error.
    """
    log.debug("Parsing target string: %s", target_str)
    if ':' not in target_str:
        log.error("Target format invalid. Expected 'path/to/module.py:function_name'. Got: %s", target_str)
        return None, None

    path_str, name = target_str.rsplit(':', 1)
    abs_path = os.path.abspath(path_str)

    if not abs_path.endswith(".py"):
        log.warning("Module path '%s' does not end with .py.", abs_path)

    log.debug("Parsed path='%s', name='%s'", abs_path, name)
    return abs_path, name


def load_target_function(module_path, function_name):
    """
    Dynamically loads a module from its path and returns the specified function object.
    Returns None on error. Assumes module_path is absolute.
    """
    log.debug("Loading function '%s' from module '%s'", function_name, module_path)
    if not os.path.isfile(module_path):
        log.error("Module file not found at %s", module_path)
        return None

    try:
        module_name_from_path = os.path.splitext(os.path.basename(module_path))[0]
        unique_module_name = module_name_from_path

        spec = importlib.util.spec_from_file_location(unique_module_name, module_path)
        if spec is None:
            log.error("Could not create module spec for %s", module_path)
            return None

        module = importlib.util.module_from_spec(spec)
        if module is None:
            log.error("Could not create module from spec for %s", module_path)
            return None

        sys.modules[unique_module_name] = module

        module_dir = os.path.dirname(module_path)
        path_needs_cleanup = False
        if module_dir not in sys.path:
            sys.path.insert(0, module_dir)
            path_needs_cleanup = True

        spec.loader.exec_module(module)

        if path_needs_cleanup and sys.path[0] == module_dir:
            sys.path.pop(0)

        target_obj = getattr(module, function_name, None)
        if target_obj is None:
            log.error("Target '%s' not found in module '%s'", function_name, module_path)
            return None

        if not isinstance(target_obj, (FunctionType, MethodType, type)):
            log.error("Target '%s' in module '%s' is not a function, method, or class.", function_name, module_path)
            return None

        log.debug("Successfully loaded %s", target_obj)
        return target_obj

    except FileNotFoundError:
        log.error("Module file not found at %s", module_path)
        return None
    except SyntaxError as e:
        log.error("Syntax error in module %s: %s", module_path, e)
        return None
    except Exception as e:
        log.error("Error loading module or function from %s: %s - %s", module_path, type(e).__name__, e)
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

        if not file_path or not os.path.exists(file_path):
            log.debug("Skipping object %s - source file path '%s' not found or invalid.", obj, file_path)
            return None, None, None

        return source_code, os.path.abspath(file_path), start_line
    except (TypeError, OSError, IOError) as e:
        log.debug("Could not get source for %s: %s - %s", obj, type(e).__name__, e)
        return None, None, None
