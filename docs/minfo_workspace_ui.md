# minfo 工作区 UI

插件 2.0 以一次 `.minfo` 导入创建的 Collection 作为独立编辑会话。Collection 保存用户选择的 minfo 路径、`workspace.json`、Armature 和主 Mesh 指针；Cloth、SOP 与 MOT 状态继续保存在该会话的 Armature 上。导入多个 minfo 时，各集合的材质、约束、动画缓存、Cloth 参数和构建目标互不共享。

3D 视图右侧 `GBFR > GBFR 工作区` 是中控面板。顶部菜单切换会话并选中其 Armature，路径栏显示当前编辑的 minfo 源地址。选择某个已导入对象时，面板自动使用该对象所属会话；选择用户在其他 Collection 中导入的替换模型时，中控仍保持显式选择的 GBFR 会话，不会把插件操作应用到替换模型。

中控操作：

- 导入按钮创建新的 minfo 会话，不覆盖现有会话。
- “恢复”重新读取当前会话的材质、Cloth XML、SOP 和 MOT 列表，会丢弃这些中间态的当前编辑；它不会重新创建 Mesh 或 Armature。
- “导出到工作区”先锁定当前会话 Armature，再让用户选择 `workspace.json`。文件选择器会在确认前列出模型 ID、即将覆盖的三条 `unpack` 路径、调试 JSON 路径，并明确提示不会写入 `build`。插件按当前会话模型 ID 读取 `ModelFiles`，在临时目录完成转换后直接覆盖该工作区 `unpack` 中登记的 `.minfo/.skeleton/.mmesh`；不使用用户在其他 Collection 中的活动对象，也不再要求手工管理 `_Exported_MInfo`。
- “构建 Cloth”只写回当前会话的全部 CLP/CLH，并编码到该工作区的 build 路径。
- “对象”面板只选择或控制当前会话记录的 Armature、主 Mesh 与 Collection。
- “材质”“Cloth”“SOP 约束”“MOT 动画”都是中控子面板，只解析当前会话。

旧版 Fixes、Utilities、Materials、Advanced 和 Credits 全局面板不再注册。这些面板依赖当前选择对象，无法保证多 minfo 与外部替换集合之间的作用域，因此不再作为 2.0 编辑流程入口。底层操作符暂时保留，供脚本或搜索调用；新 UI 不会自动对会话外对象执行它们。

模型导出的可读调试 JSON 保存在工作区 `.gbfr/exports/<模型ID>.json`。三个游戏二进制文件只写入 `unpack`，不会直接写入 `build`；在 GBFR Modtools 预览、刷新并确认后，再由编辑器复制到 `build`。
