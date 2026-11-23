# AC2 泄露测试报告（100 问题 × 5 角色，0 命中）

对应验收条款：**「100 个问题的泄露测试中，无权条目的标题与原文出现次数为 0（附测试报告）」**。

本报告位于仓库根目录，所有数字均由本机实际执行产生（Python 3.11.9 / pytest 9.2.0，解释器 `.venv/Scripts/python.exe`），未手工填写；生成逻辑见 `aclguard/leak.py` 的 `run_leak_suite` 与 `to_report`，逐字产物另存于 `reports/leak_test_report.md`。

## 1. 指标（实测）

| 指标 | 实测值 |
| --- | --- |
| 问题数 | 100 |
| 角色数 | 5 |
| 断言次数 | 11100 |
| 泄露命中 | 0 |
| 通过率 | 1.000000 |
| 授权引用（正控） | 1008 |
| 被丢弃片段累计 | 1992 |

## 2. 分角色统计（5 行 + 合计）

| 角色 key | 问答轮次 | 断言次数（无权条目） | 泄露命中 | 授权引用（正控） |
| --- | --- | --- | --- | --- |
| community | 100 | 2300 | 0 | 171 |
| finance | 100 | 2000 | 0 | 228 |
| front | 100 | 2400 | 0 | 155 |
| sales | 100 | 2400 | 0 | 185 |
| sales_lead | 100 | 2000 | 0 | 269 |
| **合计** | 500 | 11100 | 0 | 1008 |

## 3. 判据

**判据**：对每一次问答，凡当前角色无权查看的条目，其**标题**与**正文前 40 字**在四个泄露面 —— 回答 `answer`、助手轮次消息、引用（`citations`）、模型请求体 `context` —— 中出现次数均为 **0**；同时以正控 `positive_citations = 1008 > 0` 证明本轮仍正常产生了授权引用，从而排除「一律拒答」导致的假通过。

判定实现：`aclguard/leak.py:54` 的 `forbidden_markers` 只取 `entry.title` 与 `entry.body[:40]`；`aclguard/leak.py:59` 的 `scan_text` 命中任一即计为泄露；`aclguard/leak.py:123` 起对每条 `denied` 条目逐条累加 `run.checks`，命中才递增 `run.hits`。

## 4. 复现命令（原文）

```bash
.venv/Scripts/python.exe -m pytest -q tests/test_ac2_leak_100.py
cat reports/leak_test_report.md
```

实测输出：`3 passed in 0.16s`，退出码 `0`。全量回归见根目录 `reports/pytest_output.txt`（`61 passed`，`EXIT=0`）。

## 5. 统计口径说明

**本报告不统计用户自己的提问字段。** 用户提问里本来就带着被问条目的标题，把它计入会让统计失真；因此 `aclguard/leak.py:68` 的 `scan_surface` 只拼接 answer、assistant 轮次消息与 `model.last_request.chunks`（即模型请求体 `context`），不含 `question` 字段。

补充口径：

- 断言次数 = 问题数 × 角色数 × 该角色当次不可见条目数（各角色可见集合不同，故 5 行断言次数不等、合计 11100）。
- 「被丢弃片段累计 1992」是 500 次问答里 `second_check.filter_chunks` 判定丢弃的片段总数，与断言次数口径不同（前者按检索命中计，后者按全量条目遍历计）。
- 正控样本（授权引用确实发生）：问题 `q-001`，提问角色 `front`，被授权引用条目 `doc-001`（`入馆流程总览`）。

## 6. 断言所在代码位置

| 断言 | 位置 |
| --- | --- |
| 问题数 100 / 角色数 5 | `tests/test_ac2_leak_100.py:18`、`tests/test_ac2_leak_100.py:19` |
| 泄露命中 0 | `tests/test_ac2_leak_100.py:21` |
| 通过率 1.0 | `tests/test_ac2_leak_100.py:22` |
| 正控 > 0 | `tests/test_ac2_leak_100.py:23` |
| 夹具形状 5/40/100 与标签分布 | `tests/test_ac2_leak_100.py:36` |
| 报告落盘且含「无命中」 | `tests/test_ac2_leak_100.py:32`、`tests/test_ac2_leak_100.py:33` |
| 逐条扫描逻辑 | `aclguard/leak.py:123`–`aclguard/leak.py:134` |
| 泄露面拼接（不含 question） | `aclguard/leak.py:68`–`aclguard/leak.py:81` |

