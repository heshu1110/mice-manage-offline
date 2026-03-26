# Mice Manage MVP

这是一版按“路线二”实现的最小可运行版本：

- 手机网页离线录入
- 本地 IndexedDB 暂存待同步操作
- 回到实验室局域网后手动同步到本机 FastAPI 后端
- 服务器保留笼位数据和操作记录

## 首次准备

```powershell
cd "D:\mice manage"
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

## 启动

不要先执行 `Activate.ps1`，直接这样启动，能避开 PowerShell 执行策略报错：

```powershell
cd "D:\mice manage"
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

启动成功后打开：

```text
http://127.0.0.1:8000
```

## 页面说明

- `/`
  离线录入页。先在有网时打开，进入鼠房后可继续离线登记，回到实验室再点同步。
- `/dashboard`
  服务器当前笼位数据页。
- `/records`
  服务器全部操作记录页。
- `/login`
  在线后台示例登录页。

## 默认示例账号

- 管理员：`王老师`
- 负责人：`张同学`
- 普通用户：`李同学`

首次启动会自动创建 `mice_manage.db` 并写入示例数据。
