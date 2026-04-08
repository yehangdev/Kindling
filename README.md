# Kindling

`Kindling` 用于流式处理 JSONL 应用日志，支持过滤、分组、聚合和多种输出格式。

当前版本：`v1.0.0-rc2`。

## 功能

- 端到端 CLI
- 配置和基准测试
- 错误输入诊断

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
