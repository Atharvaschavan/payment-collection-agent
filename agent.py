"""Required top-level entry point used for automated evaluation.

    agent = Agent()
    agent.next("Hi")
    # -> {"message": "Hello! Please share your account ID to get started."}

This module only adapts the real implementation (payment_agent/orchestrator.py)
to the exact interface the assignment specifies -- see that module (and
DESIGN.md) for the actual conversation logic.
"""
from payment_agent.orchestrator import PaymentCollectionAgent


class Agent:
    def __init__(self):
        self._impl = PaymentCollectionAgent()

    def next(self, user_input: str) -> dict:
        """Process one turn of the conversation.

        Args:
            user_input: The user's message as a plain string.

        Returns:
            {"message": str}
        """
        return self._impl.next(user_input)
