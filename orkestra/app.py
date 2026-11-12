"""
AI CLI Orchestration Terminal Entry Point.
Launches the multi-agent orchestration terminal.
"""
import argparse
import sys
from config import AVAILABLE_PROVIDERS, DEFAULT_CONDUCTOR
from ui import OrchestrationApp

def main():
    parser = argparse.ArgumentParser(description="AI CLI Orchestration Terminal")
    parser.add_argument("--chief", choices=list(AVAILABLE_PROVIDERS.keys()), help="Baş yapay zekayı doğrudan belirle")
    parser.add_argument("--model", help="Şef için model id")
    parser.add_argument("--effort", help="Akıl yürütme seviyesi (low, medium, high, xhigh, max, ultra)")
    args = parser.parse_args()

    chief_key = args.chief or DEFAULT_CONDUCTOR
    chief_model = args.model
    chief_effort = args.effort

    # Launch full graphical orchestration TUI
    app = OrchestrationApp(
        conductor_key=chief_key,
        conductor_model=chief_model,
        conductor_effort=chief_effort
    )
    app.run()

if __name__ == "__main__":
    main()
