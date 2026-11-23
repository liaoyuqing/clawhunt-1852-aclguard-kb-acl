# 返修自证（FIX_REVIEW）

本文件对应一次**独立只读审计**提出的 9 处缺口。审计方不是本文作者，结论是「按现状交付很可能过不了买方验收」。

处理原则：**不删任何既有用例、不削弱任何既有断言**；9 处缺口全部补上可证伪的回归断言，并对 5 处关键实现做了**变异自证** —— 把实现改坏，对应用例必须变红；恢复后必须全绿。

环境：Python 3.11.9 / pytest 9.2.0，解释器 `.venv/Scripts/python.exe`。

## 1. 九处缺口与修复

| # | 审计指出的问题 | 现状 | 修复后位置 | 钉住它的用例 |
| --- | --- | --- | --- | --- |
| 1 | AC3 根本没接线：`render_history` / `visible_citations_only` 全仓零调用，角色被收回后历史不会折叠 | 已接线：`ask()` 每次构造模型请求前调用 `render_history`，结果进 `ModelRequest.history` | `aclguard/assistant.py:191`–`aclguard/assistant.py:198` | `tests/test_repair_gaps.py:66`–`tests/test_repair_gaps.py:95` |
| 2 | 缓存命中直接返回旧答案，绕过二次校验 | 命中后按**知识库现行条目**重判；不通过则作废该键并重新作答 | `aclguard/assistant.py:104`–`aclguard/assistant.py:132`（`recheck_cached`）、`aclguard/assistant.py:160`–`aclguard/assistant.py:184`（命中分支） | `tests/test_repair_gaps.py:124`–`tests/test_repair_gaps.py:161`（重判杀掉）、`tests/test_repair_gaps.py:182`–`tests/test_repair_gaps.py:196`（反向：仍可见时正常走缓存） |
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
| M6 | `cache_key.py` 的 `cache_key()` 去掉 `subject_fingerprint(principal)`（键退回「同角色同馆即同键」） | `4 failed, 78 passed`，退出码 1；红：`test_rework_cache_key_covers_subject_so_confidential_does_not_leak_between_principals`、`test_repair_cache_key_covers_subject_and_scope`、`test_repair_cache_does_not_leak_across_subject_or_scope`、`test_ac4_cache_key.py::test_acl4_cache_key_contains_role_and_site_fingerprint` |
| M7 | `assistant.py` 里把可复用引用的循环改成 `for prior in ():`（接线取空） | `1 failed, 81 passed`，退出码 1；红：`test_rework_visible_citations_only_wired_through_ask_main_chain` |
| M8 | `leak.py` 把空转格也算进分母（`if entry.doc_id not in retrieved:` 处改成 `if False:`） | `3 failed, 79 passed`，退出码 1；红：`test_acl2_leak_suite_100_questions_zero_unauthorized_hits`、`test_repair_leak_suite_excludes_idle_cells_from_denominator`、`test_rework_ac2_checks_equal_exact_sum_of_denied_entries_per_role` |

8 次变异全部「改坏即红」，每次变异后都立刻还原源文件并复查 `git diff` 为空。

- M1–M5 是第 1 轮审计返修时的实测，当时全量是 78 条用例（返修 2 轮的用例尚未加入），所以分母是 77/75。
- M6–M8 是第 2 轮（买家 3 条）返修时的实测，全量已是 82 条用例，所以分母是 78/79/81。
- 两轮恢复后都回到全绿：第 1 轮 `78 passed, exit 0`，第 2 轮 `82 passed, exit 0`。

## 3. 既有断言变更申报（两处）

原则不变：只允许**因为语义变化而必须改**的断言，改完必须更强，且逐条申报。

`tests/test_ac4_cache_key.py:17`：`assert key.count(":") == 3` → `assert key.count(":") == 5`。

- **原因**：旧断言把「4 段键」写成了契约，而 4 段键正是审计指出的越权隐患（同角色换人或 scope 收缩会误命中）。若保留旧断言，第 3 项修复根本无法落地。
- **替代断言更强**：改成 5 个冒号后，又新增 `key.count(":") == 5`、`len(key.split(":")) == 6`、四个指纹各自 `in key`（`tests/test_repair_gaps.py:201`–`tests/test_repair_gaps.py:232`），并新增同角色他人 / scope 收缩两种功能级 miss 断言（`tests/test_repair_gaps.py:235`–`tests/test_repair_gaps.py:259`）。旧断言只是「段数对」，新断言覆盖了「换人换 scope 必须换键」。
### 3.1 `tests/test_ac4_cache_key.py:17`（第 1 轮审计返修）

理由与替代断言见上。

### 3.2 `tests/test_ac2_leak_100.py:22`–`tests/test_ac2_leak_100.py:24`（第 2 轮买方返修第 3 条）

- **旧断言**：`assert run.checks == 100 * 5 * 40 - 0 or run.checks > 0`。右侧 `or run.checks > 0` 让整条恒真：只要跑出任何非零次数就通过，等于没有约束力。
- **新断言**：`assert run.checks == 1992`、`assert run.skipped_by_acl == 9108`、`assert run.checks + run.skipped_by_acl == 11100`（逐角色精确断言见 6.3）。
- **为什么必须改**：买方点名这条为「几乎恒真」。新断言把三条独立数量关系钉死：分母 1992、空转 9108、候选格 11100，任一实现漂移（例如把空转格重新计入分母，或某个角色的可见集变化）都会立刻变红。
- **强度对比**：旧断言对 `checks` 的任何正值都不敏感；新断言要求五个角色逐格合计精确到个位，并与 `dropped_total`、`cells_total` 自洽（`test_rework_ac2_checks_equal_exact_sum_of_denied_entries_per_role`）。

除以上两处外，其余既有用例**一条未删、一条未改**。

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
.venv/Scripts/python.exe -m pytest -q tests/test_rework_1852.py
.venv/Scripts/python.exe scripts/collect_metrics.py
```

实测：全量 `82 passed`，退出码 `0`；`tests/test_repair_gaps.py` `17 passed`；`tests/test_rework_1852.py` `4 passed`；`collect_metrics.py` 退出码 `0`、`test_cases` 记 82。

## 6. 第 2 轮返修（买方 3 条）

平台 `latest_delivery_status=rework_requested`、`rework_count=1/3`。买方确认了二次校验的强制执行位置（`ask()` → `second_check.filter_chunks`）、判定默认拒绝、审计只记 `doc_id`、泄露测试用不做 ACL 的知识库桩、四条验收各有测试，只提出 1 blocker + 2 minor。逐条对比如下。

| # | 买方原话要点 | 修复前 | 修复后 | 钉住它的用例 |
| --- | --- | --- | --- | --- |
| 1 (blocker) | `cache_key` 只含 role/site/问题，而 `visibility.decide` 还依赖 `subject_id` 与 `data_scope`；`ask()` 命中缓存即返回不再二次校验，同角色同馆但 confidential 白名单不同的人会拿到对方回答 | 第 1 轮已把键扩到 6 段并加 `recheck_cached`，但**没有**按买方描述的「同角色同馆只差 subject_id」构造用例，这条越权路径无测试钉住 | 按买方描述精确构造：两人同 `roles`、同 `site_id`、同 `data_scope`，只差 `subject_id`（`doc-034` 的 `allowed_subject_ids=("u-fin-05",)`），共用一个 `TTLCache` 实例 | `tests/test_rework_1852.py:43`–`tests/test_rework_1852.py:90`、`tests/test_rework_1852.py:93`–`tests/test_rework_1852.py:115` |
| 2 (minor) | `visible_citations_only` 已实现有测试，但 `ask()` 不调用它，主链路也不向模型传历史 | 函数零调用方，只被单测直接调用 | `ask()` 在写本轮消息**之前**用当前 principal 过一遍历史引用，结果作为 `ModelRequest.reusable_citations` 送进模型，并在返回 dict 里以 `reusable_citation_doc_ids` 暴露 | `aclguard/assistant.py:149`–`aclguard/assistant.py:154`、`aclguard/assistant.py:191`–`aclguard/assistant.py:198`；用例 `tests/test_rework_1852.py:118`–`tests/test_rework_1852.py:160` |
| 3 (minor) | AC2 的 `assert ... or run.checks > 0` 几乎恒真 | 见 3.2 | 精确断言 1992 / 9108 / 11100，并在 `AC2_LEAK_TEST_REPORT.md` 写明 1992 的推导 | `tests/test_ac2_leak_100.py:20`–`tests/test_ac2_leak_100.py:24`、`tests/test_rework_1852.py:163`–`tests/test_rework_1852.py:180` |

### 6.1 第 1 条：缓存键与跨主体隔离

判定链是 `ask()` 取键 → `cache.get(key)` → `recheck_cached()` 按知识库**现行**条目重判 → 不通过则 `cache.invalidate(key)` 并重新作答。键为 6 段 `kind:role_fp:site_fp:subject_fp:scope_fp:query_fp`（`aclguard/cache_key.py:28`–`aclguard/cache_key.py:50`），把 `subject_id` 与 `data_scope` 都纳入指纹，所以「同角色同馆、不同主体」在取键这一步就分叉，不会命中对方的条目；`recheck_cached` 是第二道保险，覆盖「写入后条目被重新密级化」这类键分不开的情形。

用例断言的可观察事实（全部来自真实运行）：

- 白名单内的人（`u-fin-05`）拿到 `doc-034`，`warm["cached"] is False`，`len(cache) == 1`；
- 两把键必须不同：`cache_key("qa", allowed, question) != cache_key("qa", denied, question)`；
- 白名单外的人（`u-fin-06`）：标题与 `body[:40]` 都不在 `answer` 里，`doc_id` 不在 `citations` 里、在 `dropped` 里，`cache["served"] is False`、`served_from_cache_despite_now_denied is False`；
- 把 `answer + citations + context + history` 序列化成一个面再搜一遍，标题与原文仍然 0 次出现；
- 第二条用例让两人在同一个缓存实例上轮流两轮，每一轮无权一方拿到的都仍是自己的结果。

### 6.2 第 2 条：`visible_citations_only` 接进主链路

接线点在 `aclguard/assistant.py:149`–`aclguard/assistant.py:154`：算完后放进 `ModelRequest.reusable_citations`（`aclguard/assistant.py:191`–`aclguard/assistant.py:198`），返回 dict 增 `reusable_citation_doc_ids`（缓存命中路径同样带上）。**必须在并入本轮消息之前算**，否则本轮引用会污染「上一轮可复用」集合 —— 用例首轮断言 `reusable_citation_doc_ids == []` 正是钉这一点。

用例走的是 `ask()` 主链路（不是直接调 `visible_citations_only`），三轮：

1. 首轮：`reusable_citation_doc_ids == []`；
2. 次轮：集合等于首轮 `citations` 的集合，且与 `last_request.reusable_citations`、`last_request.as_dict()["reusable_citations"]` 三者一致；
3. 收回 `sales_rep` 后：`doc-013` 从集合中消失，集合等于次轮集合减去 `{doc-013}`，`doc-013` 进 `dropped`；模型请求体里的历史仍保留折叠形态（`folded is True`）供审计，但助手侧消息里既有 `FOLD_MARKER` 又没有该条目的标题与 `body[:40]`。

第 3 步刻意只检查**助手侧**消息：用户自己的提问里本来就写着该标题，那不是泄露面，与 `aclguard/leak.py` 的 `scan_surface` 口径一致。

### 6.3 第 3 条：AC2 精确分母

1992 = 五个角色各自无权条目数之和：front 445 + community 429 + sales 415 + sales_lead 331 + finance 372。推导与逐角色统计写在根目录 `AC2_LEAK_TEST_REPORT.md`，并由两条用例双向钉住：`tests/test_ac2_leak_100.py:22`–`tests/test_ac2_leak_100.py:24` 断言总量，`tests/test_rework_1852.py:163`–`tests/test_rework_1852.py:180` 断言逐角色字典 + 合计 + 与 `cells_total` / `dropped_total` 的自洽。

### 6.4 本轮变异自证

见第 2 节 M6–M8：去掉 `subject_fingerprint`、把可复用引用的循环取空、把空转格重新计入分母，三种改坏方式各自让对应用例变红；连同第 1 轮的 5 次，共 8 次变异全部「改坏即红」，恢复后 `82 passed, exit 0`。

### 6.5 本轮既有断言变更

仅 `tests/test_ac2_leak_100.py:22`–`tests/test_ac2_leak_100.py:24` 一处，申报见 3.2。第 1 轮的 78 条用例一条未删；本轮新增 4 条，全量 82 条。
