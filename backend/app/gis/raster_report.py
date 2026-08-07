from __future__ import annotations

from app.gis.raster_manifest import RasterAuditManifest, RasterRecord


def _yes_no(value: bool | None) -> str:
    if value is None:
        return "无法判断"
    return "是" if value else "否"


def _fmt_number(value: float | str | None, digits: int = 6) -> str:
    if value is None:
        return "-"
    if isinstance(value, str):
        return value
    return f"{value:.{digits}g}"


def _fmt_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "-"
    return f"{size_bytes / 1024 / 1024:.2f} MB"


def _fmt_resolution(record: RasterRecord) -> str:
    if not record.resolution:
        return "-"
    return f"{record.resolution[0]:.10g} × {record.resolution[1]:.10g}"


def render_audit_markdown(manifest: RasterAuditManifest) -> str:
    lines: list[str] = [
        "# 真实栅格数据审计报告",
        "",
        f"> 生成时间：{manifest.generated_at.isoformat()}",
        f"> 审计模式：`{manifest.audit_mode}`",
        "",
        "## 1. 结论摘要",
        "",
        (
            f"- 预期栅格：**{manifest.expected_raster_count}** 个；"
            f"实际找到：**{manifest.found_raster_count}** 个。"
        ),
        (
            f"- {manifest.expected_raster_count} 个预期文件是否齐全："
            f"**{_yes_no(manifest.all_expected_files_present)}**。"
        ),
        f"- 所有预期文件是否能被 Rasterio 正常读取：**{_yes_no(manifest.all_rasters_readable)}**。",
        f"- 共同 CRS：**{manifest.common_crs or '不一致或无法判断'}**。",
        f"- 是否完全像元对齐：**{_yes_no(manifest.all_rasters_aligned)}**。",
        f"- 0～1 标准化检查：**{manifest.normalized_range_check}**。",
        f"- 标准化结论说明：{manifest.normalized_range_note}",
        "",
        "## 2. 为什么会得到这些结论",
        "",
        "### 2.1 文件数量",
        "",
        (
            "程序不是扫描到几个 `.tif` 就认为数据齐全，而是用项目固定的 "
            f"{manifest.expected_raster_count} 项指标目录逐一匹配文件名。"
        ),
        (
            f"因此“齐全”表示 {manifest.expected_raster_count} 个业务指标对应的文件都存在；"
            "额外的 TIFF 会单独列为 unexpected，避免把历史文件误当成指标。"
        ),
        "",
        "### 2.2 CRS 与像元对齐",
        "",
        (
            f"对齐检查以 `{manifest.reference_file or '-'}` 作为比较基准。"
            "这个基准只用于确定性比较，没有业务优先级。"
        ),
        "每张栅格都会比较 CRS、width/height、resolution、Affine transform 和 bounds。",
        "其中 `CRS + shape + transform` 是本阶段判定像元网格完全对齐的核心条件：",
        (
            "即使两张图都是 EPSG:4326、分辨率也相同，只要左上角原点偏了半个像元，"
            "transform 就会不同，不能直接逐像元加权。"
        ),
        "",
        "### 2.3 0～1 标准化",
        "",
        "`quick` 模式在影像的四角、边缘和中心读取确定性窗口，适合快速发现明显异常，但它是抽样；",
        "因此 quick 模式“没有发现越界值”会记为 `not-complete`，而不是直接宣称整幅栅格验证通过。",
        (
            "`full` 模式逐 block 扫描全部像元，只有完整扫描没有 NaN、Inf 和 "
            "[0,1] 越界值时才会记为 `passed`。"
        ),
        "",
        "## 3. 单栅格明细",
        "",
        "| 指标 | 文件 | 大小 | shape | CRS | 分辨率 | NoData | min | max | mean | 0～1 | 对齐 |",
        "| --- | --- | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]

    for record in manifest.rasters:
        stats = record.stats
        shape = f"{record.width}×{record.height}" if record.width and record.height else "-"
        normalized = (
            _yes_no(stats.within_expected_range) if stats is not None else "无法判断"
        )
        aligned = _yes_no(record.alignment.aligned) if record.alignment else "无法判断"
        lines.append(
            "| "
            + " | ".join(
                [
                    record.name,
                    f"`{record.filename}`",
                    _fmt_size(record.size_bytes),
                    shape,
                    record.crs or "-",
                    _fmt_resolution(record),
                    _fmt_number(record.nodata),
                    _fmt_number(stats.minimum if stats else None),
                    _fmt_number(stats.maximum if stats else None),
                    _fmt_number(stats.mean if stats else None),
                    normalized,
                    aligned,
                ]
            )
            + " |"
        )

    lines.extend(["", "## 4. 异常与差异", ""])

    if manifest.missing_files:
        lines.append("### 缺失文件")
        lines.extend(f"- `{name}`" for name in manifest.missing_files)
        lines.append("")

    if manifest.unexpected_tif_files:
        lines.append("### 额外 TIFF")
        lines.extend(f"- `{name}`" for name in manifest.unexpected_tif_files)
        lines.append("")

    detail_written = False
    for record in manifest.rasters:
        if record.warnings:
            detail_written = True
            lines.append(f"### {record.name} / `{record.filename}` 数据契约提醒")
            lines.extend(f"- {warning}" for warning in record.warnings)
            lines.append("")
        if record.errors:
            detail_written = True
            lines.append(f"### {record.name} / `{record.filename}` 读取错误")
            lines.extend(f"- {error}" for error in record.errors)
            lines.append("")
        if record.alignment and not record.alignment.aligned:
            detail_written = True
            lines.append(f"### {record.name} / `{record.filename}` 对齐差异")
            lines.extend(f"- {reason}" for reason in record.alignment.mismatch_reasons)
            lines.append("")
        if record.stats and record.stats.within_expected_range is False:
            detail_written = True
            lines.append(f"### {record.name} / `{record.filename}` 数值异常")
            lines.append(
                "- "
                f"NaN={record.stats.nan_count}，Inf={record.stats.inf_count}，"
                f"<0={record.stats.below_expected_min_count}，"
                f">1={record.stats.above_expected_max_count}。"
            )
            lines.append("")

    if not detail_written and not manifest.missing_files and not manifest.unexpected_tif_files:
        lines.append("本次审计没有发现需要单独列出的文件、读取或像元对齐异常。")
        lines.append("")

    lines.extend(
        [
            "## 5. 本报告不能证明什么",
            "",
            "- quick 模式不能证明整幅影像所有像元都处于 0～1，只能证明抽样窗口没有发现异常。",
            (
                "- 本阶段只验证数据结构、数值范围和网格条件，"
                "不验证每个指标的业务语义、年份或数据来源是否正确。"
            ),
            (
                "- 即使 12 张图完全对齐，也不代表加权模型一定合理；"
                "模型正确性会在后续 RiskAnalysisPipeline 的确定性测试中单独验证。"
            ),
            "",
        ]
    )

    return "\n".join(lines)
