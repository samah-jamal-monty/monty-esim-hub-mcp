from dto.bundle import Bundle


class DtoMapper:

    @staticmethod
    def to_bundle(data: dict) -> Bundle:
        bundle_info = data.get("bundleInfo", {})
        code = data.get("recordGuid", "")
        name = data.get("bundleDetails")[0].get("name", "")
        description = data.get("bundleDetails")[0].get("description", "")
        price = data.get("price", "N/A")
        gprs_limit = data.get("gprs_limit", 0)
        gprs_limit_display = f'{gprs_limit} {bundle_info.get("dataUnit")}' if gprs_limit >= 0 else "∞ Unlimited"
        validity_period = data.get("validityPeriodCycle", {})
        validity_details = validity_period.get("details", [])
        if len(validity_details) > 0:
            validity = validity_details[0].get("name", "0 Day")
        else:
            validity = "0 Day"
        countries = [c.get("name", "") for c in data.get("supportedCountries", [])]

        return Bundle(
            code=code,
            name=name,
            description=description,
            price=f"{price} USD",
            validity=validity,
            countries=countries,
            gprs_limit=gprs_limit_display,
        )
