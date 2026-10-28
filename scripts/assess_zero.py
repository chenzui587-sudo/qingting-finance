#!/usr/bin/env python3
"""Offline zero-activity screening. Never calculates or files tax."""
import argparse
import calendar
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys

VERSION = "0.2.0"
SUPPORTED_YEAR = 2026
POLICY_SNAPSHOT = "2026-10-27"
AMOUNTS = (
    "invoiced_revenue", "uninvoiced_revenue", "exempt_revenue", "other_revenue",
    "costs_and_expenses", "refunds_and_red_invoices", "advance_receipts",
    "tax_prepaid", "carryforward_items", "other_return_items", "non_revenue_receipts",
)
CHECKS = (
    "all_receipt_channels_reconciled", "invoice_records_reviewed", "costs_reviewed",
    "prior_returns_reviewed", "portal_prefill_reviewed", "tax_events_reviewed",
    "deductions_and_carryforwards_reviewed",
)
FLAGS = ("unclassified_receipts", "unresolved_tax_timing", "special_transactions", "nonzero_prefill")
LABELS = {
    "zero_activity_candidate": "零业务候选，待逐栏核对",
    "nonzero_return": "存在非零事项，不能整表填零",
    "insufficient_data": "资料不足",
    "manual_review": "需要进一步核对",
    "out_of_scope": "超出本版自动筛查范围",
    "not_listed": "本期清单未列应报，不代表免税",
}
PRIORITY = {"out_of_scope": 5, "nonzero_return": 4, "insufficient_data": 3,
            "manual_review": 2, "zero_activity_candidate": 1, "not_listed": 0}
TAX_LABELS = {
    "vat": "增值税", "business_income_prepaid": "经营所得预缴",
    "business_income_annual": "经营所得年度汇算", "payroll": "工资个税扣缴",
    "surcharges": "附加税费", "stamp": "印花税", "social_insurance": "社保",
    "financial_reports": "财务报表", "other": "其他义务",
}


class InputError(ValueError):
    """Messages contain field paths, not submitted values."""


def obj(value, allowed, path):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise InputError(f"{path}: 必须是对象或 null")
    if set(value) - set(allowed):
        raise InputError(f"{path}: 含未定义字段，请对照输入说明；不要放入身份或登录信息")
    return value


def text_value(value, path):
    if value is None:
        return None
    if not isinstance(value, str):
        raise InputError(f"{path}: 必须是字符串或 null")
    return value.strip() or None


def choice(value, allowed, path):
    value = text_value(value, path)
    if value is not None and value not in allowed:
        raise InputError(f"{path}: 不是支持的枚举值")
    return value


def boolean(value, path):
    if value is not None and type(value) is not bool:
        raise InputError(f"{path}: 必须是 true、false 或 null，不能用数字或字符串代替")
    return value


def day(value, path):
    value = text_value(value, path)
    if value is None:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise InputError(f"{path}: 日期必须为 YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InputError(f"{path}: 无效日期") from exc


def money(value, path):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9]\d{0,14})(?:\.\d{1,2})?", value):
        raise InputError(f"{path}: 金额须为非负十进制字符串，至多两位小数；未知用 null")
    return Decimal(value)


def refs(value, path):
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
        raise InputError(f"{path}: 必须是非空引用字符串组成的列表或 null")
    return value


def validate(raw):
    root = obj(raw, {"schema_version", "case_id", "mode", "as_of", "taxpayer",
                     "registration", "policy_check", "obligations"}, "root")
    if type(root.get("schema_version")) is not int or root["schema_version"] != 1:
        raise InputError("schema_version: 仅支持整数 1")
    case_id = root.get("case_id")
    if not isinstance(case_id, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", case_id):
        raise InputError("case_id: 使用 1—64 位匿名小写字母/数字/连字符编号，以字母开头")
    mode = choice(root.get("mode"), {"synthetic", "real"}, "mode")
    as_of = day(root.get("as_of"), "as_of")
    t = obj(root.get("taxpayer"), {"entity_type", "region", "vat_status",
            "business_income_method", "business_start_month"}, "taxpayer")
    taxpayer = {
        "entity_type": choice(t.get("entity_type"), {"individual_business", "company",
            "sole_proprietorship", "partnership", "other"}, "taxpayer.entity_type"),
        "region": text_value(t.get("region"), "taxpayer.region"),
        "vat_status": choice(t.get("vat_status"), {"small_scale", "general"}, "taxpayer.vat_status"),
        "business_income_method": choice(t.get("business_income_method"),
            {"actual", "fixed_quota", "deemed"}, "taxpayer.business_income_method"),
    }
    month = text_value(t.get("business_start_month"), "taxpayer.business_start_month")
    taxpayer["business_start_month"] = day(month + "-01", "taxpayer.business_start_month") if month else None
    reg = obj(root.get("registration"), {"source_ref", "checked_for_period", "obligations_complete"}, "registration")
    registration = {
        "source_ref": text_value(reg.get("source_ref"), "registration.source_ref"),
        "checked_for_period": boolean(reg.get("checked_for_period"), "registration.checked_for_period"),
        "obligations_complete": boolean(reg.get("obligations_complete"), "registration.obligations_complete"),
    }
    p = obj(root.get("policy_check"), {"checked_on", "source_refs"}, "policy_check")
    policy = {"checked_on": day(p.get("checked_on"), "policy_check.checked_on"),
              "source_refs": refs(p.get("source_refs"), "policy_check.source_refs")}
    items = root.get("obligations")
    if not isinstance(items, list) or not items:
        raise InputError("obligations: 至少列出一项待核对义务；不得以空列表表示全部无需申报")
    obligations, seen = [], set()
    for i, item in enumerate(items):
        base = f"obligations[{i}]"
        item = obj(item, {"tax_kind", "required", "period", "facts"}, base)
        kind = choice(item.get("tax_kind"), TAX_LABELS, base + ".tax_kind")
        if kind is None:
            raise InputError(base + ".tax_kind: 需要明确税种或 other")
        per = obj(item.get("period"), {"start", "end", "frequency", "deadline", "deadline_source"}, base + ".period")
        period = {k: day(per.get(k), base + ".period." + k) for k in ("start", "end", "deadline")}
        period["frequency"] = choice(per.get("frequency"), {"monthly", "quarterly", "annual", "other"}, base + ".period.frequency")
        period["deadline_source"] = text_value(per.get("deadline_source"), base + ".period.deadline_source")
        if period["start"] and period["end"] and period["start"] > period["end"]:
            raise InputError(base + ".period: 开始日不能晚于结束日")
        if period["deadline"] and period["end"] and period["deadline"] <= period["end"]:
            raise InputError(base + ".period.deadline: 本版定期申报截止日应晚于所属期末")
        key = (kind, period["start"], period["end"])
        if key in seen:
            raise InputError(base + ": 相同税种和所属期重复，先合并并核对资料")
        seen.add(key)
        f = obj(item.get("facts"), {"coverage_start", "coverage_end", "evidence_refs", "amounts", "checks", "flags"}, base + ".facts")
        amounts = obj(f.get("amounts"), AMOUNTS, base + ".facts.amounts")
        checks = obj(f.get("checks"), CHECKS, base + ".facts.checks")
        flags = obj(f.get("flags"), FLAGS, base + ".facts.flags")
        facts = {
            "coverage_start": day(f.get("coverage_start"), base + ".facts.coverage_start"),
            "coverage_end": day(f.get("coverage_end"), base + ".facts.coverage_end"),
            "evidence_refs": refs(f.get("evidence_refs"), base + ".facts.evidence_refs"),
            "amounts": {k: money(amounts.get(k), base + ".facts.amounts." + k) for k in AMOUNTS},
            "checks": {k: boolean(checks.get(k), base + ".facts.checks." + k) for k in CHECKS},
            "flags": {k: boolean(flags.get(k), base + ".facts.flags." + k) for k in FLAGS},
        }
        obligations.append({"tax_kind": kind, "required": boolean(item.get("required"), base + ".required"),
                            "period": period, "facts": facts})
    return {"case_id": case_id, "mode": mode, "as_of": as_of, "taxpayer": taxpayer,
            "registration": registration, "policy_check": policy, "obligations": obligations}


def assess(raw):
    data = validate(raw)
    t, reg, policy, as_of = (data[k] for k in ("taxpayer", "registration", "policy_check", "as_of"))
    results = []
    for index, item in enumerate(data["obligations"]):
        issues, notes = [], []
        kind, period, facts = (item[k] for k in ("tax_kind", "period", "facts"))

        def issue(status, code, field, message, sources=()):
            issues.append({"status": status, "code": code, "field": field,
                           "message": message, "policy_refs": list(sources)})

        def missing(field, message):
            issue("insufficient_data", "MISSING_OR_UNVERIFIED", field, message)

        if data["mode"] is None:
            missing("mode", "区分真实事项与虚构演示")
        if as_of is None:
            missing("as_of", "补充本次评估日期")
        if t["entity_type"] is None:
            missing("taxpayer.entity_type", "查看营业执照登记主体类型")
        elif t["entity_type"] != "individual_business":
            issue("out_of_scope", "ENTITY_SCOPE", "taxpayer.entity_type", "本版仅面向个体工商户，不套用公司或个人独资企业模板", ("P02",))
        if t["business_income_method"] == "fixed_quota":
            issue("out_of_scope", "FIXED_QUOTA_HOUSEHOLD", "taxpayer.business_income_method", "定期定额户需先核对各税种核定与简易申报安排，本版不生成零业务候选", ("P04",))
        if not t["region"]:
            missing("taxpayer.region", "补充实际经营所在地与主管税务地区")
        for k in ("source_ref", "checked_for_period", "obligations_complete"):
            if not reg[k]:
                missing("registration." + k, "核实本期税费种认定与完整应报清单；未列出不等于无义务")
        if not policy["source_refs"] or not policy["checked_on"]:
            missing("policy_check", "记录本次适用官方政策查阅日期和来源；离线整理不能冒充复核完成")
        elif as_of and policy["checked_on"] != as_of:
            issue("manual_review", "POLICY_RECHECK", "policy_check.checked_on", "政策查阅日不是本次评估日，核实适用政策并记录实际查阅日")
        declared_refs = policy["source_refs"] + facts["evidence_refs"] + [reg["source_ref"], period["deadline_source"]]
        if data["mode"] == "real" and any(v and v.startswith("synthetic:") for v in declared_refs):
            missing("evidence_refs", "真实事项中仍含虚构示例引用，必须替换为实际核对依据")
        for k in ("start", "end", "frequency"):
            if period[k] is None:
                missing("period." + k, "从本期待办核对所属期与申报周期")
        if item["required"] is None:
            missing("required", "核对本期该税种是否列为应申报，不能自行假定")

        # A portal's omission is not proof that there is no legal obligation.
        if item["required"] is False:
            if any(v is not None and v > 0 for k, v in facts["amounts"].items() if k != "non_revenue_receipts"):
                issue("manual_review", "UNLISTED_WITH_ACTIVITY", "required", "清单未列应报但已提供非零事项，核实实际义务及清单是否完整，不能直接跳过")
            status = max((v["status"] for v in issues), key=PRIORITY.get, default="not_listed")
            notes.append("仅记录清单未列应报；若有实际应税业务，仍需核实。不能替填零或据此免除其他义务。")
        else:
            if kind not in ("vat", "business_income_prepaid"):
                issue("out_of_scope", "TAX_SCOPE", "tax_kind", "保留该项待办，本版不判定其零申报条件")
            if period["frequency"] not in (None, "monthly", "quarterly"):
                issue("out_of_scope", "PERIOD_SCOPE", "period.frequency", "年度、按次及特殊期间需另行核对")
            start, end = period["start"], period["end"]
            if start and end:
                if start.year != SUPPORTED_YEAR or end.year != SUPPORTED_YEAR:
                    issue("out_of_scope", "YEAR_SCOPE", "period", "本版仅核查 2026 年所属期；历史或新年度先更新规则及验证")
                is_month = start.day == 1 and end == date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
                is_quarter = start.day == 1 and start.month in (1, 4, 7, 10) and end == date(start.year, start.month + 2, calendar.monthrange(start.year, start.month + 2)[1])
                if (period["frequency"] == "monthly" and not is_month) or (period["frequency"] == "quarterly" and not is_quarter):
                    issue("out_of_scope", "PARTIAL_PERIOD", "period", "不是完整自然月/季，不能拼接成普通申报期间")
                if as_of and as_of <= end:
                    issue("manual_review", "PERIOD_NOT_CLOSED", "period.end", "所属期尚未完整结束，不能把当前零发生额当整期零业务")
            if not period["deadline"] or not period["deadline_source"]:
                missing("period.deadline", "核对当地本期真实截止日及来源，不能默认 15 日")
            elif as_of and as_of > period["deadline"]:
                issue("manual_review", "OVERDUE", "period.deadline", "已超过输入的截止日，转逾期/历史申报核对，不直接提交")
            if kind == "vat":
                if t["business_income_method"] is None:
                    missing("taxpayer.business_income_method", "先核实是否属于定期定额户，不能只看小规模身份")
                if not t["vat_status"]:
                    missing("taxpayer.vat_status", "核对增值税纳税人身份")
                elif t["vat_status"] != "small_scale":
                    issue("out_of_scope", "VAT_STATUS", "taxpayer.vat_status", "一般纳税人的进项、留抵等需专门核对", ("P01",))
                expected_start = start
            elif kind == "business_income_prepaid":
                method = t["business_income_method"]
                if method is None:
                    missing("taxpayer.business_income_method", "核对经营所得征收方式")
                elif method != "actual":
                    issue("out_of_scope", "COLLECTION_METHOD", "taxpayer.business_income_method", "核定/定期定额不能仅凭无营业判断零申报", ("P04",))
                began = t["business_start_month"]
                if began is None:
                    missing("taxpayer.business_start_month", "核对开始经营月份，确定年内累计数据覆盖起点")
                if began and end and began > end:
                    issue("manual_review", "BUSINESS_NOT_STARTED", "taxpayer.business_start_month", "开始经营月份晚于所属期，需核对登记及筹备期间义务")
                expected_start = max(date(end.year, 1, 1), began) if end and began else None
            else:
                expected_start = None
            if not facts["evidence_refs"]:
                missing("facts.evidence_refs", "提供经核对的账单、发票记录、历史申报及预填数据引用；不上传原件")
            for field, expected in (("coverage_start", expected_start), ("coverage_end", end)):
                if facts[field] is None:
                    missing("facts." + field, "明确资料覆盖起止期间")
                elif expected and facts[field] != expected:
                    issue("manual_review", "COVERAGE_MISMATCH", "facts." + field, "资料期间与税种口径不符；经营所得必须使用年内累计数据", ("P03",))
            for k, value in facts["checks"].items():
                if value is not True:
                    missing("facts.checks." + k, "该核对项尚未确认完成；不能把未知金额补零")
            for k, value in facts["flags"].items():
                if value is None:
                    missing("facts.flags." + k, "核实是否存在未分类收款、时点争议、特殊交易或非零预填")
                elif value:
                    issue("manual_review", "UNRESOLVED_FACT", "facts.flags." + k, "存在未决事项或非零预填，先核对，不清空系统数据")
            nonzero_fields = set(AMOUNTS) - {"non_revenue_receipts", "advance_receipts"}
            if kind == "vat":
                nonzero_fields.discard("costs_and_expenses")
            for k, value in facts["amounts"].items():
                if value is None:
                    missing("facts.amounts." + k, "金额未确认；只有核对依据支持时才能填零")
                elif value > 0:
                    if k in nonzero_fields:
                        issue("nonzero_return", "NONZERO_ITEM", "facts.amounts." + k, "存在应核对的非零事项；免税、亏损或无补税不等于整表填零", ("P01", "P02", "P03"))
                    elif k == "advance_receipts":
                        issue("manual_review", "ADVANCE_RECEIPTS", "facts.amounts." + k, "预收款需确认交易性质与纳税义务发生时间", ("P01",))
                    elif k == "non_revenue_receipts":
                        notes.append("已声明有非收入收款，结论依赖分类证据；不得自动把收款均当收入或均当借款。")
                    else:
                        notes.append("存在成本费用，不直接否定小规模增值税无销售候选；经营所得仍需单独据实填报。")
            status = max((v["status"] for v in issues), key=PRIORITY.get, default="zero_activity_candidate")
            if status == "zero_activity_candidate":
                notes.append("仅根据已声明资料生成零业务候选；继续核对真实表单的扣除、结转、减免及预填，不得把全表覆盖为零。")
        results.append({
            "index": index, "tax_kind": kind, "tax_label": TAX_LABELS[kind],
            "period_start": period["start"].isoformat() if period["start"] else None,
            "period_end": period["end"].isoformat() if period["end"] else None,
            "coverage_start": facts["coverage_start"].isoformat() if facts["coverage_start"] else None,
            "coverage_end": facts["coverage_end"].isoformat() if facts["coverage_end"] else None,
            "status": status, "label": LABELS[status], "issues": issues, "notes": notes,
            "evidence_reference_count": len(facts["evidence_refs"]),
            "tax_amount": None, "submission_status": "not_performed",
        })
    # Cross-item checks prevent individually plausible rows from hiding conflicts.
    def cross_issue(index, code, message):
        result = results[index]
        result["issues"].append({"status": "manual_review", "code": code,
                                 "field": "obligations", "message": message,
                                 "policy_refs": ["P03"] if code == "CUMULATIVE_RESET" else []})
        result["status"] = max(result["status"], "manual_review", key=PRIORITY.get)
        result["label"] = LABELS[result["status"]]
        result["notes"] = [n for n in result["notes"] if not n.startswith("仅根据已声明资料生成零业务候选")]

    items = data["obligations"]
    for i, left in enumerate(items):
        for j in range(i + 1, len(items)):
            right = items[j]
            if left["tax_kind"] != right["tax_kind"]:
                continue
            lp, rp = left["period"], right["period"]
            if not all((lp["start"], lp["end"], rp["start"], rp["end"])):
                continue
            if max(lp["start"], rp["start"]) <= min(lp["end"], rp["end"]):
                cross_issue(i, "OVERLAPPING_PERIODS", "同税种所属期重叠，先核对月报/季报或重复事项，不生成两个可提交草稿")
                cross_issue(j, "OVERLAPPING_PERIODS", "同税种所属期重叠，先核对月报/季报或重复事项，不生成两个可提交草稿")
            if left["tax_kind"] != "business_income_prepaid" or lp["end"].year != rp["end"].year or lp["end"] == rp["end"]:
                continue
            old_index, new_index = (i, j) if lp["end"] < rp["end"] else (j, i)
            old, new = items[old_index]["facts"]["amounts"], items[new_index]["facts"]["amounts"]
            groups = (("invoiced_revenue", "uninvoiced_revenue", "exempt_revenue", "other_revenue"),
                      ("costs_and_expenses",), ("tax_prepaid",))
            for group in groups:
                if any(old[k] is not None and old[k] > 0 for k in group) and all(new[k] == Decimal("0") for k in group):
                    cross_issue(new_index, "CUMULATIVE_RESET", "同年较早期间存在累计收入、费用或预缴，较晚期间却清零；核对更正、重分类或漏记依据")
                    break

    return {
        "product": "蜻蜓财务", "version": VERSION, "case_id": data["case_id"],
        "mode": data["mode"], "as_of": as_of.isoformat() if as_of else None,
        "policy_snapshot": POLICY_SNAPSHOT,
        "input_sha256": hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest(),
        "overall_status": "draft_for_review" if all(r["status"] in ("zero_activity_candidate", "not_listed") for r in results) else "needs_attention",
        "evidence_verified_by_program": False, "can_auto_submit": False,
        "scope_note": "仅评估输入列出的义务；程序不验证证据真伪、不计算税额、不决定全部法定义务、不提交申报。",
        "results": results,
    }


def markdown(report):
    lines = ["# 蜻蜓财务 · 申报准备草稿", "",
             f"事项：{report['case_id']} · 版本：{report['version']} · 评估日期：{report['as_of'] or '待补充'}",
             "", "**虚构演示资料，不可用于真实申报。**" if report["mode"] == "synthetic" else "**待复核草稿，尚未提交申报。**",
             "", report["scope_note"], "", "税额未计算；不可据此自动提交。", ""]
    for r in report["results"]:
        lines.extend([f"## {r['tax_label']} · {r['period_start'] or '?'} 至 {r['period_end'] or '?'}", "", f"结论：**{r['label']}**", ""])
        basis = "年内累计" if r["tax_kind"] == "business_income_prepaid" else "当期"
        lines.extend([f"取数期间（{basis}）：{r['coverage_start'] or '待补充'} 至 {r['coverage_end'] or '待补充'}", ""])
        for v in r["issues"]:
            lines.append(f"- `{v['field']}`：{v['message']}")
        for note in r["notes"]:
            lines.append(f"- {note}")
        lines.append("")
    lines.extend(["## 后续记录", "", "- 逐栏预览与用户授权范围：待核对。", "- 申报回执与独立回查：未取得。",
                  "- 缴款状态：未核查。", "- 其他税费、年度汇算及工商年报：按实际义务单列。", "",
                  f"输入摘要 SHA-256：`{report['input_sha256']}`", ""])
    return "\n".join(lines)


def unique_object(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise InputError("JSON 含重复键；拒绝以最后一个值覆盖前值")
        result[k] = v
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="蜻蜓财务：离线零业务候选检查，非税额计算或报税接口")
    parser.add_argument("input", type=Path, help="私有目录中的 JSON 文件，或仓库虚构示例")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)
    try:
        with args.input.open("r", encoding="utf-8") as stream:
            content = stream.read(1_048_577)
        if len(content) > 1_048_576:
            raise InputError("输入超过 1 MiB；请传汇总事实，不传原始流水")
        raw = json.loads(content, object_pairs_hook=unique_object,
                         parse_constant=lambda _: (_ for _ in ()).throw(InputError("JSON 不接受 NaN/Infinity")))
        report = assess(raw)
        print(markdown(report) if args.format == "markdown" else json.dumps(report, ensure_ascii=False, indent=2))
    except (InputError, json.JSONDecodeError, UnicodeError, OSError) as exc:
        message = str(exc) if isinstance(exc, InputError) else "无法读取有效 UTF-8 JSON；检查文件及格式（不回显敏感内容）"
        print(json.dumps({"error": message, "can_auto_submit": False}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
