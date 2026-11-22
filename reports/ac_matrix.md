# 验收矩阵（AC 复现步骤与证据）

本文件逐条列出验收项、复现命令、对应测试函数与证据文件。所有数字均为本机实测（Python 3.11.9 / pytest 9.2.0，`.venv/Scripts/python.exe`）。

复现前置：

```bash
cd E:/AI接单/Clawhunt-2/delivery/deliverables/1852
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m pytest -q
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/collect_metrics.py
```

## 总览

| AC | 要求 | 测试文件 | 测试函数 | 证据文件 | 实测结论 |
| --- | --- | --- | --- | --- | --- |
| AC1 | 无权片段在交给模型前被丢弃，日志只记 doc_id | `tests/test_ac1_dropped_before_model.py` | `test_acl1_kb_stub_returns_forbidden_chunk_then_model_body_clean`、`test_acl1_filter_chunks_drops_every_label_combination` | `reports/ac_matrix.md`、`metrics.json` | 模型请求体不含被丢弃条目；`kb_acl_dropped` 记 1 条且 doc_id 正确；日志 record 全字段无正文 |
| AC2 | 100 问题 x 5 角色的泄露测试 0 命中，且有正控 | `tests/test_ac2_leak_100.py` | `test_acl2_leak_suite_100_questions_zero_unauthorized_hits`、`test_acl2_report_written_with_zero_hits`、`test_acl2_fixture_shape_is_exactly_5_40_100` | `reports/leak_test_report.md`、`metrics.json` | 断言 11100 次，命中 0，正控引用 1008 次 |
| AC3 | 角色被收回后历史引用折叠为「该内容已无权查看」 | `tests/test_ac3_role_revoked.py` | `test_acl3_revoked_role_folds_history_citation`、`test_acl3_next_turn_model_request_excludes_revoked_citation` | `metrics.json`（`fold_marker_count`） | 折叠 1 条引用、标记出现 3 次；角色未收回时标记 0 次 |
| AC4 | 缓存键必须含角色指纹与 site 指纹 | `tests/test_ac4_cache_key.py` | `test_acl4_cache_key_contains_role_and_site_fingerprint`、`test_acl4_different_role_and_site_never_share_key`、`test_acl4_cache_written_by_one_role_is_invisible_to_another` | `metrics.json` | 键 4 段、两指纹齐全；跨角色读缓存 miss |
| 附加 | 4 种 label x 5 角色 x 2 个馆 判定矩阵 | `tests/test_visibility_matrix.py` | `test_all_staff_visible_for_every_role_and_site` 等 6 个参数化函数 | `reports/ac_matrix.md` 末节 | 40 例矩阵逐格断言 `visible` 与 `reason` |

## AC1 无权片段在交给模型前丢弃

```bash
.venv/Scripts/python.exe -m pytest -q tests/test_ac1_dropped_before_model.py
```

1. `LeakyKnowledgeBase`（`aclguard/kb_stub.py`）按关键词把条目整条返回，**完全不做 ACL**：返回 `confidential` 的 `doc-033` 与 `all_staff` 的 `doc-001`。
2. `assistant.ask` 调用 `second_check.filter_chunks`，逐片段用 `visibility.decide(chunk.entry, principal)` 重判。
3. 只有 `visible_chunks` 会进入 `describe_for_model` 并拼成 `ModelRequest`；`dropped` 只保留 `doc_id` / `reason` / `matched_by`。
4. 断言：`model.last_request.as_dict()` 序列化后不含 `doc-033`、不含其标题、不含正文前 20 字；`kb_acl_dropped` 恰好 1 条且 doc_id 为 `doc-033`，`reason == principal_deny`，`role_fp` / `site_fp` 均 16 位。
5. 反向断言：`log_payload_has_leak(record, [body[:20], title])` 必须为 `False` —— 把日志 record 的全部字段序列化后再搜，证明日志本身不成为泄露面。

## AC2 泄露测试 0 命中

```bash
.venv/Scripts/python.exe -m pytest -q tests/test_ac2_leak_100.py
cat reports/leak_test_report.md
```

1. 100 个问题 x 5 个角色 = 500 次问答，每次问答后对全部 40 条逐条判断「本轮该角色应可见 / 不应可见」。
2. 对不应可见的条目，在其标题与正文前 40 字两个判据上扫描助手侧产物：回答文本、助手轮次消息与引用、模型请求体的 `context`。
3. 实测：断言 `11100` 次、命中 `0`、通过率 `1.0`；分角色断言次数与授权引用次数见 `reports/leak_test_report.md` 的统计表。
4. 正控：`positive_citations = 1008 > 0`，报告另附 1 条正控样本（`q-001` / `front` / `doc-001`），证明不是「全部拒答」造成的假通过。
5. 说明：用户自己的提问里本就带着被问条目，因此泄漏面不含 `question` 字段，只统计助手侧产物。

## AC3 角色收回后折叠历史引用

```bash
.venv/Scripts/python.exe -m pytest -q tests/test_ac3_role_revoked.py
```

1. 以「招商业务员」身份对 `doc-013`（`role_limited`，仅 `sales_rep` 可见）提问，产生引用快照并写入会话历史。
2. `Principal.without_roles(["sales_rep"])` 模拟角色在中途被收回。
3. `history.render_history(messages, revoked)` 用**当前** principal 重新判定每条引用：不可见者 `title` 与 `snippet` 双双替换为 `「该内容已无权查看」`，消息正文里出现的标题与片段也一并替换。
4. 断言：折叠数 ≥ 1；渲染文本含占位符；助手侧文本不含原 title 与 `body[:40]`；同一份历史在角色未收回时渲染 **不含**占位符（证明折叠由当前权限决定，不是写死）。
5. 第二轮 `ask(...)` 的模型 `context` 同样不含该条目标题与正文前 40 字；`visible_citations_only` 也不再返回它。
6. `metrics.json` 里 `fold_marker_count = 3`、`fold_citations = 1`，而 `fold_marker_count_when_role_kept = 0`，对照明确。

## AC4 缓存键隔离

```bash
.venv/Scripts/python.exe -m pytest -q tests/test_ac4_cache_key.py
```

1. `cache_key(kind, principal, query)` = `kind:role_fp:site_fp:query_fp`，四段三段冒号；`role_fp = sha256("|".join(sorted(roles)))[:16]`，`site_fp = sha256(site_id)[:16]`。
2. 断言两个指纹都出现在键里；5 个角色对同一问题两两不等；同角色换 `site_id` 键不等；同输入重复计算稳定。
3. 功能断言：`TTLCache` 里 A 角色写入后，B 角色读为 `None`（`misses == 2`），证明隔离不只靠命名。

## 判定矩阵

```bash
.venv/Scripts/python.exe -m pytest -q tests/test_visibility_matrix.py
```

`test_visibility_matrix.py` 用 5 个角色 x 2 个馆 = 10 组参数，覆盖 6 个判定函数（`all_staff`、`role_limited`、`site_limited`、`confidential`、`data_scope` 越界、未知标签），共 40 例。`reason` 取值集合为 `label_all_staff` / `role_hit` / `role_miss` / `site_hit` / `site_miss` / `principal_allow` / `principal_deny` / `confidential_default_deny` / `scope_miss` / `label_unknown`。

## 密钥扫描

```bash
# 模式串在采集脚本内由片段拼接，避免脚本自身成为命中项
.venv/Scripts/python.exe scripts/collect_metrics.py
# 读取 metrics.json 的 secret_scan / secret_scan_hits 字段
```

实测：5 组上游令牌前缀模式全目录扫描，`hit_count = 0`。
