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
        all_countries = [c.get("name", "") for c in data.get("supportedCountries", [])]
        sliced_countries = all_countries[:5]  # limit to first 5 countries
        countries = ", ".join(sliced_countries) + f" and {len(all_countries) - 5} more" if sliced_countries else ""

        all_regions = [r.get("name", "") for r in data.get("supportedZones", [])]
        regions = ", ".join(all_regions)
        return Bundle(
            code=code,
            name=name,
            description=description,
            price=f"{price} USD",
            validity=validity,
            countries=countries,
            gprs_limit=gprs_limit_display,
            all_countries=all_countries,
            all_regions=all_regions,
            regions=regions
        )
