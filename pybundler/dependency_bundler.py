import ast
import inspect
import os
import sys
import textwrap
import typing
from collections import deque  # Good for the processing queue
from types import FunctionType, MethodType  # Note: Add ClassType or other types if needed

from pybundler.core_functions import should_include_module, get_object_source

MAX_PROCESSED = 1000

# --- Globals for tracking state ---
# TODO: Create a class that will keep the state

# Store IDs of objects already processed to prevent cycles and redundant work
processed_object_ids = set()

# Store collected source code fragments. Using a dict keyed by unique identifier
# (e.g., file path + start line) might prevent duplicates better than a list.
# Key: (absolute_filepath, start_line), Value: source_code_string_with_header
collected_source = {}

# Queue of objects (functions, methods, classes) to analyze
# Using deque for efficient pops from the left
objects_to_process = deque()


class DependencyFinder(ast.NodeVisitor):
    """
    An AST visitor that finds potential dependencies (names, attributes)
    within a code object's AST.
    """

    def __init__(self, global_vars):
        """
        Initialize the visitor.
        Args:
            global_vars (dict): The global namespace where the code was defined.
        """
        self.global_vars = global_vars
        # Use a set to store the resolved dependency *objects* found
        self.potential_dependencies = set()
        # Keep track of names defined locally within the AST scope (functions, args, assignments)
        # to avoid resolving them as globals mistakenly. Basic implementation.
        self.local_names = set()

    def resolve_name(self, name_str):
        """Tries to resolve a name in the global scope."""
        # Avoid resolving names we know are local to the visited scope
        if name_str in self.local_names:
            return None
        return self.global_vars.get(name_str)  # Use .get() for safe lookup

    # Keep track of local assignments/definitions
    def visit_Assign(self, node):
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.local_names.add(target.id)
        self.generic_visit(node)  # Visit value side too

    def visit_FunctionDef(self, node):
        self.local_names.add(node.name)  # Function name is local
        # Add arguments to local names for this scope (won't persist outside correctly)
        # A more robust implementation would handle scopes properly.
        arg_names = set(arg.arg for arg in node.args.args)
        self.local_names.update(arg_names)
        self.generic_visit(node)  # If we want to analyze inside nested functions

    def visit_AsyncFunctionDef(self, node):
        self.visit_FunctionDef(node)  # Treat same as sync function for name tracking

    def visit_ClassDef(self, node):
        self.local_names.add(node.name)  # Class name is local
        self.generic_visit(node)

    def visit_Name(self, node):
        """Visits a Name node (variable, function call name, etc.)."""
        # Only interested in names being loaded/used, not stored/deleted
        if isinstance(node.ctx, ast.Load):
            resolved_obj = self.resolve_name(node.id)
            # TODO: refactor to store and none hashable objects
            if resolved_obj and isinstance(resolved_obj, typing.Hashable):
                # print(f"AST Name: Found '{node.id}' -> Resolved to {type(resolved_obj)}")
                self.potential_dependencies.add(resolved_obj)

    def visit_Attribute(self, node):
        """Visits an Attribute node (e.g., module.function, instance.method)."""
        # Only interested if the attribute is being loaded/used
        if isinstance(node.ctx, ast.Load):
            # Try to resolve the base of the attribute access (e.g., 'os' in 'os.path')
            # Only handle simple case where the base is a Name node
            if isinstance(node.value, ast.Name):
                base_obj = self.resolve_name(node.value.id)
                if base_obj:
                    try:
                        # Get the attribute from the resolved base object
                        attr_obj = getattr(base_obj, node.attr, None)
                        if attr_obj:
                            # print(f"AST Attribute: Found '{node.value.id}.{node.attr}' -> Resolved to {type(attr_obj)}")
                            self.potential_dependencies.add(attr_obj)
                    except Exception as e:
                        # getattr can fail for various reasons
                        # print(f"Could not getattr {node.attr} from {base_obj}: {e}")
                        pass

        # IMPORTANT: Continue traversal down the 'value' part of the attribute
        # (e.g., in 'a.b.c', we need to visit 'a.b' first)
        self.visit(node.value)

    # Potential future improvements:
    # - visit_Call: Analyze the 'func' part of the call. If it resolves to a class,
    #   it's an instantiation. If a function, it's a call. Add resolved object.
    # - visit_Import / visit_ImportFrom: Could potentially build a local name mapping,
    #   but relying on obj_globals passed in is usually sufficient.
    # - Scope handling: Proper tracking of local variables vs globals/nonlocals.


def find_and_queue_dependencies(obj, obj_globals):
    """
    Analyzes an object (function/method/class) using AST parsing
    to find its non-standard-library dependencies and queues them.
    """
    # Avoid analyzing the same object multiple times via AST if found via different paths
    # Note: processed_object_ids already prevents adding to queue multiple times,
    # but this prevents redundant AST parsing if called directly multiple times.

    print(f"Analyzing dependencies for: {obj} using AST")

    source_code, file_path, start_line = get_object_source(obj)

    # --- Handle Classes: Base classes and methods ---
    if isinstance(obj, type):
        # Process base classes first (if not object)
        for base in obj.__bases__:
            if base is not object:  # Don't process 'object' base class
                print(f"  -> Processing base class: {base}")
                process_dependency(base)  # Queue the base class itself for analysis

        # Queue methods defined directly in this class for analysis
        # Do this regardless of whether we get source for the class itself
        print(f"  -> Queueing methods defined in class {obj.__name__}")
        for name, member in inspect.getmembers(obj):
            if isinstance(member, (FunctionType, MethodType)):
                try:
                    # Check if the method was likely defined in this class's source file
                    member_file = inspect.getsourcefile(member)
                    # Check if we have a file_path for the class itself to compare
                    # Use file_path obtained earlier if available
                    if member_file and file_path and member_file == file_path:
                        # A simple check: if method's source file matches class's source file
                        print(f"    -> Queueing own method: {name}")
                        process_dependency(member)  # Queue the method itself
                    elif inspect.getmodule(member) == inspect.getmodule(obj):
                        # Fallback: check if modules match if file check fails/not possible
                        # This might queue inherited methods if files differ but modules match
                        print(f"    -> Queueing method by module match: {name}")
                        process_dependency(member)
                except (TypeError, OSError, AttributeError):
                    # Cannot get source/module/file info, skip queueing this member
                    print(f"    -> Skipping method {name} (cannot get source/module info)")
                    pass

    # --- AST Analysis (only if source code is available) ---
    if not source_code:
        print(f"  -> Cannot get source code for {obj}. Skipping AST analysis.")
        return  # Cannot proceed with AST

    try:
        # Use unparse from ast if available (Python 3.9+) for potentially better round-tripping?
        # Or just parse the raw source. Raw source is fine.
        # Dedent source code first to handle methods correctly
        tree = ast.parse(textwrap.dedent(source_code))
    except SyntaxError as e:
        print(f"  -> SyntaxError parsing source for {obj} (line {e.lineno}): {e}. Skipping AST analysis.")
        return
    except Exception as e:
        print(f"  -> Error parsing source for {obj} with AST: {type(e).__name__} - {e}. Skipping AST analysis.")
        return

    # Create and run the visitor
    # Pass the globals dictionary associated with the object being analyzed
    finder = DependencyFinder(global_vars=obj_globals)
    try:
        finder.visit(tree)
    except Exception as e:
        print(f"  -> Error visiting AST nodes for {obj}: {type(e).__name__} - {e}. Analysis may be incomplete.")
        # Continue to process whatever was found before the error

    # Process all potential dependencies found by the visitor
    print(f"  -> AST analysis found {len(finder.potential_dependencies)} potential dependencies to check.")
    num_queued = 0
    for dep_obj in finder.potential_dependencies:
        # Let process_dependency handle all filtering (stdlib, type, source, visited) and queueing
        original_queue_size = len(objects_to_process)
        process_dependency(dep_obj)
        if len(objects_to_process) > original_queue_size:
            num_queued += 1

    print(f"  -> Queued {num_queued} new dependencies from AST analysis "
          f"of {obj.__name__ if hasattr(obj, '__name__') else type(obj).__name__}.")


def process_dependency(dep_obj):
    """
    Checks if a potential dependency object is valid
    (Python source, not stdlib/builtin, not processed, included/excluded lists)
    and adds it to the processing queue.
    """
    obj_id = id(dep_obj)
    # Avoid cycles and redundant processing
    if obj_id in processed_object_ids or dep_obj in objects_to_process:
        return

    # Filter out objects we cannot or should not get source for
    # Only process functions, methods, and classes
    if not isinstance(dep_obj, (FunctionType, MethodType, type)):
        return

    # Get the module where the dependency is defined
    try:
        module = inspect.getmodule(dep_obj)
        if module is None:
            # If we can't get the module, we can't check if it's stdlib.
            # Should we include based only on get_object_source? Risky.
            # Let's exclude if module is unknown.
            print(f"DEBUG: Skipping dependency {dep_obj} - could not determine defining module.")
            return
    except Exception as e:
        print(f"DEBUG: Error getting module for dependency {dep_obj}: {e}")
        return  # Exclude if error occurs

    if not should_include_module(module):
        # If it is should not be included, SKIP processing it further
        return

    # If we reach here, it's NOT standard library/builtin.
    # Now check if we can actually retrieve Python source code for it
    source_code, src_file, start_line = get_object_source(dep_obj)
    if source_code is None or src_file is None:
        print(f"DEBUG: Skipping non-stdlib dependency {dep_obj} - "
              f"cannot retrieve its source code (maybe C extension?).")
        return

    # If all checks pass add to queue to be processed
    print(f"DEBUG: Queuing dependency: {dep_obj} (id={obj_id}, module='{module.__name__}')")
    objects_to_process.append(dep_obj)


def run_dependency_analysis(start_obj):
    """
    Runs the full dependency analysis loop starting from start_obj.
    Populates the global collected_source dictionary. Clears previous state.
    """
    # Reset state before analysis run
    processed_object_ids.clear()
    collected_source.clear()
    objects_to_process.clear()

    if not start_obj:
        print("Error: Cannot start analysis with None object.", file=sys.stderr)
        return  # Or raise an error

    objects_to_process.append(start_obj)
    print(f"--- Starting dependency analysis run for {start_obj} ---")

    processed_count = 0
    max_processed = MAX_PROCESSED  # Safety break for complex cases or potential loops

    while objects_to_process:
        if processed_count >= max_processed:
            print(f"Warning: Reached processing limit ({max_processed}). Stopping analysis.", file=sys.stderr)
            break
        current_obj = objects_to_process.popleft()  # FIFO processing
        processed_count += 1

        obj_id = id(current_obj)
        if obj_id in processed_object_ids:
            continue  # Skip if already processed

        processed_object_ids.add(obj_id)
        # Optional: Reduced debug noise during runs
        # print(f"\nProcessing ({processed_count}): {current_obj}")

        # Get and store source code for the current object
        source_code, file_path, start_line = get_object_source(current_obj)
        if source_code and file_path and start_line:
            source_key = (file_path, start_line)  # abs path from get_object_source
            if source_key not in collected_source:
                # Format header comment
                try:
                    rel_path = os.path.relpath(file_path)
                except ValueError:
                    rel_path = file_path  # Use abs path if relpath fails
                # Try to get a qualified name if possible for the header
                obj_name = getattr(current_obj, '__qualname__',
                                   getattr(current_obj, '__name__', str(type(current_obj))))
                header = f"# --- Source from: {rel_path} Line: {start_line} Object: {obj_name} ---"
                collected_source[source_key] = f"{header}\n{source_code}"
                # print(f"  (+) Collected source: {rel_path} (line {start_line})")

        # Find *its* dependencies and queue them
        # Requires the object's defining module's globals to resolve names
        try:
            obj_module = inspect.getmodule(current_obj)
            if obj_module:
                # Call the function responsible for finding dependencies within current_obj
                find_and_queue_dependencies(current_obj, obj_module.__dict__)
            else:  # Decided earlier not to analyze if module unknown
                print(f"Warning: Could not determine module for {current_obj}, dependency analysis may be incomplete.",
                      file=sys.stderr)
        except Exception as e:
            print(f"Error during dependency analysis call for {current_obj}: {e}", file=sys.stderr)
            # Decide whether to continue or stop on error

    print(f"--- Dependency analysis run complete. Processed {processed_count} objects."
          f"Collected {len(collected_source)} source fragments. ---")
