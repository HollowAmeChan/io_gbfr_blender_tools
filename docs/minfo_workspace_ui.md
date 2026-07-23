# minfo 工作区 UI

插件 2.0 以一次 `.minfo` 导入创建的 Collection 作为独立编辑会话。Collection 保存用户选择的 minfo 路径、`workspace.json`、模型根对象、Armature 和主 Mesh 指针；Cloth、SOP 与 MOT 状态继续保存在该会话的 Armature 上。导入多个 minfo 时，各集合的材质、约束、动画缓存、Cloth 参数和构建目标互不共享。

3D 视图右侧 `GBFR > GBFR 工作区` 是中控面板。顶部菜单切换会话并选中其 Armature，路径栏显示当前编辑的 minfo 源地址。选择某个已导入对象时，面板自动使用该对象所属会话；选择用户在其他 Collection 中导入的替换模型时，中控仍保持显式选择的 GBFR 会话，不会把插件操作应用到替换模型。

中控操作：

- 导入按钮创建新的 minfo 会话，不覆盖现有会话。
- “恢复”重新读取当前会话的材质、Cloth XML、SOP 和 MOT 列表，会丢弃这些中间态的当前编辑；它不会重新创建 Mesh 或 Armature。
- “导出到工作区”先锁定当前会话根对象，再让用户选择 `workspace.json`。文件选择器会在确认前列出模型 ID，以及将覆盖的 `.minfo`、`.skeleton` 和全部 `lod#`/`shadowlod#` `.mmesh` 路径，并明确提示不会写入 `build`。插件复制当前会话的完整层级到临时场景，由 v2 构建器直接生成二进制并原子覆盖 `unpack`；不使用其他 Collection 中的活动对象，也不生成 `_Exported_MInfo` 或中间 JSON。
- “构建 Cloth”只写回当前会话的全部 CLP/CLH，并编码到该工作区的 build 路径。
- “对象”面板只选择或控制当前会话记录的模型根对象、Armature、主 Mesh 与 Collection；材质摘要会统计全部 LOD 下的 Mesh。
- “材质”“Cloth”“SOP 约束”“MOT 动画”都是中控子面板，只解析当前会话。

旧版 Fixes、Utilities、Materials、Advanced 和 Credits 已汇总为同一 `GBFR` N 栏标签下的顶级“GBFR 实用工具”面板。它不是工作区中控的子面板，内部按骨架、网格、材质 ID、高级和项目链接折叠；骨骼名称可在 GBFR 编号与 Unity/Blender 人形名称之间双向转换，旧的网格清理、拆分/合并、材质 ID 与 minfo Magic 操作也保留。该面板明确作用于 Blender 当前活动对象，方便处理用户自己导入的替换模型；它不会因为中控选中了某个 minfo 会话而自动改动会话对象。

模型导出只写入工作区中已登记的 `unpack` 二进制，不会直接写入 `build`。在 GBFR Modtools 预览、刷新并确认后，再由编辑器复制到 `build`。`flatc.exe` 不再参与模型导出；它仍可能被 Modtools 的其他格式工具使用。

## 融合骨架与稳定索引

Blender 的 `Armature.data.bones` 顺序不是可靠的游戏骨骼索引。即使融合工具只是使用 `edit_bones.new()` 添加骨骼，新骨挂到已有父骨并退出编辑模式后，Blender 也可能按层级把新骨插入旧骨序列中间。父子关系仍然正确，但如果直接按该集合顺序写 `.skeleton`，原来的 cloth、SOP、动作和顶点权重会指向错误骨骼，游戏可能在载入模型时崩溃。

工作区导出不再依赖 Blender 的内部顺序。存在 source `.skeleton` 时，导出器按导出骨名匹配并建立一张稳定索引表：

1. source 中的全部原骨骼保持原索引和原顺序。
2. 融合后新增的骨骼统一追加到 source 骨骼之后。
3. `.skeleton` 的 `ParentId`、`.minfo` 的 deform bone 表和 `.mmesh` 权重索引共同使用这张表。

父子关系通过重新计算的 `ParentId` 保持，不要求父子骨在 Blender 列表中相邻。当前回归样本已验证：342 根原骨融合为 838 根后，原骨名称和父索引逐项不变，新增骨从索引 342 开始输出。

这项处理属于 GBFR 导出契约，不要求通用骨架融合工具写入 GBFR 自定义属性。已经融合好的 `.blend` 也可直接根据工作区 source skeleton 恢复导出顺序。前提是原骨骼没有被删除、重命名或改变父级；缺少源骨、出现重复导出骨名或修改原父级时，导出器会拒绝生成不一致的文件。

重新导出后必须把同一次生成的 `.minfo`、`.skeleton` 和全部 `.mmesh` 一起构建、投放。只替换 `data/model_streaming` 中的 `.mmesh`，让它搭配游戏原版 `.minfo/.skeleton`，会造成权重表和骨骼索引契约不一致。
