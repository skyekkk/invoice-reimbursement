# 发票报销助手

公开分享地址：<https://github.com/skyekkk/invoice-reimbursement>

把本次出差行程告诉AI，它会先检查此仓库更新，再下载相关票据、检查遗漏，按连续出差分段填写Excel，等你确认后准备飞书付款申请。默认由你亲自提交；你当次明确授权后，助手可以提交审批申请。提交审批不等于财务已审批或款已到账。

## 给同事：复制这段话给Codex

> 请帮我安装发票报销助手：https://github.com/skyekkk/invoice-reimbursement 。按仓库首页安装完整技能并保留每次使用前检查更新的功能。已有同名技能先备份比较，不要覆盖。请检查Git和Python 3是否可用，安装后运行更新检查并读取技能入口，按当前宿主要求重新加载。我的姓名、公司规则和账号权限由我自己配置，不沿用作者资料。

安装好后，直接说“帮我报销这次出差”，说明日期、城市、交通、落地接送、住宿由谁预订及付款。需要邮箱/飞书登录时由你本人完成。技能不包含作者的邮箱或飞书权限，也不会要求你提供密码给别人。

首次使用会集中核对报销姓名、部门、公司主体、每日补助和收款字段，保存在你电脑的独立配置中；之后复用。每家公司是否接受其他真实行程发票作补充凭证，需由该公司规则确认，不能直接套用其他人的处理方式。

## 每次更新怎样生效

- 作者将新版推送至main后，同事下次启动报销会先联网检查，发现新版就备份旧版，再更新并重新读取规则。
- 不需要同事注册GitHub，也不是后台持续推送。按下面方式完整安装才支持更新；仅手动解压ZIP或复制SKILL.md不够。
- 使用者有本地修改、更新源改变或版本分叉时，程序停止覆盖并提示；个人配置在技能目录外，正常更新会保留。
- 联网失败会明确提示，不能假称已是最新版。排查后仍失败，可先只读整理；要用旧版填表/操作飞书，需你明确同意本次离线继续。
- 更新只下载技能文件，不上传个人票据，不提交报销，不改已创建的申请。后续作者需要实际推送，新版才会生效。

## 给AI：安装步骤

推荐官方接口安装，只需Python 3；可选Git安装还需Git。运行报销需当前宿主可用的PDF/Excel处理能力、邮箱和飞书界面或连接器，不假设所有宿主都有相同工具。更新脚本只用Python标准库，不需要额外Python包。

1. 来源固定为 `https://github.com/skyekkk/invoice-reimbursement`。公开仓库优先匿名HTTPS，不要求同事登录GitHub。
2. Codex尊重已有 `CODEX_HOME`，默认安装目录 `~/.codex/skills/invoice-reimbursement`；其他宿主按其实际技能目录。已有同名文件时先读、比较并备份到技能目录之外，不删除/覆盖新旧两份。先在临时目录验证克隆再切换。
3. 推荐：通过官方接口取得main的实际提交SHA，再从 `https://api.github.com/repos/skyekkk/invoice-reimbursement/contents/scripts/github_snapshot.py?ref=<实际SHA>` 下载bootstrap脚本（JSON的content为base64），保存到临时目录。核对来自指定仓库并阅读脚本，再运行下面的安装命令；实际SHA必须从 `https://api.github.com/repos/skyekkk/invoice-reimbursement/commits/main` 取得，不编造或写死旧SHA。只从已确认的该来源下载，不接受第三方镜像。该方式会下载并校验完整目录，不只是安装脚本本身。

```bash
python3 -B <临时脚本>/github_snapshot.py --install <不存在的技能目录>
python3 -B <技能目录>/scripts/sync_skill.py
```

可选Git方式（主站Git连接可用时）：下列路径由安装环境解析，不照抄作者电脑路径。

```bash
git clone --branch main --single-branch https://github.com/skyekkk/invoice-reimbursement.git <技能目录>
git -C <技能目录> config --local skill.trustedOrigin https://github.com/skyekkk/invoice-reimbursement.git
python3 -B <技能目录>/scripts/sync_skill.py
```

4. 核实安装输出`installed`，更新检查为 `current`（若期间发布新版返回`updated`则重新读取入口）。检查 `SKILL.md`、`scripts/`、`references/`、`assets/报销单-空白.xlsx`、`config/profile.example.json` 和 `agents/openai.yaml` 均存在。接口安装保留隐藏文件 `.skill-install.json`，Git安装保留 `.git`，不能只复制说明文件。
5. 读取 `references/profile.md`，在技能目录外建立使用者配置，空白模板需核对公司是否适用。首次未提供的配置可在真实报销时集中询问，不编造字段。模板/配置/报销资料均不提交Git。
6. 按宿主要求重新加载技能。文件安装成功与宿主已载入是两件事，未实际载入不能声称自动触发已验证。运行前每次检查的规则已写在技能入口，助手仍需遵守，脚本不会自行驻留后台。

## 本次2.0.0升级

- 分段日期标签和计补日期分开，前晚准备费用并入后段但不自动增加补助。
- 新邮件补票、业务退改签、客户订房与付款区别、含高速费金额核对。
- 真实行程和补充票据分开记录，逐张分配；票面超过实际支出的部分不加报销，避免重复。
- PDF按实际用途命名，混合材料拆分，同类发票可完整合并以满足附件上限。
- Excel先确认，草稿保存后回读；正式提交依据当次明确授权，保存真实审批状态并避免重复提交。
- 每次运行检查GitHub，先备份再快进更新，本地修改和个性配置保留。
- 原个人样本改为脱敏空白模板。仓库不带真实票据、个人行程、私有审批链接或凭据。

## 给维护者：发布新版

在开发副本更新，递增 `VERSION`，测试 `python3 -B -m unittest discover -s tests -v`，并用宿主的skill校验工具检查入口；修改模板时检查隐私、公式和排版。只提交通用文件，不提交真实工作资料/本地profile/.env/登录信息。正常提交并推送main；Git连接不可用时可用官方Git数据API基于远端当前提交创建后续提交并更新引用，禁止强推覆盖。发布后核对远端提交，可创建同版本Release。个人安装目录有本地未发布改动会阻止自动同步，应在开发副本发布，不强行覆盖。
