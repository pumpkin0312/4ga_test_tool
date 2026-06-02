# 导入看板测试夹具说明

本目录用于存放浏览器自动化导入看板场景需要上传的真实导出文件。

## 已准备

- `4gaboards_export.tgz`
  - 来源：`https://demo.4gaboards.com` 的 `Export Board`
  - 用途：`data/test_scenarios.json` 中 `f012_s02` 的 4ga Boards 导入场景
  - 状态：已确认是 gzip 压缩的 `.tgz` 文件，内部包含 `boards.csv`、`cards.csv`、`lists.csv` 等导出数据

## 待准备

- `trello_export.json`
  - 来源：Trello 看板的 `Export as JSON`
  - 用途：`data/test_scenarios.json` 中 `f012_s01` 的 Trello 导入场景
  - 状态：需要 Trello 账号导出真实 JSON；不要用随意编写的假 JSON 替代，否则网页解析可能失败

