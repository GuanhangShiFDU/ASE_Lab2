# 业务事件契约 v1

本文件是 #71199990 的设计草案，基于已交接的 #71199989 服务边界。事件是已提交事实，不是指令、候选建议或客户端点击。运行系统尚未实现；字段示例均为虚构数据。

协议、事务投递、消费重试、城市队列和降级见 [设计报告第 3 章](../../docs/design.md#三服务通信设计15-分)。[JSON Schema](event.schema.json) 使用 Draft 2020-12；全部示例在 [examples](examples/ride.order-created.v1.json) 中逐个提供。

## 事件目录

| 事件名（含主版本） | 业务含义 | 发布服务 | 订阅服务及用途 | 示例 |
| --- | --- | --- | --- | --- |
| `ride.order-created.v1` | 订单已建立，允许开始候选计算 | `ride-service` | dispatch-service：开始匹配；operations-service：建立查询投影 | [JSON](examples/ride.order-created.v1.json) |
| `ride.invitation-issued.v1` | 一个有效接单邀请已创建 | `ride-service` | notification-service：给受邀司机提示；operations-service：邀请记录 | [JSON](examples/ride.invitation-issued.v1.json) |
| `ride.invitation-closed.v1` | 邀请已不可继续接受 | `ride-service` | dispatch-service：重读订单，仍 MATCHING 且未到期才换候选；notification-service：撤销提示；operations-service：记录 | [JSON](examples/ride.invitation-closed.v1.json) |
| `ride.order-assigned.v1` | 司机分配已由权威确认 | `ride-service` | notification-service：向乘客/司机提示；operations-service：更新履约投影 | [JSON](examples/ride.order-assigned.v1.json) |
| `ride.order-arrived.v1` | 已分配司机到达上车点 | `ride-service` | notification-service：到达提示；operations-service：更新履约投影 | [JSON](examples/ride.order-arrived.v1.json) |
| `ride.trip-started.v1` | 已确认上车并开始行程 | `ride-service` | notification-service：行程开始提示；operations-service：更新行程投影 | [JSON](examples/ride.trip-started.v1.json) |
| `ride.order-cancelled.v1` | 订单已取消并保存费用判断依据 | `ride-service` | pricing-service：按 cancellationId 唯一建立 BillingJob；notification-service：取消提示；operations-service：更新投影 | [JSON](examples/ride.order-cancelled.v1.json) |
| `ride.match-failed.v1` | 匹配已失败，旧单不再允许接单 | `ride-service` | notification-service：失败及重新叫车提示；operations-service：终态投影 | [JSON](examples/ride.match-failed.v1.json) |
| `ride.trip-completed.v1` | 行程与履约已结束，费用可随后生成 | `ride-service` | pricing-service：按 tripId 唯一建立 BillingJob；notification-service：完成提示；operations-service：终态投影 | [JSON](examples/ride.trip-completed.v1.json) |
| `ride.trip-measurement-ready.v1` | 已结束行程的缺失计费依据已核验补齐 | `ride-service` | pricing-service：恢复同一 tripId 任务；operations-service：补齐查询依据 | [JSON](examples/ride.trip-measurement-ready.v1.json) |
| `pricing.bill-created.v1` | 应付费用已确定且不可变 | `pricing-service` | notification-service：费用可查询提示；operations-service：费用投影 | [JSON](examples/pricing.bill-created.v1.json) |
| `payment.attempt-updated.v1` | 一次支付尝试的权威状态已持久化 | `payment-service` | pricing-service：只读支付摘要；notification-service：状态提示；operations-service：支付过程投影 | [JSON](examples/payment.attempt-updated.v1.json) |
| `payment.receipt-confirmed.v1` | 唯一收款已确认 | `payment-service` | pricing-service：费用支付摘要；notification-service：付款成功提示；operations-service：收款投影 | [JSON](examples/payment.receipt-confirmed.v1.json) |

## 公共 envelope

所有下列字段均必需。ID 为 1～128 位不透明字符串（字母、数字、下划线、短横线，首位字母或数字）；业务版本为正整数。eventId 对每个已提交事实固定，broker 重投、relay 重发和隔离重放不得换 ID 或改内容。

| 字段 | 类型/约束 | 含义 |
| --- | --- | --- |
| `eventId` | string / ID | 所有者生成的稳定事实消息 ID，重投不改变 |
| `eventType` | string | 包含主版本的事件名 |
| `schemaVersion` | "1.0.0" | 本次字段契约版本 |
| `source` | string | 发布服务；需同时通过 MQ 发布身份验证 |
| `occurredAt` | string / RFC 3339 UTC | 本业务事实的提交/裁决时刻，不是重投时刻 |
| `cityId` | string：shanghai, hangzhou, nanjing | 业务归属城市 |
| `aggregateType` | string | 本服务内的聚合类型 |
| `aggregateId` | string / ID | 聚合 ID |
| `aggregateVersion` | integer ≥ 1 | 本聚合 Outbox 事件流序号；不等于跨实体全局版本 |
| `correlationId` | string / ID | 贯穿业务请求的关联 ID |
| `causationId` | string / ID | 导致此事实的操作 ID 或上游 eventId |
| `data` | object | 具体业务载荷 |

aggregateVersion 是发布方为 `(source, aggregateType, aggregateId)` 分配的持久事件序号，可与业务写入/Outbox 一起递增；同一事务多个事件也各有稳定序号。它不同于 data.stateVersion、statusVersion、measurementVersion：邀请变化或计费依据补齐可能没有推进订单状态版本。订阅者可能只看到部分事件，所以序号间有空档并不自动表示丢消息。

schemaVersion=1.0.0 对应本文件与示例。主版本变化更换 eventType 的 `.vN` 并独立迁移绑定；同一主版本只能增加可选字段、不能删/改旧字段语义。消费者忽略未知可选字段，但拒绝不支持的主版本，不能用默认值猜必需字段。本次 Schema 固定 1.0.0；新增小版本时发布配套 Schema 并更新兼容测试。

MQ 使用 AMQP 0-9-1/TLS、JSON content-type，exchange `ridehailing.events`，routing key 为 `cityId.eventType`。服务和城市各有自己的持久订阅队列；对某事件订阅多个服务要有多个队列，同服务实例才竞争消费。高频位置点、HTTP 命令/响应、身份凭据和原始渠道回调不进入本目录的可靠事实流。

## 数据字段与业务约束

每个事件载荷中列出的字段都必需；标为“或 null”的字段也须显式给出 null，避免把“缺失”误读为零或空成功。每个示例可单独阅读，不能把不同订单的示例串成一条执行记录。主示例链的 order-demo-01 展示完成→依据补齐→费用→付款未知→确认收款；取消/失败使用其他订单 ID。

`measurement` 对象必含 actualDistanceMeters（非负整数米）、durationSeconds（非负整数秒）、measurementVersion（正整数）和 meteringSource（非空来源标识）。数值上界采用 JavaScript 安全整数 9007199254740991；服务还需执行合理范围与实体关联校验。

### E-01 `ride.order-created.v1`

**含义/触发**：订单已建立，允许开始候选计算。RideOrder=MATCHING、乘客活动槽位、操作记录与 Outbox 同事务提交。

**发布/订阅**：ride-service → dispatch-service：开始匹配；operations-service：建立查询投影。

| data 字段 | 类型/约束 | 含义 |
| --- | --- | --- |
| `rideOrderId` | string / ID | 权威订单 ID；必须等于 envelope.aggregateId |
| `passengerId` | string / ID | 订单所属乘客 ID |
| `stateVersion` | integer ≥ 1 | 该订单的业务状态版本 |
| `quoteId` | string / ID | 已绑定报价 ID |
| `sourceOrderId` | string / ID 或 null | 重新叫车关联的旧订单；无此事实时为 null |
| `state` | "MATCHING" | 当前权威状态 |
| `createdAt` | string / RFC 3339 UTC | 订单建立时刻 |
| `matchDeadline` | string / RFC 3339 UTC | 建立后 60 秒截止 |
| `fareRuleVersionId` | string / ID | 锁定的计价规则版本 |
| `cancellationRuleVersionId` | string / ID | 锁定的取消规则版本 |

**处理约束**：只表示建单成功；起终点等匹配输入按订单 ID 查询 S-02，不让消息副本确认接单。

**完整消息**：[示例 JSON](examples/ride.order-created.v1.json)。字段校验定义为 `event.schema.json#/$defs/ride.order-created.v1`。

### E-02 `ride.invitation-issued.v1`

**含义/触发**：一个有效接单邀请已创建。S-02 重验订单/资格后创建唯一 PENDING Invitation，与 Outbox 同事务。

**发布/订阅**：ride-service → notification-service：给受邀司机提示；operations-service：邀请记录。

| data 字段 | 类型/约束 | 含义 |
| --- | --- | --- |
| `rideOrderId` | string / ID | 权威订单 ID；必须等于 envelope.aggregateId |
| `passengerId` | string / ID | 订单所属乘客 ID |
| `stateVersion` | integer ≥ 1 | 该订单的业务状态版本 |
| `invitationId` | string / ID | 邀请 ID |
| `driverId` | string / ID | 唯一被邀请司机 |
| `matchPlanId` | string / ID 或 null | 候选方案 ID；无此事实时为 null |
| `createdAt` | string / RFC 3339 UTC | 邀请创建时刻 |
| `expiresAt` | string / RFC 3339 UTC | 单次 15 秒与总期限的较早时刻 |

**处理约束**：Invitation 所有者为 S-02。通知延迟不延长 expiresAt；司机从 S-02 查询并接受，不由通知服务直接分配。

**完整消息**：[示例 JSON](examples/ride.invitation-issued.v1.json)。字段校验定义为 `event.schema.json#/$defs/ride.invitation-issued.v1`。

### E-03 `ride.invitation-closed.v1`

**含义/触发**：邀请已不可继续接受。Invitation 进入终态并提交；接受/取消时可与相应订单事实在同一事务产生。

**发布/订阅**：ride-service → dispatch-service：重读订单，仍 MATCHING 且未到期才换候选；notification-service：撤销提示；operations-service：记录。

| data 字段 | 类型/约束 | 含义 |
| --- | --- | --- |
| `rideOrderId` | string / ID | 权威订单 ID；必须等于 envelope.aggregateId |
| `passengerId` | string / ID | 订单所属乘客 ID |
| `stateVersion` | integer ≥ 1 | 该订单的业务状态版本 |
| `invitationId` | string / ID | 邀请 ID |
| `driverId` | string / ID | 受邀司机 |
| `status` | string：ACCEPTED, REJECTED, EXPIRED, REVOKED | 邀请终态 |
| `closedAt` | string / RFC 3339 UTC | 终结时刻 |

**处理约束**：接受产生的 ACCEPTED 关闭事件不能被误解为需要重新派单；取消/失败后迟到的关闭事件也只能结束处理。

**完整消息**：[示例 JSON](examples/ride.invitation-closed.v1.json)。字段校验定义为 `event.schema.json#/$defs/ride.invitation-closed.v1`。

### E-04 `ride.order-assigned.v1`

**含义/触发**：司机分配已由权威确认。邀请接受、订单 ASSIGNED、司机占用与操作记录/Outbox 原子提交。

**发布/订阅**：ride-service → notification-service：向乘客/司机提示；operations-service：更新履约投影。

| data 字段 | 类型/约束 | 含义 |
| --- | --- | --- |
| `rideOrderId` | string / ID | 权威订单 ID；必须等于 envelope.aggregateId |
| `passengerId` | string / ID | 订单所属乘客 ID |
| `stateVersion` | integer ≥ 1 | 该订单的业务状态版本 |
| `invitationId` | string / ID | 被接受邀请 |
| `driverId` | string / ID | 确认分配司机 |
| `state` | "ASSIGNED" | 订单状态 |
| `acceptedAt` | string / RFC 3339 UTC | 取消费计算所用接单时刻 |

**处理约束**：只有本事实/权威状态表示接单成功；候选、邀请送达、接受请求已发送都不等价。

**完整消息**：[示例 JSON](examples/ride.order-assigned.v1.json)。字段校验定义为 `event.schema.json#/$defs/ride.order-assigned.v1`。

### E-05 `ride.order-arrived.v1`

**含义/触发**：已分配司机到达上车点。S-02 核验司机及 ASSIGNED→ARRIVED 并提交。

**发布/订阅**：ride-service → notification-service：到达提示；operations-service：更新履约投影。

| data 字段 | 类型/约束 | 含义 |
| --- | --- | --- |
| `rideOrderId` | string / ID | 权威订单 ID；必须等于 envelope.aggregateId |
| `passengerId` | string / ID | 订单所属乘客 ID |
| `stateVersion` | integer ≥ 1 | 该订单的业务状态版本 |
| `driverId` | string / ID | 已分配司机 |
| `state` | "ARRIVED" | 订单状态 |
| `arrivedAt` | string / RFC 3339 UTC | 权威到达时刻 |

**处理约束**：不能从 GPS 接近直接推断到达；须由有权司机发起并通过 S-02 状态检查。

**完整消息**：[示例 JSON](examples/ride.order-arrived.v1.json)。字段校验定义为 `event.schema.json#/$defs/ride.order-arrived.v1`。

### E-06 `ride.trip-started.v1`

**含义/触发**：已确认上车并开始行程。Trip 建立、boardingConfirmedAt/startedAt、订单 IN_TRIP 与 Outbox 同事务提交。

**发布/订阅**：ride-service → notification-service：行程开始提示；operations-service：更新行程投影。

| data 字段 | 类型/约束 | 含义 |
| --- | --- | --- |
| `rideOrderId` | string / ID | 权威订单 ID；必须等于 envelope.aggregateId |
| `passengerId` | string / ID | 订单所属乘客 ID |
| `stateVersion` | integer ≥ 1 | 该订单的业务状态版本 |
| `tripId` | string / ID | 新建行程 ID |
| `driverId` | string / ID | 已分配司机 |
| `state` | "IN_TRIP" | 订单状态 |
| `boardingConfirmedAt` | string / RFC 3339 UTC | 确认上车时刻 |
| `startedAt` | string / RFC 3339 UTC | 行程开始时刻 |

**处理约束**：上车与开始不拆成两个可独立成功的写操作；与取消竞争只可能一方成功。

**完整消息**：[示例 JSON](examples/ride.trip-started.v1.json)。字段校验定义为 `event.schema.json#/$defs/ride.trip-started.v1`。

### E-07 `ride.order-cancelled.v1`

**含义/触发**：订单已取消并保存费用判断依据。Cancellation、CANCELLED、邀请撤销及本单乘客/司机占用释放与 Outbox 同事务提交。

**发布/订阅**：ride-service → pricing-service：按 cancellationId 唯一建立 BillingJob；notification-service：取消提示；operations-service：更新投影。

| data 字段 | 类型/约束 | 含义 |
| --- | --- | --- |
| `rideOrderId` | string / ID | 权威订单 ID；必须等于 envelope.aggregateId |
| `passengerId` | string / ID | 订单所属乘客 ID |
| `stateVersion` | integer ≥ 1 | 该订单的业务状态版本 |
| `cancellationId` | string / ID | 取消事实 ID |
| `driverId` | string / ID 或 null | 取消前已分配司机；无此事实时为 null |
| `state` | "CANCELLED" | 订单状态 |
| `previousState` | string：MATCHING, ASSIGNED, ARRIVED | 取消前权威状态 |
| `actorId` | string / ID | 已验证的发起主体 |
| `actorRole` | string：PASSENGER, DRIVER | 取消者角色 |
| `reason` | string | 取消原因代码或简述 |
| `acceptedAt` | string / RFC 3339 UTC 或 null | 接单时刻；未分配时 null；无此事实时为 null |
| `cancelledAt` | string / RFC 3339 UTC | 权威取消裁决时刻 |
| `cancellationRuleVersionId` | string / ID | 下单保留的取消规则版本 |
| `ruleSnapshot` | object | 嵌套对象，字段见下方 |

ruleSnapshot 必含 graceSeconds=120、feeMinor=500、currency=CNY，均对应本组 BR-03 草案，不读取后续新规则覆盖历史取消。

**处理约束**：MATCHING 必须无 acceptedAt/driverId，且只能乘客取消；ASSIGNED/ARRIVED 必须二者都有。司机取消免费；乘客已接单满 120 秒收 500 分，之前免费。计费失败不反向取消已提交事实。

**完整消息**：[示例 JSON](examples/ride.order-cancelled.v1.json)。字段校验定义为 `event.schema.json#/$defs/ride.order-cancelled.v1`。

### E-08 `ride.match-failed.v1`

**含义/触发**：匹配已失败，旧单不再允许接单。S-02 确认无候选或到 matchDeadline，终结邀请并释放乘客活动槽位。

**发布/订阅**：ride-service → notification-service：失败及重新叫车提示；operations-service：终态投影。

| data 字段 | 类型/约束 | 含义 |
| --- | --- | --- |
| `rideOrderId` | string / ID | 权威订单 ID；必须等于 envelope.aggregateId |
| `passengerId` | string / ID | 订单所属乘客 ID |
| `stateVersion` | integer ≥ 1 | 该订单的业务状态版本 |
| `state` | "MATCH_FAILED" | 订单状态 |
| `reason` | string：NO_CANDIDATE, DEADLINE_EXCEEDED | 失败依据 |
| `failedAt` | string / RFC 3339 UTC | 权威失败时刻 |

**处理约束**：终态由 S-02 写入，即便 S-03/MQ 不可用也依靠 S-02 的持久截止任务执行；无取消费。

**完整消息**：[示例 JSON](examples/ride.match-failed.v1.json)。字段校验定义为 `event.schema.json#/$defs/ride.match-failed.v1`。

### E-09 `ride.trip-completed.v1`

**含义/触发**：行程与履约已结束，费用可随后生成。Trip/订单完成、占用释放、计费依据或缺失标记与 Outbox 同事务提交。

**发布/订阅**：ride-service → pricing-service：按 tripId 唯一建立 BillingJob；notification-service：完成提示；operations-service：终态投影。

| data 字段 | 类型/约束 | 含义 |
| --- | --- | --- |
| `rideOrderId` | string / ID | 权威订单 ID；必须等于 envelope.aggregateId |
| `passengerId` | string / ID | 订单所属乘客 ID |
| `stateVersion` | integer ≥ 1 | 该订单的业务状态版本 |
| `tripId` | string / ID | 已完成行程 ID |
| `driverId` | string / ID | 执行司机 |
| `state` | "COMPLETED" | 订单状态 |
| `startedAt` | string / RFC 3339 UTC | 开始时刻 |
| `endedAt` | string / RFC 3339 UTC | 结束时刻，不得早于开始 |
| `fareRuleVersionId` | string / ID | 报价绑定的计价规则版本 |
| `measurement` | object / 计费依据 或 null | 有效计费依据；缺失不得用零代替；无此事实时为 null |

**处理约束**：measurement=null 时建立待恢复计费任务，查询为 FEE_PENDING；不阻止释放司机，不用预估金额结算。

**完整消息**：[示例 JSON](examples/ride.trip-completed.v1.json)。字段校验定义为 `event.schema.json#/$defs/ride.trip-completed.v1`。

### E-10 `ride.trip-measurement-ready.v1`

**含义/触发**：已结束行程的缺失计费依据已核验补齐。S-02 为已结束 Trip 首次补齐并保存已核对的计费快照、measurementVersion 和 Outbox；本事件不用于反复改价。

**发布/订阅**：ride-service → pricing-service：恢复同一 tripId 任务；operations-service：补齐查询依据。

| data 字段 | 类型/约束 | 含义 |
| --- | --- | --- |
| `rideOrderId` | string / ID | 权威订单 ID；必须等于 envelope.aggregateId |
| `passengerId` | string / ID | 订单所属乘客 ID |
| `stateVersion` | integer ≥ 1 | 该订单的业务状态版本 |
| `tripId` | string / ID | 已结束行程 ID |
| `state` | "COMPLETED" | 履约终态不改变 |
| `fareRuleVersionId` | string / ID | 原计价版本 |
| `measurement` | object / 计费依据 | 核验后的计费依据 |
| `verifiedAt` | string / RFC 3339 UTC | 核验保存时刻 |

**处理约束**：可先于 completed 消息到达；按 tripId 建立/恢复同一 BillingJob，向 S-02 核实完成事实。已有 Bill 时同依据只去重，冲突依据隔离复核，禁止自动重算已确定费用。

**完整消息**：[示例 JSON](examples/ride.trip-measurement-ready.v1.json)。字段校验定义为 `event.schema.json#/$defs/ride.trip-measurement-ready.v1`。

### E-11 `pricing.bill-created.v1`

**含义/触发**：应付费用已确定且不可变。S-04 原子建立唯一 Bill、完成 BillingJob 并保存 Outbox。

**发布/订阅**：pricing-service → notification-service：费用可查询提示；operations-service：费用投影。

| data 字段 | 类型/约束 | 含义 |
| --- | --- | --- |
| `billId` | string / ID | 费用单 ID；等于 aggregateId |
| `billVersion` | 1 | 本版费用单不可变，版本为 1 |
| `billingJobId` | string / ID | 唯一计费任务 |
| `rideOrderId` | string / ID | 关联订单 |
| `passengerId` | string / ID | 付款乘客 |
| `kind` | string：TRIP_FARE, CANCELLATION_FEE | 费用类型 |
| `sourceId` | string / ID | tripId 或 cancellationId |
| `amountMinor` | integer ≥ 0 | 非负整数金额，分 |
| `currency` | "CNY" | 币种 |
| `ruleVersionId` | string / ID | 本次计算使用的费用规则版本 |
| `createdAt` | string / RFC 3339 UTC | 费用单提交时刻 |

**处理约束**：金额仅为契约示例，不代表三城真实费率。0 分无需付款；事件本身不触发自动扣款，S-06 发起支付时仍查 S-04 权威 Bill。

**完整消息**：[示例 JSON](examples/pricing.bill-created.v1.json)。字段校验定义为 `event.schema.json#/$defs/pricing.bill-created.v1`。

### E-12 `payment.attempt-updated.v1`

**含义/触发**：一次支付尝试的权威状态已持久化。S-06 创建或推进 PaymentAttempt 并提交；成功状态须与唯一 Receipt 同事务。

**发布/订阅**：payment-service → pricing-service：只读支付摘要；notification-service：状态提示；operations-service：支付过程投影。

| data 字段 | 类型/约束 | 含义 |
| --- | --- | --- |
| `paymentAttemptId` | string / ID | 尝试 ID；等于 aggregateId |
| `billId` | string / ID | 费用单 |
| `rideOrderId` | string / ID | 订单 |
| `passengerId` | string / ID | 付款乘客 |
| `status` | string：CREATED, PROCESSING, UNKNOWN, SUCCEEDED, FAILED_FINAL | 尝试状态 |
| `statusVersion` | integer ≥ 1 | 尝试状态版本 |
| `amountMinor` | integer ≥ 1 | 正整数金额，分 |
| `currency` | "CNY" | 币种 |
| `updatedAt` | string / RFC 3339 UTC | 权威更新时刻 |
| `reasonCode` | string 或 null | 未知/终态失败原因代码，不含渠道敏感原文；无此事实时为 null |

**处理约束**：UNKNOWN 不等于 FAILED_FINAL；跨尝试不能比较 statusVersion。即使摘要显示失败，是否可新付款仍由 S-06 按 billId 槽位判定；成功展示需要 Receipt 事实/权威查询。

**完整消息**：[示例 JSON](examples/payment.attempt-updated.v1.json)。字段校验定义为 `event.schema.json#/$defs/payment.attempt-updated.v1`。

### E-13 `payment.receipt-confirmed.v1`

**含义/触发**：唯一收款已确认。S-06 验证渠道成功关联、金额、币种及真实性后，将 Receipt、尝试 SUCCEEDED、Outbox 原子提交。

**发布/订阅**：payment-service → pricing-service：费用支付摘要；notification-service：付款成功提示；operations-service：收款投影。

| data 字段 | 类型/约束 | 含义 |
| --- | --- | --- |
| `receiptId` | string / ID | 收款 ID；等于 aggregateId |
| `paymentAttemptId` | string / ID | 成功尝试 |
| `billId` | string / ID | 费用单 |
| `rideOrderId` | string / ID | 订单 |
| `passengerId` | string / ID | 付款人 |
| `amountMinor` | integer ≥ 1 | 确认实收正金额，分 |
| `currency` | "CNY" | 币种 |
| `paidAt` | string / RFC 3339 UTC | 经核验的渠道支付时刻 |

**处理约束**：Receipt 按 billId 唯一；重复回调/主动查询不得重复入账。Receipt 的存在优先于任何迟到尝试摘要，不能回退成未付款；渠道交易号留在 S-06，不广播敏感回调。

**完整消息**：[示例 JSON](examples/payment.receipt-confirmed.v1.json)。字段校验定义为 `event.schema.json#/$defs/payment.receipt-confirmed.v1`。

## 订阅、乱序与恢复责任

| 消费方 | 幂等键/来源 | 乱序、缺失与故障处理 |
| --- | --- | --- |
| dispatch-service | eventId + rideOrderId/matchPlanId 的提议幂等 | 先读订单是否仍 MATCHING/未过截止；过时事实不创建邀请，重复提议由 S-02 拒绝或返回原结果；重启扫描 S-02 的未到期匹配单恢复 |
| pricing-service：计费 | eventId；BillingJob 按 (sourceType, sourceId) 唯一，Bill 按 billingJobId 唯一 | 不能只按最大 aggregateVersion 丢掉旧未处理事实；依据补齐先到则查 S-02 事实并恢复同任务；缺依据持久等待，已有 Bill 与新依据冲突隔离核查 |
| pricing-service：支付摘要 | 各 paymentAttemptId 的 statusVersion，Receipt 按 billId 去重 | Receipt 一旦存在，迟到的任何尝试状态都不能回退 PAID；跨尝试不比较版本；显示未知时从 S-06 查证，支付资格不由摘要决定 |
| notification-service | (eventId, recipientId, channel)，映射稳定 deliveryId | 先持久投递任务，再 ACK；重放不重做业务。投递前检查接收者归属与事实是否过时；过期邀请提示丢弃，但仍记录已处理 |
| operations-service | eventId + 各来源实体 ID/业务版本 | 分别维护履约、邀请、Trip、Bill、PaymentAttempt 和 Receipt；不把它们混成一个版本。较新的完成可建立履约骨架，迟到的费用/收款仍按各自来源关联；缺项显示未同步并按权限回源 |

业务事实处理与当前状态投影必须区分：投影可忽略同实体的旧状态值，但不可丢弃尚未发生的费用任务/通知任务。事件的发生时间不能决定并发谁先成功；权威本地事务已作出决定，消费者不能重写决定。

邀请子视图以 invitationId 为键，使用其所属 RideOrder 事件的 aggregateVersion 比较 issued/closed 先后，不能仅用未变化的 stateVersion。计费任务按 sourceType/sourceId 唯一，sourceVersion 记录来源事件的 aggregateVersion，并另外保存 measurementVersion；较新依据恢复同一任务，不生成第二张 Bill。measurement-ready 表示缺失依据的首次核验补齐，后续争议/纠错转人工复核，不通过重复发布该事件自动改价。

Schema 仅校验字段结构/枚举等。发布身份、aggregateId 与载荷 ID 相等、同订单/乘客/城市关联、截止时刻、状态合法迁移、版本递增、真实渠道验签和金额一致都由服务及设计评审约束，不能仅靠 JSON Schema 证明。

## 检查与后续工作

本次静态校验及未执行事项见 [CHECKS.md](CHECKS.md)。三条时序图使用上述精确事件名；HTTP 方法、路径与错误体由 #71199996 补齐。服务边界、流程和契约发生变更时协同修改，跨成员确认须在真实评审后填写。
