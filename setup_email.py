"""Asks for your email details, saves them to .env, and sends a test email."""

import os
import re
from pathlib import Path

import house_hunter as h

EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", re.I)


def ask(prompt, check, error):
    while True:
        answer = input(prompt).strip()
        if check(answer):
            return answer
        print(f"   {error} Try again.\n")


def clear():
    os.system("cls" if os.name == "nt" else "clear")


clear()
print("House hunter email setup\n")
user = ask("1) Gmail address you made the app password on: ",
           lambda a: EMAIL_RE.fullmatch(a) and a.lower().endswith("@gmail.com"),
           "That doesn't look like a Gmail address.").lower()

print("\n2) Paste the app password (right-click, or Ctrl+V) and press Enter.")
print("   It's 16 letters, spaces are fine. The screen is cleared afterwards.")
password = ask("   App password: ",
               lambda a: re.fullmatch(r"[a-z]{16}", a.replace(" ", "").lower()),
               "That isn't 16 letters. Copy it again from the Google page.")
password = password.replace(" ", "").lower()
clear()  # don't leave the password on screen
print("House hunter email setup\n")
print(f"1) Gmail: {user}")
print("2) App password: saved (hidden)\n")

to = ask("3) Email address to send the house alerts to: ",
         lambda a: EMAIL_RE.fullmatch(a), "That doesn't look like an email address.")

(Path(h.__file__).parent / ".env").write_text(
    f"SMTP_USER={user}\nSMTP_PASSWORD={password}\nEMAIL_TO={to}\n"
    "SMTP_HOST=smtp.gmail.com\nSMTP_PORT=587\n", encoding="utf-8")
print("\nSaved. Sending a test email...")

for k in ("SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO"):
    os.environ.pop(k, None)
h.load_env()
if h.send_email("House hunter test", "Emails are working. You're all set."):
    print(f"\nSUCCESS - check {to} (and its Junk folder).")
else:
    print("\nThe test email failed (reason above). If it says 'Username and Password")
    print("not accepted', make sure the app password was made while signed in as")
    print(f"{user} - the icon in the top right of the Google page shows which account.")
