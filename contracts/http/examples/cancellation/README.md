# 取消与重新叫车示例

这些是设计示例，不是运行日志。`validate_cancellation.py` 使用现有 OpenAPI、事件 Schema 与字段关联校验读取本目录，不发送请求。

| 文件 | 场景 |
| --- | --- |
| cancel-request.json | 乘客已读取 ASSIGNED / version=2，同意最高 500 分 |
| cancelled-response.json | 恰好接单后 120 秒取消，CANCELLED / version=3 |
| cancelled-event.json | 对应 S-02 事实；aggregateVersion=5 与 stateVersion=3 各自有独立含义 |
| fee-pending-response.json | 同一取消的费用待恢复；bill=null，不能当作免费 |
| fee-ready-response.json、fee-created-event.json | 同一取消最终生成唯一 500 分 Bill 及事实，费用确定不代表收款完成 |
| operation-succeeded-response.json | 原取消操作成功响应丢失后的原结果重放 |
| rebook-request.json、rebook-response.json | 新报价、新订单、新操作键（在 HTTP header 发送），sourceOrderId 保留旧单关联 |
| version-conflict-response.json | 独立的旧版本取消请求被拒绝示例，不是上面成功操作的第二个结果 |
| fee-free-response.json | 独立的 0 分费用单示例，不是把上述 500 分账单修改为免费 |

共 9 个 HTTP 示例和 2 个事件示例。成功链展示具体字段如何相互引用；单份示例不能证明并发、重试、数据库或消息系统已经实现。时间边界及故障分支需按报告第 4.2 节继续评审。
