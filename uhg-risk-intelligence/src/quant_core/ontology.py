"""
Layer 1 analog: Source & Ontology Layer.

IMPORTANT — DATA PROVENANCE:
The indicator registry and driver-loading matrix below are SYNTHETIC,
illustrative data constructed for this proof-of-concept. They are NOT sourced
from any real UHG internal system, and no such access exists or was used.
Real, public inputs used elsewhere in this project are UHG's own SEC filings
and CMS public rate notices — see README.md "Data provenance" section.

Every raw indicator, regardless of source, is mapped here into one common
taxonomy before any transform or weighting touches it. This is what makes a
cardinal hazard score and an ordinal structural rank comparable later.
"""
from __future__ import annotations

import pandas as pd

from src.schemas import Driver, Segment

# Which raw-data "layer role" each indicator belongs to, mirroring the
# original framework's Hazard / Structural / Digital split.
LAYER_ROLES = ("hazard", "structural", "digital")

# Source-quality priors: how much a layer's weights get scaled before
# normalization. S&P-analog (hazard) gets full weight because it's the most
# event-responsive; the two annual-cadence sources get a modest discount —
# same 1.00 / 0.95 / 0.95 split as the original framework, kept because the
# rationale (update-frequency discount) is domain-independent.
SOURCE_QUALITY_PRIOR = {"hazard": 1.00, "structural": 0.95, "digital": 0.95}

# Indicator registry: one row per raw indicator. `driver_loadings` follows the
# original framework's 0-3 relevance scale (0 = not relevant, 3 = highly
# relevant), expert-coded at this ontology layer, same as the source design.
INDICATOR_REGISTRY = pd.DataFrame([
    # --- Hazard layer (CMS/regulatory hazard feed analog) ---
    dict(indicator_id="IND_H01", layer_role="hazard", factor="Policy",
         subfactor="CMS Medicare Advantage rate notice", measure_type="cardinal",
         driver_loadings={Driver.CAPITAL: 3, Driver.DEMAND: 2}),
    dict(indicator_id="IND_H02", layer_role="hazard", factor="Policy",
         subfactor="PBM/drug-pricing rulemaking", measure_type="cardinal",
         driver_loadings={Driver.CAPITAL: 2, Driver.SUPPLY: 2}),
    dict(indicator_id="IND_H03", layer_role="hazard", factor="Enforcement",
         subfactor="CMS/OIG enforcement action", measure_type="cardinal",
         driver_loadings={Driver.BRAND_REPUTATION: 3, Driver.CAPITAL: 1}),
    dict(indicator_id="IND_H04", layer_role="hazard", factor="Security",
         subfactor="Health-data breach disclosure", measure_type="cardinal",
         driver_loadings={Driver.DATA_DIGITAL: 3, Driver.BRAND_REPUTATION: 2}),

    # --- Structural layer (state health-system performance proxy) ---
    dict(indicator_id="IND_S01", layer_role="structural", factor="System quality",
         subfactor="State health-system performance rank", measure_type="ordinal",
         driver_loadings={Driver.DEMAND: 2, Driver.INFRASTRUCTURE: 1}),
    dict(indicator_id="IND_S02", layer_role="structural", factor="Access",
         subfactor="State Medicaid eligibility/redetermination rank", measure_type="ordinal",
         driver_loadings={Driver.DEMAND: 3}),
    dict(indicator_id="IND_S03", layer_role="structural", factor="Workforce",
         subfactor="Clinical labor-market tightness rank", measure_type="ordinal",
         driver_loadings={Driver.TALENT: 3}),

    # --- Digital layer (weakest-fit proxy — see README limitations) ---
    dict(indicator_id="IND_D01", layer_role="digital", factor="Interoperability",
         subfactor="Health-data interoperability maturity rank", measure_type="ordinal",
         driver_loadings={Driver.DATA_DIGITAL: 3}),
    dict(indicator_id="IND_D02", layer_role="digital", factor="Compliance",
         subfactor="HIPAA enforcement-activity rank", measure_type="ordinal",
         driver_loadings={Driver.DATA_DIGITAL: 2, Driver.BRAND_REPUTATION: 1}),
])


def indicators_for_driver(driver: Driver) -> pd.DataFrame:
    """All indicators that load (loading > 0) onto a given driver."""
    mask = INDICATOR_REGISTRY["driver_loadings"].apply(lambda d: d.get(driver, 0) > 0)
    return INDICATOR_REGISTRY[mask].copy()


def loading_for(row: pd.Series, driver: Driver) -> int:
    return row["driver_loadings"].get(driver, 0)


# Segment metadata: real, public FY2025 figures (UHG SEC filings / earnings
# release), NOT synthetic. Used for weighting component impact, not for the
# indicator scores themselves.
SEGMENT_REVENUE_USD_B = {
    Segment.UHC_MEDICARE_RETIREMENT: None,   # reported jointly with UHC total; not broken out
    Segment.UHC_COMMUNITY_STATE: 94.4,
    Segment.UHC_EMPLOYER_INDIVIDUAL: None,   # reported jointly with UHC total; not broken out
    Segment.OPTUM_HEALTH: 102.0,
    Segment.OPTUM_RX: 154.7,
    Segment.OPTUM_INSIGHT: 19.4,
}
