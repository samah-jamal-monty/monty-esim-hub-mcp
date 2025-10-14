import os

from dotenv import load_dotenv

from services.esim_hub_service import EsimHubService

load_dotenv()


def esim_hub_service_instance() -> EsimHubService:
    return EsimHubService(
        digital_service_url=os.getenv("ESIM_DIGITAL_SERVICE_URL"),
        mm_hub_url=os.getenv("ESIM_MM_HUB_API_URL"),
        api_key=os.getenv("ESIM_HUB_API_KEY"),
        tenant_key=os.getenv("ESIM_HUB_TENANT_KEY")
    )
