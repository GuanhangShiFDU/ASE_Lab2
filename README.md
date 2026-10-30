# Lab 2：网约车平台微服务架构设计

2026 高级软件工程 · 第 22 小组

> 当前阶段：四章设计报告、八服务与数据归属、三条核心流程、28 个客户端操作/16 个内部操作、13 类事件及总体架构图均已整合。57 项人工交叉评审和最终 CodeArts 版本验收仍待执行；本作业没有业务服务实现或性能测试结果。

## 作业范围

为面向乘客、司机和运营人员的网约车平台完成领域分析、微服务与数据归属、服务通信、业务流程与契约设计，并汇总为系统整体架构图。

- [作业要求](https://openmsg.yuque.com/openmsg/gp3cfs/eyuag71f933gx041)
- 截止日期：2026-11-02，以课程后续通知为准。
- 本次无需实现业务代码，无需完整物理表结构或建表 SQL。
- 沿用原课程小组和 CodeArts 项目，使用独立的 Lab 2 仓库。

## 小组成员及分工

沿用 Lab 1 成员及角色。以下区分已合入的材料、当前卡片交付与尚未执行的人工复核；PR 合并不代表全组已确认设计。

| 成员 | 学号 | 实际材料贡献与对应 PR | 后续人工复核 / 交付 |
| --- | --- | --- | --- |
| 史冠航（组长） | 26113050105 | #71199986 框架与同步；#71199988 领域规则 [PR #1](https://github.com/GuanhangShiFDU/ASE_Lab2/pull/1)；本分支 #71199999 总体图、报告整合及交付导航 | 统筹规则讨论、图文一致性、最终课程提交 |
| 刘乐翔 | 26113050085 | #71199991 客户端与叫车流程 [PR #4](https://github.com/GuanhangShiFDU/ASE_Lab2/pull/4)；#71199996 核心接口 [PR #7](https://github.com/GuanhangShiFDU/ASE_Lab2/pull/7) | 核对客户端反馈、取消费同意上限与异常恢复 |
| 刘子扬 | 26113050091 | #71199990 通信与事件 [PR #3](https://github.com/GuanhangShiFDU/ASE_Lab2/pull/3)；#71199994 取消/重叫 [PR #5](https://github.com/GuanhangShiFDU/ASE_Lab2/pull/5) | 核对事件、幂等、状态竞争和数据边界 |
| 李全昊 | 26113050071 | #71199989 服务与数据 [PR #2](https://github.com/GuanhangShiFDU/ASE_Lab2/pull/2)；#71199995 接驾/行程/支付 [PR #6](https://github.com/GuanhangShiFDU/ASE_Lab2/pull/6) | 核对事务、字段、权限及状态权威 |
| 杨润东 | 26213050435 | #71199997 设计评审准备 [PR #8](https://github.com/GuanhangShiFDU/ASE_Lab2/pull/8) | 执行逐项评审；#71200000 最终验收、问题跟踪及复核 |

任务入口：[Lab 2 总 Story #71199981](https://devcloud.cn-north-4.huaweicloud.com/projectman/scrum/c1aa0a224dba4c2591226b87a5af9407/task/detail/71199981)。

## 仓库与交付入口

- GitHub：[ASE_Lab2](https://github.com/GuanhangShiFDU/ASE_Lab2)
- CodeArts 项目：`2026高级软件工程_第22小组`。
- CodeArts 仓库：[lab2](https://devcloud.cn-north-4.huaweicloud.com/codehub/project/c1aa0a224dba4c2591226b87a5af9407/codehub/3104885/home)。
- CodeArts SSH：`git@codehub.devcloud.cn-north-4.huaweicloud.com:c1aa0a224dba4c2591226b87a5af9407/lab2.git`。
- [设计报告](docs/design.md)：第 1 章包含领域分析与规则，第 2 章包含上下文、八个服务、逻辑模型和一致性边界；第 3 章包含通信/事件；第 4.1～4.3 节包含叫车、取消重叫、接驾行程支付及恢复；整体架构图已嵌入报告。
- [绘图约定](docs/diagrams/README.md)：图源、导出文件及报告引用方式。
- [契约入口](contracts/README.md)：核心接口与业务事件。
- [总体架构 PNG](architecture.png) / [可编辑 SVG](docs/diagrams/architecture.svg)：三类客户端、八服务、数据归属、请求/事件及外部依赖。
- [设计评审清单](docs/review-checklist.md) / [逐项结果](docs/review-results.md) / [问题台账](docs/review-issues.md)：人工执行后记录真实结论。
- [#71200000 固定版本验收记录](docs/validation.md)：CodeArts 候选、自动日志、57 项辅助设计核对及真实待确认项。
- [#71199999 整合检查及 QA 交接](docs/checks/architecture-71199999.md)：基线版本、检查结果和后续验收流程。

```text
ASE_Lab2/
├── README.md / LICENSE
├── architecture.png                 # 整体图（已嵌入报告）
├── docs/
│   ├── design.md                    # 四章设计 + 整体图 + 评审记录
│   ├── diagrams/                    # 整体 SVG、3 张数据图、6 张流程图及图源
│   ├── checks/                      # 各卡真实静态检查记录
│   ├── validation.md / evidence/    # 固定版本验收及原始证据
│   └── review-*.md                  # 人工清单、结果、问题
├── contracts/
│   ├── http/                        # 公网/内部 OpenAPI、方法说明、示例与检查器
│   └── events/                      # 13 类事件、JSON Schema、示例与检查器
├── scripts/                        # 交付文件/本地引用检查
└── .github/                         # master → CodeArts 单向同步
```

## 阅读与静态复核

先读报告第 1 章规则和第 2 章边界，再沿第 3 章通信清单阅读第 4 章三条流程，最后用整体图与接口总览核对。查看 PNG/SVG 和 Markdown 不需要启动业务服务。

复跑契约静态检查（需 Python 3 与 pip；Windows 可将 `python3` 换成 `python`）：

```bash
python3 -m venv .venv
# macOS / Linux / Git Bash
source .venv/bin/activate
# Windows 创建的虚拟环境改用：source .venv/Scripts/activate
python -m pip install -r contracts/http/requirements-check.txt
python -m pip install -r contracts/events/requirements-check.txt
python -X utf8 contracts/http/validate.py
python -X utf8 contracts/http/validate_cancellation.py
python -X utf8 contracts/http/validate_trip_payment.py
python -X utf8 contracts/events/validate.py
python -X utf8 contracts/http/validate_contracts.py
```

图的导出工具与命令见 [绘图约定](docs/diagrams/README.md)。上述命令检查契约和材料一致性，不运行乘客/司机/支付业务，不产生性能或全组签字结论。

## GitHub → CodeArts 同步

通过 `.github/workflows/sync-codearts.yml` 将 GitHub 的 `master` 单向同步至 CodeArts 的 `lab2/master`；也可在 GitHub Actions 中手动运行 `Sync master to CodeArts`。

首次启用：

1. 在本 GitHub 仓库的 **Settings → Secrets and variables → Actions** 创建 Repository secret：`CODEARTS_SSH_PRIVATE_KEY`，填入用于 Actions 同步的 SSH 私钥完整内容。
2. 该私钥对应的公钥需已添加到 CodeArts，所属账号对 `lab2` 有推送权限。可以复用 Lab 1 的专用同步密钥；GitHub 仓库级 secret 不会自动继承到新仓库。
3. 将工作流和 `.github/codearts_known_hosts` 提交并合并到 GitHub 的 `master` 后触发同步。私钥仅放在 Actions secret，不放入仓库。
4. 首次运行后检查 Actions 结果与两端 `master` 的 SHA；在此之前，不将同步标记为已完成。

工作流读取最新 `master`、保留完整历史、校验已固定的 SSH 主机公钥，并在推送后比较 SHA。仅同步 `master`，不强制推送；若 CodeArts 出现独立提交导致推送失败，先核对差异再协调处理。

## 协作顺序

1. 确认题目未规定的业务规则，并记录在设计报告中。
2. 完成子领域、限界上下文和术语，再讨论微服务与数据归属。
3. 围绕三条关键流程迭代通信方案、时序图、接口及事件契约。
4. 汇总整体架构图，交叉核对名称、状态、数据所有者和调用关系。
5. 补齐实际分工，评审合并并将最终材料提交到 CodeArts 独立仓库。

每张任务卡写清目标、交付文件、验收条件和负责人。每个 PR 说明修改范围、关联任务和仍未确定的问题。契约变更应同步更新相关图与报告。

当前交接：#71199999 已通过 PR #9 合并；#71200000 已针对 CodeArts 候选 `b941b92a8a9b3be72f3575c0e6cdb877e6ee0b50` 执行自动检查与 Codex 辅助设计核对，见 [验收记录](docs/validation.md)。杨润东正式人工评审、全组规则/接口确认和另一位组员独立复核仍待实际记录；不能把合并或静态校验等同于全组确认。

## 交付状态

以下已勾选项仅表示材料存在且本次完成静态整合检查；人工结论见逐项结果表。

- [x] README 记录成员、实际材料贡献、PR 和后续职责。
- [x] 四章报告包含领域规则、服务边界、逻辑模型、通信、三条流程及异常恢复。
- [x] 核心 HTTP / 事件契约、示例与静态检查器齐备。
- [x] 根目录 `architecture.png` 有图例，已嵌入报告，并保留可编辑图源。
- [x] CodeArts `lab2` 网页与 SSH 入口已补齐；本卡基线两端 master 相同，见检查记录。
- [ ] 全组实际确认规则及接口，填写评审人、版本与结论。
- [ ] 57 项人工评审执行并附证据；DRI-001 修复待复核，其他发现按台账跟踪。
- [x] #71200000 已核对固定设计候选的两端 SHA 并保存自动检查/辅助核对记录。
- [ ] 完成正式人工评审及另一位成员独立复核；验收材料合并后再核对最终两端 SHA。
- [ ] 组长按课程入口提交最终仓库、分支及完整 SHA 等要求材料。

## 仓库组织说明

本次用一个仓库集中保存报告、图源和契约。微服务边界通过职责、数据所有权和通信契约表达，不以 Git 仓库数量判断。若后续课程要求实现服务，再根据独立发布、权限和团队协作需要决定是否拆仓库。
