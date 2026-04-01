"""
Compliance Prompts module.

This module contains prompt templates for the decision agent in the NBFC compliance AI system.
The prompt assembly strategy uses a structured approach: start with system persona and JSON schema,
provide few-shot examples for calibration, inject regulatory context from RAG (with warnings if empty),
summarize agent signals in a readable format, and end with strict format reminders.
This ensures the LLM produces consistent, regulation-cited decisions with appropriate confidence adjustments.
"""

from ai.schemas import AgentState

# ---------------------------------------------------------------------------
# System Prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are an expert NBFC compliance officer with deep knowledge of RBI Master Directions, "
    "FEMA, PMLA, and KYC norms. Your task is to evaluate loan compliance based on provided data "
    "and regulatory context.\n\n"
    "Respond ONLY with a valid JSON object, no preamble, no markdown fences, no explanation outside the JSON.\n\n"
    "JSON Schema:\n"
    "{\n"
    '  "status": "APPROVED" | "REJECTED" | "REVIEW",\n'
    '  "reason": "string — 2-3 sentences, cite specific RBI regulation",\n'
    '  "clauses": ["list of specific RBI clause numbers cited"],\n'
    '  "confidence": 0.0–1.0,\n'
    '  "rules_used": ["list of rule names used in decision"]\n'
    "}\n\n"
    "Confidence Calibration: If upstream agent errors are present or RAG context is empty, "
    "reduce confidence by at least 0.15 and state why in the reason field.\n\n"
    "Bias Instruction: Default to REVIEW (not REJECTED) when evidence is ambiguous or agent errors present. "
    "Only REJECT on clear, unambiguous RBI violation."
)

# ---------------------------------------------------------------------------
# Few-Shot Examples
# ---------------------------------------------------------------------------
FEW_SHOT_EXAMPLES = (
    "INPUT: Missing PAN document + FOIR 65% (exceeds 50% RBI limit)\n"
    "OUTPUT: {\"status\": \"REJECTED\", \"reason\": \"PAN document is missing, violating KYC requirements. "
    "FOIR at 65% exceeds the RBI limit of 50% under DNBR.PD.008/03.10.119/2016-17, Section 4.2. "
    "Combined violations warrant rejection.\", \"clauses\": [\"RBI Master Direction DNBR.PD.008/03.10.119/2016-17, Section 4.2\"], "
    "\"confidence\": 0.92, \"rules_used\": [\"KYC Completeness\", \"FOIR Limit\"]}\n\n"
    "INPUT: All docs present, FOIR 38%, no sanctions, no expired docs\n"
    "OUTPUT: {\"status\": \"APPROVED\", \"reason\": \"All required documents are present and valid. "
    "FOIR at 38% is within RBI limits. No sanctions hits or expirations detected, complying with RBI Circular RBI/2022-23/100.\", "
    "\"clauses\": [\"RBI Circular RBI/2022-23/100\"], \"confidence\": 0.98, \"rules_used\": [\"Document Validity\", \"FOIR Check\", \"Sanctions Screening\"]}\n\n"
    "INPUT: RAG retrieval failed (empty context), FOIR borderline at 49.8%, one doc expires in 8 days\n"
    "OUTPUT: {\"status\": \"REVIEW\", \"reason\": \"FOIR at 49.8% is borderline and requires manual verification. "
    "Document expires in 8 days, and RAG context is empty, reducing confidence due to lack of regulatory retrieval. "
    "Per RBI guidelines, ambiguous cases default to review.\", \"clauses\": [], \"confidence\": 0.55, \"rules_used\": [\"FOIR Threshold\", \"Document Expiry\"]}"
)

# ---------------------------------------------------------------------------
# RAG Context Template
# ---------------------------------------------------------------------------
RAG_CONTEXT_TEMPLATE = (
    "REGULATORY CONTEXT for query: {query}\n\n"
    "{rag_context_formatted}"
)

# ---------------------------------------------------------------------------
# Agent Summary Template
# ---------------------------------------------------------------------------
AGENT_SUMMARY_TEMPLATE = (
    "COMPLIANCE SIGNAL SUMMARY:\n"
    "- Document Check Passed: {doc_check_passed}\n"
    "- Missing Documents: {missing_docs}\n"
    "- FOIR Value: {foir_value}\n"
    "- FOIR Passed: {foir_passed}\n"
    "- EMI Breakdown: {emi_breakdown}\n"
    "- Sanctions Hit: {sanctions_hit}\n"
    "- Matched Entity: {matched_entity}\n"
    "- Sanctions Score: {sanctions_score}\n"
    "- Expired Documents: {expired_docs}\n"
    "- Temporal Passed: {temporal_passed}\n"
    "- Days to Expiry: {days_to_expiry}\n"
    "- Agent Errors: {agent_errors}\n"
    "- Short Circuit Reason: {short_circuit_reason}"
)

# ---------------------------------------------------------------------------
# Format Reminder
# ---------------------------------------------------------------------------
FORMAT_REMINDER = (
    "CRITICAL: Your entire response must be a single valid JSON object. "
    "Do not include any text before or after the JSON. "
    "Do not use markdown code blocks."
)

# Legacy aliases for backward compatibility
FORMAT_INSTRUCTION = FORMAT_REMINDER
RAG_CONTEXT_PROMPT = RAG_CONTEXT_TEMPLATE

DECISION_AGENT_PROMPT = (
    SYSTEM_PROMPT
    + "\n\n---FEW SHOT EXAMPLES---\n" + FEW_SHOT_EXAMPLES
    + "\n\n---REGULATORY CONTEXT---\n{regulatory_context}"
    + "\n\n---COMPLIANCE SIGNALS---\n{agent_outputs}"
    + "\n\n" + FORMAT_REMINDER
)

# ---------------------------------------------------------------------------
# Prompt Builder Function
# ---------------------------------------------------------------------------
def build_decision_prompt(state: AgentState) -> str:
    """
    Assembles the final prompt for the decision agent by combining all template sections.
    
    Args:
        state: The current AgentState containing all agent outputs and context.
        
    Returns:
        The complete prompt string ready for Bedrock.
    """
    # Format RAG context
    rag_chunks = state.get("rag_context", [])
    if not rag_chunks:
        rag_context_formatted = (
            "WARNING: No regulatory context retrieved. Decision must rely on "
            "base training knowledge only. Reduce confidence accordingly."
        )
    else:
        rag_context_formatted = "\n\n".join(
            f"[SOURCE: {chunk['source']} | RELEVANCE: {chunk['score']:.2f}]\n{chunk['text']}"
            for chunk in rag_chunks
        )
    
    # Fill RAG template
    rag_section = RAG_CONTEXT_TEMPLATE.format(
        rag_context_formatted=rag_context_formatted,
        query=state.get("query", "")
    )
    
    # Fill agent summary
    agent_section = AGENT_SUMMARY_TEMPLATE.format(
        doc_check_passed=state.get("doc_check_passed", False),
        missing_docs=state.get("missing_docs", []),
        foir_value=state.get("foir_value", 0.0),
        foir_passed=state.get("foir_passed", False),
        emi_breakdown=state.get("emi_breakdown", {}),
        sanctions_hit=state.get("sanctions_hit", False),
        matched_entity=state.get("matched_entity", None),
        sanctions_score=state.get("sanctions_score", 0.0),
        expired_docs=state.get("expired_docs", []),
        temporal_passed=state.get("temporal_passed", False),
        days_to_expiry=state.get("days_to_expiry", {}),
        agent_errors=state.get("agent_errors", []),
        short_circuit_reason=state.get("short_circuit_reason", None)
    )
    
    # Assemble full prompt
    prompt = (
        SYSTEM_PROMPT
        + "\n\n---FEW SHOT EXAMPLES---\n" + FEW_SHOT_EXAMPLES
        + "\n\n---REGULATORY CONTEXT---\n" + rag_section
        + "\n\n---COMPLIANCE SIGNALS---\n" + agent_section
        + "\n\n" + FORMAT_REMINDER
    )
    
    return prompt
