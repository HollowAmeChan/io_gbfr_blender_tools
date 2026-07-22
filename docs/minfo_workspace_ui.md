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
