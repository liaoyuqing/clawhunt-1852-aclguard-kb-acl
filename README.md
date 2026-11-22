# 助手侧可见性二次校验（工单 S5-ASST-007 交付）

知识库侧对知识条目做了第一道可见性过滤；本包实现**助手侧独立的第二道校验**，保证任一层失效时都不会把无权内容送给模型或写进回答。全部依赖只用 Python 3.11 标准库 + `pytest`，**不需要数据库、不需要 Redis、不需要任何 API 密钥**。

## 1. 目录

| 路径 | 作用 |
| --- | --- |
| `aclguard/models.py` | `Principal` / `KnowledgeEntry` / `Chunk` / `Decision` / `DroppedChunk` / `SecondCheckResult` / `CitationRef` |
| `aclguard/visibility.py` | `decide(entry, principal)`：四类 `visibility_label` 的判定与稳定 `reason` 枚举 |
| `aclguard/second_check.py` | `filter_chunks(...)`：交给模型前逐片段重判，丢弃并记 `kb_acl_dropped` |
| `aclguard/cache_key.py` | `role_fingerprint` / `site_fingerprint` / `cache_key` / `TTLCache` |
| `aclguard/history.py` | `render_history(...)`：角色被收回后把历史引用折叠为「该内容已无权查看」 |
| `aclguard/assistant.py` | `ask(...)`：检索 → 二次校验 → 模型请求体 → 答案与引用 → 缓存 |
| `aclguard/kb_stub.py` | 最坏情形的知识库桩：**完全不做 ACL**，按关键词整条返回 |
| `aclguard/iam_stub.py` | 5 个虚构角色的 IAM 桩 |
| `aclguard/leak.py` | 100 问题 × 5 角色的泄露测试与报告生成 |
| `fixtures/roles.json` | 5 个角色（前台 / 社群运营 / 招商业务员 / 招商主管 / 财务） |
| `fixtures/knowledge_40.json` | 40 条虚构知识，`all_staff` 10 / `role_limited` 12 / `site_limited` 10 / `confidential` 8 |
| `fixtures/questions_100.json` | 100 个虚构问题 |
| `tests/` | 5 个测试文件 |
| `scripts/collect_metrics.py` | 现算全部交付数字，写 `metrics.json` |
| `scripts/selfcheck.sh` | 复制到临时目录后跑全套（等价干净 clone） |
| `reports/leak_test_report.md` | 泄露测试报告（脚本生成） |

## 2. 运行环境与命令

```bash
# 依赖：Python 3.11+ 与 pytest（本机实测 Python 3.11.9 / pytest 9.2.0）
python -m venv .venv
.venv/Scripts/python.exe -m pip install pytest

# 跑全部测试（Windows Git Bash 下同样可用）
cd E:/AI接单/Clawhunt-2/delivery/deliverables/1852
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest -q
# 预期末行：61 passed in 0.38s

# 现算指标（会重写 metrics.json 与 reports/leak_test_report.md）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/collect_metrics.py
# 预期：打印 JSON，EXIT=0

# 干净副本自检
bash scripts/selfcheck.sh
```

## 3. 每条验收的复现步骤与证据

### AC1 知识库桩故意返回无权片段时，模型请求体不含该片段内容，并有 `kb_acl_dropped` 日志

```bash
.venv/Scripts/python.exe -m pytest -q tests/test_ac1_dropped_before_model.py
```

- 做法：`LeakyKnowledgeBase` 对任何提问都返回 `confidential` 的 `doc-033`（欠款清单）与 `all_staff` 的 `doc-001`；`test_acl1_kb_stub_returns_forbidden_chunk_then_model_body_clean` 断言 `model.last_request.as_dict()` 里既无 `doc-033`、也无该条目标题与前 20 字正文，且 `kb_acl_dropped` 恰好 1 条、其 `doc_id == doc-033`、`reason == principal_deny`、`role_fp`/`site_fp` 均为 16 位。
- 反向断言：`log_payload_has_leak(...)` 把日志 record 的全部字段序列化后再搜正文前 20 字，结果必须为 `False` —— 证明日志只记 `doc_id`，没把内容写进日志。

### AC2 100 个问题的泄露测试中，无权条目的标题与原文出现次数为 0

```bash
.venv/Scripts/python.exe -m pytest -q tests/test_ac2_leak_100.py
cat reports/leak_test_report.md
```

- 100 个问题 × 5 个角色 = 500 次问答，每次对全部 40 条逐条判定「本次应可见 / 不应可见」，对不应可见的条目检查助手侧产物（回答文本、助手轮次消息与引用、交给模型的 `context`）是否出现其标题或正文前 40 字。
- 实测断言次数 `11100`、命中 `0`、通过率 `1.0`；正控 `positive_citations = 1008 > 0`，排除「全部拒答」造成的假通过。
- 说明：用户自己的提问里本来就会带着被问条目的标题，因此泄漏面只统计助手侧产物与模型 `context`，不含 `question` 字段。

### AC3 角色被收回后，历史消息中对应引用显示「该内容已无权查看」

```bash
.venv/Scripts/python.exe -m pytest -q tests/test_ac3_role_revoked.py
```

- 以「招商业务员」身份对 `doc-013`（`role_limited`，仅 `sales_rep`）提问并产生引用；随后用 `Principal.without_roles(["sales_rep"])` 模拟角色被收回。
- `render_history(...)` 返回 `folded >= 1`，且引用项的 `title` 与 `snippet` 都被替换为「该内容已无权查看」；仅看助手侧文本也不含原 `title` 与 `body[:40]`。同一份历史在角色未收回时渲染，不含折叠标记 —— 说明折叠由**当前**权限决定，而不是写死。
- 第二轮 `ask(...)` 的模型 `context` 同样不含该条目标题与正文前 40 字。

### AC4 单元测试断言缓存键包含角色与 site 指纹

```bash
.venv/Scripts/python.exe -m pytest -q tests/test_ac4_cache_key.py
```

- `cache_key("qa", p, q)` 形如 `qa:{role_fp}:{site_fp}:{query_fp}`，断言两个指纹都在键里、键被 3 个冒号切成 4 段。
- 5 个角色对同一问题的键两两不同；同角色换 `site_id` 键也不同。
- 功能侧：A 角色写入的缓存，B 角色读取为 `None`（`misses == 2`），证明隔离不是只靠命名。

### 附加：可见性判定矩阵

```bash
.venv/Scripts/python.exe -m pytest -q tests/test_visibility_matrix.py
```

- 4 种 `label` × 5 个角色 × 2 个馆 = 40 例参数化，逐格断言 `visible` 与 `reason`（`label_all_staff` / `role_hit` / `role_miss` / `site_hit` / `site_miss` / `principal_allow` / `principal_deny` / `scope_miss` / `label_unknown`）。

## 4. 实测数字（由 `scripts/collect_metrics.py` 现算，见 `metrics.json`）

- Python `3.11.9`；`pytest 9.2.0`；`pytest -q` 末行 `61 passed in 0.38s`，退出码 `0`
- 测试文件 `5` 个、用例 `61` 个；包内 `10` 个 `.py`、有效代码行 `608`；测试有效代码行 `241`
- 夹具：角色 `5`、知识 `40`（`all_staff` 10 / `role_limited` 12 / `site_limited` 10 / `confidential` 8）、问题 `100`、馆 `2`
- 泄露测试：断言 `11100` 次、命中 `0`、通过率 `1.0`、正控引用 `1008` 次、被判丢弃片段累计 `1992` 次
- 密钥扫描：5 组模式（`cph_` / `gho_` / `github_pat_` / `sk-` / `AKIA`）全目录扫描，命中 `0`
- 目录内容摘要 `tree_sha256 = f552d8c520e2a8b5618b609c65456d44da3b5f7cebb5ad6d533dafeb74745b19`（不含 `metrics.json` 与 `.venv`）

## 5. 与真实系统的对接点（mock 边界）

本包**不连**任何后端、数据库或模型服务，全部跑在本地内存里：

| 本包 | 生产替换为 | 对接说明 |
| --- | --- | --- |
| `kb_stub.LeakyKnowledgeBase.search` | S3-KB 检索接口 | 只需返回 `Chunk`（含 `doc_id`/`title`/`text`/`visibility_label`/`module`/`allowed_roles`/`site_id`/`allowed_subject_ids`）；助手侧不信任其过滤结果 |
| `iam_stub.load_roles` | S2-IAM `whoami` | 需要 `subject_id`、`roles`、`site_id`、`data_scope` 四项；`roles` 必须是**当前**授权集合，撤回即时生效 |
| `assistant.RecordingModelClient` | 真实模型调用 | 只用 `ModelRequest.chunks` 拼上下文；不要把 `SecondCheckResult.dropped` 传进去 |
| `cache_key.TTLCache` | Redis | 键格式保持不变；`role_fp` + `site_fp` 必须参与键，禁止只按 `session_id` 缓存 |
| `history.CitationRef` | 会话存储 | 引用快照必须**随消息保存 ACL 字段**，否则收回角色后无法重新判定 |

## 6. 已知边界

- `role_limited` 只做角色集合交集，不做「角色层级」推导；层级由 IAM 在 `roles` 里展开。
- `confidential` 只认 `allowed_subject_ids` 名单，默认拒绝；如需按组织架构放行，应在 IAM 侧先展开到人员名单。
- `data_scope` 判定先于 `label` 判定：模块不在范围内一律 `scope_miss` 拒绝，这是有意的「先粗后细」。
- 缓存不做真实 TTL 淘汰（只用于证明隔离）；生产用 Redis 时补 `EX` 即可。