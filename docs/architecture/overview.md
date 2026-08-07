# 系统架构概览

```text
Vue 3 Web Client
    │ REST / JSON
    ▼
Flask API ───────── PostgreSQL/PostGIS
    │                     │
    │ task id             │ task/geometry/metadata
    ▼                     │
Redis / Celery Broker     │
    │                     │
    ▼                     │
Celery GIS Worker ────────┘
    │
    ├── read-only source rasters
    └── runtime result files
```

项目先采用分层单体，避免在业务和数据口径尚未稳定时拆分微服务。
