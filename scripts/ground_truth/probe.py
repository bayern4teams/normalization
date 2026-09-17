#!/usr/bin/env python3
"""Probe the real Dispatcher on representative values so column_config.json
is grounded in actual normalizer behavior, not assumptions.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for pkg in ("normcore", "normalizers", "normdict", "normexec"):
    sys.path.insert(0, str(ROOT / "packages" / pkg / "src"))

import blake3

from normalizers.address import AddressNormalizer, LibpostalClient
from normalizers.boolean import BooleanNormalizer
from normalizers.company import CompanyNormalizer
from normalizers.country import CountryNormalizer
from normalizers.currency import CurrencyNormalizer
from normalizers.date import DateNormalizer
from normalizers.email import EmailNormalizer
from normalizers.generic_text import GenericTextNormalizer
from normalizers.identifier import IdentifierNormalizer, UuidNormalizer
from normalizers.language import LanguageNormalizer
from normalizers.name import NameNormalizer
from normalizers.numeric import NumericNormalizer
from normalizers.passthrough import PassthroughNormalizer
from normalizers.phone import PhoneNormalizer
from normalizers.postcode import PostcodeNormalizer
from normalizers.script import ScriptNormalizer
from normalizers.unit import UnitNormalizer
from normalizers.url import URLNormalizer
from normcore import Dispatcher, ErrorPolicy, FieldSemanticType, NormalizationContext, NormalizerRegistry
from normcore.rules import NormalizationProfile
from normdict import DictionaryLoader

PROFILE = NormalizationProfile(
    id="scaffold", name="probe", version="v0", description="probe",
    created_at="1970-01-01T00:00:00Z", updated_at="1970-01-01T00:00:00Z", created_by="probe",
)

CASES: list[tuple[str, FieldSemanticType, list[str]]] = [
    ("company.website", FieldSemanticType.URL,
     ["1918.eu", "2020satellite.satpremium.com", "http://www.2d-engineering.com", "https://Kg.Diffbot.com/Image/Api/Get?fetch=yes"]),
    ("company.logo", FieldSemanticType.URL,
     ["https://kg.diffbot.com/image/api/get?fetch=yes&url=g%3Cj7P0", "https://logo.clearbit.com/acme.com"]),
    ("company.foundingdate", FieldSemanticType.DATE,
     ["d1836-01-01", "d1877-XX-XX", "1987-03-14", "03/04/2024", "d1989-12-11", ""]),
    ("company.ispublic", FieldSemanticType.BOOLEAN,
     ["True", "False", ""]),
    ("companyceoname", FieldSemanticType.PERSON_NAME,
     ["Adel Al-Saleh", "Adi Rahman Adiwoso", "Alexander H. Good"]),
    ("contactphone", FieldSemanticType.PHONE,
     ["+-44-1207-544664", "+1-202-482-6125", "8816-555-0100", "(212) 555-0198", "+44 20 7946 0958"]),
    ("contactemail", FieldSemanticType.EMAIL,
     ["30sw.pa.workflow@us.af.mil", "INFO@VOXSPACE.COM", "not-an-email", "Darrell.Hackler@ads-inc.com"]),
    ("location.street", FieldSemanticType.ADDRESS,
     ["#101 Gong Ye 3rd Rd", "6 / F, building 1, innovation and entrepreneurship Plaza, Science and technology innovation city High tech Industrial Development Zone", ""]),
    ("location.postalcode", FieldSemanticType.POSTCODE,
     ["00143", "03054-4898", "PO box.65523", ""]),
    ("location.latitude", FieldSemanticType.NUMERIC,
     ["-1.003188967704773", "-11.929178237915039", "1,234.5"]),
    ("currency", FieldSemanticType.CURRENCY,
     ["USD", "EUR", "CAD", "$1,234", "100 USD"]),
    ("company.types", FieldSemanticType.CODE,
     ['["Organization", "Company", "Corporation"]', "Organization"]),
    ("techname", FieldSemanticType.FREE_TEXT,
     [".NET Framework", "#Wemakespacepossible #Headinspacefeetonearth"]),
    ("year", FieldSemanticType.NUMERIC,
     ["2014", "2001"]),
    ("companyid", FieldSemanticType.IDENTIFIER,
     ["E-24TeCP8Oju_YTk6cv0GUw", "0009c025cf82d994"]),
]


def main() -> None:
    loader = DictionaryLoader(str(ROOT / "data" / "dictionaries"))
    registry = NormalizerRegistry()
    registry.register(PassthroughNormalizer())
    registry.register(GenericTextNormalizer(loader))
    registry.register(NameNormalizer(loader))
    registry.register(CompanyNormalizer(loader))
    registry.register(PhoneNormalizer())
    registry.register(EmailNormalizer())
    registry.register(AddressNormalizer(LibpostalClient("http://localhost:8081")))
    registry.register(PostcodeNormalizer())
    registry.register(DateNormalizer())
    registry.register(CountryNormalizer())
    registry.register(LanguageNormalizer())
    registry.register(ScriptNormalizer())
    registry.register(IdentifierNormalizer())
    registry.register(UuidNormalizer())
    registry.register(NumericNormalizer())
    registry.register(CurrencyNormalizer())
    registry.register(UnitNormalizer())
    registry.register(BooleanNormalizer())
    registry.register(URLNormalizer())
    dispatcher = Dispatcher(registry, env_id=blake3.blake3(b"probe").hexdigest())

    for label, stype, values in CASES:
        ctx = NormalizationContext(
            field_name=label, semantic_type=stype, table="probe",
            source="probe", error_policy=ErrorPolicy.RETURN_ORIGINAL,
        )
        print(f"\n### {label} [{stype.value}]")
        for v in values:
            r = dispatcher.normalize(v, stype, ctx, PROFILE)
            print(f"  {v!r:58s} -> status={r.normalization_status.value:12s} display={str(r.display)[:56]!r} errs={r.errors}")


if __name__ == "__main__":
    main()
