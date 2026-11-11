"""Report views that explain the valuation: the walk from our DCF to the share price, what the price pays for, the
Monte Carlo range and regression-based peer multiples. Computed on the fly from the saved model (engine.insights is
pure and fast), so every saved report gets them; each view says how to read it."""
from __future__ import annotations

from functools import lru_cache
from statistics import median

import plotly.graph_objects as go
import streamlit as st

from engine.analysis import invested_capital_at
from engine.classify import DECLINING
from engine.insights import (MIN_CORR_YEARS, dividend_check, growth_margin_correlation, monte_carlo, peer_regressions,
                             pooled_growth_margin_correlation, price_walk,
                             economic_profit, return_on_new_capital, tornado, value_split)
from engine.report_mc import history_pairs, mc_cached, mc_for  # noqa: F401 - re-exported for the exports and talking points
from ui.format import millions, money, mult, pct, plain_table
from ui.theme import ACCENT, BORDER, FAINT, MUTED, TEXT, esc, guide, plotly_layout

CHART_CONFIG = {"displayModeBar": False}
NM_EV_EBIT = 100.0  # EV/EBIT above this is not meaningful (near-zero operating income)


def _html(s: str) -> None:
    st.markdown(s, unsafe_allow_html=True)


def _kv(items: list[tuple[str, str, str]], accent: int | None = None) -> str:
    """Key figures in a row: (label, value, note)."""
    return "<div class='vt-kv'>" + "".join(
        f"<div><div class='l'>{esc(a)}</div><div class='v{' acc' if i == accent else ''}'>{esc(b)}</div>"
        f"<div class='s'>{esc(c)}</div></div>" for i, (a, b, c) in enumerate(items)) + "</div>"


def _ordinary_price(m) -> float:
    return m.verdict.price / m.valuation.per_us_share_factor


def walk_args(rep) -> tuple:
    """Today's effective tax rate and ROIC (latest fiscal year) and operating margin (latest period, LTM if any).
    Without the company's analysis, only the discount-rate step of the walk is possible."""
    h, a = getattr(rep.company, "historicals_usd", None), getattr(rep.company, "analysis", None)
    if h is None or a is None or not h.fy_labels:
        return None, None, None, rep.model.inputs.risk_free.value
    fy = h.fy_labels[-1]
    latest = h.ltm.label if h.ltm else fy
    eff, roic = a.metrics.get("effective_tax_rate", {}).get(fy), a.metrics.get("roic", {}).get(fy)
    return (eff.value if eff else None, roic.value if roic else None, a.m("operating_margin", latest),
            rep.model.inputs.risk_free.value)


# --- 1. walk to the price (in the reverse DCF section) ---------------------------------------------------------------
def walk_view(rep) -> None:
    v = rep.model.valuation
    if v is None or v.dcf_inputs is None:
        return
    f, price = v.per_us_share_factor, rep.model.verdict.price
    steps = price_walk(v.dcf_inputs, price / f, *walk_args(rep))
    st.markdown("#### From our DCF to the share price, one assumption at a time")
    _html(guide("The first bar is our DCF value per share. Each bar after it changes one assumption and shows how "
                "many dollars that adds. When the price is above our value, the first steps swap our cautious choices "
                "for ones many sell-side models make (each kept only where it is more generous than ours); the last "
                "step is the discount rate the price then needs. The bars add up exactly to the gap between our value "
                "and the price, so you can see which assumption explains how much of it."))
    xs = [s["label"].replace(" the price needs", "<br>the price needs").replace(" held", "<br>held") for s in steps]
    xs.append("Share price")
    ys = [steps[0]["value"] * f] + [s["change"] * f for s in steps[1:]] + [0]
    measures = ["absolute"] + ["relative"] * (len(steps) - 1) + ["total"]
    labels = [money(steps[0]["value"] * f)] + [f"{s['change'] * f:+,.2f}" for s in steps[1:]] + [money(price)]
    fig = go.Figure(go.Waterfall(
        x=xs, y=ys, measure=measures, text=labels, textposition="outside", cliponaxis=False,
        textfont=dict(family="IBM Plex Mono", size=12, color=TEXT),
        increasing=dict(marker=dict(color=ACCENT)), decreasing=dict(marker=dict(color="#c4b49c")),
        totals=dict(marker=dict(color="rgba(237,228,211,.75)")),
        connector=dict(line=dict(color=BORDER, width=1, dash="dot")),
        hovertemplate="%{x}: %{text}<extra></extra>"))
    top = max(max(s["value"] for s in steps) * f, price)
    fig.update_layout(**plotly_layout(height=400, margin=dict(l=10, r=10, t=36, b=10),
                                      yaxis=dict(title="US$ per share", range=[0, top * 1.16]),
                                      xaxis=dict(tickfont=dict(size=11, color=MUTED))))
    st.plotly_chart(fig, width="stretch", config=CHART_CONFIG)
    rows = [[s["label"], f"{s['change'] * f:+,.2f}" if i else "–", money(s["value"] * f), s["detail"]]
            for i, s in enumerate(steps)]
    _html(plain_table(rows, ["Step", "Change", "Value per share", "What changed"]))
    gap = price - steps[0]["value"] * f
    conv = sum(s["change"] for s in steps[1:] if s["label"] not in ("Discount rate the price needs", "Not explained")) * f
    rate = next((s for s in steps if s["label"] == "Discount rate the price needs"), None)
    if gap and abs(gap) > 0.01:
        items = [("Gap to explain", f"{gap:+,.2f}", f"price {money(price)} less our DCF {money(steps[0]['value'] * f)}")]
        if conv:
            items.append(("Sell-side conventions", f"{conv:+,.2f}", f"{conv / gap:.0%} of the gap"))
        if rate:
            items.append(("Discount rate", f"{rate['change'] * f:+,.2f}", rate["detail"]))
        _html(_kv(items, accent=len(items) - 1))


# --- 2. what the price pays for (in the DCF section) -----------------------------------------------------------------
def split_view(rep) -> None:
    v = rep.model.valuation
    if v is None or v.dcf is None:
        return
    st.markdown("#### What the price is paying for")
    sp = value_split(v.dcf, _ordinary_price(rep.model))
    if sp is None:
        _html(guide("Not shown: year-1 operating profit after tax is not positive, so there is no meaningful "
                    "'today's profits with no growth' value to compare against.", "Why it is missing"))
        return
    ng, ev, mev = sp["no_growth_ev"], sp["ev"], sp["market_ev"]
    _html(guide(f"Today's profits with no growth: year-1 operating profit after tax ({millions(sp['nopat'])}) "
                f"divided by WACC ({pct(sp['wacc'])}), i.e. what the business is worth if it never grew. Everything "
                f"above that is a bet on growth. The market row uses the share price: price x shares, less the "
                f"bridge from enterprise value to equity (US$ millions)."))
    if sp["growth_ev"] < 0:
        _html(guide(f"Our DCF ({millions(ev)}) is below the no-growth value ({millions(ng)}): in the forecast, the "
                    f"money reinvested to grow earns less than the {pct(sp['wacc'])} cost of capital, so growth "
                    f"subtracts value. The market prices the opposite: {millions(mev)}.", "What this means"))
    else:
        fig = go.Figure()
        rows = ["Market price", "Our DCF"]
        fig.add_bar(y=rows, x=[ng, ng], orientation="h", name="Today's profits, no growth",
                    marker=dict(color="rgba(196,180,156,.55)"), text=[millions(ng)] * 2, textposition="inside",
                    insidetextanchor="middle", textfont=dict(family="IBM Plex Mono", size=12, color="#0a0908"),
                    hovertemplate="No growth: %{x:,.0f}m<extra></extra>")
        fig.add_bar(y=rows, x=[max(sp["market_growth_ev"], 0), sp["growth_ev"]], orientation="h", name="Growth",
                    marker=dict(color=[ACCENT, "rgba(255,122,26,.6)"]),
                    text=[millions(sp["market_growth_ev"]), millions(sp["growth_ev"])], textposition="inside",
                    insidetextanchor="middle", textfont=dict(family="IBM Plex Mono", size=12, color="#0a0908"),
                    hovertemplate="Growth: %{x:,.0f}m<extra></extra>")
        fig.update_layout(**plotly_layout(height=230, barmode="stack", showlegend=True, bargap=0.35,
                                          legend=dict(orientation="h", y=1.25, x=0, font=dict(color=MUTED)),
                                          margin=dict(l=10, r=10, t=40, b=10),
                                          xaxis=dict(title="Enterprise value, US$ millions")))
        st.plotly_chart(fig, width="stretch", config=CHART_CONFIG)
    items = [("Today's profits, no growth", millions(ng), f"{ng / mev:.0%} of the market's EV" if mev > 0 else "")]
    if ev > 0:
        items.append(("Growth in our DCF", millions(sp["growth_ev"]),
                      f"{sp['growth_ev'] / ev:.0%} of our EV" if sp["growth_ev"] >= 0 else "growth subtracts value"))
    if mev > 0:
        items.append(("Growth in the price", millions(sp["market_growth_ev"]),
                      f"{sp['market_growth_ev'] / mev:.0%} of the market's EV"))
    if ev > 0 and sp["pv_forecast"] > 0:
        items.append(("Beyond year " + str(sp["years"]), f"{sp['pv_terminal'] / ev:.0%}",
                      "of our EV comes from the terminal value"))
    _html(_kv(items, accent=2 if mev > 0 and ev > 0 else None))
    rn = return_on_new_capital(v.dcf)
    if rn is not None:
        verdict = ("above the WACC: the forecast's growth adds value" if rn["roic_new"] > rn["wacc"] else
                   "below the WACC: the forecast's growth subtracts value" if rn["gain"] > 0 else
                   "operating profit after tax falls while the forecast reinvests")
        _html(guide(f"Is the forecast reinvesting enough for its growth? It puts US${rn['reinvestment']:,.0f}m into "
                    f"the business over {rn['years']} years and operating profit after tax goes from "
                    f"US${rn['nopat0']:,.0f}m to US${rn['nopat_final']:,.0f}m: a return on that new capital of "
                    f"{pct(rn['roic_new'])}, {verdict} ({pct(rn['wacc'])}).", "Return on new capital"))


def exit_multiple_check(rep) -> dict | None:
    """The EV/EBIT our terminal value implies, against the selected peers' median EV/EBIT today and the company's own
    (the market's EV over its latest operating income). None without a terminal multiple."""
    m = rep.model
    v = m.valuation
    if v is None or v.dcf is None or not v.dcf.implied_exit_ebit_multiple:
        return None
    peers = [p.ev / p.operating_income for p in (m.comps.peers if m.comps else [])
             if p.ev and p.operating_income and p.operating_income > 0 and 0 < p.ev / p.operating_income <= NM_EV_EBIT]
    me, own = m.company_metrics, None
    sp = value_split(v.dcf, _ordinary_price(m))
    if me is not None and me.operating_income and me.operating_income > 0 and sp and sp["market_ev"] > 0:
        own = sp["market_ev"] / me.operating_income
    return {"exit": v.dcf.implied_exit_ebit_multiple, "final_year": v.dcf.years[-1].label,
            "peer_median": median(peers) if peers else None, "peers": len(peers), "own": own,
            "own_period": getattr(me, "period", "")}


def exit_view(rep) -> None:
    x = exit_multiple_check(rep)
    if x is None:
        return
    items = [(f"Terminal value / EBIT {x['final_year']}", mult(x["exit"]), "what our DCF pays at the end")]
    if x["peer_median"] is not None:
        items.append(("Peers today", mult(x["peer_median"]), f"median EV/EBIT of {x['peers']} selected peers"))
    if x["own"] is not None:
        items.append((f"{rep.ticker} today", mult(x["own"]), f"market EV / operating income, {x['own_period']}"))
    _html(guide("The terminal value as a multiple of the final forecast year's operating income, set against what "
                "the peers and the company trade on today. A terminal multiple below today's is normal, because "
                "growth has slowed to the terminal rate by then; one well above the peers would mean the DCF is "
                "paying more for a mature business than the market pays for growing ones.", "Terminal value check"))
    _html(_kv(items, accent=0))


def ep_for(rep) -> tuple[dict | None, str]:
    """The economic-profit split of the base-case DCF, with capital from the US$ balance sheet of the DCF's base
    period (equity + debt - cash - investments valued in the bridge), and where that capital came from."""
    v = rep.model.valuation
    h = getattr(rep.company, "historicals_usd", None) or rep.company.historicals
    if v is None or v.dcf is None or h is None:
        return None, ""
    p = v.dcf.inputs.base_label
    ic = invested_capital_at(h, p)
    return economic_profit(v.dcf, ic), f"equity + debt - cash - investments in the bridge, {p} balance sheet"


def ep_view(rep) -> None:
    ep, src = ep_for(rep)
    if ep is None:
        return
    st.markdown("#### The same DCF as capital plus value created")
    _html(guide(f"Economic profit is operating profit after tax less a charge for the capital it needs: WACC on the "
                f"capital at the start of the year, and on the year's new capital from mid-year. Our DCF's enterprise value is exactly the capital in the business "
                f"today ({src}), plus the present value of each year's economic profit, plus the terminal value above "
                f"the capital the forecast ends with. A business only adds value above its capital when it earns more "
                f"than its WACC (US$ millions)."))
    ev = ep["ev"]
    _html(_kv([("Capital in the business", millions(ep["capital"]), f"{ep['capital'] / ev:.0%} of our EV" if ev > 0
                else ""),
               (f"Economic profit, years 1-{len(ep['rows'])}", millions(ep["pv_ep"]),
                f"{ep['pv_ep'] / ev:.0%} of our EV (present value)" if ev > 0 else "present value"),
               ("After the forecast, above capital", millions(ep["beyond"]),
                f"{ep['beyond'] / ev:.0%} of our EV" if ev > 0 else "")], accent=1))
    rows = ep["rows"]
    _html(plain_table([["Capital at start"] + [millions(r["capital"]) for r in rows],
                       ["Return on capital"] + [pct(r["return"]) for r in rows],
                       ["Operating profit after tax"] + [millions(r["nopat"]) for r in rows],
                       ["Capital charge"] + [millions(r["charge"]) for r in rows],
                       ["Economic profit"] + [millions(r["ep"]) for r in rows]],
                      [""] + [r["label"] for r in rows]))
    st.caption("Year 1 covers the part of the year the DCF counts, so its profit and charge are for that part only "
               "(its return on capital is for the full year). Figures are at mid-year, where the DCF counts profit. "
               "Capital grows by the DCF's reinvestment.")


def dividend_for(rep) -> tuple[dict | None, str]:
    """The dividend cross-check (per ordinary share) and where the dividend per share came from. Dividends declared
    per share in the latest fiscal year; else dividends paid / diluted shares."""
    m = rep.model
    v = m.valuation
    h = getattr(rep.company, "historicals_usd", None)
    if v is None or v.dcf is None or h is None or not h.fy_labels:
        return None, ""
    fy = h.fy_labels[-1]
    dps, src = h.v("dps_declared", fy), f"dividends declared per share, {fy}"
    if not dps:
        paid = h.v("dividends_paid", fy)
        dps = paid / v.diluted_shares.value if paid and v.diluted_shares.value else None
        src = f"dividends paid / diluted shares, {fy}"
    if not dps:
        return None, ""
    return dividend_check(v.dcf, dps, v.wacc.cost_of_equity.value, v.plan.terminal_growth.value,
                          _ordinary_price(m)), src


def dividend_view(rep) -> None:
    d, src = dividend_for(rep)
    if d is None:
        return
    f = rep.model.valuation.per_us_share_factor
    dcf_v = rep.model.valuation.per_us_share(rep.model.valuation.dcf.value_per_share)
    st.markdown("#### Dividend cross-check")
    _html(guide(f"A second way to value the shares, from the dividend alone ({money(d['dps0'] * f)} a share, "
                f"{src}). Dividends grow in line with the DCF's operating profit after tax for {d['years']} years "
                f"(the payout held constant: {pct(d['stage1_cagr'])} a year), then at {pct(d['terminal_growth'])}, "
                f"discounted at the {pct(d['cost_of_equity'])} cost of equity. It ignores buybacks, so for a "
                "company that also buys back shares it reads low. The last figure turns it round: the dividend "
                "growth for ever that today's price needs. A cross-check, not part of the fair value."))
    _html(_kv([("Dividend model value", money(d["value"] * f), f"against our base-case DCF {money(dcf_v)}"),
               ("Dividend yield", pct(d["yield"]), "latest fiscal year's dividend / price"),
               ("Growth the price implies", pct(d["implied_growth"]),
                f"dividend growth for ever at a {pct(d['cost_of_equity'])} cost of equity")], accent=2))


def tornado_view(rep) -> None:
    v = rep.model.valuation
    if v is None or v.dcf_inputs is None:
        return
    cap = 0.0 if v.classification.stage == DECLINING else rep.model.inputs.risk_free.value
    rows = tornado(v.dcf_inputs, cap)
    if not rows:
        return
    f = v.per_us_share_factor
    base = rows[0]["base"] * f
    st.markdown("#### Which assumption matters most")
    _html(guide("Each bar moves one input at a time from the base case to its bear setting (left end) and its bull "
                "setting (right end), the same steps as the scenarios above; sales-to-capital, which the scenarios do "
                "not move, goes 20% either way. The longest bar is the assumption to argue about; the line is the "
                "base-case value."))
    fig = go.Figure()
    labels = [r["label"] for r in rows][::-1]
    for key, colour, name in (("low", "rgba(196,180,156,.55)", "Bear setting"), ("high", ACCENT, "Bull setting")):
        fig.add_bar(y=labels, x=[(r[key] - r["base"]) * f for r in rows][::-1], base=base, orientation="h",
                    name=name, marker=dict(color=colour),
                    customdata=[[r[key] * f, r[key + "_detail"]] for r in rows][::-1],
                    hovertemplate="%{y}, %{customdata[1]}: $%{customdata[0]:,.2f}<extra></extra>")
    fig.add_vline(x=base, line=dict(color=TEXT, width=1))
    fig.update_layout(**plotly_layout(height=60 + 46 * len(rows), barmode="overlay", showlegend=True, bargap=0.35,
                                      legend=dict(orientation="h", y=1.12, x=0, font=dict(color=MUTED)),
                                      margin=dict(l=10, r=10, t=40, b=10),
                                      xaxis=dict(title="Value per share, US$", tickprefix="$")))
    st.plotly_chart(fig, width="stretch", config=CHART_CONFIG)
    _html(_kv([(r["label"], f"{money(r['low'] * f)} to {money(r['high'] * f)}",
                f"{r['low_detail']} / {r['high_detail']}") for r in rows[:3]], accent=0))


# --- 3. Monte Carlo (in the scenarios section) -----------------------------------------------------------------------
def monte_carlo_view(rep) -> None:
    v = rep.model.valuation
    if v is None or v.dcf_inputs is None:
        return
    f, price = v.per_us_share_factor, rep.model.verdict.price
    mc, corr, ind = mc_for(rep)
    st.markdown("#### How wide is the range? 2,000 versions of the DCF")
    if mc is None:
        _html(guide("Not shown: too many of the random draws gave an invalid DCF.", "Why it is missing"))
        return
    sp = mc["spreads"]
    if corr:
        link = (f"Growth and margin are drawn together, with a correlation of {corr['rho']:+.2f}, measured from "
                f"{corr['basis']} of revenue growth against the change in its operating margin"
                + (f" ({corr['raw']:+.2f}, capped at 0.8 because a few years cannot make it certain)"
                   if corr["raw"] != corr["rho"] else "")
                + "; WACC and terminal growth are drawn independently.")
    else:
        link = ("All four are drawn independently (fewer than six years of history to measure how growth and margin "
                "move together).")
    _html(guide(f"Each version shifts four inputs at random, by amounts with a standard deviation of "
                f"{sp['growth'] * 100:.1f} points for revenue growth, {sp['margin'] * 100:.1f} for operating margin, "
                f"{sp['wacc'] * 100:.2f} for WACC and {sp['terminal_growth'] * 100:.2f} for terminal growth. Those "
                f"spreads make each input's 10th-90th percentile range equal to the bear-to-bull step above. {link} "
                "The bars show how often each value came up. The inputs rarely all go wrong together, so the range is "
                "narrower than bear-to-bull. The random seed is fixed: the same result on every run."))
    vals = [x * f for x in mc["values"]]
    p = {k: x * f for k, x in mc["pct"].items()}
    base = v.per_us_share(v.dcf.value_per_share)
    fig = go.Figure(go.Histogram(x=vals, nbinsx=60, marker=dict(color="rgba(255,122,26,.55)",
                                                                line=dict(color="rgba(255,122,26,.9)", width=0.5)),
                                 hovertemplate="%{x}: %{y} versions<extra></extra>"))
    fig.add_vrect(x0=p[10], x1=p[90], fillcolor="rgba(255,122,26,.07)", line_width=0)
    lo, hi = min(p[5], price, base), max(p[95], price, base)
    pad = (hi - lo) * 0.08
    # labels point away from each other when the lines are close (so they never overlap) and towards each other when
    # far apart (so a line near the edge keeps its label inside the chart)
    outward = abs(price - base) < 0.3 * (hi - lo + 2 * pad)
    for x, other, name, colour, dash in ((price, base, f"Price {money(price)}", TEXT, "solid"),
                                         (base, price, f"Our DCF {money(base)}", ACCENT, "dash")):
        fig.add_vline(x=x, line=dict(color=colour, width=1.5, dash=dash))
        left = (x < other) == outward
        fig.add_annotation(x=x, y=1.02, yref="paper", text=name, showarrow=False, yanchor="bottom",
                           xanchor="right" if left else "left", xshift=-4 if left else 4,
                           font=dict(family="IBM Plex Mono", size=11, color=colour))
    fig.update_layout(**plotly_layout(height=330, margin=dict(l=10, r=10, t=40, b=10), bargap=0.04,
                                      xaxis=dict(title="US$ per share", range=[lo - pad, hi + pad]),
                                      yaxis=dict(title="Versions", tickfont=dict(color=FAINT))))
    st.plotly_chart(fig, width="stretch", config=CHART_CONFIG)
    bear, bull = (v.per_us_share(s.value_per_share) for s in (v.scenarios[0], v.scenarios[2])) \
        if len(v.scenarios) == 3 else (None, None)
    _html(_kv([("Median", money(p[50]), f"base case {money(base)}"),
               ("Middle 80% (10th-90th)", f"{money(p[10])} - {money(p[90])}",
                f"bear to bull {money(bear)} - {money(bull)}" if bear and bull else ""),
               ("Chance the value is above the price", f"{mc['prob_above_price']:.0%}",
                f"of {mc['valid']:,} versions above {money(price)}")]
              + ([("If drawn independently", f"{money(ind['pct'][10] * f)} - {money(ind['pct'][90] * f)}",
                   f"middle 80%; {ind['prob_above_price']:.0%} above the price")] if corr and ind else []), accent=2))


# --- 4. regression multiples (in the comps section) ------------------------------------------------------------------
def regression_view(rep) -> None:
    m, v = rep.model, rep.model.valuation
    c = m.comps
    if c is None or m.company_metrics is None or v is None:
        return
    bridge = sum(x.value for n, x in v.bridge if n != "Long-term investments")  # as in the comps value
    regs = peer_regressions(m.company_metrics, c.peers, v.diluted_shares.value, bridge, v.per_us_share_factor)
    st.markdown("#### Multiples adjusted for profitability and growth")
    _html(guide("A median multiple treats the company as an average peer. Here each multiple is plotted against what "
                "should explain it (EV/Sales against operating margin: a dollar of sales is worth more when more of "
                "it turns into profit; EV/EBITDA against revenue growth), a straight line is fitted through the "
                "peers, and the company's 'warranted' multiple is read off the line at its own margin or growth. "
                "R² says how much of the spread in the peers' multiples the line explains (1 = all of it). With five "
                "to eight peers this is a cross-check: it is not part of the fair value."))
    shown = [r for r in regs if r["applicable"]]
    for r in regs:
        if not r["applicable"]:
            st.caption(f"{r['label']} against {r['driver']}: not shown, {r['reason']}.")
    if not shown:
        return
    cols = st.columns(len(shown)) if len(shown) > 1 else [st.container()]
    for col, r in zip(cols, shown):
        xs = [x * 100 for _, x, _ in r["points"]]
        line_x = [min(xs + [r["company_x"] * 100]), max(xs + [r["company_x"] * 100])]
        span_x = (line_x[1] - line_x[0]) or 1.0
        top_y = max([y for _, _, y in r["points"]] + [r["warranted"], r["company_multiple"] or 0])
        fig = go.Figure()
        fig.add_scatter(x=line_x, y=[r["intercept"] + r["slope"] * x / 100 for x in line_x], mode="lines",
                        line=dict(color=MUTED, width=1.5, dash="dot"), hoverinfo="skip")
        fig.add_scatter(x=xs, y=[y for _, _, y in r["points"]], mode="markers+text", text=[t for t, _, _ in r["points"]],
                        textposition="top center", textfont=dict(size=10, color=MUTED),
                        marker=dict(size=9, color="rgba(196,180,156,.75)"),
                        hovertemplate="%{text}: %{y:.1f}x at %{x:.1f}%<extra></extra>")
        fig.add_scatter(x=[r["company_x"] * 100], y=[r["warranted"]], mode="markers+text", text=[f"{rep.ticker} warranted"],
                        textposition="middle left", textfont=dict(size=11, color=ACCENT),
                        marker=dict(size=12, color=ACCENT, symbol="diamond"),
                        hovertemplate="warranted %{y:.1f}x<extra></extra>")
        if r["company_multiple"] is not None:
            fig.add_scatter(x=[r["company_x"] * 100], y=[r["company_multiple"]], mode="markers+text",
                            text=[f"{rep.ticker} today"], textposition="middle left",
                            textfont=dict(size=11, color=TEXT), marker=dict(size=10, color=TEXT, symbol="circle-open"),
                            hovertemplate="today %{y:.1f}x<extra></extra>")
        fig.update_layout(**plotly_layout(height=380, margin=dict(l=10, r=24, t=44, b=10),
                                          title=dict(text=f"{r['label']} vs {r['driver']} · R² {r['r2']:.2f}",
                                                     font=dict(size=13, color=TEXT), x=0),
                                          xaxis=dict(title=f"{r['driver'].capitalize()} (%)",
                                                     range=[line_x[0] - span_x * 0.15, line_x[1] + span_x * 0.08]),
                                          yaxis=dict(title=r["label"], range=[0, top_y * 1.15])))
        col.plotly_chart(fig, width="stretch", config=CHART_CONFIG)
    rows = []
    for r in shown:
        med = c.multiples[r["key"]]
        rows.append([r["label"], f"{r['driver']} {pct(r['company_x'])}", str(len(r["points"])), f"{r['r2']:.2f}",
                     mult(med.median), money(med.implied_price), mult(r["warranted"]), money(r["implied_price"])])
    _html(plain_table(rows, ["Multiple", "Company's driver", "Peers", "R²", "Peer median", "Implied at median",
                             "Warranted", "Implied at warranted"]))
    ex = [r for r in shown if r["extrapolated"]]
    if ex:
        st.caption("Read with care: " + "; ".join(f"{rep.ticker}'s {r['driver']} ({pct(r['company_x'])}) is outside "
                                                    f"the peers' range, so its {r['label']} is extrapolated beyond "
                                                    f"the data" for r in ex) + ".")
