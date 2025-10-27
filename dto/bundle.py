from pydantic import BaseModel


class Bundle(BaseModel):
    code: str
    name: str
    description: str
    validity: str
    price: str
    countries: str
    gprs_limit: str
