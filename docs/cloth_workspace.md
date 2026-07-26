# GBFR Modtools Cloth 工作流

插件的模型导入入口仍然选择 `.minfo`，但该文件必须是 `GBFR_modtools` 生成工作区中、已登记在 `workspace.json` 的文件。插件不会再读取放在 `.minfo` 隔壁的手工 `.mmesh` 副本。

导入时会自动解析：

- `ModelFiles` 中同模型 ID 的 `.minfo`、`.skeleton` 和全部已登记的 `model_streaming/lod#`/`shadowlod#` `.mmesh`；导入层级为模型根对象、LOD 空对象、该 LOD 的一个或多个 Mesh；
- `ClothFiles` 中全部基础 `*_clp.bxm.xml` 与 `*_clh.bxm.xml`；
- 工作区上级 `_lib/tools/GBFRDataTools/GBFRDataTools.exe`。

导入完成后，3D 视图右侧 `GBFR 工作区` 下提供三个互相独立的区域：`Cloth 预览` 只管理视口覆盖，`CLP 求解` 编辑求解组和节点，`CLH 碰撞` 编辑碰撞层和球/胶囊。它们只操作中控当前选择的 minfo 会话。视图开关绘制当前会话的静态数据：绿色为上下游骨骼链，粉色为横向连接，橙色为 `noFix`，青色为 CLH 球/胶囊。当前没有运行物理解算。

CLP 列表会直接显示组 ID、节点数和引用的 CLH 层。选择组后，可在“求解组/节点”之间切换；组级 Header 每次只展开一个参数分类，节点属性按拓扑、运动、碰撞、风力与缩放、原始字段分类。CLH 列表显示每层碰撞体数量，碰撞体属性按形状、附着、状态和原始字段分类，添加与删除使用列表右侧的 `+/-`。这样切换对象时只显示当前任务所需字段，不再同时展开整个 CLP 和 CLH 数据树。

界面不会把骨骼编码当普通整数暴露出来。CLP 的节点、上游、下游、横向、多边形和固定引用，以及 CLH 的 P1/P2 附着骨骼，都会解析为当前 Armature 的可搜索骨骼字段；按钮可以直接在骨架中选中目标。通用人体骨骼优先显示 `Hips (_000)` 一类映射名称，cloth 专用骨骼保留 `_c45` 等游戏名。搜索字段修改后会通过骨骼的 `gbfr_bone_id` 同步回原始编码，`4095` 仍表示无连接。CLP 节点自身的骨骼是原 XML 拓扑身份，因此只读；需要改变拓扑时不能仅靠改一个 ID。

`useCollisionFlags_` 显示为逐层的 CLH 开关，不再要求手算位掩码；CLH 的 `capsule` 显示为同层碰撞端点引用，留空表示球。已知 Header 与节点字段使用中文名称和用途提示，未完全确认的参数会明确标注。数据版本、原始骨骼编码、碰撞 ID 和位掩码仍可在“原始 Header”或各对象的“原始字段”分类中检查，以便研究和故障排查。

“写入当前”或“全部写入 build”会先更新 `unpack` 中的 XML，再调用 GBFRDataTools 编码到记录指定的 `build` 路径。写回基于原 XML 树更新已知字段，未知节点和属性会保留。CLP 与 CLH 都允许创建和删除记录；空 CLP 会保留 Header 和组号并把节点数写为 0。

半隐式 CLP 创建与删除位于顶级 `GBFR 实用工具 > CLP 创建工具`，不会在上面的 `Cloth 预览`、`CLP 求解` 和 `CLH 碰撞` 区域增加操作按钮。常驻面板只显示当前 CLP 和操作按钮；点击“添加所选”或“替换当前组”后，弹窗才集中显示本次创建使用的预设、连接方式、闭合和组参数选项：

- 选择多串骨链后，“添加所选”或“替换当前组”会按真实父子层级计算深度，按 root 骨名排序横向顺序，并把预设曲线立即烘焙为普通可编辑节点。
- 点击“添加所选”或“替换当前组”时会立即按当前 Blender 模式读取并快照骨骼选择。编辑/姿态模式只要 context 返回了有效当前选择，就不会再合并底层历史选择标记；context 完全取不到时才回退到 EditBone 的骨身/头/尾或 PoseBone/Bone 状态。生成后的所有纵向、横向和固定引用还会校验为仅指向本次快照骨骼。
- “覆盖物理参数”只控制 `CLOTH_HEADER`：关闭时保留当前 CLP 原有求解组参数，开启时用弹窗所选物理预设覆盖。它每次打开都默认关闭。新建节点的节点级参数无论开关状态如何都来自所选预设。
- 横向网格可以选择首尾闭合；独立骨链不会生成 `noSide/noPoly`。独立链遇到父骨分叉时，最长子树会继续当前主链，其余分支分别成为新链；长度相同时按子骨名选择。横向网格仍会拒绝分叉。
- 独立链不要制作一个父节点连接多个下游的一对多结构。`noUp/noDown` 只支持互反线性链；分叉时只能保留一支纵向续接，其余分支必须成为新链。不要用 `noSide/noPoly` 伪装父子分叉。
- “删除所选”严格按用户当前选择删除命中的当前组节点并清除悬空引用。删除不会自动扩展到后代，不会重写幸存节点参数，也不会跨过被删父骨桥接。
- “重建连接（保留节点参数）”点击后会单独询问连接方式和闭合设置，再按当前父子层级重建拓扑。它只改连接引用；与“替换当前组”不同，它保留每个 `CLOTH_WK` 节点的全部物理数值。
- 新增骨的 CLP 编号复用模型导出器的 source skeleton 与实验白名单分配器，和模型导出临时副本得到相同 `_xxx` 名称。若模型导出时关闭“实验：新增骨骼使用白名单编号”，新节点将无法与模型骨架一致。

这些操作只修改 Blender 内存中的当前 CLP，支持 Undo。确认连接和参数后再用原有“写入当前”生成 XML/BXM；不满意时也可以重新载入 `unpack`，或在 GBFR Modtools 中从 source 恢复单个 CLP。

实现注意：复制现有 `CLOTH_WK` 或 CLH 碰撞记录时，必须先把 Blender RNA 的向量属性转换为普通 tuple，再清空并重建 `CollectionProperty`。RNA 数组是对原集合存储的动态引用；直接保存在临时数据类中会在 `clear()` 后失效，导致追加新链时改坏其他节点的 `offset`。真实 `pl1400` 烟测会在独立链追加前后逐字段比较全部旧节点，并检查新引用不越过本次选择。

新增骨号分配前必须收集所有 CLP 的 `no/noUp/noDown/noSide/noPoly/noFix` 和所有 CLH 的 `p1/p2`，把这些编号全部列为全模型保留号。白名单分配器必须绕开保留号，并把最终编号固化到新增骨的 `gbfr_bone_id`，保证 CLP 创建和模型导出使用完全相同的编号。这样新袖骨不会让其他 CLP/CLH 的旧悬空引用突然复活。对已经由旧版本产生冲突的当前组，追加时仍会把命中新节点编号的五种旧引用清为 `4095`，作为兼容修复。

纯 Python 测试：

```powershell
py -3.13 -m unittest discover -s test -p "test_*.py"
```

Blender 注册测试：

```powershell
blender --background --python test/blender_smoke.py
```

CLP 创建与模型导出骨号联合测试：

```powershell
blender --background --python test/blender_clp_tools_smoke.py -- <工作区 source minfo>
```

## SOP 骨骼约束

选择身体模型 `.minfo` 时，插件还会从工作区 `source/data/model/...` 自动寻找同名 `.sop`。全部 SOP 操作都会作为只读检查数据导入 `GBFR > SOP 骨骼约束`：

- 通过静止姿态自检的 `Swing/Twist 分配` 与 `Twist 提取` 会生成名称带有 `[近似]` 的 Blender `Copy Rotation` 约束；N 面板可以整体启用或静音。
- Blender 的分轴 Copy Rotation 不能严格等价于游戏的四元数 swing/twist 公式，因此这里只用于建模和动作检查，不应被视为游戏运行结果的完整复现。
- 自检失败的核心变体不会执行；未完全探明的 corrective 操作只显示 source、target、类型、状态和原始属性，不会生成错误约束。
- SOP 当前是**单向导入**。模型、CLP/CLH 导出都不会修改或生成 `.sop`，N 面板也不提供 SOP 写回按钮。

## MOT 动画预览

身体和面部模型导入后，`GBFR > MOT 动画预览` 会索引工作区 `source/data/pl/...` 或 `source/data/fp/...` 中的同模型 MOT。列表按文件名排序，点击条目才完整解析当前剪辑；切换条目会替换内存中的当前剪辑。

- 预览器支持 MOT 压缩类型 `0-8`、常量/线性/Hermite 曲线和 60 FPS 时间轴。
- 采样结果由帧回调直接写入 PoseBone `matrix_basis`，随后交给 Blender 依赖图计算已导入的 SOP 近似约束。
- 不为整批身体动作或表情切片创建 Action、Animation Slot、NLA Track 或关键帧数据。
- “停止并恢复静止姿态”会清除当前内存剪辑并把骨架恢复到导入 rest pose；MOT 只用于预览，不参与模型或 cloth 导出。

## 工作区材质

导入 `.minfo` 时，插件会读取该模型 `unpack/data/model/.../vars/0.mmat.json` 的 `Entries1`，按网格材质槽保存的 `MaterialID` 关联材质。这里只导入 `0.mmat` 基础配色，不读取 `1.mmat` 及之后的换色材质，也会忽略名称中带 `_c01_`、`_c02_` 等标记的贴图。

基础色 DDS 按以下顺序查找：`unpack/data/granite/2k`、`unpack/data/texture/2k`、`unpack/data/granite/4k`、`unpack/data/texture/4k`。文件名同时支持 `<name>.dds` 和旧 WTB 解码生成的 `<name>_0.dds`。Blender 4.5 可以直接读取这些 DDS，不需要预先转换格式。

当前材质是面向制作预览的简化无光照材质：DDS 颜色连接到 Emission，Transparent BSDF 与 Emission 通过 Mix Shader 混合，DDS alpha 作为混合因子，材质表面模式设为 Alpha Blend。没有普通 albedo 的眼球槽会按各自 alpha 依次合成结膜、虹膜和高光 DDS，再连接到同一个 Emission 输出。它不会复现游戏中的 PBR、MSK 通道、法线、描边或颜色参数。导入结果和缺图数量记录在网格对象的 `gbfr_material_applied`、`gbfr_material_missing` 属性中；每个材质还会记录所用 `0.mmat.json` 和 DDS 路径，便于定位资源。
