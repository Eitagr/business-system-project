# Demo — identity verification chat

The chat header must show **Gemini פעיל**. Appointment details are shown
only after a matching national ID.

There are two customers named רותם, so the bot asks which one. It does
not guess.

```
User:  קוראים לי רותם ויש לי תור בתאריך 18.01.2027
Bot:   מצאתי כמה לקוחות בשם הזה: רותם מירון או רותם לוי. מי מביניהם?

User:  מירון
Bot:   מה תעודת הזהות שלך? (לצורך אימות בלבד)

User:  123456789
Bot:   מצאתי אותך! שימו לב: התור שלך בפועל הוא ב-19.01.2027 בשעה 19:00
       (ולא ב-18.01 כפי שציינת).
```

Run locally: [DEPLOY.md](DEPLOY.md). Required scenarios: `python check_chat.py`.
