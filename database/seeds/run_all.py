"""
Runs every seed_phaseN.py in the correct order with one command.

Run with:
    python database/seeds/run_all.py
"""
import runpy
import sys
from pathlib import Path

PHASES = [1, 2, 3, 4, 5, 6]


def run():
    seeds_dir = Path(__file__).parent
    for phase in PHASES:
        script = seeds_dir / f"seed_phase{phase}.py"
        print(f"\n=== seed_phase{phase}.py ===")
        try:
            runpy.run_path(str(script), run_name="__main__")
        except Exception as exc:
            print(f"seed_phase{phase}.py failed: {exc}", file=sys.stderr)
            raise
    print("\nAll seed scripts completed.")


if __name__ == "__main__":
    run()
