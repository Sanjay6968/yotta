import argparse
import subprocess
import sys
import time
from pathlib import Path

def run_benchmark(input_file: str) -> None:
    path = Path(input_file)
    if not path.exists():
        print(f'ERROR: {input_file} not found. Run generate_data.py first.')
        sys.exit(1)
    row_count = sum((1 for _ in open(path, encoding='utf-8'))) - 1
    print(f'Input file : {input_file}')
    print(f'Input rows : {row_count:,}')
    print('Running pipeline...')
    print('-' * 50)
    start = time.perf_counter()
    result = subprocess.run([sys.executable, '-m', 'src.main', '--run', input_file], capture_output=True, text=True)
    elapsed = time.perf_counter() - start
    print(result.stdout)
    if result.stderr:
        print('STDERR:', result.stderr[-500:])
    print('-' * 50)
    print(f'Duration   : {elapsed:.3f}s')
    if elapsed > 0:
        print(f'Throughput : {row_count / elapsed:,.0f} rows/sec')
    print(f'Exit code  : {result.returncode}')
    print()
    print('Performance notes:')
    print('  - Pipeline does one DB round-trip per customer to fetch existing events')
    print('  - Optimization: batch customer lookups with ANY() array to reduce N queries -> 1')
    print("  - reconstruction.py rebuilds each customer's SCD chain in-memory (O(k log k) per customer)")
    print('  - For 100k+ rows, parallelizing reconstruction across CPU cores would reduce wall time')

def main():
    parser = argparse.ArgumentParser(description='Benchmark ChronoLedger pipeline')
    parser.add_argument('--input', default='data/generated/medium_events.csv', help='Input CSV to benchmark against')
    args = parser.parse_args()
    run_benchmark(args.input)
if __name__ == '__main__':
    main()
