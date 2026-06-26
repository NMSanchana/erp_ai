from __future__ import annotations

import json
import os
from functools import lru_cache

TAX_RULES_DIR = os.path.join("data", "tax_rules")
DEFAULT_YEAR = "2026"


@lru_cache(maxsize=None)
def load_tax_rules(year: str) -> dict:
    path = os.path.join(TAX_RULES_DIR, f"{year}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No tax rules file found for year '{year}' at {path}. "
            f"Add data/tax_rules/{year}.json before processing employees for this period."
        )
    with open(path, "r") as f:
        return json.load(f)


def _resolve_year(profile: dict, year: str | None) -> str:
    return year or profile.get("period_code") or DEFAULT_YEAR


def _apply_slabs(income: int, slabs: list[list]) -> int:
    tax = 0.0
    prev = 0
    for upper, rate in slabs:
        if upper is None:
            tax += max(0, income - prev) * rate
            break
        if income <= upper:
            tax += max(0, income - prev) * rate
            break
        tax += (upper - prev) * rate
        prev = upper
    return int(tax)


def _apply_surcharge(income: int, tax: int, surcharge_slabs: list[list]) -> int:
    rate = 0.0
    for upper, r in surcharge_slabs:
        if upper is None or income <= upper:
            rate = r
            break
    return int(tax * rate)


def _marginal_rate_old(taxable: int, is_senior: bool, is_very_senior: bool, slabs_cfg: dict) -> float:
    if is_very_senior:
        slabs = slabs_cfg["very_senior"]
    elif is_senior:
        slabs = slabs_cfg["senior"]
    else:
        slabs = slabs_cfg["general"]
    for upper, rate in slabs:
        if upper is None or taxable <= upper:
            return rate
    return slabs[-1][1]


def _rebate_with_marginal_relief(
    taxable: int, raw_tax: int, limit: int, max_rebate: int, use_marginal_relief: bool
) -> int:
    """
    Sec 87A rebate, including marginal relief.

    Without marginal relief, crossing the threshold by even Rs 1 would make
    the full slab tax apply -- a huge cliff. Marginal relief caps the tax
    in that narrow zone to just the amount by which income exceeds the
    threshold, so there's no cliff.
    """
    if taxable <= limit:
        return min(raw_tax, max_rebate)

    if not use_marginal_relief:
        return 0

    excess_income = taxable - limit
    if raw_tax > excess_income:
        # Tax payable becomes just the excess over the threshold,
        # not the full slab-calculated tax.
        relief = raw_tax - excess_income
        return min(relief, raw_tax)

    return 0


def compute_old_regime(profile: dict, rules: dict) -> dict:
    is_senior = bool(profile.get("is_senior"))
    is_very_senior = profile.get("age", 0) >= 80
    # NOTE: there is currently no field in parser.py / the ERP feed indicating
    # whether the employee's PARENTS are senior citizens (only the employee's
    # own age is tracked). Until that field exists, we default to the
    # non-senior parent limit -- the conservative choice, since it can only
    # under-state the deduction, never overstate it.
    parents_are_senior = bool(profile.get("parents_senior", False))

    gross = profile.get("gross_salary", 0)
    hra_exempt = profile.get("hra_exemption", 0)
    lta_exempt = profile.get("lta_exemption", 0)
    ptax = profile.get("ptax", 0)
    ent_allow = profile.get("entertainment_allowance", 0)
    other_inc = profile.get("other_income_total", 0) or profile.get("total_other_income", 0)
    home_int = profile.get("home_loan_interest_24b", 0)
    rental_inc = profile.get("rental_income", 0)

    limits = rules["deduction_limits"]
    std_ded = rules["standard_deduction"]["old"]

    net_salary = gross - hra_exempt - lta_exempt
    net_salary -= std_ded
    net_salary -= ent_allow
    net_salary -= ptax

    total_income = net_salary + other_inc + rental_inc

    sec24_ded = min(home_int, limits["home_loan_24b"])

    sec_80c = min(profile.get("sec_80c_items_total", 0), limits["sec_80c"])
    nps = min(profile.get("nps_80ccd_1b", 0), limits["nps_80ccd_1b"])

    d80_self_limit = limits["health_80d_self_senior"] if is_senior else limits["health_80d_self"]
    d80_self = min(profile.get("health_ins_self_80d", 0), d80_self_limit)

    # FIX: parents' 80D limit now split senior/non-senior (defaults to non-senior, see note above)
    d80_par_limit = (
        limits["health_80d_parents_senior"] if parents_are_senior else limits["health_80d_parents_non_senior"]
    )
    d80_par = min(profile.get("health_ins_parents_80d", 0), d80_par_limit)
    d80_total = d80_self + d80_par

    other_deds = (
        profile.get("sec_80e", 0)
        + profile.get("sec_80g", 0)
        + profile.get("sec_80tta", 0)
        + profile.get("sec_80ttb", 0)
        + profile.get("sec_80u", 0)
        + profile.get("sec_80dd", 0)
        + profile.get("sec_80ddb", 0)
        + profile.get("sec_80ee", 0)
        + profile.get("sec_80ee1", 0)
        + profile.get("sec_80eeb", 0)
    )

    total_ded = sec_80c + nps + d80_total + sec24_ded + other_deds
    taxable = max(0, total_income - total_ded)

    slabs_cfg = rules["old_regime_slabs"]
    if is_very_senior:
        slabs = slabs_cfg["very_senior"]
    elif is_senior:
        slabs = slabs_cfg["senior"]
    else:
        slabs = slabs_cfg["general"]

    raw_tax = _apply_slabs(taxable, slabs)

    rebate_cfg = rules["rebate_87a"]
    # FIX: now uses marginal relief instead of a hard cliff at the threshold
    rebate = _rebate_with_marginal_relief(
        taxable,
        raw_tax,
        rebate_cfg["old_limit"],
        rebate_cfg["old_max_rebate"],
        rebate_cfg.get("old_marginal_relief", False),
    )
    tax_after_rebate = max(0, raw_tax - rebate)

    surcharge = _apply_surcharge(taxable, tax_after_rebate, rules["surcharge"]["old_regime"])
    cess = int((tax_after_rebate + surcharge) * rules["cess_rate"])
    total_tax = tax_after_rebate + surcharge + cess

    return {
        "regime": "old",
        "gross_salary": gross,
        "hra_exemption": hra_exempt,
        "standard_deduction": std_ded,
        "other_income": other_inc + rental_inc,
        "total_income": int(total_income),
        "deductions": {
            "sec_80c": sec_80c,
            "nps_80ccd_1b": nps,
            "health_80d": d80_total,
            "home_loan_24b": sec24_ded,
            "others": other_deds,
            "total": int(total_ded),
        },
        "taxable_income": int(taxable),
        "raw_tax": raw_tax,
        "rebate_87a": rebate,
        "tax_after_rebate": tax_after_rebate,
        "surcharge": surcharge,
        "cess": cess,
        "total_tax": total_tax,
        "marginal_rate": _marginal_rate_old(taxable, is_senior, is_very_senior, slabs_cfg),
    }


def compute_new_regime(profile: dict, rules: dict) -> dict:
    gross = profile.get("gross_salary", 0)
    other_inc = profile.get("other_income_total", 0) or profile.get("total_other_income", 0)
    rental = profile.get("rental_income", 0)
    nps_emp = profile.get("nps_employer_80ccd2", 0)

    std_ded = rules["standard_deduction"]["new"]
    total_inc = gross - std_ded + other_inc + rental

    total_ded = nps_emp
    taxable = max(0, total_inc - total_ded)

    raw_tax = _apply_slabs(taxable, rules["new_regime_slabs"])

    rebate_cfg = rules["rebate_87a"]
    # FIX: now uses marginal relief instead of a hard cliff at the threshold
    rebate = _rebate_with_marginal_relief(
        taxable,
        raw_tax,
        rebate_cfg["new_limit"],
        rebate_cfg["new_max_rebate"],
        rebate_cfg.get("new_marginal_relief", False),
    )
    tax_after_rebate = max(0, raw_tax - rebate)

    surcharge = _apply_surcharge(taxable, tax_after_rebate, rules["surcharge"]["new_regime"])
    cess = int((tax_after_rebate + surcharge) * rules["cess_rate"])
    total_tax = tax_after_rebate + surcharge + cess

    return {
        "regime": "new",
        "gross_salary": gross,
        "standard_deduction": std_ded,
        "other_income": other_inc + rental,
        "total_income": int(total_inc),
        "deductions": {
            "nps_employer": nps_emp,
            "total": int(total_ded),
        },
        "taxable_income": int(taxable),
        "raw_tax": raw_tax,
        "rebate_87a": rebate,
        "tax_after_rebate": tax_after_rebate,
        "surcharge": surcharge,
        "cess": cess,
        "total_tax": total_tax,
    }


def compare_regimes(profile: dict, year: str | None = None) -> dict:
    resolved_year = _resolve_year(profile, year)
    rules = load_tax_rules(resolved_year)

    old = compute_old_regime(profile, rules)
    new = compute_new_regime(profile, rules)

    if old["total_tax"] <= new["total_tax"]:
        recommended = "old"
        savings = new["total_tax"] - old["total_tax"]
        savings_note = f"Old regime saves Rs {savings:,} vs new regime."
    else:
        recommended = "new"
        savings = old["total_tax"] - new["total_tax"]
        savings_note = f"New regime saves Rs {savings:,} vs old regime."

    return {
        "financial_year": resolved_year,
        "old_regime": old,
        "new_regime": new,
        "recommended": recommended,
        "savings": savings,
        "savings_note": savings_note,
    }


def compute_deduction_gaps(profile: dict, year: str | None = None) -> dict:
    resolved_year = _resolve_year(profile, year)
    rules = load_tax_rules(resolved_year)
    limits = rules["deduction_limits"]
    parents_are_senior = bool(profile.get("parents_senior", False))
    parent_limit = (
        limits["health_80d_parents_senior"] if parents_are_senior else limits["health_80d_parents_non_senior"]
    )

    return {
        "sec_80c_used": min(profile.get("sec_80c_items_total", 0), limits["sec_80c"]),
        "sec_80c_gap": max(0, limits["sec_80c"] - profile.get("sec_80c_items_total", 0)),
        "sec_80c_limit": limits["sec_80c"],
        "nps_used": profile.get("nps_80ccd_1b", 0),
        "nps_gap": max(0, limits["nps_80ccd_1b"] - profile.get("nps_80ccd_1b", 0)),
        "nps_limit": limits["nps_80ccd_1b"],
        "health_80d_self_used": profile.get("health_ins_self_80d", 0),
        "health_80d_self_gap": max(0, limits["health_80d_self"] - profile.get("health_ins_self_80d", 0)),
        "health_80d_self_limit": limits["health_80d_self"],
        "health_80d_par_used": profile.get("health_ins_parents_80d", 0),
        "health_80d_par_gap": max(0, parent_limit - profile.get("health_ins_parents_80d", 0)),
        "health_80d_par_limit": parent_limit,
        "home_loan_int_used": profile.get("home_loan_interest_24b", 0),
        "home_loan_int_gap": max(0, limits["home_loan_24b"] - profile.get("home_loan_interest_24b", 0)),
        "home_loan_int_limit": limits["home_loan_24b"],
        "sec_80tta_used": profile.get("sec_80tta", 0),
        "sec_80tta_gap": max(0, limits["sec_80tta"] - profile.get("sec_80tta", 0)),
        "sec_80tta_limit": limits["sec_80tta"],
        "hra_claimed": profile.get("hra_exemption", 0),
    }