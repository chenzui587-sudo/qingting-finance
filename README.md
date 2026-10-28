# 蜻蜓财务 · Qingting Finance

**先判断能不能零申报，再准备申报材料。**

面向中国大陆个体工商户的财税 Agent Skill。帮助 Codex 等支持 Agent Skills 的助手核对经营事实、识别不能直接填零的情况，并生成逐税种申报准备底稿。

当前版本 **0.2.0 · 早期试用**。本地零申报检查程序和虚构场景已测试；新增社保增减员、缴费与周期任务的协作流程。尚未经过真实税务/社保系统逐表验收或独立税务专业人员审核。它不提供自动报税 API，不把“零业务候选”当作申报完成。

## 解决什么问题

| 你说的情况 | 技能应如何处理 |
| --- | --- |
| “没有开票” | 继续核对未开票、现金、平台及个人账户代收收入 |
| “免税，不用交钱” | 保留实际销售额和减免事项，不把全表填零 |
| “没收入，只有房租” | 分开核对增值税和经营所得，保留成本费用 |
| “这季没收入，上季有” | 经营所得继续使用年内累计数据 |
| “收款和退款抵完是零” | 分开记录原始发生额，不用净额掩盖业务 |
| “定期定额，没开门” | 核对核定与简易申报安排，不直接判零 |
| “资料没找到，就按零吧” | 保留未知和缺项，不生成零业务候选 |

## 当前范围

- 2026 年完整自然月/季的小规模增值税，以及查账征收经营所得预缴的零业务候选筛查。
- 逐税种期间检查、年内累计检查、非零事项与资料缺口提示。
- 本地 JSON / Markdown 草稿与后续申报回执清单。
- 其他税费与年度汇算保留为待办，不自动判定无需申报。
- 社保增减员的资料、变更预览、受理及生效回查流程；区分单位职工和灵活就业参保。
- 定时核对官方社保代扣结果，或准备经授权的缴费协作任务；实际所在地、身份、执行模式和时间确定后再接入调度工具。

检查脚本不包含：正式计税、发票验真、真实流水自动识别、税务账号登录、自动提交、缴款、年度汇算计算。一般纳税人、核定征收、特殊业务、逾期和更正等转进一步核对。

社保支持目前是 Agent 办理核对流程，**不是已验证的各地社保 API 或自动扣费服务**。官方银行代扣与 AI 定时任务分开：建立提醒不会开通代扣，任务运行成功不代表缴费成功。参考 [社保与定时任务](references/social-insurance.md)。

## 使用

需要 Python 3.10+，不需要安装第三方包或提供 API Key。先运行虚构示例：

```bash
python3 scripts/assess_zero.py examples/no-activity.json --format markdown
python3 scripts/assess_zero.py examples/uninvoiced-income.json
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

`examples/` 全部是虚构案例，日期、截止日和来源引用仅供测试，不能当作真实地区的征期或申报资料。真实事项从 `assets/intake-template.json` 开始，保留未知值；不要只改示例名称和模式来制造“资料已核对”。

AI 调用示例：

> 使用 $qingting-finance 帮我核对个体户本期能否零申报。先利用已有资料，缺项再问，生成逐税种底稿。

程序退出码 `0` 只表示评估完成，**不表示符合零申报**。查看每项 `status` 和 `issues`；`tax_amount` 始终为 `null`，`can_auto_submit` 始终为 `false`。

## 安装为 Codex 技能

取得源码后，在此项目根目录运行以下命令。目标已存在时 `ln` 会失败；先比较已有版本，不覆盖它。

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
ln -s "$PWD" "${CODEX_HOME:-$HOME/.codex}/skills/qingting-finance"
```

链接依赖源码目录存在且可访问。其他电脑可把整个目录复制到其技能目录。新开会话后确认技能已被发现；已运行会话不保证自动刷新。

## 文件

- [SKILL.md](SKILL.md)：给 AI 的入口与操作边界。
- [references/input.md](references/input.md)：输入口径及状态含义。
- [references/policies.md](references/policies.md)：官方依据、日期和适用范围。
- [references/filing.md](references/filing.md)：实际办理与回执核对。
- [references/social-insurance.md](references/social-insurance.md)：社保增减员及定时缴费流程。
- [assets/social-insurance-workpaper.md](assets/social-insurance-workpaper.md)：私有办理事项和任务定义模板。
- [scripts/assess_zero.py](scripts/assess_zero.py)：离线检查器。
- [tests/test_assess_zero.py](tests/test_assess_zero.py)：可复现的合成案例测试。
- [VALIDATION.md](VALIDATION.md)：本版验证结果与尚未覆盖的验收。

## 数据与贡献

脚本只读取明确指定的输入文件并向终端输出草稿，不联网、不上传、不建立后台任务。使用云端 AI 整理资料时，模型服务的数据处理范围另行适用，不能把“本地脚本”说成“整个过程绝不离开本机”。

真实客户资料保存在仓库外。提交问题或 PR 时只用虚构/脱敏案例，提供预期结果、实际结果及适用的官方依据，不提交税号、身份信息、账单原件、密码或回执原件。

新增规则要附来源和适用期，以及能够区分正确/错误行为的案例。不要为了扩大支持范围，仅删除保护条件或把未知值改成默认零。

本项目的代码与原创文档采用 [MIT 许可证](LICENSE)。外链法规和第三方资料不随本项目重新授权。“蜻蜓财务”是本项目名称，不表示政府认证或商标注册状态。
