"""Synthetic deadline-radar checks; never read real Gmail in CI."""
from datetime import date
from backend.deadlines import deadline_hints,sort_items

TODAY=date(2026,10,30)
def hints(s,b=""):
    return deadline_hints(s,b,"Fri, 30 Oct 2026 12:00:00 +0000",TODAY)

def test_subscription_renewal():
    r=hints("Your music subscription renews","Your subscription renews on November 8, 2026.")
    assert len(r)==1 and r[0]["type"]=="subscription" and r[0]["due_date"]=="2026-11-08"

def test_payment_deadline():
    r=hints("Monthly invoice","Your payment is due by November 2, 2026.")
    assert r[0]["type"]=="payment" and r[0]["priority"]=="soon"

def test_trial_end():
    r=hints("Your free trial","Your free trial ends on November 3, 2026.")
    assert r[0]["type"]=="trial"

def test_ignore_receipt_and_promotions():
    assert hints("Payment received","Payment received on November 1, 2026.")==[]
    assert hints("Flash sale","Shop now, discount ends on November 3, 2026.")==[]

def test_no_date_no_alert():
    assert hints("Subscription renewal","Your membership will renew soon.")==[]

def test_old_expired_date_not_new_charge():
    assert hints("Membership","Your subscription expired on January 1, 2025.")==[]

def test_sort():
    rows=[{"due_date":"2026-11-05","subject":"B"},{"due_date":"2026-11-01","subject":"A"}]
    assert sort_items(rows)[0]["subject"]=="A"

def test_numeric_us_deadline():
    assert hints("Your invoice", "Payment due 11/08/2026.")[0]["due_date"]=="2026-11-08"

def test_adjacent_line_deadline():
    found=hints("Subscription renewal","Your subscription will renew.\nNovember 8, 2026")
    assert found and found[0]["due_date"]=="2026-11-08"
