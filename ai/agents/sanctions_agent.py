"""
Sanctions Agent module.

Screens entities against a mock sanctions list to detect prohibited
borrowers or counterparties.
"""

import logging

from ai.schemas import AgentState

logger = logging.getLogger(__name__)

# Mock sanctions list — in production this would be backed by an API / DB
MOCK_SANCTIONS_LIST: list[dict[str, str]] = [
    {"name": "John Doe", "pan": "ABCDE1234F"},
    {"name": "Jane Smith", "pan": "XYZAB5678G"},
    {"name": "Ravi Verma", "pan": "PQRST9012H"},
]


def sanctions_agent(state: AgentState) -> AgentState:
    """
    Screen the applicant against a mock sanctions/PEP list.

    Checks ``state.user_data`` for:
        - ``pan_number`` (str)
        - ``name``       (str)

    Populates ``state.agent_outputs["sanctions_agent"]`` with:
        - ``sanctioned`` (bool)     — True if a match is found
        - ``match``      (str|None) — matched entry description, or None

    Args:
        state: Current agent graph state.

    Returns:
        Updated AgentState with sanctions screening results.
    """
    try:
        pan = str(state.user_data.get("pan_number", "")).strip().upper()
        name = str(state.user_data.get("name", "")).strip().upper()

        match_description: str | None = None

        for entry in MOCK_SANCTIONS_LIST:
            entry_pan = entry.get("pan", "").strip().upper()
            entry_name = entry.get("name", "").strip().upper()

            if pan and pan == entry_pan:
                match_description = (
                    f"PAN match: {entry['name']} ({entry['pan']})"
                )
                break

            if name and name == entry_name:
                match_description = (
                    f"Name match: {entry['name']} ({entry['pan']})"
                )
                break

        sanctioned = match_description is not None

        state.agent_outputs["sanctions_agent"] = {
            "sanctioned": sanctioned,
            "match": match_description,
        }

        logger.info("sanctions_agent: sanctioned=%s", sanctioned)

    except Exception as exc:
        logger.warning("sanctions_agent: screening failed — %s", exc)
        state.agent_outputs["sanctions_agent"] = {
            "sanctioned": False,
            "match": None,
        }

    return state
