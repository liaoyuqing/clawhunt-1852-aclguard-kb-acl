# AC2 泄露测试报告（100 问题 × 5 角色，0 命中）

对应验收条款：**「100 个问题的泄露测试中，无权条目的标题与原文出现次数为 0（附测试报告）」**。

本报告位于仓库根目录，所有数字均由本机实际执行产生（Python 3.11.9 / pytest 9.2.0，解释器 `.venv/Scripts/python.exe`），未手工填写；生成逻辑见 `aclguard/leak.py` 的 `run_leak_suite` 与 `to_report`，逐字产物另存于 `reports/leak_test_report.md`。

## 1. 指标（实测）

| 指标 | 实测值 |
| --- | --- |
| 问题数 | 100 |
| 角色数 | 5 |
| 候选格（100 问题 × 5 角色 × 40 条） | 11100 |
| **断言次数（实际扫描过的无权条目格）** | **1992** |
| 空转格（本轮未被检索到，扫描恒为 0，不计入分母） | 9108 |
| 泄露命中 | 0 |
| 通过率 | 1.000000 |
| 授权引用（正控） | 1008 |
| 被丢弃片段累计 | 1992 |

> 分母口径：只有「知识库本轮确实检索到、并被助手侧二次校验拦下」的条目才算一个真的检查格。
> 没被检索到的条目扫描必然是 0，那是空转（`skipped_by_acl`），计入分母只会把命中率稀释到好看，
> 掩盖检测器本身是否有效。因此 `checks = 1992`，与 `dropped_total` 逐格相等。

## 2. 分角色统计（5 行 + 合计）

| 角色 key | 问答轮次 | 断言次数（实际扫描） | 空转格 | 泄露命中 | 授权引用（正控） |
| --- | --- | --- | --- | --- | --- |
| community | 100 | 429 | 1871 | 0 | 171 |
| finance | 100 | 372 | 1628 | 0 | 228 |
| front | 100 | 445 | 1955 | 0 | 155 |
| sales | 100 | 415 | 1985 | 0 | 185 |
| sales_lead | 100 | 331 | 1669 | 0 | 269 |
| **合计** | 500 | 1992 | 9108 | 0 | 1008 |

## 3. 判据

**判据**：对每一次问答，凡当前角色无权查看的条目，其**标题**与**正文前 40 字**在四个泄露面 —— 回答 `answer`、助手轮次消息、引用（`citations`）、模型请求体 `context` 中出现次数均为 **0**；同时以正控 `positive_citations = 1008 > 0` 证明本轮仍正常产生了授权引用，从而排除「一律拒答」导致的假通过。

判定实现：`aclguard/leak.py:67` 的 `forbidden_markers` 只取 `entry.title` 与 `entry.body[:40]`；`aclguard/leak.py:72` 的 `scan_text` 命中任一即计为泄露；`aclguard/leak.py:143`–`aclguard/leak.py:159` 只对「本轮被检索到且被拦下」的条目累加 `run.checks`，命中才递增 `run.hits`。

**检测器自身也有正控**（否则「命中 0」可能只是检测器坏了）：`tests/test_repair_gaps.py:316`–`tests/test_repair_gaps.py:335` 把条目标题与正文前 40 字真的塞进产物，断言 `scan_text` 返回 `True`、并在 `scan_surface` 拼出的面上再次命中。把 `scan_text` 改成恒 `False`，这条用例立刻变红。

## 4. 复现命令（原文）

```bash
.venv/Scripts/python.exe -m pytest -q tests/test_ac2_leak_100.py
cat reports/leak_test_report.md
```

实测输出：`3 passed in 0.31s`，退出码 `0`（用例数固定 3，耗时随机器浮动）。全量回归见根目录 `reports/pytest_output.txt`（`78 passed`，`EXIT=0`）。

## 5. 统计口径说明

**本报告不统计用户自己的提问字段。** 用户提问里本来就带着被问条目的标题，把它计入会让统计失真；因此 `aclguard/leak.py:81`–`aclguard/leak.py:98` 的 `scan_surface` 只拼接 answer、assistant 轮次消息与 `model.last_request.chunks`（即模型请求体 `context`），外加折叠后的 `history`，不含 `question` 字段。

补充口径：

- 断言次数 = 各角色「本轮被检索到且被拦下」的条目数之和，故 5 行断言次数不等、合计 1992；候选格 11100 是「全部条目遍历一遍」的上界，不是分母。
- 「被丢弃片段累计 1992」是 500 次问答里 `second_check.filter_chunks` 判定丢弃的片段总数；它与断言次数相等不是巧合 —— 每个被计入的格就对应一次真实的丢弃。
- 正控样本（授权引用确实发生）：问题 `q-001`，提问角色 `front`，被授权引用条目 `doc-001`（`入馆流程总览`）。

## 6. 断言所在代码位置

| 断言 | 位置 |
| --- | --- |
| 问题数 100 / 角色数 5 | `tests/test_ac2_leak_100.py:18`、`tests/test_ac2_leak_100.py:19` |
| 泄露命中 0 | `tests/test_ac2_leak_100.py:21` |
| 通过率 1.0 | `tests/test_ac2_leak_100.py:22` |
| 正控 > 0 | `tests/test_ac2_leak_100.py:23` |
| 夹具形状 5/40/100 与标签分布 | `tests/test_ac2_leak_100.py:36`–`tests/test_ac2_leak_100.py:47` |
| 报告落盘且含「无命中」 | `tests/test_ac2_leak_100.py:32`–`tests/test_ac2_leak_100.py:33` |
| 检测器正控（塞进去必须命中） | `tests/test_repair_gaps.py:316`–`tests/test_repair_gaps.py:335` |
| 分母口径（空转不计入、checks == dropped_total） | `tests/test_repair_gaps.py:338`–`tests/test_repair_gaps.py:351` |
| 逐条扫描与计数逻辑 | `aclguard/leak.py:143`–`aclguard/leak.py:159` |
| 泄露面拼接（不含 question） | `aclguard/leak.py:81`–`aclguard/leak.py:98` |
