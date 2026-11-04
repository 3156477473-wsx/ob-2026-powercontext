# MiniMax 开发记录

本目录保存 MiniMax 参与本次代码修改的全部调用记录，用于核对「MiniMax 实际参与」。

## 记录文件

| 文件 | 说明 |
|---|---|
| `minimax-20261104-161317.json` | 首次调用：`max_tokens` 太小，模型推理 token 耗尽预算，返回空 |
| `minimax-20261104-161619.json` | 调整参数后调用，生成代码 |
| `minimax-20261104-161706.json` | 正式生成：新增 `list()` 的时间过滤，但漏改 `create()` |
| `minimax-20261104-161805.json` | **反馈测试失败后重新生成**：补齐 `create(created_at=...)`，全部测试通过 |

## 每条记录的结构

```json
{
  "timestamp": "20261104-161805",
  "model": "MiniMax-M3",
  "task": "本次开发任务",
  "target_file": "被修改的文件",
  "context_specs": ["SPEC-005", "SPEC-003", ...],   // 喂给模型的规格
  "context_code":  ["list", "_validate_status", ...], // 喂给模型的代码
  "context_tests": ["test_both_bounds", ...],         // 喂给模型的测试
  "request":  [system, user],   // 完整提示词（含上下文与当前文件）
  "response": "...",            // 模型完整回复
  "extracted_code": "..."       // 从回复中提取的代码（已写入目标文件）
}
```

## 开发过程还原

### 第 1 轮：生成

`minimax-20261104-161706.json`

模型基于上下文（SPEC-005 + `list` 方法 + 目标测试）生成了新版本，新增了 `created_from` / `created_to` 过滤逻辑。

**测试结果：**

```
13 passed, 8 errors
ERROR tests/test_time_filter.py::test_created_from_only
E   TypeError: TaskService.create() got an unexpected keyword argument 'created_at'
```

模型实现了 `list()` 的过滤，但**没有同步修改 `create()`**，而测试需要用 `create(created_at=...)` 构造固定时间的数据。

### 第 2 轮：反馈修正

`minimax-20261104-161805.json`

把测试失败信息作为补充说明追加到提示词：

```
上一轮生成的代码没能通过测试，请修正。

测试失败信息：
E   TypeError: TaskService.create() got an unexpected keyword argument 'created_at'
...

特别注意：
1. create() 方法需要新增 created_at 可选参数（datetime）
2. list() 需要新增 created_from / created_to 参数并做过滤
3. 保持 create() 原有的 title/description/tags 参数不变
```

模型重新生成了完整文件，补上 `create()` 的 `created_at` 参数。

**测试结果：**

```
21 passed
```

### 最终代码

第 2 轮的 `extracted_code` 已写入 `business/src/task_service.py`，第 2 轮的 `extracted_code` 字段与提交的代码差异一致。

## 验证方式

评审可按以下步骤核对：

1. 打开 `minimax-20261104-161805.json` 的 `request` 字段，确认任务、上下文、当前文件都完整传入
2. 比对 `extracted_code` 与 `business/src/task_service.py`，二者应一致
3. 在 `business/` 下执行 `pytest tests -q`，应得到 `21 passed`

## 说明

- 记录中不含 API Key，调用时通过环境变量 `MINIMAX_API_KEY` 传入。
- 模型为 `MiniMax-M3`，经 MiniMax 开放平台 HTTP 接口调用。
- 本目录仅保留与最终代码修改相关的记录；首次空响应记录保留，用于说明参数调整过程。