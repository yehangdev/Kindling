# Kindling

`Kindling` 用于流式处理 JSONL 应用日志，支持类型化布尔表达式过滤、关联记录分组、
数值汇总，以及 JSON、JSONL、CSV 和终端表格输出。除 Python 标准库外没有运行时
依赖。

当前版本：`v1.0.0`。版本历史见 [CHANGELOG.md](CHANGELOG.md)。

## 安装

```bash
python3 -m pip install -e .
```

运行环境要求 Python 3.9 或更高版本。

## 输入

未提供路径时读取标准输入：

```bash
cat application.jsonl | kindling --level ERROR
```

读取文件、目录或 shell 安全引用的 glob：

```bash
kindling application.jsonl
kindling 'logs/**/*.jsonl'
kindling logs/
kindling 'logs/archive-*.jsonl.gz'
```

目录会递归查找 `.jsonl`、`.json`、`.gz` 和 `.gzip` 文件。支持普通文本和 gzip
压缩的 JSONL。输入逐行读取，因此在选择 JSONL 输出时可以处理大于内存的文件。

空行会被忽略。非法 JSON 和非对象 JSON 值会写入标准错误并跳过。只要出现过输入
错误，`--fail-on-error` 就会把最终退出码改为失败。

## 时间过滤

`--start` 为包含边界，`--end` 为排除边界：

```bash
kindling app.jsonl \
  --start 2025-01-01T10:00:00Z \
  --end 2025-01-01T10:05:00Z
```

默认时间戳字段依次为 `timestamp`、`time`、`ts` 和 `@timestamp`。使用
`--time-field` 选择字段，支持点分路径。

自动解析支持 ISO 8601、Unix 秒、毫秒、微秒和纳秒。也可以显式选择解析器：

```text
iso8601
unix
unix-seconds
unix-milliseconds
unix-microseconds
unix-nanoseconds
```

应用专用格式可以重复传入 `--timestamp-format`：

```bash
kindling app.jsonl \
  --time-field event.time \
  --timestamp-format '%Y-%m-%d %H:%M:%S'
```

## 布尔过滤

使用 `--filter` 或 `--where` 查询嵌套字段：

```bash
kindling app.jsonl \
  --filter 'level == ERROR and request.status >= 500'

kindling app.jsonl \
  --where 'path ~= "^/v1/" or retry in [true, 1]'

kindling app.jsonl \
  --filter 'not (service == gateway) and latency_ms > 100'
```

支持的运算符：

```text
==  =  !=  >  >=  <  <=  ~=  =~  !~  in  not in
```

逻辑运算符为 `and`、`or` 和 `not`，别名分别为 `&&`、`||` 和 `!`。括号控制
优先级。右侧裸词按字符串处理，因此 `level == ERROR` 等价于
`level == "ERROR"`。

`~`、`~=` 和 `=~` 执行不区分大小写的正则搜索，`!~` 对其结果取反。数值比较
会转换数字字符串。字段缺失时不满足关系比较。

重复传入 `--filter` 会使用 AND 组合表达式。

## 字段选择

`--fields` 接受逗号分隔的顶层字段或点分路径：

```bash
kindling app.jsonl \
  --fields timestamp,request.path,request.status,latency_ms
```

点分输出键仍保留点号，例如 `"request.path"`。缺失字段输出为 `null`。

## 计数

统计一个字段的值：

```bash
kindling app.jsonl --count service
kindling app.jsonl --count status --group-by service
```

`--count` 配合分组会生成以分组字段值为键的嵌套对象：

```json
{
  "gateway": {
    "200": 3,
    "503": 1
  }
}
```

缺失值使用 `(missing)` 表示。

## 数值汇总

使用 `--stats`、`--aggregate` 或 `--summary` 汇总数值字段：

```bash
kindling app.jsonl --stats latency_ms --percentiles 50,90,95,99
kindling app.jsonl --stats latency_ms --group-by service
```

每个字段汇总包含 `count`、`total`、`missing`、`non_numeric`、`sum`、`min`、
`max`、`mean`、`stddev` 和请求的百分位键。百分位使用线性插值，并保留数值样本
以获得精确结果。

## 请求分组

按请求 ID 对完整记录分组：

```bash
kindling app.jsonl --group-by-request-id
kindling app.jsonl \
  --group-by-request-id \
  --request-id-field trace.id \
  --group-order count \
  --within-group-order timestamp \
  --fields timestamp,service,message
```

`--group-order` 接受 `first-seen`、`request-id` 或 `count`。
`--within-group-order` 接受 `input` 或 `timestamp`。

## 输出格式

使用 `--format` 选择输出格式：

```bash
kindling app.jsonl --format jsonl
kindling app.jsonl --format json
kindling app.jsonl --format table
kindling app.jsonl --format csv
```

`jsonl` 每行输出一条记录，也是默认格式。`json` 输出数组。`table` 对齐列并截断
过长单元格。`csv` 按首次出现顺序使用记录字段的并集。汇总对象遵循相同的格式
选择。

使用 `--output` 写入文件：

```bash
kindling app.jsonl --format csv --output selected.csv
```

## 配置

支持 JSON 和 INI 配置文件。命令行参数会覆盖配置文件中的值：

```bash
kindling --config examples/kindling.json examples/application.jsonl
```

JSON 配置示例：

```json
{
  "format": "table",
  "service": ["gateway"],
  "fields": ["level", "path", "status", "latency_ms"],
  "percentiles": [50, 95, 99]
}
```

INI 配置示例：

```ini
[kindling]
format = jsonl
level = ERROR,WARN
fields = timestamp,service,message
percentiles = 50,95
```

使用 `KINDLING_CONFIG` 可以在不传 `--config` 的情况下选择配置文件。选项名称
不区分大小写，并可使用 `-` 或 `_`。

## 跟随模式

不依赖外部运行时工具，持续跟踪一个或多个文件：

```bash
kindling live.jsonl --follow
kindling live.jsonl --follow --follow-from-start --follow-interval 0.5
```

默认跳过已有字节。新出现的完整行会立即解析。文件缺失时会轮询；文件截断或替换
后会重置位置。末尾不完整的行会等待换行符到达。按 `Ctrl-C` 停止。

跟随模式只写 JSONL，不能和计数、汇总、请求分组、其他输出格式或标准输入组合
使用。

## 基准测试

解析器基准测试可重复执行，并使用与 CLI 相同的读取器和时间戳路径：

```bash
PYTHONPATH=src python3 -m kindling.benchmark examples/application.jsonl \
  --iterations 100

PYTHONPATH=src python3 -m kindling.benchmark 'logs/*.jsonl' \
  --iterations 20 --json
```

报告包含行吞吐量、已解析记录吞吐量、耗时和迭代次数。

## 开发

运行标准库测试和语法检查：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m compileall -q src tests
```

也可以按开发便利使用 pytest：

```bash
python3 -m pip install -e '.[dev]'
python3 -m pytest
```

## 架构

`Kindling` 使用拉取式流处理管线：

```text
输入源
    |
    v
读取器和时间戳解析器
    |
    v
过滤表达式求值器
    |
    +--> 选中记录 --> 格式化器
    |
    +--> 计数/汇总/分组聚合 --> 格式化器
```

| 模块 | 职责 |
| --- | --- |
| `reader` | 标准输入、文件、目录、glob、gzip、跟随模式和诊断 |
| `timestamps` | 解析器注册表和时间戳归一化 |
| `filters` | 布尔表达式解析和嵌套字段求值 |
| `aggregates` | 计数、分组计数、数值汇总和百分位 |
| `formatters` | JSON、JSONL、CSV 和表格渲染 |
| `config` | JSON 和 INI 配置加载 |
| `benchmark` | 可重复的解析器和读取器吞吐量测量 |
| `cli` | 参数解析和管线组合 |

流式 JSONL 输出不会保留全部输入记录。聚合和分组只保留生成目标报告所需的数据。
跟随模式记录每个文件已完成的字节位置，等待不完整行，并检测截断或替换。

该工具不会把日志索引进数据库，不运行 HTTP 查询服务，也不尝试替代完整的日志
处理框架。

## 安全

安全问题请通过 GitHub Security Advisories 报告，不要在公开 Issue 中披露
真实日志、访问令牌或个人信息。

## 许可证

MIT
