from pydantic import BaseModel


class Strategy(BaseModel):
    name: str
    description: str
    status: str
