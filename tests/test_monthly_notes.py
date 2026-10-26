import monthly_reports


def _view(**over):
    v = {
        "period": "2026-09", "label": "Eylül 2026", "status": "taslak",
        "metrics": {"grossRevenue": 352742.68, "returnAmount": 22875.95, "netRevenue": 329866.73,
                    "netProfit": 70999.35, "fixedExpenses": 52801.89, "realNetProfit": 18197.46,
                    "orderCount": 147, "unitCount": 159, "avgBasket": 2399.61},
        "compare": {"prev": {"netProfit": {"value": 70999.35, "prev": 52276.0, "pct": 35.8},
                             "avgBasket": {"value": 2399.61, "prev": 2153.0, "pct": 11.5}}, "yoy": {}},
        "byMarketplace": {"trendyol": {"grossRevenue": 202865.33, "netProfit": 28223.31},
                          "hepsiburada": {"grossRevenue": 149877.35, "netProfit": 42739.64}},
        "dataQuality": {"ordersMissingCargo": 32, "linesEstimated": 6, "skusMissingCost": []},
        "topProfit": [{"productName": "Softhydra Filtre", "sku": "SFHY-3-GRS", "profit": 25189.0}],
        "lossMaking": [],
    }
    v.update(over)
    return v


def test_notes_cover_main_figures():
    text = "\n".join(monthly_reports.build_notes(_view()))
    assert "\u20ba70.999" in text
    assert "%35,8" in text and "arttı" in text
    assert "gerçek net kâr \u20ba18.197" in text
    assert "Trendyol %57,5" in text
    assert "SFHY-3-GRS" in text
    assert "Zarar eden ürün yok" in text
    assert "32 sipariş" in text
    assert "taslaktır" in text


def test_notes_report_loss_and_decrease():
    v = _view(status="kesin")
    v["metrics"]["realNetProfit"] = -2812.12
    v["compare"]["prev"]["netProfit"] = {"value": 70999.35, "prev": 90000.0, "pct": -21.1}
    v["lossMaking"] = [{"sku": "SH-X", "profit": -100.0}]
    text = "\n".join(monthly_reports.build_notes(v))
    assert "zararla kapandı" in text
    assert "azaldı" in text
    assert "1 ürün zarar etti" in text
    assert "taslaktır" not in text


def test_notes_empty_view_does_not_fail():
    assert monthly_reports.build_notes({}) == []
