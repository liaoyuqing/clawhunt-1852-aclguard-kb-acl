# 验收证据索引（EVIDENCE）

工单 **S5-ASST-007**「按角色过滤可见知识：助手侧二次校验与泄露测试」。本表把 4 条验收 + 1 条附加矩阵与**可执行命令、可观察结果、证据文件、断言代码位置**一一对应，评审不必翻目录即可逐条复核。

环境：Python 3.11.9 / pytest 9.2.0，解释器 `.venv/Scripts/python.exe`（仓库内已有，不新建、不联网）。全部数字均为本机实测。

## 总表

| 验收编号 | 复现命令 | 预期可观察结果 | 证据文件路径 | 断言所在代码位置（文件:行） |
| --- | --- | --- | --- | --- |
| **AC1** 知识库桩故意返回无权片段时，模型请求体不含该片段内容，并有 `kb_acl_dropped` 日志 | `.venv/Scripts/python.exe -m pytest -q tests/test_ac1_dropped_before_model.py` | `2 passed`；模型请求体不含 `doc-033` 及其标题、正文前 20 字；`kb_acl_dropped` 恰 1 条且 `doc_id=doc-033`、`reason=principal_deny`、`role_fp`/`site_fp` 各 16 位；日志全字段序列化后不含标题与正文（`log_payload_has_leak` 为 `False`） | `tests/test_ac1_dropped_before_model.py`、`reports/pytest_output.txt`、`metrics.json` | `tests/test_ac1_dropped_before_model.py:66`–`tests/test_ac1_dropped_before_model.py:79`；第二例 `tests/test_ac1_dropped_before_model.py:90`–`tests/test_ac1_dropped_before_model.py:92`；判定 `aclguard/second_check.py:28`–`aclguard/second_check.py:33`；请求体装配 `aclguard/assistant.py:100`–`aclguard/assistant.py:101` |
| **AC2** 100 个问题的泄露测试中，无权条目的标题与原文出现次数为 0（附测试报告） | `.venv/Scripts/python.exe -m pytest -q tests/test_ac2_leak_100.py` 与 `cat reports/leak_test_report.md` | `3 passed`；断言 `11100` 次、命中 `0`、通过率 `1.0`、正控引用 `1008 > 0`、丢弃片段累计 `1992`；报告含「泄露命中次数 \| 0 \|」与「无命中」 | `AC2_LEAK_TEST_REPORT.md`（根目录）、`reports/leak_test_report.md`、`reports/pytest_output.txt` | `tests/test_ac2_leak_100.py:18`–`tests/test_ac2_leak_100.py:23`、`tests/test_ac2_leak_100.py:32`–`tests/test_ac2_leak_100.py:33`；扫描逻辑 `aclguard/leak.py:123`–`aclguard/leak.py:134`；泄露面 `aclguard/leak.py:68`–`aclguard/leak.py:81` |
| **AC3** 角色被收回后，历史消息中对应引用显示「该内容已无权查看」 | `.venv/Scripts/python.exe -m pytest -q tests/test_ac3_role_revoked.py` | `2 passed`；折叠引用 `1` 条、标记出现 `3` 次；助手侧文本不含原 `title` 与 `body[:40]`；角色未收回时标记 `0` 次；第二轮模型 `context` 同样不含该条目 | `tests/test_ac3_role_revoked.py`、`metrics.json`（`fold_marker_count`/`fold_citations`） | `tests/test_ac3_role_revoked.py:36`–`tests/test_ac3_role_revoked.py:44`、`tests/test_ac3_role_revoked.py:47`–`tests/test_ac3_role_revoked.py:48`、`tests/test_ac3_role_revoked.py:61`–`tests/test_ac3_role_revoked.py:62`；折叠 `aclguard/history.py:12`–`aclguard/history.py:17`、`aclguard/history.py:33`–`aclguard/history.py:35` |
| **AC4** 单元测试断言缓存键包含角色与 site 指纹 | `.venv/Scripts/python.exe -m pytest -q tests/test_ac4_cache_key.py` | `3 passed`；`qa:{role_fp}:{site_fp}:{query_fp}` 含两指纹、3 个冒号 4 段；5 角色键两两不等；同角色换 `site_id` 键不等；跨角色读缓存 `None` 且 `misses == 2` | `tests/test_ac4_cache_key.py`、`metrics.json` | `tests/test_ac4_cache_key.py:12`–`tests/test_ac4_cache_key.py:15`、`tests/test_ac4_cache_key.py:22`、`tests/test_ac4_cache_key.py:29`、`tests/test_ac4_cache_key.py:37`–`tests/test_ac4_cache_key.py:40`；键构造 `aclguard/cache_key.py:28`–`aclguard/cache_key.py:30` |
| **附加** 可见性判定矩阵（4 label × 5 角色 × 2 馆 = 40 个矩阵格） | `.venv/Scripts/python.exe -m pytest -q tests/test_visibility_matrix.py` | `51 passed`（5 个参数化函数 × 10 组角色/馆 = 50 例，外加 1 例未知标签；覆盖 40 个矩阵格）；逐格断言 `visible` 与 `reason`（`label_all_staff` / `role_hit` / `role_miss` / `site_hit` / `site_miss` / `principal_allow` / `principal_deny` / `scope_miss` / `label_unknown`） | `tests/test_visibility_matrix.py`、`reports/ac_matrix.md` | `tests/test_visibility_matrix.py:28`–`tests/test_visibility_matrix.py:29`、`tests/test_visibility_matrix.py:36`–`tests/test_visibility_matrix.py:37`、`tests/test_visibility_matrix.py:44`–`tests/test_visibility_matrix.py:45`、`tests/test_visibility_matrix.py:52`–`tests/test_visibility_matrix.py:53`、`tests/test_visibility_matrix.py:60`–`tests/test_visibility_matrix.py:61`、`tests/test_visibility_matrix.py:67`–`tests/test_visibility_matrix.py:68`；判定主体 `aclguard/visibility.py:29`–`aclguard/visibility.py:63` |

## 全量回归与指标复现

```bash
# 全量回归：末行应为 61 passed，退出码 0；逐字输出已存档
.venv/Scripts/python.exe -m pytest -q
# 现算全部指标（会重写 metrics.json 与 reports/leak_test_report.md）
.venv/Scripts/python.exe scripts/collect_metrics.py
```

- `reports/pytest_output.txt`：全量 `pytest -q` 的真实重定向输出，含末行 `61 passed` 与 `EXIT=0`，由实际执行产生、非手写。
- `metrics.json`：`collect_metrics.py` 现算并回填 README 第 4 节的数据快照（含 `pytest_last_line`、`leak_*`、`fold_*`、`secret_scan`）。
- 密钥扫描：5 组上游令牌前缀模式全目录扫描，`hit_count = 0`；模式串由脚本内部拼接，代码与文档中不留字面量。

## 与 AC2 报告的关系

根目录 `AC2_LEAK_TEST_REPORT.md` 是本表 AC2 行的**主证据**（评审在根目录即可看到指标表、5 行分角色表、判据与复现命令）；`reports/leak_test_report.md` 是脚本 `to_report` 生成的逐字产物，两者数字同源（同一次 `run_leak_suite()` 口径）。

