# 4ga Boards 最新测试报告逐用例失败分析与修改计划

- 最新报告：`/Users/qiguangyu/Desktop/现代软件/4ga_test_tool-main 3/reports/test_report_20260702_125824.json`
- 对比报告：`/Users/qiguangyu/Desktop/现代软件/4ga_test_tool-main 3/reports/test_report_20260701_194132.json`
- 页面通用操作证据：`/Users/qiguangyu/Desktop/现代软件/4ga_test_tool-main 3/reports/ui_operation_probe_20260702_141621.json`
- 卡片详情控件补充探测：`/Users/qiguangyu/Desktop/现代软件/4ga_test_tool-main 3/reports/card_modal_controls_20260702_readonly.json`
- 生成时间：2026-07-02 14:29:17

## 一、总体结论

本次最新报告共 44 个场景：PASS 11，FAIL 32，BLOCKED 1，功能通过率约 25.6%。相较 20260701_194132 的 41.9%，通过率下降，主要不是产品本身突然坏掉，而是自动化执行层的新改动把一部分真实页面元素“找丢了”。

最主要的共性原因：

1. **弹窗作用域误判**：`executor._visible_dialog_or_page()` 把普通页面残留的 `[class*=Popup]` 也当成弹窗；真实看板页没打开弹窗时也有 Popup 组件，导致 `_find()` 只在错误 scope 内找元素，页面上的 `Card_wrapper`、`Add List`、`Add Card` 反而找不到。
2. **项目设置与用户设置混淆**：`classify_precondition()` 只要看到“设置/settings”就进入用户 `/settings/profile`，导致“项目设置”类用例停在错误页面。
3. **打开看板假阳性**：`open_first_board()` 的 DOM 探测点到项目卡片后也返回 True，没有验证 URL 必须包含 `/boards/`。
4. **固定名称与真实 demo 数据不一致**：`Kanban Test Board`、`Getting started1` 等名称在真实页面不存在或不是看板名。
5. **卡片详情不是 `role=dialog`**：真实详情是 `CardModal_wrapper`，URL 会变成 `/cards/{id}`，很多用例等待 `div[role=dialog]` 注定失败。
6. **取消类/验证逻辑有误判**：部分取消场景虽然关键步骤失败，却因为“目标名称不可见”被规则验证误判为通过；必须先确认表单/弹窗曾打开。

## 二、优先修改顺序

1. P0：补 `test_data/trello_export.json`，否则 f012_s01 永远 BLOCKED。
2. P1：修 `_visible_dialog_or_page()` 和 `_find()`，弹窗内优先找，但找不到必须回退到 page；不要把普通 `[class*=Popup]` 残留组件直接当弹窗 scope。
3. P1：修 `classify_precondition()`：用户 Profile/Account/Authentication 和项目 Project Settings 分开；卡片/列表/看板场景优先进入 board/card。
4. P1：修 `open_first_board()`：点击后必须验证 `/boards/`，否则继续找真实 `a[href*=boards]`。
5. P1-P2：把 Add Board/Add List/Add Card/CardModal/Member/Label/Due Date/Description 做成专用 helper，不再只依赖 LLM 生成的单步 selector。
6. P2：固定名称改成运行时变量，或者先创建测试数据；不要“步骤动态化、预期仍固定化”。
7. P3：拖拽、移动、复制这些复杂交互单独探测隐藏菜单后再做，不要和基础 selector 修复混在一轮。

## 三、真实页面操作路径摘要

- 登录/登出：登录后右上角用户按钮 `button[title="Profile and Settings"]`，文字会随资料变化；登出点菜单 `Log out`。
- 用户设置：顶部 `button[title="Settings"][class*=Button_header]` → 左侧 Profile/Account/Authentication/Users。Profile 字段是 `input[name=name]`、`input[name=phone]`、`input[name=organization]`。
- 项目设置：看板页顶部 `button[title="Project Settings"]` → `/projects/{id}/settings`，不要走用户 Settings。
- 打开看板：必须点击 `a[href*=boards]` 并验证 URL 包含 `/boards/`。
- 新建看板：Dashboard/侧边栏 `Add Board` → 弹窗 `input[name=name]` → submit/Add Board；取消用 Close/Escape。
- 新建列表：看板页最右 `button[title="Add List"]` → `textarea[name=name]` → Enter/Add list。
- 新建卡片：列表底部 `button[title="Add Card"]` → `textarea[name=name]` → Enter/Add card。
- 卡片详情：点击 `[class*=Card_wrapper]` → URL `/cards/{id}` 或 `[class*=CardModal_wrapper]`；不要等 `div[role=dialog]`。
- 卡片成员：CardModal → `button[title="Add Member"]` → `input[placeholder="Search members..."]` → 点击候选用户。
- 卡片标签：CardModal → `button[title="Add Label"]` → Popup `Filter By Labels` → 点已有标签。
- 截止日期：CardModal → `button[title="Add Due Date"]` → `input[name=date]` / `Enter due date...` → Save。
- 描述编辑：CardModal → `button[title="Edit Description"]` 或描述文本 → textarea `Enter description...`；工具栏按钮包括 `Add colored text`、`Add table`、`Insert code`、`Insert Code Block`、`Add bold text (ctrl + b)`、`Add italic text (ctrl + i)`。

## 四、逐测试用例分析

### f001_s01 使用演示账号成功登录 — PASS

- 对比上一轮：PASS → PASS
- 步骤成功率：1.0; 规则通过率：1.0
- 失败原因：无，本轮通过。当前报告中 PASS，暂不需要针对该用例修复；但如果依赖 DD/TN 等共享账号状态，后续建议改为动态读取。
- 修改建议：暂不优先修改；后续统一做共享账号状态隔离和动态文本读取即可。

### f001_s02 使用无效密码登录失败 — PASS

- 对比上一轮：PASS → PASS
- 步骤成功率：1.0; 规则通过率：1.0
- 失败原因：无，本轮通过。当前报告中 PASS，暂不需要针对该用例修复；但如果依赖 DD/TN 等共享账号状态，后续建议改为动态读取。
- 修改建议：暂不优先修改；后续统一做共享账号状态隔离和动态文本读取即可。

### f001_s03 SSO 登录按钮可见 — PASS

- 对比上一轮：PASS → PASS
- 步骤成功率：1.0; 规则通过率：1.0
- 失败原因：无，本轮通过。当前报告中 PASS，暂不需要针对该用例修复；但如果依赖 DD/TN 等共享账号状态，后续建议改为动态读取。
- 修改建议：暂不优先修改；后续统一做共享账号状态隔离和动态文本读取即可。

### f002_s01 通过用户菜单成功登出 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：0.8333333333333334; 规则通过率：0.5
- 报告中的失败步骤：Step 5 `wait` `input[name='emailOrUsername']`：等待元素超时: input[name='emailOrUsername']
- 报告摘要问题：登出后用户名/邮箱输入框未出现，页面未正确跳转至登录页；等待输入框元素超时，表明登出流程未完成或页面状态异常；备选方案虽执行成功，但最终页面URL仍为首页，未跳转至/login
- 失败原因：登出后等待登录输入框超时，最终 URL 仍在首页 `/`。这里既可能是真登出按钮没有被正确点到，也可能是验证只等 `input[name=emailOrUsername]` 太窄。用户头像文字已从 DD 变为 TN，不能依赖固定头像文本。
- 真实操作步骤：真实路径：右上角 `button[title="Profile and Settings"]`（文字可能是 TN/DD/任意缩写）→ 菜单 `Log out` → 等 URL 包含 `/login` 或登录表单输入框可见。
- 具体修改方法：把登出 helper 改为 title 定位用户菜单，不按头像文字定位；点击 Log out 后同时验证 URL、登录表单、认证状态。如果点击后仍停留 `/`，把该用例归为产品/环境状态问题。
- 优先级：P1

### f004_s01 管理员成功编辑用户资料（修改显示名称） — PASS

- 对比上一轮：PASS → PASS
- 步骤成功率：1.0; 规则通过率：1.0
- 失败原因：无，本轮通过。当前报告中 PASS，暂不需要针对该用例修复；但如果依赖 DD/TN 等共享账号状态，后续建议改为动态读取。
- 修改建议：暂不优先修改；后续统一做共享账号状态隔离和动态文本读取即可。

### f004_s02 管理员成功修改用户邮箱 — PASS

- 对比上一轮：FAIL → PASS
- 步骤成功率：1.0; 规则通过率：1.0
- 失败原因：无，本轮通过。当前报告中 PASS，暂不需要针对该用例修复；但如果依赖 DD/TN 等共享账号状态，后续建议改为动态读取。
- 修改建议：暂不优先修改；后续统一做共享账号状态隔离和动态文本读取即可。

### f004_s03 管理员取消编辑用户资料 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：0.8571428571428571; 规则通过率：0.5
- 报告中的失败步骤：Step 6 `click` `Cancel`：click 返回 False
- 报告摘要问题：步骤6点击Cancel按钮失败，返回False；备选方案点击了Save按钮，与取消编辑的意图相悖；用户菜单未保持原始名称DD，说明修改可能被保存或状态异常
- 失败原因：测试要“取消编辑用户资料”，但真实 Profile 页通常只有 Save，没有稳定 Cancel。报告中 Step 6 点 Cancel 失败，备选方案还点了 Save，等于把取消场景做成了保存场景。
- 真实操作步骤：真实路径：顶部 Settings → Profile；字段是 `input[name=name]`、`input[name=phone]`、`input[name=organization]`；若没有 Cancel，只能用 Escape/离开页面不保存来验证。
- 具体修改方法：取消类用例禁止 fallback 到 Save。若页面无 Cancel，改场景定义为“输入后 Escape/导航离开，值不改变”，或标记为 BLOCKED/不支持。
- 优先级：P1

### f004_s05 修改用户资料-添加电话号码和组织名称 — PASS

- 对比上一轮：FAIL → PASS
- 步骤成功率：1.0; 规则通过率：1.0
- 失败原因：无，本轮通过。当前报告中 PASS，暂不需要针对该用例修复；但如果依赖 DD/TN 等共享账号状态，后续建议改为动态读取。
- 修改建议：暂不优先修改；后续统一做共享账号状态隔离和动态文本读取即可。

### f005_s01 成功创建项目 — PASS

- 对比上一轮：PASS → PASS
- 步骤成功率：1.0; 规则通过率：1.0
- 失败原因：无，本轮通过。当前报告中 PASS，暂不需要针对该用例修复；但如果依赖 DD/TN 等共享账号状态，后续建议改为动态读取。
- 修改建议：暂不优先修改；后续统一做共享账号状态隔离和动态文本读取即可。

### f005_s02 创建项目时取消操作 — PASS

- 对比上一轮：PASS → PASS
- 步骤成功率：1.0; 规则通过率：1.0
- 失败原因：无，本轮通过。当前报告中 PASS，暂不需要针对该用例修复；但如果依赖 DD/TN 等共享账号状态，后续建议改为动态读取。
- 修改建议：暂不优先修改；后续统一做共享账号状态隔离和动态文本读取即可。

### f006_s02 取消修改项目设置 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：0.5714285714285714; 规则通过率：0.5
- 报告中的失败步骤：Step 5 `click` `Settings`：click 返回 False；Step 6 `click` `input[name='name']`：click 返回 False；Step 7 `input` `input[name='name']`：input_text 返回 False
- 报告摘要问题：步骤5点击项目设置按钮失败，可能原因是页面未正确导航到项目详情页（实际停留在设置页面），导致目标元素不可见或不可点击。；实际执行轨迹中步骤4虽然标记成功，但URL未发生变化，仍为/settings/profile，说明未成功进入项目详情页。；测试前置条件要求存在项目（如Getting started1），但执行中未验证项目列表是否存在或可访问。
- 失败原因：“项目设置”被 `classify_precondition` 误判成用户 Settings，执行停在 `/settings/profile`，所以点击项目设置、项目名称输入框都失败。
- 真实操作步骤：真实路径：进入项目/看板 → 点击顶部 `button[title="Project Settings"]` → URL `/projects/{id}/settings` → 编辑 `input[name=name]`；取消同样需要确认页面是否真的提供 Cancel。
- 具体修改方法：修改前置条件分类：包含“项目设置/project settings”时优先 `needs_project/open_project_settings`，不要走 `open_settings(Profile)`；项目设置取消场景也不能 Save fallback。
- 优先级：P1

### f008_s01 从看板页面邀请成员到看板 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：0.5555555555555556; 规则通过率：0.0
- 报告中的失败步骤：Step 5 `wait` `div[role='button']`：等待元素超时: div[role='button']；Step 7 `wait` `input[name='emailOrUsername']`：等待元素超时: input[name='emailOrUsername']；Step 8 `input` `input[name='emailOrUsername']`：input_text 返回 False；Step 9 `click` `Invite`：click 返回 False
- 报告摘要问题：步骤5等待看板页面加载完成时超时，元素div[role='button']未找到，可能页面结构或加载逻辑有变化。；步骤7等待邀请成员弹窗出现超时，输入框input[name='emailOrUsername']未出现，弹窗可能未正确触发或定位符错误。；步骤8输入邮箱/用户名失败，因弹窗未出现导致无法操作。
- 失败原因：看板邀请成员使用了不存在的 `input[name=emailOrUsername]` 和 `Invite` 按钮；真实面板是 Add Member 搜索候选用户。
- 真实操作步骤：真实路径：进入 `/boards/` → 点击 `button[title="Add user"]` → 弹出 Add Member 面板 → 输入框 `input[placeholder="Search members..."]` 或 `Search users...` → 点击候选用户项（如 `TN / Temporary Name / demo@demo.demo`）。
- 具体修改方法：新增 board_invite_member helper：定位 Add user，等待 `[role=dialog]` 或 Popup，填 Search members/users，点击候选项；若没有可邀请用户，标 BLOCKED，不应 FAIL 为 selector 错。
- 优先级：P1

### f008_s02 从项目设置弹窗邀请成员到项目 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：0.5714285714285714; 规则通过率：0.0
- 报告中的失败步骤：Step 5 `wait` `Settings`：等待元素超时: Settings；Step 6 `click` `Settings`：click 返回 False；Step 7 `wait` `text=Members`：等待元素超时: text=Members
- 报告摘要问题：步骤4点击侧边栏项目名称后，URL未变化，仍停留在用户设置页面，导致后续步骤全部失败；步骤5等待项目页面加载超时，说明项目页面未成功加载；步骤6点击项目设置按钮失败，因为未进入项目页面，设置按钮不存在
- 失败原因：同样被项目设置/用户设置混淆，停在 `/settings/profile`，不是项目成员设置页；后续 Members/邀请弹窗都不存在。
- 真实操作步骤：真实路径：进入项目或看板 → `Project Settings` → 项目成员/Members 或 Add user 区域 → 搜索候选用户。不要点击顶部用户 Settings。
- 具体修改方法：先修 `classify_precondition`，再做 project_invite_member helper；如果项目设置页没有成员入口，标为 BLOCKED 并附 DOM 证据。
- 优先级：P1

### f009_s01 在项目中成功创建看板 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：0.7142857142857143; 规则通过率：0.5
- 报告中的失败步骤：Step 5 `click` `+`：click 返回 False；Step 6 `input` `input[name='name']`：input_text 返回 False
- 报告摘要问题：步骤5点击『+』按钮失败，导致无法触发添加看板流程；步骤6输入看板名称失败，进一步确认创建流程中断；核心验证点（新看板可见）未通过，功能未完成
- 失败原因：创建看板步骤点击 `+`，真实页面没有这个通用加号入口；真实入口是侧边栏/仪表板底部 Add Board。
- 真实操作步骤：真实路径：Dashboard 或侧边栏底部 `Add Board` → 弹窗 `input[name=name]` / placeholder `Enter board name...` → 选择 Project（如需要）→ 弹窗内 submit/Add Board。
- 具体修改方法：把 `+` 归一化/重写为 Add Board 流程；使用弹窗作用域填写 `input[name=name]`；新看板名称使用时间戳唯一值。
- 优先级：P1

### f009_s02 创建看板时取消操作 — FAIL

- 对比上一轮：PASS → FAIL
- 步骤成功率：0.5714285714285714; 规则通过率：1.0
- 报告中的失败步骤：Step 5 `click` `+`：click 返回 False；Step 6 `input` `input[name='name']`：input_text 返回 False；Step 7 `click` `Cancel`：click 返回 False
- 报告摘要问题：步骤5、6、7全部失败，未能完成取消操作流程；规则验证实际结果与执行轨迹严重矛盾：步骤失败但验证显示通过；测试场景的核心操作未执行，无法得出任何关于取消功能的结论
- 失败原因：取消创建看板仍走错误 `+` 流程，Cancel 点不到。更严重的是之前有“步骤失败但规则验证通过”的误判。
- 真实操作步骤：真实路径：点 Add Board → 弹窗出现 → 输入临时名称 → 点 Close 或按 Escape 取消 → 验证该临时看板名不可见。
- 具体修改方法：修 Add Board 取消 helper；验证必须要求“弹窗曾经打开且输入过名称”，否则不能因为名称不存在就 PASS。
- 优先级：P1

### f010_s01 从仪表板侧边栏切换到指定看板 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：1.0; 规则通过率：0.5
- 报告中的失败步骤：没有单步失败，但最终规则/LLM 判定失败，通常是预期名称或 URL 校验不匹配。
- 报告摘要问题：目标看板名称『Kanban Test Board』在页面上不可见，尽管URL显示已切换到看板视图
- 失败原因：固定看板名 `Kanban Test Board` 与真实 demo 数据不一致；执行打开了某个看板但预期仍检查固定名称，导致 FAIL。
- 真实操作步骤：真实路径：Dashboard 左侧项目 `a[href*=projects]` → 展开后点击 `a[href*=boards]`；真实默认看板常见为 `Learn 4ga Boards`。
- 具体修改方法：不要硬编码看板名；运行时读取第一个可见 `a[href*=boards]` 的文本作为变量，再用同一变量验证。若必须测试指定看板，先创建/导入该看板作为前置数据。
- 优先级：P2

### f010_s02 从看板页面通过侧边栏切换到另一个看板 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：1.0; 规则通过率：0.5
- 报告中的失败步骤：没有单步失败，但最终规则/LLM 判定失败，通常是预期名称或 URL 校验不匹配。
- 报告摘要问题：核心预期『目标看板名称可见』未通过，说明实际并未切换到目标看板『Getting started1』，可能侧边栏点击未生效或跳转逻辑有误。
- 失败原因：固定名 `Getting started1` 不是当前看板名；真实列表叫 `Getting Started`，真实看板是 `Learn 4ga Boards`。步骤成功但验证固定名失败。
- 真实操作步骤：真实路径：从看板页侧边栏点击另一个 `a[href*=boards]`，等待 URL 改为新的 `/boards/{id}`，验证点击的链接文本出现在 header。
- 具体修改方法：建立 dynamic board 变量，不再把固定名重写为 first board 后仍保留旧预期；至少要同步重写 expectation。
- 优先级：P2

### f012_s01 从Trello JSON文件导入看板 — BLOCKED

- 对比上一轮：BLOCKED → BLOCKED
- 步骤成功率：0; 规则通过率：0
- 报告中的失败步骤：没有单步失败，但最终规则/LLM 判定失败，通常是预期名称或 URL 校验不匹配。
- 报告摘要问题：测试数据缺失：上传文件不存在 test_data/trello_export.json
- 失败原因：测试数据缺失：报告明确指出 `test_data/trello_export.json` 不存在。
- 真实操作步骤：真实路径：Add Board → Import/Trello JSON → 上传 Trello export JSON。
- 具体修改方法：补一个合法 Trello JSON 到 `test_data/trello_export.json`，或继续把该用例归为 BLOCKED，不计入功能失败率。
- 优先级：P0

### f012_s02 从4ga Boards TGZ文件导入看板 — PASS

- 对比上一轮：PASS → PASS
- 步骤成功率：0.9230769230769231; 规则通过率：1.0
- 失败原因：无，本轮通过。当前报告中 PASS，暂不需要针对该用例修复；但如果依赖 DD/TN 等共享账号状态，后续建议改为动态读取。
- 修改建议：暂不优先修改；后续统一做共享账号状态隔离和动态文本读取即可。

### f012_s03 导入看板时取消操作 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：0.8333333333333334; 规则通过率：0.5
- 报告中的失败步骤：Step 7 `wait` `text=Add Board`：等待元素超时: text=Add Board；Step 10 `click` `Cancel`：click 返回 False
- 报告摘要问题：点击『Cancel』取消导入操作失败（click返回False），备选点击『Close』按钮虽成功但未关闭导入弹窗；导入弹窗在取消操作后仍然可见，未达到预期关闭效果
- 失败原因：导入取消场景等待 `text=Add Board` 超时，随后 Cancel/Close 没有真正关闭导入弹窗；项目创建后页面/弹窗状态没有被可靠确认。
- 真实操作步骤：真实路径：创建/进入项目 → `Add Board` → 切到 Import/Trello/4ga 导入页签 → 打开导入弹窗 → Close/Escape 取消 → 验证导入弹窗不可见且没有新看板。
- 具体修改方法：用 Add Board 弹窗内的 tab/按钮定位，不要靠页面文字 `text=Add Board`；取消后验证 `[role=dialog]`/Popup 关闭。
- 优先级：P2

### f013_s01 在看板上成功创建新列表 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：0.625; 规则通过率：0.0
- 报告中的失败步骤：Step 6 `click` `button[title='Add List']`：click 返回 False；Step 7 `input` `textarea[name='name']`：input_text 返回 False；Step 8 `click` `button[title='Add List']`：click 返回 False
- 报告摘要问题：步骤6点击『Add a list』按钮失败，导致后续输入和确认步骤无法执行；实际打开的看板URL（1808019506602182218）与前置条件指定的看板URL（1782552018351555584）不一致，可能造成元素定位失败；所有创建列表的关键步骤均返回False，表明页面元素可能不存在或不可交互
- 失败原因：真实 `button[title="Add List"]` 存在，但仍点击失败，核心原因很可能是 `_visible_dialog_or_page()` 把页面残留 Popup 当成弹窗，导致 `_find()` 只在错误 scope 内找元素。
- 真实操作步骤：真实路径：进入 `/boards/` → 横向滚到最右 → `button[title="Add List"]`（可见文本 Add list）→ 填 `textarea[name=name]` → Enter 或 Add list。
- 具体修改方法：先修弹窗作用域：普通页面查找必须 fallback 到 page；然后封装 `add_list(name)`，不要只靠单步 selector。
- 优先级：P1

### f013_s02 创建列表时取消操作 — FAIL

- 对比上一轮：PASS → FAIL
- 步骤成功率：0.625; 规则通过率：1.0
- 报告中的失败步骤：Step 6 `click` `button[title='Add List']`：click 返回 False；Step 7 `input` `textarea[name='name']`：input_text 返回 False；Step 8 `click` `Cancel`：click 返回 False
- 报告摘要问题：步骤6点击『Add a list』按钮失败，导致后续所有操作无法执行；规则验证实际结果与执行轨迹严重矛盾，可能为误报或验证逻辑错误；最终URL与前置条件中的看板URL不一致，说明未进入目标看板
- 失败原因：同 f013_s01，Add List 没打开，后续输入和 Cancel 自然失败；验证还因为名称不存在而误判通过。
- 真实操作步骤：真实路径：Add List → `textarea[name=name]` → 输入临时列表名 → Escape/Cancel → 验证临时名不可见且表单关闭。
- 具体修改方法：取消类验证必须记录“表单已打开”这个前置事实，否则不能 PASS。
- 优先级：P1

### f015_s01 通过拖拽移动列表位置 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：0.625; 规则通过率：0.5
- 报告中的失败步骤：Step 6 `wait` `div[class*='List_']`：等待元素超时: div[class*='List_']；Step 7 `hover` `div[class*='List_'] >> nth=0`：返回 False/未执行；Step 8 `wait` `div[class*='List_'] >> nth=0 >> [class*='dragHandle']`：等待元素超时: div[class*='List_'] >> nth=0 >> [class*='dragHandle']
- 报告摘要问题：实际执行轨迹中步骤6失败：等待看板列加载超时，说明页面结构或选择器不匹配；步骤7、8因前置步骤失败而无法执行，拖拽操作完全未发生；规则验证实际结果中'第二个列表仍然存在'未通过，与预期严重不符
- 失败原因：列表选择器 `div[class*=List_]` 太泛，等待失败；报告还在找不存在/不稳定的 `dragHandle`。真实列表是 `List_outerWrapper/List_header`，折叠按钮和编辑按钮在 header 内。
- 真实操作步骤：真实路径：进入看板 → 使用 `[class*=List_outerWrapper]` 或 `[class*=List_header]` 定位至少两个列表 → 用 Playwright `drag_to` 从一个 List header 拖到另一个 header。
- 具体修改方法：新增 list drag helper；如果真实 UI 没有可稳定拖拽点，用坐标 drag header，并截图/DOM 验证顺序变化。
- 优先级：P3

### f015_s02 使用鼠标拖拽移动列表到指定位置 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：0.625; 规则通过率：0.5
- 报告中的失败步骤：Step 6 `wait` `div[class*='List_']`：等待元素超时: div[class*='List_']；Step 7 `hover` `div[class*='List_'] >> nth=1`：返回 False/未执行；Step 8 `wait` `div[class*='List_'] >> nth=1 >> [class*='dragHandle']`：等待元素超时: div[class*='List_'] >> nth=1 >> [class*='dragHandle']
- 报告摘要问题：步骤6等待看板列加载超时，导致后续所有与列表交互的步骤失败。；规则验证实际结果中两个预期存在矛盾：第一个列表不存在但标题文本却发生变化，说明验证逻辑可能不准确或依赖了错误元素。；实际执行轨迹与预期步骤不匹配：预期步骤包含拖拽操作，但实际执行在第6步即失败，未执行任何拖拽动作。
- 失败原因：与 f015_s01 相同，列表元素等待和拖拽手柄定位都不可靠。
- 真实操作步骤：同 f015_s01，目标位置应使用第二个列表 header 坐标。
- 具体修改方法：同 f015_s01；先保证两个列表存在，再验证顺序。
- 优先级：P3

### f016_s01 折叠列表-隐藏卡片 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：0.8571428571428571; 规则通过率：0.0
- 报告中的失败步骤：Step 7 `wait` `div[role='button']`：等待元素超时: div[role='button']
- 报告摘要问题：规则验证实际结果明确判定卡片隐藏失败（✗ 未通过）；实际执行步骤7等待div[role='button']超时，可能由于列表折叠后卡片元素未正确隐藏或选择器定位错误；实际执行看板ID（1808019506602182218）与预期看板ID（1782552018351555584）不一致，可能影响测试准确性
- 失败原因：等待 `div[role=button]` 太泛且失败；真实折叠入口是列表 header 上的 `button[title="Collapse List"]`。
- 真实操作步骤：真实路径：找到目标列表标题（如 `Getting Started`，不是 `Getting started1`）→ 点击相邻 `button[title="Collapse List"]` → 验证列表变为 `List_headerCollapsed` 或卡片不可见。
- 具体修改方法：替换折叠 helper：按列表标题定位 header，再点 Collapse；不要用 `div[role=button]`。
- 优先级：P2

### f016_s02 展开列表-显示卡片 — FAIL

- 对比上一轮：PASS → FAIL
- 步骤成功率：0.8571428571428571; 规则通过率：1.0
- 报告中的失败步骤：Step 7 `wait` `Getting started1`：等待元素超时: Getting started1
- 报告摘要问题：步骤7等待元素超时，未能找到列表标题'Getting started1'，导致后续所有操作无法执行。；规则验证实际结果中声称'通过'，但实际执行轨迹显示关键步骤失败，存在数据不一致。
- 失败原因：固定列表名 `Getting started1` 错误，真实是 `Getting Started`；展开入口是 `button[title="Expand List"]`。
- 真实操作步骤：真实路径：找到 collapsed list → `button[title="Expand List"]` → 验证卡片重新可见。
- 具体修改方法：列表名动态化或修正为真实名称；新增 expand_list helper。
- 优先级：P2

### f018_s01 在看板列表中成功创建卡片 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：0.7777777777777778; 规则通过率：0.0
- 报告中的失败步骤：Step 7 `click` `+`：click 返回 False；Step 8 `input` `textarea[name='name']`：input_text 返回 False
- 报告摘要问题：步骤7点击『+』按钮失败，导致无法进入卡片创建流程；步骤8输入卡片标题失败，进一步确认创建操作未执行；最终页面未出现新卡片，功能未实现
- 失败原因：创建卡片仍点击 `+`，真实入口是每个列表底部 `button[title="Add Card"]`。
- 真实操作步骤：真实路径：进入看板，确保有展开列表 → 点击 `button[title="Add Card"]` → `textarea[name=name]` → Enter/Add card → 等 `[class*=Card_wrapper]` 出现新标题。
- 具体修改方法：将卡片创建场景重写为 `ensure_list_exists` + Add Card helper；修 Popup scope 后该流程应稳定。
- 优先级：P1

### f018_s02 创建卡片时取消操作 — FAIL

- 对比上一轮：PASS → FAIL
- 步骤成功率：0.7777777777777778; 规则通过率：1.0
- 报告中的失败步骤：Step 7 `click` `+`：click 返回 False；Step 8 `input` `textarea[name='name']`：input_text 返回 False
- 报告摘要问题：步骤7点击『+』按钮失败，无法触发创建卡片界面；步骤8输入卡片标题失败，无法完成创建流程；规则验证实际结果声称通过，但实际未执行有效操作，验证结果不可信
- 失败原因：同 f018_s01，Add Card 表单未打开；验证因卡片名不存在可能误判。
- 真实操作步骤：真实路径：Add Card → 输入临时卡片名 → Escape/Cancel → 验证表单关闭且临时卡片名不可见。
- 具体修改方法：取消创建卡片必须验证表单曾打开；取消按钮失败时用 Escape。
- 优先级：P1

### f019_s01 通过拖拽将卡片移动到另一个列表 — FAIL

- 对比上一轮：PASS → FAIL
- 步骤成功率：0.7; 规则通过率：1.0
- 报告中的失败步骤：Step 8 `hover` `[class*='Card_wrapper']`：返回 False/未执行；Step 9 `click` `[class*='Card_wrapper']`：click 返回 False；Step 10 `wait` `[class*='CardModal_wrapper']`：等待元素超时: [class*='CardModal_wrapper']
- 报告摘要问题：步骤8悬停卡片失败，导致后续点击卡片、等待详情弹窗等关键步骤全部失败；实际执行轨迹未执行预期步骤中的点击Move按钮、选择目标列表、确认移动等操作；规则验证实际结果与执行轨迹严重矛盾：执行失败但验证结果全部通过，说明验证逻辑或数据采集存在严重问题
- 失败原因：卡片点击/等待 CardModal 失败；真实 `Card_wrapper` 在页面上存在，失败更像是错误 Popup scope。移动卡片的步骤本身也没有真实 DOM 证据。
- 真实操作步骤：基础真实路径：点击 `[class*=Card_wrapper]` → 等 URL `/cards/` 或 `[class*=CardModal_wrapper]`；拖拽移动应优先在看板上把卡片 wrapper 拖到另一个列表区域。
- 具体修改方法：先修 `_find` scope 和 `open_first_card`；移动动作另写 `drag_card_to_list`，不要在卡片未打开时继续验证 PASS。
- 优先级：P3

### f019_s02 通过菜单将卡片移动到另一个看板 — FAIL

- 对比上一轮：PASS → FAIL
- 步骤成功率：0.6666666666666666; 规则通过率：1.0
- 报告中的失败步骤：Step 7 `wait` `[class*='Card_wrapper']`：等待元素超时: [class*='Card_wrapper']；Step 8 `click` `[class*='Card_wrapper']`：click 返回 False；Step 9 `wait` `[class*='CardModal_wrapper']`：等待元素超时: [class*='CardModal_wrapper']
- 报告摘要问题：步骤7等待卡片加载失败（超时），导致后续所有依赖卡片存在的步骤均失败；步骤8点击第一张卡片失败，无法打开卡片详情；步骤9等待卡片详情弹窗失败，无法执行移动操作
- 失败原因：卡片加载/打开失败；“通过菜单移动到另一个看板”的 Move 入口在已探测 CardModal 中没有直接可见，需要进一步点 `Edit Card` 或隐藏菜单确认。
- 真实操作步骤：已确认基础路径：打开卡片详情后有 `Edit Card`、`Close Card`、`Delete Card`、Add Member/Label/Due Date 等；Move/Copy 不是直接按钮。
- 具体修改方法：先补充 Edit Card 弹窗探测，再实现 move_to_board helper。没有目标看板时先创建目标看板或标 BLOCKED。
- 优先级：P3

### f019_s03 通过菜单将卡片移动到另一个项目 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：0.6666666666666666; 规则通过率：0.5
- 报告中的失败步骤：Step 7 `wait` `[class*='Card_wrapper']`：等待元素超时: [class*='Card_wrapper']；Step 8 `click` `[class*='Card_wrapper']`：click 返回 False；Step 9 `wait` `[class*='CardModal_wrapper']`：等待元素超时: [class*='CardModal_wrapper']
- 报告摘要问题：步骤7等待卡片加载失败，定位元素超时，可能是页面结构或选择器不匹配；步骤8点击第一张卡片失败，因卡片未加载或无法定位；步骤9等待卡片详情弹窗失败，因卡片未打开
- 失败原因：同 f019_s02，卡片详情未可靠打开，且跨项目移动需要目标项目/看板前置数据。
- 真实操作步骤：基础路径同 f019_s02；跨项目移动还要先准备第二个项目和目标看板。
- 具体修改方法：增加前置数据构造；Move 面板未确认前不要硬写 selector。
- 优先级：P3

### f020_s01 复制卡片并在原卡片下方生成副本 — FAIL

- 对比上一轮：PASS → FAIL
- 步骤成功率：0.7; 规则通过率：1.0
- 报告中的失败步骤：Step 8 `wait` `div[role='button']`：等待元素超时: div[role='button']；Step 9 `hover` `div[role='button']`：返回 False/未执行；Step 10 `click` `Copy`：click 返回 False
- 报告摘要问题：步骤8等待卡片列表渲染失败（超时），导致后续悬停和点击复制操作无法执行；步骤9悬停操作失败，原因未知；步骤10点击复制按钮失败，click返回False
- 失败原因：复制卡片使用旧的 `div[role=button]`/Copy 流程；真实页面没有直接可见 Copy 按钮，可能在 hover 的 `Edit Card` 或隐藏菜单里。
- 真实操作步骤：已确认卡片 hover/详情有 `Edit Card`；还未确认 Copy 所在面板。
- 具体修改方法：先探测 `Edit Card` 弹窗/卡片 hover 菜单，找到 Copy 的真实入口；在此之前该用例应标为“需补 DOM 证据/暂缓”。
- 优先级：P3

### f020_s02 复制卡片后副本内容与原卡片一致 — FAIL

- 对比上一轮：PASS → FAIL
- 步骤成功率：0.6666666666666666; 规则通过率：1.0
- 报告中的失败步骤：Step 7 `wait` `Getting started1`：等待元素超时: Getting started1；Step 8 `wait` `div[role='button']`：等待元素超时: div[role='button']；Step 9 `hover` `div[role='button']`：返回 False/未执行
- 报告摘要问题：步骤7失败：等待元素超时，无法找到侧边栏中的'Getting started1'看板，可能看板名称或路径与预期不符。；步骤8失败：等待卡片列表渲染超时，无法定位卡片列表元素，可能页面结构或选择器有误。；步骤9失败：无法悬停到第一张卡片，因前置步骤失败导致无法继续。
- 失败原因：同 f020_s01，另外还依赖错误固定名 `Getting started1`。
- 真实操作步骤：同 f020_s01，且验证副本内容应打开原卡和副本分别读取标题/描述/标签。
- 具体修改方法：修固定名和 Copy 入口后再实现内容比对。
- 优先级：P3

### f022_s01 成功编辑卡片标题 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：0.6666666666666666; 规则通过率：0.0
- 报告中的失败步骤：Step 7 `click` `div[role='button']`：click 返回 False；Step 8 `click` `[contenteditable='true']`：click 返回 False；Step 9 `input` `[contenteditable='true']`：input_text 返回 False
- 报告摘要问题：步骤7点击第一张卡片失败，导致后续所有编辑操作无法执行；步骤8点击标题编辑区域失败，可能因卡片未打开或元素定位错误；步骤9输入新标题失败，因前序步骤未成功
- 失败原因：点击 `div[role=button]` 与 `[contenteditable=true]` 是旧假设；真实卡片标题在 CardModal header：`CardModal_headerTitle`，编辑入口是 header 右侧 `button[title="Edit Card"]` 或点击标题。
- 真实操作步骤：真实路径：点击 `[class*=Card_wrapper]` → URL `/cards/` → 点击标题 `CardModal_headerTitle` 或 `Edit Card` → 修改标题 → Save/Enter。
- 具体修改方法：新增 edit_card_title helper；不要假定 contenteditable。先修 open_first_card scope。
- 优先级：P2

### f022_s02 取消编辑卡片标题 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：0.6666666666666666; 规则通过率：0.0
- 报告中的失败步骤：Step 7 `click` `div[role='button']`：click 返回 False；Step 8 `click` `[contenteditable='true']`：click 返回 False；Step 9 `input` `[contenteditable='true']`：input_text 返回 False
- 报告摘要问题：步骤7点击第一张卡片失败，导致后续所有与卡片交互的步骤均无法执行；卡片标题编辑区域未出现，无法验证取消编辑后的可见性
- 失败原因：同 f022_s01，且取消编辑要确认编辑表单已打开。
- 真实操作步骤：真实路径：打开卡片详情 → 进入标题编辑 → 输入临时标题 → Escape/Cancel → 验证原标题未变。
- 具体修改方法：取消逻辑禁止 Save fallback；按真实标题编辑控件实现。
- 优先级：P2

### f023_s01 为卡片添加标签 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：0.9090909090909091; 规则通过率：0.0
- 报告中的失败步骤：Step 8 `wait` `div[role='dialog']`：等待元素超时: div[role='dialog']
- 报告摘要问题：步骤8等待卡片详情弹窗超时，导致后续步骤在弹窗未出现的情况下继续执行；规则验证实际结果中核心预期（弹窗可见）未通过，功能未正确完成
- 失败原因：等待 `div[role=dialog]` 错误；真实卡片详情没有 role dialog，是 `CardModal_wrapper`。标签入口是 `button[title="Add Label"]`。
- 真实操作步骤：真实路径：打开卡片 → `button[title="Add Label"]` → Popup `Filter By Labels` → 点击已有标签（如 Best Practices/Docs/Sample Label/Unique Feature）→ 验证卡片标签出现。
- 具体修改方法：把 CardModal 等待条件改为 `/cards/` 或 `[class*=CardModal_wrapper]`；新增 add_label helper。
- 优先级：P2

### f023_s02 为卡片设置截止日期 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：0.875; 规则通过率：0.0
- 报告中的失败步骤：Step 5 `wait` `div[role='dialog']`：等待元素超时: div[role='dialog']
- 报告摘要问题：步骤5等待卡片详情弹窗超时，弹窗未出现；备选步骤5b虽然点击了看板名称进入项目，但后续步骤URL跳回根路径，操作上下文可能已丢失；最终页面URL为https://demo.4gaboards.com/，并非卡片详情弹窗可见状态
- 失败原因：卡片场景被错误带到了根路径/错误上下文，并等待 `div[role=dialog]`；真实截止日期入口是 CardModal 里的 `button[title="Add Due Date"]`。
- 真实操作步骤：真实路径：打开卡片 → `button[title="Add Due Date"]` → Popup `input[name=date]` / placeholder `Enter due date...` → 选择日期或填日期 → Save；可选 Remove。
- 具体修改方法：修前置分类，卡片/看板场景优先进入 board/card，不要走 user settings；新增 set_due_date helper。
- 优先级：P2

### f023_s03 为卡片添加成员 — FAIL

- 对比上一轮：PASS → FAIL
- 步骤成功率：0.9; 规则通过率：1.0
- 报告中的失败步骤：Step 8 `wait` `div[role='dialog']`：等待元素超时: div[role='dialog']
- 报告摘要问题：步骤8等待卡片详情弹窗（div[role='dialog']）超时失败，但后续步骤9和10仍继续执行并标记成功，说明自动化流程未正确处理弹窗缺失的异常；步骤9和10的点击操作可能未在卡片详情弹窗内执行，导致成员添加实际未生效，但规则验证结果却显示通过，存在验证与执行轨迹不一致
- 失败原因：仍等待错误的 `div[role=dialog]`；虽然后续点了成员相关按钮，但没有确认在 CardModal 里执行。
- 真实操作步骤：真实路径：打开卡片 → `button[title="Add Member"]` → Popup `input[placeholder="Search members..."]` → 点击候选用户项。
- 具体修改方法：新增 add_card_member helper；验证应读取 CardModal 成员头像/成员区，而不是只靠页面文本。
- 优先级：P2

### f024_s01 编辑卡片描述 - 添加彩色文本和代码块 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：0.6666666666666666; 规则通过率：0.0
- 报告中的失败步骤：Step 7 `click` `[class*='Card_wrapper']`：click 返回 False；Step 8 `click` `[class*='CardModal_descriptionText']`：click 返回 False；Step 9 `click` `button[aria-label='Add colored text']`：click 返回 False
- 报告摘要问题：步骤7点击第一张卡片失败，导致后续所有操作无法执行；描述区域未出现，无法进入编辑模式；彩色文本和代码块均未添加成功
- 失败原因：卡片详情未打开导致描述区和工具栏失败；真实描述编辑入口和工具栏已确认存在。
- 真实操作步骤：真实路径：打开卡片 → `button[title="Edit Description"]` 或描述文本按钮 → 出现 textarea `placeholder="Enter description..."`；工具栏有 `Add colored text`、`Insert code`、`Insert Code Block`；最后 Save。
- 具体修改方法：先修 open_first_card；描述编辑使用 textarea/w-md-editor，不是 `.ProseMirror`。按钮用 title 定位。
- 优先级：P2

### f024_s02 编辑卡片描述 - 添加表格和@提及 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：0.6666666666666666; 规则通过率：0.0
- 报告中的失败步骤：Step 7 `click` `[class*='Card_wrapper']`：click 返回 False；Step 8 `click` `[class*='CardModal_descriptionText']`：click 返回 False；Step 9 `click` `button[aria-label='Insert table']`：click 返回 False
- 报告摘要问题：步骤7点击第一张卡片失败，导致后续所有步骤无法执行；所有规则验证结果均为未通过，说明功能未完成或页面状态异常；实际执行轨迹与预期步骤不一致（多了登录、创建列表/卡片等步骤），但核心失败点在于卡片详情未打开
- 失败原因：同 f024_s01；原步骤 `button[aria-label="Insert table"]` 不贴合真实 DOM，真实按钮 title 是 `Add table`。@提及入口需要在编辑器内输入 `@` 后选择候选。
- 真实操作步骤：真实路径：Edit Description → `button[title="Add table"]` → textarea 里输入/确认；@提及通过 textarea 输入 `@` + 用户名。
- 具体修改方法：把 Insert table selector 改为 title `Add table`；@提及若无候选用户，标 BLOCKED 或只验证文本插入。
- 优先级：P2

### f024_s03 编辑卡片描述 - 使用快捷键添加粗体和斜体 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：0.6666666666666666; 规则通过率：0.0
- 报告中的失败步骤：Step 7 `click` `[class*='Card_wrapper']`：click 返回 False；Step 8 `click` `[class*='CardModal_descriptionText']`：click 返回 False；Step 9 `input` `.ProseMirror`：input_text 返回 False
- 报告摘要问题：步骤7点击第一张卡片失败，无法打开卡片详情视图。；后续所有依赖卡片详情视图的步骤（点击描述、输入文本、使用快捷键）均因前置步骤失败而无法执行。；规则验证实际结果中所有三项预期均未通过，表明功能未正确完成。
- 失败原因：描述编辑器真实控件不是 `.ProseMirror`，而是 w-md-editor textarea；粗体/斜体按钮 title 分别是 `Add bold text (ctrl + b)`、`Add italic text (ctrl + i)`。
- 真实操作步骤：真实路径：Edit Description → textarea → 使用快捷键 Ctrl/Meta+B、Ctrl/Meta+I 或点击对应 title 按钮 → Save。
- 具体修改方法：替换 `.ProseMirror` 为描述 textarea；快捷键按平台使用 Meta/Control；验证保存后的 markdown/渲染内容。
- 优先级：P2

### f025_s01 切换侧边栏样式 - 从紧凑到正常宽度 — PASS

- 对比上一轮：PASS → PASS
- 步骤成功率：1.0; 规则通过率：1.0
- 失败原因：无，本轮通过。当前报告中 PASS，暂不需要针对该用例修复；但如果依赖 DD/TN 等共享账号状态，后续建议改为动态读取。
- 修改建议：暂不优先修改；后续统一做共享账号状态隔离和动态文本读取即可。

### f025_s02 切换侧边栏样式 - 从正常到紧凑宽度 — PASS

- 对比上一轮：PASS → PASS
- 步骤成功率：1.0; 规则通过率：1.0
- 失败原因：无，本轮通过。当前报告中 PASS，暂不需要针对该用例修复；但如果依赖 DD/TN 等共享账号状态，后续建议改为动态读取。
- 修改建议：暂不优先修改；后续统一做共享账号状态隔离和动态文本读取即可。

### f025_s03 侧边栏样式切换在项目详情页也生效 — FAIL

- 对比上一轮：FAIL → FAIL
- 步骤成功率：1.0; 规则通过率：0.5
- 报告中的失败步骤：没有单步失败，但最终规则/LLM 判定失败，通常是预期名称或 URL 校验不匹配。
- 报告摘要问题：进入的页面是项目详情页（/projects/），而非项目看板页（/boards/），与预期URL不符
- 失败原因：`open_first_board` DOM 探测误点了项目 `Updated Project Name` 却返回 True；最终 URL 是 `/projects/` 而不是 `/boards/`。
- 真实操作步骤：真实路径：Dashboard 项目链接是 `a[href*=projects]`；看板链接必须是 `a[href*=boards]`。打开看板后必须验证 URL 包含 `/boards/`。
- 具体修改方法：修改 `open_first_board`：只允许点击 href 含 `/boards/` 的元素；DOM 探测点击后必须检查 URL，失败则返回 False 并继续找 board link。
- 优先级：P1

## 五、可直接交给成员 D 的任务拆分

1. 修执行器基础稳定性：`_visible_dialog_or_page`、`_find` fallback、`open_first_board` URL 校验。验收：Add List/Add Card/Card_wrapper 在真实看板页可被单测/冒烟脚本找到。
2. 修前置条件分类：项目设置、用户设置、卡片/列表/看板页面分别进入正确路径。验收：f006_s02、f008_s02 不再停在 `/settings/profile`。
3. 补测试数据与动态数据：增加 `test_data/trello_export.json`；固定项目/看板/列表名改为运行时变量或前置创建。验收：固定名称失败归零。
4. 做基础 helper：Add Board、Add List、Add Card、Open Card、Add Member、Add Label、Set Due Date、Edit Description。验收：对应 f009/f013/f018/f023/f024 组通过率明显提升。
5. 修验证策略：取消类必须确认弹窗/表单曾打开；关键动作失败时不能仅因目标文本不存在而 PASS。验收：报告不再出现“关键步骤失败但 inline_pass_rate=1.0”的假通过。
6. 最后处理复杂交互：列表拖拽、卡片拖拽、Move/Copy。先探测 `Edit Card` 或隐藏菜单，再实现；没有 DOM 证据前先标为待补证据。
