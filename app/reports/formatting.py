"""Display helpers; unknown currency precision remains explicit minor units."""

from decimal import Decimal

PRECISION = {
    "BRL": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "CAD": 2,
    "AUD": 2,
    "CHF": 2,
    "CNY": 2,
    "ARS": 2,
    "MXN": 2,
    "JPY": 0,
    "KRW": 0,
    "CLP": 0,
    "KWD": 3,
    "BHD": 3,
    "OMR": 3,
}


def display_amount(amount: int, currency: str) -> str:
    precision = PRECISION.get(currency)
    if precision is None:
        return f"{amount} unidades mínimas"
    return f"{Decimal(amount) / Decimal(10**precision):.{precision}f}"
