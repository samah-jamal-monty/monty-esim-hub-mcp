from typing import List

from pydantic import BaseModel


class Bundle(BaseModel):
    code: str
    name: str
    description: str
    validity: str
    price: str
    countries: str
    regions: str
    all_countries: List[str]
    all_regions: List[str]
    gprs_limit: str
