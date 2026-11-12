import os
import time
import threading
import queue
import secrets
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

import requests

# Replace this with your deployed Render URL after deployment.
SERVER_URL = "https://YOUR-APP-NAME.onrender.com"

APP_DIR = Path(os.getenv("APPDATA", str(Path.home()))) / "ScreenShare"
DEVICE_FILE = APP_DIR / "device_id.txt"


def get_device_id():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if DEVICE_FILE.exists():
        value = DEVICE_FILE.read_text(encoding="utf-8").strip()
        if len(value) == 32:
            return value
    value = secrets.token_hex(16)
    DEVICE_FILE.write_text(value, encoding="utf-8")
    return value


class ScreenShareClient:
    def __init__(self, root):
        self.root = root
        self.root.title("ScreenShare - Consent Client")
        self.root.geometry("460x370")
        self.root.resizable(False, False)

        self.device_id = get_device_id()
        self.events = queue.Queue()
        self.running = True
        self.current_request = None
        self.request_busy = False

        tk.Label(
            root, text="ScreenShare",
            font=("Segoe UI", 23, "bold")
        ).pack(pady=(16, 3))

        tk.Label(
            root,
            text="This computer can receive screen-viewing requests.",
            font=("Segoe UI", 9)
        ).pack(pady=(0, 10))

        tk.Label(
            root, text="Your device pairing ID:",
            font=("Segoe UI", 9, "bold")
        ).pack()

        self.id_entry = tk.Entry(root, width=39, justify="center")
        self.id_entry.insert(0, self.device_id)
        self.id_entry.configure(state="readonly")
        self.id_entry.pack(pady=(3, 8))

        self.status = tk.Label(
            root, text="Waiting for a request…",
            fg="#2563eb", font=("Segoe UI", 9)
        )
        self.status.pack(pady=(2, 8))

        self.request_panel = tk.Frame(
            root, bd=1, relief="solid", padx=12, pady=10
        )
        tk.Label(
            self.request_panel,
            text="Incoming screen-viewing request",
            font=("Segoe UI", 11, "bold")
        ).pack(pady=(0, 5))
        tk.Label(
            self.request_panel,
            text="Someone wants permission to view this computer's screen. "
                 "Only accept if you recognise and trust the requester.",
            wraplength=390, justify="center",
            font=("Segoe UI", 9)
        ).pack(pady=(0, 10))

        self.accept_button = tk.Button(
            self.request_panel,
            text="Accept & Open Screen Sharing",
            command=self.accept_request,
            bg="#16833b", fg="white",
            activebackground="#116b30", activeforeground="white",
            font=("Segoe UI", 10, "bold"),
            width=31, pady=7
        )
        self.accept_button.pack(pady=3)

        self.decline_button = tk.Button(
            self.request_panel,
            text="Decline",
            command=self.decline_request,
            font=("Segoe UI", 9), width=18
        )
        self.decline_button.pack(pady=3)
        self.request_panel.pack_forget()

        self.stop_note = tk.Label(
            root,
            text="After accepting, your browser will open. Confirm the screen "
                 "or window in its screen-sharing picker. You can stop sharing "
                 "from the browser at any time.",
            font=("Segoe UI", 8), wraplength=410, justify="center",
            fg="#444444"
        )
        self.stop_note.pack(pady=(12, 5))

        tk.Button(
            root, text="Quit", command=self.close, width=12
        ).pack(pady=(3, 8))

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        threading.Thread(target=self.poll_loop, daemon=True).start()
        self.root.after(300, self.process_events)

    def poll_loop(self):
        while self.running:
            try:
                if "YOUR-APP-NAME" in SERVER_URL:
                    self.events.put(("status", "Set SERVER_URL in client.py first."))
                    time.sleep(4)
                    continue

                response = requests.get(
                    f"{SERVER_URL}/api/poll/{self.device_id}", timeout=12
                )
                if response.ok:
                    data = response.json()
                    if data.get("status") == "pending":
                        self.events.put(("request", data["request_id"]))
                        time.sleep(5)
                    else:
                        time.sleep(3)
                else:
                    self.events.put(("status", "Server unavailable; retrying…"))
                    time.sleep(6)
            except requests.RequestException:
                self.events.put(("status", "Connecting to server…"))
                time.sleep(6)

    def process_events(self):
        if not self.running:
            return
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "status":
                    self.status.config(text=value)
                elif kind == "request":
                    self.show_request(value)
                elif kind == "decision_result":
                    self.finish_decision(value)
        except queue.Empty:
            pass
        self.root.after(300, self.process_events)

    def show_request(self, request_id):
        if self.current_request == request_id or self.request_busy:
            return
        self.current_request = request_id
        self.status.config(text="A screen-viewing request needs your decision.",
                           fg="#b45309")
        self.request_panel.pack(fill="x", padx=18, pady=5)

    def accept_request(self):
        self.send_decision("allow")

    def decline_request(self):
        self.send_decision("deny")

    def send_decision(self, decision):
        if not self.current_request or self.request_busy:
            return
        self.request_busy = True
        self.accept_button.config(state="disabled")
        self.decline_button.config(state="disabled")
        self.status.config(text="Sending your decision…", fg="#2563eb")
        request_id = self.current_request

        def worker():
            try:
                response = requests.post(
                    f"{SERVER_URL}/api/respond/{request_id}",
                    json={"device_id": self.device_id, "decision": decision},
                    timeout=12
                )
                if response.ok:
                    self.events.put(("decision_result", (decision, request_id, True)))
                else:
                    self.events.put(("decision_result", (decision, request_id, False)))
            except requests.RequestException:
                self.events.put(("decision_result", (decision, request_id, False)))

        threading.Thread(target=worker, daemon=True).start()

    def finish_decision(self, result):
        decision, request_id, ok = result
        self.request_busy = False
        self.current_request = None
        self.request_panel.pack_forget()
        self.accept_button.config(state="normal")
        self.decline_button.config(state="normal")

        if not ok:
            self.status.config(
                text="Could not send your decision. Waiting for another request…",
                fg="#b91c1c"
            )
            return

        if decision == "allow":
            self.status.config(
                text="Approved. Complete the screen-sharing confirmation in your browser.",
                fg="#16833b"
            )
            webbrowser.open(f"{SERVER_URL}/share/{request_id}")
        else:
            self.status.config(text="Request declined.", fg="#555555")

    def close(self):
        self.running = False
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = ScreenShareClient(root)
    root.mainloop()
