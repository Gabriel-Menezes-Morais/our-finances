"""Financial display uses the same currency precision as the ledger."""

from app.domain.service import currency_digits


def format_money(amount: int, currency: str = "BRL") -> str:
    if type(amount) is not int:
        raise ValueError("Valor financeiro deve ser inteiro em unidades mínimas.")
    digits = currency_digits(currency)
    divisor = 10**digits
    absolute = abs(amount)
    grouped = f"{absolute // divisor:,}".replace(",", ".")
    fraction = f",{absolute % divisor:0{digits}d}" if digits else ""
    return f"{currency} {'-' if amount < 0 else ''}{grouped}{fraction}"
