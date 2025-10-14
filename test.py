import asyncio

from config.utils import esim_hub_service_instance

service = esim_hub_service_instance()


bundles = asyncio.run(service.get_all_bundles())

print(bundles)