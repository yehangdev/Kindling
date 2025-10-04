# Kindling

`Kindling` 用于流式处理 JSONL 应用日志，支持过滤、分组、聚合和多种输出格式。

当前版本：`v0.1.0`。

## 功能

- JSONL 过滤和字段选择
- JSON、JSONL 和 CSV 输出

## 安装

```bash
python3 -m pip install -e .
```

## 测试

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  python3 -m unittest discover -s tests
```

## 许可证

MIT
