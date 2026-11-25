# 本地配置：每人独立，不随GitHub发布

配置位置：若有 `XDG_CONFIG_HOME`，用其下 `invoice-reimbursement/profile.json`；否则用 `~/.config/invoice-reimbursement/profile.json`。不放在技能Git目录里，更新不会改动它。读取文件内容时只取本次必需字段，不复制到公开仓库。没有配置时按 `config/profile.example.json` 的结构在本机新建；不要覆盖既有配置。

首次需确认：报销姓名、Excel部门名、飞书申请部门/组织路径、公司开票主体、日补助标准、实际使用的付款类别、发票性质和收款字段。公司允许的补充凭证规则单独确认，不从作者试跑推定所有公司都允许。

| 字段 | 用途 |
| --- | --- |
| `claimant_name` | Excel报销姓名 |
| `excel_department` | 报销单部门文字 |
| `feishu_department_name` / `feishu_department_path` | 飞书真实部门及组织路径 |
| `invoice_entity` / `invoice_nature` | 主体及性质；每票仍需核对 |
| `default_payment_category` | 未另指定时的类别，主内容与选定类别一致 |
| `daily_allowance` / `currency` | 已确认的每日标准和币种，不等于天数规则 |
| `payee` / `bank_name` / `bank_account` | 三项均用字符串，`"000"`有确认依据才使用 |
| `supplemental_receipts.allowed` | `true`为已由使用者确认公司允许，`false`为不允许，`null`为未确认 |
| `supplemental_receipts.basis` | 许可依据和适用范围；属于用户确认，不冒称独立核验财务制度 |
| `template_path` / `archive_root` | 此人的模板与归档位置；不适用于其他电脑 |

示例仅说明结构，不是财务制度，空值不是0或默认许可。日标准80元也须由该使用者确认。个人报销的起止日期、计补日、金额、票据、审批编号与链接记录在本次资料夹，不塞进长期配置。默认Excel先确认、最终留草稿；当次用户可明确授权提交审批，不能存成永久代提交权限。

若用户更换公司、身份或明确改规则，按当前说明更新本地配置并注明依据；不为每笔报销重复询问同一已确认的公司规则。不要将飞书Cookie、邮箱密码、API密钥、验证码或登录数据写进配置。
