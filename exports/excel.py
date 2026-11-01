"""Excel model export with banking conventions and live formulas (PROMPT.md section 11).

Colours: blue font = hard-coded input, black = formula on the same sheet, green = link to another sheet,
light-yellow fill = assumption, red = check row. Numbers #,##0;(#,##0), percentages 0.0%, multiples 0.0x.
Every DCF (base, each scenario, each sensitivity cell) is a full formula block on the same rules as the engine:
growth -> revenue -> EBIT -> tax with loss carry-forward -> NOPAT -> reinvestment (sales-to-capital) -> FCF,
timing (share of the year before / after today, discount period), value-driver terminal value, equity bridge.
"""
from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from engine.comps import NM_ABOVE
from exports.cached_values import with_cached_values

BLUE, BLACK, GREEN, RED = "0000FF", "000000", "008000", "C00000"
YELLOW = PatternFill("solid", fgColor="FFF2CC")
HEAD = PatternFill("solid", fgColor="DDEBF7")
NUM = "#,##0;(#,##0)"
NUM1 = "#,##0.0;(#,##0.0)"
PCT = "0.0%"
PCT2 = "0.00%"
MULT = '0.0"x"'
PS = "#,##0.00;(#,##0.00)"
DEC4 = "0.0000"
THIN = Border(bottom=Side(style="thin", color="999999"))


def col(i: int) -> str:
    return get_column_letter(i)


class Sheet:
    def __init__(self, wb: Workbook, title: str, units: str, note: str | None = None, first: bool = False):
        self.ws = wb.active if first else wb.create_sheet(title)
        self.ws.title = title
        self.ws.sheet_view.showGridLines = False
        self.ws["A1"] = title
        self.ws["A1"].font = Font(bold=True, size=14)
        self.ws["A2"] = units
        self.ws["A2"].font = Font(italic=True, color="595959")
        if note:
            self.ws["A3"] = note
            self.ws["A3"].font = Font(italic=True, size=9, color="595959")
        self.ws.column_dimensions["A"].width = 44
        self.ws.freeze_panes = "B5"
        self.name = title

    def ref(self, cell: str, absolute: bool = True) -> str:
        c = cell
        if absolute:
            letters = "".join(ch for ch in cell if ch.isalpha())
            digits = cell[len(letters):]
            c = f"${letters}${digits}"
        return f"'{self.name}'!{c}"

    def label(self, cell: str, text: str, bold: bool = False) -> None:
        self.ws[cell] = text
        self.ws[cell].font = Font(bold=bold)

    def head(self, cell: str, text: str) -> None:
        self.ws[cell] = text
        self.ws[cell].font = Font(bold=True)
        self.ws[cell].fill = HEAD
        self.ws[cell].alignment = Alignment(horizontal="center")

    def input(self, cell: str, value, fmt: str | None = None, assumption: bool = False) -> None:
        self.ws[cell] = value
        self.ws[cell].font = Font(color=BLUE)
        if assumption:
            self.ws[cell].fill = YELLOW
        if fmt:
            self.ws[cell].number_format = fmt

    def formula(self, cell: str, f: str, fmt: str | None = None, bold: bool = False, check: bool = False) -> None:
        self.ws[cell] = f if f.startswith("=") else "=" + f
        colour = RED if check else (GREEN if "!" in f else BLACK)
        self.ws[cell].font = Font(color=colour, bold=bold)
        if fmt:
            self.ws[cell].number_format = fmt


# --- DCF block ---------------------------------------------------------------------------------------------------
def dcf_block(sh: Sheet, top: int, n: int, I: dict, title: str, g_shift: str = "0", m_shift: str = "0",
              wacc: str | None = None, tg: str | None = None) -> dict:
    """Write one full DCF from row `top`. I holds Inputs references. Returns cell refs of the results."""
    ws = sh.ws
    wacc = wacc or I["wacc"]
    tg = tg or I["tg"]
    sh.label(f"A{top}", title, bold=True)
    r = {k: top + i for i, k in enumerate(["year", "growth", "rev", "margin", "ebit", "tax_rate", "used", "tax",
                                            "loss_cf", "nopat", "reinv", "fcf", "pre", "post", "t", "pv"], start=1)}
    labels = {"year": "Fiscal year", "growth": "Revenue growth", "rev": "Revenue", "margin": "Operating margin",
              "ebit": "Operating income (EBIT)", "tax_rate": "Tax rate", "used": "Tax losses used",
              "tax": "Tax", "loss_cf": "Tax losses carried forward", "nopat": "NOPAT",
              "reinv": "Reinvestment (change in revenue / sales-to-capital)", "fcf": "Unlevered free cash flow",
              "pre": "Share of year earned before today (undiscounted)", "post": "Share of year still to come",
              "t": "Discount period (years)", "pv": "Present value"}
    for k, row in r.items():
        sh.label(f"A{row}", labels[k])
    for j in range(n):
        c, prev = col(2 + j), col(1 + j)
        first = j == 0
        sh.formula(f"{c}{r['year']}", f"{I['years'][j]}")
        sh.formula(f"{c}{r['growth']}", f"{I['growth'][j]}+{g_shift}", PCT)
        prev_rev = I["base_rev"] if first else f"{prev}{r['rev']}"
        sh.formula(f"{c}{r['rev']}", f"{prev_rev}*(1+{c}{r['growth']})", NUM)
        sh.formula(f"{c}{r['margin']}", f"{I['margin'][j]}+{m_shift}", PCT)
        sh.formula(f"{c}{r['ebit']}", f"{c}{r['rev']}*{c}{r['margin']}", NUM)
        sh.formula(f"{c}{r['tax_rate']}", f"{I['tax'][j]}", PCT)
        prev_loss = "0" if first else f"{prev}{r['loss_cf']}"
        sh.formula(f"{c}{r['used']}", f"MIN({prev_loss},MAX({c}{r['ebit']},0))", NUM)
        sh.formula(f"{c}{r['tax']}", f"MAX(0,{c}{r['ebit']}-{c}{r['used']})*{c}{r['tax_rate']}", NUM)
        sh.formula(f"{c}{r['loss_cf']}", f"{prev_loss}-{c}{r['used']}+MAX(0,-{c}{r['ebit']})", NUM)
        sh.formula(f"{c}{r['nopat']}", f"{c}{r['ebit']}-{c}{r['tax']}", NUM)
        sh.formula(f"{c}{r['reinv']}", f"({c}{r['rev']}-{prev_rev})/{I['s2c'][j]}", NUM)
        sh.formula(f"{c}{r['fcf']}", f"{c}{r['nopat']}-{c}{r['reinv']}", NUM)
        sh.formula(f"{c}{r['pre']}", f"{I['pre'][j]}", DEC4)
        sh.formula(f"{c}{r['post']}", f"{I['post'][j]}", DEC4)
        sh.formula(f"{c}{r['t']}", f"{I['t'][j]}", DEC4)
        sh.formula(f"{c}{r['pv']}", f"{c}{r['fcf']}*({c}{r['pre']}+{c}{r['post']}*(1+{wacc})^(-{c}{r['t']}))", NUM)
    last = col(1 + n)
    b = top + 18
    rows = ["Terminal growth", "Terminal revenue", "Terminal operating margin", "Terminal NOPAT",
            "Terminal FCF (NOPAT x (1 - g / ROIC))", "Terminal value", "PV of terminal value", "Sum of PV of FCF",
            "Enterprise value", "Equity bridge (cash - debt - other claims)", "Equity value",
            "Value per ordinary share", "Value per US share"]
    for i, t in enumerate(rows):
        sh.label(f"A{b + i}", t)
    sh.formula(f"B{b}", f"{tg}", PCT)
    sh.formula(f"B{b + 1}", f"{last}{r['rev']}*(1+B{b})", NUM)
    sh.formula(f"B{b + 2}", f"{last}{r['margin']}", PCT)
    sh.formula(f"B{b + 3}", f"B{b + 1}*B{b + 2}*(1-{I['tax_t']})", NUM)
    sh.formula(f"B{b + 4}", f"B{b + 3}*(1-B{b}/{I['roic']})", NUM)
    sh.formula(f"B{b + 5}", f"B{b + 4}/({wacc}-B{b})", NUM)
    sh.formula(f"B{b + 6}", f"B{b + 5}*(1+{wacc})^(-{I['t_tv']})", NUM)
    sh.formula(f"B{b + 7}", f"SUM(B{r['pv']}:{last}{r['pv']})", NUM)
    sh.formula(f"B{b + 8}", f"B{b + 7}+B{b + 6}", NUM, bold=True)
    sh.formula(f"B{b + 9}", f"{I['bridge']}", NUM)
    sh.formula(f"B{b + 10}", f"B{b + 8}+B{b + 9}", NUM)
    sh.formula(f"B{b + 11}", f"B{b + 10}/{I['shares']}", PS)
    sh.formula(f"B{b + 12}", f"B{b + 11}*{I['adr']}", PS, bold=True)
    return {"vps": sh.ref(f"B{b + 12}"), "ev": sh.ref(f"B{b + 8}"), "tv": sh.ref(f"B{b + 6}"),
            "end_row": b + 13, "fcf_row": r["fcf"], "rev_row": r["rev"], "nopat_row": r["nopat"],
            "reinv_row": r["reinv"], "last_col": last}


# --- workbook -------------------------------------------------------------------------------------------------------
def build_workbook(rep) -> Workbook:
    """`rep` is a desks.pipeline.FullReport (or any object with .model / .company / .md / .ticker)."""
    m = rep.model
    if getattr(m, "financial", None) is not None:  # bank / insurer / REIT toolkit
        from exports.excel_fin import build_financial_workbook
        return build_financial_workbook(rep)
    v, ei = m.valuation, m.inputs
    d = v.dcf_inputs
    if d is None or v.dcf is None:
        raise ValueError("no DCF to export")
    wb = Workbook()
    name = getattr(rep.company.profile, "name", rep.ticker) if rep.company else rep.ticker
    cover = Sheet(wb, "Cover", "US$ millions unless stated", first=True)
    inp = Sheet(wb, "Inputs", "US$ millions unless stated; percentages as decimals",
                "Blue = input (yellow fill = assumption). Sources in column C.")
    n = len(d.years)
    I: dict = {}

    # --- Inputs ------------------------------------------------------------------------------------------------
    row = 5

    def add(label, value, fmt, source, assumption=False, key=None):
        nonlocal row
        inp.label(f"A{row}", label)
        inp.input(f"B{row}", value, fmt, assumption)
        inp.ws[f"C{row}"] = source
        inp.ws[f"C{row}"].font = Font(size=9, color="595959")
        ref = inp.ref(f"B{row}")
        if key:
            I[key] = ref
        row += 1
        return ref

    inp.head(f"A{row}", "Market and capital structure")
    row += 1
    add("Share price (US$ per US share)", ei.price.value, PS, f"{ei.price.source} {ei.price.period}", key="price")
    add("ADR ratio (ordinary shares per US share)", ei.adr_ratio, "0.00", "data_desk/adr.py", key="adr")
    add("Diluted ordinary shares (m)", v.diluted_shares.value, NUM1, v.diluted_shares.formula or "reported",
        key="shares")
    add("Market capitalisation", ei.market_cap.value, NUM, ei.market_cap.source or "calculated", key="mcap")
    for bname, bval in v.bridge:
        add(f"Equity bridge: {bname}", bval.value, NUM, bval.source if not bval.formula else bval.formula,
            key=f"bridge_{bname}")
    row += 1
    inp.head(f"A{row}", "WACC inputs")
    row += 1
    w = v.wacc
    add("Risk-free rate", ei.risk_free.value, PCT2, f"{ei.risk_free.source} {ei.risk_free.period}", key="rf")
    add("Equity risk premium", ei.erp.value, PCT2, f"{ei.erp.source} {ei.erp.period}", key="erp")
    add("Industry unlevered beta", ei.industry.unlevered_beta.value if ei.industry.unlevered_beta else 0, "0.00",
        ei.industry.how, True, key="beta_u")
    add("Beta used (industry relevered unless overridden)", w.beta.value, "0.00",
        "relevered: unlevered x (1 + (1 - tax) x D/E)" if w.relevered_industry_beta is not None and
        w.beta.value == w.relevered_industry_beta.value else w.beta.source, True, key="beta_used")
    add("Country risk premium", ei.crp.value, PCT2, ei.crp.source, True, key="crp")
    add("Pre-tax cost of debt", v.cost_of_debt_detail["pre_tax_cost_of_debt"].value, PCT2,
        str(v.cost_of_debt_detail.get("rating")), True, key="kd")
    add("Marginal tax rate", ei.marginal_tax.value, PCT2, ei.marginal_tax.note or ei.marginal_tax.source, key="tax_m")
    add("Debt used in WACC weights", w.inputs.debt.value, NUM, "debt for valuation", key="debt_w")
    row += 1
    inp.head(f"A{row}", "Forecast drivers")
    row += 1
    hdr = row
    inp.label(f"A{hdr}", "Fiscal year")
    for j, y in enumerate(d.years):
        inp.input(f"{col(2 + j)}{hdr}", y.label)
    row += 1
    I["years"] = [inp.ref(f"{col(2 + j)}{hdr}") for j in range(n)]

    def add_row(label, values, fmt, key, assumption=True):
        nonlocal row
        inp.label(f"A{row}", label)
        refs = []
        for j, x in enumerate(values):
            inp.input(f"{col(2 + j)}{row}", x, fmt, assumption)
            refs.append(inp.ref(f"{col(2 + j)}{row}"))
        I[key] = refs
        row += 1

    add_row("Revenue growth", [y.revenue_growth for y in d.years], PCT, "growth")
    add_row("Operating margin (GAAP)", [y.operating_margin for y in d.years], PCT, "margin")
    add_row("Tax rate", [y.tax_rate for y in d.years], PCT, "tax")
    add_row("Sales-to-capital", [y.sales_to_capital for y in d.years], "0.00", "s2c")
    add_row("Timing: share of year earned before today", [t[0] for t in d.timing], DEC4, "pre", False)
    add_row("Timing: share of year still to come", [t[1] for t in d.timing], DEC4, "post", False)
    add_row("Timing: discount period (years)", [t[2] for t in d.timing], DEC4, "t", False)
    inp.ws[f"A{row}"] = ("Timing comes from the dates: cash generated after the latest balance sheet is counted; the "
                         "part before the valuation date is not discounted.")
    inp.ws[f"A{row}"].font = Font(size=9, italic=True, color="595959")
    row += 2
    inp.head(f"A{row}", "Terminal value and base")
    row += 1
    add("Base-year revenue", d.base_revenue, NUM, f"{d.base_label} (SEC XBRL, US$)", key="base_rev")
    add("Terminal growth", d.terminal_growth, PCT2, v.plan.terminal_growth.note or "", True, key="tg")
    add("Terminal ROIC", d.terminal_roic, PCT2, v.plan.terminal_roic.note or "", True, key="roic")
    add("Terminal tax rate (marginal)", d.terminal_tax_rate if d.terminal_tax_rate is not None else d.years[-1].tax_rate,
        PCT2, "statutory rate in steady state", True, key="tax_t")
    add("Years from today to end of final forecast year", d.end_of_final_year, DEC4, "dates", key="end_n")
    add("Max terminal growth in scenarios", 0.0 if v.classification.stage == "declining" else ei.risk_free.value,
        PCT2, "risk-free rate (0% for declining companies)", key="g_cap")
    row += 1
    inp.head(f"A{row}", "Scenarios")
    row += 1
    for s in v.scenarios:
        sc = s.scenario
        add(f"{sc.name}: probability", sc.probability, PCT, sc.describe(), True, key=f"p_{sc.name}")
        add(f"{sc.name}: revenue growth shift", sc.growth_shift, PCT, "points per year", True, key=f"gs_{sc.name}")
        add(f"{sc.name}: margin shift", sc.margin_shift, PCT, "points", True, key=f"ms_{sc.name}")
        add(f"{sc.name}: WACC shift", sc.wacc_shift, PCT2, "points", True, key=f"ws_{sc.name}")
        add(f"{sc.name}: terminal growth shift", sc.terminal_growth_shift, PCT2, "points", True, key=f"ts_{sc.name}")
    row += 1
    inp.head(f"A{row}", "Valuation blend")
    row += 1
    weights = m.verdict.weights_used
    for k in ("dcf", "comps", "history"):
        add(f"Weight: {k}", weights.get(k, 0.0), PCT, "default 50/30/20, rescaled if a method is missing", True,
            key=f"w_{k}")
    for col_letter in "BCDEFGHIJKL":
        inp.ws.column_dimensions[col_letter].width = 13
    inp.ws.column_dimensions["C"].width = 13
    I["bridge"] = "+".join(I[f"bridge_{b}"] for b, _ in v.bridge)
    # peer and past EVs net only cash, so their multiples already price any investments: the multiples bridge leaves
    # out long-term investments (as the app does), or they would be counted twice
    I["bridge_multiples"] = "+".join(I[f"bridge_{b}"] for b, _ in v.bridge if b != "Long-term investments") or "0"

    # --- Historicals and Ratios --------------------------------------------------------------------------------------
    h = ei.historicals
    hs = Sheet(wb, "Historicals", "US$ millions", "Source: SEC EDGAR XBRL companyfacts (tag per number in the app's "
                                                  "provenance table). Blue = reported input.")
    periods = [p.label for p in h.periods]
    hs.head("A4", "Line")
    for j, p in enumerate(periods):
        hs.head(f"{col(2 + j)}4", p)
    hlines = ["revenue", "operating_income", "d_and_a", "ebitda", "net_income_attributable", "sbc", "cfo", "capex",
              "fcf", "total_assets", "total_equity", "cash_and_investments", "debt_for_valuation", "net_debt",
              "shares_diluted_weighted"]
    hrow = {}
    for i, line in enumerate(hlines):
        rr = 5 + i
        hrow[line] = rr
        hs.label(f"A{rr}", line.replace("_", " ").capitalize())
        for j, p in enumerate(periods):
            x = h.v(line, p)
            if x is not None:
                hs.input(f"{col(2 + j)}{rr}", x, NUM)
    for j in range(len(periods)):
        hs.ws.column_dimensions[col(2 + j)].width = 12
    rs = Sheet(wb, "Ratios", "percentages", "Calculated from the Historicals tab (green = cross-sheet link).")
    rs.head("A4", "Ratio")
    for j, p in enumerate(periods):
        rs.head(f"{col(2 + j)}4", p)
    ratio_rows = [("Revenue growth", lambda c, pc: f"IF(ISNUMBER(Historicals!{pc}{hrow['revenue']}),Historicals!{c}{hrow['revenue']}/Historicals!{pc}{hrow['revenue']}-1,\"\")" if pc else None),
                  ("Operating margin", lambda c, pc: f"IFERROR(Historicals!{c}{hrow['operating_income']}/Historicals!{c}{hrow['revenue']},\"\")"),
                  ("EBITDA margin", lambda c, pc: f"IFERROR(Historicals!{c}{hrow['ebitda']}/Historicals!{c}{hrow['revenue']},\"\")"),
                  ("FCF margin", lambda c, pc: f"IFERROR(Historicals!{c}{hrow['fcf']}/Historicals!{c}{hrow['revenue']},\"\")"),
                  ("SBC % revenue", lambda c, pc: f"IFERROR(Historicals!{c}{hrow['sbc']}/Historicals!{c}{hrow['revenue']},\"\")"),
                  ("FCF / net income", lambda c, pc: f"IFERROR(Historicals!{c}{hrow['fcf']}/Historicals!{c}{hrow['net_income_attributable']},\"\")"),
                  ("Net debt / EBITDA", lambda c, pc: f"IFERROR(Historicals!{c}{hrow['net_debt']}/Historicals!{c}{hrow['ebitda']},\"\")")]
    for i, (label, fn) in enumerate(ratio_rows):
        rr = 5 + i
        rs.label(f"A{rr}", label)
        for j in range(len(periods)):
            c, pc = col(2 + j), (col(1 + j) if j > 0 else None)
            f = fn(c, pc)
            if f:
                rs.formula(f"{c}{rr}", f, MULT if "/" in label else PCT)

    # --- WACC ---------------------------------------------------------------------------------------------------------
    ws_ = Sheet(wb, "WACC", "percentages", "CAPM with a revenue-weighted country risk premium; market-value weights.")
    lines = [("D/E (debt / market cap)", f"{I['debt_w']}/{I['mcap']}", "0.00"),
             ("Cost of equity = rf + beta x ERP + CRP", f"{I['rf']}+{I['beta_used']}*{I['erp']}+{I['crp']}", PCT2),
             ("After-tax cost of debt", f"{I['kd']}*(1-{I['tax_m']})", PCT2),
             ("Equity weight", f"{I['mcap']}/({I['mcap']}+{I['debt_w']})", PCT),
             ("Debt weight", f"{I['debt_w']}/({I['mcap']}+{I['debt_w']})", PCT),
             ("WACC", "B6*B8+B9*B7", PCT2),
             ("Relevered industry beta (reference)", f"{I['beta_u']}*(1+(1-{I['tax_m']})*B5)", "0.00")]
    for i, (label, f, fmt) in enumerate(lines):
        ws_.label(f"A{5 + i}", label, bold=label == "WACC")
        ws_.formula(f"B{5 + i}", f, fmt, bold=label == "WACC")
    I["wacc"] = ws_.ref("B10")
    I["coe"] = ws_.ref("B6")
    ws_.ws.column_dimensions["B"].width = 14

    # --- Forecast + DCF -----------------------------------------------------------------------------------------
    I["t_tv"] = f"({I['end_n']}-0.5)" if d.conventions.discounting == "mid_year" else I["end_n"]
    dcf_s = Sheet(wb, "DCF", "US$ millions unless stated", "Base case. SBC is a cash cost (GAAP operating income "
                                                          "already expenses it). Mid-year discounting.")
    base = dcf_block(dcf_s, 5, n, I, "Base case DCF")
    for j in range(n):
        dcf_s.ws.column_dimensions[col(2 + j)].width = 12
    fc = Sheet(wb, "Forecast", "US$ millions", "Links to the base-case DCF (green).")
    fc.head("A4", "Line")
    for j in range(n):
        fc.formula(f"{col(2 + j)}4", f"DCF!{col(2 + j)}6")
    for i, (label, src_row) in enumerate([("Revenue growth", 7), ("Revenue", 8), ("Operating margin", 9),
                                          ("EBIT", 10), ("Tax", 13), ("NOPAT", 15), ("Reinvestment", 16),
                                          ("Free cash flow", 17)]):
        fc.label(f"A{5 + i}", label)
        for j in range(n):
            fc.formula(f"{col(2 + j)}{5 + i}", f"DCF!{col(2 + j)}{src_row}", PCT if "growth" in label or "margin" in label else NUM)

    # --- Scenarios and sensitivity (calculation blocks) ------------------------------------------------------------
    calc = Sheet(wb, "Calc", "US$ millions", "Full DCF recalculated for each scenario and each sensitivity cell.")
    top = 5
    scen_refs = {}
    for s in v.scenarios:
        nm = s.scenario.name
        g_expr = f"MIN({I['tg']}+{I[f'ts_{nm}']},{I['g_cap']})"
        blk = dcf_block(calc, top, n, I, f"{nm} scenario", g_shift=I[f"gs_{nm}"], m_shift=I[f"ms_{nm}"],
                        wacc=f"({I['wacc']}+{I[f'ws_{nm}']})", tg=g_expr)
        scen_refs[nm] = blk["vps"]
        top = blk["end_row"] + 2
    sens1, sens2 = v.sensitivity_wacc_growth, v.sensitivity_growth_margin
    grid1, grid2 = [], []
    for gi, gd in enumerate((-0.01, -0.005, 0, 0.005, 0.01)):
        row_refs = []
        for wd in (-0.01, -0.005, 0, 0.005, 0.01):
            blk = dcf_block(calc, top, n, I, f"WACC {wd:+.1%} / g {gd:+.1%}", wacc=f"({I['wacc']}+{wd})",
                            tg=f"({I['tg']}+{gd})")
            row_refs.append(blk["vps"])
            top = blk["end_row"] + 2
        grid1.append(row_refs)
    for gs in (-0.04, -0.02, 0, 0.02, 0.04):
        row_refs = []
        for ms in (-0.04, -0.02, 0, 0.02, 0.04):
            blk = dcf_block(calc, top, n, I, f"growth {gs:+.0%} / margin {ms:+.0%}", g_shift=str(gs), m_shift=str(ms))
            row_refs.append(blk["vps"])
            top = blk["end_row"] + 2
        grid2.append(row_refs)

    sc = Sheet(wb, "Scenarios", "US$ per US share", "Each scenario is a full DCF on the Calc tab.")
    for i, s in enumerate(v.scenarios):
        nm = s.scenario.name
        sc.label(f"A{5 + i}", f"{nm}: {s.scenario.describe()}")
        sc.formula(f"B{5 + i}", scen_refs[nm], PS)
        sc.formula(f"C{5 + i}", I[f"p_{nm}"], PCT)
    k = 5 + len(v.scenarios)
    sc.label(f"A{k}", "Probability-weighted DCF value", bold=True)
    sc.formula(f"B{k}", f"SUMPRODUCT(B5:B{k - 1},C5:C{k - 1})", PS, bold=True)
    sc.ws.column_dimensions["A"].width = 70
    dcf_weighted = sc.ref(f"B{k}")

    se = Sheet(wb, "Sensitivity", "US$ per US share", "Each cell is a full DCF on the Calc tab.")
    se.label("A4", "WACC (columns) x terminal growth (rows)", bold=True)
    for wi, wd in enumerate((-0.01, -0.005, 0, 0.005, 0.01)):
        se.formula(f"{col(2 + wi)}5", f"{I['wacc']}+{wd}", PCT2)
    for gi, gd in enumerate((-0.01, -0.005, 0, 0.005, 0.01)):
        se.formula(f"A{6 + gi}", f"{I['tg']}+{gd}", PCT2)
        for wi in range(5):
            se.formula(f"{col(2 + wi)}{6 + gi}", grid1[gi][wi], PS)
    se.label("A13", "Revenue growth shift (rows) x operating margin shift (columns)", bold=True)
    for mi, ms in enumerate((-0.04, -0.02, 0, 0.02, 0.04)):
        se.input(f"{col(2 + mi)}14", ms, PCT)
    for gi, gs in enumerate((-0.04, -0.02, 0, 0.02, 0.04)):
        se.input(f"A{15 + gi}", gs, PCT)
        for mi in range(5):
            se.formula(f"{col(2 + mi)}{15 + gi}", grid2[gi][mi], PS)

    # --- SOTP ----------------------------------------------------------------------------------------------------
    sotp_ref = None
    if v.sotp.applicable:
        so = Sheet(wb, "SOTP", "US$ millions; multiples in x",
                   "Each segment: its operating income x the median EV/EBIT of US-listed comparables (EV/Sales on revenue "
                   "when it has no operating profit); unallocated corporate costs capitalised and deducted.")
        for j, hd in enumerate(["Segment", "Basis", "Metric", "Multiple", "EV", "Source"]):
            so.head(f"{col(1 + j)}4", hd)
        segs = {sg.name: sg for sg in ei.segments}
        for i, (nm, ev, how) in enumerate(v.sotp.segment_values):
            r_, sg = 5 + i, segs.get(nm)
            so.label(f"A{r_}", nm)
            if sg is not None and sg.metric_value is not None and sg.multiple is not None:
                so.label(f"B{r_}", f"{sg.metric} on {'operating income' if sg.metric == 'EV/EBIT' else 'revenue'}")
                so.input(f"C{r_}", sg.metric_value, NUM)
                so.input(f"D{r_}", sg.multiple, MULT)
                so.formula(f"E{r_}", f"C{r_}*D{r_}", NUM)
                so.label(f"F{r_}", sg.multiple_source)
            else:  # a segment DCF value
                so.label(f"B{r_}", how)
                so.input(f"E{r_}", ev, NUM)
        k = 5 + len(v.sotp.segment_values)
        so.label(f"A{k}", "Enterprise value", bold=True)
        so.formula(f"E{k}", f"SUM(E5:E{k - 1})", NUM, bold=True)
        so.label(f"A{k + 1}", "Value per US share", bold=True)
        so.formula(f"E{k + 1}", f"(E{k}+{I['bridge']})/{I['shares']}*{I['adr']}", PS, bold=True)
        so.ws.column_dimensions["A"].width = 34
        so.ws.column_dimensions["B"].width = 26
        sotp_ref = so.ref(f"E{k + 1}")

    # --- Comps -----------------------------------------------------------------------------------------------------
    co = Sheet(wb, "Comps", "US$ millions; multiples in x", "Peer data from each peer's SEC filings and market data.")
    comps_ref = None
    if m.comps and m.comps.peers and getattr(m, "company_metrics", None) is not None:
        heads = ["Ticker", "Market cap", "Debt", "Cash", "Minorities", "Revenue", "EBITDA", "FCF", "Net income",
                 "P/E", "EV/Sales", "EV/EBITDA", "EV/FCF"]
        for j, hd in enumerate(heads):
            co.head(f"{col(1 + j)}4", hd)
        for i, p in enumerate(m.comps.peers):
            r_ = 5 + i
            co.input(f"A{r_}", p.ticker)
            for j, x in enumerate([p.market_cap, p.debt, p.cash, p.minority, p.revenue, p.ebitda, p.fcf, p.net_income]):
                if x is not None:
                    co.input(f"{col(2 + j)}{r_}", x, NUM)
            ev = f"(B{r_}+C{r_}-D{r_}+E{r_})"
            pe_ok = "TRUE" if p.pe_meaningful else "FALSE"
            # multiples above NM_ABOVE are not meaningful (blank), as in the app
            co.formula(f"J{r_}", f'IF(AND({pe_ok},I{r_}>0,B{r_}/I{r_}<={NM_ABOVE["pe_trailing"]:g}),B{r_}/I{r_},"")'
                       if p.net_income is not None else '""', MULT)
            for cc, metric, key in (("K", "F", "ev_sales"), ("L", "G", "ev_ebitda"), ("M", "H", "ev_fcf")):
                co.formula(f"{cc}{r_}", f'IFERROR(IF(AND({metric}{r_}>0,{ev}>0,{ev}/{metric}{r_}<={NM_ABOVE[key]:g}),'
                                        f'{ev}/{metric}{r_},""),"")', MULT)
        last = 4 + len(m.comps.peers)
        co.label(f"A{last + 1}", "Peer median", bold=True)
        for cc in "JKLM":
            co.formula(f"{cc}{last + 1}", f'IFERROR(MEDIAN({cc}5:{cc}{last}),"")', MULT, bold=True)
        own = getattr(m, "company_metrics", None)
        cm_row = last + 3
        co.label(f"A{cm_row}", f"Company metrics ({own.period}, SEC XBRL)", bold=True)
        implied = []
        r_ = cm_row + 1
        for label, cc, key, metric in (("Revenue", "K", "ev_sales", own.revenue), ("EBITDA", "L", "ev_ebitda", own.ebitda),
                                       ("FCF", "M", "ev_fcf", own.fcf), ("Net income", "J", "pe_trailing", own.net_income)):
            mres = m.comps.multiples[key]
            if mres.implied_price is None or metric is None or not mres.in_blend:
                continue  # fewer than 3 peers, negative metric, P/E distorted by one-offs, or margins not comparable
            co.label(f"A{r_}", f"{label} (company)")
            co.input(f"B{r_}", metric, NUM)
            co.label(f"C{r_}", f"Implied price at peer median {mres.label}")
            if key == "pe_trailing":
                co.formula(f"D{r_}", f"{cc}{last + 1}*B{r_}/{I['shares']}*{I['adr']}", PS)
            else:
                co.formula(f"D{r_}", f"({cc}{last + 1}*B{r_}+{I['bridge_multiples']})/{I['shares']}*{I['adr']}", PS)
            implied.append(f"D{r_}")
            r_ += 1
        if implied:
            co.label(f"A{r_ + 1}", "Comps value (median of implied prices)", bold=True)
            co.formula(f"D{r_ + 1}", f"MEDIAN({','.join(implied)})", PS, bold=True)
            comps_ref = co.ref(f"D{r_ + 1}")
    else:
        co.label("A5", "No usable peers for this company.")

    # --- Historical multiples (inputs per year, formulas for median and implied price) ----------------------------------
    hist_ref = None
    if m.history and any(x.implied_price is not None for x in m.history.values()):
        hm = Sheet(wb, "Hist multiples", "multiples in x; US$ per US share",
                   "Multiple at each fiscal year end: split-adjusted price x restated shares, that year's fundamentals.")
        hm.head("A4", "Multiple")
        years = sorted({y for x in m.history.values() for y in x.series})
        for j, y in enumerate(years):
            hm.head(f"{col(2 + j)}4", y)
        mc = col(2 + len(years))
        hm.head(f"{mc}4", "Median")
        hm.head(f"{col(3 + len(years))}4", "Company metric")
        hm.head(f"{col(4 + len(years))}4", "Implied price")
        implied = []
        r_ = 5
        for x in m.history.values():
            if x.implied_price is None:
                continue
            hm.label(f"A{r_}", x.label)
            for j, y in enumerate(years):
                if y in x.series:
                    hm.input(f"{col(2 + j)}{r_}", x.series[y], MULT)
            hm.formula(f"{mc}{r_}", f"MEDIAN(B{r_}:{col(1 + len(years))}{r_})", MULT)
            bridge_total = sum(b.value for n, b in v.bridge if n != "Long-term investments")
            if x.key == "pe_trailing":
                metric = x.implied_price / ei.adr_ratio * v.diluted_shares.value / x.median
                f = f"{mc}{r_}*{col(3 + len(years))}{r_}/{I['shares']}*{I['adr']}"
            else:
                metric = (x.implied_price / ei.adr_ratio * v.diluted_shares.value - bridge_total) / x.median
                f = f"({mc}{r_}*{col(3 + len(years))}{r_}+{I['bridge_multiples']})/{I['shares']}*{I['adr']}"
            hm.input(f"{col(3 + len(years))}{r_}", metric, NUM)
            hm.formula(f"{col(4 + len(years))}{r_}", f, PS)
            implied.append(f"{col(4 + len(years))}{r_}")
            r_ += 1
        hm.label(f"A{r_ + 1}", "Historical-multiples value (median of implied prices)", bold=True)
        hm.formula(f"{col(4 + len(years))}{r_ + 1}", f"MEDIAN({','.join(implied)})", PS, bold=True)
        hist_ref = hm.ref(f"{col(4 + len(years))}{r_ + 1}")

    # --- Summary ---------------------------------------------------------------------------------------------------
    su = Sheet(wb, "Summary", "US$ per US share", "Fair value = weighted blend (weights on the Inputs tab).")
    # a method the workbook could not rebuild (e.g. a report saved before company metrics were stored) is carried
    # as an input from the app, so the blend still matches; missing methods get zero weight via the Inputs tab
    comps_link = comps_ref or (str(m.verdict.components.get("comps")) if m.verdict.components.get("comps") else "0")
    hist_link = hist_ref or (str(m.verdict.components.get("history")) if m.verdict.components.get("history") else "0")
    dcf_link = sotp_ref or dcf_weighted
    rows_ = [("Share price", I["price"], PS), ("DCF (probability-weighted)" if not sotp_ref else "Sum of the parts",
                                               dcf_link, PS),
             ("Comps", comps_link, PS), ("Historical multiples", hist_link, PS)]
    for i, (label, f, fmt) in enumerate(rows_):
        su.label(f"A{5 + i}", label)
        su.formula(f"B{5 + i}", f, fmt)
    su.label("A10", "Fair value (weighted blend)", bold=True)
    su.formula("B10", f"(B6*{I['w_dcf']}+B7*{I['w_comps']}+B8*{I['w_history']})/({I['w_dcf']}+{I['w_comps']}+{I['w_history']})",
               PS, bold=True)
    su.label("A11", "Upside / (downside) to fair value")
    su.formula("B11", "B10/B5-1", PCT)
    su.label("A12", "Verdict (price > 15% below fair value = Undervalued; > 15% above = Overvalued)")
    su.formula("B12", 'IF(B5<B10*0.85,"Undervalued",IF(B5>B10*1.15,"Overvalued","Fairly valued"))')
    su.label("A14", "Check: base-case DCF per share in the app", bold=True)
    su.input("B14", v.per_us_share(v.dcf.value_per_share), PS)
    su.label("A15", "Check: Excel minus app (should be 0.00)")
    su.formula("B15", f"{base['vps']}-B14", PS, check=True)
    su.label("A16", "Check: fair value in the app")
    su.input("B16", m.verdict.fair_value, PS)
    su.label("A17", "Check: Excel minus app (should be 0.00)")
    su.formula("B17", "B10-B16", PS, check=True)
    su.ws.column_dimensions["A"].width = 70
    su.ws.column_dimensions["B"].width = 16

    # --- Analysis: what explains the value ------------------------------------------------------------------------
    analysis_sheet(wb, rep, I, base)

    # --- Cover ---------------------------------------------------------------------------------------------------------
    cover.ws["A4"] = f"{name} ({rep.ticker})"
    cover.ws["A4"].font = Font(bold=True, size=16)
    info = [("Report", getattr(rep, "report_id", "")), ("Valuation date", str(getattr(rep, "valuation_date", ""))),
            ("Stage", v.classification.stage_label), ("Toolkit", v.classification.toolkit),
            ("Verdict (app)", m.verdict.verdict), ("Confidence", m.verdict.confidence),
            ("MD rating", rep.md.rating if getattr(rep, "md", None) else "n/a")]
    for i, (k_, x) in enumerate(info):
        cover.label(f"A{6 + i}", k_)
        cover.ws[f"B{6 + i}"] = x
    cover.label("A14", "Fair value (US$ per share)", bold=True)
    cover.formula("B14", "Summary!B10", PS, bold=True)
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
    cover.ws["A24"] = ("Based on assumptions and public data; may contain errors; not financial advice.")
    cover.ws["A24"].font = Font(italic=True, size=9)
    cover.ws.column_dimensions["B"].width = 30
    return wb


def analysis_sheet(wb: Workbook, rep, I: dict, base: dict) -> None:
    """The report's explaining analyses: the walk from our DCF to the price, what the price pays for (live formulas on
    the DCF tab), the Monte Carlo range and the peer regressions (live SLOPE / INTERCEPT / RSQ on the peers)."""
    from engine.classify import DECLINING
    from engine.insights import (peer_regressions, price_walk, return_on_new_capital, tornado,
                                 value_split)
    from ui.insights import dividend_for, mc_for, walk_args
    m = rep.model
    v = m.valuation
    if v is None or getattr(v, "dcf_inputs", None) is None or v.dcf is None:
        return
    f = v.per_us_share_factor
    an = Sheet(wb, "Analysis", "US$ per US share unless stated",
               "Explains the value: the walk to the price, the no-growth split, the Monte Carlo range and peer "
               "regressions. None of these changes the fair value.")
    an.ws.column_dimensions["A"].width = 60
    for c_ in "BCD":
        an.ws.column_dimensions[c_].width = 15
    r = 5
    # 1. walk from our DCF to the price
    steps = price_walk(v.dcf_inputs, m.verdict.price / f, *walk_args(rep))
    an.label(f"A{r}", "1. From our DCF to the share price, one assumption at a time", bold=True)
    r += 1
    for j, hd in enumerate(["Step", "Value", "Change", "Detail"]):
        an.head(f"{col(1 + j)}{r}", hd)
    r += 1
    first = r
    for i, st_ in enumerate(steps):
        an.label(f"A{r}", st_["label"])
        an.input(f"B{r}", st_["value"] * f, PS)
        if i:
            an.formula(f"C{r}", f"B{r}-B{r - 1}", PS)
        an.label(f"D{r}", st_["detail"])
        r += 1
    an.label(f"A{r}", "Share price")
    an.formula(f"B{r}", I["price"], PS)
    an.formula(f"C{r}", f"B{r}-B{r - 1}", PS)
    an.label(f"D{r}", "left after the last step (0.00 when the last step solves for the price)")
    an.label(f"A{r + 1}", "Check: first step minus the base-case DCF (should be 0.00)")
    an.formula(f"B{r + 1}", f"B{first}-{base['vps']}", PS, check=True)
    r += 3
    # 2. what the price pays for
    sp = value_split(v.dcf, m.verdict.price / f)
    if sp is not None:
        an.label(f"A{r}", "2. What the price pays for (US$ millions unless stated)", bold=True)
        r += 1
        rows = [("Year-1 NOPAT on today's revenue (base revenue x year-1 margin x (1 - tax))",
                 f"{I['base_rev']}*{I['margin'][0]}*(1-{I['tax'][0]})", NUM),
                ("WACC", I["wacc"], PCT2),
                ("No-growth value (NOPAT / WACC)", f"B{r}/B{r + 1}", NUM),
                ("Our enterprise value (DCF tab)", base["ev"], NUM),
                ("of which growth (EV - no-growth value)", f"B{r + 3}-B{r + 2}", NUM),
                ("Market enterprise value (price / ADR ratio x shares - bridge)",
                 f"{I['price']}/{I['adr']}*{I['shares']}-({I['bridge']})", NUM),
                ("of which the market pays for growth", f"B{r + 5}-B{r + 2}", NUM),
                ("Share of the market's EV that is growth", f"B{r + 6}/B{r + 5}", PCT),
                ("No-growth value per US share", f"(B{r + 2}+{I['bridge']})/{I['shares']}*{I['adr']}", PS),
                ("Our EV in the forecast years (PV of FCF)", f"{base['ev']}-{base['tv']}", NUM),
                ("Our EV in the terminal value", base["tv"], NUM),
                ("Terminal value share of our EV", f"B{r + 10}/B{r + 3}", PCT)]
        for i, (label, fm, fmt) in enumerate(rows):
            an.label(f"A{r + i}", label)
            an.formula(f"B{r + i}", fm, fmt)
        an.label(f"A{r + len(rows)}", "Check: no-growth value minus the app (should be 0)")
        an.formula(f"B{r + len(rows)}", f"B{r + 2}-{sp['no_growth_ev']!r}", NUM, check=True)
        k = r + len(rows) + 1
        lc = base["last_col"]
        an.label(f"A{k}", "Total reinvestment over the forecast (DCF tab)")
        an.formula(f"B{k}", f"SUM(DCF!B{base['reinv_row']}:{lc}{base['reinv_row']})", NUM)
        an.label(f"A{k + 1}", "NOPAT in the final forecast year (DCF tab)")
        an.formula(f"B{k + 1}", f"DCF!{lc}{base['nopat_row']}", NUM)
        an.label(f"A{k + 2}", "Return on new capital ((final NOPAT - today's NOPAT) / reinvestment); compare with WACC",
                 bold=True)
        an.formula(f"B{k + 2}", f"(B{k + 1}-B{r})/B{k}", PCT, bold=True)
        rn = return_on_new_capital(v.dcf)
        if rn is not None:
            an.label(f"A{k + 3}", "Check: Excel minus app (should be 0.0%)")
            an.formula(f"B{k + 3}", f"B{k + 2}-{rn['roic_new']!r}", PCT, check=True)
        r = k + 5
    # 3. Monte Carlo
    mc, corr, ind = mc_for(rep)
    if mc:
        an.label(f"A{r}", "3. Monte Carlo range of the DCF (from the app's simulation; fixed seed)", bold=True)
        r += 1
        how = (f"growth and margin drawn with their measured correlation of {corr['rho']:+.2f} ({corr['n']} years)"
               if corr else "inputs drawn independently")
        an.label(f"A{r}", f"{mc['valid']:,} DCFs; {how}")
        r += 1
        both = bool(corr and ind)
        for j, hd in enumerate(["Percentile", "Value"] + (["Independent"] if both else [])):
            an.head(f"{col(1 + j)}{r}", hd)
        r += 1
        for p_ in sorted(mc["pct"]):
            an.label(f"A{r}", f"{p_}th")
            an.input(f"B{r}", mc["pct"][p_] * f, PS)
            if both:
                an.input(f"C{r}", ind["pct"][p_] * f, PS)
            r += 1
        an.label(f"A{r}", "Chance the value is above the price")
        an.input(f"B{r}", mc["prob_above_price"], PCT)
        if both:
            an.input(f"C{r}", ind["prob_above_price"], PCT)
        r += 2
    # 4. peer regressions
    cm = getattr(m, "company_metrics", None)
    if m.comps and m.comps.peers and cm is not None:
        br = sum(x.value for n_, x in v.bridge if n_ != "Long-term investments")
        regs = [g for g in peer_regressions(cm, m.comps.peers, v.diluted_shares.value, br, f) if g["applicable"]]
        if regs:
            an.label(f"A{r}", "4. Peer regressions: the multiple the peers' line gives the company (cross-check)",
                     bold=True)
            r += 1
        for g in regs:
            metric = cm.revenue if g["key"] == "ev_sales" else cm.ebitda
            if not metric or not g["implied_price"]:
                continue
            an.label(f"A{r}", f"{g['label']} against {g['driver']}", bold=True)
            r += 1
            an.head(f"A{r}", "Peer")
            an.head(f"B{r}", g["driver"].capitalize())
            an.head(f"C{r}", g["label"])
            r += 1
            top = r
            for t_, x_, y_ in g["points"]:
                an.label(f"A{r}", t_)
                an.input(f"B{r}", x_, PCT)
                an.input(f"C{r}", y_, MULT)
                r += 1
            xs, ys = f"B{top}:B{r - 1}", f"C{top}:C{r - 1}"
            rows = [("Slope", f"SLOPE({ys},{xs})", DEC4), ("Intercept", f"INTERCEPT({ys},{xs})", DEC4),
                    ("R squared", f"RSQ({ys},{xs})", DEC4)]
            for i, (label, fm, fmt) in enumerate(rows):
                an.label(f"A{r + i}", label)
                an.formula(f"B{r + i}", fm, fmt)
            an.label(f"A{r + 3}", f"Company's {g['driver']}")
            an.input(f"B{r + 3}", g["company_x"], PCT)
            an.label(f"A{r + 4}", "Warranted multiple (intercept + slope x company's driver)")
            an.formula(f"B{r + 4}", f"B{r + 1}+B{r}*B{r + 3}", MULT)
            an.label(f"A{r + 5}", ("Company revenue" if g["key"] == "ev_sales" else "Company EBITDA") + " (US$m)")
            an.input(f"B{r + 5}", metric, NUM)
            an.label(f"A{r + 6}", "Implied value per US share ((multiple x metric + bridge) / shares x ADR)", bold=True)
            an.formula(f"B{r + 6}", f"(B{r + 4}*B{r + 5}+{I['bridge_multiples']})/{I['shares']}*{I['adr']}", PS,
                       bold=True)
            an.label(f"A{r + 7}", "Check: Excel minus app (should be 0.00)")
            an.formula(f"B{r + 7}", f"B{r + 6}-{g['implied_price']!r}", PS, check=True)
            r += 9
    # 5. dividend cross-check: dividends grow with the DCF tab's NOPAT, discounted at the cost of equity
    dv, dsrc = dividend_for(rep)
    if dv:
        an.label(f"A{r}", "5. Dividend cross-check (per ordinary share; ignores buybacks; not in the fair value)",
                 bold=True)
        r += 1
        an.label(f"A{r}", f"Dividend per share ({dsrc})")
        an.input(f"B{r}", dv["dps0"], PS)
        an.label(f"A{r + 1}", "Cost of equity (WACC tab)")
        an.formula(f"B{r + 1}", I["coe"], PCT2)
        an.label(f"A{r + 2}", "Terminal growth")
        an.formula(f"B{r + 2}", I["tg"], PCT2)
        an.label(f"A{r + 3}", "Today's NOPAT (as in section 2)")
        an.formula(f"B{r + 3}", f"{I['base_rev']}*{I['margin'][0]}*(1-{I['tax'][0]})", NUM)
        d0, cc, gg, n0 = f"B{r}", f"B{r + 1}", f"B{r + 2}", f"B{r + 3}"
        r += 5
        for j, hd in enumerate(["Year", "NOPAT (DCF tab)", "Dividend", "PV"]):
            an.head(f"{col(1 + j)}{r}", hd)
        r += 1
        top = r
        for t, row in enumerate(dv["rows"], start=1):
            c_ = col(1 + t)  # DCF tab column of forecast year t
            an.label(f"A{r}", row["year"])
            an.formula(f"B{r}", f"MAX(DCF!{c_}{base['nopat_row']},0)", NUM)
            an.formula(f"C{r}", f"{d0}*B{r}/{n0}", PS)
            an.formula(f"D{r}", f"C{r}*(1+{cc})^(-{t})", PS)
            r += 1
        last = r - 1
        n = len(dv["rows"])
        rows = [("Terminal value (last dividend x (1 + g) / (CoE - g))", f"C{last}*(1+{gg})/({cc}-{gg})"),
                ("PV of terminal value", f"B{r}*(1+{cc})^(-{n})"),
                ("Dividend model value per ordinary share", f"SUM(D{top}:D{last})+B{r + 1}"),
                ("Dividend model value per US share", f"B{r + 2}*{I['adr']}"),
                ("Dividend growth for ever the price implies ((P x CoE - D0) / (P + D0))",
                 f"({I['price']}/{I['adr']}*{cc}-{d0})/({I['price']}/{I['adr']}+{d0})")]
        for i, (label, fm) in enumerate(rows):
            an.label(f"A{r + i}", label, bold=i == 3)
            an.formula(f"B{r + i}", fm, PCT if i == 4 else PS, bold=i == 3)
        an.label(f"A{r + 5}", "Check: Excel minus app (should be 0.00)")
        an.formula(f"B{r + 5}", f"B{r + 3}-{dv['value'] * v.per_us_share_factor!r}", PS, check=True)
        r += 7
    # 6. tornado
    cap = 0.0 if v.classification.stage == DECLINING else m.inputs.risk_free.value
    rows = tornado(v.dcf_inputs, cap)
    if rows:
        an.label(f"A{r}", "6. Which assumption matters most: each input alone at its bear and bull setting "
                 "(from the app)", bold=True)
        r += 1
        for j, hd in enumerate(["Input (bear / bull setting)", "Bear", "Bull", "Swing"]):
            an.head(f"{col(1 + j)}{r}", hd)
        r += 1
        for row in rows:
            an.label(f"A{r}", f"{row['label']} ({row['low_detail']} / {row['high_detail']})")
            an.input(f"B{r}", row["low"] * f, PS)
            an.input(f"C{r}", row["high"] * f, PS)
            an.formula(f"D{r}", f"C{r}-B{r}", PS)
            r += 1


def export_bytes(rep, cached: bool = True) -> bytes:
    """The workbook as bytes; `cached` stores each formula's result too, so previews and Protected View show numbers."""
    buf = BytesIO()
    build_workbook(rep).save(buf)
    return with_cached_values(buf.getvalue()) if cached else buf.getvalue()
