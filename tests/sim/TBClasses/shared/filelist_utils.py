# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2024-2025 sean galloway
#
# RTL Design Sherpa - Industry-Standard RTL Design and Verification
# https://github.com/sean-galloway/RTLDesignSherpa
#
# Module: filelist_utils
# Purpose: Utility functions for processing RTL file lists in CocoTB tests.
#
# Documentation: cocotb-framework PyPI package
# Subsystem: framework
#
# Author: sean galloway
# Created: 2025-10-18

"""
Utility functions for processing RTL file lists in CocoTB tests.

This module provides helper functions to integrate the FileListProcessor
with CocoTB test runners, making it easy to use hierarchical .f file lists
instead of manually specifying verilog_sources in every test.

Usage Example:
    from TBClasses.shared.filelist_utils import get_sources_from_filelist

    def test_scheduler(request, ...):
        module, repo_root, tests_dir, log_dir, rtl_dict = get_paths({})

        # Get sources from file list (replaces manual verilog_sources list)
        verilog_sources, includes = get_sources_from_filelist(
            repo_root=repo_root,
            filelist_path='rtl/rapids/filelists/fub/scheduler.f'
        )

        run(
            verilog_sources=verilog_sources,
            includes=includes,
            ...
        )
"""

import os
import sys
from pathlib import Path


def rtl_root(repo_root):
    """Where the RTL and its filelists actually live.

    This repo ships verification infrastructure only — the RTL under
    test stays in RTLDesignSherpa. A caller here passes its own
    `repo_root`, which is the DV checkout, so every `$REPO_ROOT/rtl/...`
    path in a filelist would resolve into a tree that deliberately has
    no RTL in it. `RDS_RTL_PATH` (set by `env_python`) points at the RDS
    checkout; use it whenever the local repo has no `rtl/` of its own.

    Falls back to `repo_root` so a repo that does carry its own RTL, or
    a caller that already passed the RDS root, keeps working unchanged.
    """
    if os.path.isdir(os.path.join(repo_root, 'rtl')):
        return repo_root

    rds = os.environ.get('RDS_RTL_PATH')
    if rds and os.path.isdir(os.path.join(rds, 'rtl')):
        return rds

    raise FileNotFoundError(
        f"No RTL tree found. {repo_root} has no rtl/ directory (this repo "
        "ships verification infrastructure only), and RDS_RTL_PATH is "
        f"{'unset' if not rds else f'set to {rds!r}, which has no rtl/'}.\n"
        "Point RDS_RTL_PATH at an RTLDesignSherpa checkout, or "
        "`source env_python`, which auto-detects one."
    )


def _processor_dir(repo_root, rtl):
    """Directory holding file_list_processor.py, local copy first."""
    for candidate in (Path(repo_root), Path(rtl)):
        path = candidate / 'bin' / 'FileFolderFunctions'
        if (path / 'file_list_processor.py').exists():
            return path
    return Path(repo_root) / 'bin' / 'FileFolderFunctions'


def get_sources_from_filelist(repo_root, filelist_path):
    """
    Process an RTL file list and return verilog_sources and includes for CocoTB.

    Args:
        repo_root (str): Absolute path to repository root
        filelist_path (str): Relative path from repo_root to .f file
                             Example: 'rtl/rapids/filelists/fub/scheduler.f'

    Returns:
        tuple: (verilog_sources, includes)
            - verilog_sources: List of absolute paths to Verilog files
            - includes: List of absolute paths to include directories

    Example:
        verilog_sources, includes = get_sources_from_filelist(
            repo_root='/path/to/rtldesignsherpa',
            filelist_path='rtl/rapids/filelists/fub/scheduler.f'
        )

    File List Format:
        # Comments start with # or //
        +incdir+$REPO_ROOT/rtl/rapids/includes     # Include directory
        -f $REPO_ROOT/path/to/other.f            # Include another file list
        $REPO_ROOT/rtl/rapids/rapids_fub/module.sv   # Verilog source file

    Note:
        - Sets REPO_ROOT environment variable for file list processor
        - Automatically resolves -f directives (hierarchical inclusion)
        - Removes duplicates from final lists
    """
    # Import FileListProcessor (add to path if needed)
    rtl = rtl_root(repo_root)
    filelist_processor_dir = _processor_dir(repo_root, rtl)
    if str(filelist_processor_dir) not in sys.path:
        sys.path.insert(0, str(filelist_processor_dir))

    from file_list_processor import FileListProcessor

    # Set REPO_ROOT environment variable for substitution
    os.environ['REPO_ROOT'] = rtl

    # Set component root environment variables (from env_python)
    # These are used in filelists for referencing cross-component dependencies
    components_root = os.path.join(rtl, 'projects', 'components')
    os.environ['APB_XBAR_ROOT'] = os.path.join(components_root, 'apb_xbar')
    os.environ['BRIDGE_ROOT'] = os.path.join(components_root, 'bridge')
    os.environ['CONVERTERS_ROOT'] = os.path.join(components_root, 'converters')
    os.environ['RETRO_ROOT'] = os.path.join(components_root, 'retro_legacy_blocks')
    os.environ['STREAM_ROOT'] = os.path.join(components_root, 'dmas', 'stream')

    # Construct absolute path to file list
    filelist_abs = os.path.join(rtl, filelist_path)

    if not os.path.exists(filelist_abs):
        raise FileNotFoundError(
            f"File list not found: {filelist_abs}\n"
            f"  repo_root: {repo_root}\n"
            f"  filelist_path: {filelist_path}"
        )

    # Process file list
    processor = FileListProcessor([filelist_abs], debug=False)

    # Get resolved lists (may contain relative paths)
    verilog_sources_raw = processor.get_file_list()
    includes_raw = processor.get_include_list()

    # Get filelist directory for resolving relative paths
    filelist_dir = os.path.dirname(filelist_abs)

    # Bridge convention: paths in filelist are relative to parent of filelist directory
    # Example: filelist at rtl/filelists/bridge_1x2_wr.f, paths relative to rtl/
    base_dir = os.path.dirname(filelist_dir)

    # A filelist here can mix two roots: generated bridge RTL is listed
    # relative to THIS repo (`tests/sim/rtl/bridges/...`), while shared
    # RTL comes in as `$REPO_ROOT/rtl/...` against the RDS tree. So a
    # relative entry is tried against each plausible root and the one
    # that exists wins, rather than assuming a single base — assuming
    # base_dir alone doubles the prefix on the bridge entries.
    roots = [base_dir, repo_root, rtl]

    def _resolve(entry):
        for root in roots:
            candidate = os.path.normpath(os.path.join(root, entry))
            if os.path.exists(candidate):
                return candidate
        # Nothing matched; keep the historical base_dir form so the
        # simulator's error names a path someone can act on.
        return os.path.normpath(os.path.join(base_dir, entry))

    verilog_sources = [
        source if os.path.isabs(source) else _resolve(source)
        for source in verilog_sources_raw
    ]

    # Resolve include directories relative to base directory (same as verilog_sources)
    includes = []
    for inc in includes_raw:
        # First expand environment variables
        import re
        expanded = re.sub(r'\$(\w+)', lambda m: os.getenv(m.group(1), m.group(0)), inc)

        # Then resolve relative paths, same multi-root rule as sources
        includes.append(expanded if os.path.isabs(expanded)
                        else _resolve(expanded))

    return verilog_sources, includes


def get_sources_from_multiple_filelists(repo_root, filelist_paths):
    """
    Process multiple RTL file lists and merge results.

    Useful when a test needs files from multiple independent file lists
    that aren't hierarchically related via -f directives.

    Args:
        repo_root (str): Absolute path to repository root
        filelist_paths (list): List of relative paths to .f files

    Returns:
        tuple: (verilog_sources, includes) - merged and deduplicated

    Example:
        verilog_sources, includes = get_sources_from_multiple_filelists(
            repo_root='/path/to/rtldesignsherpa',
            filelist_paths=[
                'rtl/rapids/filelists/fub/scheduler.f',
                'rtl/common/filelists/utilities.f'
            ]
        )
    """
    # Import FileListProcessor
    rtl = rtl_root(repo_root)
    filelist_processor_dir = _processor_dir(repo_root, rtl)
    if str(filelist_processor_dir) not in sys.path:
        sys.path.insert(0, str(filelist_processor_dir))

    from file_list_processor import FileListProcessor, remove_dups_from_list

    # Set REPO_ROOT environment variable
    os.environ['REPO_ROOT'] = rtl

    # Construct absolute paths
    filelist_abs_paths = [os.path.join(rtl, fp) for fp in filelist_paths]

    # Check all exist
    for filelist_abs in filelist_abs_paths:
        if not os.path.exists(filelist_abs):
            raise FileNotFoundError(f"File list not found: {filelist_abs}")

    # Process all file lists
    processor = FileListProcessor(filelist_abs_paths, debug=False)

    # Get merged, deduplicated lists
    verilog_sources = processor.get_file_list()
    includes = processor.get_include_list()

    return verilog_sources, includes


def debug_filelist(repo_root, filelist_path, output_file='filelist_debug.txt'):
    """
    Debug helper: Process file list and write detailed debug output.

    Args:
        repo_root (str): Absolute path to repository root
        filelist_path (str): Relative path to .f file
        output_file (str): Where to write debug output

    Returns:
        tuple: (verilog_sources, includes)

    Side Effects:
        Writes debug information to output_file showing:
        - All processed files
        - Hierarchy of -f inclusions
        - Final deduplicated lists

    Example:
        verilog_sources, includes = debug_filelist(
            repo_root='/path/to/rtldesignsherpa',
            filelist_path='rtl/rapids/filelists/macro/scheduler_group.f',
            output_file='scheduler_group_debug.txt'
        )
        # Check scheduler_group_debug.txt for processing details
    """
    # Import FileListProcessor
    rtl = rtl_root(repo_root)
    filelist_processor_dir = _processor_dir(repo_root, rtl)
    if str(filelist_processor_dir) not in sys.path:
        sys.path.insert(0, str(filelist_processor_dir))

    from file_list_processor import FileListProcessor

    # Set REPO_ROOT environment variable
    os.environ['REPO_ROOT'] = rtl

    # Construct absolute path
    filelist_abs = os.path.join(rtl, filelist_path)

    if not os.path.exists(filelist_abs):
        raise FileNotFoundError(f"File list not found: {filelist_abs}")

    # Process with debug enabled
    processor = FileListProcessor([filelist_abs], debug=True)

    # Get results
    verilog_sources = processor.get_file_list()
    includes = processor.get_include_list()

    print(f"✓ Debug output written to: {output_file}")
    print(f"  Verilog sources: {len(verilog_sources)} files")
    print(f"  Include dirs: {len(includes)} directories")

    return verilog_sources, includes
