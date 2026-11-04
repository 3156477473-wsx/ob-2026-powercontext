# 一页技术说明

## 模块结构

```
minimax/
├── ctx/                        上下文模块（核心交付物）
│   ├── cli.py                  CLI 入口：index / build / save / resume / status
│   ├── indexer.py              工程资料拆分：规格按 SPEC 分节，代码/测试按函数
│   ├── seekdb_store.py         seekdb 存储与混合检索
│   ├── powercontext_client.py  PowerContext 任务状态读写
│   ├── context_builder.py      上下文组装
│   └── minimax_agent.py        MiniMax 调用与记录落盘
├── business/                   业务工程（被修改对象）
│   ├── docs/specs.md           规格：SPEC-001 ~ SPEC-006
│   ├── src/task_service.py     实现（初始版未实现 SPEC-005）
│   ├── tests/test_regression.py 回归测试（13 个）
│   ├── tests/test_time_filter.py 目标测试（8 个，SPEC-005）
│   └── reference/              SPEC-005 参考实现
├── records/                    MiniMax 调用记录（运行后生成）
├── scripts/                    环境安装与验证脚本
└── docs/                       运行说明、验证样例
```

## 上下文选择方式

**索引阶段**（`ctx.cli index`）

把工程资料拆成可检索单元写入 seekdb `eng_docs` 表：

| doc_type | 拆分粒度 | 记录字段 |
|---|---|---|
| `spec` | 按 `## SPEC-xxx` 分节 | doc_path=`docs/specs.md`，symbol=`SPEC-005` |
| `code` | 按 `def` 拆分，含紧邻注释 | doc_path=`src/task_service.py`，symbol=`list` |
| `test` | 按 `def test_*` 拆分 | doc_path=`tests/test_time_filter.py`，symbol=`test_both_bounds` |

**检索阶段**（`ctx.cli build`）

对任务描述做混合检索，`doc_type` 分别过滤，取 Top-K：

1. 全文召回：`MATCH(content) AGAINST(任务描述)`，走 ik 分词
2. 向量重排：`l2_distance(vector, query_vec)`，本地哈希向量
3. 加权融合：`0.6 × 归一化全文分 + 0.4 × 归一化向量分`

任务「为任务列表增加按创建时间范围过滤」的实际输出：

- 规格：SPEC-003（列表查询）、SPEC-005（时间范围过滤）
- 代码：`list`（需修改）、`to_dict`、`_validate_status`
- 测试：`test_both_bounds`、`test_bounds_are_inclusive` 等

## 各项技术的分工

| 技术 | 承担作用 | 可核对证据 |
|---|---|---|
| **MiniMax** | 根据上下文生成 SPEC-005 的代码修改 | `records/minimax-*.json` 保存完整请求与响应，`extracted_code` 与最终代码差异对应 |
| **seekdb** | 存储规格/代码/测试并做混合检索，检索结果直接构成上下文 | `SELECT * FROM eng_docs` 可见索引数据；`ctx.cli build` 输出中的 `sources.seekdb` 为表内计数 |
| **PowerContext** | 保存任务进展（kind=`task-state`），重启后检索复用 | `ctx.cli save` 写入，`ctx.cli resume` 读取；输出中 `task_state.from_powercontext` 含 artifact_id |

## 任务流程

```
1. ctx.cli index          行李规格/代码/测试 → seekdb
2. ctx.cli build          任务 → 检索 → 上下文（规格+代码+测试+历史状态）
3. python -m ctx.minimax_agent --task ... --file src/task_service.py
                         上下文 + 原文件 → MiniMax → 新文件（记录落盘）
4. pytest tests          目标测试由失败转为通过，回归测试保持通过
5. ctx.cli save           任务进展写入 PowerContext
6. 重启后 ctx.cli resume  读回任务状态，继续处理
```

## 规格变更处理

上下文模块不使用固定答案：`ctx.cli index` 每次重新读取 `docs/specs.md` 并重建索引。修改 SPEC 文本后重新索引，`build` 输出的 excerpt 会随之变化。

## 已知限制

- 向量使用本地哈希算法（字符 n-gram + 子线性 TF），不依赖外部 embedding 模型；语义泛化能力弱于真实模型，靠全文匹配兜底。
- 业务工程为内存实现，便于测试复现，不涉及真实数据库。
- PowerContext 未配置推理模型，因此使用显式写入的原子记忆保存任务状态，不依赖自动记忆抽取。