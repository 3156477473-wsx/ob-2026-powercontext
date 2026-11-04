# 验证样例

本样例可按步骤执行，验证「上下文构造 → MiniMax 修改 → 测试通过 → 状态复用」的完整流程。

## 任务描述

> 为任务清单服务的列表查询增加按创建时间范围过滤的能力。
>
> - 要改什么：`GET /tasks` 新增 `created_from`、`created_to` 两个可选参数（SPEC-005）
> - 哪些原有行为必须保持：状态过滤、标签过滤、AND 语义、非法状态校验（SPEC-001 ~ SPEC-004、SPEC-006）

## 初始数据

| 文件 | 内容 |
|---|---|
| `business/docs/specs.md` | 规格 SPEC-001 ~ SPEC-006 |
| `business/src/task_service.py` | 初始实现，**未实现 SPEC-005** |
| `business/tests/test_regression.py` | 13 个回归测试 |
| `business/tests/test_time_filter.py` | 8 个目标测试（SPEC-005） |

## 上下文中必须包含的来源

| 类型 | 必须包含 | 原因 |
|---|---|---|
| 规格 | `docs/specs.md` 的 SPEC-005 | 定义要新增的参数与约束 |
| 规格 | `docs/specs.md` 的 SPEC-003 | 定义原有列表过滤语义，必须保持 |
| 代码 | `src/task_service.py` 的 `list` | 需要修改的方法 |
| 测试 | `tests/test_time_filter.py` 的 `test_both_bounds`、`test_bounds_are_inclusive` | 验证新功能 |
| 测试 | `tests/test_regression.py` 的 `test_list_status_and_tag_is_and` | 验证兼容性 |

## 操作步骤

### 步骤 0：环境准备

```bash
# seekdb
docker run -d --name seekdb -p 2881:2881 -p 2886:2886 \
  -v ./data:/var/lib/oceanbase oceanbase/seekdb:latest

# PowerContext（Python 3.11+）
uv venv --python 3.11 .venv
. .venv/bin/activate
uv pip install "powercontext[cli,server]==1.5.0"
powercontext config init --template --output .env
# 将 POWERCONTEXT_SERVER_HTTP_PORT 改为 8100 后启动
powercontext server run --env-file .env

# 本项目依赖
uv pip install -r requirements.txt
```

### 步骤 1：索引工程资料

```bash
python -m ctx.cli index --project business
```

**预期：** 输出 `indexed` 数量与三类统计，例如：

```json
{"indexed": 21, "spec": 6, "code": 9, "test": 21}
```

### 步骤 2：构造任务上下文

```bash
python -m ctx.cli build --task "为任务列表增加按创建时间范围过滤的功能，需要改哪些代码和测试"
```

**预期：**

- `specs` 含 SPEC-005 与 SPEC-003
- `code` 含 `list`
- `tests` 含 `test_both_bounds`

### 步骤 3：修改前跑测试

```bash
cd business
python -m pytest tests -q
```

**预期：**

- `tests/test_regression.py`：13 passed
- `tests/test_time_filter.py`：8 failed（`TypeError: unexpected keyword argument 'created_at'`）

### 步骤 4：由 MiniMax 完成修改

```bash
export MINIMAX_API_KEY=sk-...      # 不要提交真实密钥
python -m ctx.minimax_agent \
  --task "为任务列表增加按创建时间范围过滤的功能" \
  --file business/src/task_service.py
```

**预期：**

- 在 `records/` 生成 `minimax-<时间戳>.json`
- 内含本次任务、提供的上下文、模型响应与提取出的代码
- 将提取的代码写入 `business/src/task_service.py`

> 若 MiniMax 额度不足，可直接使用参考实现对照：
> `cp business/reference/task_service_spec005.py business/src/task_service.py`

### 步骤 5：修改后跑测试

```bash
cd business
python -m pytest tests -q
```

**预期：** `21 passed`（13 回归 + 8 目标）

### 步骤 6：保存任务状态

```bash
python -m ctx.cli save \
  --task "为任务列表增加按创建时间范围过滤" \
  --summary "SPEC-005 时间范围过滤" \
  --status done \
  --done "list 方法新增 created_from/created_to；目标测试 8 个通过" \
  --todo "补充 API 层参数校验"
```

**预期：** 返回含 `artifact_id` 与 `revision` 的 JSON。

### 步骤 7：重启后复用状态

```bash
# 重启上下文模块（进程退出即可，PowerContext 状态持久化在其数据库中）
python -m ctx.cli resume --task "时间范围过滤"
```

**预期：** 返回步骤 6 写入的任务状态文本与 `artifact_id`。

## 重置方法

```bash
# 清空 seekdb 索引
docker exec seekdb mysql -h127.0.0.1 -P2881 -uroot -e "DROP TABLE IF EXISTS test.eng_docs;"

# 恢复初始代码
cp business/reference/../business_init/src/task_service.py business/src/ 2>/dev/null || \
  git checkout -- business/src/task_service.py

# 清空 PowerContext（可选：换一个 Scope）
rm -rf records/
```

## 规格变更验证

1. 修改 `business/docs/specs.md` 中 SPEC-005 的正文（例如把参数名改为 `from_ts`）
2. 重新执行 `python -m ctx.cli index --project business`
3. 再执行 `python -m ctx.cli build --task ...`
4. **预期：** 上下文中的 SPEC-005 excerpt 显示修改后的内容，而非固定答案