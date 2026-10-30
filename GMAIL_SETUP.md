# Connect Gmail to ActionInbox (optional, local use)

ActionInbox v2 can show messages from your own Gmail account without copying them by hand. You choose when to search and which email to read. The existing task review flow stays the same: **nothing becomes a task until you click Approve task**.

This is a **personal local development setup**, not a public Gmail service. No Google credentials are included in the repository, and you should **never send your OAuth JSON or local token file to anyone, including in a chat**.

## 1. Get the Gmail branch

Open a new PowerShell terminal in your existing ActionInbox folder:

```powershell
cd $HOME\ActionInbox
git fetch origin
git switch --track origin/feature/gmail-readonly
```

If you already created the local branch, use `git switch feature/gmail-readonly` instead. Your existing `data/tasks.sqlite3` remains on your computer; it is excluded from Git.

## 2. Enable Gmail API in your own Google Cloud project

1. Open the [Google Cloud Console](https://console.cloud.google.com/), choose or create a project, and enable the [Gmail API](https://console.cloud.google.com/apis/library/gmail.googleapis.com).
2. Open [Google Auth Platform](https://console.cloud.google.com/auth/overview). Configure **Branding**, **Audience**, and **Data Access** as requested. For a personal Gmail account, choose **External** with **Testing** publishing status (Internal is only for eligible Google Workspace organizations).
3. Under **Audience > Test users**, add **your own Gmail address**. The app may remain in testing mode for personal development.
4. Under **Data Access**, add only the scope `https://www.googleapis.com/auth/gmail.readonly` if the console asks you to configure scopes.
5. Under **Clients**, create an OAuth client with **Application type: Desktop app**. Download the OAuth client JSON. Rename it to `credentials.json` and put it directly in `C:\Users\ysaic\ActionInbox\credentials.json` (or the root of your checkout).

Do **not** create an API key or use a service-account key; this flow uses your own Google sign-in. The requested `gmail.readonly` scope is **restricted** by Google. It grants read access to your mailbox, although the app only fetches messages on demand. A public, multi-user version would require Google's verification and potentially additional security assessment. See [Google's Python quickstart](https://developers.google.com/workspace/gmail/api/quickstart/python) and [Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes).

## 3. Install optional Gmail libraries

From the **project root**, in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-gmail.txt
```

If you have not made a virtual environment yet, follow the main [README](README.md) first.

## 4. Connect through your own browser

```powershell
.\.venv\Scripts\python.exe -m backend.gmail connect
```

Your browser opens Google's OAuth login and consent screen. Select the Gmail account you added as a test user. Grant access only if you recognize the Google Cloud project **you just configured**. ActionInbox cannot grant consent for you.

A successful flow writes a local OAuth token to `data/gmail-token.json`. The file contains sensitive access/refresh tokens, is excluded from Git, and is never sent to the browser or stored in SQLite. Keep it private. OAuth test-mode refresh tokens may expire, so you might need to reconnect periodically.

You can check the *local token presence* with:

```powershell
.\.venv\Scripts\python.exe -m backend.gmail status
```

## 5. Open the updated app

If your FastAPI terminal is still running v1, stop it with **Ctrl+C**, then restart:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
cd $HOME\ActionInbox\frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173, choose **Gmail (optional)**, then **Refresh connection**.

1. Keep the default search `in:inbox newer_than:14d` or enter your own Gmail query.
2. Click **Find emails** to fetch up to ten subject/sender/date summaries. The app does not search Gmail on page load.
3. Choose one message to fetch its body. It never fetches attachments.
4. Click **Analyze this email**, inspect the message on the Inbox assistant page, then **Find action items**.
5. Edit or dismiss the suggestions, and approve only what you want saved.

**Important:** The task extraction interprets relative dates (like “Friday”) relative to the current local date, not the sender's timestamp. Always inspect and correct dates, especially for old messages.

## Disconnect or troubleshoot

```powershell
.\.venv\Scripts\python.exe -m backend.gmail disconnect
```

Disconnect deletes the **local token only**. To revoke access at Google as well, open [Google Account > Third-party connections](https://myaccount.google.com/connections) and remove your app's authorization.

- **Access blocked / not a test user:** Add your exact account under Google Auth Platform > Audience > Test users.
- **API has not been used / disabled:** Enable Gmail API in the same Google Cloud project as the Desktop client.
- **Missing credentials file:** Confirm the file is named exactly `credentials.json` at the project root, not `credentials.json.json`.
- **Token expired:** Re-run the connect command; consent may need to be repeated while in testing mode.
- **Nothing shows in Gmail:** Verify the two PowerShell terminals are running updated code; refresh Gmail connection status, then click Find emails.
- **Message unreadable:** Some emails contain only attachments or unsupported encodings. No attachment is downloaded or analyzed.

**Privacy boundary:** This integration talks to **Google's Gmail API** only after you explicitly request it. Email bodies are not sent to a hosted AI provider, and the app has no permission to send, modify, or delete Gmail. Because the local FastAPI app has no login, **never expose port 8000 or the frontend to the public Internet**, especially after connecting an account.

**Testing limitation:** Automated tests mock Gmail API responses. The live OAuth connection must be completed on your own computer because it requires your Google Cloud client and consent.
