"""Versioned geographic sampling zones, not Saudi administrative boundaries.

East takes longitude >=48; the remaining area is split into South (<21N),
North (>=27N), West (<42E), and Central. Country verification is mandatory.
Search boxes cover focused cores within the assignment zones, not their full extent.
Boxes may include neighboring countries; they never establish Saudi membership.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    name: str
    bbox: tuple[float, float, float, float]

    @property
    def query_bbox(self):
        return ",".join(str(value) for value in self.bbox)


REGIONS = (
    Region("North", (36, 27, 45, 30)),
    Region("South", (40, 16.5, 45, 21)),
    Region("East", (48, 22, 50.5, 28)),
    Region("West", (37, 21, 42, 27)),
    Region("Central", (42, 21, 48, 27)),
)
REGION_SCHEME = "saudi-coordinate-zones-v1"


def region_for(latitude, longitude):
    if not (16 <= latitude <= 33 and 34 <= longitude <= 56):
        return None
    if longitude >= 48:
        return "East"
    if latitude < 21:
        return "South"
    if latitude >= 27:
        return "North"
    return "West" if longitude < 42 else "Central"
