# 独立绘图数据格式

本页描述最终绘图 JSON。可以先用[来源导入流程](import-guide.md)从 GTFS、站序 CSV 或拓扑自动生成它，再精修；不必手工逐站填写。工具没有内置城市数据库；随包示例均为虚构数据。JSON 采用 UTF-8，`version` 固定为 `1`，其余内容由本次图决定。命令的输入/输出路径相对于调用者当前目录；工具不读取外部项目文件。

## 顶层字段

| 字段 | 用途 |
| --- | --- |
| `title` / `subtitle` | 主标题与可选副标题，任意语言；默认标题区位于左上 |
| `canvas` | `width`、`height`、`background`；默认 1200×900、白底 |
| `style` | 全局字体/几何/文字样式；`interchange_style`、`interchange_radius`、`reserved_color`、`structure_patterns` 详见 [样式规则](style-rules.md) |
| `stations` | 站点/节点数组，必填；名称不限语言 |
| `routes` | 线路数组，必填；一个线路可以包含多个区段形成支线或分段样式 |
| `basemap` | 可选的分层底图，契约见 [底图指南](basemap-guide.md)；支持行政区、陆地/岛屿、水域/河流、曲线/孔洞、裁切和独立标签 |
| `regions` | 可选背景多边形数组，每项 `points` 至少三个坐标、`fill` 为颜色；不从地名自动生成地理轮廓 |
| `legend` | 可选图例：`point` 为左上坐标、`width`、`title`；每条线路自动占一行，`items` 可追加结构与站点符号；省略则不绘图例 |
| `source_metadata` | 可选来源记录，由前置生成器保留；不自动改变绘图，署名可另写 `annotations` |
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

区段可选 `station_offsets: {"central": [0, 9]}`：只偏移此区段在该站的线路路径，符号、标签、身份与换乘保持在原站心。字符串引用仍决定线路与车站的关联，实际线路坐标为站心加偏移；用于连续平行车道，不要在每个站间先偏移再返回中心。键必须是本段 `points` 引用的站 ID，值必须为有限坐标；缺省/空对象保持旧图不变。坐标控制点使用绝对位置，不跟随该偏移。复制自动生成区段作路径覆盖时，应连同此字段保留，并检查弯道及分岔的连续性。

`points` 的字符串是站点 ID，数组是仅改变路径走向的控制点；每段至少两个点，相邻点不可重合。每段可独立指定 `pattern`，否则继承线路的样式。多个区段的同名端点构成分支；非站点分岔也可用共用坐标连接，不必虚构车站。

区段加上 `"closed": true` 自动连接终点与起点，至少需要三个不同位置。闭环的起点应放在站点或允许折角的位置，因为起点处不自动圆角；其他坐标控制点会圆角，站点位置保持精确，必要时在站点前后增加控制点。

样式：`solid` 为实线，`hollow` 为同一路径叠加窄内芯，`dashed` 为虚线。线路和区段均可指定 `structure`：默认 `underground` 用实线、`surface/elevated` 用空心线；映射可在全局或线路的 `structure_patterns` 中覆盖，区段显式 `pattern` 优先。没有 `structure` 时不推断敷设方式，沿用线路样式。空心线内芯默认白色，可用 `hollow_fill` 调整；不是透明挖空。完整优先级和转换示例见 [样式规则](style-rules.md)。

自动图例显示每条线路的默认样式。混合结构区段须用 `legend.items` 追加结构线型说明，站点与换乘符号也可在该列表加入，避免图例遗漏真实使用的符号。

## 能力边界

此格式支持示意网络的常用骨架，坐标、站名、线宽及标签偏移彼此独立。`draw_map.py` 只按输入渲染，不选择布局或推断换乘。前置 `create_map.py` 构造水平、垂直或 45° 的走廊骨架，沿走廊均匀布站并安排连续共线车道；报告中的模式映射说明哪些源停站模式复用显示路径，原始模式仍保存在 `topology.json`。生成器估算文字冲突，但不测实际字体、不使用轨道真实几何，也不求解全网最优布局或推演车辆。复杂枢纽、短转角与密集标签仍需检查渲染图并修订，大规模线网可能需要分区布局。

生成 SVG 包含 `regions/routes/stations/labels/heading/legend/annotations` 等分组（图例可省略），文字保留为 `<text>`。临时在矢量编辑器里调整后，应回写 JSON 或生成器再生成，确保后续可复现。

原生 `.ai` 工程导出已转入[后续改进计划](roadmap.md)，不改变本次 JSON、SVG 和 PNG 的数据约定。
