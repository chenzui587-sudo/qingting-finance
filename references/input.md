# 检查器输入与输出

Python 3.10+，纯标准库；不联网、不识别票据、不访问税务系统、不自动保存文件。AI 根据已核实资料整理输入，检查器检查数据一致性与零业务候选条件，**不验证证据真实性**。

开始真实事项请复制 `assets/intake-template.json` 到私有目录。金额以人民币元为单位，用十进制字符串，如 `"0.00"`；未知用 `null` 或保留缺项，不能为了通过检查补零。最多两位小数，不能传 JSON 数字、负数、NaN、千位分隔符或指数形式。金额为各类发生额的非负绝对值，退款/红字单独记录，不用收支相抵后的净额。校验拒绝未知字段与重复 JSON 键，防止拼写错误被忽略。

## 顶层

| 字段 | 规则 |
| --- | --- |
| `schema_version` | 固定整数 `1` |
| `case_id` | 匿名编号；小写字母开头，后续字母/数字/连字符，最长 64 位；不要放税号、姓名或账号 |
| `mode` | `real` 真实资料 / `synthetic` 虚构测试。把示例模式改成 real 不代表资料变真 |
| `as_of` | 本次评估日期，`YYYY-MM-DD`；不自动采用电脑时区或当前日期 |
| `taxpayer` | 主体与征收方式，见下 |
| `registration` | 当前税费种认定及完整义务清单核对，不仅是营业执照 |
| `policy_check` | 本次查阅政策日期与来源；要与 `as_of` 一致，否则转复核。此为产品工作流要求，不是法定有效期 |
| `obligations` | 非空列表，保留所有已识别义务，包括本版不支持的税种 |

`taxpayer`：

- `entity_type`：`individual_business` 个体工商户；`company` 公司、`sole_proprietorship` 个人独资企业、`partnership` 合伙企业、`other` 其他为范围外。未知 `null`。
- `region`：实际省/市及主管税务地区，用于人工核实地方口径；代码不从地区推断税率或截止日。
- `vat_status`：`small_scale` / `general` / `null`。
- `business_income_method`：`actual` 查账征收 / `fixed_quota` 定期定额户 / `deemed` 其他核定征收 / `null`。定期定额户整体转核对；其他核定的经营所得转核对。
- `business_start_month`：`YYYY-MM`，开始经营月份。经营所得资料从本年 1 月或本年开始经营月份的月初起累计，以较晚者为准；不能猜为本季第一天。

`registration`：`source_ref` 为已查看资料的私有引用；`checked_for_period` 和 `obligations_complete` 为 `true/false/null`，分别表示已针对本次全部期间核对、已核对全部应报事项。清单遗漏与税务认定冲突仍需人工解决。

`policy_check`：`checked_on` 日期，`source_refs` 为实际查阅的官方来源列表。模板不预填“已复核”。

## 每项义务

- `tax_kind`：`vat`、`business_income_prepaid`；其他可填 `business_income_annual`、`payroll`、`surcharges`、`stamp`、`social_insurance`、`financial_reports`、`other`，会保留为范围外待办。
- `required`：`true` 已列为本期应申报；`false` 仅表示已核实清单未列；`null` 未知。`false` 不证明没有法律义务，不输出免申报许可。
- `period`：`start`、`end` 为税种所属期；`frequency` 为 `monthly/quarterly/annual/other`；`deadline`、`deadline_source` 是该税种当期官方征期或系统显示截止日与来源。当前仅支持 2026 完整自然月/季，尚未结束、逾期、缺截止日均不生成候选。
- `facts`：下列资料均以该税种需要的期间口径汇总；未知可用 `null`。同税种同所属期不能出现重复条目。

## facts

`coverage_start/end`：资料覆盖时间。增值税为当期；经营所得为年内累计，必须截止所属期末。`evidence_refs`：核对过的流水、发票、成本、历史申报和预填信息引用列表；空列表阻止候选。引用不应含密码、令牌或原始客户数据。

`amounts` 的各项均必须明确。它们是筛查维度，可能存在交叉，程序**不会把它们相加计算税基**：

| 字段 | 含义 |
| --- | --- |
| `invoiced_revenue` | 已开票收入发生额；不能只看开票软件余额 |
| `uninvoiced_revenue` | 未开票但已确认应计入该税种该期间的收入 |
| `exempt_revenue` | 免税收入，仍不能当作无收入 |
| `other_revenue` | 其他应申报收入，含非货币收入等已确认事项 |
| `costs_and_expenses` | 成本、费用、税金、损失等实际支出/计提的筛查金额；折旧和手续费不能漏掉。增值税费用非零不直接否定小规模无销售候选；经营所得费用非零需据实填表 |
| `refunds_and_red_invoices` | 退款及红字发生额的绝对值，不能与收入相抵后只传零 |
| `advance_receipts` | 预收款，包括待核实的预收会员费。非零转纳税时点复核，不直接当零或直接当收入 |
| `tax_prepaid` | 该申报口径内已缴/预缴税额 |
| `carryforward_items` | 留抵、可弥补亏损、历史结转等涉及的非零金额，取绝对值；不能清空 |
| `other_return_items` | 其他实际需要填写的非零金额，包括适用扣除、减免、调整、系统预填等；未知用 null，不能为了全零忽略栏目 |
| `non_revenue_receipts` | 已有证据确认的非收入收款，如老板投入/借款；非零不单独否定候选，但仍须完成分类核对 |

`checks` 每项为 `true/false/null`，必须确实完成才填 `true`：

- `all_receipt_channels_reconciled`：全部适用收款渠道及代收账户覆盖、核对完成。
- `invoice_records_reviewed`：已核对开票、红冲、代开和历史记录。
- `costs_reviewed`：已核对费用、计提、租金、工资、银行手续费等。
- `prior_returns_reviewed`：已查前期及年内累计申报、预缴、欠报和结转。
- `portal_prefill_reviewed`：已查看本期真实税务表单预填；没登录过不得勾选完成。
- `tax_events_reviewed`：已核对没有收款但可能已发生纳税义务的交易及跨期归属。
- `deductions_and_carryforwards_reviewed`：已核对扣除、优惠与结转；不能把个人减除费用机械填零。

`flags` 每项为 `true/false/null`：`unclassified_receipts` 未分类收款、`unresolved_tax_timing` 未决时点、`special_transactions` 特殊业务、`nonzero_prefill` 系统非零预填。只有已确认不存在才能填 `false`；`null` 表示待核查。明确存在任一项即转复核。

## 输出

`results` 按税种保留所有问题，最高优先级状态作为标题：范围外 > 非零事项 > 资料不足 > 人工核对 > 零业务候选。发现非零事项不表示还缺的材料已经补齐。

同税种所属期重叠会转复核。若同一输入已有较早期累计收入、费用或预缴，后期对应累计却变零，也会转复核；这不能替代对未提供历史期间的调查。`required=false` 但存在非零事实时仍核对实际义务。

`tax_amount` 始终为 `null`；`submission_status` 始终为 `not_performed`；`can_auto_submit` 始终为 `false`。`overall_status=draft_for_review` 仅表示列出事项的草稿可供继续核对，不表示资料客观真实、所有税费已处理或已获得提交授权。`input_sha256` 仅标识本次输入版本，不是税务数字签名。

退出码 `0` 表示已完成评估（结果仍可能为范围外/资料不足等）；`2` 表示输入文件或结构无效。调用方必须读取状态，不能把进程退出码 0 当成可以申报。
