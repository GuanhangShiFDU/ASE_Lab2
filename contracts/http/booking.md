# 报价、叫车与接单契约

任务：#71199991；基线：`bada6eb9aa0300487b93facb4e0c157fe4937f58`。本文件给流程图提供确定的方法名、权限和恢复语义，配套 [OpenAPI](openapi.yaml) 定义 9 个客户端核心操作。它是设计草案，没有可调用服务器；示例均为虚构数据。#71199996 现已在 [接口总览](core-api.md) 汇总其余流程和辅助接口；本文件保留叫车语义。

## 共同约定

- 使用 HTTPS/JSON，请求先经过身份验证，业务服务再校验角色和资源归属。客户端不能通过传入 passengerId/driverId 指定操作身份；内部接口只允许授权服务身份，不能从公网绕过。
- 新增坐标提案统一为 **WGS84**，范围检查后再校验起点所属城市及起终点同城。地图供应商坐标由适配器显式转换，禁止只改坐标系标签。此项待组内确认；若后续更换，须同时更新 Point、定位接口和地图适配器。
- 时间为 UTC RFC 3339，以 `Z` 结尾；金额为非负整数分（CNY），距离为整数米、时长为整数秒。ID 是不透明字符串，版本为正安全整数。业务状态沿用设计报告第 2 章，不能混用订单状态与邀请状态。
- Quote 的价格是“预估”，不是应付费用。报价包含 120 秒有效期、计价版本及取消规则展示快照。首次建单使用服务端裁决时间，恰好到期即失效；成功后保留版本，不能途中追溯改价。
- `Idempotency-Key` 在本文也称 `operationId`，作用域为 `(认证主体, 方法名 operationType, 键)`；同键同内容返回原状态码与结果快照，同键异内容返回 `IDEMPOTENCY_CONFLICT`。接单/拒绝的 invitationId 也属于请求指纹；不能换资源复用键。
- 写请求先核对已有操作结果，再读依赖和检查当前资格。业务事实、操作成功记录、Outbox 必须同事务提交。重复键并发只允许一次效果；另一个请求等待有界时间后可返回 `OPERATION_PENDING`。无已提交成功而发生依赖故障时仍用原键恢复，不为避免等待生成新意图。
- 操作在线重放至少 7 天，依照第 3 章提案；业务唯一约束及历史事实继续保存。超过窗口先按本人活动单、历史订单及业务标识核对，不能把记录过期当成重新执行许可。客户端可本地保存 operationId/请求指纹用于恢复，但本地“成功/失败”不构成业务事实。
- 超时/断网/网关 5xx 可能根本没有本契约错误体，一律按结果未知处理。`retryable=true` 只表示可退避恢复，不授权换键或重复创建业务。

## 客户端核心调用（OpenAPI operationId）

表中名称与图中的调用名完全一致；所有输入输出结构及逐操作示例在 [OpenAPI](openapi.yaml) 中。

| 名称 / 方法与路径 | 调用方 → 提供方 | 输入与结果 | 关键约束 |
| --- | --- | --- | --- |
| `createQuote` / POST `/v1/quotes` | 乘客 → S-04 | cityId、pickup、destination → Quote | 本人、支持城市及同城；地图失败不能猜报价；改起终点重新报价 |
| `createRideOrder` / POST `/v1/ride-orders` | 乘客 → S-02 | quoteId、sourceOrderId 或 null、原操作键 → RideOrder | 201 仅是 MATCHING 已提交；全局乘客活动槽位和 quoteId 唯一；不是接单成功 |
| `getRideOrder` / GET `/v1/ride-orders/{rideOrderId}` | 所属乘客/已分配司机 → S-02 | ID、可选 minStateVersion → 当前 RideOrder | 版本仅在同一订单内比较；不得用其他订单的版本；恢复或写后确认回源 |
| `getMyActiveRide` / GET `/v1/me/active-ride` | 乘客/司机 → S-02 | 认证主体 → 当前活动单或 null | 不需要本地已知订单 ID；null 不证明之前的未知请求失败 |
| `listDriverInvitations` / GET `/v1/me/invitations` | 司机 → S-02 | 认证主体 → 当前有效邀请列表 | 只含本人的有效 PENDING；司机可收到不同订单邀请，但最多成功占用一单 |
| `acceptInvitation` / POST `/v1/invitations/{invitationId}/accept` | 受邀司机 → S-02 | invitationId、原操作键；无请求体 → DecisionResult | 位置证明在事务外获取；截止时间、订单、邀请、在线/同城/占用在本地裁决时重验 |
| `rejectInvitation` / POST `/v1/invitations/{invitationId}/reject` | 受邀司机 → S-02 | invitationId、原操作键；无请求体 → DecisionResult | 只拒绝邀请，不取消订单；REJECTED 不占用司机，不推进订单 stateVersion |
| `getOperationResult` / GET `/v1/me/operations/{operationId}?operationType=…` | 原操作者 → 写入所有者（按 operationType 路由） | 原键、方法名 → SUCCEEDED / REJECTED / PENDING / NOT_OBSERVED | 查询已有结果快照；后两者都不是失败证明。只有该主体可查询 |
| `getOrderLocation` / GET `/v1/ride-orders/{rideOrderId}/location` | 所属乘客 → S-05 | 订单 ID → 关联司机最新点、新鲜度和时间 | 只允许 ASSIGNED/ARRIVED/IN_TRIP；不能拿任意 driverId 枚举位置 |

`RideOrder` 是本流程所需的查询字段子集，不替代完整逻辑模型。MATCHING/MATCH_FAILED 的 assignedDriverId、acceptedAt 为 null；ASSIGNED/ARRIVED/IN_TRIP/COMPLETED 二者非空；CANCELLED 按取消前是否接单保留事实。createdAt + 60 秒 = matchDeadline。邀请 expiresAt = min(createdAt + 15 秒, matchDeadline)。这些跨字段约束必须由实现和设计评审检查，不能仅依赖字段类型验证。

`InvitationList` 不包含乘客联系方式和精确终点等非必要资料；本卡不设计接单前公开个人信息。后续邀请详情若增加字段，应按最小授权原则评审。司机列表展示订单/邀请 ID、城市、剩余期限即可表达本实验的接受/拒绝流程。

`DecisionResult` 保留第一次裁决时的邀请与 stateVersion；它不能证明订单此刻仍 ASSIGNED。接单成功后有可能紧接着发生取消，客户端必须再读当前订单。过期邀请的重复成功请求先返回原成功记录，不根据当前时间把历史成功改成失败。

## 错误与恢复

| HTTP / 业务 code | 含义与客户端动作 |
| --- | --- |
| 400 `INVALID_REQUEST` / `INVALID_COORDINATE` / `UNSUPPORTED_CITY` / `CROSS_CITY_NOT_SUPPORTED` | 输入或范围不支持；明确反馈，修改输入后再产生新意图 |
| 401 `UNAUTHENTICATED`；403 `FORBIDDEN` / `LOCATION_NOT_AUTHORIZED` | 重新认证或拒绝访问；认证恢复后先查询原操作，不凭 UI 自行放行 |
| 404 `NOT_FOUND` | 不存在或对主体不可见；不泄露其他人的实体；未知写结果不能因此自动判失败 |
| 409 `QUOTE_EXPIRED` | 首次叫车未提交且报价失效，重新报价并由用户确认；先排除已有原键成功 |
| 409 `QUOTE_ALREADY_USED` / `ACTIVE_RIDE_EXISTS` / `INVALID_SOURCE_ORDER` | 报价已绑定、已有活动单或来源单不合法；查询本人已有业务，不能绕过唯一约束 |
| 409 `INVITATION_EXPIRED` / `ORDER_STATE_CONFLICT` / `DRIVER_UNAVAILABLE` / `LOCATION_STALE` | 本次新决策不能提交；重新读取当前订单/本人邀请。不能本地显示已接单或换键强行接受 |
| 409 `IDEMPOTENCY_CONFLICT` | 同键的资源或输入不同；保留并核对原结果，不自动分配新键 |
| 429 `RATE_LIMITED` | 按 Retry-After 退避；写请求保留原键；不多层无限重试 |
| 503 `ROUTE_UNAVAILABLE` / `DEPENDENCY_UNAVAILABLE` / `STATE_NOT_FRESH` | 地图/依赖/指定最低版本不可用；读请求在预算内重试，写请求保持原键。服务若确认事务未提交可用 outcome=REJECTED，否则用 UNKNOWN |
| 503 `OPERATION_PENDING`，或无业务响应的传输超时 | 结果未知，查询原 operationId，必要时原键原内容恢复。不能解释为“没有创建订单”或“司机没有接单” |

错误体 `{code,message,requestId,outcome,retryable}`；只有鉴权通过且资源属于该主体时才可附带 rideOrderId/stateVersion。OpenAPI 现提供逐操作错误示例，具体错误按对应 operation 的 `x-error-codes`、[统一映射](error-codes.yaml)和本表选择。

## 服务间方法与外部适配器

这些是本组定义的方法契约，使用第 3 章的同步 HTTPS/JSON；不是新增 gRPC。内部路径已由 #71199996 在 [internal.yaml](internal.yaml) 统一，接口名称和语义保持供图引用。`MapAdapter.estimateRoute` 是本组对地图服务的适配器端口名，不声称是某供应商真实 API。网关转发、身份组件校验和每次 HTTP 返回不分别占用图中生命线。

| 方法 | 调用方 → 提供方 | 输入 → 输出 / 失败条件 |
| --- | --- | --- |
| `estimateRoute` | S-04 → 外部地图适配器 | 同城 WGS84 起终点 → 非负整数 distanceMeters/durationSeconds、路径来源；转换/路由失败则 ROUTE_UNAVAILABLE |
| `getQuoteSnapshot` | S-02 → S-04 | quoteId、受信的乘客身份 → 不可变 Quote/所属乘客；不存在、不属于该乘客或依赖故障不建单；首次有效期由 S-02 重验 |
| `getMatchingOrder` | S-03 → S-02 | rideOrderId → 起终点/城市、state、stateVersion、aggregateVersion、当前邀请及 matchDeadline；非 MATCHING 或到期即停止方案 |
| `findCandidateLocations` | S-03 → S-05 | 城市、起点、候选范围/上限 → driverId、有效点、locationVersion、lastValidReceivedAt；依赖故障与成功空列表严格区分 |
| `getDriverEligibility` | S-03 → S-02 | 候选 driverId 集合 → 在线、城市、占用、availabilityVersion；仅提供快照，不预占司机 |
| `proposeInvitation` | S-03 → S-02 | rideOrderId、driverId、matchPlanId、expectedAggregateVersion、proposalId → Invitation；原 proposalId 幂等。重验 MATCHING、无 PENDING、期限和本地资格，过时版本返回冲突 |
| `finishMatchingNoCandidates` | S-03 → S-02 | rideOrderId、matchPlanId、expectedAggregateVersion、proposalId → MATCH_FAILED；仅成功完成候选搜索确为空、订单仍 MATCHING 且无 PENDING、版本未变化才提交；搜索故障不能冒充无司机 |
| `getFreshLocationProof` | S-02 → S-05 | driverId、cityId → 最新有效点引用、locationVersion、lastValidReceivedAt；失败不确认新接单，事务内再次比较年龄和本地城市资格 |
| `expireInvitation` | S-02 持久截止任务 → S-02 | invitationId → 到期时 PENDING 转 EXPIRED、Outbox；不存在/已终态只读返回；不依赖 MQ TTL 或客户端计时 |
| `expireMatchingDeadline` | S-02 持久截止任务 → S-02 | rideOrderId → 到期且仍 MATCHING 才转 MATCH_FAILED、撤销待处理邀请、释放本单乘客槽位、Outbox；ASSIGNED/CANCELLED 等不回退 |
| `authorizeOrderLocation` | S-05 → S-02 | 受信主体、rideOrderId → 当前关联 driverId、stateVersion、是否允许；错误/授权不明拒绝。可用缓存上限 5 秒且终态/分配改变失效 |
| `deliverHint` | S-07 → 客户端通知通道适配器 | deliveryId、接收者、eventId、rideOrderId/邀请标识 → 投递回执/待重试；外部回执不代表业务确认 |

expectedAggregateVersion 来自 S-02 的 RideOrder 事件流版本（第 3 章与事件 envelope 已定义），用于避免旧候选方案在邀请已变化后仍生效；它不等于订单 stateVersion。同一事务写多条事件可递增多次。S-03 提议冲突后先重读当前状态，不用旧方案无限重试。邀请 PENDING 不占用司机；司机同时收到不同订单的邀请时，只有一次接受可以设置全局 activeOrderId。

补充入口的业务方法（HTTP 绑定现见 [总览](core-api.md)）：S-01 `getMyProfile/updateMyProfile`；S-02 `getDriverServiceState/setDriverAvailability`（离线且无活动单才换城）；S-05 `openLocationSession/reportDriverLocation`（服务端 epoch + sequence，旧点不刷新新鲜度）；S-07 `listMyNotifications`；S-08 `queryOperationsRecords`（按城市授权、返回来源版本和同步时间、审计查询）。输入输出及界面反馈见报告 4.1.1，完整 OpenAPI 已由 #71199996 补齐。

## 事实事件对照

| 图中事件 | 触发 / 结果 | 订阅者 |
| --- | --- | --- |
| `ride.order-created.v1` | MATCHING、乘客槽位、OperationRecord、Outbox 提交后 | S-03 开始候选；S-08 查询投影 |
| `ride.invitation-issued.v1` | S-02 创建 PENDING 后；不是接单成功 | S-07 邀请提示；S-08 |
| `ride.invitation-closed.v1` | ACCEPTED/REJECTED/EXPIRED/REVOKED 后 | S-03 重读后决定是否换候选；S-07；S-08 |
| `ride.order-assigned.v1` | S-02 原子确认分配后 | S-07 乘客/司机提示；S-08 |
| `ride.match-failed.v1` | S-02 确认无候选或总期限后 | S-07 失败提示；S-08 |

字段、JSON Schema、完整示例及投递恢复沿用 [事件目录](../events/README.md)。图中的 MQ 表示 RabbitMQ topic 路由；S-02 自身持久截止任务独立于队列。关闭事件可能晚于分配事件到达，S-03 必须回源；不能把 ACCEPTED 关闭理解成“换一个司机”。每个订阅者使用自己的队列，重复 eventId 去重，通知失败不反向取消业务。

## 调用示例：一个意图、一把键

下面仅演示设计用请求，域名不可连接；不要把这些示例当作验证服务已运行的命令。

```http
POST /v1/ride-orders
Authorization: Bearer <当前乘客凭据>
Idempotency-Key: op-order-01
Content-Type: application/json

{"quoteId":"quote-booking-01","sourceOrderId":null}
```

若响应丢失，先请求 `GET /v1/me/operations/op-order-01?operationType=createRideOrder`；SUCCEEDED 返回原 MATCHING 快照及 order ID 后，再 `GET /v1/ride-orders/order-booking-01?minStateVersion=1` 获取可能已 ASSIGNED 的当前状态。NOT_OBSERVED 时继续原键查询/重试，不产生 `op-order-02`。独立新报价/新叫车意图才使用新键；已有活动单时服务端仍拒绝。

## 本地静态校验

安装隔离环境后可重复校验 OpenAPI、内嵌示例与字段边界；无需 Docker 或后端。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r contracts/http/requirements-check.txt
.venv/bin/python contracts/http/validate.py
```

Windows 使用 `py -m venv .venv` 后，将 Python 路径改为 `.venv/Scripts/python.exe`。建议 Python 3.10 及以上；验证器没有发起业务 HTTP 请求。约束间的时间关系、幂等、并发和权限仍须设计评审与未来实现测试。临时环境不要提交。
