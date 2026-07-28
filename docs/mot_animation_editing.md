# MOT 动画制作与编辑

本文档面向 GBFR 的骨骼动画制作，当前优先目标是 `fpXXXX` 面部模型的表情 MOT。插件可以按需把多条 MOT 转换为 Blender Action，使用单层 NLA Edit 修改，并逐条写回 unpack。下文先说明可安全进行的骨架整理，再说明第一版编辑器的工作方式和边界。

## 制作前整理面部骨骼

面部骨骼通常数量多、显示较长，遮挡模型后不便选择。可以在 Blender 编辑模式中缩短骨骼，但只能改变显示长度：

- 保持 `head` 完全不动。
- `tail` 必须沿原来的 `head -> tail` 方向缩短，不能改变方向或越过 `head`。
- 不要修改 Bone Roll、父子关系或骨骼名称。
- 不要启用 Connected 后再缩短父骨，避免连带移动子骨的 `head`。插件导入的原骨默认不连接。

GBFR `.skeleton` 不保存 tail 或骨长，只保存父级、局部位置、四元数和缩放。插件导入时给骨骼设置的长度是 Blender 显示长度；沿原方向缩短不会改变 `bone.matrix_local`，也不会改变模型导出的骨骼位置和旋转。移动 `head`、改变骨骼方向或 Bone Roll 则会改变 rest transform；模型导出会把当前 Blender rest 位置和旋转写入 `.skeleton`。`fpXXXX` 与身体使用同一重建规则：source 只锁定既有骨号、顺序以及 Blender 中缺失的占位骨槽，不会覆盖 Blender 中已经存在的脸骨变换。

在骨架编辑模式中选择需要缩短的骨骼，可以在 Blender Python Console 执行：

```python
import bpy

for bone in bpy.context.object.data.edit_bones:
    if bone.select:
        bone.tail = bone.head + (bone.tail - bone.head) * 0.25
```

这会把所选骨骼缩短到 25%。不要选择整根骨后围绕公共中心缩放，因为那可能同时移动 `head`。

## MOT 预览与 Action 编辑

导入面部模型 `.minfo` 后，`GBFR > MOT 动画` 会优先读取当前会话 `workspace.json/AnimationFiles` 中 `ModelId` 完全一致的 MOT。旧工作区没有 `AnimationFiles` 时才兼容扫描 `source/data/fp/fpXXXX` 与 `unpack/data/fp/fpXXXX`。普通列表播放使用 `source MOT + source skeleton`；“预览导出 MOT”使用 `unpack MOT + unpack skeleton`。两种模式最后都把各自游戏局部姿态映射到当前 Blender rest，因此不能混用另一侧的 skeleton offset。

源文件预览仍有以下限制：

- 预览不会创建 Action、关键帧、Animation Slot 或 NLA Track。
- 在直接预览状态下手工插入的 Pose 关键帧不是当前 MOT 的可写回副本；需要先点击该行的“导入 Action”。
- “停止并恢复静止姿态”会清除内存剪辑并恢复 rest pose。
- 模型的“导出到工作区”不会修改或导出 MOT。

MOT 直接预览与 Action 编辑保持会话级互斥。当前会话没有任何已导入 Action 时，列表下方播放 source MOT；一旦导入第一个 Action，插件立即停止直接预览、清除内存剪辑并恢复静止姿态。只要会话仍保留任意 MOT Action，播放按钮就只驱动 Blender 时间轴和当前 Action/NLA，不能再次让帧回调直接覆盖 `matrix_basis`。删除会话中的全部 MOT Action 后，source 直接预览才重新启用。

已导出到 unpack 的动画会额外显示“预览导出 MOT”。这是上述互斥规则的显式验证模式：插件临时解除当前 Action/NLA，重新解析磁盘上的 unpack `.mot` 并直接预览实际写出结果；“返回 Action”会恢复原编辑栈。该模式不会删除或重新烘焙 Action，也不会把普通源 MOT 播放重新启用。

“导回 Action”会用 `unpack MOT + unpack skeleton` 重新逐帧烘焙 Base Action。普通列表预览与首次导入 Action 仍以 `source MOT + source skeleton` 为基线；两者是有意保留的双模式，不得仅替换 MOT 路径而沿用另一侧 rest。

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
2. 点击该行的“导入 Action”。插件停止只读预览，并为该 MOT 创建 Base Action。
3. 场景切到 60 FPS，时间范围设为 `0` 到 `frame_count - 1`。
4. 用户进入 Pose Mode，选择面部骨骼，通过普通 Location、Rotation、Scale 和关键帧编辑表情。
5. 点击“验证 MOT”，检查骨号、轨道、非有限值、旋转连续性和目标路径。
6. 点击该行的“导出到 unpack”，只写出这一条动画到当前会话工作区 `AnimationFiles` 登记的 `Input`；旧工作区则使用兼容计算出的 `unpack/data/fp/fpXXXX/<原文件名>.mot`。
7. GBFR Modtools 再负责把确认后的文件封装到 build，source 原文件始终不覆盖。

列表始终显示工作区登记的全部 MOT，但不一次性烘焙全部动作。用户可以逐行导入任意多个动画；所有已导入的 Action 同时保存在 `.blend`，无需重新解析即可来回切换。一个 Armature 同一时间只绑定一条动画作为当前编辑目标，其他 Action 保持未绑定状态，不参与求值。

### 文件名推测注释

动画列表会按已知文件名后缀显示带问号的推测注释，并允许用注释文本筛选。这些描述只帮助查找模板，不写入 MOT，也不视为已确认的游戏格式语义：

| 后缀 | 推测 |
| --- | --- |
| `030a` | 闭左眼 |
| `031a` | 紧张闭眼 |
| `032a` | 闭右眼 |
| `034a` | 闭眼 |
| `035a` | 紧闭眼 |
| `036a` | 舒张闭眼 |
| `c50b-c84b` | 口型 |
| `e00a` | 闭眼笑 |

每个动画资产保存独立状态：

```text
MOT 动画资产
    source MOT 路径
    unpack MOT 路径
    Base Action
    可选 Edit Action
    验证 / 导出状态
```

切换动画时，插件先保存当前 Base/Edit 关联，再解除当前 NLA Stack，最后绑定目标动画及其帧范围。切换不会删除其他动画的 Action 或编辑层。

## Action 与 MOT 的转换

MOT 保存的是相对父骨的绝对局部变换，Blender Action 编辑的是相对 rest pose 的 PoseBone 变换。两者不能直接复制数值。source/unpack 模式分别读取同区域 skeleton 作为 MOT 缺轨静止值；Blender 当前骨架只作为显示和编辑坐标系。

MOT 面板常驻提醒：修改 Blender rest 后，应先执行模型“导出到工作区”，再编辑或导出动画，使 `unpack .skeleton` 与 MOT 使用同一基准。该提醒不锁定 Action 的导入、编辑、验证、导出或回导；基准是否正确由用户当前工作流负责。

载入 Action 时，每一帧先执行：

```text
MOT 位置/欧拉旋转/缩放
    -> animated_local_matrix
    -> inverse(rest_local_matrix) @ animated_local_matrix
    -> 最接近的 PoseBone location/rotation/scale（TRS 投影）
```

某些源骨的非均匀缩放与旋转组合会让 `inverse(rest) @ animated` 带有剪切分量。Blender 普通 Action 只有 Location、Rotation、Scale，不能逐项表示剪切矩阵。插件会记录精确源矩阵，Action 只显示可编辑的最近 TRS 投影；导出时计算“当前 Action 相对原 TRS 投影的修改量”，再把该修改量叠加到精确源矩阵：

```text
exact_source_basis @ inverse(source_trs_projection) @ edited_pose_basis
    -> rest_local_matrix @ corrected_basis
    -> MOT 位置/XYZ 欧拉旋转/缩放
```

这样未修改 Action 写回时不会把 Blender TRS 投影误差污染到 MOT；用户修改则以相对差值写回。验证状态会分别显示 Action 对 TRS 投影的误差和源矩阵本身的 TRS 投影误差。后者不等于 Action 损坏。

第一版将当前模板涉及的骨骼逐帧烘焙到 Action。原因是 rest 旋转参与矩阵换算后，MOT 单轴 Hermite 曲线通常不能无损地直接映射为 Blender 的单轴 F-Curve。逐帧烘焙更占内存，但能保证除上述不可表达剪切外，Blender 中的每个整数帧与所选 source/unpack 模式一致，并保证未编辑文件的 MOT 采样往返一致。

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

### 骨名、骨号与新增轨道的已知风险边界

MOT 二进制轨道不保存 Blender 骨名。当前实现用“骨号 + 属性”识别轨道；导入骨架时保存在骨上的 `gbfr_bone_id` 才是 MOT 目标身份。Blender 当前骨名只用于 Action 的 `pose.bones["骨名"]` 曲线路径和镜像编辑。因此，把源骨改成便于镜像的语义名不会改变 MOT 目标，前提是该骨仍保留原来的 `gbfr_bone_id`。source/unpack rest 直接读取对应 `.skeleton`，`gbfr_original_name` 用于模型和名称往返。

当前支持边界如下：

| 情况 | 当前行为 |
| --- | --- |
| 源 skeleton 中已有骨，语义化改名后元数据仍在，且模板已有该骨所需轨道 | 支持编辑和写回；建议先完成改名，再导入 Action |
| 骨存在于当前 skeleton，但所选 MOT 模板没有该骨或属性的轨道 | Blender 中可以打关键帧，但导出器不会创建新轨道，游戏文件中该修改不会出现 |
| MOT 模板有轨道，但当前 Blender 骨架缺少对应骨或 rest 元数据 | 该轨道不进入 Action，导出时按源 MOT 原样透传，不能编辑 |
| 用户后来新增的骨不属于源 skeleton，或只有模型导出阶段分配的临时骨号 | 当前不支持 MOT 写回；没有稳定的骨号、rest 数据和模板轨道契约 |

不要通过复制 `gbfr_bone_id` 让新增骨冒充已有骨。重复骨号目前没有合法语义，可能令现有 MOT 轨道绑定到错误的 PoseBone。删除并重建骨、清除骨自定义属性、在导入 Action 后批量改名，也都必须重新验证 Action 的曲线路径和上述元数据；仅看到 Blender 中动画能播放，不能证明该通道会进入 MOT。

以后若要支持“修改模板里没有的骨”，应增加显式的“新增 MOT 轨道”流程：只允许从当前 workspace 的源 skeleton 选择已有稳定骨号，逐项选择位置、旋转或缩放属性，并明确生成轨道顺序、unknown 和初始采样。不能从任意 Action F-Curve 自动猜测这些二进制字段。真正新增到模型的骨还需要先建立跨模型导出与 MOT 导出的稳定骨号契约；在此之前，它属于已知的不支持范围。

模板引用了当前 Blender 骨架没有的骨，或出现尚不能映射到 PoseBone TRS 的属性时，插件不会再像旧预览那样静默丢弃，也不会因为一个非变形 dummy 拒绝整条动画。这些轨道不会进入 Action，界面会报告数量，导出时按源 MOT 的每个整数帧原样透传。`fp1400` 的 `_8d0` 就是已知的近零缩放非变形 dummy；它保留在参考 skeleton 和部分 MOT 中，但有意不创建为 Blender 骨。

若模板出现以下情况，导出必须停止并明确报告：

- 同一骨号和属性出现重复轨道。
- Action 帧范围超过 MOT 能表示的范围。
- NaN、Infinity、无法分解的变换矩阵或无法连续展开的旋转。

## 界面设计

MOT 列表的每行显示文件名、帧数、轨道数和状态，并只放置资产级命令：

- 未导入时显示“导入 Action”。
- 已导入但未激活时显示“切换到此 Action”。
- 当前编辑动画显示高亮状态，不重复放播放按钮。
- 已导入动画显示“导出到 unpack”和“移除 Action”。

播放、暂停、回到首帧和停止继续共用列表下方的现有控制区。没有已导入 Action 时，这些按钮驱动源 MOT 预览；存在任意已导入 Action 时，源预览按钮禁用，控制区只调用 Blender 时间轴播放当前 Action/NLA，并显示“已有可编辑 Action，源 MOT 直接预览已禁用”。

面板另提供当前动画级命令：

- “验证 MOT”：只读检查，不写文件。
- “添加编辑层”：为当前动画创建唯一一条 Edit Action。
- “合并编辑层”：逐帧烘焙 Base + Edit 为新的 Base Action，成功后移除 Edit。
- “删除编辑层”：放弃并解除当前 Edit Action。

Action 保存这些自定义元数据：会话标识、原文件名、Base/Edit 角色、source MOT 路径、目标 MOT 路径、模型 ID 和帧数。重新打开 `.blend` 后可以恢复动画资产与 Action 的关联，不只依赖内存缓存。

## 单层 NLA 编辑层

每个已导入动画最多允许一条额外编辑层。当前动画绑定到 Armature 时使用：

```text
MOT Base    原始或已合并 Action，NLA REPLACE
MOT Edit    用户修改 Action，NLA COMBINE
```

`COMBINE` 用于让位置按差值叠加、旋转按变换组合、缩放按比例组合，比对所有通道统一使用普通 `ADD` 更符合骨骼变换。非当前动画的 Base/Edit Action 只保存在数据块中，不在 Armature 上留下未静音 NLA 轨道。

“合并编辑层”不能直接相加两组 F-Curve。插件必须在每个整数帧求值 Base + Edit 的最终 Pose，烘焙为新的 Base Action，验证成功后才替换旧 Base 并删除 Edit。导出动画时不要求用户预先合并；导出器直接采样最终 NLA 结果，相当于执行一次不改变 `.blend` 数据的临时合并。

从 NLA Tweak Mode 直接插入的关键帧是否能稳定得到预期差值需要 Blender 集成测试。若 Blender 自动关键帧不能可靠写入组合层，第一版增加“在编辑层插入关键帧”操作，由插件根据当前最终 Pose 与 Base Pose 计算 Edit 差值后写入，不能让用户无提示地产生双重变换。

## 写回与验证要求

MOT 写出必须先生成临时文件，再重新解析并验证，最后原子替换目标文件。失败时保留原 unpack MOT。

每行导出必须明确使用该行动画关联的 Base/Edit Action，不能依赖 Armature 当时碰巧激活的 Action。导出非当前动画时，插件临时绑定目标 Base/Edit、完成逐帧采样，并在结束后恢复原来绑定的动画和帧位置。

自动测试至少覆盖：

1. 原 MOT 载入 Action 后，每个整数帧的 Pose 矩阵与当前只读预览一致。
2. 未编辑 Action 写回后，重新解析的每条轨道在每个整数帧与原文件误差小于规定阈值。
3. 编辑单根面部骨后，只有该骨相关输出轨道的采样值发生变化。
4. version、flags、内部名称、头部 unknown、轨道顺序和轨道 unknown 保持不变。
5. source MOT 永不写入，输出只落到当前会话 workspace 明确登记的 unpack 路径。
6. Blender 关闭重开后，Action 元数据仍能正确定位模板和输出。

## 实施顺序

### 阶段一：面部模板编辑

- 增加 MOT 写出器，支持常量 `0` 和逐帧 float `1`。
- 增加 source/unpack 双路径动画资产和逐行独立导出。
- 按行把选中 MOT 烘焙为 Action，允许一个会话保存并切换多个已导入 Action。
- 实现源预览与 Action 编辑的互斥状态机。
- 实现 Action 反向采样、验证和 unpack 原子写出。
- 实现单条 NLA Edit 的添加、逐帧合并、删除和合成导出。
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
