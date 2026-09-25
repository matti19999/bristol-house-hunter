# Bristol House Hunter

Every 10 minutes, GitHub checks **Rightmove** (student lets only),
**AccommodationForStudents** and **UniHomes** for **student** houses and flats
with **2, 3 or 4 bedrooms**, within about a **25-minute walk of Senate House**.
It keeps anything at or under **£185 per person per week** (£200 if bills are
included) and **emails you** each new one with a link. It runs on GitHub's
computers, so your laptop can be off.

## Changing things

- **Budget, bedrooms, walking distance, areas:** edit `config.toml`, then upload it
  (or ask Claude to).
- **Email details:** GitHub repo → Settings → Secrets and variables → Actions
  (`SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_TO`).
- **Pause it:** GitHub repo → Actions → House hunter → "..." → Disable workflow.
- **Run a check now:** GitHub repo → Actions → House hunter → Run workflow.

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
