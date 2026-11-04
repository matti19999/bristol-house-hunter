# Bristol House Hunter

Every 10 minutes, GitHub checks **Rightmove** (student lets only),
**AccommodationForStudents** and **UniHomes** for **student** houses and flats
with **5 bedrooms** and **at least 2 bathrooms**, within about a **25-minute walk of Senate House**.
Only places for the **2027/28 year** count (available from June 2027, or listed
as 2027/28). It keeps anything at or under **£210 per person per week** (£225 if bills are
included) and **emails you** each new one with a link. It runs on GitHub's
computers, so your laptop can be off.

## Changing things

- **Budget, bedrooms, walking distance, areas:** edit `config.toml`, then upload it
  (or ask Claude to).
- **Email details:** GitHub repo → Settings → Secrets and variables → Actions
  (`SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_TO`).
- **Pause it:** GitHub repo → Actions → House hunter → "..." → Disable workflow.
- **Run a check now:** GitHub repo → Actions → House hunter → Run workflow.

## Requesting viewings

Double-click **Open Viewing Page.bat** on your laptop. The page opens in your
browser and runs only while its small window is open, so close the window when
you're done.

1. **Tick** the properties you want. Ticks do nothing by themselves.
2. Press **Submit**. You'll see exactly who gets emailed and what it says.
3. Press **Send**, or **Go back** to change your mind.

- **Remove** hides a property. It stays under "Removed" so you can put it back.
- **Add a property you found yourself** takes a link from any site. Agents in your
  address book are filled in. Otherwise type the email address yourself.
- It starts in **test mode**, where everything goes to your own inbox. Going live is a
  button under "Your details", and there's a limit of 5 real requests a day.
- Requests come from your Gmail, with replies going to your inbox.
- Agent addresses are in `agents.toml`. Your details and history stay on this laptop in
  `viewing_details.json` and `viewing_state.json`, and are never uploaded to GitHub.
- If emails fail, double-click **Set Up Email.bat** and enter a new Gmail app password.

## Good to know

- You're only emailed about each place once. If nothing new appears, there's no email.
- If an email fails to send, those listings are saved and sent with the next one.
- If a site stops working for about 2 hours, you get one email saying so.
- `matches.html` lists every match found so far. `seen.json` is its memory, so
  don't delete it unless you want to be re-sent everything.
- OpenRent is switched off: it has no student-let category and blocks GitHub.
  Zoopla blocks automated access, so set up Zoopla's own email alert if you want it.
- Prices are converted to per person per week: monthly rent × 12 ÷ 52 ÷ bedrooms.
  Walking times are estimates from straight-line distance, adjusted for roads and hills.
- GitHub pauses scheduled workflows in repositories with no activity for 60
  days. The hunter's own updates count as activity, and GitHub emails you
  before pausing, so you can re-enable it with one click.
- These sites' terms discourage automated access, so keep this for personal use.

## Running on your own computer instead

Don't run both at once, or you'll get every email twice.

| Command | What it does |
|---|---|
| `python setup_email.py` | Save your email details to `.env` and send a test |
| `python house_hunter.py` | One check |
| `python house_hunter.py --loop` | Keep checking forever |
| `python house_hunter.py --dry-run` | One check, print emails instead of sending |
| `powershell -ExecutionPolicy Bypass -File setup_autostart.ps1` | Start it in the background at every login |
