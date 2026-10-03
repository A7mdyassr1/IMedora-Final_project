"""
Runs every validate_phaseN.py in order with one command. Stops at the
first failure (each script raises on its first failed check).

Run with:
    python database/tests/run_all.py
"""
import runpy
import sys
from pathlib import Path

PHASES = [1, 2, 3, 4, 5, 6]


def run():
    tests_dir = Path(__file__).parent
    for phase in PHASES:
        script = tests_dir / f"validate_phase{phase}.py"
        print(f"\n=== validate_phase{phase}.py ===")
        try:
            runpy.run_path(str(script), run_name="__main__")
        except Exception as exc:
            print(f"validate_phase{phase}.py failed: {exc}", file=sys.stderr)
            raise
    print("\nAll validation suites passed - Phases 1-6, full schema.")


if __name__ == "__main__":
    run()
