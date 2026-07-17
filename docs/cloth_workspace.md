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
