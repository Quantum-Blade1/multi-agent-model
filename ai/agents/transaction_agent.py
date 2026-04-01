"""
Transaction Agent module.

Applies basic financial obligation rules (FOIR) to determine whether
a borrower's debt-to-income ratio is within acceptable limits.
"""

import logging

from ai.core.schemas import AgentState

logger = logging.getLogger(__name__)

FOIR_THRESHOLD = 0.5  # Fixed Obligation to Income Ratio ceiling


def transaction_agent(state: AgentState) -> AgentState:
    """
    Evaluate the borrower's FOIR (Fixed Obligation to Income Ratio).

    Rule: ``(existing_emi + new_emi) / income < 0.5``

    Expected keys in ``state.user_data``:
        - ``loan_amount``   (float) — requested loan principal
        - ``income``        (float) — monthly income
        - ``existing_emi``  (float) — sum of current monthly EMI obligations
        - ``tenure_months`` (int, optional) — loan tenure; defaults to 60

    Populates ``state.agent_outputs["transaction_agent"]`` with:
        - ``foir_pass``  (bool)  — True if FOIR is below threshold
        - ``foir_value`` (float) — calculated FOIR ratio

    Args:
        state: Current agent graph state.

    Returns:
        Updated AgentState with FOIR evaluation results.
    """
    try:
        user_data = state["user_data"]
        income = float(user_data.get("income", 0))
        existing_emi = float(user_data.get("existing_emi", 0))
        loan_amount = float(user_data.get("loan_amount", 0))
        tenure_months = int(user_data.get("tenure_months", 60))

        if income <= 0:
            logger.warning("transaction_agent: income is zero or negative.")
            state["agent_outputs"]["transaction_agent"] = {
                "foir_pass": False,
                "foir_value": 1.0,
            }
            return state

        # Simple flat EMI approximation (principal / tenure)
        new_emi = loan_amount / tenure_months if tenure_months > 0 else loan_amount

        foir = (existing_emi + new_emi) / income
        foir_pass = foir < FOIR_THRESHOLD

        state["agent_outputs"]["transaction_agent"] = {
            "foir_pass": foir_pass,
            "foir_value": round(foir, 4),
        }

        logger.info(
            "transaction_agent: FOIR=%.4f, pass=%s", foir, foir_pass
        )

    except Exception as exc:
        logger.warning("transaction_agent: evaluation failed — %s", exc)
        state["agent_outputs"]["transaction_agent"] = {
            "foir_pass": False,
            "foir_value": 0.0,
        }

    return state
