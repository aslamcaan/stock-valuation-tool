

def test_piotroski_counts_the_nine_tests():
    from types import SimpleNamespace
    from engine.forensic import piotroski

    data = {  # FY2024 -> FY2025: improving on every test
        "FY2023": {"total_assets": 1000},
        "FY2024": {"total_assets": 1000, "net_income": 50, "cfo": 60, "long_term_debt": 300, "current_assets": 200,
                   "current_liabilities": 200, "shares_diluted_weighted": 100, "gross_profit": 400, "revenue": 1000},
        "FY2025": {"total_assets": 1000, "net_income": 80, "cfo": 120, "long_term_debt": 250, "current_assets": 260,
                   "current_liabilities": 200, "shares_diluted_weighted": 98, "gross_profit": 460, "revenue": 1100},
    }

    class H:
        fy_labels = ["FY2023", "FY2024", "FY2025"]

        def get(self, line, p):
            x = data.get(p, {}).get(line)
            return None if x is None else SimpleNamespace(value=x, source="test", tag=line)

    s = piotroski(H(), "2080", "FY2025", "FY2024")
    assert s.value == 9 and s.reading.startswith("strong")
    data["FY2025"].update(net_income=-10, cfo=-5, shares_diluted_weighted=110)
    s = piotroski(H(), "2080", "FY2025", "FY2024")
    # fails: ROA positive, CFO positive, ROA up, no new shares; CFO (-5) is still above net income (-10)
    assert s.value == 5 and "No new shares" in s.notes[-1]
    assert piotroski(H(), "6021", "FY2025", "FY2024").value is None  # banks: not meaningful
