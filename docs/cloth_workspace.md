# GBFR Modtools Cloth 工作流

插件的模型导入入口仍然选择 `.minfo`，但该文件必须是 `GBFR_modtools` 生成工作区中、已登记在 `workspace.json` 的文件。插件不会再读取放在 `.minfo` 隔壁的手工 `.mmesh` 副本。

导入时会自动解析：

- `ModelFiles` 中同模型 ID 的 `.minfo`、`.skeleton` 和 `model_streaming/lod0/*.mmesh`；
- `ClothFiles` 中全部基础 `*_clp.bxm.xml` 与 `*_clh.bxm.xml`；
- 工作区上级 `_lib/tools/GBFRDataTools/GBFRDataTools.exe`。

导入完成后，在 3D 视图右侧 `GBFR > Cloth 数据` 中编辑。CLP Header 和节点参数、CLH 端点与胶囊引用都直接来自 XML。视图开关只绘制静态数据：绿色为上下游骨骼链，粉色为横向连接，橙色为 `noFix`，青色为 CLH 球/胶囊。当前没有运行物理解算。

“写入当前”或“全部写入 build”会先更新 `unpack` 中的 XML，再调用 GBFRDataTools 编码到记录指定的 `build` 路径。写回基于原 XML 树更新已知字段，未知节点和属性会保留。CLP 当前不允许创建或删除拓扑节点；CLH 允许添加和删除碰撞端点。

纯 Python 测试：

```powershell
py -3.13 -m unittest discover -s test -p "test_*.py"
```

Blender 注册测试：

```powershell
blender --background --python test/blender_smoke.py
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
