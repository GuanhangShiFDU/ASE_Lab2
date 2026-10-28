# 设计图

本目录用于保存可编辑图源和导出图。已提供三张逻辑数据模型图、#71199991 叫车主流程/恢复图及 #71199994 取消重叫/竞争恢复图；行程支付时序图和总体架构图待后续完成。

| 图 | 建议图源名 | 说明 |
| --- | --- | --- |
| 履约与分配模型 | [data-model-ride.mmd](data-model-ride.mmd) / [PNG](data-model-ride.png) | S-02 履约权威与 S-03 候选方案 |
| 定价与收款模型 | [data-model-billing.mmd](data-model-billing.mmd) / [PNG](data-model-billing.png) | S-04 费用与 S-06 收款边界 |
| 参与者与查询副本 | [data-model-support.mmd](data-model-support.mmd) / [PNG](data-model-support.png) | 资料、位置、通知和运营只读模型 |
| 报价、叫车与接单 | [源](quote-request-match.mmd) / [PNG](quote-request-match.png) / [SVG](quote-request-match.svg) | 正常路径及无候选、拒绝/过期、失效报价与接单冲突 |
| 客户端恢复与位置/通知 | [源](booking-recovery.mmd) / [PNG](booking-recovery.png) / [SVG](booking-recovery.svg) | 叫车流程补充图，未知结果、刷新、位置权限和只读投影 |
| 取消与重新叫车 | [源](cancel-rebook.mmd) / [PNG](cancel-rebook.png) / [SVG](cancel-rebook.svg) | 取消资格、计价、通知与全新订单 |
| 取消竞争与恢复 | [源](cancellation-races.mmd) / [PNG](cancellation-races.png) / [SVG](cancellation-races.svg) | 接单/上车竞争、费用同意上限与原键恢复 |
| 接驾、上车与支付 | `pickup-trip-payment.mmd` | 包含支付失败及结果处理 |
| 系统整体架构 | `architecture.mmd` | 汇总最终服务及主要交互，提供图例 |

接驾支付及整体架构的文件名是后续约定，文件尚未创建。可使用 Mermaid，也可根据表达需要使用 `.drawio` 或 `.puml` 等图源，并相应调整引用。

## 导出与引用

- 图源与导出图一并保留，确保后续可修改。
- 数据模型、时序图等导出文件可放在本目录，并通过相对路径嵌入 [设计报告](../design.md)。
- 整体架构图最终导出到仓库根目录 `architecture.png`。文件生成后，在报告中使用 `![系统整体架构图](../architecture.png)` 引用；还可以附加 SVG 等格式。
- 截图或导出后检查文字、线条和图例是否清晰，避免只提交图源链接而缺少报告中的可见图。
- 服务名、ID、状态、接口方法和事件名以报告与契约中的一致定义为准。修改图时检查相关定义是否也需要更新。

## 本卡数据图说明

- 每个框的 `S-xx` 是权威所属服务，与报告第 2.2 节一致；`ref` 是跨服务业务 ID 引用，不是跨库外键或调用协议。关系基数表示业务关联，不能仅由线型判断服务边界。
- 图中字段为关键子集，状态、互斥和幂等约束以报告第 2.3～2.5 节为准。`OperationRecord` 是各服务内部通用记录，未重复画入各图。
- PNG 已嵌入报告。图源使用 Mermaid CLI 11.12.0 导出，不需要同学安装绘图工具才能应用交接包。
- 需要重新导出时，在仓库根目录运行以下命令（需 Node.js 和相应绘图依赖）：

```bash
for model in ride billing support; do
  npx --yes @mermaid-js/mermaid-cli@11.12.0 \
    -i "docs/diagrams/data-model-$model.mmd" \
    -o "docs/diagrams/data-model-$model.png" \
    -t neutral -b white -w 1800 -s 2
done
```

语法参考：[Mermaid ER 图](https://mermaid.js.org/syntax/entityRelationshipDiagram)；导出工具：[Mermaid CLI](https://github.com/mermaid-js/mermaid-cli)。

## 叫车流程图导出

#71199991 的两张图均已嵌入报告；方法定义见 [叫车契约](../../contracts/http/booking.md)，SVG 便于缩放阅读。图例：同步请求为实线实心箭头，响应为虚线实心箭头，异步事实为开放箭头；本地自调用为服务内截止任务。

```bash
for diagram in quote-request-match booking-recovery; do
  for format in png svg; do
    npx --yes @mermaid-js/mermaid-cli@11.12.0 \
      -c docs/diagrams/booking-render.json \
      -i "docs/diagrams/$diagram.mmd" \
      -o "docs/diagrams/$diagram.$format" \
      -t neutral -b white -w 2400 -s 2
  done
done
```

语法参考：[Mermaid 时序图](https://mermaid.js.org/syntax/sequenceDiagram.html)。这只是设计图渲染，不是业务运行测试。

## 取消与重叫图导出

#71199994 两张图复用上述 `booking-render.json`；将导出循环的图名替换为 `cancel-rebook cancellation-races` 即可。请求与事件定义见 [取消契约](../../contracts/http/cancellation.md)。PNG 已嵌入报告，长图可打开 SVG 放大阅读。
