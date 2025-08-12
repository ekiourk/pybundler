import ast
import inspect
import logging
import os
import textwrap
import typing
from collections import deque
from types import FunctionType, MethodType

from pybundler.core_functions import should_include_module, get_object_source

log = logging.getLogger(__name__)

EXCLUDE_PACKAGES = []  # ['sqlalchemy', 'chardet', 'click']


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
        self.potential_dependencies = set()
        self.local_names = set()

    def resolve_name(self, name_str):
        """Tries to resolve a name in the global scope."""
        if name_str in self.local_names:
            return None
        return self.global_vars.get(name_str)

    def visit_Assign(self, node):
        """
        Visit an Assign node to identify local variable assignments.
        This helps in distinguishing between local variables and global dependencies.
        """
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.local_names.add(target.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        """
        Visit a FunctionDef node to identify local function definitions and arguments.
        This prevents misidentifying them as global dependencies.
        """
        self.local_names.add(node.name)
        arg_names = set(arg.arg for arg in node.args.args)
        self.local_names.update(arg_names)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        """
        Visit an AsyncFunctionDef node, treating it like a synchronous function
        for dependency analysis.
        """
        self.visit_FunctionDef(node)

    def visit_ClassDef(self, node):
        """
        Visit a ClassDef node to identify local class definitions.
        This prevents misidentifying them as global dependencies.
        """
        self.local_names.add(node.name)
        self.generic_visit(node)

    def visit_Name(self, node):
        """Visits a Name node (variable, function call name, etc.)."""
        if isinstance(node.ctx, ast.Load):
            resolved_obj = self.resolve_name(node.id)
            if resolved_obj and isinstance(resolved_obj, typing.Hashable):
                self.potential_dependencies.add(resolved_obj)

    def visit_Attribute(self, node):
        """Visits an Attribute node (e.g., module.function, instance.method)."""
        if isinstance(node.ctx, ast.Load):
            if isinstance(node.value, ast.Name):
                base_obj = self.resolve_name(node.value.id)
                if base_obj:
                    try:
                        attr_obj = getattr(base_obj, node.attr, None)
                        if attr_obj:
                            self.potential_dependencies.add(attr_obj)
                    except Exception:
                        pass
        self.visit(node.value)


class DependencyBundler:
    """
    Analyzes and bundles the source code of a target object and its dependencies.
    """
    MAX_PROCESSED = 1000

    def __init__(self, exclude_third_party=False):
        """
        Initializes the DependencyBundler, setting up the state for a new analysis run.
        """
        self.processed_object_ids = set()
        self.collected_source = {}
        self.objects_to_process = deque()
        self.exclude_third_party = exclude_third_party

    def find_and_queue_dependencies(self, obj, obj_globals):
        """
        Analyzes an object using AST parsing to find and queue its dependencies.
        """
        log.info("Analyzing dependencies for: %s using AST", obj)
        source_code, file_path, start_line = get_object_source(obj)

        if isinstance(obj, type):
            for base in obj.__bases__:
                if base is not object:
                    log.info("  -> Processing base class: %s", base)
                    self.process_dependency(base)
            log.info("  -> Queueing methods defined in class %s", obj.__name__)
            for name, member in inspect.getmembers(obj):
                if isinstance(member, (FunctionType, MethodType)):
                    try:
                        member_file = inspect.getsourcefile(member)
                        if member_file and file_path and member_file == file_path:
                            log.info("    -> Queueing own method: %s", name)
                            self.process_dependency(member)
                        elif inspect.getmodule(member) == inspect.getmodule(obj):
                            log.info("    -> Queueing method by module match: %s", name)
                            self.process_dependency(member)
                    except (TypeError, OSError, AttributeError):
                        log.warning("    -> Skipping method %s (cannot get source/module info)", name)
                        pass

        if not source_code:
            log.warning("  -> Cannot get source code for %s. Skipping AST analysis.", obj)
            return

        try:
            tree = ast.parse(textwrap.dedent(source_code))
        except (SyntaxError, Exception) as e:
            log.error("  -> Error parsing source for %s with AST: %s - %s. Skipping AST analysis.", obj,
                      type(e).__name__, e)
            return

        finder = DependencyFinder(global_vars=obj_globals)
        try:
            finder.visit(tree)
        except Exception as e:
            log.error("  -> Error visiting AST nodes for %s: %s - %s. Analysis may be incomplete.", obj,
                      type(e).__name__, e)

        log.info("  -> AST analysis found %d potential dependencies to check.", len(finder.potential_dependencies))
        num_queued = 0
        for dep_obj in finder.potential_dependencies:
            original_queue_size = len(self.objects_to_process)
            self.process_dependency(dep_obj)
            if len(self.objects_to_process) > original_queue_size:
                num_queued += 1
        log.info("  -> Queued %d new dependencies from AST analysis of %s.", num_queued,
                 getattr(obj, '__name__', type(obj).__name__))

    def process_dependency(self, dep_obj):
        """
        Checks if a dependency is valid and adds it to the processing queue.
        """
        obj_id = id(dep_obj)
        if obj_id in self.processed_object_ids or dep_obj in self.objects_to_process:
            return

        if not isinstance(dep_obj, (FunctionType, MethodType, type)):
            # The dependency is an instance of a class. We should try to process
            # the class itself.
            dep_type = type(dep_obj)
            try:
                # We check if the class's module is one we should include, to avoid
                # bundling the classes of built-in objects like integers or strings.
                module = inspect.getmodule(dep_type)
                if module and should_include_module(module, exclude_list=EXCLUDE_PACKAGES,
                                                     exclude_third_party=self.exclude_third_party):
                    log.debug("Processing class '%s' from instance dependency.", dep_type.__name__)
                    self.process_dependency(dep_type)
            except Exception as e:
                log.debug("Could not process class for instance dependency %s: %s", dep_obj, e)
            return

        try:
            module = inspect.getmodule(dep_obj)
            if module is None:
                log.debug("Skipping dependency %s - could not determine defining module.", dep_obj)
                return
        except Exception as e:
            log.debug("Error getting module for dependency %s: %s", dep_obj, e)
            return

        if not should_include_module(module, exclude_list=EXCLUDE_PACKAGES,
                                     exclude_third_party=self.exclude_third_party):
            return

        source_code, src_file, start_line = get_object_source(dep_obj)
        if source_code is None or src_file is None:
            log.debug("Skipping non-stdlib dependency %s - cannot retrieve its source code.", dep_obj)
            return

        log.debug("Queuing dependency: %s (id=%s, module='%s')", dep_obj, obj_id, module.__name__)
        self.objects_to_process.append(dep_obj)

    def run_dependency_analysis(self, start_obj):
        """
        Runs the dependency analysis loop and returns the collected source code.
        """
        if not start_obj:
            log.error("Cannot start analysis with None object.")
            return {}

        self.objects_to_process.append(start_obj)
        log.info("--- Starting dependency analysis run for %s ---", start_obj)

        processed_count = 0
        while self.objects_to_process:
            if processed_count >= self.MAX_PROCESSED:
                log.warning("Reached processing limit (%d). Stopping analysis.", self.MAX_PROCESSED)
                break
            current_obj = self.objects_to_process.popleft()
            processed_count += 1

            obj_id = id(current_obj)
            if obj_id in self.processed_object_ids:
                continue

            self.processed_object_ids.add(obj_id)

            # To handle decorated functions, we need to unwrap them. We check for
            # common attributes that point to the original function. This handles
            # decorators that create wrapper objects and those that use functools.wraps.
            if not isinstance(current_obj, type):  # Don't check attributes on classes
                for attr in ['__wrapped__', 'callback', 'func', 'function']:
                    if hasattr(current_obj, attr):
                        wrapped_func = getattr(current_obj, attr)
                        if callable(wrapped_func):
                            log.debug("Found potential wrapped function in attribute '%s': %s", attr, wrapped_func)
                            self.process_dependency(wrapped_func)

            # If the object is a function/method, also check its closure for other functions/classes.
            if isinstance(current_obj, (FunctionType, MethodType)) and hasattr(current_obj, '__closure__'):
                if current_obj.__closure__:
                    for cell in current_obj.__closure__:
                        closed_obj = cell.cell_contents
                        self.process_dependency(closed_obj)

            source_code, file_path, start_line = get_object_source(current_obj)
            if source_code and file_path and start_line:
                source_key = (file_path, start_line)
                if source_key not in self.collected_source:
                    try:
                        rel_path = os.path.relpath(file_path)
                    except ValueError:
                        rel_path = file_path
                    obj_name = getattr(current_obj, '__qualname__',
                                       getattr(current_obj, '__name__', str(type(current_obj))))
                    header = f"# --- Source from: {rel_path} Line: {start_line} Object: {obj_name} ---"
                    self.collected_source[source_key] = f"{header}\n{source_code}"

            try:
                obj_module = inspect.getmodule(current_obj)
                if obj_module:
                    self.find_and_queue_dependencies(current_obj, obj_module.__dict__)
                else:
                    log.warning("Could not determine module for %s, dependency analysis may be incomplete.", current_obj)
            except Exception as e:
                log.error("Error during dependency analysis call for %s: %s", current_obj, e)

        log.info("--- Dependency analysis run complete. Processed %d objects. Collected %d source fragments. ---",
                 processed_count, len(self.collected_source))
        return self.collected_source
