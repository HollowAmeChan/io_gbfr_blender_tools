# MOT 动画制作与编辑

本文档面向 GBFR 的骨骼动画制作，当前优先目标是 `fpXXXX` 面部模型的表情 MOT。现有插件已经可以索引和预览 MOT，但还没有把 MOT 转换为 Blender Action，也不能写回 MOT。下文先说明当前可安全进行的骨架整理，再定义第一版编辑器的工作方式。

## 制作前整理面部骨骼

面部骨骼通常数量多、显示较长，遮挡模型后不便选择。可以在 Blender 编辑模式中缩短骨骼，但只能改变显示长度：

- 保持 `head` 完全不动。
- `tail` 必须沿原来的 `head -> tail` 方向缩短，不能改变方向或越过 `head`。
- 不要修改 Bone Roll、父子关系或骨骼名称。
- 不要启用 Connected 后再缩短父骨，避免连带移动子骨的 `head`。插件导入的原骨默认不连接。

GBFR `.skeleton` 不保存 tail 或骨长，只保存父级、局部位置、四元数和缩放。插件导入时给骨骼设置的长度是 Blender 显示长度；沿原方向缩短不会改变 `bone.matrix_local`，也不会改变模型导出的骨骼位置和旋转。`fpXXXX` 联合导出还会原样保留 source skeleton。

在骨架编辑模式中选择需要缩短的骨骼，可以在 Blender Python Console 执行：

```python
import bpy

for bone in bpy.context.object.data.edit_bones:
    if bone.select:
        bone.tail = bone.head + (bone.tail - bone.head) * 0.25
```

这会把所选骨骼缩短到 25%。不要选择整根骨后围绕公共中心缩放，因为那可能同时移动 `head`。

## 当前 MOT 预览能力

导入面部模型 `.minfo` 后，`GBFR > MOT 动画` 会索引 `source/data/fp/fpXXXX` 或 `unpack/data/fp/fpXXXX` 中的同模型 MOT。点击列表条目后，插件按 60 FPS 在内存中采样，并直接更新 PoseBone `matrix_basis`。

当前限制：

- 预览不会创建 Action、关键帧、Animation Slot 或 NLA Track。
- 在预览状态下手工插入的 Pose 关键帧不是当前 MOT 的可写回副本。
- “停止并恢复静止姿态”会清除内存剪辑并恢复 rest pose。
- 模型的“导出到工作区”不会修改或导出 MOT。

因此，在编辑功能完成前，只能把现有 MOT 当作只读动作参考。

## 已确认的 MOT 通道

每条 MOT 轨道只保存一个骨号的一个轴向属性。当前解析器的属性映射如下：

| 属性 | 含义 | Blender 编辑目标 |
| --- | --- | --- |
| `0`、`1`、`2` | 局部位置 X、Y、Z | PoseBone Location |
| `3`、`4`、`5` | 局部 XYZ 欧拉旋转 | PoseBone Rotation |
| `6` | 尚未确认 | 第一版拒绝写回 |
| `7`、`8`、`9` | 局部缩放 X、Y、Z | PoseBone Scale |

解析器已经支持压缩类型 `0-8`：

- `0/-1`：常量。
- `1-3`：逐帧线性曲线，分别使用 float、u16 和 u8 数据。
- `4-8`：稀疏 Hermite 曲线及其量化变体。

对本机 `fp1400` 的 80 个表情 MOT 统计结果：

- 全部文件版本为 `0x20200619`，flags 和头部 unknown 均为 `0`。
- 只出现属性 `0-5/7-9`，没有属性 `6`。
- 压缩类型 `0-8` 全部实际存在。
- 每个文件包含 24-98 根骨、216-874 条轨道，帧数为 2-1071。
- 没有负骨号，也没有重复的“骨号 + 属性”轨道。
- 轨道 unknown 出现 `0` 和 `1`，写回时必须保留，不能统一重置。

这些结论是当前角色资源的实测范围，不代表所有角色和所有 MOT 的完整契约。

## 第一版编辑工作流

第一版采用“以现有 MOT 为模板”的方式，不直接提供空白 MOT 创建功能：

1. 在 `MOT 动画` 列表中选择一个接近目标表情的 MOT。
2. 点击“载入为可编辑 Action”。插件停止只读预览，只为当前 MOT 创建一个 Action。
3. 场景切到 60 FPS，时间范围设为 `0` 到 `frame_count - 1`。
4. 用户进入 Pose Mode，选择面部骨骼，通过普通 Location、Rotation、Scale 和关键帧编辑表情。
5. 点击“验证 MOT”，检查骨号、轨道、非有限值、旋转连续性和目标路径。
6. 点击“导出当前 MOT 到工作区”，写入对应的 `unpack/data/fp/fpXXXX/<原文件名>.mot`。
7. GBFR Modtools 再负责把确认后的文件封装到 build，source 原文件始终不覆盖。

一个会话可以有多个 MOT Action，但同一时间只允许一个 Action 作为当前 MOT 编辑目标。第一版不使用 NLA 混合，避免用户误把多个表情叠加后写进单个文件。

## Action 与 MOT 的转换

MOT 保存的是相对父骨的绝对局部变换，Blender Action 编辑的是相对 rest pose 的 PoseBone 变换。两者不能直接复制数值。

载入 Action 时，每一帧执行：

```text
MOT 位置/欧拉旋转/缩放
    -> animated_local_matrix
    -> inverse(rest_local_matrix) @ animated_local_matrix
    -> PoseBone location/rotation/scale
```

导出 MOT 时执行反向转换：

```text
rest_local_matrix @ pose_basis_matrix
    -> MOT 位置/XYZ 欧拉旋转/缩放
```

第一版将当前模板涉及的骨骼逐帧烘焙到 Action。原因是 rest 旋转参与矩阵换算后，MOT 单轴 Hermite 曲线通常不能无损地直接映射为 Blender 的单轴 F-Curve。逐帧烘焙更占内存，但能保证 Blender 中看到的每个整数帧与现有预览一致。

导出时也按整数帧采样：

- 整段不变的轨道写为常量压缩 `0`。
- 发生变化的轨道先写为逐帧 float 压缩 `1`。
- 第一版优先正确性和可验证性，不立即重新量化为 `2-8`。
- XYZ 欧拉旋转按上一帧选择最近的等价角，防止跨越正负 π 时产生整圈跳变。

## 必须保留的模板数据

第一版写回时必须继承原 MOT：

- version、flags、frame count、内部名称和头部 unknown。
- 原轨道顺序、骨号、属性和每条轨道的 unknown。
- 当前 Action 未编辑的骨骼和通道。

第一版不允许增加或删除轨道，也不允许改变目标骨号。这样可以先绕开未知轨道标志和不同角色通道集合的风险。用户可以让原常量轨道变为动画轨道，但不能给模板中不存在的骨骼新增 MOT 通道。

若模板出现以下情况，导出必须停止并明确报告：

- 属性 `6` 或解析器尚不支持的属性。
- 负骨号，或骨号无法解析为当前真实 Blender 骨骼。
- 同一骨号和属性出现重复轨道。
- Action 帧范围超过 MOT 能表示的范围。
- NaN、Infinity、无法分解的变换矩阵或无法连续展开的旋转。

## 界面设计

`GBFR > MOT 动画` 面板分为两个标签：

- `浏览`：保留当前列表、搜索、只读预览和播放控制。
- `编辑`：显示当前 Action、源 MOT、目标 unpack 路径、帧数、修改状态和验证结果。

编辑标签提供以下命令：

- “载入为可编辑 Action”：从浏览列表创建或激活对应 Action。
- “恢复模板”：丢弃当前 Action 修改并重新烘焙，执行前要求确认。
- “验证 MOT”：只读检查，不写文件。
- “导出当前 MOT 到工作区”：验证通过后原子替换 unpack MOT。
- “在资源管理器中定位”：定位输出文件，不改变数据。

Action 保存这些自定义元数据：source MOT 路径、目标 MOT 路径、模型 ID、头部字段、模板摘要和导入插件版本。重新打开 `.blend` 后必须能恢复编辑上下文，不能只依赖内存缓存。

## 写回与验证要求

MOT 写出必须先生成临时文件，再重新解析并验证，最后原子替换目标文件。失败时保留原 unpack MOT。

自动测试至少覆盖：

1. 原 MOT 载入 Action 后，每个整数帧的 Pose 矩阵与当前只读预览一致。
2. 未编辑 Action 写回后，重新解析的每条轨道在每个整数帧与原文件误差小于规定阈值。
3. 编辑单根面部骨后，只有该骨相关输出轨道的采样值发生变化。
4. version、flags、内部名称、头部 unknown、轨道顺序和轨道 unknown 保持不变。
5. source MOT 永不写入，输出只落到 workspace 的 unpack 路径。
6. Blender 关闭重开后，Action 元数据仍能正确定位模板和输出。

## 实施顺序

### 阶段一：面部模板编辑

- 增加 MOT 写出器，支持常量 `0` 和逐帧 float `1`。
- 把单个选中 MOT 烘焙为 Action。
- 实现 Action 反向采样、验证和 unpack 原子写出。
- 用 `fp1400` 表情做未修改往返测试和首轮游戏实机测试。

### 阶段二：稀疏曲线与体积优化

- 对没有变化的逐帧区间做关键帧精简。
- 精确转换 Hermite 切线，并按误差预算选择 `2-8` 量化压缩。
- 提供输出大小和最大采样误差报告。

### 阶段三：新建动作与身体 MOT

- 允许从空白 Action 新建轨道和选择目标骨骼。
- 研究属性 `6`、负骨号和不同版本头部字段。
- 支持身体 MOT、根运动以及动作事件等尚未确认的数据。

在阶段一完成并通过游戏测试前，不把 Blender Action 导出描述为通用 MOT 制作器。
