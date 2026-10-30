# Lab 2 固定版本验收记录

任务：[#71200000 Integration & Acceptance](https://devcloud.cn-north-4.huaweicloud.com/projectman/scrum/c1aa0a224dba4c2591226b87a5af9407/task/detail/71200000)。

**当前结论：固定候选的自动检查通过，辅助设计核对已记录；正式人工评审、全组规则确认和另一位成员的独立复核待完成，尚不能宣布最终验收通过或关闭卡片。** 这是纯设计作业的验收，不是 Lab 1 的容器/计数器测试，也没有运行网约车业务、真实支付或压测。

## 候选来源与执行身份

| 项目 | 实际记录 |
| --- | --- |
| 课程依据 | [Lab 2 原题](https://openmsg.yuque.com/openmsg/gp3cfs/eyuag71f933gx041)，2026-10-30 重新阅读；设计交付，无须业务代码/SQL |
| CodeArts 项目 / 仓库 | `2026高级软件工程_第22小组` / `lab2`；项目 ID `c1aa0a224dba4c2591226b87a5af9407` |
| 克隆源 | `git@codehub.devcloud.cn-north-4.huaweicloud.com:c1aa0a224dba4c2591226b87a5af9407/lab2.git` |
| 被测分支 / 完整 SHA | `master` / `b941b92a8a9b3be72f3575c0e6cdb877e6ee0b50` |
| 源工作区 | 重新从 CodeArts 克隆；`git status --porcelain` 为空；检查期间未改源材料 |
| 同步 | 本轮 GitHub / CodeArts `master` 均为上述 SHA，见 [两端原始查询](evidence/acceptance-71200000/remotes.json) |
| 实际执行者 | Codex：自动命令执行、文档/图源阅读、图像检查与桌面推演；**不是杨润东或其他组员的签字** |
| 日期 / 环境 | 2026-10-30 Asia/Shanghai；macOS 26.6.2 arm64，Git 2.50.1，Python 3.9.6；完整依赖与 UTC 执行时间见 [run.json](evidence/acceptance-71200000/run.json) |
| 校验依赖 | 仓库外隔离 Python 环境；PyYAML 6.0.3、jsonschema 4.25.1、openapi-spec-validator 0.7.2；设计材料仅取提交文件 |
| 源材料指纹 | [逐文件 SHA-256 / 大小清单](evidence/acceptance-71200000/source-manifest.json)；针对被测源版本，不包含本次新增报告 |

被测 SHA 是报告产生前已合入的设计候选。提交本报告会产生新的证据提交 SHA，不能把二者混写。若只是加入这些验收材料，旧候选仍是本轮被审对象；如果规则/图/接口发生变化，应记录新候选并重做受影响核对。最终提交仓库 SHA 另在真实合并及同步后记录，不在此预填。

## 已执行的自动检查

以下命令均在干净的 CodeArts 候选根目录执行，每条退出码单独记录为 0。日志中的 LibreSSL/urllib3 警告保留；未使校验失败，不将其当作业务或渠道网络连通测试。

| 命令（Python 使用 `-X utf8`） | 实际结果 | 原始日志 |
| --- | --- | --- |
| `contracts/http/validate.py` | OpenAPI 3.1；28 operationId；274 示例；9 非法案例被拒 | [日志](evidence/acceptance-71200000/contracts__http__validate.py.log) |
| `contracts/http/validate_cancellation.py` | 9 HTTP 示例、2 事件、17 链检查；22 非法案例被拒 | [日志](evidence/acceptance-71200000/contracts__http__validate_cancellation.py.log) |
| `contracts/http/validate_trip_payment.py` | 21 HTTP + 7 事件、29 链检查；28 非法案例被拒 | [日志](evidence/acceptance-71200000/contracts__http__validate_trip_payment.py.log) |
| `contracts/events/validate.py` | 13 类事件、Schema、覆盖与局部字段关系 | [日志](evidence/acceptance-71200000/contracts__events__validate.py.log) |
| `contracts/http/validate_contracts.py` | 28 公网 + 16 内部操作、706 内联示例、42 错误映射；6 图的 42 方法/13 事件引用、11 恢复操作类型、11 负例 | [日志](evidence/acceptance-71200000/contracts__http__validate_contracts.py.log) |
| 本卡 `scripts/check-deliverables.py --root <候选目录>` | 21 Markdown、279 本地引用、6 锚点、10 PNG 头/尺寸、8 服务、18 交互、57 清单/结果 ID 对应 | [日志](evidence/acceptance-71200000/source-check.log) |

各检查有交叉覆盖，示例/负例数量不能相加当成独立业务测试数。图片头检查不证明可读性，格式正确也不证明业务实现正确。

## 设计内容与课程交付核对

[57 项逐项辅助记录](evidence/acceptance-71200000/desk-review.md)按 DR ID 保存实际观察、交换提交顺序等推演和固定 SHA 文件/行链接：55 项在设计核对范围内符合预期，DR-D03 / DR-P02 需要真实团队确认。

| 课程部分 | 本轮检查内容与结果 |
| --- | --- |
| 领域分析（20） | 三端、七类能力和 R-01～R-08 到九子域；核心/支撑/通用分类有理由；题目条件与 BR 提案分开 |
| 服务与数据（30） | 九上下文、八服务职责/取舍、三组逻辑模型、权威写入与引用；全局乘客/司机独占不被城市队列隔离破坏 |
| 服务通信（15） | C-01～18、HTTPS/JSON、RabbitMQ、短轮询、同步/异步和外部适配器；Outbox/Inbox、去重与恢复责任 |
| 流程与契约（30） | 三流程六时序图；正常/失败/超时/重复/并发/恢复；28+16 HTTP 和 13 事件；取消竞争、费用与支付未知边界 |
| 整体图（5） | 根目录 PNG 已嵌入报告，有 SVG 源；三客户端/网关/服务/存储/消息/外部依赖分组和图例；与四章名称、方向及事件订阅相符 |
| 提交材料 | README 成员与 PR 入口、设计报告、根图、契约均在提交文件内；同一课程项目的独立 CodeArts lab2 仓库 |

分值为题目映射，不是自评得分。十张图片均能读取；总体图已直接查看，三张 ER 与六张时序导出图做布局缩览并与图源对照。长时序图在 README 缩略显示时文字较小，应打开原尺寸 PNG 或 SVG 放大；不把缩略图当作完整阅读。

## 问题及尚未完成事项

- **DRI-001**：报告顶部过时 API 状态已在 `f780600e3a42465b3d3f62d965d36e394b0f8e08` 修正，由 [PR #9](https://github.com/GuanhangShiFDU/ASE_Lab2/pull/9) 合并。本轮 Codex 对候选版静态复核通过；成员实际复核仍未执行，台账保持待复核。
- 本轮没有新发现可明确复现的设计矛盾，不据此保证没有遗漏。新发现按 [问题台账](review-issues.md) 记录并重查，不能覆盖原失败证据。
- [正式人工结果](review-results.md)仍为 **57 项未执行**。可以引用本轮辅助记录帮助复核，但只能由实际阅读/推演者填写真实姓名、日期、SHA、结论及证据；已有 PR 合并不能代替此记录。
- BR-01～BR-09 以及角色分工的实际全组确认未提供，沿用 [确认表](review-checklist.md) 的待确认状态。
- 另一位成员独立核对阅读入口与交付清单：**未执行**。不是由 Codex 重新克隆就能代替第二个人。
- 最终人工验收结论、最终合并后两端 SHA、组长课程提交：**待完成**。

## 人工复核的最短记录方式

杨同学阅读清单和本轮证据后，在 `review-results.md` 的对应 DR 行记录自己的实际结果；同一批次可共享一个详细证据文件，但每项仍应能定位。不要只把 57 行批量改为“通过”而不检查。

全组可在一次讨论中确认九条 BR，再由真实参与者把确认意见/日期/被审 SHA 或实际评论链接补入清单确认表。若规则改变，先改模型/流程/契约并重验，再下结论。

另一位成员（不是本轮主验收人）从 CodeArts 干净克隆候选，按 README 独立打开报告四章、总体图及契约，记录：

```text
独立复核人：
日期 / 时区：
CodeArts 仓库 / 分支 / 完整 SHA：
工作区状态：
按 README 实际打开的材料：
发现的问题及复核情况：
结论及证据位置/评论链接：
```

上述信息尚未填写，不能把模板当作完成证据。待实际完成后更新本页结论、统计和问题状态。

## 复跑方式

从 CodeArts 克隆并 checkout 上方完整 SHA，先确认工作区干净。依照 README 创建独立 Python 环境并安装两份 `requirements-check.txt`，逐条执行本页列出的五个契约检查命令。本卡交接包另外提供 `verify-candidate.sh`：在新建的独立 CodeArts 克隆中检查固定 SHA、全部源文件哈希，再执行这些命令，保留接收方本机日志；不会替接收方填写人工通过。

交付引用检查可从包含本卡脚本的目录执行：

```bash
python3 -X utf8 scripts/check-deliverables.py --root /path/to/clean-codearts-candidate
```

`--root` 是实际固定候选目录；脚本默认检查自己所在仓库，检查新报告时引用数量增加是正常的。脚本只用 Python 标准库，检查本地链接，不把外站 HTTP 可用性或成员访问权限标记为已验证。
