# 接驾、行程与付款示例

#71199995 的虚构契约示例，不是运行日志，也不是已接入的支付渠道。与 [OpenAPI](../../openapi.yaml)、[流程约定](../../trip-payment.md)、[事件 Schema](../../../events/event.schema.json) 配套。

## 连续主链（同一订单）

| 阶段 | 文件 | 关键事实 |
| --- | --- | --- |
| 到达 | [请求](arrival-request.json) / [响应](arrival-response.json) / [事件](arrival-event.json) | order-trip-01 已分配后到达，stateVersion 2→3 |
| 上车开始 | [请求](start-request.json) / [响应](start-response.json) / [事件](started-event.json) | 唯一 trip-flow-01；上车/开始一起提交，stateVersion 3→4 |
| 结束，计量尚缺 | [请求](complete-request.json) / [响应](complete-response.json) / [事件](completed-event.json) | 4→5、COMPLETED、measurement=null；已结束不等于已出账 |
| 首次计量补齐 | [行程查询](trip-ready-response.json) / [事件](measurement-event.json) | 8000 米/720 秒，measurementVersion=1，订单仍 stateVersion=5 |
| 费用 | [未齐](bill-pending-response.json) / [已出单](bill-ready-response.json) / [事件](bill-event.json) | 同一 BillingJob/Bill；原计价版本、虚构参数计算 2500 分 |
| 未付款查询 | [响应](payment-unpaid-state.json) | 正额、权威确认无 Receipt/未决尝试；提交时还要原子复核 |
| 建立尝试 | [请求](payment-request.json) / [202 响应](payment-created-response.json) / [操作恢复](payment-operation-response.json) | 原键 op-pay-trip-01，attempt-trip-01=CREATED；操作 SUCCEEDED 不表示付款成功 |
| 渠道超时 | [尝试查询](payment-unknown-response.json) / [支付汇总](payment-pending-state.json) / [事件](attempt-event.json) | 原尝试 UNKNOWN、statusVersion=2，不能新扣款 |
| 核验收款 | [尝试查询](payment-succeeded-response.json) / [支付汇总](payment-paid-state.json) / [事件](receipt-event.json) | 同尝试 SUCCEEDED、statusVersion=3，唯一 receipt-trip-01；2500 分一致 |

HTTP 查询字段 source 表示权威服务；事件 aggregateVersion 表示源事件流，不能与 stateVersion/statusVersion 混用。事件沿用既有 7 类 v1 类型，未新增事件格式；示例 eventId 在本目录唯一，跨目录示例是独立样本。渠道请求号/交易号为 S-06 内部字段，不向业务事件广播；实际回调验签细节留给渠道适配实现。

## 独立分支（不要串入主链）

- [确定失败](payment-failed-final-response.json)：attempt-failed-02 为同类账单上的**另一条示意分支**；代表渠道不可逆拒绝，不能当作 attempt-trip-01 先成功再失败。
- [零额](payment-free-state.json)：另一张 bill-free-02 无需支付，无尝试/Receipt。
- [版本冲突](version-conflict-response.json)：履约新请求确定拒绝；需读最新再确认。
- [写结果未知](unknown-operation-response.json)：原写可能已提交，必须原键恢复。

`validate_trip_payment.py` 校验 21 份 HTTP、7 份事件、29 项跨字段关联，并用 28 个错误示例验证检查能拒绝缺确认、伪造金额、成功无收款、计量/费用/收款串错等问题。它不执行网络请求、支付、并发或服务恢复。
