from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from chatbot import RoutineChatbot
from google_integration import GoogleIntegration
from routine_manager import load_routine
from service_config import ServiceConfig
from slack_integration import SlackIntegration


class RoutineLauncherWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Routine Assistant")
        self.root.geometry("500x420")
        self.root.minsize(420, 300)

        title = ttk.Label(root, text="Choose which services to handle your routine", font=("Segoe UI", 12, "bold"))
        title.pack(pady=(18, 8), padx=18, anchor="w")

        self.slack_var = tk.BooleanVar(value=True)
        self.gmail_var = tk.BooleanVar(value=True)
        self.calendar_var = tk.BooleanVar(value=True)

        ttk.Checkbutton(root, text="Slack", variable=self.slack_var).pack(anchor="w", padx=24)
        ttk.Checkbutton(root, text="Gmail", variable=self.gmail_var).pack(anchor="w", padx=24)
        ttk.Checkbutton(root, text="Calendar", variable=self.calendar_var).pack(anchor="w", padx=24)

        ttk.Label(root, text="Routine file:", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=24, pady=(16, 6))
        self.routine_path_var = tk.StringVar(value="routine.json")
        ttk.Entry(root, textvariable=self.routine_path_var, width=38).pack(anchor="w", padx=24, fill="x")

        ttk.Label(root, text="If you do not have a routine yet, leave the default file and start empty.", foreground="#555555").pack(anchor="w", padx=24, pady=(6, 16))

        button_row = ttk.Frame(root)
        button_row.pack(pady=(0, 18))
        ttk.Button(button_row, text="Start Assistant", command=self.start_assistant).pack(side="left", padx=8)
        ttk.Button(button_row, text="Exit", command=self.root.destroy).pack(side="left", padx=8)

    def start_assistant(self):
        enabled = []
        if self.slack_var.get():
            enabled.append("slack")
        if self.gmail_var.get():
            enabled.append("gmail")
        if self.calendar_var.get():
            enabled.append("calendar")

        if not enabled:
            messagebox.showwarning("No service selected", "Please select at least one service.")
            return

        service_config = ServiceConfig(
            enabled_services=enabled,
            slack_enabled=self.slack_var.get(),
            gmail_enabled=self.gmail_var.get(),
            calendar_enabled=self.calendar_var.get(),
        )

        routine_path = self.routine_path_var.get().strip() or "routine.json"
        self.root.destroy()
        RoutineChatWindow(service_config, routine_path)


class RoutineChatWindow:
    def __init__(self, service_config: ServiceConfig, routine_path: str):
        self.service_config = service_config
        self.routine_path = routine_path
        self.bot = RoutineChatbot(routine_path=routine_path, service_config=service_config)

        self.root = tk.Tk()
        self.root.title("Routine Assistant Chat")
        self.root.geometry("820x620")

        top_bar = ttk.Frame(self.root, padding=(12, 10))
        top_bar.pack(fill="x")

        ttk.Label(top_bar, text=f"Mode: {', '.join(service_config.enabled_services)}", font=("Segoe UI", 11, "bold")).pack(anchor="w")

        action_frame = ttk.Frame(self.root)
        action_frame.pack(fill="x", padx=12, pady=(0, 8))
        ttk.Button(action_frame, text="Today’s routine", command=self.show_today_routine).pack(side="left", padx=(0, 8))
        ttk.Button(action_frame, text="Free slots", command=self.show_free_slots).pack(side="left", padx=(0, 8))
        ttk.Button(action_frame, text="Check auth", command=self.check_auth).pack(side="left", padx=(0, 8))
        if service_config.gmail_enabled or service_config.calendar_enabled:
            ttk.Button(action_frame, text="Google login", command=self.google_login).pack(side="left", padx=(0, 8))
        if service_config.slack_enabled:
            ttk.Button(action_frame, text="Slack check", command=self.slack_check).pack(side="left")

        self.chat_widget = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, state="disabled", font=("Segoe UI", 10))
        self.chat_widget.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        input_frame = ttk.Frame(self.root)
        input_frame.pack(fill="x", padx=12, pady=(0, 12))
        self.user_input = ttk.Entry(input_frame)
        self.user_input.pack(side="left", fill="x", expand=True)
        self.user_input.bind("<Return>", lambda event: self.send_message())
        ttk.Button(input_frame, text="Send", command=self.send_message).pack(side="left", padx=(8, 0))

        self._append_system(self.bot.startup_check())
        self._append_system("Type a request like: 'what is my routine today?', 'when am I free?', or 'move gym to 10 pm'.")
        self.root.mainloop()

    def _append_system(self, message: str):
        self.chat_widget.configure(state="normal")
        self.chat_widget.insert(tk.END, message + "\n\n")
        self.chat_widget.configure(state="disabled")
        self.chat_widget.see(tk.END)

    def send_message(self):
        text = self.user_input.get().strip()
        if not text:
            return
        self.user_input.delete(0, tk.END)
        self._append_system(f"You: {text}")

        response = self.bot.respond(text)
        self._append_system(f"Assistant: {response}")

    def show_today_routine(self):
        self._append_system("Assistant: " + self.bot.respond("what is my routine today?"))

    def show_free_slots(self):
        self._append_system("Assistant: " + self.bot.respond("when am i free today?"))

    def check_auth(self):
        summary = self.bot.startup_check()
        self._append_system("Assistant: " + summary)

    def google_login(self):
        try:
            GoogleIntegration()
            self._append_system("Assistant: Google login checked successfully. Gmail/Calendar authentication is ready.")
        except Exception as exc:  # pragma: no cover - UI flow
            self._append_system(f"Assistant: Google login failed: {exc}")

    def slack_check(self):
        try:
            SlackIntegration().verify_connection()
            self._append_system("Assistant: Slack connection verified successfully.")
        except Exception as exc:  # pragma: no cover - UI flow
            self._append_system(f"Assistant: Slack check failed: {exc}")


def main():
    root = tk.Tk()
    app = RoutineLauncherWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
