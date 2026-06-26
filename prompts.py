from __future__ import annotations


def build_prompt(profile_text: str, profile: dict, tax: dict, gaps: dict) -> str:
    old = tax["old_regime"]
    new = tax["new_regime"]
    recommended = tax["recommended"]  # "old" or "new"

    old_tax      = old["total_tax"]
    new_tax      = new["total_tax"]
    tax_gap      = abs(old_tax - new_tax)
    marginal     = old.get("marginal_rate", 0)
    marginal_pct = int(marginal * 100)

    # ── Use the engine's binary-search flip result — never approximate ────────
    flip                    = tax.get("flip", {})
    deduction_needed        = flip.get("deduction_needed_to_flip", 0)
    total_unused_capacity   = flip.get("total_unused_capacity", gaps.get("total_unused_capacity", 0))
    can_flip                = flip.get("can_old_regime_become_better", False)
    flip_note               = flip.get("flip_note", "")

    # ── Per-section tax saving at actual marginal rate ────────────────────────
    # gap × marginal_rate is still the right approximation FOR INDIVIDUAL SECTIONS
    # (the binary search is for the total flip point, not per-section estimates).
    def tax_saving(gap: int) -> int:
        return int(gap * marginal)

    sec_80c_saving     = tax_saving(gaps["sec_80c_gap"])
    nps_saving         = tax_saving(gaps["nps_gap"])
    health_self_saving = tax_saving(gaps["health_80d_self_gap"])
    health_par_saving  = tax_saving(gaps["health_80d_par_gap"])
    home_loan_saving   = tax_saving(gaps["home_loan_int_gap"])
    tta_saving         = tax_saving(gaps["sec_80tta_gap"])

    # ── Correct headline ──────────────────────────────────────────────────────
    if recommended == "new":
        headline = f"New Regime Recommended — Estimated Tax Saving of Rs {tax_gap:,} vs Old Regime"
    else:
        headline = f"Old Regime Recommended — Estimated Tax Saving of Rs {tax_gap:,} vs New Regime"

    senior_label = "Senior Citizen" if profile.get("is_senior") else "Non-Senior Citizen"

    # ── Total declared deductions ─────────────────────────────────────────────
    total_declared = (
        gaps["sec_80c_used"]
        + profile.get("nps_80ccd_1b", 0)
        + profile.get("health_ins_self_80d", 0)
        + profile.get("health_ins_parents_80d", 0)
        + profile.get("home_loan_interest_24b", 0)
        + profile.get("sec_80tta", 0)
        + profile.get("sec_80e", 0)
        + profile.get("sec_80g", 0)
    )

    lines = [
        "=== EMPLOYEE TAX PROFILE — FY 2025-26 ===",
        "",
        f"NAME              : {profile['name']}",
        f"DESIGNATION       : {profile['designation']}",
        f"AGE               : {profile['age']} ({senior_label})",
        f"PAN               : {profile['pan']}",
        "",
        "=== INCOME ===",
        f"Gross Salary           : Rs {profile.get('gross_salary', 0):,}",
        f"HRA Exemption          : Rs {profile.get('hra_exemption', 0):,}",
        f"LTA Exemption          : Rs {profile.get('lta_exemption', 0):,}",
        f"Standard Deduction     : Rs 75,000",
        f"Other Income           : Rs {profile.get('other_income_total', 0) or profile.get('total_other_income', 0):,}",
        f"Rental Income          : Rs {profile.get('rental_income', 0):,}",
        "",
        "=== DECLARED DEDUCTIONS (use exactly these figures — do not alter) ===",
        f"80C (PF + others)      : Rs {profile.get('sec_80c_items_total', 0):,}",
        f"80CCD(1B) NPS          : Rs {profile.get('nps_80ccd_1b', 0):,}",
        f"80CCD(2) Employer NPS  : Rs {profile.get('nps_employer_80ccd2', 0):,}",
        f"80D Self               : Rs {profile.get('health_ins_self_80d', 0):,}",
        f"80D Parents            : Rs {profile.get('health_ins_parents_80d', 0):,}",
        f"Home Loan Interest 24b : Rs {profile.get('home_loan_interest_24b', 0):,}",
        f"80TTA                  : Rs {profile.get('sec_80tta', 0):,}",
        f"80E                    : Rs {profile.get('sec_80e', 0):,}",
        f"80G                    : Rs {profile.get('sec_80g', 0):,}",
        f"TOTAL DECLARED         : Rs {total_declared:,}",
        "",
        "=== PRE-COMPUTED TAX — DO NOT RECALCULATE, COPY THESE EXACTLY ===",
        "",
        "OLD REGIME:",
        f"  Gross Total Income   : Rs {old['total_income']:,}",
        f"  Total Deductions     : Rs {old['deductions']['total']:,}",
        f"    80C                : Rs {old['deductions']['sec_80c']:,}",
        f"    NPS 80CCD(1B)      : Rs {old['deductions']['nps_80ccd_1b']:,}",
        f"    Health 80D         : Rs {old['deductions']['health_80d']:,}",
        f"    Home Loan 24b      : Rs {old['deductions']['home_loan_24b']:,}",
        f"    Others             : Rs {old['deductions']['others']:,}",
        f"  Taxable Income       : Rs {old['taxable_income']:,}",
        f"  Base Tax             : Rs {old['raw_tax']:,}",
        f"  Rebate 87A           : Rs {old['rebate_87a']:,}",
        f"  Surcharge            : Rs {old['surcharge']:,}",
        f"  Cess (4%)            : Rs {old['cess']:,}",
        f"  TOTAL TAX OLD        : Rs {old_tax:,}",
        f"  Marginal Slab Rate   : {marginal_pct}%",
        "",
        "NEW REGIME:",
        f"  Gross Total Income   : Rs {new['total_income']:,}",
        f"  Taxable Income       : Rs {new['taxable_income']:,}",
        f"  Base Tax             : Rs {new['raw_tax']:,}",
        f"  Rebate 87A           : Rs {new['rebate_87a']:,}",
        f"  Surcharge            : Rs {new['surcharge']:,}",
        f"  Cess (4%)            : Rs {new['cess']:,}",
        f"  TOTAL TAX NEW        : Rs {new_tax:,}",
        "",
        f"RECOMMENDED REGIME     : {recommended.upper()}",
        f"TAX SAVING             : Rs {tax_gap:,}",
        f"CORRECT HEADLINE       : {headline}",
        "",
        "=== FLIP ANALYSIS — BINARY-SEARCH RESULT FROM TAX ENGINE, USE EXACTLY ===",
        f"Deduction needed to flip recommendation : Rs {deduction_needed:,}",
        f"Total unused deduction capacity         : Rs {total_unused_capacity:,}",
        f"Can Old Regime become better            : {str(can_flip).lower()}",
        f"Flip note (use this verbatim)           : {flip_note}",
        "",
        "NOTE ON PER-SECTION TAX SAVINGS:",
        f"These are estimated as gap × {marginal_pct}% (actual marginal slab rate from tax engine).",
        "They are estimates for individual sections — the total flip point above is exact.",
        "",
        "=== DEDUCTION GAPS & ESTIMATED TAX SAVINGS ===",
        f"80C      : Used Rs {gaps['sec_80c_used']:,} / Rs 1,50,000  | Gap Rs {gaps['sec_80c_gap']:,}  | Est. saving under Old Regime: Rs {sec_80c_saving:,}",
        f"NPS      : Used Rs {gaps['nps_used']:,} / Rs 50,000     | Gap Rs {gaps['nps_gap']:,}  | Est. saving under Old Regime: Rs {nps_saving:,}",
        f"80D Self : Used Rs {gaps['health_80d_self_used']:,} / Rs 25,000     | Gap Rs {gaps['health_80d_self_gap']:,}  | Est. saving under Old Regime: Rs {health_self_saving:,}",
        f"80D Par  : Used Rs {gaps['health_80d_par_used']:,} / Rs 50,000     | Gap Rs {gaps['health_80d_par_gap']:,}  | Est. saving under Old Regime: Rs {health_par_saving:,}",
        f"Sec 24b  : Used Rs {gaps['home_loan_int_used']:,} / Rs 2,00,000  | Gap Rs {gaps['home_loan_int_gap']:,} | Est. saving under Old Regime: Rs {home_loan_saving:,}",
        f"80TTA    : Used Rs {gaps['sec_80tta_used']:,} / Rs 10,000     | Gap Rs {gaps['sec_80tta_gap']:,}  | Est. saving under Old Regime: Rs {tta_saving:,}",
        f"TOTAL UNUSED CAPACITY  : Rs {total_unused_capacity:,}",
        "",
        "=== TDS STATUS ===",
        f"Remaining Months       : {profile.get('remaining_months', 'N/A')}",
        f"TDS Per Month          : Rs {profile.get('tds_per_month', 0):,}",
        f"Total TDS Paid So Far  : Rs {profile.get('tds_from_salary', 0):,}",
        f"Total Tax Liability    : Rs {new_tax if recommended == 'new' else old_tax:,}",
        "",
        "=== SECTION-WISE INSTRUMENT MAPPING — USE EXACTLY, NEVER MIX SECTIONS ===",
        "80C only          : EPF, PPF, ELSS, Life Insurance Premium, NSC, Tax Saver FD (5yr), Principal Repayment of Housing Loan, Tuition Fees, Sukanya Samriddhi",
        "80CCD(1B) only    : NPS Tier 1",
        "80D Self only     : Health insurance premium — self, spouse, dependent children",
        "80D Parents only  : Health insurance premium — parents (limit Rs 50,000 if parents are senior citizens)",
        "Sec 24b only      : Home loan interest on self-occupied or let-out property",
        "80TTA only        : Savings bank account interest",
        "",
        "=== INSTRUCTIONS FOR OUTPUT ===",
        "1. Copy all tax figures exactly from PRE-COMPUTED TAX above. Do not recalculate.",
        "2. Copy per-section savings exactly from DEDUCTION GAPS above. Do not apply any rate yourself.",
        "3. Copy flip analysis exactly from FLIP ANALYSIS above. Do not recompute deduction_needed_to_flip.",
        "4. Use CORRECT HEADLINE exactly as stated above — one headline only, no pipe-separated alternatives.",
        "5. Use instruments only from SECTION-WISE INSTRUMENT MAPPING — never mix sections.",
        "6. For New Regime: frame all deduction opportunities as financial planning, not tax saving.",
        "7. would_flip_recommendation = true only if can_old_regime_become_better = true AND that single section's gap >= deduction_needed_to_flip.",
        "8. Apply all RULES A–I from the system prompt.",
        "9. other_income declared is Rs {0:,}. If > 0, advise ITR tracking with exact amount.".format(
            profile.get('other_income_total', 0) or profile.get('total_other_income', 0)
        ),
    ]

    return "\n".join(lines)