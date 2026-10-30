from __future__ import annotations
import argparse
import logging
import sys
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from pathlib import Path

def _setup_logging(level: str='INFO') -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format='%(asctime)s  %(levelname)-8s  %(name)s  %(message)s', datefmt='%Y-%m-%dT%H:%M:%S', stream=sys.stdout)

def main(argv: list[str] | None=None) -> int:
    parser = argparse.ArgumentParser(prog='chronoledger', description='ChronoLedger — Auditable SCD Type 2 Pipeline')
    parser.add_argument('--init-db', action='store_true', help='Initialise (or re-apply) the database schema')
    parser.add_argument('--run', metavar='CSV_FILE', help='Process a CSV event file through the full pipeline')
    parser.add_argument('--report', action='store_true', help='Generate the audit/reconciliation report')
    parser.add_argument('--log-level', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='Logging verbosity (default: INFO)')
    args = parser.parse_args(argv)
    _setup_logging(args.log_level)
    logger = logging.getLogger('chronoledger.main')
    if not any([args.init_db, args.run, args.report]):
        parser.print_help()
        return 0
    if args.init_db:
        logger.info('Initialising database schema...')
        from src.config import get_config
        from src.storage import get_connection, init_schema
        cfg = get_config()
        conn = get_connection(cfg)
        init_schema(conn)
        conn.close()
        logger.info('Schema initialised successfully.')
    if args.run:
        csv_path = Path(args.run)
        if not csv_path.exists():
            logger.error('File not found: %s', csv_path)
            return 1
        logger.info('Running pipeline on: %s', csv_path)
        from src.pipeline import run_pipeline
        result = run_pipeline(str(csv_path))
        print(f"\n{'=' * 50}")
        print(f'  Run ID   : {result.run_id}')
        print(f'  Status   : {result.status.upper()}')
        print(f'  Input    : {result.input_count} rows')
        print(f'  Accepted : {result.accepted_count}')
        print(f'  Rejected : {result.rejected_count}')
        print(f'  New evts : {result.event_insert_count}')
        print(f'  Dup skip : {result.duplicate_count}')
        print(f'  Conflicts: {result.conflict_count}')
        print(f'  Dim vers : {result.dimension_insert_count}')
        print(f'  Late evts: {result.late_event_count}')
        print(f'  Duration : {result.processing_duration_ms}ms')
        print(f"{'=' * 50}\n")
    if args.report:
        logger.info('Generating audit report...')
        from src.audit import generate_audit_report
        report = generate_audit_report()
        print(report)
    return 0
if __name__ == '__main__':
    sys.exit(main())
