import hb_fast_order_tasks as t


def test_group_orders_skips_cancelled_and_blank():
    items = [
        {"orderNumber": "1", "status": "Open", "totalPrice": {"amount": 100}},
        {"orderNumber": "1", "status": "Open", "totalPrice": 50.5},
        {"orderNumber": "2", "status": "Cancelled", "totalPrice": 10},
        {"orderNumber": "", "status": "Open"},
    ]
    grouped = t.group_orders(items)
    assert list(grouped) == ["1"]
    assert len(grouped["1"]) == 2


def test_order_total_handles_dict_number_and_bad_values():
    items = [{"totalPrice": {"amount": 100}}, {"totalPrice": 50.5}, {"totalPrice": "x"}, {}]
    assert t.order_total(items) == 150.5
