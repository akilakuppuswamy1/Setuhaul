from app.models.carrier import Carrier
from app.repositories.base import BaseRepository


class CarrierRepository(BaseRepository[Carrier]):
    model = Carrier
    order_by_columns = (Carrier.name, Carrier.id)
