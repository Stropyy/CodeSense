"""Built-in CodeLens rules. Importing this package registers exactly 14 rules."""

from .base import RULE_REGISTRY, Rule, register
from . import flow as flow
from . import project as project
from . import structure as structure

__all__ = ["RULE_REGISTRY", "Rule", "register", "flow", "project", "structure"]
