from __future__ import annotations

import argparse
from pathlib import Path

from app.gis.raster_audit import audit_raster_directory
from app.gis.raster_report import render_audit_markdown


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="只读审计 ESR Platform 的 12 项真实 GeoTIFF。"
    )
    parser.add_argument(
        "--raster-dir",
        type=Path,
        required=True,
        help="真实 GeoTIFF 所在目录；Docker 开发环境通常为 /data/source。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/workspace/docs/data"),
        help="raster-manifest.json 与 raster-audit.md 输出目录。",
    )
    parser.add_argument(
        "--mode",
        choices=("quick", "full"),
        default="quick",
        help="quick=9 个确定性窗口抽样；full=逐 block 完整扫描。",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    manifest = audit_raster_directory(args.raster_dir, mode=args.mode)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = args.output_dir / "raster-manifest.json"
    report_path = args.output_dir / "raster-audit.md"

    manifest_path.write_text(
        manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )
    report_path.write_text(render_audit_markdown(manifest), encoding="utf-8")

    print(f"[OK] manifest: {manifest_path}")
    print(f"[OK] report:   {report_path}")
    print(f"[INFO] expected={manifest.expected_raster_count}, found={manifest.found_raster_count}")
    print(f"[INFO] readable={manifest.all_rasters_readable}")
    print(f"[INFO] aligned={manifest.all_rasters_aligned}")
    print(f"[INFO] normalized={manifest.normalized_range_check}")

    # Audit findings are data facts, not a CLI crash. Missing/misaligned rasters are
    # written to the report and still return 0 so the developer can inspect them.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
