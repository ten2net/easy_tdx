# easy-tdx Agent 指南

> 本文档面向 AI 编程 Agent。阅读对象对项目一无所知，需要据此快速理解项目结构、构建方式、代码规范与安全边界。

---

## 项目概述

**easy-tdx** 是一个开源的通达信（TDX）TCP 协议行情数据客户端，当前版本 `1.17.0`。

它提供：

- **在线行情**：通过逆向通达信 TCP 协议获取 A 股、港股、美股、期货的 K 线、报价、分时、逐笔成交、板块、资金流向等数据。
- **离线数据**：直接读取本地通达信安装目录下的 `.day` / `.lc1` / `.lc5` 等二进制文件，也支持把服务端数据写回本地。
- **技术指标**：内置 34 个指标（MACD / KDJ / RSI / BOLL / 捉妖大师 / 30日乖离率信号等），基于 `MyTT` 纯计算实现。
- **缠论分析**：K 线合并 → 分型 → 笔 → 中枢 → 线段 → 买卖点 → 背驰的完整管道。
- **回测引擎**：向量化回测框架，支持单策略、组合回测、多因子组合、参数网格寻优、滑点/执行仿真、绩效分析。
- **策略选股扫描**：离线读取 `.day` 文件全市场扫描买入信号，或按强势股算法排名。
- **Web API**：基于 FastAPI 的 REST 服务；前端 `web-ui/` 是 Vue3 + ECharts 可视化界面。
- **CLI**：`easy-tdx` 命令行工具，默认 JSON 输出，适合 Agent / 脚本调用。

项目语言以 **中文** 为主（注释、文档、CLI 输出、提交日志）。修改代码时请保持中文注释风格，公共 API 的 docstring 也优先使用中文。

---

## 技术栈与运行时架构

### Python 后端

| 层级 | 路径 | 职责 |
|------|------|------|
| 公共 API | `src/easy_tdx/__init__.py` | 导出 `TdxClient`、`AsyncTdxClient`、`MacClient`、`Market`、`KlineCategory` 等 |
| 高层客户端 | `src/easy_tdx/client.py` | 同步 / 异步 `TdxClient`，封装行情、K 线、财务、资金流等高层 API |
| 传输层 | `src/easy_tdx/transport/` | TCP 连接管理、心跳、断线重连、帧头解析、响应解压 |
| 协议命令 | `src/easy_tdx/commands/` | 每个请求对应一个 `BaseCommand` 子类，负责「构造请求字节」和「解析响应字节」 |
| 编解码器 | `src/easy_tdx/codec/` | 价格、成交量、日期时间、板块文件、财务数据等二进制格式解析 |
| 数据模型 | `src/easy_tdx/models/` | `SecurityBar`、`SecurityQuote`、`TransactionRecord`、`MarketStat` 等 dataclass |
| MAC 协议 | `src/easy_tdx/mac/` | 更丰富的行情协议客户端（板块、排行、分时图、扩展数据等） |
| 扩展市场 | `src/easy_tdx/ex/` | 港股 / 美股 / 期货的扩展行情客户端 |
| 离线读写 | `src/easy_tdx/offline/` | 本地 `.day`、分钟线、板块、股本变迁、历史财务文件的读取与增量写入 |
| 回测 | `src/easy_tdx/backtest/` | 策略基类、订单模拟、持仓跟踪、绩效分析、组合、参数寻优 |
| 缠论 | `src/easy_tdx/chanlun/` | 缠论分析完整管道 |
| 因子 / 组合 | `src/easy_tdx/factor/`、`src/easy_tdx/portfolio/` | 量化因子计算、分析、组合再平衡与风险模型 |
| 选股扫描 | `src/easy_tdx/screen/` | 离线信号扫描、强势股排名、信号回测排名 |
| Web API | `src/easy_tdx/web/` | FastAPI 应用、路由、schema、任务执行器 |
| CLI | `src/easy_tdx/cli/` | Click 命令集合，入口在 `src/easy_tdx/cli/__init__.py:cli` |
| 外部数据源 | `src/easy_tdx/sina/`、`src/easy_tdx/cninfo/` | 新浪财经三表、巨潮资讯网公告 |
| 配置 | `src/easy_tdx/config.py` | 服务器地址、端口、超时；优先级：环境变量 > `~/.easy_tdx/config.json` > 源码默认值 |

核心依赖（`pyproject.toml`）：`pandas>=2.0,<3`、`tzdata>=2024.1`、`click>=8.0,<9`。

可选依赖组：

- `[dev]`：`pytest`、`mypy`、`ruff`、`scipy`、`httpx`、`pytest-cov`
- `[science]`：`scipy`
- `[web]`：`fastapi`、`uvicorn`

### Web UI 前端

- 位置：`web-ui/`
- 技术：Vue 3.5 + TypeScript + Vite 8 + Pinia + Vue Router 4 + ECharts 6
- 开发：`npm install && npm run dev`（默认 `http://localhost:5173`）
- 构建：`npm run build`
- Vite dev server 会把 `/api` 代理到后端 `127.0.0.1:8000`

### 文档

- 位置：`docs/`
- 构建：Sphinx + MyST parser + ReadTheDocs 主题
- 在线托管：ReadTheDocs（配置见 `.readthedocs.yaml`）

---

## 代码组织

```
easy-tdx/
├── src/easy_tdx/          # 主库源码（~211 个 .py 文件，~23k+ 行）
├── tests/
│   ├── unit/              # 单元测试（~60 个测试文件）
│   └── integration/       # 集成测试（需要真实行情连接）
├── strategies/            # 开箱即用的示例策略文件（16 个）
├── web-ui/                # Vue3 前端
├── examples/              # 按主题组织的示例脚本
├── docs/                  # Sphinx 文档
├── scripts/               # 辅助脚本（ruff hook、探测脚本、验证脚本）
├── pyproject.toml         # 项目元数据、依赖、工具配置
├── requirements-dev.txt   # 开发工具链锁文件
├── run_all_strategies.py  # 批量回测入口脚本
└── .github/workflows/     # CI / Publish
```

---

## 构建与测试命令

### 安装开发环境

```bash
# 基础开发模式
pip install -e ".[dev]"

# 同时包含 Web 依赖
pip install -e ".[dev,web]"

# 锁定开发工具链（CI 使用）
pip install -r requirements-dev.txt
```

### 运行测试

```bash
# 单元测试（与 CI 一致）
python -m pytest tests/unit/ -v --tb=short --cov src/easy_tdx --cov-fail-under=60

# 全部测试（含需要网络的集成测试）
python -m pytest tests/ -v --tb=short
```

### 代码风格检查

```bash
ruff check src/ tests/
ruff format --check src/ tests/

# 自动修复与格式化
ruff check --fix src/ tests/
ruff format src/ tests/
```

### 类型检查

```bash
mypy src/
```

### 构建发布产物

```bash
python -m build
```

### 启动服务

```bash
# CLI
easy-tdx --help

# Web API 服务
easy-tdx serve --port 8000

# Web UI（另开终端）
cd web-ui && npm install && npm run dev
```

### 文档构建

```bash
cd docs
pip install -r requirements.txt
sphinx-build . _build
```

---

## 代码风格指南

- **Python 版本**：>= 3.10，使用 `from __future__ import annotations`、`|` 联合类型、`match` 等现代语法。
- **格式化**：`ruff format`，行宽 **100**。
- **Lint**：`ruff check`，启用规则 `E`、`F`、`I`、`UP`（目标版本 `py310`）。
- **类型**：`mypy --strict` 必须通过。所有公共函数需标注类型，避免 `Any` 滥用。
- **注释与文档**：优先使用中文 docstring / 注释；注释里常见的审计编号如 `审计 #18` 指历史代码审计 issue，保留它们。
- **模块排除**：`src/easy_tdx/exchange_margin.py` 和 `*.pyi` 不参与 ruff / mypy 检查。
- **导入**：使用 `from __future__ import annotations`；相对导入用于包内模块；第三方放上面，本地放下面。
- **错误处理**：网络层优先转换为 `TdxConnectionError` / `TdxDecodeError` / `TdxCommandError`（定义在 `exceptions.py`）。
- **时区**：业务时间统一使用 `Asia/Shanghai`，避免 naive datetime。

---

## 测试策略

- **单元测试**为主，覆盖编解码、协议命令、客户端重连、回测引擎、缠论、因子、Web API 等。
- **覆盖率门槛 60%**（`pyproject.toml [tool.coverage.report]`），CI 会强制 `--cov-fail-under=60`。
- **集成测试** `tests/integration/test_live_client.py` 需要真实通达信行情连接，默认不在 CI 核心任务中运行。
- **异步测试**：`pytest-asyncio`，`asyncio_mode = auto`。
- **CI 矩阵**：`ubuntu-latest` + `windows-latest`，Python `3.10` / `3.12` / `3.13`。
- 新增关键路径（尤其是协议层、数据正确性、错误处理）建议补充回归测试。

---

## 部署与发布

- **PyPI 发布**：推送 `v*` 标签触发 `.github/workflows/publish.yml`。
- 使用 **PyPI trusted publishing** + **sigstore 签名**（`attestations: true`）。
- 发布前确保：
  - `pytest tests/unit/` 通过
  - `ruff check`、`ruff format --check`、`mypy src/` 全绿
  - 版本号已在 `pyproject.toml` 更新
- **文档**：ReadTheDocs 在推送 main 分支时自动构建。

---

## 安全与边界注意事项

1. **路径穿越**：`offline/` 模块处理本地文件路径，已加入清洗逻辑拒绝 `..`、 `/`、 `\` 等危险字符。修改此处需同步加固。
2. **参数校验**：Web API 与策略注册表已拦截 `NaN` / `Inf` / 超大整数，防止 DoS。新增参数入口需保持同等校验。
3. **CORS**：`web/app.py` 在开发模式下使用 `allow_origins=["*"]`，生产部署应收紧。
4. **网络连接**：项目无需 API Key，但依赖外部通达信公共服务器。这些服务器可能不稳定，客户端已实现自动重连与指数退避。
5. **数据正确性**：协议层存在已知缩放（如 `market-stat` 计数字段需 ×10 还原）。修改协议解析前请查阅 `docs/protocol-reverse-engineering.md` 与相关注释。
6. **外部脚本**：`src/easy_tdx/exchange_margin.py` 是本地独立脚本，依赖外部 `unified_config/sqlalchemy/requests`，不属于库的一部分，已被 `.gitignore` 与 lint 排除。
7. **回测 ≠ 实盘**：回测结果仅用于研究，README 与文档中已明确风险声明。新增策略 demo 时需附带免责声明。

---

## 给 Agent 的常用入口

- 想加 CLI 命令：在 `src/easy_tdx/cli/` 新建 `cmd_xxx.py`，在 `src/easy_tdx/cli/__init__.py` 注册。
- 想加 Web API 端点：在 `src/easy_tdx/web/routers/` 新建 / 修改 router，在 `src/easy_tdx/web/app.py` 挂载。
- 想加行情协议命令：继承 `src/easy_tdx/commands/base.py` 的 `BaseCommand`，在客户端中调用 `_execute`。
- 想加回测策略：参考 `strategies/` 或 `src/easy_tdx/backtest/strategies/builtin.py`，继承 `Strategy` 或 `ParametrizedStrategy`。
- 想改二进制解析：优先在 `src/easy_tdx/codec/` 增加 / 修改解析函数，并补充 `tests/unit/test_codec_*.py` 回归测试。
- 想改配置优先级：修改 `src/easy_tdx/config.py`，并在 `tests/unit/test_config.py` 补充对应测试。
