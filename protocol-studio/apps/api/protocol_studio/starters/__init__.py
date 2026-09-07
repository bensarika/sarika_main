"""Reviewed starter templates shipped with the application.

A starter is a complete ``DraftState`` seed: a schema-valid trial model plus
narrative blocks for every authoring section, with claims binding phrases in
the prose to model fields so the checks can see them. Starters are *synthetic*
teaching designs — no dose, eligibility rule, safety policy or sample size in
them is proposed for use in a real trial. The Adapt Starter flow rewrites
source-drug mentions and creates evidence requirements for the target drug.
"""

from protocol_studio.starters.ad_antibody import AD_ANTIBODY_ID, ad_antibody_blocks, ad_antibody_model

__all__ = ["AD_ANTIBODY_ID", "ad_antibody_blocks", "ad_antibody_model"]
