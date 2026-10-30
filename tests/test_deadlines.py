"""Synthetic deadline-radar checks; never read real Gmail in CI."""
from datetime import date
from backend.deadlines import deadline_hints,sort_items,notice_kind

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


def test_paypal_financing_ad_is_not_a_payment_deadline():
    subject="Enjoy special financing when you pay over time with the PayPal Credit Card"
    body="Apply today for a PayPal Credit account. Your next payment could start soon."
    assert hints(subject,body)==[]
    assert notice_kind(subject,body) is None

def test_amex_rewards_offer_is_not_a_membership_renewal():
    subject="Apply and earn 100,000 Membership Rewards points"
    body="Apply today. Your new membership rewards can be earned after signing up."
    assert hints(subject,body)==[]
    assert notice_kind(subject,body) is None

def test_costco_promotional_payment_processing_offer():
    subject="Switch to Elavon for payment processing and get up to $300 (Terms Apply)"
    body="Earn a bonus on your payment processor."
    assert hints(subject,body)==[]
    assert notice_kind(subject,body) is None

def test_amex_referral_is_not_subscription():
    subject="Card Member, make the most of Membership & refer a friend"
    assert hints(subject,"Start earning bonus points today.")==[]
    assert notice_kind(subject,"Start earning bonus points today.") is None

def test_real_undated_robinhood_trial_remains_reviewable():
    subject="Your free trial is ending"
    assert hints(subject,"Your trial is ending soon. Please review your plan.")==[]
    assert notice_kind(subject,"Your trial is ending soon.")=="trial"

def test_no_contextual_today_false_due():
    assert hints("Your upcoming payment","Apply today for a special card.")==[]

def test_real_billing_relative_date_is_valid_when_explicit():
    result=hints("Your bill is ready","Your payment is due tomorrow.")
    assert result and result[0]["type"]=="payment"
    assert result[0]["due_date"]=="2026-10-31"

def test_real_subscription_renewal_with_date():
    assert hints("Upcoming renewal","Your subscription renews on November 8, 2026.")[0]["due_date"]=="2026-11-08"

def test_genuine_bill_without_date_is_manual_review():
    assert notice_kind("Your statement is ready", "Your bill is available to view.")=="payment"

def test_receipt_excluded_from_undated():
    assert notice_kind("Payment received for your monthly bill", "Your payment was successful.") is None


def test_amazon_bundled_trial_offers_not_active_subscriptions():
    for service in ("Apple Fitness+", "Apple News+", "Apple Arcade"):
        subject = f"Your recent Amazon purchase includes an {service} trial"
        body = "Claim the trial to enjoy benefits. After activation the subscription renews automatically on November 20, 2026."
        assert notice_kind(subject, body) is None
        assert hints(subject, body) == []


def test_music_free_months_eligibility_is_not_an_active_subscription():
    subject = "Congratulations! You’re eligible for 4 months for $0 🎵"
    body = "Your music subscription will renew on November 20, 2026 if you choose to start your offer."
    assert notice_kind(subject, body) is None
    assert hints(subject, body) == []


def test_trial_offer_not_confused_with_genuine_ending_notice():
    assert notice_kind("Your free trial is ending", "Your trial will end soon.") == "trial"
    assert notice_kind("Claim your free trial", "After activation, it renews on November 20, 2026.") is None
    assert hints("Your free trial is ending", "Your free trial ends on November 3, 2026.")[0]["due_date"] == "2026-11-03"


def test_real_subscription_notice_still_detected():
    assert notice_kind("Your streaming subscription will renew", "Your plan renews soon.") == "subscription"
