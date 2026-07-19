"""Interactive CLI for manually exercising the payment collection agent.

Usage:
    python cli.py

Requires OPENAI_API_KEY to be set, or a .env file (see README.md).
"""
import sys

from agent import Agent

# Balances are printed with a rupee sign (₹). Windows terminals often
# default to a legacy codepage (cp1252) that can't encode it, which would
# otherwise crash on the first "Identity verified..." message. Force UTF-8
# stdout so this works the same on every platform.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    agent = Agent()
    print("Payment Collection Agent -- type 'quit' to exit.\n")

    try:
        user_input = input("You: ")
    except EOFError:
        return

    while True:
        if user_input.strip().lower() in {"quit", "exit"}:
            print("Agent: Goodbye!")
            break

        result = agent.next(user_input)
        print(f"Agent: {result['message']}\n")

        if agent._impl.state.closed:
            break

        try:
            user_input = input("You: ")
        except EOFError:
            break


if __name__ == "__main__":
    main()
