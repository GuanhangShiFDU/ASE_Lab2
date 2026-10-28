# 接驾、行程与支付契约（#71199995）

这是设计草案，配合[报告第 4.3 节](../../docs/design.md#43-接驾上车与支付)和 [OpenAPI](openapi.yaml)。未实现业务服务、真实计量或支付渠道，本文的规则细化及虚构示例待组内评审。前置 [叫车](booking.md)、[取消](cancellation.md) 和 [13 类事件](../events/README.md) 的语义保持不变；#71199996 已在 [接口总览](core-api.md) 汇总内部 HTTP 绑定和渠道适配边界。

## 1. 权威、身份和操作恢复

S-02 `ride-service` 拥有 RideOrder/Trip、占用和履约操作；S-04 `pricing-service` 拥有 BillingJob/Bill；S-06 `payment-service` 拥有 PaymentAttempt/Receipt 和支付操作。Bill 是应收费用，Receipt 是已核验收款，两者不能互相替代。S-07 只发送提示，客户端/运营副本不能宣布收款。

公网使用 HTTPS + bearer 身份，各服务再验证资源归属。司机只能操作本人已分配行程，乘客只能查本人账单/付款；客户端传入的 passengerId/driverId 或“内部调用”标头不能作为身份。内部请求用受限服务身份和可信委托上下文，逐个核验订单/行程/乘客关联。跨城不改变全局占用约束。未认证 401、无权 403；为防枚举，可将不可见资源统一 404，不泄露他人行程/收款。

三个司机写操作和 createPaymentAttempt 都要求 `Idempotency-Key`。沿用 `(actorId, operationType, key)` + 请求指纹（路径、业务 body，包括支付方式引用）的 OperationRecord。先鉴权并恢复原键，再处理新状态；同键异内容 409 IDEMPOTENCY_CONFLICT。原成功或确定拒绝重放原响应；原已受理支付始终重放原 202 快照，不伪装为最新付款结果。版本冲突后的新意图要先读最新、本人确认再换键。

getOperationResult 在 `/v1/me/operations/{operationId}?operationType=...` 按方法名路由：履约操作归 S-02，createPaymentAttempt 归 S-06；各服务只查认证主体自己的记录。SUCCEEDED 表示**该写操作**已提交：支付建立的 SUCCEEDED/result 仍可为 CREATED；最终收款另查 getPaymentAttempt/getBillPaymentState。PENDING、NOT_OBSERVED、网络超时、502/503、断连均不证明未执行。保持原键和内容查询/恢复，不自动产生新的支付尝试。完整操作响应在线重放至少保留 7 天；支付原键/指纹到 paymentAttemptId 的关联随尝试长期保留，旧键不能在记录归档后变成一次新付款。完整快照归档时先恢复历史关联/原结果；不能确认历史结果就保持未知并查证，不把记录过期当成重新执行许可。

## 2. 公网核心操作

请求/响应字段、枚举、示例和路径以 OpenAPI 为准。时间为服务器 RFC3339 UTC；金额为整数分，距离为整数米，时长为整数秒。下表写入成功均在本地事务提交之后。

| 方法 / HTTP | 调用权限与输入 | 成功及边界 |
| --- | --- | --- |
| reportArrival / POST `/v1/ride-orders/{rideOrderId}/arrive` | 已分配司机；expectedStateVersion | 200 ArrivalResult；仅 ASSIGNED→ARRIVED，记录 arrivedAt，操作/Outbox 同事务；GPS 仅辅助，不自动宣布到达 |
| confirmBoardingAndStartTrip / POST `/v1/ride-orders/{rideOrderId}/start-trip` | 本单司机；expectedStateVersion、boardingConfirmed=true | 200 StartedTripResult；ARRIVED→IN_TRIP，唯一 Trip(IN_PROGRESS) 与 boardingConfirmedAt/startedAt 同事务，不能拆成两个独立成功步骤 |
| completeTrip / POST `/v1/trips/{tripId}/complete` | 本行程司机；expectedStateVersion | 200 CompletedTripResult；IN_TRIP→COMPLETED、Trip→COMPLETED、endedAt，按旧单 ID 条件释放两个占用槽位，操作/Outbox 同事务，不等待计费/付款 |
| getTrip / GET `/v1/trips/{tripId}` | 本行程乘客/司机 | 200 TripResult；从 S-02 查当前状态/已核验计量；IN_PROGRESS 的 endedAt/measurement 均 null |
| getTripBill / GET `/v1/trips/{tripId}/bill` | 所属乘客 | 200 FEE_PENDING/bill=null 或 BILL_READY/TripBill；行程未结束为 409 TRIP_NOT_COMPLETED，权威不可用为 503；查询不创建 Bill |
| createPaymentAttempt / POST `/v1/payment-attempts` | 账单乘客；billId、billVersion、paymentMethodRef，另带幂等键 | 202 PaymentAttemptResult(CREATED)；持久任务异步发往渠道。输入不含金额；支付方式须属本人且有效。支持行程费用或已生成的取消费用 |
| getPaymentAttempt / GET `/v1/payment-attempts/{paymentAttemptId}` | 该尝试所属乘客 | 200 PaymentAttemptResult；状态为 CREATED/PROCESSING/UNKNOWN/SUCCEEDED/FAILED_FINAL；SUCCEEDED 必附 Receipt |
| getBillPaymentState / GET `/v1/bills/{billId}/payment-state` | 费用单乘客；S-04 可经受限内部委托调用 | 200 权威费用支付状态；不可用 503，客户端展示 UNKNOWN，不猜 UNPAID |

订单状态由 S-02 的 `stateVersion` 控制，新操作版本不匹配 409 ORDER_VERSION_CONFLICT，非法状态 409 ORDER_STATE_CONFLICT。confirmBoardingAndStartTrip 与上一张卡的 cancelRideOrder 使用同一订单串行裁决：取消先提交就不能开始；开始先提交就不能普通取消。不按客户端时间裁决。单个 rideOrderId 只能创建一个 Trip，新键重复结束也不能重置 endedAt 或重复释放占用。

## 3. 计量、计费与唯一费用单

completeTrip 不接受司机任意输入的金额/计量。S-02 按服务器 startedAt/endedAt 得到非负整秒时长（向下取整），从经过授权核验的计量来源获得实际距离；原始位置点不直接等同于有效计量。meteringSource 指向可追溯的核验来源，measurementVersion 为正版本。来源丢失时 measurement=null，行程仍可结束，费用保持 FEE_PENDING。

已结束 Trip 缺失计量时，授权的恢复作业调用 supplyTripMeasurement（见下节）：S-02 核验来源、Trip 身份、结束时刻和时长，一次性保存首份完整有效计量及 Outbox。与 completeTrip 并发串行化，先保存者发布带计量的 completed，后补者发布 measurement-ready。补齐不改变订单 stateVersion；同内容重放不新增事实，冲突内容进入人工复核，不能自动覆盖已有有效计量。**该事件只补缺失依据，不提供任意修订已出账费用的通道。**完整计量和规则快照随后不可变，避免“出账与改计量”跨服务竞态；争议/退款不在本轮范围。

S-04 消费 completed/measurement-ready 时，以 `(TRIP_COMPLETED, tripId)` 唯一创建/恢复 BillingJob；Inbox+Job 同事务持久后 ACK。measurement-ready 先到、completed 后到也回源 getTripFact，仍只有同一个任务。sourceVersion 是源 RideOrder 事件流序号，另存 measurementVersion；不能拿订单 stateVersion 去覆盖计量版本或无条件丢弃旧计费事实。

计算只用本单原 fareRuleVersionId 的不可变规则及核验计量；计算结果、唯一 Bill(billingJobId)、Job=READY、Outbox 一次提交。缺依据 PENDING，暂时失败 RETRYING，有冲突 REQUIRES_REVIEW。失败保留任务/lastError/nextRetryAt，持久重试/人工复核；恢复作业按 listCompletedTripFacts 的稳定提交游标补漏，先持久 Job 后推进游标。getTripBill 的 FEE_PENDING 不意味着零费用或支付失败。

本组细化的示例计价式：`roundHalfUp(max(minimumMinor, baseMinor + distanceMeters × ratePerMeterMinor + durationSeconds × ratePerSecondMinor))`，使用精确十进制，最后只舍入一次到整数分，不用二进制浮点。Bill 保存原规则版本、参数、计量和分项依据。虚构示例：900 + 8000×0.11 + 720×1 = 2500 分，最低 1000 分；此数字仅作一致性检查，不是真实城市价格。预估 Quote 不代替实际计费。零额 Bill 为 NO_PAYMENT_REQUIRED，无尝试/Receipt；正数才进入支付。

## 4. 内部方法及外部适配器（用途 / 输入输出）

这些是具体逻辑方法名；#71199996 已在 [internal.yaml](internal.yaml) 统一内部路径/传输鉴权绑定。它们不作为客户端可绕过权限的接口。网络调用在本地数据库事务外完成。

| 方法 | 调用方 → 所有者 / 关键输入 | 输出及约束 |
| --- | --- | --- |
| getTripFact(tripId, trustedSubject) | S-04/授权恢复作业 → S-02 | orderId、passengerId、driverId、城市、Trip 状态/时刻、原计价规则快照、measurement、源事实版本；核验委托归属；不可用不猜事实 |
| listCompletedTripFacts(cursor, limit) | S-04 恢复作业 → S-02 | 按不可变提交游标分页的完成/首次计量补齐事实及 nextCursor；限定授权城市，重叠页去重；不使用可能乱序的客户端时间跳过记录 |
| supplyTripMeasurement(tripId, evidenceRef, operationId) | 已认证、限定权限的计量核验作业 → S-02 | 核验已完成行程与可信证据，返回同一份冻结 measurement/版本；缺失时首次补齐并发出 measurement-ready；同键恢复、冲突隔离，无司机直接改价入口 |
| getBillSnapshot(billId, trustedPassenger) | S-06 → S-04 | 不可变 billId/billVersion、rideOrderId、passengerId、cityId、kind、amountMinor、currency；可信归属校验；原单未出账不可支付 |
| getBillPaymentState(billId, trustedPassenger) | S-04 或乘客 → S-06 | 同一 billId 一致读取 Receipt/未决槽位；可用于费用页聚合。S-04 查询支付失败只显示 UNKNOWN，不改 Bill；S-06 获取 Bill 用纯快照方法，不反向聚合支付，避免循环调用 |
| submitCharge(channelRequestId, verifiedBill, paymentMethodRef) | S-06 持久发送任务 → 外部支付适配器 | 按商户+渠道+稳定请求号幂等；请求含已核验金额/币种，返回成功/处理中/不可逆失败/未知；无业务 DB 锁跨网络等待 |
| queryCharge(channelRequestId) | S-06 对账/恢复作业 → 外部支付适配器 | 返回渠道权威状态、交易号、金额/币种、paidAt、核验材料；普通 NOT_FOUND/超时均未知，不能证明最终失败 |
| handlePaymentCallback(rawBody, signedHeaders) | 外部渠道 → S-06 回调适配器 | 按渠道约定验签、商户/请求号/交易号/金额/币种/时间及重放检查；可信事实持久处理后才 ACK；验签失败拒绝并审计，真实状态矛盾持久隔离核查 |
| applyVerifiedPaymentFact(verifiedFact) | S-06 查询/提交响应/回调适配器 → S-06 本地状态机 | 同一校验和本地事务入口；不向客户端开放；成功更新尝试+唯一 Receipt+释放未决槽位+Outbox；失败/重复/矛盾按第 5 节处理 |
| deliverHint(deliveryId, recipient, reference) | S-07 → 外部通知适配器 | 沿用 booking.md：持久任务与去重、原 ID 重投；只引导读权威状态，付款通知不再发起扣款 |

未指定真实渠道或签名算法。本设计要求渠道提供请求号幂等和可查询的不可逆终态；接入时要验证这两项能力。若渠道不满足，保持 UNKNOWN 并人工核查，不能宣称跨网络自动恰好一次扣款。支付方式引用为本人已授权的不透明引用；不把真实卡号、凭据、原始回调或签名密钥写入业务事件/日志/示例。

## 5. 支付并发、恢复及最终确认

1. 乘客查看不可变 Bill 并确认付款。S-06 先恢复幂等记录，再在事务外核验 Bill 快照、版本、归属和支付方式；请求中的 billVersion 不匹配 409，客户端不能覆盖金额。
2. 同一 billId 在 S-06 串行检查：已有 Receipt → BILL_ALREADY_PAID；零额 → NO_PAYMENT_REQUIRED；CREATED/PROCESSING/UNKNOWN 槽位占用 → PAYMENT_IN_PROGRESS；否则创建一次尝试和稳定 channelRequestId，保存发送任务、操作结果、Outbox 后返回 202。不能在首次渠道调用后才记录请求号。
3. worker 使用原 channelRequestId 提交。进程在发送前/后崩溃均恢复原任务/原请求号；多 worker 租约用于减负，真正防重复扣款依靠稳定渠道幂等号及本地唯一约束。收到处理中改 PROCESSING；超时/断线/结果不明改 UNKNOWN。同步提交响应、主动查询、回调最终统一走 applyVerifiedPaymentFact。
4. UNKNOWN 保留未决槽位，继续 queryCharge。传输重试沿用同请求号，且只在渠道保证的幂等保留期内重发；超过该期只查询/人工核查，不靠同号猜测不会二次扣款。退避按第 3 章 1/5/30/120/600 秒加抖动；达到自动重试预算后转持久隔离/告警，由对账或人工触发继续核查，**预算耗尽不转 FAILED_FINAL，也不释放槽位**。查询无记录不是新扣款许可。
5. 只有核验成功的渠道事实（对应原商户/请求号/交易号、实收金额/币种一致）才能在一次 S-06 事务中写 SUCCEEDED、唯一 Receipt、释放槽位、Outbox。Receipt 对 billId 和成功尝试唯一，交易号在渠道/商户范围唯一。成功响应仅在事务提交后返回；回调确认丢失重放同结果。若已存在一致 Receipt，幂等接受；不同交易号/金额或身份冲突隔离审计，不能产生第二张收款。
6. FAILED_FINAL 仅渠道确认“此请求永远不可能成功”的不可逆失败。该失败与释放未决槽位同事务；新的用户付款意图可用新键创建新尝试/新 channelRequestId，原失败尝试保留。再次创建仍重新检查是否已经收款或有另一个未决尝试。
7. 乱序失败/处理中不能覆盖已存在 Receipt 或倒退 SUCCEEDED。FAILED_FINAL 后若渠道自相矛盾又报成功，不擅自变更已失败尝试/再次收款，而是记录矛盾、暂停本账单新尝试并人工核查渠道；不能用客户端返回页或未经核验回调宣称“已付款”。仍有在途尝试时同样停止额外发送并查证，不能承诺外部已发请求可被撤回。

| 费用/收款事实 | getBillPaymentState / 客户端反馈 | 可否创建新扣款 |
| --- | --- | --- |
| 尚未产生 Bill | getTripBill=FEE_PENDING；“费用计算中” | 否 |
| Bill=0 | NO_PAYMENT_REQUIRED；“无需支付”，无 Receipt | 否 |
| 正额无 Receipt 且无未决槽位，权威读取成功 | UNPAID；可展示付款确认 | 由 S-06 原子复核后决定 |
| 有 CREATED/PROCESSING/UNKNOWN 尝试 | PAYMENT_PENDING + currentAttempt；“支付处理中/结果待确认” | 否；原尝试恢复 |
| 有核验 Receipt | PAID + receipt；即使旧摘要晚到仍保持已付 | 否 |
| S-06/必要 Bill 权威读取不可用 | HTTP 503；调用方显示 UNKNOWN | 否，不把查询失败展示未付款 |

FAILED_FINAL 的示例为独立失败分支，不与成功示例当成同一个尝试的连续状态。S-06 对争议持久保留 billId 级审计冻结标记及原因/证据引用，创建尝试与 worker 发送前都检查它；它不改变 S-04 的费用事实或既有 Receipt。争议隔离会阻止新付款，即便只读汇总暂时无 Receipt/未决槽位，createPaymentAttempt 仍须返回 409 PAYMENT_REVIEW_REQUIRED，不把汇总页面当成付款资格的裁决者。

## 6. 错误与客户端反馈

| HTTP / code | 含义 | 客户端动作 |
| --- | --- | --- |
| 409 ORDER_VERSION_CONFLICT / ORDER_STATE_CONFLICT | 新履约操作未执行，原状态或版本不符 | 读 getRideOrder/getTrip，确定未完成且本人重新确认后新意图；不盲目重放新键 |
| 409 TRIP_NOT_COMPLETED | 行程未结束，不能展示最终费用 | 显示行程中，等权威完成 |
| 409 BILL_VERSION_CONFLICT / PAYMENT_METHOD_INVALID | Bill 版本或支付方式不符 | 重新读取并让用户确认，不改原幂等请求内容 |
| 409 PAYMENT_IN_PROGRESS | 别的键已有未决尝试 | getBillPaymentState 获取 currentAttempt；跟踪原尝试，不自动第二次付 |
| 409 BILL_ALREADY_PAID / NO_PAYMENT_REQUIRED | 已收款或无需付款 | 读取权威结果，停止付款按钮 |
| 409 PAYMENT_REVIEW_REQUIRED | 渠道矛盾/疑似重复收款待核查 | 显示人工核查中，不发新扣款 |
| 409 IDEMPOTENCY_CONFLICT | 同键内容变化 | 找回原请求；不可随机换键掩盖未知结果 |
| 503 OPERATION_PENDING / 传输超时 | 原写操作可能已提交 | 原键 getOperationResult；不得宣称失败或重新扣款 |
| 503 DEPENDENCY_UNAVAILABLE | 读取或前置验证无法确认 | 显示暂不可用/UNKNOWN；写结果不明仍原键恢复 |

客户端使用短轮询、请求中禁用同意图重复点击、展示独立行程/费用/支付状态。未知状态允许刷新/回到页面继续查。服务状态不依赖浏览器是否打开。通知携带参考 ID，收到后读取权威状态；不根据通知先后、事件时间或渠道前端跳转宣布成功。订单完成后可接新单，旧账继续属于原 rideOrderId/billId。

## 7. 静态检查与评审

完整虚构链和边界例见 [examples/trip-payment](examples/trip-payment/README.md)，执行记录及尚未执行的人工推演见 [检查记录](../../docs/checks/trip-payment-71199995.md)。可在仓库根目录使用独立 Python 环境：

```bash
python3 -m venv /tmp/lab2-contract-check
/tmp/lab2-contract-check/bin/python -m pip install -r contracts/http/requirements-check.txt
/tmp/lab2-contract-check/bin/python contracts/http/validate.py
/tmp/lab2-contract-check/bin/python contracts/http/validate_cancellation.py
/tmp/lab2-contract-check/bin/python contracts/http/validate_trip_payment.py
/tmp/lab2-contract-check/bin/python contracts/events/validate.py
```

这些只校验设计格式、示例及引用一致性，不能证明真实鉴权、并发事务、渠道验签、扣款或恢复可靠性。刘子扬复核事件/权威与时序；刘乐翔复核客户端反馈及 #71199996 接口汇总；杨润东复核正常/异常覆盖；真实结论由评审后记录。
