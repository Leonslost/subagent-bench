#!/usr/bin/env python3
import argparse
import subprocess, pathlib, shutil

def write_files(root: pathlib.Path, files: dict[str, str]):
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content.lstrip("\n"), encoding="utf-8")

def git_init(root: pathlib.Path):
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "bench@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Bench"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial baseline"], cwd=root, check=True)

# =============================================================================
# CHALLENGE 3: c3-bugfix-py (7-file Python subscription billing bugfix)
# =============================================================================
C3_FILES = {
"subbill/__init__.py": """
from .models import Account, Coupon, CreditNote, Invoice, LineItem
from .dates import billing_date_for_cycle, billing_period
from .proration import allocate_amount, prorate_cents
from .coupons import CouponApplicationResult, apply_coupons
from .tax import calculate_tax_cents
from .billing import generate_invoice, apply_credit_note

__all__ = [
    "Account",
    "Coupon",
    "CreditNote",
    "Invoice",
    "LineItem",
    "billing_date_for_cycle",
    "billing_period",
    "allocate_amount",
    "prorate_cents",
    "CouponApplicationResult",
    "apply_coupons",
    "calculate_tax_cents",
    "generate_invoice",
    "apply_credit_note",
]
""",
"subbill/models.py": """
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class LineItem:
    description: str
    amount_cents: int


@dataclass
class Coupon:
    code: str
    currency: str = "USD"
    percent_off: Optional[int] = None   # 1..100
    amount_off: Optional[int] = None    # cents
    expires_at: Optional[date] = None
    max_redemptions: Optional[int] = None
    times_redeemed: int = 0


@dataclass
class CreditNote:
    id: str
    invoice_id: str
    amount_cents: int


@dataclass
class Invoice:
    id: str
    account_id: str
    invoice_date: date
    currency: str
    line_items: list[LineItem]
    subtotal_cents: int
    discount_cents: int
    applied_coupons: list[str]
    tax_cents: int
    total_cents: int
    credit_applied_cents: int
    amount_due_cents: int


@dataclass
class Account:
    id: str
    currency: str = "USD"
    credit_balance_cents: int = 0
    invoices: dict[str, Invoice] = field(default_factory=dict)
    credit_notes: dict[str, CreditNote] = field(default_factory=dict)
    _invoice_seq: int = 0

    def next_invoice_id(self) -> str:
        self._invoice_seq += 1
        return f"inv_{self.id}_{self._invoice_seq}"
""",
"subbill/dates.py": """
import calendar
from datetime import date


def _add_one_month(d: date) -> date:
    year = d.year + (1 if d.month == 12 else 0)
    month = 1 if d.month == 12 else d.month + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def billing_date_for_cycle(start_date: date, cycle_index: int) -> date:
    if cycle_index < 0:
        raise ValueError("cycle_index must be >= 0")
    cur = start_date
    for _ in range(cycle_index):
        cur = _add_one_month(cur)
    return cur


def billing_period(start_date: date, cycle_index: int) -> tuple[date, date]:
    return (
        billing_date_for_cycle(start_date, cycle_index),
        billing_date_for_cycle(start_date, cycle_index + 1),
    )
""",
"subbill/proration.py": """
from typing import Sequence


def prorate_cents(full_amount_cents: int, days_used: int, total_days: int) -> int:
    if total_days <= 0:
        raise ValueError("total_days must be > 0")
    return int(round(full_amount_cents * (days_used / total_days)))


def allocate_amount(total_cents: int, weights: Sequence[int]) -> list[int]:
    if not weights:
        return []
    total_weight = sum(weights)
    if total_weight <= 0 or any(w < 0 for w in weights):
        raise ValueError("weights must be non-negative and sum to > 0")
    return [int(total_cents * w / total_weight) for w in weights]
""",
"subbill/coupons.py": """
from dataclasses import dataclass
from datetime import date
from typing import Sequence
from .models import Coupon


@dataclass
class CouponApplicationResult:
    discount_cents: int
    net_subtotal_cents: int
    applied_codes: list[str]


def apply_coupons(
    subtotal_cents: int,
    coupons: Sequence[Coupon],
    invoice_date: date,
    currency: str,
    *,
    preview: bool = False,
) -> CouponApplicationResult:
    discount = 0
    applied: list[str] = []

    for c in coupons:
        if c.currency != currency:
            continue
        if c.expires_at is not None and invoice_date > c.expires_at:
            continue
        if c.max_redemptions is not None and c.times_redeemed >= c.max_redemptions:
            continue

        if c.percent_off is not None:
            d = int(subtotal_cents * c.percent_off / 100)
            discount += d
            applied.append(c.code)
            c.times_redeemed += 1
        elif c.amount_off is not None:
            discount += c.amount_off
            applied.append(c.code)
            c.times_redeemed += 1

    return CouponApplicationResult(
        discount_cents=discount,
        net_subtotal_cents=subtotal_cents - discount,
        applied_codes=applied,
    )
""",
"subbill/tax.py": """
def calculate_tax_cents(net_amount_cents: int, tax_rate_bps: int) -> int:
    if tax_rate_bps < 0:
        raise ValueError("tax_rate_bps must be >= 0")
    return int(round(net_amount_cents * tax_rate_bps / 10000))
""",
"subbill/billing.py": """
from datetime import date
from typing import Sequence
from .models import Account, Coupon, CreditNote, Invoice, LineItem
from .coupons import apply_coupons
from .tax import calculate_tax_cents


def generate_invoice(
    account: Account,
    line_items: Sequence[LineItem],
    coupons: Sequence[Coupon],
    invoice_date: date,
    tax_rate_bps: int = 0,
    *,
    preview: bool = False,
) -> Invoice:
    items = list(line_items)
    subtotal = sum(item.amount_cents for item in items)
    tax = calculate_tax_cents(subtotal, tax_rate_bps)
    coupon_res = apply_coupons(
        subtotal,
        coupons,
        invoice_date,
        account.currency,
        preview=preview,
    )
    total = subtotal - coupon_res.discount_cents + tax

    credit_applied = min(account.credit_balance_cents, max(0, total))
    amount_due = total - credit_applied
    if not preview:
        account.credit_balance_cents -= credit_applied

    inv_id = f"preview_{account.id}" if preview else account.next_invoice_id()
    inv = Invoice(
        id=inv_id,
        account_id=account.id,
        invoice_date=invoice_date,
        currency=account.currency,
        line_items=items,
        subtotal_cents=subtotal,
        discount_cents=coupon_res.discount_cents,
        applied_coupons=coupon_res.applied_codes,
        tax_cents=tax,
        total_cents=total,
        credit_applied_cents=credit_applied,
        amount_due_cents=amount_due,
    )
    if not preview:
        account.invoices[inv.id] = inv
    return inv


def apply_credit_note(
    account: Account,
    invoice: Invoice,
    credit_id: str,
    amount_cents: int,
) -> CreditNote:
    if amount_cents <= 0:
        raise ValueError("amount_cents must be > 0")
    cn = CreditNote(id=credit_id, invoice_id=invoice.id, amount_cents=amount_cents)
    account.credit_notes[credit_id] = cn
    invoice.amount_due_cents = max(0, invoice.amount_due_cents - amount_cents)
    account.credit_balance_cents += amount_cents
    return cn
""",
"tests/test_billing.py": """
import unittest
from datetime import date
from subbill import (
    Account,
    Coupon,
    LineItem,
    allocate_amount,
    billing_date_for_cycle,
    generate_invoice,
    prorate_cents,
)


class TestBillingBaseline(unittest.TestCase):
    def test_mid_month_cycles(self):
        start = date(2025, 1, 15)
        self.assertEqual(billing_date_for_cycle(start, 0), date(2025, 1, 15))
        self.assertEqual(billing_date_for_cycle(start, 1), date(2025, 2, 15))
        self.assertEqual(billing_date_for_cycle(start, 2), date(2025, 3, 15))

    def test_even_allocation(self):
        self.assertEqual(allocate_amount(1000, [1, 1]), [500, 500])

    def test_simple_proration(self):
        self.assertEqual(prorate_cents(3000, 15, 30), 1500)

    def test_simple_invoice_no_coupon(self):
        acc = Account(id="a1")
        inv = generate_invoice(
            acc,
            [LineItem("Pro Plan", 2000)],
            [],
            date(2025, 3, 1),
            tax_rate_bps=1000,
        )
        self.assertEqual(inv.subtotal_cents, 2000)
        self.assertEqual(inv.tax_cents, 200)
        self.assertEqual(inv.total_cents, 2200)
        self.assertEqual(inv.amount_due_cents, 2200)


if __name__ == "__main__":
    unittest.main()
"""
}

C3_GRADING = {
"test_hidden_grading.py": """
import unittest
from datetime import date
from subbill import (
    Account,
    Coupon,
    LineItem,
    allocate_amount,
    apply_coupons,
    apply_credit_note,
    billing_date_for_cycle,
    billing_period,
    calculate_tax_cents,
    generate_invoice,
    prorate_cents,
)


class TestC3HiddenGrading(unittest.TestCase):
    # --- Bug 1: Month-end anchor dates ---
    def test_01_jan31_anchor_preserved_across_months_and_years(self):
        start = date(2025, 1, 31)
        self.assertEqual(billing_date_for_cycle(start, 0), date(2025, 1, 31))
        self.assertEqual(billing_date_for_cycle(start, 1), date(2025, 2, 28))
        self.assertEqual(billing_date_for_cycle(start, 2), date(2025, 3, 31))
        self.assertEqual(billing_date_for_cycle(start, 3), date(2025, 4, 30))
        self.assertEqual(billing_date_for_cycle(start, 4), date(2025, 5, 31))
        self.assertEqual(billing_date_for_cycle(start, 12), date(2026, 1, 31))
        self.assertEqual(billing_date_for_cycle(start, 37), date(2028, 2, 29))  # leap year!
        self.assertEqual(billing_date_for_cycle(start, 38), date(2028, 3, 31))

    def test_02_leap_day_anchor(self):
        start = date(2024, 2, 29)
        self.assertEqual(billing_date_for_cycle(start, 1), date(2024, 3, 29))
        self.assertEqual(billing_date_for_cycle(start, 12), date(2025, 2, 28))
        self.assertEqual(billing_date_for_cycle(start, 48), date(2028, 2, 29))

    def test_03_billing_period_pair(self):
        s, e = billing_period(date(2025, 1, 31), 1)
        self.assertEqual((s, e), (date(2025, 2, 28), date(2025, 3, 31)))

    # --- Bug 2: Cent conservation, Hamilton largest-remainder, half-up rounding, post-discount tax ---
    def test_04_allocate_amount_conserves_cents_and_largest_remainder(self):
        # 100 split 1:1:1 -> 33.333 each -> tie broken by lowest index: [34, 33, 33]
        self.assertEqual(allocate_amount(100, [1, 1, 1]), [34, 33, 33])
        # 100 split [1, 2, 5]: exact 12.5, 25.0, 62.5 -> remainders 0.5, 0.0, 0.5 -> lowest idx 0 gets +1 -> [13, 25, 62]
        self.assertEqual(allocate_amount(100, [1, 2, 5]), [13, 25, 62])
        # Non-equal remainders: 10 split [1, 3, 2] -> 1.666, 5.0, 3.333 -> idx 0 has 0.666 > idx 2 0.333 -> [2, 5, 3]
        self.assertEqual(allocate_amount(10, [1, 3, 2]), [2, 5, 3])
        # 10 split [2, 1, 3] -> 3.333, 1.666, 5.0 -> idx 1 has largest remainder -> [3, 2, 5]
        self.assertEqual(allocate_amount(10, [2, 1, 3]), [3, 2, 5])

    def test_05_allocate_amount_negative_and_zero_weights(self):
        self.assertEqual(allocate_amount(-100, [1, 1, 1]), [-34, -33, -33])
        self.assertEqual(allocate_amount(-10, [2, 1, 3]), [-3, -2, -5])
        self.assertEqual(allocate_amount(100, [0, 1, 1]), [0, 50, 50])
        self.assertEqual(allocate_amount(0, [1, 2, 3]), [0, 0, 0])
        self.assertEqual(allocate_amount(100, []), [])

    def test_06_prorate_cents_half_up_exact(self):
        # 5 * 1 / 2 = 2.5 -> half-up = 3 (Python round(2.5) would give 2!)
        self.assertEqual(prorate_cents(5, 1, 2), 3)
        self.assertEqual(prorate_cents(1, 1, 2), 1)
        self.assertEqual(prorate_cents(-5, 1, 2), -3)
        self.assertEqual(prorate_cents(1000, 1, 3), 333)
        self.assertEqual(prorate_cents(1000, 2, 3), 667)

    def test_07_calculate_tax_cents_half_up_and_non_negative(self):
        # 50 * 500 / 10000 = 2.5 -> half-up = 3 (Python round gives 2!)
        self.assertEqual(calculate_tax_cents(50, 500), 3)
        # 100 * 825 / 10000 = 8.25 -> 8
        self.assertEqual(calculate_tax_cents(100, 825), 8)
        # Negative net amount -> 0 tax
        self.assertEqual(calculate_tax_cents(-500, 1000), 0)
        self.assertEqual(calculate_tax_cents(0, 1000), 0)

    def test_08_tax_applied_after_discounts(self):
        acc = Account(id="t1")
        coupons = [Coupon(code="HALF", percent_off=50)]
        inv = generate_invoice(
            acc,
            [LineItem("Plan", 2000)],
            coupons,
            date(2025, 5, 1),
            tax_rate_bps=1000,  # 10%
        )
        # Subtotal 2000, discount 1000 -> post-discount 1000 -> 10% tax = 100 -> total 1100
        self.assertEqual(inv.discount_cents, 1000)
        self.assertEqual(inv.tax_cents, 100)
        self.assertEqual(inv.total_cents, 1100)
        self.assertEqual(inv.amount_due_cents, 1100)

    # --- Bug 3: Coupon stacking order, compounding, cap, non-mutation, preview ---
    def test_09_coupon_stacking_order_and_compounding(self):
        # Input list intentionally unsorted and mixed
        c_amt_b = Coupon(code="B_FLAT", amount_off=300)
        c_amt_a = Coupon(code="A_FLAT", amount_off=200)
        c_pct_10 = Coupon(code="P10", percent_off=10)
        c_pct_20 = Coupon(code="P20", percent_off=20)
        original_list = [c_amt_b, c_pct_10, c_amt_a, c_pct_20]
        snapshot_ids = [c.code for c in original_list]

        res = apply_coupons(1000, original_list, date(2025, 5, 1), "USD")
        # Order: P20 (20% of 1000 = 200 -> rem 800), P10 (10% of 800 = 80 -> rem 720),
        # A_FLAT (200 -> rem 520), B_FLAT (300 -> rem 220). Total discount = 780.
        self.assertEqual(res.applied_codes, ["P20", "P10", "A_FLAT", "B_FLAT"])
        self.assertEqual(res.discount_cents, 780)
        self.assertEqual(res.net_subtotal_cents, 220)
        # Input list order MUST NOT be mutated!
        self.assertEqual([c.code for c in original_list], snapshot_ids)

    def test_10_coupon_tie_break_and_cap_no_over_redemption(self):
        c1 = Coupon(code="B_AMT", amount_off=500)
        c2 = Coupon(code="A_AMT", amount_off=1200)
        c3 = Coupon(code="C_AMT", amount_off=100)
        res = apply_coupons(1000, [c1, c2, c3], date(2025, 5, 1), "USD")
        # A_AMT applied first -> deducts 1000 -> remaining is 0! B_AMT and C_AMT contribute 0 and must NOT be redeemed!
        self.assertEqual(res.discount_cents, 1000)
        self.assertEqual(res.net_subtotal_cents, 0)
        self.assertEqual(res.applied_codes, ["A_AMT"])
        self.assertEqual(c2.times_redeemed, 1)
        self.assertEqual(c1.times_redeemed, 0)
        self.assertEqual(c3.times_redeemed, 0)

    def test_11_coupon_preview_does_not_mutate_and_filters_currency_expiry_max(self):
        c_ok = Coupon(code="OK", percent_off=15, expires_at=date(2025, 5, 1), max_redemptions=1)
        c_exp = Coupon(code="EXP", percent_off=50, expires_at=date(2025, 4, 30))
        c_cur = Coupon(code="EUR", amount_off=500, currency="EUR")
        c_max = Coupon(code="MAXED", amount_off=500, max_redemptions=2, times_redeemed=2)

        acc = Account(id="p1", credit_balance_cents=300)
        prev = generate_invoice(
            acc,
            [LineItem("Plan", 1000)],
            [c_ok, c_exp, c_cur, c_max],
            date(2025, 5, 1),
            tax_rate_bps=1000,
            preview=True,
        )
        # Only c_ok applies: 15% of 1000 = 150 -> net 850 -> tax 85 -> total 935 -> credit 300 -> due 635
        self.assertEqual(prev.applied_coupons, ["OK"])
        self.assertEqual(prev.discount_cents, 150)
        self.assertEqual(prev.tax_cents, 85)
        self.assertEqual(prev.total_cents, 935)
        self.assertEqual(prev.credit_applied_cents, 300)
        self.assertEqual(prev.amount_due_cents, 635)
        # Preview MUST NOT mutate anything on coupons or account!
        self.assertEqual(c_ok.times_redeemed, 0)
        self.assertEqual(acc.credit_balance_cents, 300)
        self.assertEqual(len(acc.invoices), 0)

    def test_12_coupon_percent_half_up_rounding(self):
        # 25 * 10% = 2.5 -> half-up = 3
        c = Coupon(code="TEN", percent_off=10)
        res = apply_coupons(25, [c], date(2025, 1, 1), "USD")
        self.assertEqual(res.discount_cents, 3)
        self.assertEqual(res.net_subtotal_cents, 22)

    # --- Bug 4: Negative invoice rollover & idempotent credit notes ---
    def test_13_mid_cycle_downgrade_negative_total_rolls_over_to_credit_balance(self):
        acc = Account(id="d1", credit_balance_cents=100)
        c = Coupon(code="C10", percent_off=10)
        # Unused old plan credit -3000, new plan +1200 => subtotal -1800
        inv1 = generate_invoice(
            acc,
            [LineItem("Unused Enterprise", -3000), LineItem("Starter Prorated", 1200)],
            [c],
            date(2025, 5, 15),
            tax_rate_bps=1000,
        )
        # Negative subtotal => no coupons applied, 0 tax, total -1800, amount_due 0, credit_balance becomes 100 + 1800 = 1900
        self.assertEqual(inv1.applied_coupons, [])
        self.assertEqual(c.times_redeemed, 0)
        self.assertEqual(inv1.tax_cents, 0)
        self.assertEqual(inv1.total_cents, -1800)
        self.assertEqual(inv1.credit_applied_cents, 0)
        self.assertEqual(inv1.amount_due_cents, 0)
        self.assertEqual(acc.credit_balance_cents, 1900)

        # Next month invoice: 1200 + 10% tax = 1320 => uses 1320 of 1900 credit => due 0, remaining credit 580
        inv2 = generate_invoice(
            acc,
            [LineItem("Starter", 1200)],
            [],
            date(2025, 6, 1),
            tax_rate_bps=1000,
        )
        self.assertEqual(inv2.total_cents, 1320)
        self.assertEqual(inv2.credit_applied_cents, 1320)
        self.assertEqual(inv2.amount_due_cents, 0)
        self.assertEqual(acc.credit_balance_cents, 580)

        # Month 3 invoice: 1200 + 10% tax = 1320 => uses remaining 580 => due 740, credit 0
        inv3 = generate_invoice(
            acc,
            [LineItem("Starter", 1200)],
            [],
            date(2025, 7, 1),
            tax_rate_bps=1000,
        )
        self.assertEqual(inv3.credit_applied_cents, 580)
        self.assertEqual(inv3.amount_due_cents, 740)
        self.assertEqual(acc.credit_balance_cents, 0)

    def test_14_credit_note_idempotency_and_due_vs_balance_split(self):
        acc = Account(id="cn1")
        inv = generate_invoice(acc, [LineItem("Plan", 1000)], [], date(2025, 5, 1))
        self.assertEqual(inv.amount_due_cents, 1000)

        # Apply partial credit of 400 -> reduces amount_due to 600, does NOT also add 400 to credit_balance!
        cn1 = apply_credit_note(acc, inv, "cred-1", 400)
        self.assertEqual(inv.amount_due_cents, 600)
        self.assertEqual(acc.credit_balance_cents, 0)

        # Idempotent retry of cred-1 MUST NOT double-credit!
        cn1_retry = apply_credit_note(acc, inv, "cred-1", 400)
        self.assertEqual(cn1_retry.id, cn1.id)
        self.assertEqual(inv.amount_due_cents, 600)
        self.assertEqual(acc.credit_balance_cents, 0)

        # Simulate customer paid the remaining 600 (amount_due -> 0), then gets a 500 refund credit note
        inv.amount_due_cents = 0
        apply_credit_note(acc, inv, "cred-2", 500)
        self.assertEqual(inv.amount_due_cents, 0)
        self.assertEqual(acc.credit_balance_cents, 500)  # overflow goes to credit balance

        # Retry cred-2 -> still 500
        apply_credit_note(acc, inv, "cred-2", 500)
        self.assertEqual(acc.credit_balance_cents, 500)

        # Trying to credit another 200 (400 + 500 + 200 = 1100 > total 1000) MUST raise ValueError
        with self.assertRaises(ValueError):
            apply_credit_note(acc, inv, "cred-3", 200)

        # Exact remaining 100 succeeds
        apply_credit_note(acc, inv, "cred-4", 100)
        self.assertEqual(acc.credit_balance_cents, 600)

    def test_15_credit_note_mixed_due_and_overflow(self):
        acc = Account(id="cn2")
        inv = generate_invoice(acc, [LineItem("Plan", 1000)], [], date(2025, 5, 1))
        inv.amount_due_cents = 300  # 700 already paid
        apply_credit_note(acc, inv, "cred-mix", 500)
        # 300 reduces amount_due to 0, 200 overflows into credit_balance_cents
        self.assertEqual(inv.amount_due_cents, 0)
        self.assertEqual(acc.credit_balance_cents, 200)

    def test_16_preview_negative_invoice_does_not_mutate_credit_balance(self):
        acc = Account(id="pvneg", credit_balance_cents=50)
        prev = generate_invoice(
            acc,
            [LineItem("Credit", -500)],
            [],
            date(2025, 5, 1),
            preview=True,
        )
        self.assertEqual(prev.amount_due_cents, 0)
        self.assertEqual(acc.credit_balance_cents, 50)
        self.assertEqual(len(acc.invoices), 0)


if __name__ == "__main__":
    unittest.main()
"""
}

# =============================================================================
# CHALLENGE 4: c4-concurrent-go (6-file Go concurrent DAG task runner + -race)
# =============================================================================
C4_FILES = {
"go.mod": """
module dagrun

go 1.22
""",
"types.go": """
package dagrun

import (
	"context"
	"errors"
	"time"
)

var (
	ErrEmptyTaskID       = errors.New("dagrun: empty task id")
	ErrDuplicateTask     = errors.New("dagrun: duplicate task id")
	ErrMissingDependency = errors.New("dagrun: missing dependency")
	ErrCycleDetected     = errors.New("dagrun: cycle detected")
)

type TaskStatus string

const (
	StatusSucceeded TaskStatus = "succeeded"
	StatusFailed    TaskStatus = "failed"
	StatusSkipped   TaskStatus = "skipped"
	StatusCancelled TaskStatus = "cancelled"
)

type TaskFunc func(ctx context.Context) (any, error)

type Task struct {
	ID         string
	Deps       []string
	Fn         TaskFunc
	Timeout    time.Duration
	MaxRetries int
	RetryDelay time.Duration
}

type Options struct {
	MaxConcurrency int
	FailFast       bool
	Sink           EventSink
}

type TaskResult struct {
	ID       string
	Status   TaskStatus
	Attempts int
	Output   any
	Err      error
	Duration time.Duration
}

type RunResult struct {
	Tasks map[string]*TaskResult
}
""",
"events.go": """
package dagrun

import "time"

type EventType string

const (
	EventStarted   EventType = "started"
	EventRetrying  EventType = "retrying"
	EventSucceeded EventType = "succeeded"
	EventFailed    EventType = "failed"
	EventSkipped   EventType = "skipped"
	EventCancelled EventType = "cancelled"
)

type Event struct {
	TaskID  string
	Type    EventType
	Attempt int
	Err     error
	At      time.Time
}

type EventSink interface {
	Emit(Event)
}

// RecordingSink intentionally has NO internal mutex; Runner must serialize Emit calls.
type RecordingSink struct {
	Events []Event
}

func (s *RecordingSink) Emit(e Event) {
	s.Events = append(s.Events, e)
}
""",
"graph.go": """
package dagrun

// Validate checks that tasks form a valid DAG:
// - no empty task IDs (ErrEmptyTaskID)
// - no duplicate task IDs (ErrDuplicateTask)
// - all dependencies exist (ErrMissingDependency)
// - no self-dependencies or cycles (ErrCycleDetected)
func Validate(tasks []Task) error {
	seen := make(map[string]struct{}, len(tasks))
	for _, t := range tasks {
		if t.ID == "" {
			return ErrEmptyTaskID
		}
		if _, exists := seen[t.ID]; exists {
			return ErrDuplicateTask
		}
		seen[t.ID] = struct{}{}
	}
	return nil
}
""",
"runner.go": """
package dagrun

import (
	"context"
	"time"
)

// Run executes tasks respecting their DAG dependencies and Options.
// Current implementation is a placeholder sequential stub.
func Run(ctx context.Context, tasks []Task, opts Options) (*RunResult, error) {
	if err := Validate(tasks); err != nil {
		return nil, err
	}

	res := &RunResult{
		Tasks: make(map[string]*TaskResult, len(tasks)),
	}
	for _, t := range tasks {
		start := time.Now()
		if opts.Sink != nil {
			opts.Sink.Emit(Event{TaskID: t.ID, Type: EventStarted, Attempt: 1, At: start})
		}
		out, err := t.Fn(ctx)
		dur := time.Since(start)
		if err != nil {
			res.Tasks[t.ID] = &TaskResult{
				ID:       t.ID,
				Status:   StatusFailed,
				Attempts: 1,
				Err:      err,
				Duration: dur,
			}
			if opts.Sink != nil {
				opts.Sink.Emit(Event{TaskID: t.ID, Type: EventFailed, Attempt: 1, Err: err, At: time.Now()})
			}
			return res, err
		}
		res.Tasks[t.ID] = &TaskResult{
			ID:       t.ID,
			Status:   StatusSucceeded,
			Attempts: 1,
			Output:   out,
			Duration: dur,
		}
		if opts.Sink != nil {
			opts.Sink.Emit(Event{TaskID: t.ID, Type: EventSucceeded, Attempt: 1, At: time.Now()})
		}
	}
	return res, nil
}
""",
"runner_test.go": """
package dagrun

import (
	"context"
	"errors"
	"testing"
)

func TestRunSimpleChain(t *testing.T) {
	var order []string
	tasks := []Task{
		{
			ID: "a",
			Fn: func(ctx context.Context) (any, error) {
				order = append(order, "a")
				return 1, nil
			},
		},
		{
			ID:   "b",
			Deps: []string{"a"},
			Fn: func(ctx context.Context) (any, error) {
				order = append(order, "b")
				return 2, nil
			},
		},
	}

	res, err := Run(context.Background(), tasks, Options{MaxConcurrency: 2})
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if res.Tasks["a"].Status != StatusSucceeded || res.Tasks["b"].Status != StatusSucceeded {
		t.Fatalf("expected both succeeded: %+v", res.Tasks)
	}
	if len(order) != 2 || order[0] != "a" || order[1] != "b" {
		t.Fatalf("wrong order: %v", order)
	}
}

func TestValidateDuplicate(t *testing.T) {
	err := Validate([]Task{
		{ID: "a", Fn: func(ctx context.Context) (any, error) { return nil, nil }},
		{ID: "a", Fn: func(ctx context.Context) (any, error) { return nil, nil }},
	})
	if !errors.Is(err, ErrDuplicateTask) {
		t.Fatalf("expected ErrDuplicateTask, got %v", err)
	}
}
"""
}

C4_GRADING = {
"hidden_grading_test.go": """
package dagrun

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func noopFn(ctx context.Context) (any, error) { return "ok", nil }

func TestHidden01_ValidateGraphErrors(t *testing.T) {
	// Empty ID
	if err := Validate([]Task{{ID: "", Fn: noopFn}}); !errors.Is(err, ErrEmptyTaskID) {
		t.Fatalf("expected ErrEmptyTaskID, got %v", err)
	}
	// Duplicate ID
	if err := Validate([]Task{{ID: "a", Fn: noopFn}, {ID: "a", Fn: noopFn}}); !errors.Is(err, ErrDuplicateTask) {
		t.Fatalf("expected ErrDuplicateTask, got %v", err)
	}
	// Missing dependency
	if err := Validate([]Task{{ID: "a", Deps: []string{"ghost"}, Fn: noopFn}}); !errors.Is(err, ErrMissingDependency) {
		t.Fatalf("expected ErrMissingDependency, got %v", err)
	}
	// Self cycle
	if err := Validate([]Task{{ID: "a", Deps: []string{"a"}, Fn: noopFn}}); !errors.Is(err, ErrCycleDetected) {
		t.Fatalf("expected ErrCycleDetected for self loop, got %v", err)
	}
	// 3-node cycle with unrelated valid branch
	cycleTasks := []Task{
		{ID: "root", Fn: noopFn},
		{ID: "a", Deps: []string{"c", "root"}, Fn: noopFn},
		{ID: "b", Deps: []string{"a"}, Fn: noopFn},
		{ID: "c", Deps: []string{"b"}, Fn: noopFn},
	}
	if err := Validate(cycleTasks); !errors.Is(err, ErrCycleDetected) {
		t.Fatalf("expected ErrCycleDetected for 3-node cycle, got %v", err)
	}
	// Run must not execute any task if Validate fails
	ran := atomic.Bool{}
	cycleTasks[0].Fn = func(ctx context.Context) (any, error) {
		ran.Store(true)
		return nil, nil
	}
	if _, err := Run(context.Background(), cycleTasks, Options{}); !errors.Is(err, ErrCycleDetected) {
		t.Fatalf("Run should fail validation: %v", err)
	}
	if ran.Load() {
		t.Fatal("root task should not have run when graph is invalid")
	}
}

func TestHidden02_EmptyTasks(t *testing.T) {
	res, err := Run(context.Background(), nil, Options{MaxConcurrency: 2})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if res == nil || len(res.Tasks) != 0 {
		t.Fatalf("expected empty result map, got %+v", res)
	}
}

func TestHidden03_ReverseOrderDiamondAndConcurrency(t *testing.T) {
	// Deliberately pass tasks in reverse topological order!
	var active atomic.Int32
	var maxActive atomic.Int32
	var mu sync.Mutex
	completed := map[string]bool{}

	record := func(id string, sleep time.Duration, reqDeps ...string) TaskFunc {
		return func(ctx context.Context) (any, error) {
			mu.Lock()
			for _, d := range reqDeps {
				if !completed[d] {
					mu.Unlock()
					return nil, fmt.Errorf("task %s started before dep %s completed", id, d)
				}
			}
			mu.Unlock()

			cur := active.Add(1)
			for {
				prev := maxActive.Load()
				if cur <= prev || maxActive.CompareAndSwap(prev, cur) {
					break
				}
			}
			time.Sleep(sleep)
			active.Add(-1)

			mu.Lock()
			completed[id] = true
			mu.Unlock()
			return id + "_out", nil
		}
	}

	tasks := []Task{
		{ID: "join", Deps: []string{"b1", "b2", "b3"}, Fn: record("join", 10*time.Millisecond, "b1", "b2", "b3")},
		{ID: "b3", Deps: []string{"root"}, Fn: record("b3", 40*time.Millisecond, "root")},
		{ID: "b2", Deps: []string{"root"}, Fn: record("b2", 40*time.Millisecond, "root")},
		{ID: "b1", Deps: []string{"root"}, Fn: record("b1", 40*time.Millisecond, "root")},
		{ID: "root", Fn: record("root", 10*time.Millisecond)},
	}

	sink := &RecordingSink{}
	res, err := Run(context.Background(), tasks, Options{MaxConcurrency: 2, Sink: sink})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if maxActive.Load() != 2 {
		t.Fatalf("expected max concurrency to reach exactly 2 (not >2, not sequential), got %d", maxActive.Load())
	}
	for _, id := range []string{"root", "b1", "b2", "b3", "join"} {
		tr := res.Tasks[id]
		if tr == nil || tr.Status != StatusSucceeded || tr.Output != id+"_out" {
			t.Fatalf("bad task result for %s: %+v", id, tr)
		}
	}
	if len(sink.Events) != 10 {
		t.Fatalf("expected 10 events (5 started + 5 succeeded), got %d", len(sink.Events))
	}
}

func TestHidden04_DuplicateDepInSliceHandledCleanly(t *testing.T) {
	tasks := []Task{
		{ID: "a", Fn: noopFn},
		{ID: "b", Deps: []string{"a", "a"}, Fn: noopFn},
	}
	res, err := Run(context.Background(), tasks, Options{MaxConcurrency: 2})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if res.Tasks["b"].Status != StatusSucceeded {
		t.Fatalf("expected b succeeded, got %+v", res.Tasks["b"])
	}
}

func TestHidden05_PerTaskTimeoutAndRetrySuccess(t *testing.T) {
	var attempts atomic.Int32
	sink := &RecordingSink{}
	tasks := []Task{
		{
			ID:         "flaky",
			Timeout:    35 * time.Millisecond,
			MaxRetries: 2,
			RetryDelay: 10 * time.Millisecond,
			Fn: func(ctx context.Context) (any, error) {
				n := attempts.Add(1)
				if n == 1 {
					// Hang until per-attempt timeout
					<-ctx.Done()
					return nil, ctx.Err()
				}
				if n == 2 {
					return nil, errors.New("transient err")
				}
				return "finally", nil
			},
		},
	}

	res, err := Run(context.Background(), tasks, Options{MaxConcurrency: 1, Sink: sink})
	if err != nil {
		t.Fatalf("expected retry success, got err: %v", err)
	}
	tr := res.Tasks["flaky"]
	if tr.Status != StatusSucceeded || tr.Attempts != 3 || tr.Output != "finally" {
		t.Fatalf("unexpected task result: %+v", tr)
	}
	// Verify events: started(1), retrying(1), started(2), retrying(2), started(3), succeeded(3)
	var types []EventType
	for _, e := range sink.Events {
		types = append(types, e.Type)
	}
	want := []EventType{EventStarted, EventRetrying, EventStarted, EventRetrying, EventStarted, EventSucceeded}
	if len(types) != len(want) {
		t.Fatalf("wrong events: got %v, want %v", types, want)
	}
	for i := range want {
		if types[i] != want[i] {
			t.Fatalf("event[%d] = %s, want %s (all: %v)", i, types[i], want[i], types)
		}
	}
}

func TestHidden06_RetryBackoffReleasesConcurrencySlot(t *testing.T) {
	// MaxConcurrency = 2:
	//   start -> retryingA (fails immediately, 220ms RetryDelay) & gate (25ms)
	//   gate  -> B (50ms) & C (50ms)
	// If retryingA releases its concurrency slot while sleeping in RetryDelay,
	// B and C MUST run concurrently (bcMax == 2)!
	var bcActive atomic.Int32
	var bcMax atomic.Int32
	bcFn := func(ctx context.Context) (any, error) {
		cur := bcActive.Add(1)
		for {
			prev := bcMax.Load()
			if cur <= prev || bcMax.CompareAndSwap(prev, cur) {
				break
			}
		}
		time.Sleep(50 * time.Millisecond)
		bcActive.Add(-1)
		return "ok", nil
	}

	var aTries atomic.Int32
	detTasks := []Task{
		{ID: "start", Fn: noopFn},
		{
			ID:         "retryingA",
			Deps:       []string{"start"},
			MaxRetries: 1,
			RetryDelay: 220 * time.Millisecond,
			Fn: func(ctx context.Context) (any, error) {
				if aTries.Add(1) == 1 {
					return nil, errors.New("backoff now")
				}
				return "recovered", nil
			},
		},
		{
			ID:   "gate",
			Deps: []string{"start"},
			Fn: func(ctx context.Context) (any, error) {
				time.Sleep(25 * time.Millisecond)
				return nil, nil
			},
		},
		{ID: "B", Deps: []string{"gate"}, Fn: bcFn},
		{ID: "C", Deps: []string{"gate"}, Fn: bcFn},
	}

	res, err := Run(context.Background(), detTasks, Options{MaxConcurrency: 2})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if res.Tasks["retryingA"].Status != StatusSucceeded || res.Tasks["retryingA"].Attempts != 2 {
		t.Fatalf("bad retryingA: %+v", res.Tasks["retryingA"])
	}
	if bcMax.Load() < 2 {
		t.Fatalf("expected B and C to run concurrently while retryingA was in RetryDelay (slot should be released), got maxConcurrent=%d", bcMax.Load())
	}
}

func TestHidden07_FailFastCancelsInFlightSkipsUnstartedNoGoroutineLeak(t *testing.T) {
	var inFlight atomic.Int32
	var slowSawCancel atomic.Bool
	var dependentRan atomic.Bool
	sink := &RecordingSink{}

	tasks := []Task{
		{
			ID: "failer",
			Fn: func(ctx context.Context) (any, error) {
				inFlight.Add(1)
				defer inFlight.Add(-1)
				time.Sleep(25 * time.Millisecond)
				return nil, errors.New("boom")
			},
		},
		{
			ID: "slow",
			Fn: func(ctx context.Context) (any, error) {
				inFlight.Add(1)
				defer inFlight.Add(-1)
				select {
				case <-ctx.Done():
					slowSawCancel.Store(true)
					time.Sleep(15 * time.Millisecond) // verify Run waits for goroutine exit!
					return nil, ctx.Err()
				case <-time.After(2 * time.Second):
					return "too_late", nil
				}
			},
		},
		{
			ID:   "downstream",
			Deps: []string{"slow"},
			Fn: func(ctx context.Context) (any, error) {
				dependentRan.Store(true)
				return nil, nil
			},
		},
	}

	start := time.Now()
	res, err := Run(context.Background(), tasks, Options{MaxConcurrency: 4, FailFast: true, Sink: sink})
	elapsed := time.Since(start)

	if err == nil {
		t.Fatal("expected non-nil error")
	}
	if elapsed > 500*time.Millisecond {
		t.Fatalf("FailFast took too long: %v", elapsed)
	}
	if !slowSawCancel.Load() {
		t.Fatal("slow task did not receive context cancellation")
	}
	if inFlight.Load() != 0 {
		t.Fatalf("Run returned while %d goroutines still in-flight (goroutine leak!)", inFlight.Load())
	}
	if dependentRan.Load() {
		t.Fatal("downstream task should not have run")
	}
	if res.Tasks["failer"].Status != StatusFailed {
		t.Fatalf("failer status = %s, want failed", res.Tasks["failer"].Status)
	}
	if res.Tasks["slow"].Status != StatusCancelled {
		t.Fatalf("slow status = %s, want cancelled", res.Tasks["slow"].Status)
	}
	if res.Tasks["downstream"].Status != StatusSkipped {
		t.Fatalf("downstream status = %s, want skipped", res.Tasks["downstream"].Status)
	}
}

func TestHidden08_ContinueOnErrorSkipsTransitiveDependentsRunsIndependent(t *testing.T) {
	var ran sync.Map
	mk := func(id string, fail bool) TaskFunc {
		return func(ctx context.Context) (any, error) {
			ran.Store(id, true)
			time.Sleep(10 * time.Millisecond)
			if fail {
				return nil, fmt.Errorf("fail_%s", id)
			}
			return id, nil
		}
	}

	// Graph:
	//   a (fails) -> b -> c -> d
	//   x (ok)    -> y (ok)
	//   z depends on [x, c] (must be skipped because c is skipped!)
	tasks := []Task{
		{ID: "a", Fn: mk("a", true)},
		{ID: "b", Deps: []string{"a"}, Fn: mk("b", false)},
		{ID: "c", Deps: []string{"b"}, Fn: mk("c", false)},
		{ID: "d", Deps: []string{"c"}, Fn: mk("d", false)},
		{ID: "x", Fn: mk("x", false)},
		{ID: "y", Deps: []string{"x"}, Fn: mk("y", false)},
		{ID: "z", Deps: []string{"x", "c"}, Fn: mk("z", false)},
	}

	sink := &RecordingSink{}
	res, err := Run(context.Background(), tasks, Options{MaxConcurrency: 4, FailFast: false, Sink: sink})
	if err == nil {
		t.Fatal("expected non-nil error because task a failed")
	}

	wantStatus := map[string]TaskStatus{
		"a": StatusFailed,
		"b": StatusSkipped,
		"c": StatusSkipped,
		"d": StatusSkipped,
		"x": StatusSucceeded,
		"y": StatusSucceeded,
		"z": StatusSkipped,
	}
	for id, want := range wantStatus {
		tr := res.Tasks[id]
		if tr == nil {
			t.Fatalf("missing task %s in RunResult", id)
		}
		if tr.Status != want {
			t.Fatalf("task %s status = %s, want %s", id, tr.Status, want)
		}
	}
	for _, skippedID := range []string{"b", "c", "d", "z"} {
		if _, ok := ran.Load(skippedID); ok {
			t.Fatalf("skipped task %s should never have executed", skippedID)
		}
	}
}

func TestHidden09_ParentCancelAbortsRetryDelayImmediately(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	var attempts atomic.Int32
	tasks := []Task{
		{
			ID:         "retrySlow",
			MaxRetries: 5,
			RetryDelay: 3 * time.Second,
			Fn: func(ctx context.Context) (any, error) {
				attempts.Add(1)
				return nil, errors.New("always fails")
			},
		},
	}

	go func() {
		time.Sleep(40 * time.Millisecond)
		cancel()
	}()

	start := time.Now()
	res, err := Run(ctx, tasks, Options{MaxConcurrency: 1})
	elapsed := time.Since(start)

	if err == nil {
		t.Fatal("expected error on parent cancel")
	}
	if elapsed > 400*time.Millisecond {
		t.Fatalf("Run waited during retry backoff instead of cancelling immediately: %v", elapsed)
	}
	if attempts.Load() != 1 {
		t.Fatalf("should not retry after parent cancel, attempts=%d", attempts.Load())
	}
	if res.Tasks["retrySlow"].Status != StatusCancelled {
		t.Fatalf("expected StatusCancelled, got %s", res.Tasks["retrySlow"].Status)
	}
}

func TestHidden10_HighConcurrencyRaceStressAndSerializedSink(t *testing.T) {
	// 30-task layered DAG with MaxConcurrency=8 + non-mutex RecordingSink under -race!
	var tasks []Task
	for layer := 0; layer < 5; layer++ {
		for j := 0; j < 6; j++ {
			id := fmt.Sprintf("L%d_%d", layer, j)
			var deps []string
			if layer > 0 {
				deps = []string{
					fmt.Sprintf("L%d_%d", layer-1, j),
					fmt.Sprintf("L%d_%d", layer-1, (j+1)%6),
				}
			}
			tasks = append(tasks, Task{
				ID:   id,
				Deps: deps,
				Fn: func(ctx context.Context) (any, error) {
					time.Sleep(2 * time.Millisecond)
					return id, nil
				},
			})
		}
	}
	sink := &RecordingSink{}
	res, err := Run(context.Background(), tasks, Options{MaxConcurrency: 8, Sink: sink})
	if err != nil {
		t.Fatalf("unexpected err: %v", err)
	}
	if len(res.Tasks) != 30 {
		t.Fatalf("expected 30 task results, got %d", len(res.Tasks))
	}
	for _, tr := range res.Tasks {
		if tr.Status != StatusSucceeded {
			t.Fatalf("task %s not succeeded: %+v", tr.ID, tr)
		}
	}
	if len(sink.Events) != 60 {
		t.Fatalf("expected 60 events, got %d", len(sink.Events))
	}
}
"""
}

def main():
    parser = argparse.ArgumentParser(description="Build C3 and C4 fixer-bench templates and grading suites")
    parser.add_argument("--work-dir", default="/tmp/opencode/fixer-bench", help="Benchmark work directory")
    args = parser.parse_args()
    base = pathlib.Path(args.work_dir)

    write_files(base / "templates" / "c3-bugfix-py", C3_FILES)
    git_init(base / "templates" / "c3-bugfix-py")
    write_files(base / "grading" / "c3-bugfix-py", C3_GRADING)

    write_files(base / "templates" / "c4-concurrent-go", C4_FILES)
    git_init(base / "templates" / "c4-concurrent-go")
    write_files(base / "grading" / "c4-concurrent-go", C4_GRADING)

    print("Built C3 and C4 successfully.")


if __name__ == "__main__":
    main()
