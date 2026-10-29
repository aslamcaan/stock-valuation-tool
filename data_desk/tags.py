"""Standard line items -> candidate XBRL tags (US GAAP and IFRS), in priority order.

Each alternative is a tuple of tags that are summed (usually a single tag). For each line the
extractor uses the alternative with the best coverage of recent fiscal years, then fills gaps from
the others, and logs the tag used for every value.
"""
from __future__ import annotations

from dataclasses import dataclass

G = "us-gaap"
I = "ifrs-full"
D = "dei"


@dataclass(frozen=True)
class Line:
    label: str
    statement: str  # "IS", "BS", "CF", "SH" (shares), "PS" (per share), "OT" (other)
    kind: str  # "duration" or "instant"
    alternatives: tuple[tuple[tuple[str, str], ...], ...]
    unit: str = "money"  # "money", "shares", "per_share"


OPT = ("opt", "")  # marker: an alternative starting with OPT needs its first tag; the others are added if reported


def a(*tags: tuple[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(tags)


def opt(*tags: tuple[str, str]) -> tuple[tuple[str, str], ...]:
    return (OPT,) + tuple(tags)


def L(label, statement, kind, *alts, unit="money") -> Line:
    return Line(label, statement, kind, tuple(x if isinstance(x[0], tuple) else (x,) for x in alts), unit)


LINES: dict[str, Line] = {
    # --- income statement --------------------------------------------------------------------
    "revenue": L("Revenue", "IS", "duration",
                 (G, "Revenues"), (G, "RevenueFromContractWithCustomerExcludingAssessedTax"),
                 (G, "RevenueFromContractWithCustomerIncludingAssessedTax"), (G, "SalesRevenueNet"),
                 (G, "SalesRevenueGoodsNet"), (I, "Revenue"), (I, "RevenueFromContractsWithCustomers")),
    "cost_of_revenue": L("Cost of revenue", "IS", "duration",
                         (G, "CostOfRevenue"), (G, "CostOfGoodsAndServicesSold"), (G, "CostOfGoodsSold"),
                         (G, "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"),
                         (I, "CostOfSales")),
    "gross_profit": L("Gross profit", "IS", "duration", (G, "GrossProfit"), (I, "GrossProfit")),
    "rnd": L("Research and development", "IS", "duration",
             (G, "ResearchAndDevelopmentExpense"),
             (G, "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"),
             (I, "ResearchAndDevelopmentExpense")),
    "sga": L("Selling, general and administrative", "IS", "duration",
             (G, "SellingGeneralAndAdministrativeExpense"),
             a((G, "SellingAndMarketingExpense"), (G, "GeneralAndAdministrativeExpense")),
             a((I, "SalesAndMarketingExpense"), (I, "GeneralAndAdministrativeExpense")),
             (I, "SellingGeneralAndAdministrativeExpense")),
    "operating_income": L("Operating income", "IS", "duration",
                          (G, "OperatingIncomeLoss"), (I, "ProfitLossFromOperatingActivities")),
    "interest_expense": L("Interest expense", "IS", "duration",
                          (G, "InterestExpense"), (G, "InterestExpenseNonoperating"), (G, "InterestExpenseDebt"),
                          (G, "InterestAndDebtExpense"), (I, "FinanceCosts"), (I, "InterestExpense")),
    "pretax_income": L("Pre-tax income", "IS", "duration",
                       (G, "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"),
                       (G, "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"),
                       (G, "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic"),
                       (I, "ProfitLossBeforeTax")),
    "income_tax": L("Income tax", "IS", "duration",
                    (G, "IncomeTaxExpenseBenefit"), (I, "IncomeTaxExpenseContinuingOperations")),
    "net_income": L("Net income (consolidated)", "IS", "duration",
                    (G, "ProfitLoss"), (I, "ProfitLoss"),
                    (G, "NetIncomeLossIncludingPortionAttributableToNonredeemableNoncontrollingInterest")),
    "net_income_attributable": L("Net income to shareholders", "IS", "duration",
                                 (G, "NetIncomeLoss"), (I, "ProfitLossAttributableToOwnersOfParent"),
                                 (G, "NetIncomeLossAvailableToCommonStockholdersBasic"),
                                 (I, "ProfitLossAttributableToOrdinaryEquityHoldersOfParentEntity")),
    "eps_diluted": L("Diluted EPS", "PS", "duration",
                     (G, "EarningsPerShareDiluted"), (I, "DilutedEarningsLossPerShare"), unit="per_share"),
    "shares_basic_weighted": L("Weighted basic shares", "SH", "duration",
                               (G, "WeightedAverageNumberOfSharesOutstandingBasic"), (I, "WeightedAverageShares"),
                               unit="shares"),
    "shares_diluted_weighted": L("Weighted diluted shares", "SH", "duration",
                                 (G, "WeightedAverageNumberOfDilutedSharesOutstanding"),
                                 (I, "AdjustedWeightedAverageShares"), unit="shares"),
    # --- balance sheet -----------------------------------------------------------------------
    "cash": L("Cash and equivalents", "BS", "instant",
              (G, "CashAndCashEquivalentsAtCarryingValue"), (I, "CashAndCashEquivalents"), (G, "Cash")),
    "short_term_investments": L("Short-term investments", "BS", "instant",
                                (G, "ShortTermInvestments"), (G, "MarketableSecuritiesCurrent"),
                                (G, "AvailableForSaleSecuritiesDebtSecuritiesCurrent"),
                                (I, "CurrentInvestments"), (I, "OtherCurrentFinancialAssets")),
    "receivables": L("Receivables", "BS", "instant",
                     (G, "AccountsReceivableNetCurrent"), (G, "ReceivablesNetCurrent"),
                     (I, "CurrentTradeReceivables"), (I, "TradeAndOtherCurrentReceivables")),
    "inventory": L("Inventory", "BS", "instant", (G, "InventoryNet"), (I, "Inventories")),
    "current_assets": L("Total current assets", "BS", "instant", (G, "AssetsCurrent"), (I, "CurrentAssets")),
    "ppe_net": L("Property, plant and equipment", "BS", "instant",
                 (G, "PropertyPlantAndEquipmentNet"),
                 (G, "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization"),
                 (I, "PropertyPlantAndEquipment"), (I, "PropertyPlantAndEquipmentIncludingRightofuseAssets")),
    "goodwill": L("Goodwill", "BS", "instant", (G, "Goodwill"), (I, "Goodwill")),
    "intangibles": L("Intangible assets", "BS", "instant",
                     (G, "IntangibleAssetsNetExcludingGoodwill"), (G, "FiniteLivedIntangibleAssetsNet"),
                     (I, "IntangibleAssetsOtherThanGoodwill")),
    "total_assets": L("Total assets", "BS", "instant", (G, "Assets"), (I, "Assets")),
    "accounts_payable": L("Accounts payable", "BS", "instant",
                          (G, "AccountsPayableCurrent"), (G, "AccountsPayableTradeCurrent"),
                          (I, "TradeAndOtherCurrentPayablesToTradeSuppliers"), (I, "TradeAndOtherCurrentPayables")),
    "current_liabilities": L("Total current liabilities", "BS", "instant",
                             (G, "LiabilitiesCurrent"), (I, "CurrentLiabilities")),
    # Current debt: a single reported total if there is one; otherwise standardise.py adds the current
    # portion of long-term debt and short-term borrowings (two lines, so neither is double counted).
    "debt_current": L("Short-term debt and current portion", "BS", "instant",
                      (G, "DebtCurrent"), (I, "CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings"),
                      (I, "ShorttermBorrowings")),
    "current_portion_ltd": L("Current portion of long-term debt", "BS", "instant",
                             (G, "LongTermDebtCurrent"), (G, "LongTermDebtAndCapitalLeaseObligationsCurrent")),
    "short_term_borrowings": L("Short-term borrowings and commercial paper", "BS", "instant",
                               (G, "ShortTermBorrowings"), (G, "NotesAndLoansPayable"), (G, "DebtCurrentExcludingLongTermDebt"),
                               opt((G, "CommercialPaper"), (G, "OtherShortTermBorrowings"))),
    "long_term_debt": L("Long-term debt", "BS", "instant",
                        (G, "LongTermDebtNoncurrent"), (G, "LongTermDebtAndCapitalLeaseObligations"),
                        (G, "LongTermNotesPayable"), (G, "SeniorLongTermNotes"),
                        (I, "NoncurrentPortionOfNoncurrentBorrowings"), (I, "LongtermBorrowings"),
                        # REITs and others that tag debt by instrument rather than maturity
                        opt((G, "NotesPayable"), (G, "LoansPayable"), (G, "SecuredDebt"), (G, "UnsecuredDebt"),
                            (G, "LineOfCredit")),
                        # companies whose only debt is convertible notes
                        (G, "ConvertibleNotesPayable"), (G, "ConvertibleDebtNoncurrent"),
                        (G, "ConvertibleLongTermNotesPayable")),
    # All-in debt totals (current + non-current) where the filer reports one. Preferred over summing parts,
    # because parts can overlap (e.g. commercial paper reclassified to long-term). Tags containing
    # "CapitalLease" already include finance leases.
    "debt_total_reported": L("Total debt (as reported)", "BS", "instant",
                             (G, "DebtLongtermAndShorttermCombinedAmount"), (G, "DebtAndCapitalLeaseObligations")),
    # Long-term debt including current maturities (excludes short-term borrowings / commercial paper)
    "ltd_incl_current": L("Long-term debt incl. current maturities", "BS", "instant",
                          (G, "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities"), (G, "LongTermDebt")),
    "total_borrowings": L("Total borrowings (as reported)", "BS", "instant",
                          (G, "LongTermDebt"), (I, "Borrowings")),
    "operating_lease_liabilities": L("Operating lease liabilities", "BS", "instant",
                                     (G, "OperatingLeaseLiability"),
                                     a((G, "OperatingLeaseLiabilityCurrent"), (G, "OperatingLeaseLiabilityNoncurrent")),
                                     (I, "LeaseLiabilities"),
                                     a((I, "CurrentLeaseLiabilities"), (I, "NoncurrentLeaseLiabilities"))),
    "finance_lease_liabilities": L("Finance lease liabilities", "BS", "instant",
                                   (G, "FinanceLeaseLiability"),
                                   a((G, "FinanceLeaseLiabilityCurrent"), (G, "FinanceLeaseLiabilityNoncurrent"))),
    "total_liabilities": L("Total liabilities", "BS", "instant", (G, "Liabilities"), (I, "Liabilities")),
    "temporary_equity": L("Redeemable / temporary equity", "BS", "instant",
                          (G, "TemporaryEquityCarryingAmountIncludingPortionAttributableToNoncontrollingInterests"),
                          (G, "TemporaryEquityCarryingAmountAttributableToParent"),
                          (G, "RedeemableNoncontrollingInterestEquityCarryingAmount")),
    "parent_equity": L("Shareholders' equity", "BS", "instant",
                       (G, "StockholdersEquity"), (I, "EquityAttributableToOwnersOfParent")),
    # investments outside operating income (equity-method stakes, non-current securities): added in the equity
    # bridge, since their income is not in the operating income the DCF values
    "long_term_investments": L("Long-term investments (incl. equity-method)", "BS", "instant",
                               (G, "LongTermInvestments"),
                               opt((G, "EquityMethodInvestments"), (G, "MarketableSecuritiesNoncurrent")),
                               (G, "MarketableSecuritiesNoncurrent"),
                               opt((I, "InvestmentsAccountedForUsingEquityMethod"),
                                   (I, "NoncurrentInvestmentsOtherThanInvestmentsAccountedForUsingEquityMethod")),
                               (I, "NoncurrentInvestmentsOtherThanInvestmentsAccountedForUsingEquityMethod")),
    "depreciation": L("Depreciation (excluding amortisation)", "CF", "duration",
                      (G, "Depreciation"), (G, "DepreciationNonproduction"), (I, "AdjustmentsForDepreciationExpense"),
                      (I, "DepreciationExpense"), (I, "DepreciationPropertyPlantAndEquipment")),
    "income_continuing": L("Income from continuing operations", "IS", "duration",
                           (G, "IncomeLossFromContinuingOperations"), (I, "ProfitLossFromContinuingOperations")),
    "retained_earnings": L("Retained earnings (accumulated deficit)", "BS", "instant",
                           (G, "RetainedEarningsAccumulatedDeficit"), (I, "RetainedEarnings")),
    "minority_interest": L("Non-controlling interests", "BS", "instant",
                           (G, "MinorityInterest"), (I, "NoncontrollingInterests")),
    "total_equity": L("Total equity (incl. NCI)", "BS", "instant",
                      (G, "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"), (I, "Equity")),
    "preferred_equity": L("Preferred stock", "BS", "instant",
                          (G, "PreferredStockValue"), (G, "PreferredStockValueOutstanding")),
    "liabilities_and_equity": L("Total liabilities and equity", "BS", "instant",
                                (G, "LiabilitiesAndStockholdersEquity"), (I, "EquityAndLiabilities")),
    "shares_outstanding": L("Shares outstanding (balance sheet)", "SH", "instant",
                            (G, "CommonStockSharesOutstanding"), (I, "NumberOfSharesOutstanding"), unit="shares"),
    # --- equity awards (treasury-method dilution) ----------------------------------------------------
    "options_outstanding": L("Share options outstanding", "SH", "instant",
                             (G, "ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingNumber"),
                             (I, "NumberOfShareOptionsOutstandingInSharebasedPaymentArrangement"), unit="shares"),
    "options_strike": L("Options weighted-average exercise price", "PS", "instant",
                        (G, "ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingWeightedAverageExercisePrice"),
                        (I, "WeightedAverageExercisePriceOfShareOptionsOutstandingInSharebasedPaymentArrangement"),
                        unit="per_share"),
    "rsus_outstanding": L("Unvested RSUs / restricted shares", "SH", "instant",
                          (G, "ShareBasedCompensationArrangementByShareBasedPaymentAwardEquityInstrumentsOtherThanOptionsNonvestedNumber"),
                          unit="shares"),
    # --- cash flow ---------------------------------------------------------------------------
    "cfo": L("Cash from operations", "CF", "duration",
             (G, "NetCashProvidedByUsedInOperatingActivities"),
             (G, "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
             (I, "CashFlowsFromUsedInOperatingActivities")),
    "capex": L("Capital expenditure", "CF", "duration",
               (G, "PaymentsToAcquirePropertyPlantAndEquipment"),
               (G, "PaymentsToAcquireProductiveAssets"),
               (I, "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"),
               (I, "PurchaseOfPropertyPlantAndEquipment")),
    "capitalised_software_and_intangibles": L("Purchases of intangibles / capitalised software", "CF", "duration",
                                              (G, "PaymentsToDevelopSoftware"), (G, "PaymentsToAcquireIntangibleAssets"),
                                              (I, "PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities")),
    "d_and_a": L("Depreciation and amortisation", "CF", "duration",
                 (G, "DepreciationDepletionAndAmortization"), (G, "DepreciationAmortizationAndAccretionNet"),
                 (G, "DepreciationAndAmortization"),
                 a((G, "Depreciation"), (G, "AmortizationOfIntangibleAssets")),
                 (I, "DepreciationAndAmortisationExpense"),
                 a((I, "AdjustmentsForDepreciationExpense"), (I, "AdjustmentsForAmortisationExpense")),
                 (I, "DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss")),
    "sbc": L("Share-based compensation", "CF", "duration",
             (G, "ShareBasedCompensation"), (G, "AllocatedShareBasedCompensationExpense"),
             (I, "AdjustmentsForSharebasedPayments"),
             (I, "ExpenseFromSharebasedPaymentTransactionsWithEmployees")),
    "acquisitions": L("Acquisitions (net of cash)", "CF", "duration",
                      (G, "PaymentsToAcquireBusinessesNetOfCashAcquired"),
                      (I, "CashFlowsUsedInObtainingControlOfSubsidiariesOrOtherBusinessesClassifiedAsInvestingActivities")),
    "buybacks": L("Share repurchases", "CF", "duration",
                  (G, "PaymentsForRepurchaseOfCommonStock"), (G, "PaymentsForRepurchaseOfEquity"),
                  (I, "PaymentsToAcquireOrRedeemEntitysShares")),
    "dividends_paid": L("Dividends paid", "CF", "duration",
                        (G, "PaymentsOfDividendsCommonStock"), (G, "PaymentsOfDividends"),
                        (I, "DividendsPaidClassifiedAsFinancingActivities"), (I, "DividendsPaid")),
    "cfi": L("Cash from investing", "CF", "duration",
             (G, "NetCashProvidedByUsedInInvestingActivities"),
             (G, "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations"),
             (I, "CashFlowsFromUsedInInvestingActivities")),
    "cff": L("Cash from financing", "CF", "duration",
             (G, "NetCashProvidedByUsedInFinancingActivities"),
             (G, "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations"),
             (I, "CashFlowsFromUsedInFinancingActivities")),
    "fx_effect_on_cash": L("FX effect on cash", "CF", "duration",
                           (G, "EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
                           (G, "EffectOfExchangeRateOnCashAndCashEquivalents"),
                           (I, "EffectOfExchangeRateChangesOnCashAndCashEquivalents")),
    "change_in_cash": L("Net change in cash", "CF", "duration",
                        (G, "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect"),
                        (G, "CashAndCashEquivalentsPeriodIncreaseDecrease"),
                        (I, "IncreaseDecreaseInCashAndCashEquivalents")),
    "change_in_cash_before_fx": L("Net change in cash before FX", "CF", "duration",
                                  (G, "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseExcludingExchangeRateEffect"),
                                  (I, "IncreaseDecreaseInCashAndCashEquivalentsBeforeEffectOfExchangeRateChanges")),
    "total_investments_ifrs": L("Investments (current + non-current)", "OT", "instant",
                                (I, "InvestmentsOtherThanInvestmentsAccountedForUsingEquityMethod")),
    "noncurrent_investments_ifrs": L("Non-current investments", "OT", "instant",
                                     (I, "NoncurrentInvestmentsOtherThanInvestmentsAccountedForUsingEquityMethod")),
    "cash_end_cf": L("Cash at end (cash flow basis)", "CF", "instant",
                     (G, "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
                     (G, "CashAndCashEquivalentsAtCarryingValue"), (I, "CashAndCashEquivalents")),
    # --- debt maturities (latest year only matters) --------------------------------------------
    "debt_due_y1": L("Debt due within 1 year", "OT", "instant",
                     (G, "LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths")),
    "debt_due_y2": L("Debt due in year 2", "OT", "instant", (G, "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo")),
    "debt_due_y3": L("Debt due in year 3", "OT", "instant", (G, "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearThree")),
    "debt_due_y4": L("Debt due in year 4", "OT", "instant", (G, "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFour")),
    "debt_due_y5": L("Debt due in year 5", "OT", "instant", (G, "LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFive")),
    "debt_due_after_y5": L("Debt due after year 5", "OT", "instant",
                           (G, "LongTermDebtMaturitiesRepaymentsOfPrincipalAfterYearFive")),
}

# Cover-page share count (dei) is read separately: it is dated at the filing date, not the period end.
DEI_SHARES = (D, "EntityCommonStockSharesOutstanding")

# Tags whose presence with a non-zero recent value indicates convertible debt.
CONVERTIBLE_TAGS = (
    (G, "ConvertibleDebtNoncurrent"), (G, "ConvertibleDebtCurrent"), (G, "ConvertibleNotesPayable"),
    (G, "ConvertibleNotesPayableCurrent"), (G, "ConvertibleSeniorNotesPayable"), (G, "ConvertibleDebt"),
    (G, "DebtInstrumentConvertibleConversionPrice1"), (G, "ProceedsFromConvertibleDebt"),
    (G, "IncrementalCommonSharesAttributableToConversionOfDebtSecurities"),
    (G, "ConvertibleNotesPayableCurrent"), (G, "ConvertibleLongTermNotesPayable"),
    (I, "IssueOfConvertibleInstruments"),
)
# companyfacts omits dimensional facts, so convertibles are often invisible here; the research desk
# confirms from the debt note (Phase 6).
