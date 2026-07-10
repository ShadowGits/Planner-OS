import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from planner_engine import ExcelPlannerStore, PlannerEngine

DEFAULT_PLANNER_PATH = Path(
    "/Users/sparry00/Library/CloudStorage/"
    "GoogleDrive-sparsh0304@gmail.com/My Drive/"
    "Life tracking/Master_Planner_Jul26_Jun27.xlsx"
)
DEFAULT_BACKUP_DIR = Path("backups")


def build_parser() -> argparse.ArgumentParser:
    """Build the edit planner command-line parser."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--sheet", required=True)
    parser.add_argument("--cell", required=True)
    parser.add_argument("--value", required=True)
    parser.add_argument("--planner-path", type=Path, default=DEFAULT_PLANNER_PATH)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    return parser


def main() -> None:
    """Edit a planner cell through Planner Engine."""

    args = build_parser().parse_args()
    store = ExcelPlannerStore(
        planner_path=args.planner_path,
        backup_dir=args.backup_dir,
    )
    engine = PlannerEngine(store)
    result = engine.write_cell(args.sheet, args.cell, args.value)

    print(f"Backup: {result.backup_path}")
    print(f"Updated {args.sheet}!{args.cell} = {args.value}")


if __name__ == "__main__":
    main()
