# ADR-002：数据库与文件存储边界

- 状态：已接受
- 日期：2026-08-05

## PostgreSQL/PostGIS 保存

- 用户和认证信息
- 分析任务、状态和进度
- WGS84 分析 Geometry、指标权重和不可变提交参数
- 幂等键、父子重试关系和调度状态
- 排队、开始、完成和过期时间戳
- 成果相对路径、大小、过期时间和删除状态

指标目录仍由版本化代码 Contract 管理；本阶段不增加管理后台或可编辑指标表。审计以保留的
任务元数据、失败信息和父子关系为主，不声称已经实现通用操作日志。

## 文件系统或对象存储保存

- 12 项原始 GeoTIFF
- 综合风险 GeoTIFF
- 透明风险预览 PNG
- 风险结果 JSON manifest
- POI CSV 等现有导出成果

数据库只保存相对路径和生命周期。文件访问必须先校验 owner、DB 终态、manifest Contract 和
安全相对路径；不暴露无需鉴权的静态结果 URL。

## Redis 保存

- Celery 消息
- 每用户提交固定窗口计数
- refresh token 失效 JTI

长期任务状态以 PostgreSQL 为准。Redis 中禁止传输大型 GeoJSON、GeoTIFF 二进制或完整分析结果。
