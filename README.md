# Holo Binder

A personal Pokémon TCG collection tracker (English and Japanese), with Cardmarket prices and price history.

Card data and images come from [TCGdex](https://tcgdex.dev). Daily prices come from Cardmarket's public price guide.

## Files

| File | What it does |
|---|---|
| `index.html` | The whole app. |
| `.github/workflows/prices.yml` | Runs every day at 07:23 UTC and saves Cardmarket prices for the cards you track. |
| `scripts/update_prices.py` | Downloads the Cardmarket price guide and appends one row per tracked card to `history.json`. |
| `collection.json` | Your cards. The app writes this file, so don't edit it by hand. |
| `history.json` | Daily prices. The Action writes this file. |

## Setup (about 10 minutes)

1. **Create the repo.** On GitHub, create a new repository, for example `holo-binder`. It must be public for free GitHub Pages.
2. **Upload the files.** Upload `index.html`, the `scripts` folder and the `.github` folder, keeping the folder structure.
3. **Turn on the website.** In the repo, go to Settings → Pages, choose "Deploy from a branch", then `main` and `/ (root)`. After a minute your app is live at `https://<you>.github.io/holo-binder/`.
4. **Let the Action save prices.** Go to Settings → Actions → General → Workflow permissions and choose "Read and write permissions".
5. **Create a token for the app.** Go to GitHub → Settings → Developer settings → Fine-grained tokens → Generate new token.
   - Repository access: only this repo.
   - Permissions: Contents, Read and write.
6. **Connect the app.** Open the app on your phone, go to the Value tab, then Daily price tracking. Enter `owner/holo-binder` and the token.
7. **Get your first prices now (optional).** In the repo, go to Actions → Daily Cardmarket prices → Run workflow.

On iPhone, open the app in Safari and choose Share → Add to Home Screen.

## Notes

- **Your data is public.** The repo is public, so `collection.json` (which cards you own and want) can be seen by anyone who finds it. The token is stored only on your phone and is never committed.
- **What gets tracked.** Only cards that Cardmarket lists are tracked. Many Japanese cards have no Cardmarket ID. The Value tab shows how many of your cards are tracked.
- **Two price sources.** The app still saves a price whenever you open it. The Action fills in the days you don't open it, and the app merges both into the charts.
- **Several phones.** If you edit on two phones, the most recent change wins.
