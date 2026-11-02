"""Availability depends on status first and quantity second."""

from enum import StrEnum


class Availability(StrEnum):
    AVAILABLE = "available"
    OUT_OF_STOCK = "out_of_stock"
    DISCONTINUED = "discontinued"
    COMING_SOON = "coming_soon"


def availability_of(status: str, stock_quantity: int) -> Availability:
    if status == "discontinued":
        return Availability.DISCONTINUED
    if status == "coming_soon":
        return Availability.COMING_SOON
    return Availability.AVAILABLE if stock_quantity > 0 else Availability.OUT_OF_STOCK
