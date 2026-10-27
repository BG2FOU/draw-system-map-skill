# 独立绘图数据格式

工具没有城市数据库；示例均为虚构数据。复制模板后填写自己的网络。JSON 采用 UTF-8，`version` 固定为 `1`，其余内容由本次图决定。命令的输入/输出路径相对于调用者当前目录；工具不读取外部项目文件。

## 顶层字段

| 字段 | 用途 |
| --- | --- |
| `title` / `subtitle` | 主标题与可选副标题，任意语言；默认标题区位于左上 |
| `canvas` | `width`、`height`、`background`；默认 1200×900、白底 |
| `style` | 全局字体/几何/文字样式；`interchange_style`、`interchange_radius`、`reserved_color`、`structure_patterns` 详见 [样式规则](style-rules.md) |
| `stations` | 站点/节点数组，必填；名称不限语言 |
| `routes` | 线路数组，必填；一个线路可以包含多个区段形成支线或分段样式 |
| `regions` | 可选背景多边形数组，每项 `points` 至少三个坐标、`fill` 为颜色；不从地名自动生成地理轮廓 |
| `legend` | 可选图例：`point` 为左上坐标、`width`、`title`；每条线路自动占一行，`items` 可追加结构与站点符号；省略则不绘图例 |
| `annotations` | 可选任意说明文字：`point`、`text`，可选 `size` 和 `anchor`；可用于区域名、来源或版权 |

颜色接受 `#RGB`、`#RRGGBB` 或 CSS 颜色名。坐标都是 `[x, y]`，从画布左上起向右/向下增加；必须是有限数值。字体必须在渲染环境中存在，否则会回退。标题不自动换行，图例宽度和标签位置需要按文字长度安排。

## 站点与身份

```json
{
  "id": "central",
  "name": "中央广场",
  "secondary_name": "Central Square",
  "point": [390, 310],
  "label": { "offset": [20, -28], "anchor": "start" }
}
```

`id`、`name`、`point` 必填。`secondary_name` 可省略，不要求双语，也不自动翻译。`label.offset` 相对于站点坐标，`anchor` 为 `start/middle/end`；默认 `[14,-12]`、`start`。可用 `radius` 覆盖站点符号半径。

多条线路引用同一站点 ID，会在同一圆心绘制对应线路色的换乘箭头，也可配置为换乘环；同一线路的多条支线引用该 ID 不重复计为多线换乘。`transfer_order` 可指定颜色方位，`status` 可标记 `open/reserved/unopened`，具体见 [样式规则](style-rules.md)。不同 ID 即使同名或同坐标也不会合并。过站但不停车/不换乘的线路应使用坐标经过该位置，而不是引用该站点 ID；这只是绘图约定，不代表列车运营模型。

## 线路、支线与环线

```json
{
  "id": "line-a",
  "name": "A 线",
  "color": "#D8443C",
  "mode": "tram",
  "pattern": "solid",
  "segments": [
    { "points": ["west", "central", "east"] },
    { "points": ["central", [390,440], [650,440], "harbor"], "pattern": "dashed" }
  ]
}
```

线路必填 `id`、`name`、`segments`；建议显式提供 `color`。`mode` 是自由文本元数据，地铁、公交、轮渡或其他网络均可，不触发任何专属规则。`width` 和 `corner_radius` 可覆盖全局值。

`points` 的字符串是站点 ID，数组是仅改变路径走向的控制点；每段至少两个点，相邻点不可重合。每段可独立指定 `pattern`，否则继承线路的样式。多个区段的同名端点构成分支；非站点分岔也可用共用坐标连接，不必虚构车站。

区段加上 `"closed": true` 自动连接终点与起点，至少需要三个不同位置。闭环的起点应放在站点或允许折角的位置，因为起点处不自动圆角；其他坐标控制点会圆角，站点位置保持精确，必要时在站点前后增加控制点。

样式：`solid` 为实线，`hollow` 为同一路径叠加窄内芯，`dashed` 为虚线。线路和区段均可指定 `structure`：默认 `underground` 用实线、`surface/elevated` 用空心线；映射可在全局或线路的 `structure_patterns` 中覆盖，区段显式 `pattern` 优先。没有 `structure` 时不推断敷设方式，沿用线路样式。空心线内芯默认白色，可用 `hollow_fill` 调整；不是透明挖空。完整优先级和转换示例见 [样式规则](style-rules.md)。

自动图例显示每条线路的默认样式。混合结构区段须用 `legend.items` 追加结构线型说明，站点与换乘符号也可在该列表加入，避免图例遗漏真实使用的符号。

## 能力边界

此格式支持示意网络的常用骨架，坐标、站名、线宽及标签偏移彼此独立。工具不会自动分开平行重叠线路、推断换乘、选择最优布局、测量标签碰撞、处理真实 GIS 投影或推演车辆。并行线路应由输入安排各自路径；大规模密集线网需要分区布局和多轮视觉调整。

生成 SVG 包含 `regions/routes/stations/labels/heading/legend/annotations` 等分组（图例可省略），文字保留为 `<text>`。临时在矢量编辑器里调整后，应回写 JSON 或生成器再生成，确保后续可复现。
