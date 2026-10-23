"""Run with: python -m unittest discover tests"""
import unittest

from scraper.salary import extract_salary


def _result(text):
    s = extract_salary(text)
    return s["salary_min"], s["salary_max"], s["salary_period"]


class ExtractSalaryTest(unittest.TestCase):
    def assertSalary(self, text, expected):
        self.assertEqual(_result(text), expected, text)

    def test_formats_seen_in_scraped_postings(self):
        self.assertSalary("Pay Range\n\n$22.00 - $28.00 per hour", (22.0, 28.0, "hour"))  # REI
        self.assertSalary("Hiring Range: $66,000 to $74,000 USD Annual", (66000.0, 74000.0, "year"))  # Patagonia
        self.assertSalary("Job Compensation: $18.00/hr plus bonus potential", (18.0, 18.0, "hour"))  # Cotopaxi
        self.assertSalary("Job Compensation: $65-70k annually plus bonus potential", (65000.0, 70000.0, "year"))

    def test_units(self):
        self.assertSalary("$17.84/hr", (17.84, 17.84, "hour"))
        self.assertSalary("$20 an hour", (20.0, 20.0, "hour"))
        self.assertSalary("$18.00 hourly", (18.0, 18.0, "hour"))
        self.assertSalary("Salary Range: $95,000 - $115,000 USD per year", (95000.0, 115000.0, "year"))
        self.assertSalary("Job Salary: $95k-$115k", (95000.0, 115000.0, "year"))

    def test_second_amount_without_dollar_sign(self):
        self.assertSalary("Pay Range: $20 - 25 per hour", (20.0, 25.0, "hour"))
        self.assertSalary("Salary: $95,000 - 2 openings available", (95000.0, 95000.0, "year"))

    def test_label_and_period_hint(self):
        self.assertSalary("Hourly Rate: $21.00", (21.0, 21.0, "hour"))
        self.assertSalary("**Compensation:**\n$95,000", (95000.0, 95000.0, "year"))

    def test_non_pay_figures_are_skipped(self):
        self.assertSalary(
            "You will manage a retail profit center of $5-$30 million in sales volume!\n\n"
            "Pay Range\n\n$125,284.72 - $156,605.90 per year",
            (125284.72, 156605.90, "year"),
        )
        self.assertSalary("Sign-on bonus of $1,000 - $2,000.\n\nPay Range: $22.00 - $28.00 per hour", (22.0, 28.0, "hour"))
        self.assertSalary("We offer a $100/month phone stipend.\n\nSalary: $95,000", (95000.0, 95000.0, "year"))
        self.assertSalary("Earn $20-$25 per hour! Benefits: competitive pay, $1,000 401(k) match.", (20.0, 25.0, "hour"))
        self.assertSalary("Manage $5M in annual sales. Salary: $60,000", (60000.0, 60000.0, "year"))
        self.assertSalary("Pay: $20/hr M-F", (20.0, 20.0, "hour"))

    def test_no_salary(self):
        self.assertSalary("", (None, None, None))
        self.assertSalary("Manage a store doing $5-$30 million in annual sales.", (None, None, None))
        self.assertSalary("Gear typically costs $20-$50 at our shop.", (20.0, 50.0, None))


class KnownGapsTest(unittest.TestCase):
    """Formats not handled yet. Remove expectedFailure once fixed."""

    @unittest.expectedFailure
    def test_range_with_unit_on_each_amount(self):  # Epic Mountain Gear
        self.assertEqual(_result("Starting wage: $20.00/hr - $23.00/hr"), (20.0, 23.0, "hour"))

    @unittest.expectedFailure
    def test_second_amount_without_dollar_sign_or_unit(self):
        self.assertEqual(_result("Salary: $65,000 - 75,000"), (65000.0, 75000.0, "year"))

    @unittest.expectedFailure
    def test_pay_colon_label(self):
        self.assertEqual(_result("Pay: $22"), (22.0, 22.0, "hour"))

    @unittest.expectedFailure
    def test_period_word_before_label(self):
        self.assertEqual(_result("Annual Salary: $5,000 - $8,000"), (5000.0, 8000.0, "year"))

    @unittest.expectedFailure
    def test_unit_priced_perk_after_salary(self):
        self.assertEqual(
            _result("Salary: $120,000. We cover up to $100/month for your internet."),
            (120000.0, 120000.0, "year"),
        )


if __name__ == "__main__":
    unittest.main()
