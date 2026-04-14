"""
Re-tag existing stored news with the latest categorization rules.

Usage examples:
  python retag_news.py --dry-run
  python retag_news.py --roots DATA DATA_older
  python retag_news.py --source tradingview --source timesofindia
  python retag_news.py --include-daywise
  python retag_news.py --max-files 50 --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from categorizing.fast_categorizer import get_news_categorizer


LOGGER = logging.getLogger("retag_news")


@dataclass
class RetagStats:
    files_scanned: int = 0
    files_changed: int = 0
    articles_seen_total: int = 0
    articles_seen_target: int = 0
    articles_retagged: int = 0
    skipped_files: int = 0
    failed_files: int = 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Re-tag already collected news files using latest categorizer rules."
    )
    parser.add_argument(
        "--roots",
        nargs="+",
        default=["DATA"],
        help="Root folders to scan (default: DATA).",
    )
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        help="Only retag articles from this source (repeatable).",
    )
    parser.add_argument(
        "--include-daywise",
        action="store_true",
        help="Also process DAYWISE mirrored files (off by default).",
    )
    parser.add_argument(
        "--skip-top-news",
        action="store_true",
        help="Skip DATA/top_news files.",
    )
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="Skip backup.json files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute changes without writing files.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Limit number of files processed (0 = no limit).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose file-level logging.",
    )
    return parser.parse_args()


def _resolve_roots(root_args: list[str]) -> list[Path]:
    roots: list[Path] = []
    for root_arg in root_args:
        root = Path(root_arg)
        if not root.is_absolute():
            root = (PROJECT_ROOT / root).resolve()
        if not root.exists():
            LOGGER.warning("Skipping missing root: %s", root)
            continue
        roots.append(root)
    return roots


def _should_skip_file(path: Path, args: argparse.Namespace) -> bool:
    parts = {p.lower() for p in path.parts}

    if ".cache" in parts:
        return True

    if not args.include_daywise and "daywise" in parts:
        return True

    if args.skip_top_news and "top_news" in parts:
        return True

    if args.skip_backup and path.name.lower() == "backup.json":
        return True

    return False


def _iter_json_files(roots: list[Path], args: argparse.Namespace) -> list[Path]:
    collected: list[Path] = []

    for root in roots:
        for path in root.rglob("*.json"):
            if _should_skip_file(path, args):
                continue
            collected.append(path)

    collected.sort()

    if args.max_files and args.max_files > 0:
        collected = collected[: args.max_files]

    return collected


def _default_source_for_file(path: Path) -> str:
    parent = path.parent.name.lower()
    if parent in {"daywise", "top_news"}:
        return ""
    return parent


def _resolve_article_source(article: dict, default_source: str) -> str:
    return (article.get("source") or default_source or "").strip().lower()


def _retag_article(article: dict, default_source: str, source_filter: set[str]) -> tuple[bool, bool]:
    if not isinstance(article, dict):
        return False, False

    source = _resolve_article_source(article, default_source)
    if source_filter and source not in source_filter:
        return False, False

    before_categories = tuple(article.get("categories") or [])
    before_category = article.get("category")

    if source and not article.get("source"):
        article["source"] = source

    get_news_categorizer().apply_to_article(article)

    after_categories = tuple(article.get("categories") or [])
    after_category = article.get("category")
    changed = (before_categories != after_categories) or (before_category != after_category)
    return True, changed


def _process_payload(payload, file_path: Path, source_filter: set[str]) -> tuple[int, int, int]:
    default_source = _default_source_for_file(file_path)

    if isinstance(payload, list):
        seen_total = 0
        seen_target = 0
        changed = 0
        for item in payload:
            if not isinstance(item, dict):
                continue
            seen_total += 1
            considered, item_changed = _retag_article(
                item,
                default_source=default_source,
                source_filter=source_filter,
            )
            if not considered:
                continue
            seen_target += 1
            if item_changed:
                changed += 1
        return seen_total, seen_target, changed

    if isinstance(payload, dict) and isinstance(payload.get("articles"), list):
        seen_total = 0
        seen_target = 0
        changed = 0
        for item in payload["articles"]:
            if not isinstance(item, dict):
                continue
            seen_total += 1
            considered, item_changed = _retag_article(
                item,
                default_source=default_source,
                source_filter=source_filter,
            )
            if not considered:
                continue
            seen_target += 1
            if item_changed:
                changed += 1
        return seen_total, seen_target, changed

    return 0, 0, 0


def _write_json(path: Path, payload) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(f"{text}\n", encoding="utf-8")


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    source_filter = {s.strip().lower() for s in args.source if s.strip()}
    roots = _resolve_roots(args.roots)
    if not roots:
        LOGGER.error("No valid roots to scan.")
        return 1

    files = _iter_json_files(roots, args)
    if not files:
        LOGGER.warning("No JSON files found after filters.")
        return 0

    stats = RetagStats()
    categorizer = get_news_categorizer()
    LOGGER.info("Using categorizer: %s", categorizer.__class__.__name__)
    LOGGER.info("Scanning %d JSON files", len(files))
    if source_filter:
        LOGGER.info("Source filter enabled: %s", ", ".join(sorted(source_filter)))
        if not args.include_daywise:
            LOGGER.info(
                "Note: DAYWISE files are excluded. Dashboard all-source view reads DAYWISE; "
                "use --include-daywise to reflect retags there."
            )

    for file_path in files:
        stats.files_scanned += 1

        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as exc:
            stats.failed_files += 1
            LOGGER.warning("Failed to read %s: %s", file_path, exc)
            continue

        seen_total, seen_target, changed = _process_payload(payload, file_path, source_filter)
        if seen_total == 0:
            stats.skipped_files += 1
            continue

        stats.articles_seen_total += seen_total
        stats.articles_seen_target += seen_target
        stats.articles_retagged += changed

        if changed > 0:
            stats.files_changed += 1
            if args.verbose:
                LOGGER.info("%s -> retagged %d/%d target articles", file_path, changed, seen_target)
            if not args.dry_run:
                try:
                    _write_json(file_path, payload)
                except Exception as exc:
                    stats.failed_files += 1
                    LOGGER.warning("Failed to write %s: %s", file_path, exc)
        elif args.verbose:
            LOGGER.info("%s -> no category changes", file_path)

    mode = "DRY-RUN" if args.dry_run else "WRITE"
    LOGGER.info("--- Retag Summary (%s) ---", mode)
    LOGGER.info("Files scanned   : %d", stats.files_scanned)
    LOGGER.info("Files changed   : %d", stats.files_changed)
    LOGGER.info("Files skipped   : %d", stats.skipped_files)
    LOGGER.info("Files failed    : %d", stats.failed_files)
    LOGGER.info("Articles seen (all)    : %d", stats.articles_seen_total)
    LOGGER.info("Articles seen (target) : %d", stats.articles_seen_target)
    LOGGER.info("Articles retagged: %d", stats.articles_retagged)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
