# Bristol House Hunter

Checks **Rightmove** (plus OpenRent, AccommodationForStudents and UniHomes)
every ~10 minutes for **whole 2, 3 and 4-bed** places within about a
**25-minute walk of Senate House**. That covers Clifton, Redland, Cotham,
Kingsdown, Hotwells, Stokes Croft, Montpelier and the centre. It keeps anything
at or under **£185 per person per week** (or £200 if bills are included) and
**emails you** new ones with a link.

Everything you might want to change is in `config.toml`.

## Setup (about 10 minutes)

1. **Install the two libraries**
   ```
   pip install -r requirements.txt
   ```
2. **Set up a Gmail account to send the alerts from.** It can be your own or
   a new one made just for this.
   - Turn on 2-Step Verification (Google Account → Security).
   - Go to https://myaccount.google.com/apppasswords, create an app password
     called "House hunter", and copy the 16 letters.
3. **Copy `.env.example` to `.env`** and fill in:
   - the Gmail address,
   - the app password,
   - the address you want alerts sent to. Any inbox works, including Outlook.
4. **Test it**
   ```
   python house_hunter.py --test-email
   ```
   If the test email lands in Junk, mark it "Not junk" so later alerts don't.
5. **Start it running in the background**, including every time you log in:
   ```
   powershell -ExecutionPolicy Bypass -File setup_autostart.ps1
   ```

The first check takes about 2 minutes and emails you everything that matches
right now, cheapest first. After that you get one email per check (only when
something new appears), listing each new place with a "View listing" button.

**Tip:** to see new listings quickly, turn on notifications for that inbox in
your phone's mail app. Houses near campus go fast.

## Good to know

- **It only runs while your computer is on.** If your laptop is asleep, it
  catches up on the next check. For true 24/7 alerts, run it on an always-on
  machine (a Raspberry Pi, or a £4/month cloud server).
- **Rightmove is the main source.** The other three sites are extras. If one
  of them breaks, the rest carry on. If any site fails for about 2 hours
  straight, you get one email saying so. Details go to `hunter.log`.
- **If an email fails to send** (e.g. your Wi-Fi drops), those listings are
  saved and included in the next email that does go through. Nothing gets lost.
- **Zoopla isn't included.** It blocks automated access. Set up Zoopla's own
  instant email alert for the same search.
- **Most Bristol student houses for Sept 2027 are released between October
  and January.**
- **Prices are converted to per person per week**: monthly rent × 12 ÷ 52 ÷ bedrooms.
- **Walking times are estimates** based on straight-line distance, adjusted
  for roads and hills. UniHomes doesn't publish locations, so it's filtered by
  area name instead.
- Check frequency is deliberately modest (every ~10 min with a random delay)
  to avoid getting blocked. These sites' terms discourage automated access,
  so keep this for personal use only.

## Commands

| Command | What it does |
|---|---|
| `python house_hunter.py` | One check |
| `python house_hunter.py --loop` | Keep checking forever |
| `python house_hunter.py --dry-run` | One check, print emails instead of sending |
| `python house_hunter.py --test-email` | Send a test email |

`matches.html` lists every match found so far. To start fresh (e.g. after
changing your budget), delete `seen.json`.

To stop it running in the background:
```
powershell -Command "Unregister-ScheduledTask -TaskName 'Bristol House Hunter' -Confirm:$false"
```
