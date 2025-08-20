from pydantic import BaseModel

class ProjectCreate(BaseModel):
    name: str
    creator: str
    category: str
    goal_microalgos: int
    token_asset_id: int
    token_rate_per_algo: float
    token_pool: int
