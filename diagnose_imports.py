#!/usr/bin/env python3
"""Diagnostic script to find import errors."""

import sys
import traceback

# Add src to path
sys.path.insert(0, '/home/lehacf/the_castle_openai/castle_bot/src')

print("Testing imports step by step...")
print()

try:
    print("1. Importing config...")
    from castle.config import get_settings
    print("   ✓ config OK")
except Exception as e:
    print(f"   ✗ config FAILED: {e}")
    traceback.print_exc()
    sys.exit(1)

try:
    print("2. Importing logging...")
    from castle.logging import setup_logging
    print("   ✓ logging OK")
except Exception as e:
    print(f"   ✗ logging FAILED: {e}")
    traceback.print_exc()
    sys.exit(1)

try:
    print("3. Importing db...")
    from castle.db import make_engine
    print("   ✓ db OK")
except Exception as e:
    print(f"   ✗ db FAILED: {e}")
    traceback.print_exc()
    sys.exit(1)

try:
    print("4. Importing runner...")
    from castle.runner import init_db, run_loop
    print("   ✓ runner OK")
except Exception as e:
    print(f"   ✗ runner FAILED: {e}")
    traceback.print_exc()
    sys.exit(1)

try:
    print("5. Importing reporting...")
    from castle.reporting import write_json
    print("   ✓ reporting OK")
except Exception as e:
    print(f"   ✗ reporting FAILED: {e}")
    traceback.print_exc()
    sys.exit(1)

try:
    print("6. Importing cli...")
    from castle.cli import app
    print("   ✓ cli OK")
    print()
    print("All imports successful!")
except Exception as e:
    print(f"   ✗ cli FAILED: {e}")
    traceback.print_exc()
    sys.exit(1)
