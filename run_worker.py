from __future__ import annotations

import time

from automation_worker import AutomationWorker
from service_config import prompt_service_selection


if __name__ == "__main__":
    service_config = prompt_service_selection()
    worker = AutomationWorker(service_config=service_config)
    print(f"Routine automation worker started with services: {', '.join(service_config.enabled_services) if service_config.enabled_services else 'none'}. Press Ctrl+C to stop.")

    try:
        if worker.service_config.slack_enabled:
            worker.listen_for_slack_messages()
        elif worker.service_config.gmail_enabled:
            worker.poll_gmail_messages()
        else:
            while True:
                time.sleep(5)
    except KeyboardInterrupt:
        print("Worker stopped.")
