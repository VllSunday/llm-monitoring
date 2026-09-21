"""Полный прогон всех четырёх кейсов."""
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
STEPS = [
    ("CASE 1 latency", "run_latency.py"),
    ("CASE 2 cost", "run_cost.py"),
    ("CASE 4 hallucinations", "run_eval.py"),
    ("CASE 3 drift", "run_drift.py"),
]


def main() -> None:
    for title, script in STEPS:
        print(f"\n=== {title} ===", flush=True)
        started = time.perf_counter()
        result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / script)],
                                cwd=ROOT)
        if result.returncode != 0:
            print(f"{script} завершился с кодом {result.returncode}")
            sys.exit(result.returncode)
        print(f"готово за {time.perf_counter() - started:.1f} с", flush=True)

    print("\nВсе отчёты в reports/, графики в reports/charts/")


if __name__ == "__main__":
    main()
