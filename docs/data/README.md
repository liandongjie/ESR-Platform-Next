# Phase 1A 数据审计

本目录只提交**数据契约和审计结果**，不提交真实 GeoTIFF。

## 快速审计

项目已经通过 Docker Compose 把宿主机真实栅格目录只读挂载到 backend 容器的 `/data/source`。

在项目根目录执行：

```powershell
docker compose exec backend python -m app.gis.audit_cli `
  --raster-dir /data/source `
  --output-dir /workspace/docs/data `
  --mode quick
```

生成：

- `docs/data/raster-manifest.json`：机器可读的数据契约；
- `docs/data/raster-audit.md`：面向开发和 Review 的解释性报告。

`quick` 会读取分布在影像四角、边缘和中心的确定性窗口，目的是快速验证文件、CRS、网格和明显的数值异常。它不会把“抽样没发现问题”误写成“整幅栅格已经验证通过”。

## 完整审计

在 quick 结果确认没有明显问题之后再运行：

```powershell
docker compose exec backend python -m app.gis.audit_cli `
  --raster-dir /data/source `
  --output-dir /workspace/docs/data `
  --mode full
```

`full` 使用 Rasterio 的 block windows 逐块扫描，不一次性把整张大栅格读进内存。完整扫描可以给出全量的 min/max/mean、NoData/Mask、NaN/Inf 和 [0,1] 越界计数。

## 为什么要同时比较 transform

两张栅格即使都是 EPSG:4326、像元分辨率也都是 0.001°，仍可能因为左上角原点不同而错开半个像元。逐像元加权要求网格对齐，因此 Phase 1A 把 `CRS + width/height + Affine transform` 作为核心对齐条件，并额外输出 resolution 和 bounds 帮助诊断。
