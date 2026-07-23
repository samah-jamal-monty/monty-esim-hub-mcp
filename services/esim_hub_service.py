import uuid
from enum import StrEnum
from typing import List

import httpx
from loguru import logger

from dto.bundle import Bundle
from dto.mapper import DtoMapper


class EsimHubEndpoint(StrEnum):
    API_GET_REGIONS = "/configuration/api/v1/zone/get-all"
    API_GET_COUNTRIES = "/core/api/v1/catalog/Country/get-all"
    API_GET_BUNDLES_BY_CATEGORY = "/catalog/api/v1/Bundle/get-by-category-with-currency"
    API_GET_BUNDLES_BY_ZONE = "/catalog/api/v1/Bundle/get-by-zone-with-currency"
    API_GET_BUNDLE_BY_ID = "/catalog/api/v1/Bundle/get-by-id-with-currency"
    API_GET_RESELLER_BUNDLE_BY_ID = "/catalog/api/reseller/v1/Bundle/get-all-basic/active"
    API_GET_BUNDLES_BY_COUNTRY = "/catalog/api/v1/BundleCountry/get-by-country-with-currency"
    API_SEARCH_BUNDLES_BY_COUNTRY = "/catalog/api/admin/v1/Bundle/search-by-countries"
    API_GET_TOPUP_RELATED_BUNDLES = "/core/api/v1/order/compatible-topup-with-currency"

    API_GET_ALL_BUNDLES = "/catalog/api/v1/Bundle/get-all-basic/active"
    API_SEARCH_BUNDLES = "/core/api/v1/catalog/bundles/search?pageSize=20"

    API_GET_CONTENT_TAG = "/catalog/api/reseller/v1/Content/get-latest"
    API_GET_CONTENT_TAGS = "/catalog/api/reseller/v1/Content/get-all-content"
    API_GET_GLOBAL_CONFIGURATIONS = "/configuration/api/v1/globalconfiguration/get-by-keys"
    API_GET_BUNDLE_CONSUMPTION = "/core/api/v1/order/consumption"

    API_CREATE_RESELLER_TOPUP = "/core/api/v1/order/topup"
    API_CREATE_RESELLER_ORDER = "/core/api/v1/order/create"
    API_GET_ACTIVATION_CODE = "/core/api/v1/order/activation-code"
    API_GET_ORDER_HISTORY = "/core/api/v1/order/get-order-history"

    API_CHECK_BUNDLE_APPLICABLE = "/core/api/v1/order/check-bundle-availability"

    API_EXCHANGE_RATE = "/billing/api/reseller/v1/exchangerate/get-all"


class EsimHubService:

    def __init__(self, mm_hub_url: str, digital_service_url: str, api_key: str, tenant_key: str):
        self.__mm_hub_url = mm_hub_url
        self.__digital_service_url = digital_service_url
        self.__api_key = api_key
        self.__tenant_key = tenant_key
        self.__headers = {
            "Api-Key": self.__api_key,
            "Tenant": self.__tenant_key,
            "Content-Type": "application/json",
        }

    async def get_all_bundles(self, page_index=1, page_size=20) -> List[Bundle]:
        url = f"{self.__digital_service_url}{EsimHubEndpoint.API_GET_ALL_BUNDLES}"
        logger.info(f"getting bundles from {url} with page_index={page_index} and page_size={page_size}")
        params = {
            "pageIndex": page_index,
            "pageSize": page_size,
            "CurrencyCode": "USD",
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(url=url, headers=self.__headers, params=params)
        if response.status_code == 200:
            data = response.json()
            return [DtoMapper.to_bundle(item) for item in data["data"]["items"]]
        else:
            logger.error(f"Failed to fetch bundles: {response.status_code} {response.text}")
            return []

    async def get_bundle_by_code(self, bundle_code: str, currency_code: str = "USD") -> dict | None:
        """Fetch a single bundle (raw API item, including numeric price) by its record GUID."""
        url = f"{self.__digital_service_url}{EsimHubEndpoint.API_GET_BUNDLE_BY_ID}"
        params = {
            "recordGuid": bundle_code,
            "CurrencyCode": currency_code,
        }
        logger.info(f"getting bundle {bundle_code} from {url}")
        async with httpx.AsyncClient() as client:
            response = await client.get(url=url, headers=self.__headers, params=params, timeout=60)
        if response.status_code != 200:
            logger.error(f"Failed to fetch bundle {bundle_code}: {response.status_code} {response.text}")
            return None
        return response.json().get("data", {}).get("item")

    async def purchase_bundle(self, bundle_code: str, user_email: str) -> dict:
        if not self.check_bundle_applicability(bundle_code):
            return {"success": False, "error": "Bundle not available for purchase"}
        url = f"{self.__mm_hub_url}{EsimHubEndpoint.API_CREATE_RESELLER_ORDER}"
        request_body = {
            "BundleGuid": bundle_code,
            "Quantity": 1,
            "UniqueIdentifier": str(uuid.uuid4()),
            "ServiceTag": "ESIM",
            "PhoneNumber": "",
            "ClientName": "",
            "Email": user_email,
            "PaymentMethod": "MCP",
            "DiscountAmount": None,
            "DiscountRate": None,
            "NewPrice": None,
            "BundleType": "LAND"
        }
        logger.info(f"creating order for bundle {bundle_code} at {url} with body {request_body}")
        async with httpx.AsyncClient() as client:
            response = await client.post(url=url, headers=self.__headers, json=request_body, timeout=60)
            logger.info(f"response: {response.status_code} {response.text}")
        if response.status_code != 200:
            logger.error(f"Failed to purchase bundle {bundle_code}: {response.status_code} {response.text}")
            return {"success": False, "error": response.text}
        return {"success": True, "response": response.json()}

    async def get_activation_code(self, order_id: str) -> str | None:
        url = f"{self.__mm_hub_url}{EsimHubEndpoint.API_GET_ACTIVATION_CODE}"
        params = {
            "orderId": order_id
        }
        logger.info(f"getting activation code for order {order_id} at {url}")
        async with httpx.AsyncClient() as client:
            response = await client.get(url=url, headers=self.__headers, params=params)
            logger.info(f"response: {response.status_code} {response.text}")
        if response.status_code != 200:
            logger.error(f"Failed to get activation code for order {order_id}: {response.status_code} {response.text}")
            return None
        data = response.json()
        return data.get("data", {}).get("activationCode")

    async def get_order_history(self, user_email: str, page_index=1, page_size=10) -> List[dict]:
        url = f"{self.__mm_hub_url}{EsimHubEndpoint.API_GET_ORDER_HISTORY}"
        logger.info(
            f"getting order history from {url} for user {user_email} with page_index={page_index} and page_size={page_size}")
        params = {
            "email": user_email,
            "pageIndex": page_index,
            "pageSize": page_size,
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(url=url, headers=self.__headers, params=params)
        if response.status_code == 200:
            data = response.json()
            return data["data"]["orders"]
        else:
            logger.error(f"Failed to fetch order history: {response.status_code} {response.text}")
            return []

    async def check_bundle_applicability(self, bundle_code: str) -> bool:
        url = f"{self.__mm_hub_url}{EsimHubEndpoint.API_CHECK_BUNDLE_APPLICABLE}"
        logger.info(f"checking bundle applicability from {url} for bundle {bundle_code}")
        params = {
            "bundleCode": bundle_code,
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(url=url, headers=self.__headers, params=params)
        if response.status_code == 200:
            if "success" not in response:
                return False
            return True
        else:
            logger.error(f"Failed to check bundle applicability: {response.status_code} {response.text}")
            return False

    async def search_bundles(self, gprs_from: str = None, gprs_to: str = None, validity: str = None,
                             country_name: str = None, currency_code: str = None,
                             search_keyword: str = None) -> List[Bundle]:
        url = f"{self.__mm_hub_url}{EsimHubEndpoint.API_SEARCH_BUNDLES}"
        logger.info(f"searching bundles from {url} with keyword={search_keyword} headers: {self.__headers}")
        params = {
            "&GprsFrom": gprs_from,
            "gprsTo": gprs_to,
            "Validity": validity,
            "CountryName": country_name,
            "CurrencyCode": currency_code,
            "Search": search_keyword,
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(url=url, headers=self.__headers, params=params, timeout=60)
        if response.status_code == 200:
            data = response.json()
            return [DtoMapper.to_bundle(item) for item in data["data"]["items"]]
        else:
            logger.error(f"Failed to search bundles: {response.status_code} {response.text}")
            return []
