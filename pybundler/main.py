#!/usr/bin/env python3

import argparse
import datetime
import logging
import sys

from pybundler.core_functions import parse_target_string, load_target_function
from pybundler.dependency_bundler import DependencyBundler

log = logging.getLogger(__name__)


def setup_logging(log_level):
    """Configure the root logger."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(level=level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


def join_all_sources(sources):
    # Sort collected source code by file path and then by line number
    sorted_sources = sorted(sources.items(), key=lambda item: item[0])
    all_code = "\n\n".join([code for _, code in sorted_sources])
    return all_code


def main():
    parser = argparse.ArgumentParser(
        description="Finds all Python dependencies of a function/class and bundles their source code."
    )
    parser.add_argument(
        "target",
        help="Target in format 'path/to/module.py:function_or_class_name'",
    )
    parser.add_argument(
        "-o", "--output",
        help="Path to the output file for bundled source code.",
        default="bundler_output.py"
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Set the logging level (default: info)."
    )
    args = parser.parse_args()

    setup_logging(args.log_level)

    # 1. Parse Input
    module_path, target_name = parse_target_string(args.target)
    if not module_path or not target_name:
        sys.exit(1)

    # 2. Load Target Object (Function or Class)
    initial_target_obj = load_target_function(module_path, target_name)
    if not initial_target_obj:
        sys.exit(1)

    # 3. *** Run the core analysis using the dedicated function ***
    bundler = DependencyBundler()
    collected_source = bundler.run_dependency_analysis(initial_target_obj)

    # 4. Collate and Output
    if not collected_source:
        log.warning("No source code was collected.")
        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(f"# No Python source dependencies found for "
                        f"{args.target} at {datetime.datetime.now().isoformat()}\n")
            log.info("Wrote empty marker file to: %s", args.output)
        except IOError as e:
            log.error("Failed to write empty output file '%s': %s", args.output, e)
            sys.exit(1)
        sys.exit(0)

    all_code = join_all_sources(collected_source)

    # 5. Write Output
    output_header = f"""#################################################################
    # Bundled Python code for target: {args.target}
    # Generated on: {datetime.datetime.now(datetime.timezone.utc).isoformat()}
    # Current time is: {datetime.datetime.now().astimezone().isoformat()}
    #
    # This file contains the source code of the target and its
    # discovered non-standard-library Python dependencies. Order is
    # based on file path and line number, not necessarily execution order.
    #################################################################

    """
    final_output = output_header + all_code
    try:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(final_output)
        log.info("Successfully wrote bundled source code to: %s", args.output)
    except IOError as e:
        log.error("Failed to write output file '%s': %s", args.output, e)
        sys.exit(1)


if __name__ == "__main__":
    main()
