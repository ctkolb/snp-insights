# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 ctkolb
"""Module entrypoint: `python -m snp_insights`."""
import sys

from snp_insights.cli import main

if __name__ == "__main__":
    sys.exit(main())
