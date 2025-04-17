#!/usr/bin/env python3

import argparse
import datetime
import sys

from pybundler.core_functions import parse_target_string, load_target_function
from pybundler.dependency_bundler import collected_source, run_dependency_analysis


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
    args = parser.parse_args()

    # 1. Parse Input
    module_path, target_name = parse_target_string(args.target)
    if not module_path or not target_name:
        sys.exit(1)

    # 2. Load Target Object (Function or Class)
    initial_target_obj = load_target_function(module_path, target_name)
    if not initial_target_obj:
        sys.exit(1)

    # 3. *** Run the core analysis using the dedicated function ***
    run_dependency_analysis(initial_target_obj)

    # 4. Collate and Output (operates on the global collected_source)
    if not collected_source:
        print("Warning: No source code was collected.")
        # Handle writing empty file as before...
        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(f"# No Python source dependencies found for "
                        f"{args.target} at {datetime.datetime.now().isoformat()}\n")
            print(f"Wrote empty marker file to: {args.output}")
        except IOError as e:
            print(f"Error: Failed to write empty output file '{args.output}': {e}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    all_code = join_all_sources(collected_source)

    # 5. Write Output
    # Add a header to the final output file
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
        print(f"Successfully wrote bundled source code to: {args.output}")
    except IOError as e:
        print(f"Error: Failed to write output file '{args.output}': {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
