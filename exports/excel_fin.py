"""Excel model for the financial-sector toolkits (banks, insurers, REITs), on the same banking conventions as the
corporate model (PROMPT.md section 11): blue inputs, black same-sheet formulas, green cross-sheet links, yellow
assumptions, red check rows, live formulas. Tabs: Cover, Inputs, Metrics, one tab per valuation method, Summary.
"""
from __future__ import annotations

from openpyxl import Workbook
from openpyxl.styles import Font

from engine.classify import BANK, INSURER, REIT
from engine.financials import DDM_YEARS, EXCESS_KEPT, FADE_TO_NORMAL, RI_YEARS, method_label, ni_common
from engine.values import PER_SHARE, RATIO
from exports.excel import BLACK, BLUE, GREEN, MULT, NUM, PCT, PCT2, PS, RED, YELLOW, Sheet, col

METRIC_LINES = {
    BANK: ["net_interest_income", "noninterest_income", "noninterest_expense", "provision_credit_losses",
           "net_income_attributable", "net_income_common", "total_assets", "loans_gross", "deposits",
           "net_charge_offs", "nonaccrual_loans", "parent_equity", "preferred_equity", "goodwill", "intangibles",
           "shares_outstanding"],
    INSURER: ["premiums_earned", "losses_incurred", "net_investment_income", "net_income_common", "total_assets",
              "parent_equity", "preferred_equity", "shares_outstanding"],
    REIT: ["net_income_common", "net_income", "interest_expense", "income_tax", "d_and_a", "real_estate_impairment",
           "real_estate_gains", "total_debt", "cash_and_investments", "minority_interest", "preferred_equity",
           "shares_diluted_weighted", "shares_outstanding", "dps_declared"],
}
# rows whose value is the engine's resolved input (with its fallback), not the raw tag
RESOLVED = {
    "net_income_common": ("Net income to common (tag, else NI attributable - preferred dividends)",
                          lambda h, y: ni_common(h, y).value),
    "net_income": ("Net income (incl. minorities; else attributable)",
                   lambda h, y: h.v("net_income", y) if h.v("net_income", y) is not None
                   else h.v("net_income_attributable", y)),
    "shares_diluted_weighted": ("Weighted diluted shares (else basic)",
                                lambda h, y: h.v("shares_diluted_weighted", y) or h.v("shares_basic_weighted", y)),
}


def build_financial_workbook(rep) -> Workbook:
    m = rep.model
    fv, ei, h = m.financial, m.inputs, rep.company.historicals_usd
    tk, d = fv.toolkit, fv.detail
    p = fv.period
    wb = Workbook()
    cover = Sheet(wb, "Cover", "US$ millions unless stated", first=True)
    inp = Sheet(wb, "Inputs", "US$ millions unless stated; percentages as decimals",
                "Blue = input (yellow fill = assumption). Sources in column C.")
    I: dict = {}
    row = 5

    def add(label, value, fmt, source, assumption=False, key=None, formula=None):
        nonlocal row
        inp.label(f"A{row}", label)
        if formula:
            inp.formula(f"B{row}", formula, fmt)
        else:
            inp.input(f"B{row}", value, fmt, assumption)
        inp.ws[f"C{row}"] = source
        inp.ws[f"C{row}"].font = Font(size=9, color="595959")
        ref = inp.ref(f"B{row}")
        if key:
            I[key] = ref
        row += 1
        return ref

    inp.head(f"A{row}", "Market")
    row += 1
    add("Share price (US$ per US share)", ei.price.value, PS, f"{ei.price.source} {ei.price.period}", key="price")
    add("Ordinary shares per US share (ADR ratio)", fv.per_us_share_factor, "0.00", "depositary agreement",
        key="adr")
    inp.head(f"A{row}", "Cost of equity")
    row += 1
    beta = next((a for a in m.assumptions if a["name"] == "Beta (levered)"), {"value": None, "source": ""})
    add("Risk-free rate", ei.risk_free.value, PCT2, f"{ei.risk_free.source} {ei.risk_free.period}", key="rf")
    add("Equity risk premium", ei.erp.value, PCT2, f"{ei.erp.source} {ei.erp.period}", key="erp")
    add("Beta (levered)", beta["value"], "0.00", beta["source"], True, key="beta")
    add("Country risk premium", ei.crp.value, PCT2, ei.crp.source, key="crp")
    if fv.cost_of_equity.source == "user override":
        add("Cost of equity (override)", fv.cost_of_equity.value, PCT2, "user override", True, key="coe")
    else:
        inp.label(f"A{row}", "Cost of equity")
        inp.formula(f"B{row}", f"{I['rf']}+{I['beta']}*{I['erp']}+{I['crp']}", PCT2)
        inp.ws[f"C{row}"] = "risk-free + beta x ERP + CRP"
        I["coe"] = inp.ref(f"B{row}")
        row += 1
    add("Long-run growth", fv.growth.value, PCT2, fv.growth.formula or fv.growth.source, True, key="g")
    if fv.normalised_return is not None:
        add("Normalised return on " + ("tangible " if tk == BANK else "") + "equity", fv.normalised_return.value,
            PCT2, fv.normalised_return.formula or fv.normalised_return.source, True, key="normal")
    if fv.base_per_share is not None:
        add(("Tangible book" if tk == BANK else "Book") + " value per share", fv.base_per_share.value, PS,
            fv.base_per_share.filing or fv.base_per_share.formula or fv.base_per_share.source, key="base")
    if "residual_income" in d:
        ri = d["residual_income"]
        add("Latest return on equity", ri["latest_return"], PCT2, f"{p}, computed from XBRL", key="latest")
        add("Retention (1 - total payout)", ri["retention"], PCT,
            "(dividends + buybacks) / net income, 3-year average", True, key="ret")
        add("Excess return kept by year 10", EXCESS_KEPT, PCT, "competition erodes excess returns", True, key="kept")
    if "ddm" in d:
        add("Last dividend per share", d["ddm"]["dps0"], PS, f"{p} XBRL (dividends declared)", key="dps0")
        add("Stage-1 dividend growth", d["ddm"]["stage1_growth"], PCT2, d["ddm"]["stage1_note"], True, key="g1")
    inp.head(f"A{row}", "Blend weights")
    row += 1
    for k in fv.weights:
        add(f"Weight: {method_label(k, tk)}", fv.weights[k], PCT, "toolkit default (zero weight if unavailable)",
            True, key=f"w_{k}")
    inp.ws.column_dimensions["B"].width = 16
    inp.ws.column_dimensions["C"].width = 70

    # --- Metrics -----------------------------------------------------------------------------------------------------
    mt = Sheet(wb, "Metrics", "US$ millions; ratios as decimals",
               "Statement lines from SEC XBRL (blue); 'Reported' from the 10-K text, with the quote in column E.")
    years = h.fy_labels[-2:]
    mt.head("A4", "Line")
    for j, y in enumerate(years):
        mt.head(f"{col(2 + j)}4", y)
    L: dict = {}
    for i, line in enumerate(METRIC_LINES[tk]):
        r_ = 5 + i
        label, get = RESOLVED.get(line, (line.replace("_", " ").capitalize(), lambda h_, y_, ln=line: h_.v(ln, y_)))
        mt.label(f"A{r_}", label)
        for j, y in enumerate(years):
            v = get(h, y)
            mt.input(f"{col(2 + j)}{r_}", v if v is not None else 0, NUM)
        L[line] = r_
    r0 = 6 + len(METRIC_LINES[tk])
    mt.head(f"A{r0}", "Metric")
    mt.head(f"B{r0}", f"Computed {p}")
    mt.head(f"C{r0}", "Reported (10-K)")
    mt.head(f"D{r0}", "Difference")
    mt.head(f"E{r0}", "Source / quote")
    B, A = col(2 + len(years) - 1), col(2) if len(years) > 1 else None  # latest and prior columns

    def avg(line):
        return f"({B}{L[line]}+{A}{L[line]})/2" if A and A != B else f"{B}{L[line]}"

    formulas = {}
    if tk == BANK:
        tce = lambda c: f"({c}{L['parent_equity']}-{c}{L['preferred_equity']}-{c}{L['goodwill']}-{c}{L['intangibles']})"  # noqa: E731
        formulas = {
            "rote": f"{B}{L['net_income_common']}/(({tce(B)}+{tce(A or B)})/2)",
            "efficiency_ratio": f"{B}{L['noninterest_expense']}/({B}{L['net_interest_income']}+{B}{L['noninterest_income']})",
            "nim": f"{B}{L['net_interest_income']}/{avg('total_assets')}",
            "loan_to_deposit": f"{B}{L['loans_gross']}/{B}{L['deposits']}",
            "nco_rate": f"{B}{L['net_charge_offs']}/{avg('loans_gross')}",
            "tbvps": f"{tce(B)}/{B}{L['shares_outstanding']}",
        }
    elif tk == INSURER:
        ce = lambda c: f"({c}{L['parent_equity']}-{c}{L['preferred_equity']})"  # noqa: E731
        formulas = {"loss_ratio": f"{B}{L['losses_incurred']}/{B}{L['premiums_earned']}",
                    "roe": f"{B}{L['net_income_common']}/(({ce(B)}+{ce(A or B)})/2)",
                    "bvps": f"{ce(B)}/{B}{L['shares_outstanding']}"}
    else:
        formulas = {"ffo": f"{B}{L['net_income_common']}+{B}{L['d_and_a']}+{B}{L['real_estate_impairment']}"
                           f"-{B}{L['real_estate_gains']}",
                    "ffo_per_share": f"({B}{L['net_income_common']}+{B}{L['d_and_a']}+{B}{L['real_estate_impairment']}"
                                     f"-{B}{L['real_estate_gains']})/{B}{L['shares_diluted_weighted']}",
                    "noi": f"{B}{L['net_income']}+{B}{L['interest_expense']}+{B}{L['income_tax']}+{B}{L['d_and_a']}"
                           f"+{B}{L['real_estate_impairment']}-{B}{L['real_estate_gains']}"}
    k = r0 + 1
    for metric in fv.metrics:
        mt.label(f"A{k}", metric.label)
        unit_fmt = PS if metric.value.unit == PER_SHARE else (PCT2 if metric.value.unit == RATIO else
                                                              (MULT if metric.value.unit == "x" else NUM))
        if metric.key in formulas:
            mt.formula(f"B{k}", formulas[metric.key], unit_fmt)
        elif metric.value.value is not None:
            mt.input(f"B{k}", metric.value.value, unit_fmt)
        if metric.reported is not None:
            mt.input(f"C{k}", metric.reported.value, unit_fmt)
            if metric.key in formulas or metric.value.value is not None:
                mt.formula(f"D{k}", f"C{k}-B{k}", unit_fmt)
            mt.ws[f"E{k}"] = f"{metric.reported.filing}; {metric.reported.note}"[:250]
        elif metric.value.value is None:
            mt.ws[f"E{k}"] = metric.value.note or "not available"
        mt.ws[f"E{k}"].font = Font(size=9, color="595959")
        k += 1
    mt.ws.column_dimensions["E"].width = 90
    for c_ in ("B", "C", "D"):
        mt.ws.column_dimensions[c_].width = 16

    refs: dict[str, str] = {}
    # --- Justified multiple ------------------------------------------------------------------------------------------
    if "justified" in d:
        js = Sheet(wb, "Justified", "US$ per share", "(normalised return - g) / (cost of equity - g) x book per share")
        for i, (lab, f, fmt) in enumerate([
                ("Normalised return", I["normal"], PCT2), ("Cost of equity", I["coe"], PCT2),
                ("Long-run growth", I["g"], PCT2), ("Justified multiple of book", "(B5-B7)/(B6-B7)", MULT),
                ("Book value per share", I["base"], PS), ("Value per ordinary share", "B8*B9", PS),
                ("Value per US share", f"B10*{I['adr']}", PS)]):
            js.label(f"A{5 + i}", lab, bold=i >= 5)
            js.formula(f"B{5 + i}", f, fmt, bold=i >= 5)
        refs["justified"] = js.ref("B11")

    # --- Residual income ---------------------------------------------------------------------------------------------
    if "residual_income" in d:
        rs = Sheet(wb, "Residual income", "US$ per share",
                   f"Return fades from the latest year to the normalised level over {FADE_TO_NORMAL} years, then the "
                   f"excess over the cost of equity shrinks to the 'kept' share by year {RI_YEARS}; book grows by "
                   "retained earnings.")
        for j, h_ in enumerate(["Year", "Return", "Opening book", "Residual income", "Discount factor", "PV"]):
            rs.head(f"{col(1 + j)}5", h_)
        rs.label("H5", "Long-run return")
        rs.formula("I5", f"{I['coe']}+{I['kept']}*({I['normal']}-{I['coe']})", PCT2)
        for t in range(1, RI_YEARS + 1):
            r_ = 5 + t
            rs.input(f"A{r_}", t)
            if t <= FADE_TO_NORMAL:
                rs.formula(f"B{r_}", f"{I['latest']}+({I['normal']}-{I['latest']})*A{r_}/{FADE_TO_NORMAL}", PCT2)
            else:
                rs.formula(f"B{r_}", f"{I['normal']}+($I$5-{I['normal']})*(A{r_}-{FADE_TO_NORMAL})/"
                                     f"{RI_YEARS - FADE_TO_NORMAL}", PCT2)
            rs.formula(f"C{r_}", I["base"] if t == 1 else f"C{r_ - 1}*(1+B{r_ - 1}*{I['ret']})", PS)
            rs.formula(f"D{r_}", f"(B{r_}-{I['coe']})*C{r_}", PS)
            rs.formula(f"E{r_}", f"(1+{I['coe']})^-A{r_}", "0.0000")
            rs.formula(f"F{r_}", f"D{r_}*E{r_}", PS)
        last = 5 + RI_YEARS
        rows_ = [("Closing book, year 10", f"C{last}*(1+B{last}*{I['ret']})", PS),
                 ("Terminal value (year-11 residual income / (CoE - g))",
                  f"($I$5-{I['coe']})*B{last + 2}/({I['coe']}-{I['g']})", PS),
                 ("PV of terminal value", f"B{last + 3}*E{last}", PS),
                 ("PV of residual income, years 1-10", f"SUM(F6:F{last})", PS),
                 ("Value per ordinary share", f"C6+B{last + 5}+B{last + 4}", PS),
                 ("Value per US share", f"B{last + 6}*{I['adr']}", PS)]
        for i, (lab, f, fmt) in enumerate(rows_):
            rs.label(f"A{last + 2 + i}", lab, bold=i >= 4)
            rs.formula(f"B{last + 2 + i}", f, fmt, bold=i >= 4)
        refs["residual_income"] = rs.ref(f"B{last + 7}")

    # --- DDM ---------------------------------------------------------------------------------------------------------
    if "ddm" in d:
        ds = Sheet(wb, "DDM", "US$ per share", "Two-stage: stage-1 growth for 5 years, then Gordon growth.")
        for j, h_ in enumerate(["Year", "Dividend", "Discount factor", "PV"]):
            ds.head(f"{col(1 + j)}5", h_)
        for t in range(1, DDM_YEARS + 1):
            r_ = 5 + t
            ds.input(f"A{r_}", t)
            ds.formula(f"B{r_}", f"{I['dps0']}*(1+{I['g1']})^A{r_}", PS)
            ds.formula(f"C{r_}", f"(1+{I['coe']})^-A{r_}", "0.0000")
            ds.formula(f"D{r_}", f"B{r_}*C{r_}", PS)
        last = 5 + DDM_YEARS
        rows_ = [("Terminal value", f"B{last}*(1+{I['g']})/({I['coe']}-{I['g']})", PS),
                 ("PV of terminal value", f"B{last + 2}*C{last}", PS),
                 ("Value per ordinary share", f"SUM(D6:D{last})+B{last + 3}", PS),
                 ("Value per US share", f"B{last + 4}*{I['adr']}", PS)]
        for i, (lab, f, fmt) in enumerate(rows_):
            ds.label(f"A{last + 2 + i}", lab, bold=i >= 2)
            ds.formula(f"B{last + 2 + i}", f, fmt, bold=i >= 2)
        refs["ddm"] = ds.ref(f"B{last + 5}")

    # --- Comps and NAV -----------------------------------------------------------------------------------------------
    for key in ("comps_pb", "comps_pe", "comps_pffo", "cap_rate"):
        x = d.get(key)
        if not x or not x.get("peers"):
            continue
        title = {"comps_pb": "Peer P-TBV" if tk == BANK else "Peer P-B", "comps_pe": "Peer PE",
                 "comps_pffo": "Peer P-FFO", "cap_rate": "Peer cap rates"}[key]
        cs = Sheet(wb, title, "multiples (cap rates as decimals)", "Peer figures from SEC XBRL, latest fiscal year.")
        for j, h_ in enumerate(["Ticker", "Name", "Multiple", "Period"]):
            cs.head(f"{col(1 + j)}5", h_)
        fmt = PCT2 if key == "cap_rate" else MULT
        for i, pr in enumerate(x["peers"]):
            r_ = 6 + i
            cs.ws[f"A{r_}"], cs.ws[f"B{r_}"], cs.ws[f"D{r_}"] = pr["ticker"], pr["name"], pr["period"]
            cs.input(f"C{r_}", pr["multiple"], fmt)
        last = 5 + len(x["peers"])
        if x.get("median") is None:
            cs.label(f"A{last + 2}", "Fewer than three usable peers: not used in the blend.")
            continue
        cs.label(f"A{last + 2}", "Peer median", bold=True)
        cs.formula(f"C{last + 2}", f"MEDIAN(C6:C{last})", fmt, bold=True)
        if key == "cap_rate":
            I["cap_rate"] = cs.ref(f"C{last + 2}")
            continue
        base_ref = {"comps_pb": I.get("base"), "comps_pe": None, "comps_pffo": None}[key]
        if key == "comps_pe":
            cs.label(f"A{last + 3}", "Earnings per share")
            cs.input(f"C{last + 3}", x["eps"], PS)
            base_ref = f"C{last + 3}"
        elif key == "comps_pffo":
            fps = fv.metric("ffo_per_share")
            b = fps.reported if fps.reported is not None else fps.value
            cs.label(f"A{last + 3}", "FFO per share (reported where available)")
            cs.input(f"C{last + 3}", b.value, PS)
            base_ref = f"C{last + 3}"
        cs.label(f"A{last + 4}", "Implied value per US share", bold=True)
        cs.formula(f"C{last + 4}", f"C{last + 2}*{base_ref}*{I['adr']}", PS, bold=True)
        refs[key] = cs.ref(f"C{last + 4}")

    if "nav" in d:
        n = d["nav"]
        ns = Sheet(wb, "NAV", "US$ millions", "NOI proxy / cap rate - net debt, per share.")
        cap = None if n.get("cap_rate_overridden") else I.get("cap_rate")  # an edited cap rate is an input
        rows_ = [("NOI proxy (EBITDAre: NI + interest + tax + D&A + impairments - gains)", n["noi"], NUM, False),
                 ("Cap rate", cap if cap else n["cap_rate"], PCT2, bool(cap)),
                 ("Gross asset value", "B5/B6", NUM, True), ("Net debt (debt - cash + minorities + preferred)",
                                                            n["net_debt"], NUM, False),
                 ("Net asset value", "B7-B8", NUM, True), ("Shares outstanding (m)", n.get("shares"), NUM, False),
                 ("NAV per ordinary share", "B9/B10", PS, True), ("NAV per US share", f"B11*{I['adr']}", PS, True)]
        for i, (lab, val, fmt, is_f) in enumerate(rows_):
            ns.label(f"A{5 + i}", lab, bold=i >= 6)
            if is_f:
                ns.formula(f"B{5 + i}", val, fmt, bold=i >= 6)
            else:
                ns.input(f"B{5 + i}", val, fmt)
        refs["nav"] = ns.ref("B12")

    # --- Summary -----------------------------------------------------------------------------------------------------
    su = Sheet(wb, "Summary", "US$ per US share", "Fair value = weighted blend (weights on the Inputs tab).")
    su.label("A5", "Share price")
    su.formula("B5", I["price"], PS)
    keys = list(fv.weights)
    for i, k_ in enumerate(keys):
        su.label(f"A{6 + i}", method_label(k_, tk))
        su.formula(f"B{6 + i}", refs[k_], PS) if k_ in refs else su.input(f"B{6 + i}", 0, PS)
        su.formula(f"C{6 + i}", f"IF(B{6 + i}>0,{I['w_' + k_]},0)", PCT)
    end = 5 + len(keys)
    fvr = end + 1
    su.label(f"A{fvr}", "Fair value (weighted blend)", bold=True)
    su.formula(f"B{fvr}", f"SUMPRODUCT(B6:B{end},C6:C{end})/SUM(C6:C{end})", PS, bold=True)
    su.label(f"A{fvr + 1}", "Upside / (downside) to fair value")
    su.formula(f"B{fvr + 1}", f"B{fvr}/B5-1", PCT)
    su.label(f"A{fvr + 2}", "Verdict (price > 15% below fair value = Undervalued; > 15% above = Overvalued)")
    su.formula(f"B{fvr + 2}", f'IF(B5<B{fvr}*0.85,"Undervalued",IF(B5>B{fvr}*1.15,"Overvalued","Fairly valued"))')
    su.label(f"A{fvr + 4}", "Check: fair value in the app", bold=True)
    su.input(f"B{fvr + 4}", m.verdict.fair_value, PS)
    su.label(f"A{fvr + 5}", "Check: Excel minus app (should be 0.00)")
    su.formula(f"B{fvr + 5}", f"B{fvr}-B{fvr + 4}", PS, check=True)
    for i, k_ in enumerate(keys):
        if k_ in fv.methods:
            r_ = fvr + 6 + i
            su.label(f"A{r_}", f"Check: {method_label(k_, tk)} minus app")
            su.formula(f"B{r_}", f"B{6 + i}-{fv.methods[k_].value}", PS, check=True)
    su.ws.column_dimensions["A"].width = 70
    su.ws.column_dimensions["B"].width = 16

    # --- Cover -------------------------------------------------------------------------------------------------------
    name = rep.company.profile.name if rep.company else rep.ticker
    cover.ws["A4"] = f"{name} ({rep.ticker})"
    cover.ws["A4"].font = Font(bold=True, size=16)
    info = [("Report", getattr(rep, "report_id", "")), ("Valuation date", str(getattr(rep, "valuation_date", ""))),
            ("Toolkit", f"{tk} (no DCF)"), ("Why no DCF", fv.why_no_dcf), ("Verdict (app)", m.verdict.verdict),
            ("Confidence", m.verdict.confidence), ("MD rating", rep.md.rating if getattr(rep, "md", None) else "n/a")]
    for i, (k_, x) in enumerate(info):
        cover.label(f"A{6 + i}", k_)
        cover.ws[f"B{6 + i}"] = x
    cover.label("A14", "Fair value (US$ per share)", bold=True)
    cover.formula("B14", f"Summary!B{fvr}", PS, bold=True)
    cover.label("A15", "Share price")
    cover.formula("B15", "Summary!B5", PS)
    cover.label("A17", "Colour key", bold=True)
    for i, (txt, colour, fill) in enumerate([("Blue: hard-coded input", BLUE, None),
                                             ("Black: formula on the same sheet", BLACK, None),
                                             ("Green: link to another sheet", GREEN, None),
                                             ("Yellow fill: assumption", BLACK, YELLOW),
                                             ("Red: check row", RED, None)]):
        cover.ws[f"A{18 + i}"] = txt
        cover.ws[f"A{18 + i}"].font = Font(color=colour)
        if fill:
            cover.ws[f"A{18 + i}"].fill = fill
    cover.ws["A24"] = "Based on assumptions and public data; may contain errors; not financial advice."
    cover.ws["A24"].font = Font(italic=True, size=9)
    cover.ws.column_dimensions["B"].width = 60
    wb.summary_rows = {"fair_value": f"Summary!B{fvr}", "check": f"Summary!B{fvr + 5}",
                       "method_checks": [f"Summary!B{fvr + 6 + i}" for i, k_ in enumerate(keys) if k_ in fv.methods]}
    return wb
