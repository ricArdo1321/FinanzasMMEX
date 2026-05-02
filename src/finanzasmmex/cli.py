import argparse
import sys
from .staging.repo import StagingRepo

def main():
    parser = argparse.ArgumentParser(description="FinanzasMMEX CLI")
    subparsers = parser.add_subparsers(dest="command")

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize the database")
    init_parser.add_argument("--db", default="staging.db", help="Path to staging.db")
    init_parser.add_argument("--schema", default="src/finanzasmmex/staging/schema.sql", help="Path to schema.sql")

    # run command
    run_parser = subparsers.add_parser("run", help="Run ingestion jobs")
    run_parser.add_argument("--source", choices=["gmail", "mp", "all"], default="all", help="Source to ingest")

    args = parser.parse_args()

    if args.command == "init":
        repo = StagingRepo(args.db)
        repo.init_db(args.schema)
        print(f"Database initialized at {args.db}")
    elif args.command == "run":
        print(f"Running ingestion for source: {args.source}")
        # To be implemented in Phase 1
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
