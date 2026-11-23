# 验收证据索引（EVIDENCE）

工单 **S5-ASST-007**「按角色过滤可见知识：助手侧二次校验与泄露测试」。本表把 4 条验收 + 1 条附加矩阵与**可执行命令、可观察结果、证据文件、断言代码位置**一一对应，评审不必翻目录即可逐条复核。

环境：Python 3.11.9 / pytest 9.2.0，解释器 `.venv/Scripts/python.exe`（仓库内已有，不新建、不联网）。全部数字均为本机实测；`pytest` 末行里的耗时每次运行浮动（用例数固定），以用例数与退出码为准。

## 总表

| 验收编号 | 复现命令 | 预期可观察结果 | 证据文件路径 | 断言所在代码位置（文件:行） |
| --- | --- | --- | --- | --- |
| **AC1** 知识库桩故意返回无权片段时，模型请求体不含该片段内容，并有 `kb_acl_dropped` 日志 | `.venv/Scripts/python.exe -m pytest -q tests/test_ac1_dropped_before_model.py` | `2 passed`（本次实测末行 `2 passed in 0.04s`，耗时随机器浮动）；模型请求体不含 `doc-033` 及其标题、正文前 20 字；`kb_acl_dropped` 恰 1 条且 `doc_id=doc-033`、`reason=principal_deny`、`role_fp`/`site_fp` 各 16 位；日志全字段序列化后不含标题与正文（`log_payload_has_leak` 为 `False`） | `tests/test_ac1_dropped_before_model.py`、`reports/pytest_output.txt`、`metrics.json` | `tests/test_ac1_dropped_before_model.py:66`–`tests/test_ac1_dropped_before_model.py:79`；第二例 `tests/test_ac1_dropped_before_model.py:90`–`tests/test_ac1_dropped_before_model.py:92`；判定 `aclguard/second_check.py:28`–`aclguard/second_check.py:33`；请求体装配 `aclguard/assistant.py:191`–`aclguard/assistant.py:198` |
| **AC2** 100 个问题的泄露测试中，无权条目的标题与原文出现次数为 0（附测试报告） | `.venv/Scripts/python.exe -m pytest -q tests/test_ac2_leak_100.py` 与 `cat reports/leak_test_report.md` | `3 passed`（断言次数按精确值 1992 / 空转 9108 / 合计 11100 钉住）；候选格 `11100`、实际扫描断言 `1992` 次、空转 `9108` 格不计入分母、命中 `0`、通过率 `1.0`、正控引用 `1008 > 0`、丢弃片段累计 `1992`；报告含「泄露命中次数 \| 0 \|」与「无命中」；检测器正控用例把标题塞进产物后必须命中 | `AC2_LEAK_TEST_REPORT.md`（根目录）、`reports/leak_test_report.md`、`reports/pytest_output.txt` | `tests/test_ac2_leak_100.py:18`–`tests/test_ac2_leak_100.py:27`、`tests/test_ac2_leak_100.py:32`–`tests/test_ac2_leak_100.py:33`；检测器正控 `tests/test_repair_gaps.py:316`–`tests/test_repair_gaps.py:335`；分母口径 `tests/test_repair_gaps.py:338`–`tests/test_repair_gaps.py:351`；扫描逻辑 `aclguard/leak.py:143`–`aclguard/leak.py:159`；泄露面 `aclguard/leak.py:81`–`aclguard/leak.py:98` |
| **AC3** 角色被收回后，历史消息中对应引用显示「该内容已无权查看」 | `.venv/Scripts/python.exe -m pytest -q tests/test_ac3_role_revoked.py` 与 `tests/test_rework_1852.py` | `2 passed in 0.04s`；`ask()` 主链路产出 `reusable_citation_doc_ids`（首轮空 → 次轮含 → 角色收回后消失）；折叠引用 `1` 条、标记出现 `3` 次；助手侧文本不含原 `title` 与 `body[:40]`；角色未收回时标记 `0` 次；第二轮模型 `context` 同样不含该条目；**折叠已接进 `ask()` 主链路**，模型请求体 `history` 里也是折叠后的版本（变异自证见 `FIX_REVIEW.md`） | `tests/test_ac3_role_revoked.py`、`metrics.json`（`fold_marker_count`/`fold_citations`）、`FIX_REVIEW.md` | `tests/test_ac3_role_revoked.py:36`–`tests/test_ac3_role_revoked.py:44`、`tests/test_ac3_role_revoked.py:47`–`tests/test_ac3_role_revoked.py:48`、`tests/test_ac3_role_revoked.py:61`–`tests/test_ac3_role_revoked.py:62`；接线断言 `tests/test_repair_gaps.py:66`–`tests/test_repair_gaps.py:95`；折叠 `aclguard/history.py:12`–`aclguard/history.py:17`、`aclguard/history.py:33`–`aclguard/history.py:35`；接线点 `aclguard/assistant.py:191`–`aclguard/assistant.py:198` |
| **AC4** 单元测试断言缓存键包含角色与 site 指纹 | `.venv/Scripts/python.exe -m pytest -q tests/test_ac4_cache_key.py` 与 `tests/test_rework_1852.py` | `3 passed in 0.03s`；同角色同馆只差 `subject_id` 的两个主体共用缓存时 confidential 不串（返修 blocker）；`qa:{role_fp}:{site_fp}:{subject_fp}:{scope_fp}:{query_fp}` 含四个指纹、5 个冒号 6 段；5 角色键两两不等；同角色换 `site_id`、换 `subject_id`、收缩 `data_scope` 键都不等；跨角色读缓存 `None` 且 `misses == 2` | `tests/test_ac4_cache_key.py`、`metrics.json` | `tests/test_ac4_cache_key.py:12`–`tests/test_ac4_cache_key.py:17`、`tests/test_ac4_cache_key.py:22`、`tests/test_ac4_cache_key.py:29`、`tests/test_ac4_cache_key.py:37`–`tests/test_ac4_cache_key.py:40`；subject/scope 覆盖 `tests/test_repair_gaps.py:201`–`tests/test_repair_gaps.py:259`；键构造 `aclguard/cache_key.py:38`–`aclguard/cache_key.py:50` |
| **附加** 可见性判定矩阵（4 label × 5 角色 × 2 馆 = 40 个矩阵格） | `.venv/Scripts/python.exe -m pytest -q tests/test_visibility_matrix.py` | `51 passed in 0.09s`（5 个参数化函数 × 10 组角色/馆 = 50 例，外加 1 例未知标签；覆盖 40 个矩阵格）；逐格断言 `visible` 与 `reason`（`label_all_staff` / `role_hit` / `role_miss` / `site_hit` / `site_miss` / `principal_allow` / `principal_deny` / `confidential_default_deny` / `scope_miss` / `label_unknown`） | `tests/test_visibility_matrix.py`、`reports/ac_matrix.md` | `tests/test_visibility_matrix.py:28`–`tests/test_visibility_matrix.py:29`、`tests/test_visibility_matrix.py:36`–`tests/test_visibility_matrix.py:37`、`tests/test_visibility_matrix.py:44`–`tests/test_visibility_matrix.py:45`、`tests/test_visibility_matrix.py:52`–`tests/test_visibility_matrix.py:53`、`tests/test_visibility_matrix.py:60`–`tests/test_visibility_matrix.py:61`、`tests/test_visibility_matrix.py:67`–`tests/test_visibility_matrix.py:68`；判定主体 `aclguard/visibility.py:29`–`aclguard/visibility.py:63` |
| **附加** 返修 9 处缺口的回归断言（审计可检索 / 缓存命中重判 / 缺标签 fail closed / 摘要排除 `.git` 且换行归一） | `.venv/Scripts/python.exe -m pytest -q tests/test_repair_gaps.py` | `17 passed in 0.20s`；每条用例都有对应的「改坏实现即变红」证明，见 `FIX_REVIEW.md` | `tests/test_repair_gaps.py`、`FIX_REVIEW.md` | 审计行可检索 `tests/test_repair_gaps.py:264`–`tests/test_repair_gaps.py:288`；单一 logger `tests/test_repair_gaps.py:290`–`tests/test_repair_gaps.py:299`；缓存命中重判 `tests/test_repair_gaps.py:124`–`tests/test_repair_gaps.py:194`；`request_id` 对齐 `tests/test_repair_gaps.py:356`–`tests/test_repair_gaps.py:367`；`CitationRef` fail closed `tests/test_repair_gaps.py:372`–`tests/test_repair_gaps.py:393`；摘要排除 `.git` 与换行归一（CRLF/LF 同哈希）`tests/test_repair_gaps.py:398`–`tests/test_repair_gaps.py:415` |
| **附加** 返修 2 轮（买家 3 条）| `.venv/Scripts/python.exe -m pytest -q tests/test_rework_1852.py` | `4 passed`；缓存键跨主体隔离、`visible_citations_only` 主链路接线、AC2 精确分母三条各自可证伪 | `tests/test_rework_1852.py`、`FIX_REVIEW.md` 第 6 节 | `tests/test_rework_1852.py` 四个用例：`test_rework_cache_key_covers_subject_so_confidential_does_not_leak_between_principals`、`test_rework_confidential_title_absent_from_denied_side_after_shared_cache_reuse`、`test_rework_visible_citations_only_wired_through_ask_main_chain`、`test_rework_ac2_checks_equal_exact_sum_of_denied_entries_per_role` |

## 全量回归与指标复现

```bash
# 全量回归：末行应为 82 passed，退出码 0；逐字输出已存档
.venv/Scripts/python.exe -m pytest -q
# 现算全部指标（会重写 metrics.json 与 reports/leak_test_report.md）
.venv/Scripts/python.exe scripts/collect_metrics.py
```

- `reports/pytest_output.txt`：全量 `pytest -q` 的真实重定向输出，含末行 `82 passed` 与 `EXIT=0`，由实际执行产生、非手写。
- `metrics.json`：`collect_metrics.py` 现算并回填 README 第 4 节的数据快照（含 `pytest_last_line`、`leak_*`、`fold_*`、`secret_scan`、`tree_sha256`）。
- `FIX_REVIEW.md`：9 处缺口 + 第 2 轮买方 3 条的逐条说明、8 次变异自证（改坏实现 → 哪条用例变红 → 恢复后全绿）与两处既有断言变更的理由。
- 密钥扫描：5 组上游令牌前缀模式全目录扫描，`hit_count = 0`；模式串由脚本内部拼接，代码与文档中不留字面量。

## 与 AC2 报告的关系

根目录 `AC2_LEAK_TEST_REPORT.md` 是本表 AC2 行的**主证据**（评审在根目录即可看到指标表、5 行分角色表、判据与复现命令）；`reports/leak_test_report.md` 是脚本 `to_report` 生成的逐字产物，两者数字同源（同一次 `run_leak_suite()` 口径）。
