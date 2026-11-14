# 新都遥感前端

Vue 3 + TypeScript + Vite 的独立前端应用，读取后端 API 契约 v1。页面按路由拆分，发布清单集中存放在 Pinia store，HTTP 访问集中在 `src/services/api.ts`。

## 启动

```powershell
npm install
npm run dev
```

默认访问 `http://localhost:5173`。默认 API 地址为同源 `/api/v1/`；可在页面左侧「接口设置」中改为后端地址。跨域部署时，后端需允许当前前端源访问。

## 目录

- `src/views/`：项目总览、地图、分析和成果页面。
- `src/components/`：可复用界面组件。
- `src/services/`：请求封装；路径使用 manifest 提供的 API 相对路径。
- `src/stores/`：跨页面共享状态，目前包含发布批次与连接状态。
- `src/types/`：接口字段类型。
- `src/router.ts`：页面路由与导航元数据。

## 扩展页面

1. 在 `src/router.ts` 新增路由，尽量为独立业务页面创建单独的 view。
2. 在 `src/App.vue` 的 `navigation` 增加导航项，并指定所属分组与图标。
3. 数据页面从 `release.manifest.resources` 获取资源状态及 `path`，只请求 `status: ready` 的资源；使用 `getResource<T>()` 读取 `{ run_id, data }` 包装中的 `data`。
4. 页面筛选留在浏览器内存中完成。不要将尚未发布的数据标成零，也不要将 `mock` 批次显示为真实研究结论。

清单 `release_state` 为 `not_published` 时保留空状态；`ready` 文件返回 404 时显示成果文件缺失，与未发布状态分开处理。

## 两种分析方式对比

访问 `/comparison`，可并排查看原有随机森林流程和文档增强方案的流程、精度、街镇扩张、分类图与驱动因素。原有 Python 分析代码保持不变。增强方案的训练、空间分析和成果发布需由离线流程另行完成；页面不会生成研究指标。

发布字段、评价口径和图像路径见 [方法对比成果契约](docs/method-comparison.md)。
