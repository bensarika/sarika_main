"""ps_rules — deterministic and conditional-completeness validation.

Public surface (keep in sync with README.md):

- ``Finding``            typed result; carries the revision it was computed at
- ``RuleContext``        everything a rule may look at besides the model
- ``run_rules``          run every registered inline rule; returns findings
- ``catalogue``          the R01–R22 catalogue from ``reference/validation_rules.json``

Rules never mutate the model and never call a model provider. Semantic checks
(R13, R14, R20, LLM-suggested conflicts) are *not* here; they belong to the
worker and produce candidate findings (docs/01_architecture.md §6.4).
"""

from ps_rules.catalogue import RuleSpec, catalogue
from ps_rules.finding import Finding, Severity
from ps_rules.registry import RuleContext, run_rules

__all__ = ["Finding", "RuleContext", "RuleSpec", "Severity", "catalogue", "run_rules"]
