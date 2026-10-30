"""Fictional reminder coverage; no live mailbox data."""
from datetime import date
from backend.reminders import reminder_hints
TODAY=date(2026,10,30)
DATE="Thu, 29 Oct 2026 13:00:00 -0400"
def scan(subject,body=""):
    return reminder_hints(subject,body,DATE,TODAY)

def test_lugless_undated_pickup():
    hints,kind=scan("Luggage pickup reminder: 830841167","Your trip is right around the corner. Don't forget your scheduled luggage pickup.")
    assert kind=="travel" and hints==[]

def test_lugless_tomorrow_pickup():
    h,k=scan("Luggage pickup reminder","Your luggage pickup is scheduled for tomorrow.")
    assert k=="travel" and h[0]["due_date"]=="2026-10-30"

def test_flight_checkin():
    h,k=scan("Flight check-in reminder","Your flight check-in opens on November 5, 2026.")
    assert k=="flight" and h[0]["due_date"]=="2026-11-05"

def test_appointment_reminder():
    h,k=scan("Appointment reminder","Your dentist appointment is scheduled for November 9, 2026.")
    assert k=="appointment" and h[0]["due_date"]=="2026-11-09"

def test_package_pickup():
    h,k=scan("Your package is ready for pickup","Collect your package by November 2, 2026.")
    assert k=="delivery" and h[0]["due_date"]=="2026-11-02"

def test_document_submission():
    h,k=scan("Document submission deadline","Please submit your application by November 8, 2026.")
    assert k=="document" and h[0]["due_date"]=="2026-11-08"

def test_ads_and_delivered_not_alerted():
    assert scan("Travel luggage clearance sale","Shop now for discounts.")==( [],None)
    assert scan("Delivered 2 items: Electronics","Delivered today.")==([],None)
    assert scan("Shipped 1 item: Costumes","Your order shipped today.")==([],None)


def test_completed_return_dropoff_not_a_reminder():
    from backend.reminders import reminder_status
    for title in ("Your return drop off confirmation",
                  "Your return drop-off confirmation",
                  "Drop off confirmed for your Amazon return"):
        assert reminder_status(title) == "completed"
        assert scan(title, "Your return was accepted on October 28, 2026.") == ([],None)

def test_failed_lugless_pickup_is_followup_not_upcoming():
    from backend.reminders import reminder_status
    title="Your luggage pickup was unsuccessful: 830841167"
    assert reminder_status(title) == "follow_up"
    hints,kind=scan(title, "Pickup attempt was unsuccessful. Contact support.")
    assert hints == [] and kind == "travel"

def test_normal_lugless_pickup_still_pending():
    from backend.reminders import reminder_status
    title="Luggage pickup reminder: 830841167"
    assert reminder_status(title) == "pending"
    assert scan(title, "Your trip is right around the corner.")[1] == "travel"
