# 通用线网图绘制 Skill

**厦门地铁线网图风格的地铁线网图绘制 skill**

为不同城市、不同交通方式绘制可编辑的线网示意图。可从站点/线路数据、参考图片或已有 SVG 开始，适用于地铁、公交、有轨电车、市域铁路、轮渡和混合网络，也可用于结构相似的节点连线图。

以厦门地铁线网图的圆角线路、清晰换乘和中英文标注为视觉参考，也支持用户指定的其他风格。城市名称、站数、颜色、语言、线型和图例语义均由输入决定，不依赖任何城市项目或专项校验。

![换乘与地上地下段样式示例](assets/previews/metro-style.png)

## 已包含的地铁制图风格

| 元素 | 默认表现 |
| --- | --- |
| 普通站 | 白底、线路色圆形描边 |
| 两线换乘 | 上下两段独立的双色半环箭头 |
| 三线换乘 | 三个独立箭头按 0°/120°/240°分布，颜色方位可指定 |
| 预留/未开放站 | 灰色虚线节点或灰色换乘箭头，站名降低显著度 |
| 地下段 | 线路色实心线 |
| 地面/高架段 | 同一路径叠加白色内芯形成空心线，保留圆角和圆头 |
| 站间结构转换 | 相邻区段共用边界坐标，不增加车站 |
| 图例 | 可加入结构线型、普通站、两线/三线换乘和预留站 |

这些是可覆盖的默认约定。可以改用多色换乘环，或者为目标网络调整地面/高架线型；不依据交通类型自动猜测敷设方式和开通状态。字段、颜色方位及完整示例见[样式规则](references/style-rules.md)。

```bash
python3 scripts/draw_map.py assets/metro-style-network.json --output output/metro-style.svg
python3 scripts/export_png.py output/metro-style.svg output/metro-style.png --scale 1.5
```

## 安装与调用

将整个仓库作为一个 skill 文件夹使用，保留 `SKILL.md`、`agents`、`scripts`、`references`、`assets` 的相对位置。

项目内安装，在目标项目根目录执行：

```bash
git clone https://github.com/BG2FOU/draw-system-map-skill.git .agents/skills/draw-system-map
```

个人安装可将同一文件夹放入 `~/.codex/skills/draw-system-map`；若设置了 `CODEX_HOME`，则使用其下的 `skills/draw-system-map`。目标目录已有内容时先核对，不覆盖已有 skill。客户端未显示新条目时，在目标项目开启新会话，或提供 `SKILL.md` 的路径。

直接向 Agent 发送：

```text
使用 $draw-system-map，根据我提供的站序和参考图，绘制这座城市的轨道交通线网图。
保留原名称和指定配色，区分换乘与普通交叉，交付可编辑 SVG、源数据和 PNG。
```

其他示例：

```text
使用 $draw-system-map 绘制公交干线与有轨电车的混合网络。
单语言标注，使用我给定的色值，环线和支线按数据连接，不套用其他城市的标准。
```

```text
使用 $draw-system-map 重绘这张参考图，保持所有可确认的站名和连接。
看不清的部分列为待确认，不自行补译。保持文字和线路可编辑。
```

如需分阶段提交推送，明确加上“每完成一个可独立验收的阶段，提交并推送当前任务分支”。未提出远端操作时，skill 不自动发布或创建 PR。

## 不使用 Agent 也能运行

SVG 生成仅依赖 **Python 3.10+ 标准库**。以下命令在此文件所在目录运行；也可用脚本的绝对路径从任意目录调用。Windows 如没有 `python3` 命令，可换为 `python`。

```bash
# 先运行随包附带的虚构数据，查看结果
python3 scripts/draw_map.py assets/minimal-network.json --output output/network.svg

# 可选：确认已有 SVG 与输入一致，不写文件
python3 scripts/draw_map.py assets/minimal-network.json --output output/network.svg --check

# 可选：导出 PNG，默认 2 倍像素
python3 scripts/export_png.py output/network.svg output/network.png --scale 2
```

创建自己的图时，复制 `assets/minimal-network.json` 为 `network.json`，填入真实输入，再运行：

```bash
python3 scripts/draw_map.py network.json --output output/network.svg
python3 scripts/export_png.py output/network.svg output/network.png --scale 2
```

PNG 导出需要以下任一环境：系统 PyGObject + librsvg/Pango，或 CairoSVG + 系统 Cairo。`--renderer auto` 默认优先使用 librsvg；可显式传 `--renderer librsvg` 或 `--renderer cairosvg`。CairoSVG 可通过 Python 环境安装 `cairosvg`，某些系统仍需单独安装 Cairo。没有这些依赖时 SVG 仍可生成并在浏览器/矢量编辑器中打开。

文字使用实际系统字体；中文示例优先使用 Noto Sans CJK SC，英文示例使用 DejaVu Sans。可以在数据中更换字体，换后重新查看排版。

## 输入数据怎么写

完整字段说明见 [数据格式](references/data-format.md)。最重要的概念：

| 内容 | 表达方式 |
| --- | --- |
| 站点/节点 | 唯一 `id`、`name`、`point: [x,y]`，可选第二语言 |
| 线路 | 名称、颜色、若干 `segments`；不限定交通类型 |
| 一段路径 | `points` 中的字符串引用站点 ID，坐标数组是转弯控制点 |
| 换乘 | 共用站点 ID；`transfer_order` 指定箭头颜色方位；几何交叉不自动合并 |
| 支线 | 同一线路增加多个区段；非站点分岔用共用坐标连接 |
| 环线 | 区段设置 `closed: true`；起点选站点或允许折角的位置 |
| 线型 | `solid`、`hollow`、`dashed`，语义自行定义 |
| 敷设方式 | 线路/区段 `structure`；地下默认实心、地面/高架默认空心，可覆盖映射 |
| 预留/未开放站 | 站点 `status: "reserved"` 或 `"unopened"`，不自动改变相邻轨道 |
| 标签 | 用站点 `label.offset` 和 `anchor` 调整，不移动站点身份 |
| 背景与说明 | `regions` 多边形与 `annotations` 文字 |

布局方法见 [绘图指南](references/drawing-guide.md)。生成器会把转弯控制点圆角化，保持站点坐标精确；不会自动计算全网最优坐标、分离重叠线路或解决文字碰撞。复杂风格可以扩展生成器或继续使用已有项目的绘图实现。

## 支线、环线与混合网络示例

```bash
python3 scripts/draw_map.py assets/multimodal-network.json --output output/multimodal.svg
python3 scripts/export_png.py output/multimodal.svg output/multimodal.png --scale 1.5
```

![混合网络示例](assets/previews/multimodal.png)

这份虚构数据同时包含铁路支线、接驳环线、轮渡、实线/空心线/虚线、单语言标签与背景区域。示例只演示结构，不规定任何真实交通类型的画法。

## 输出、修改与基本检查

SVG 保留线路路径、站点、换乘箭头/环和 `<text>` 文字，并按图层分组。用矢量编辑器查看或编辑都可以；希望修改在以后重生成时保留，需要回写 JSON 或生成器。PNG 是预览和分享格式，不替代源文件。

工具只拒绝重复 ID、不存在的站点引用、非有限坐标等无效数据。`--check` 仅检查输入与 SVG 是否一致，不证明布局无冲突。交付前查看全图与密集区域，确认站序/连接正确、文字可读、没有缺字、遮挡、压线、裁切或标签错认。

工具自身的可移植性测试：

```bash
python3 -m unittest discover -s tests -v
```

测试不含任何城市固定站数或交通类型规格。9 项标准库测试覆盖 Unicode/XML 转义、分支与换乘身份、双色/三色箭头与颜色方位、预留站、结构区段与覆盖映射、闭环与线型、圆角端点、无效数据、任意目录调用及只读一致性检查；另有 1 项可选 librsvg 像素回归，检查转换处不随区段顺序和路径方向改变，没有 PyGObject/librsvg 时跳过。本次 Linux 环境 10 项均通过，并使用 librsvg 导出、查看三份示例；不将这等同于已完成所有操作系统和 CairoSVG 渲染器验收。

## 常见问题

- **没有原始坐标：** Agent 可以依据站序和参考图安排示意坐标；自动转换经纬度与自动布局求解不在当前工具内。
- **同名站不该换乘：** 使用不同 ID；需要合并时由来源明确为同一节点后共享 ID。
- **图面重叠：** 修改路径控制点、站点位置、标签偏移或画布留白，再生成并查看；不要依赖 `--check` 发现视觉问题。
- **中文缺字或字体变化：** 安装/指定合适字体，再重新导出。
- **PNG 提示无渲染器：** 安装可选渲染依赖，或先使用可编辑 SVG。
- **修改 SVG 后又被覆盖：** 把调整写入数据/生成器，而不是只改派生产物。
- **需要特殊图例、箭头或图标：** 沿用已有项目或扩展可编辑 SVG 分组，不把整个图转换为图片。
