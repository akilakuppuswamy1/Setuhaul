"""Human escalation policy. Does not dispatch a full operations workflow."""


def should_escalate(
    *,
    wants_human: bool,
    no_safe_option: bool,
    unresolved_ambiguity: bool,
    operational_conflict: bool,
    outside_authority: bool,
) -> tuple[bool, str | None]:
    if wants_human:
        return True, "The driver requested a human operator."
    if outside_authority:
        return True, "This request is outside automated operational authority."
    if no_safe_option:
        return True, "No safe feasible option was found automatically."
    if operational_conflict:
        return True, "An operational conflict could not be resolved automatically."
    if unresolved_ambiguity:
        return True, "Required operational context could not be resolved safely."
    return False, None


def driver_escalation_message(reason: str | None) -> str:
    detail = reason or "This needs human operations review."
    return (
        f"{detail} I've marked this conversation for human operations review. "
        "A person has not acted on it yet."
    )
