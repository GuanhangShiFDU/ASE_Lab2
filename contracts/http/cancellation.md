# 取消与重新叫车契约

任务：#71199994；基线：`860f5198b1534786fa915464f5f4e39bf3fbf6f6`（已合并 #71199991）。这是设计草案，不是可运行服务或已完成的组内确认。认证、单位、幂等作用域和响应丢失处理沿用 [叫车契约](booking.md)，本卡新增 3 个核心操作并扩展原操作结果查询。

## 核心 HTTP 调用

| operationId / 方法与路径 | 调用方 → 所有者 | 输入 → 输出及权限 |
| --- | --- | --- |
| `cancelRideOrder` / POST `/v1/ride-orders/{rideOrderId}/cancel` | 所属乘客 / 已分配司机 → S-02 | 订单 ID、Idempotency-Key、expectedStateVersion、maxAcceptedFeeMinor、reason → CancellationResult。乘客可取消 MATCHING/ASSIGNED/ARRIVED；司机只可取消自己的 ASSIGNED/ARRIVED；受邀未接受司机使用 rejectInvitation |
| `getCancellation` / GET `/v1/ride-orders/{rideOrderId}/cancellation` | 所属乘客 / 取消前已分配司机 → S-02 | 订单 ID → 不可变 Cancellation；无取消事实或不可见返回 404。不会把尚未确认的取消判定为失败；历史司机不能据此继续读取实时位置 |
| `getCancellationFee` / GET `/v1/ride-orders/{rideOrderId}/cancellation-fee` | 所属乘客 → S-04 | 订单 ID → FEE_PENDING（bill=null）或 BILL_READY（CancellationBill）。先经 S-02 核验归属与取消事实；依赖不可用返回 503，不能捏造免费 |

`expectedStateVersion` 是同一 RideOrder 的业务状态版本，不是派单使用的 aggregateVersion。`maxAcceptedFeeMinor` 为用户本次同意的费用上限，当前规则只允许 0 或 500 分；它不改写服务端规则。`reason` 为 PLANS_CHANGED、UNABLE_TO_PICK_UP、OTHER；reason 不授予权限，不允许客户端传入 actorId/actorRole/金额计算结果。

`CancellationResult={operationId,cancellation,rideOrder}` 仅在 S-02 事务提交后返回 HTTP 200；rideOrder 是第一次成功的 CANCELLED 快照。Cancellation 保存角色、取消前状态、原 driverId/acceptedAt、决定时刻、规则快照和成功后的 stateVersion。费用是否已生成另查 S-04；响应不等待 MQ、通知或 Bill。

`getCancellationFee` 的 BILL_READY 只说明金额确定，不等于已付款或仍欠款。Bill 不可变，含 sourceId=cancellationId、kind=CANCELLATION_FEE、整数分、ruleVersionId 及创建时间。0 分明确无需支付；正金额的实际收款状态与再次支付资格仍由 S-06 决定，接续 #71199995/96，本接口不据金额直接显示“未支付”或自动发起扣款。FEE_PENDING 的 jobStatus 为 NOT_OBSERVED/PENDING/RETRYING/REQUIRES_REVIEW；REQUIRES_REVIEW 应显示“费用待核对”，不能填 0。

## 裁决顺序与收费边界

1. 鉴权并验证操作资源的可见性；按 `(主体,cancelRideOrder,键)` 查原记录，请求指纹包含路径订单 ID 和全部 body。同键异内容为 IDEMPOTENCY_CONFLICT。已有成功优先重放原结果，不因现在版本/费用变化改判；已有确定拒绝重放原拒绝。
2. 新操作在 S-02 的同一本地事务中串行检查订单、乘客活动槽位、司机占用和 PENDING 邀请（固定锁顺序或等价冲突检测）。先核对角色/归属；已 CANCELLED 返回 ORDER_ALREADY_CANCELLED，其他不可取消状态返回 ORDER_STATE_CONFLICT，仍可取消但版本不同返回 ORDER_VERSION_CONFLICT；不能在事务外读取后无条件写回。
3. 在事务裁决点取服务端 UTC 时间 t，按已保存规则检查费用上限：MATCHING 或司机取消为 0；乘客在 ASSIGNED/ARRIVED，t-acceptedAt <120 秒为 0，≥120 秒为 500 分。预计免费但恰好跨过阈值时，即使 stateVersion 不变，若上限为 0 仍拒绝本次新操作；客户端重新确认才可用新键和 500 上限申请。S-02 这里只检查用户同意的上限，S-04 才生成权威 Bill；两处依据同一个不可变事实/规则。
4. 成功时原子写入唯一 Cancellation、RideOrder=CANCELLED/版本加一、撤销 PENDING 邀请、按订单 ID 条件释放乘客槽位和司机占用、OperationRecord 及 Outbox。取消的是本单，不得清掉司机后来接的新单。没有 Trip 被创建，也不调用外部费用或通知接口持锁等待。
5. Outbox 提交后异步产生 `ride.order-cancelled.v1`；仅当确有 PENDING 邀请转 REVOKED 时另发 `ride.invitation-closed.v1`。取消已接受订单时原 ACCEPTED 邀请不可重写为 REVOKED。S-03 对关闭消息先读权威订单，CANCELLED 时停止，不能再邀请。

**同一版本竞争只有一次转换成功；后续合法取消不是推翻历史接单。** 如果取消先提交，原接单失败；如果接单先提交，旧 expectedStateVersion 的取消返回 ORDER_VERSION_CONFLICT。乘客读到已接单状态和规则并再次确认后，可新建取消意图；此时历史上有“先接单、后取消”两件事实，最终只有一个 CANCELLED 状态。不能要求一个可取消的已接单订单永远不出现两条成功历史。取消与上车开始同理，但一旦进入 IN_TRIP，普通取消不再允许。

| 场景 | 明确结果 / 恢复 |
| --- | --- |
| 乘客取消 MATCHING；邀请仍 PENDING | 200；免费；邀请 REVOKED、释放本单乘客槽位；受邀司机不曾占用 |
| 乘客已接单后 119.999 秒 / 恰好 120 秒 | 裁决时间分别对应 0 / 500 分；收费时需上限允许，否则 409 CANCELLATION_FEE_CHANGED |
| 已分配司机取消 ASSIGNED/ARRIVED | 200；费用 0；通知乘客；乘客后续自行确认重新叫车 |
| 未接单的受邀司机 / 非参与者取消 | 403 FORBIDDEN；不改订单；可以拒绝本人邀请不代表可以取消乘客订单 |
| 同状态版本的接单先提交 | 旧版本取消 409 ORDER_VERSION_CONFLICT；读取最新状态后人工确认新意图 |
| 取消先提交，接单 / 上车开始后提交 | 后者 409 ORDER_STATE_CONFLICT；不创建分配/Trip，不恢复订单 |
| 上车开始先提交 | 取消 409 ORDER_STATE_CONFLICT；IN_TRIP 保持，不能收费后强行倒退 |
| 另一个人或另一把键已取消 | 409 ORDER_ALREADY_CANCELLED，读取现有 Cancellation；不能把别人的成功写成自己的新取消 |
| 同键重试 / 同键不同 reason、版本、上限或订单 | 原结果重放 / 409 IDEMPOTENCY_CONFLICT；不新增 Cancellation、Bill 或业务通知 |
| MQ、计价或通知不可用 | 取消仍已成功；各自持久任务恢复，订单终态不回滚，费用不得临时显示为 0 |
| 响应丢失、503 OPERATION_PENDING | 保留原键原内容，getOperationResult(operationType=cancelRideOrder)；UNKNOWN/PENDING/NOT_OBSERVED 均不是失败证明 |

确定拒绝以 `outcome=REJECTED` 记录，不改变业务订单；需要改变输入或接受新版本/费用时，先展示原因，用户确认后使用新键。若只是超时则保持原键，不自动换键“解决冲突”。其他 400/401/404/429/503 错误体沿用公共 Error，且仅对有权主体返回订单 ID/版本。

## 费用与通知的独立恢复

S-04 消费取消事实时将 Inbox 与唯一 `(CANCELLED,cancellationId)` BillingJob 在本地事务持久化后才 ACK。Job 用事件 aggregateVersion 作为 sourceVersion，保留完整的取消事实与规则。计算失败保留 RETRYING；重复事件恢复同一 Job。成功时同事务建立唯一 Bill、将 Job 标为 READY 并写 `pricing.bill-created.v1` 的 Outbox；零费也生成 0 分记录，便于解释“免费”，不调用支付渠道。

原事件缺失可由 S-02 Outbox 重投；S-04 另通过受信内部 `listCancellationFacts` 按提交游标补漏，以 cancellationId 收敛到同一 Job。游标须是提交顺序的稳定游标，不能用客户端时间或可能迟提交的预分配序号；持久 Job 后再推进消费游标，恢复时重叠读取也安全。单项校验失败须持久保存待复核项再推进，不能静默跳过。规则快照冲突/事实关联错误保留 REQUIRES_REVIEW 和追踪 ID，运营人员核查后由原所有者恢复同一来源任务，不修改历史金额或取消状态。

查询 getCancellationFee 只读；若事实已在 S-02 而事件未到 S-04，返回 FEE_PENDING/NOT_OBSERVED，等待上述补漏，不在查询中猜金额或重建订单。新旧事实乱序时，计费任务不能仅凭最大 stateVersion 丢弃尚未处理的旧取消事实。

S-07 按 `(eventId,recipientId,channel)` 保存投递任务后 ACK。取消通知给乘客及取消前已分配司机；MATCHING 没有已分配司机，受邀司机通过 invitation-closed 撤回提示。外部通知通道失败仅重试同一 deliveryId；提示中携带订单和事实标识，客户端读当前订单，不让迟到的“已接单”提示覆盖已取消。费用通知仅给付款乘客。各服务有独立订阅队列，通知故障不会阻止计价；S-08 按原订阅更新只读投影，图中为清晰省略该支线。

## 重新叫车与未知结果

只有乘客本人从 S-02 确认旧单为 CANCELLED 或 MATCH_FAILED 后才展示重新叫车确认。旧取消响应不明时，先 `getOperationResult`、`getRideOrder`、必要时 `getCancellation`；不能以活动单查询 null、无通知或等待超时推断旧单已取消。如果权威查询已证明旧单终态，原取消“是谁成功”的审计结果仍可继续核对，但不阻塞合法新意图。

重新叫车复用 `createQuote` 和 `createRideOrder`，不是把旧单改回 MATCHING，也不新增一个模糊的 rebook endpoint。新报价、新 operationId、新 rideOrderId；`sourceOrderId=旧单 ID`。S-02 查来源属于本人且为允许终态、报价未过期且未绑定、全局活动槽位空闲；用 sourceOrderId 形成可追踪链，不修改旧 Cancellation/Bill/Receipt 或转嫁旧债。sourceOrderId 本身不是幂等键：每个新意图有自己的键，未知建单只能沿用原键，不能以“重叫”名义再次提交。

多标签页同一原键只生成一个新单；不同键同时提交受全局活动槽位及 quoteId 唯一性约束，仅一个新活动单成功。新单随后也终结后，新的用户意图可再次叫车，仍保留各自来源；本卡不新增“一个旧单永久只能重叫一次”的规则。QUOTE_EXPIRED 要重新报价并明确确认；ACTIVE_RIDE_EXISTS 读取本人现有活动单；INVALID_SOURCE_ORDER 拒绝改写来源身份或状态。旧取消费用未生成/未付不阻止新单，后续旧消息只更新旧单的费用/通知，不释放新单占用。

## 图中内部方法及既有事件

内部调用仍为有服务身份的 HTTPS/JSON，具体 HTTP 绑定现见 #71199996 的 internal.yaml；它们不是外部可调用接口。

| 方法 | 调用方 → 提供方 | 输入 → 输出及失败语义 |
| --- | --- | --- |
| `getCancellationFact` | S-04 → S-02 | 订单 ID、受信查询主体 → E-07 data 全部不可变字段、cityId、sourceVersion（原事件 aggregateVersion）；核验乘客归属；无事实 404，授权失败 403，依赖失败 503 |
| `listCancellationFacts` | S-04 补漏任务 → S-02 | 专用服务身份、授权城市、afterCursor、limit（1～100）→ 上述事实数组、nextCursor；稳定提交游标，读取失败不推进，公众不能调用 |
| `confirmBoardingAndStartTrip` | 已分配司机 → S-02 | rideOrderId、operationId、expectedStateVersion、boardingConfirmed=true → Trip/IN_TRIP 快照；原键幂等、ARRIVED 和司机归属检查，建 Trip 与状态/Outbox 同事务。这里只定义与取消竞争的边界，完整路径/字段由 #71199995/96 补齐 |
| `deliverHint` | S-07 → 外部通知适配器 | 沿用 booking.md：稳定 deliveryId、接收者、事实标识 → 投递回执或待重试；不改业务 |
| `getMatchingOrder` / `getQuoteSnapshot` / `estimateRoute` | 既有调用方 → 对应服务 | 沿用 booking.md；取消后匹配停止，重新叫车重新询价，不复活原订单 |

| 事实事件 | 发布 → 订阅；本流程作用 |
| --- | --- |
| `ride.order-cancelled.v1` | S-02 → S-04 / S-07 / S-08；取消事实、费用来源与通知 |
| `ride.invitation-closed.v1` | S-02 → S-03 / S-07 / S-08；仅实际关闭时发送；S-03 回源终态后停止 |
| `pricing.bill-created.v1` | S-04 → S-07 / S-08；金额确定，费用通知不等于收款 |
| `ride.order-created.v1` | S-02 → S-03 / S-08；全新单开始匹配，保留 sourceOrderId |

事件名、载荷及订阅边界沿用 [事件目录](../events/README.md)，没有新造取消命令消息。扩展示例放在 [examples/cancellation/](examples/cancellation/)，由 `validate_cancellation.py` 校验；公共事件目录的原 13 类示例保持不变。

## 复核命令与限制

使用 [booking.md](booking.md) 末节的隔离 Python 环境与相同依赖，在仓库根目录运行：

```bash
.venv/bin/python contracts/http/validate.py
.venv/bin/python contracts/http/validate_cancellation.py
.venv/bin/python contracts/events/validate.py
```

Windows 路径为 `.venv/Scripts/python.exe`。检查覆盖字段结构、示例关联及本卡明确写出的设计不变量；不是运行了数据库事务、消息故障或真实并发测试。设计场景和待确认项见 [本卡检查记录](../../docs/checks/cancellation-71199994.md)。

内部 HTTP 路径和 query cursor 的统一绑定现见 [#71199996 接口总览](core-api.md) 与 [internal.yaml](internal.yaml)；confirmBoardingAndStartTrip 已由 #71199995 补齐，不再是待实现的契约占位。
