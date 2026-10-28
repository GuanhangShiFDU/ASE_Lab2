# 核心接口总览（#71199996）

本卡把三条流程中已经确定的逻辑方法绑定为可校验的设计契约：20 个核心客户端操作、8 个辅助客户端操作、16 个内部操作。它们尚未实现，也不存在可调用的服务器。所有示例为虚构数据；外部渠道尚未选型，不把本组适配器端口冒充供应商真实 API。设计基线为 `3b637d1e1f5ec333808518a608602781554a83dc`。

- [公网 OpenAPI 3.1.0](openapi.yaml)：路径、参数、请求/响应 Schema、权限说明、逐接口成功及失败示例；每个操作含 `x-owner`、`x-callers`。
- [内部 OpenAPI 3.1.0](internal.yaml)：服务身份、允许调用方、scope、可信委托、独立服务的虚构域名；通过相对 `$ref` 复用公网字段，避免 ID/单位分叉。
- [统一错误码映射](error-codes.yaml)：唯一 code→HTTP 状态；失败示例必须与该接口 `x-error-codes` 完整对应。
- [叫车](booking.md)、[取消重叫](cancellation.md)、[行程支付](trip-payment.md) 保留业务规则、事务和恢复细节；[事件目录](../events/README.md) 保留完整 13 类事实及 JSON Schema。

## 1. 认证、授权、版本及幂等

公网基址是 `https://api.example.invalid`（不可连接的示例）；路径版本 `/v1`，契约文档版本 `0.4.0-contract-review` 表示评审草案。这里没有选择 JWT/OAuth 产品或登录供应商；S-01 身份组件验证已有 bearer 凭据、账号状态及当前角色，各业务服务还必须校验资源归属。注册/凭据签发不属于三条核心流程，后续接入时需另选身份方案，不能把 `getMyProfile` 当成登录接口。

乘客只能操作本人出行/费用/支付，司机只能处理本人邀请和已分配订单。运营每次查询都由 S-08 调用 S-01 `authorizeOperationsQuery` 验证当前角色和城市，并记录 QueryAudit。服务身份也不是全能身份：内部路径默认不公开，使用专用短期 serviceAuth 凭据，验证签发方、受众、有效期、允许调用方、scope 和授权城市；不能把普通用户 bearer 转发为内部身份。需要代理用户的接口同时携带 `Delegation-Token`，由受信身份组件签发并绑定主体、调用服务、受众与范围，不能转信客户端自填的 passengerId/driverId/角色标头。后台扫描/计量作业使用独立城市限定 scope，不冒用乘客。

未认证 401；权限不足 403；为防枚举，资源不存在或对主体不可见均可 404，返回体不披露他人信息。只有已授权资源可在错误中附 rideOrderId/stateVersion。内部接口不向公网暴露服务身份、业务快照中的乘客标识或位置候选。所有成功读取/写入都不改变既定数据所有者。

公共格式：HTTPS + UTF-8 JSON；ID 为 1–128 字符不透明标识；时间 UTC RFC3339、以 Z 结尾；CNY 金额为整数分，米/秒为整数，均限定安全整数范围；坐标 WGS84。请求只提交允许字段，不能自定付款金额、用户身份、占用或权威状态。响应添加可选字段可在 v1 内演进；客户端忽略未知可选字段，遇到未知业务状态保留并回源，不能默认为成功。删除/改名字段、改变单位/状态含义需新路径主版本，同时更新图、示例和消费者。

版本不能混用：stateVersion 是订单业务状态版本；aggregateVersion 是某实体事件流顺序；profileVersion、availabilityVersion、locationVersion、measurementVersion、billVersion、statusVersion 各自属于对应实体。只有同来源、同实体的版本可比较。只在声明了 minStateVersion 的 GET 传最低已见版本；其他接口写后核对返回的所属实体/版本并回源，不能随意追加未定义参数。

### 写请求及恢复

OpenAPI 的 `operationId` 是固定方法名；运行时幂等键在图中也叫 operationId，HTTP 放入 `Idempotency-Key`。本卡统一用 operationType 表示方法名，键表示具体意图。

| 写入类别 | 去重及未知结果恢复 | 所有者 |
| --- | --- | --- |
| createRideOrder、acceptInvitation、rejectInvitation、cancelRideOrder、reportArrival、confirmBoardingAndStartTrip、completeTrip、setDriverAvailability | `(认证主体, operationType, Idempotency-Key)`；指纹包含资源路径和业务 body。先鉴权与原键恢复，再裁决当前版本/资格 | S-02 |
| updateMyProfile | 同上；profileVersion 冲突明确拒绝，原键原请求恢复 | S-01 |
| openLocationSession | 同上；只有新建会话意图才分配新 epoch；旧键重放不复活旧会话 | S-05 |
| createPaymentAttempt | 同上；202/操作 SUCCEEDED 只表示创建成功，最终款项另查；支付原键→尝试关联长期保留 | S-06 |
| reportDriverLocation | `(driverId, sessionEpoch, sequence)`；同内容原结果、不同内容冲突，旧 epoch/序号拒绝；重复点不刷新 lastValidReceivedAt | S-05 |
| proposeInvitation / finishMatchingNoCandidates | `(服务身份, 方法名, proposalId)`；指纹含订单及完整 body；原键恢复优先，不用旧方案绕过 expectedAggregateVersion | S-02 |
| supplyTripMeasurement | 服务身份、方法名、Idempotency-Key；只补首份经核验计量，不允许改已有计量/费用 | S-02 |
| createQuote | 可生成新报价，没有叫车/扣款效果；不是操作恢复接口覆盖的写入 | S-04 |

前四行共 11 个操作通过 `getOperationResult` 按 operationType 路由到所有者，当前成功结果 Schema 也与方法名绑定，不能把支付尝试当建单结果。成功记录与业务事实同一事务，确定拒绝保存原结果；同键同内容重放原状态码/快照，不能按后来状态改写旧成功。同键异内容 409 IDEMPOTENCY_CONFLICT。原键响应在线保留至少 7 天；超过窗口按持久业务关联核对，不能把过期当重新执行许可。内部提议/计量的未知结果按原键重发并读取权威事实；它们不对客户端开放操作记录查询。

所有传输超时、502/504、连接断开、非 JSON 网关错误都按 UNKNOWN 处理。服务能证明本次未提交时才可 REJECTED；不能仅凭响应 5xx 推断事务回滚。NOT_OBSERVED/404/没有活动单也不证明未知写入失败。retryable 只允许有预算的退避查询或原键原内容恢复，**不允许自动换键**。确定冲突后，先读当前事实，用户重新确认的新意图才用新键。短轮询约 5 秒加抖动，单个在途请求；请求中禁用重复意图按钮，但服务端约束仍是最终保证。

### 错误与响应约定

| HTTP | 语义 | 代表 code / 恢复 |
| --- | --- | --- |
| 200/201 | 权威读取或相应业务写入已提交 | 不是后续匹配/计费/支付一并成功 |
| 202 | 支付尝试与发送任务已持久受理 | CREATED 不是 PAID；查询原尝试 |
| 400 | 格式、范围、输入能力不支持 | INVALID_REQUEST、UNSUPPORTED_CITY、INVALID_COORDINATE、INVALID_CURSOR；修正输入 |
| 401/403 | 身份或资源/城市权限不符 | UNAUTHENTICATED、FORBIDDEN、LOCATION_NOT_AUTHORIZED |
| 404 | 不存在或对当前主体不可见 | NOT_FOUND；不是此前写入失败证明 |
| 409 | 当前业务状态、版本、费用同意或幂等冲突 | QUOTE_EXPIRED、ORDER_VERSION_CONFLICT、CANCELLATION_FEE_CHANGED、PAYMENT_IN_PROGRESS 等 |
| 429 | 限流 | RATE_LIMITED；Retry-After 建议秒数，保留原键 |
| 503 | 必要权威/依赖暂不可用或仍待确认 | DEPENDENCY_UNAVAILABLE、ROUTE_UNAVAILABLE、STATE_NOT_FRESH、OPERATION_PENDING |

本卡消除旧第 3 章“422 业务校验”与既有 OpenAPI 的差异：v1 统一用 400 表示输入不合法，用 409 表示业务冲突，不再额外使用 422。错误体固定含 code/message/requestId/outcome/retryable；例如 OPERATION_PENDING 必须 UNKNOWN。逐操作响应中列出可用 code 与示例，不把所有 409 展示成 QUOTE_EXPIRED；message 是说明文字，客户端按 code 分支。503/429 可带 Retry-After，限流必须带；敏感响应 Cache-Control: no-store，禁止共享缓存泄露。真实网关仍可能不返回本错误体，需按上段兜底。

## 2. 公网接口目录

以下每行链接到同一个可导入 OpenAPI 的文件，Schema 名就是定义位置；完整参数、角色、语义和成功/错误样例在对应 operation 中。GET 不创建、补偿或重置业务事实。表中“无 body”不等于无需认证或查询/路径参数。

| 方法名 / 用途 | 提供方 ← 调用方 | HTTP 路径 | 请求体 → 成功响应 |
| --- | --- | --- | --- |
| `createQuote` 根据起终点生成限时报价 | pricing-service ← passenger | POST `/v1/quotes` | QuoteRequest → 201 Quote |
| `createRideOrder` 确认报价并建立待匹配订单 | ride-service ← passenger | POST `/v1/ride-orders` | CreateRideOrderRequest → 201 RideOrder |
| `getRideOrder` 读取当前履约状态 | ride-service ← passenger, driver | GET `/v1/ride-orders/{rideOrderId}` | 无 body → 200 RideOrder |
| `getMyActiveRide` 刷新后发现本人未结束订单 | ride-service ← passenger, driver | GET `/v1/me/active-ride` | 无 body → 200 ActiveRide |
| `listDriverInvitations` 查询给本司机的当前有效邀请 | ride-service ← driver | GET `/v1/me/invitations` | 无 body → 200 InvitationList |
| `acceptInvitation` 接受一个有效邀请 | ride-service ← driver | POST `/v1/invitations/{invitationId}/accept` | 无 body → 200 DecisionResult |
| `rejectInvitation` 拒绝邀请而不取消乘客订单 | ride-service ← driver | POST `/v1/invitations/{invitationId}/reject` | 无 body → 200 DecisionResult |
| `getOperationResult` 恢复本人未知写请求的原结果 | operationType owner: participant/ride/location/payment ← passenger, driver | GET `/v1/me/operations/{operationId}` | 无 body → 200 OperationResult |
| `getOrderLocation` 读取本人当前订单关联司机的最新位置 | location-service ← passenger | GET `/v1/ride-orders/{rideOrderId}/location` | 无 body → 200 LocationResult |
| `cancelRideOrder` 由乘客或已分配司机取消上车前的订单 | ride-service ← passenger, driver | POST `/v1/ride-orders/{rideOrderId}/cancel` | CancelRideOrderRequest → 200 CancellationResult |
| `getCancellation` 读取本人参与订单的不可变取消事实 | ride-service ← passenger | GET `/v1/ride-orders/{rideOrderId}/cancellation` | 无 body → 200 Cancellation |
| `getCancellationFee` 读取原取消来源的费用生成结果 | pricing-service ← passenger | GET `/v1/ride-orders/{rideOrderId}/cancellation-fee` | 无 body → 200 CancellationFeeResult |
| `reportArrival` 已分配司机报告到达 | ride-service ← driver | POST `/v1/ride-orders/{rideOrderId}/arrive` | TripVersionRequest → 200 ArrivalResult |
| `confirmBoardingAndStartTrip` 确认上车并原子开始行程 | ride-service ← driver | POST `/v1/ride-orders/{rideOrderId}/start-trip` | StartTripRequest → 200 StartedTripResult |
| `completeTrip` 结束行程并释放本单占用 | ride-service ← driver | POST `/v1/trips/{tripId}/complete` | TripVersionRequest → 200 CompletedTripResult |
| `getTrip` 查询本人行程及已核验计量 | ride-service ← passenger, driver | GET `/v1/trips/{tripId}` | 无 body → 200 TripResult |
| `getTripBill` 查询已结束行程的费用单 | pricing-service ← passenger | GET `/v1/trips/{tripId}/bill` | 无 body → 200 TripBillResult |
| `createPaymentAttempt` 为确定的费用单建立一次支付尝试 | payment-service ← passenger | POST `/v1/payment-attempts` | CreatePaymentAttemptRequest → 202 PaymentAttemptResult |
| `getPaymentAttempt` 查询本人支付尝试及最终收款凭据 | payment-service ← passenger | GET `/v1/payment-attempts/{paymentAttemptId}` | 无 body → 200 PaymentAttemptResult |
| `getBillPaymentState` 查询一张费用单的权威支付结果 | payment-service ← passenger | GET `/v1/bills/{billId}/payment-state` | 无 body → 200 BillPaymentState |
| `getMyProfile` 读取本人资料 | participant-service ← passenger, driver | GET `/v1/me/profile` | 无 body → 200 MyProfile |
| `updateMyProfile` 修改本人展示资料 | participant-service ← passenger, driver | PATCH `/v1/me/profile` | UpdateProfileRequest → 200 MyProfile |
| `getDriverServiceState` 查询本人在线意愿和占用 | ride-service ← driver | GET `/v1/me/driver-service-state` | 无 body → 200 DriverServiceState |
| `setDriverAvailability` 设置在线意愿或离线换城 | ride-service ← driver | PUT `/v1/me/driver-service-state` | SetAvailabilityRequest → 200 DriverServiceState |
| `openLocationSession` 建立位置会话 | location-service ← driver | POST `/v1/me/location-sessions` | 无 body → 201 LocationSession |
| `reportDriverLocation` 上报当前有效位置 | location-service ← driver | PUT `/v1/me/location` | LocationReportRequest → 200 LocationReportResult |
| `listMyNotifications` 分页读取本人提示 | notification-service ← passenger, driver | GET `/v1/me/notifications` | 无 body → 200 NotificationPage |
| `queryOperationsRecords` 按授权城市查询只读业务投影 | operations-service ← operator | GET `/v1/operations/records` | 无 body → 200 OperationsPage |


## 3. 内部服务接口目录

每个操作采用自己所属服务的 server；`/internal/v1` 不经公网网关转发。serviceAuth 必须验证调用者清单和 scope，表中的委托是额外校验。无委托的恢复/搜索接口仍须服务身份与城市权限。

| 方法名 / 用途 | 提供方 ← 调用方 | HTTP 路径 | 请求体 → 成功响应 |
| --- | --- | --- | --- |
| `getQuoteSnapshot` getQuoteSnapshot | pricing-service ← ride-service | GET `/internal/v1/quotes/{quoteId}` | 无 body → 200 QuoteSnapshot |
| `getMatchingOrder` getMatchingOrder | ride-service ← dispatch-service | GET `/internal/v1/ride-orders/{rideOrderId}/matching` | 无 body → 200 MatchingOrder |
| `findCandidateLocations` findCandidateLocations | location-service ← dispatch-service | POST `/internal/v1/location-candidates/search` | CandidateRequest → 200 Candidates |
| `getDriverEligibility` getDriverEligibility | ride-service ← dispatch-service | POST `/internal/v1/drivers/eligibility` | DriverIds → 200 DriverEligibility |
| `proposeInvitation` proposeInvitation | ride-service ← dispatch-service | POST `/internal/v1/ride-orders/{rideOrderId}/invitations` | Proposal → 200 Invitation |
| `finishMatchingNoCandidates` finishMatchingNoCandidates | ride-service ← dispatch-service | POST `/internal/v1/ride-orders/{rideOrderId}/no-candidates` | NoCandidatesRequest → 200 RideOrder |
| `getFreshLocationProof` getFreshLocationProof | location-service ← ride-service | GET `/internal/v1/drivers/{driverId}/location-proof` | 无 body → 200 LocationProof |
| `authorizeOrderLocation` authorizeOrderLocation | ride-service ← location-service | GET `/internal/v1/ride-orders/{rideOrderId}/location-authorization` | 无 body → 200 LocationAuthorization |
| `getCancellationFact` getCancellationFact | ride-service ← pricing-service | GET `/internal/v1/ride-orders/{rideOrderId}/cancellation-fact` | 无 body → 200 CancellationFact |
| `listCancellationFacts` listCancellationFacts | ride-service ← pricing-service recovery | GET `/internal/v1/cancellation-facts` | 无 body → 200 CancellationFactPage |
| `getTripFact` getTripFact | ride-service ← pricing-service | GET `/internal/v1/trips/{tripId}/fact` | 无 body → 200 TripFact |
| `listCompletedTripFacts` listCompletedTripFacts | ride-service ← pricing-service recovery | GET `/internal/v1/completed-trip-facts` | 无 body → 200 TripFactPage |
| `supplyTripMeasurement` supplyTripMeasurement | ride-service ← authorized metering recovery job | POST `/internal/v1/trips/{tripId}/measurement` | MeasurementEvidence → 200 TripMeasurement |
| `getBillSnapshot` getBillSnapshot | pricing-service ← payment-service | GET `/internal/v1/bills/{billId}/snapshot` | 无 body → 200 BillSnapshot |
| `getBillPaymentStateInternal` getBillPaymentStateInternal | payment-service ← pricing-service | GET `/internal/v1/bills/{billId}/payment-state` | 无 body → 200 BillPaymentState |
| `authorizeOperationsQuery` authorizeOperationsQuery | participant-service ← operations-service | GET `/internal/v1/operations-authorization` | 无 body → 200 OperationsAuthorization |

`getBillPaymentStateInternal` 是同一个逻辑方法 getBillPaymentState 的内部绑定，OpenAPI operationId 单独命名以避免冲突；返回同一个 BillPaymentState。getOperationResult 也是一个逻辑入口按 operationType 路由多个所有者，不是跨库聚合操作记录。

`getCancellationFact.data` 与 ride.order-cancelled.v1 的 data 同构；sourceVersion 来自事件 aggregateVersion。getTripFact 组合 TripResult、原 FareRuleSnapshot 与源版本，measurementVersion 单独保留；billVersion 不能取代源版本。getQuoteSnapshot 给出报价及原规则参数，S-02 保存用于行程结束计费；getBillSnapshot 是纯不可变费用，不调用支付查询，避免相互递归。

listCancellationFacts/listCompletedTripFacts 的线上查询参数统一为 cursor，图中 cursor 以及旧文档 afterCursor 都表示这一逻辑位置。按服务提交顺序扫描，包含首次计量补齐；响应总是提供 nextCursor（本次安全提交检查点）与 hasMore；hasMore=false 表示扫描快照当前已读完，下次从 nextCursor 继续。检查点只能越过该快照已提交且已返回的事实，不用预分配 ID 或时间戳跨过并发未提交事务。消费者持久保存每项 Job 后才更新检查点；重叠页通过事实 ID/版本与唯一 Job 去重。过期游标必须明确拒绝并重新扫描保留的事实，不能静默跳到最新。

辅助保护提案：批量上限 100、位置候选半径上限 50km、位置观测过去 15 秒至未来 5 秒容差。这些是为字段和错误边界补充的组内提案，待李全昊/刘子扬复核，不能声称课程指定了这些数字。位置“服务端收到新点”不等于“客户端补发旧点”；已过时、低序号或旧会话不改变新鲜度。

C-17 的运营列表默认只查带来源版本/同步时间的投影；如需即时核验单个对象，S-08 的受限核对端口可按 `(operator, cityId, entityType, entityId)` 调用 S-02/S-04/S-06 返回 `{sourceService, sourceId, sourceVersion, checkedAt, authorizedSummary}`，每次重新核验当前城市权限、限制数量并记 QueryAudit。该可选只读能力这里只作输入输出概要，不把公网乘客 token 冒充内部权限，不新增跨服务事务或管理员写接口；具体生产绑定不属于三条核心流程。

## 4. 外部适配器与本地方法

外部供应商未选型，下表是**本组拥有的适配器端口 IO**；由所属服务中的适配模块转换为供应商 HTTPS 调用，没有第九个业务微服务。真实供应商 URL、签名算法、商户配置、凭据签发与重试保留期需在未来实现/选型时确认，本作业不假造可运行 SDK 或已接通支付。回调 handlePaymentCallback 在 S-06 的入站适配器接收渠道原始 body/headers；不能从公网接收一个声称 verified=true 的 JSON 就当成可信支付事实。

| 方法 / 调用方 → 提供方 | 输入概要与虚构示例 | 输出 / 失败 / 幂等 |
| --- | --- | --- |
| estimateRoute / S-04 → 地图适配端口 | `{pickup:{latitude:31.2304,longitude:121.4737,coordinateSystem:"WGS84"}, destination:{latitude:31.219,longitude:121.445,coordinateSystem:"WGS84"}}`；同城校验在调用前后完成 | `{distanceMeters:6200,durationSeconds:1100,routeSource:"map-demo"}`；非负整数；供应商坐标显式转换；失败 ROUTE_UNAVAILABLE，不猜路线/报价 |
| deliverHint / S-07 → 通知适配端口 | `{deliveryId:"delivery-01",recipientId:"user-01",eventId:"event-01",reference:{rideOrderId:"order-01",billId:null}}`；多个接收者拆成各自的 deliveryId | `{deliveryId:"delivery-01",status:"ACCEPTED",channelReceiptId:"hint-01"}` 或 RETRYABLE_FAILURE/UNKNOWN；ACCEPTED 只是通道受理；持久原任务、原 ID 重投，不能重新执行订单/付款 |
| submitCharge / S-06 → 支付适配端口 | `{merchantId:"merchant-demo",channelRequestId:"charge-01",billId:"bill-01",amountMinor:2500,currency:"CNY",paymentMethodRef:"method-owned-01"}`；金额来自核验 Bill，支付方式属于付款人 | `{channelRequestId:"charge-01",status:"PROCESSING",channelTransactionId:null}` 或 UNKNOWN/核验终态；请求号在发送前持久化，商户+渠道+请求号幂等；自动重发只能在渠道保证的幂等保留期内 |
| queryCharge / S-06 → 支付适配端口 | `{merchantId:"merchant-demo",channelRequestId:"charge-01"}`；查原请求，不新扣款 | 成功核验材料 `{channelRequestId:"charge-01",channelTransactionId:"txn-01",amountMinor:2500,currency:"CNY",paidAt:"2026-10-28T02:20:00Z",status:"SUCCEEDED",evidenceRef:"proof-01"}`；普通 NOT_FOUND/超时→UNKNOWN；只有不可逆终态证明可 FAILED_FINAL |
| handlePaymentCallback / 外部渠道 → S-06 入站适配器 | `rawBody` 原始字节、渠道要求的 `signedHeaders`、已配置渠道/商户身份；验签前不先重序列化 body；认证材料不进入 MQ/日志 | 校验商户/原请求号/金额/币种/交易号、签名有效性、时效及重放；可信事实持久处理或隔离后才渠道 ACK；验签失败拒绝并审计；重复 ACK 不重复 Receipt；渠道 HTTP 格式随选型绑定 |
| expireInvitation / S-02 截止任务 → 本地事务 | invitationId，服务端当前时间 | 到期且 PENDING 才 EXPIRED+Outbox；已终态不回退；无 HTTP 入口 |
| expireMatchingDeadline / S-02 截止任务 → 本地事务 | rideOrderId，服务端当前时间 | 到期且 MATCHING 才 MATCH_FAILED、撤销 PENDING、按旧单释放槽位+Outbox；不是 MQ TTL 决定状态；无 HTTP 入口 |
| applyVerifiedPaymentFact / S-06 适配器 → 本地状态机 | 经过服务端核验的商户/请求/交易/金额币种/状态/证据引用 | 同一入口原子写 Attempt+Receipt+Outbox；矛盾持久隔离、冻结新付款；未经验证的回调/客户端不能直调；无 HTTP 入口 |

端口的成功/未知/不可逆失败是适配结果模型，不把真实渠道所有返回值直接透传给客户端。例如“渠道查不到请求”既不等于公开 getPaymentAttempt 的 NOT_FOUND，也不等于 FAILED_FINAL。支付流程进一步的唯一约束与矛盾恢复见 trip-payment.md。

## 5. 三条流程、事件与字段对照

原六张时序图无需改名或重新绘制。本卡只把图中关键参数子集展开为路径、完整 body、认证和恢复契约；`orderId` 是 rideOrderId 的图内简写，`key`/`originalKey` 是 Idempotency-Key，`version` 是对应 expectedStateVersion，`passenger`/`trustedSubject` 是已验证的委托主体，而不是请求体可任填的 ID。事件 E 编号沿用事件目录，Schema 中名字以完整 eventType 为准。

| 流程 / 图源 | 客户端和内部操作 | 事件及字段边界 |
| --- | --- | --- |
| [叫车主图](../../docs/diagrams/quote-request-match.mmd)、[恢复图](../../docs/diagrams/booking-recovery.mmd) | 报价、建单、邀请列表/接受/拒绝、操作恢复、读订单/活动单/位置；内部报价/候选/资格/提议/截止/位置授权，通知与运营列表 | ride.order-created.v1、ride.invitation-issued.v1、ride.invitation-closed.v1、ride.order-assigned.v1、ride.match-failed.v1；quoteId 绑定一次；aggregateVersion 不等于 stateVersion；邀请 PENDING 不占用司机 |
| [取消重叫](../../docs/diagrams/cancel-rebook.mmd)、[竞争恢复](../../docs/diagrams/cancellation-races.mmd) | cancelRideOrder、getCancellation、getCancellationFee、原键恢复、重新报价/建单；getCancellationFact/listCancellationFacts 提供计费事实 | ride.order-cancelled.v1、ride.invitation-closed.v1、pricing.bill-created.v1、ride.order-created.v1；sourceOrderId 仅关联旧单；maxAcceptedFeeMinor 0/500；Cancellation.cancelledAt 与 acceptedAt 及原规则决定费用 |
| [接驾行程支付](../../docs/diagrams/pickup-trip-payment.mmd)、[恢复图](../../docs/diagrams/trip-payment-recovery.mmd) | reportArrival、confirmBoardingAndStartTrip、completeTrip、getTrip/getTripBill、createPaymentAttempt/getPaymentAttempt/getBillPaymentState；内部计量、事实、账单快照和渠道端口 | ride.order-arrived.v1、ride.trip-started.v1、ride.trip-completed.v1、ride.trip-measurement-ready.v1、pricing.bill-created.v1、payment.attempt-updated.v1、payment.receipt-confirmed.v1；Trip→BillingJob→Bill→Attempt→Receipt；UNKNOWN 保留未决槽位 |

13 类事实的完整字段和来源保持 [event.schema.json](../events/event.schema.json) 为准。HTTP 内部取消事实复用 E07 的数据结构，检查器验证两者同构；计量/Bill/Payment 的跨文件示例链仍由原流程检查器核对 ID、版本、整数单位、计价和状态。事件至少一次投递，按 eventId/事实唯一约束去重；HTTP 成功与 MQ 投递确认不是同一时刻，S-07/S-08 的延迟不会回滚业务。

## 6. 重复验证与真实评审

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r contracts/http/requirements-check.txt
.venv/bin/python contracts/http/validate.py
.venv/bin/python contracts/http/validate_cancellation.py
.venv/bin/python contracts/http/validate_trip_payment.py
.venv/bin/python contracts/events/validate.py
.venv/bin/python contracts/http/validate_contracts.py
```

Windows Git Bash 可用 `py -m venv .venv`，然后把 `.venv/bin/python` 换成 `.venv/Scripts/python.exe`。检查只读本地文件：OpenAPI 3.1、相对引用、请求/响应及错误示例、方法名/事件名覆盖、错误状态映射、操作类型→返回结构、现有示例链和反例；不能证明服务已运行、权限执行、真实并发/签名/扣款可靠性。

[本卡实际检查记录](../../docs/checks/core-api-71199996.md) 保存版本/命令/结果和待评审项。李全昊复核字段、权限与数据权威；刘子扬复核事件、状态竞争与幂等。PR 链接和他们的真实确认由 PR 建立/评审后补记，不能用静态检查代替两人的确认。
