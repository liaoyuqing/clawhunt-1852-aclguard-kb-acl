# 返修自证（FIX_REVIEW）

本文件对应一次**独立只读审计**提出的 9 处缺口。审计方不是本文作者，结论是「按现状交付很可能过不了买方验收」。

处理原则：**不删任何既有用例、不削弱任何既有断言**；9 处缺口全部补上可证伪的回归断言，并对 5 处关键实现做了**变异自证** —— 把实现改坏，对应用例必须变红；恢复后必须全绿。

环境：Python 3.11.9 / pytest 9.2.0，解释器 `.venv/Scripts/python.exe`。

## 1. 九处缺口与修复

| # | 审计指出的问题 | 现状 | 修复后位置 | 钉住它的用例 |
| --- | --- | --- | --- | --- |
| 1 | AC3 根本没接线：`render_history` / `visible_citations_only` 全仓零调用，角色被收回后历史不会折叠 | 已接线：`ask()` 每次构造模型请求前调用 `render_history`，结果进 `ModelRequest.history` | `aclguard/assistant.py:177`–`aclguard/assistant.py:183` | `tests/test_repair_gaps.py:66`–`tests/test_repair_gaps.py:95` |
| 2 | 缓存命中直接返回旧答案，绕过二次校验 | 命中后按**知识库现行条目**重判；不通过则作废该键并重新作答 | `aclguard/assistant.py:97`–`aclguard/assistant.py:125`、`aclguard/assistant.py:147`–`aclguard/assistant.py:170` | `tests/test_repair_gaps.py:124`–`tests/test_repair_gaps.py:161`（重判杀掉）、`tests/test_repair_gaps.py:182`–`tests/test_repair_gaps.py:196`（反向：仍可见时正常走缓存） |
| 3 | 缓存键漏了 `subject_id` 与 `data_scope`：同角色换人、scope 收缩都会误命中 | 键从 4 段扩到 6 段 `kind:role_fp:site_fp:subject_fp:scope_fp:query_fp` | `aclguard/cache_key.py:28`–`aclguard/cache_key.py:50` | `tests/test_repair_gaps.py:201`–`tests/test_repair_gaps.py:259`、`tests/test_ac4_cache_key.py:12`–`tests/test_ac4_cache_key.py:17` |
| 4 | 审计事件检索不到：`doc_id`/`request_id` 只在 `LogRecord.extra` 里，且 `assistant` 与 `second_check` 用了两个 logger 名 | 单一 logger 名 `aclguard.audit`；关键字段进**格式化后的行文本** | `aclguard/audit.py:1`–`aclguard/audit.py:30`、`aclguard/second_check.py:44`–`aclguard/second_check.py:52` | `tests/test_repair_gaps.py:264`–`tests/test_repair_gaps.py:288`（正则从纯文本抽字段）、`tests/test_repair_gaps.py:290`–`tests/test_repair_gaps.py:311` |
| 5 | AC2 分母虚高：11100 格里绝大多数是空转，且检测器没有正控（把 `scan_text` 改成恒 `False` 仍然 61 绿） | 分母只算「真被检索到并拦下」的格；空转单列 `skipped_by_acl`；新增检测器正控 | `aclguard/leak.py:3`–`aclguard/leak.py:6`、`aclguard/leak.py:143`–`aclguard/leak.py:159` | `tests/test_repair_gaps.py:316`–`tests/test_repair_gaps.py:351` |
| 6 | `request_id` 没有任何断言，出事后对不上号 | 丢弃事件的 `request_id` 必须等于 `ask()` 返回的那个 | `aclguard/second_check.py:35`–`aclguard/second_check.py:52` | `tests/test_repair_gaps.py:356`–`tests/test_repair_gaps.py:367` |
| 7 | `CitationRef` 默认 `visibility_label="all_staff"` = 默认放行（fail-open） | 默认改为空串，缺失标签判 `label_unknown` 一律拒绝；旧历史和折叠同理 | `aclguard/models.py:97`、`aclguard/models.py:109` | `tests/test_repair_gaps.py:372`–`tests/test_repair_gaps.py:393` |
| 8 | `tree_sha256` 把 `.git` 也算进去，且按原始字节哈希；前者让提交目录与干净 clone 必然不同（c8283d… vs 733f3c…），后者让 `core.autocrlf=true` 的 CRLF 工作树与 LF 的 CI 得出两个摘要 | `SKIP_DIRS` 排除 `.git/`；`normalize_eol` 先把 `\r\n` 折成 `\n` 再进摘要，同一份内容跨平台同哈希 | `scripts/collect_metrics.py:75`–`scripts/collect_metrics.py:90` | `tests/test_repair_gaps.py:398`–`tests/test_repair_gaps.py:415` |
| 9 | `reports/ac_matrix.md` 写「51 例」，但矩阵夹具只有 40 格 | 改为 40 例矩阵 + 说明 51 是**用例数**（含 1 例未知标签） | `reports/ac_matrix.md:80` | `tests/test_repair_gaps.py:417`–`tests/test_repair_gaps.py:424` |

## 2. 变异自证（MUTATION）

做法：临时把实现改坏 → 跑对应用例 → 记录哪条变红 → 立刻恢复原文件（无残留，恢复后全绿）。

| # | 变异内容 | 实测结果 |
| --- | --- | --- |
| M1 | `assistant.py` 里把折叠短路成 `history, folded_count = [], 0` | `1 failed, 77 passed`，退出码 1；红：`test_repair_history_folding_is_wired_into_model_request` |
| M2 | `leak.py` 的 `scan_text` 开头加 `return False`（检测器恒不命中） | `1 failed, 77 passed`，退出码 1；红：`test_repair_detector_positive_control_catches_real_leak` |
| M3 | `assistant.py` 缓存命中处跳过重判（`revoked = []`） | `1 failed, 77 passed`，退出码 1；红：`test_repair_cache_hit_rechecks_and_does_not_serve_reclassified_entry` |
| M4 | `cache_key.py` 键退回 4 段（去掉 subject/scope） | `3 failed, 75 passed`，退出码 1；红：`test_repair_cache_key_covers_subject_and_scope`、`test_repair_cache_does_not_leak_across_subject_or_scope`、`test_ac4_cache_key.py::test_acl4_cache_key_contains_role_and_site_fingerprint` |
| M5 | `collect_metrics.py` 的 `SKIP_DIRS` 去掉 `.git/` | `1 failed, 77 passed`，退出码 1；红：`test_repair_tree_digest_ignores_git_directory` |

5 次变异全部「改坏即红」，恢复后 `78 passed, exit 0`。表中数字是全量 `pytest -q`（78 条用例）的实测结果，每次变异后都立刻还原源文件并复查 `git diff` 为空。

## 3. 唯一一处既有断言变更（必须申报）

`tests/test_ac4_cache_key.py:17`：`assert key.count(":") == 3` → `assert key.count(":") == 5`。

- **原因**：旧断言把「4 段键」写成了契约，而 4 段键正是审计指出的越权隐患（同角色换人或 scope 收缩会误命中）。若保留旧断言，第 3 项修复根本无法落地。
- **替代断言更强**：改成 5 个冒号后，又新增 `key.count(":") == 5`、`len(key.split(":")) == 6`、四个指纹各自 `in key`（`tests/test_repair_gaps.py:201`–`tests/test_repair_gaps.py:232`），并新增同角色他人 / scope 收缩两种功能级 miss 断言（`tests/test_repair_gaps.py:235`–`tests/test_repair_gaps.py:259`）。旧断言只是「段数对」，新断言覆盖了「换人换 scope 必须换键」。
- 其余 60 条既有用例**一条未删、一条未改**。

## 4. 分母口径变更（AC2）

| 口径 | 旧值 | 新值 |
| --- | --- | --- |
| 候选格（100 × 5 × 40） | 11100 | 11100（不变，仅作为上界展示） |
| 计入分母的断言次数 | 11100 | **1992** |
| 空转格 `skipped_by_acl` | 未统计 | 9108 |
| 泄露命中 | 0 | 0 |
| 正控引用 | 1008 | 1008 |
| 丢弃片段累计 | 1992 | 1992（与 `checks` 逐格相等） |

旧口径的问题：11100 里有 9108 格是本轮**根本没检索到**的条目，扫它们必然是 0 命中，等于用空转把命中率稀释到好看。新口径下 `checks == dropped_total`，每一格都对应一次真实的「检索到并拦下」。

## 5. 复现

```bash
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m pytest -q tests/test_repair_gaps.py
.venv/Scripts/python.exe scripts/collect_metrics.py
```

实测：`78 passed`，退出码 `0`；`collect_metrics.py` 退出码 `0`。
