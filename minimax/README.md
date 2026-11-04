# 规有所依 —— 面向软件持续演进的 SDD 上下文管理系统

2026 OceanBase 数据库大赛 · MiniMax × OceanBase 赛道

## 一句话

为 AI 开发助手提供一个**工程上下文模块**：给定开发任务，自动从工程资料中选出**该遵守的规格、该修改的代码、该运行的测试**，连同任务进展一起交给 MiniMax 完成代码修改。

## 解决的问题

AI 助手改代码时，常出现三类问题：

1. 不知道当前该遵守哪些规格 → 违反约束
2. 不知道改哪个文件和函数 → 改错位置
3. 任务中断后丢失进展 → 重复劳动

本模块把「规格 + 代码 + 测试 + 任务状态」组织成结构化上下文，让修改有据可依。

## 核心流程

```
业务工程（规格/代码/测试）
        │  ctx.cli index
        ▼
    seekdb（混合检索索引）
        │  ctx.cli build
        ▼
上下文模块输出：规格 + 代码 + 测试 + 历史任务状态
        │
        ├──▶ MiniMax：生成代码修改（记录落盘）
        │
        └──▶ PowerContext：保存任务进展 / 重启后复用
        │
        ▼
     pytest 验证：目标测试由失败转通过，回归测试保持通过
```

## 技术分工

| 技术 | 作用 | 证据位置 |
|---|---|---|
| **MiniMax** | 根据上下文生成 SPEC-005 的代码修改 | `records/minimax-*.json` |
| **seekdb** | 存储规格/代码/测试索引，混合检索结果直接构成上下文 | `eng_docs` 表；`build` 输出的 `sources.seekdb` |
| **PowerContext** | 保存任务进展（`task-state`），重启后检索复用 | `save` / `resume` 命令；输出中 `artifact_id` |

## 目录结构

```
minimax/
├── ctx/                       上下文模块
│   ├── cli.py                 入口：index / build / save / resume / status
│   ├── indexer.py             工程资料拆分
│   ├── seekdb_store.py        seekdb 存储与检索
│   ├── powercontext_client.py PowerContext 读写
│   ├── context_builder.py     上下文组装
│   └── minimax_agent.py       MiniMax 调用
├── business/                  业务工程
│   ├── docs/specs.md          规格 SPEC-001 ~ SPEC-006
│   ├── src/task_service.py    初始实现（缺 SPEC-005）
│   ├── tests/                 回归测试 + 目标测试
│   └── reference/             SPEC-005 参考实现
├── docs/                      运行说明、验证样例、技术说明
├── records/                   MiniMax 调用记录
└── scripts/                   安装与验证脚本
```

## 快速开始

### 1. 依赖

- Python 3.11+
- seekdb（Docker）
- PowerContext Server 1.5.0

```bash
uv venv --python 3.11 .venv
. .venv/bin/activate
uv pip install -r requirements.txt
```

### 2. 启动 seekdb

```bash
docker run -d --name seekdb \
  -p 2881:2881 -p 2886:2886 \
  -v ./data:/var/lib/oceanbase \
  oceanbase/seekdb:latest
```

### 3. 启动 PowerContext

```bash
uv pip install "powercontext[cli,server]==1.5.0"
powercontext config init --template --output .env
# 编辑 .env：POWERCONTEXT_SERVER_HTTP_PORT=8100
powercontext server run --env-file .env
```

### 4. 配置

```bash
cp .env.example .env
# 填入 MINIMAX_API_KEY（不要提交到仓库）
set -a; . ./.env; set +a
```

### 5. 使用

```bash
# 索引工程资料
python -m ctx.cli index --project business

# 构造任务上下文
python -m ctx.cli build --task "为任务列表增加按创建时间范围过滤的功能"

# 交给 MiniMax 修改
python -m ctx.minimax_agent \
  --task "为任务列表增加按创建时间范围过滤的功能" \
  --file business/src/task_service.py

# 验证
cd business && python -m pytest tests -q

# 保存任务状态
python -m ctx.cli save --task "时间范围过滤" --summary "SPEC-005" \
  --status done --done "实现 list 的时间过滤" --todo "补 API 层校验"

# 重启后复用
python -m ctx.cli resume --task "时间范围过滤"
```

## 验收对应

| 验收项 | 本项目如何满足 | 证据 |
|---|---|---|
| 能够运行 | 按上述步骤可完整复现 | 本文「快速开始」 |
| **MiniMax 实际参与** | 4 次真实调用，含失败→反馈→通过的完整迭代 | [records/README.md](records/README.md) |
| 上下文正确 | `build` 输出含 SPEC-005/SPEC-003、`list` 方法、目标测试；规格改动后重新 index 即生效 | `records/*.json` 的 `context_specs/code/tests` |
| 数据库实际参与 | `eng_docs` 表存全部资料（spec 6 / code 8 / test 23），检索结果构成上下文 | `SELECT doc_type, COUNT(*) FROM eng_docs GROUP BY doc_type` |
| 状态能够复用 | `save` 写入 PowerContext，`resume` 重启后读回 | `ctx.cli resume` 输出含 `artifact_id` |
| 代码修改有效 | 修改前：回归 13 passed / 目标 8 errors；修改后：**21 passed** | 见下方测试记录 |

## 测试记录

**修改前：**

```
tests/test_regression.py  13 passed
tests/test_time_filter.py  8 errors (TypeError: unexpected keyword argument 'created_at')
```

**MiniMax 第 1 轮生成后：**

```
13 passed, 8 errors   ← 实现了 list() 过滤，但漏改 create(created_at=...)
```

**反馈测试失败后，MiniMax 第 2 轮生成：**

```
21 passed
```

## 已知限制

- 向量为本地哈希实现，无外部 embedding 依赖，语义泛化弱于真实模型，由全文匹配兜底。
- PowerContext 未配置推理模型，任务状态采用显式写入的原子记忆。
- 业务工程为内存实现，便于测试复现。
- MiniMax-M3 为推理模型，生成完整文件需约 3500 completion tokens（其中推理约 2200），`max_tokens` 需设为 8000。

详细说明见 [docs/TECH.md](docs/TECH.md)，验证步骤见 [docs/SAMPLES.md](docs/SAMPLES.md)。