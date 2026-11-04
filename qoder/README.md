# Qoder 赛题：文献笔记智能检索助手

2026 OceanBase 数据库大赛 · Qoder × OceanBase 赛道

## 一句话介绍

把论文、课程笔记、实验记录导入 **seekdb**，用自然语言做「向量 + 全文 + 结构化过滤」混合检索，快速定位相关段落与出处。

## 提交材料索引

| 材料 | 位置 |
|---|---|
| 项目网站 | https://literature-search-new-xzdmkqazlbf.qoder.zone |
| 代码仓库 | 本目录 `qoder/`（分支 `2026-competition-ecosystem`） |
| 运行说明 | 本文「运行说明」章节 |
| 验证样例 | [samples/README.md](samples/README.md) |
| Qoder 开发记录 | [docs/qoder/](docs/qoder/) 下 5 张截图 |
| 技术说明 | [docs/SITE-CONTENT.md](docs/SITE-CONTENT.md) |
| Qoder 账号 UID | `1823087646185968` |

## Qoder 账号信息

| 项目 | 值 |
|---|---|
| Qoder 名称 | `aliyun-1823087646185968` |
| 阿里云账号 ID | `1823087646185968` |
| 站点域名 | `literature-search-new-xzdmkqazlbf.qoder.zone` |

## 解决的问题

复习和写论文时，资料散落在几十个 PDF、课程笔记和 Markdown 里。想找「上次记的那个概念」，只能靠文件名和记忆，翻半天找不到；找到了也说不清是哪份材料、哪一段。

## 核心功能

| 功能 | 说明 |
|---|---|
| 文档导入 | 支持 PDF / TXT / Markdown，按段落优先策略切块 |
| 向量检索 | 文本转向量存入 seekdb，用 `l2_distance` 召回语义相近内容 |
| 全文检索 | seekdb `FULLTEXT` 索引 + ik 分词，关键词精确匹配 |
| 混合检索 | 全文召回 + 向量精排两阶段，归一化加权融合 |
| 文档筛选 | 下拉框选择单篇文档，只在其内部检索 |
| 出处定位 | 每条结果给出文档名与块序号，可回溯原文 |

## seekdb 在项目中的作用

seekdb 是项目**唯一的数据底座**，承担四项工作：

| 能力 | 实现位置 | 用途 |
|---|---|---|
| 向量列存储 | `doc_chunks.vector`（`VECTOR(256)`） | 保存每个文本块的向量 |
| 向量检索 | `l2_distance(vector, %s)` | 计算查询与文本块的相似度 |
| 全文检索 | `MATCH(content) AGAINST(%s)` + ik 索引 | 关键词精确匹配 |
| 结构化过滤 | `WHERE doc_name = %s` | 按文档筛选 |

移除 seekdb，项目无法完成任何检索。

## 混合检索的两阶段设计

**第一阶段：全文召回**

用 `MATCH...AGAINST` 筛出关键词命中的文本块，候选池取最终结果的 4 倍（至少 10 条），保证不漏召回。

**第二阶段：向量精排**

对候选池中每条记录同时取 `vec_score = 1 - l2_distance` 与 `kw_score`，分别归一化后加权：

```
最终得分 = 0.6 × 归一化全文分 + 0.4 × 归一化向量分
```

全文权重略高，保证关键词精确命中优先；向量负责语义补位。

## 运行说明

### 环境要求

- Python 3.10+
- Docker
- seekdb 容器

### 1. 启动 seekdb

```bash
docker run -d \
  --name seekdb \
  -p 2881:2881 \
  -p 2886:2886 \
  -v ./data:/var/lib/oceanbase \
  oceanbase/seekdb:latest
```

等待约 30 秒，确认就绪：

```bash
docker logs seekdb | tail -5
```

看到 `SeekDB SQL ready` 即可。

### 2. 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. 配置

```bash
cp .env.example .env
```

默认配置即可连接本机 Docker 中的 seekdb（root，空密码）。

### 4. 启动服务

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

浏览器打开 <http://127.0.0.1:8000>。

## 验证样例

完整步骤见 [samples/README.md](samples/README.md)。核心验证链：

1. 上传 `samples/sample-notes.md`，页面显示 8 个文本块
2. 搜索「近似最近邻检索怎么加速」，命中「向量索引与近似最近邻」段落
3. 执行 SQL 确认数据在 seekdb 中：
   ```sql
   SELECT doc_name, chunk_no, LEFT(content, 30) FROM test.doc_chunks LIMIT 5;
   ```
4. 停掉 seekdb 容器后搜索，接口返回 503 并提示「请检查 seekdb 是否启动」

## Qoder 开发记录

项目在 Qoder 中完成开发，关键环节截图见 `docs/qoder/`：

| 截图 | 环节 | Qoder 做了什么 |
|---|---|---|
| `01-项目理解.png` | 需求拆解 | 通读代码，梳理架构、定位 seekdb 职责、分析混合检索实现 |
| `02-功能改进.png` | 编码 | 新增 `GET /api/docs` 接口 + 前端下拉框，实现按文档筛选 |
| `03-代码审查.png` | 调试 | 识别 3 个缺陷：异常处理缺失、大文件无限制、向量维度未校验 |
| `04-错误处理改进.png` | 修复 | 5 个接口统一异常捕获，seekdb 不可用时返回 503 |
| `05-站点发布.png` | 交付 | 通过 Qoder Sites 发布项目网站 |

**实测验证：**

- 新增的 `/api/docs` 返回 `["sample-notes.md"]`
- 带 `doc` 参数检索时只返回指定文档结果，首条得分 0.93
- 筛选不存在的文档返回 0 条
- 停掉 seekdb 后三个接口均返回 503，恢复后自动正常

## 技术说明

- 文本向量化使用**本地确定性哈希向量**（字符 n-gram + 子线性 TF + L2 归一化），无需外部模型或 API Key，保证评审可复现。
- 如需替换为真实 embedding 服务，只需修改 `app/embedding.py` 中的 `embed()`，保持输出维度与 `.env` 中 `EMBEDDING_DIM` 一致。
- 本项目不复用外部开源代码。

## 目录结构

```
qoder/
├── README.md               本文件
├── requirements.txt        Python 依赖
├── .env.example            配置示例
├── app/
│   ├── config.py           环境配置
│   ├── embedding.py        文本向量化
│   ├── ingest.py           文档解析与分块
│   ├── main.py             FastAPI 接口
│   └── store.py            seekdb 建表、写入、检索
├── static/index.html       前端页面
├── samples/                验证样例
└── docs/
    ├── SITE-CONTENT.md     网站内容
    └── qoder/              Qoder 开发记录截图
```