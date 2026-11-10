# Deploying WILDCAST INDIA (Streamlit host + Netlify front page)

Netlify only serves static websites, but WILDCAST is a Python (Streamlit) app. So:

1. **The app itself** runs on **Streamlit Community Cloud**, which is free. Render is an alternative.
2. **Netlify** hosts a small front page (`netlify_site/`) that shows the running app full-screen under your Netlify address.

It takes about 15 minutes. You need free accounts on GitHub, Streamlit Community Cloud and Netlify.

---

## Step 1 — Put the code on GitHub

1. Sign in at https://github.com and click **New repository**. Name it e.g. `wildcast-india`, choose **Public**, then **Create repository**.
2. On the new repository page, click **uploading an existing file**.
3. Open the unzipped `wildcast_india` folder (the one containing `app.py`). Select **everything inside it** and drag it into the browser.
4. Click **Commit changes**.
5. **Check that the `.streamlit` folder was uploaded.** Some systems hide folders whose names start with a dot. If you don't see `.streamlit/config.toml` in the repository:
   - Click **Add file → Create new file** and type the name `.streamlit/config.toml`.
   - Paste in the contents of that file from your computer, then commit.

   This file sets the dark theme.

Do **not** upload `data/wildcast.db` or `.env`. The database is created automatically on first start.

## Step 2 — Deploy the app on Streamlit Community Cloud

1. Go to https://share.streamlit.io and sign in with GitHub.
2. Click **Create app → Deploy a public app from GitHub**.
3. Fill in:
   - **Repository:** `your-name/wildcast-india`
   - **Branch:** `main`
   - **Main file path:** `app.py`
   - **App URL:** pick a name, e.g. `wildcast-india`
4. Open **Advanced settings**. Set **Python version** to **3.12**.
5. Optional: under **Secrets**, paste your API keys in the format shown in `.streamlit/secrets.toml.example`.
6. Click **Deploy**. The first build takes 3–5 minutes.
7. When it's done, you have an address like `https://wildcast-india.streamlit.app`. **Copy it.**

**Alternative: Render** (https://render.com). Click **New → Blueprint**, select the repository, and Render reads `render.yaml`. Your app address will end in `.onrender.com`.

## Step 3 — Publish the Netlify front page

1. Open `netlify_site/index.html` in a text editor (Notepad is fine). Find this line:
   ```js
   const APP_URL = "PASTE_YOUR_STREAMLIT_APP_URL_HERE";
   ```
   Replace the placeholder with your address from Step 2, keeping the quotes:
   ```js
   const APP_URL = "https://wildcast-india.streamlit.app";
   ```
   Save the file.
2. Go to https://app.netlify.com/drop and sign up or log in.
3. Drag the **`netlify_site` folder** onto the page. Within seconds the site is live at an address like `https://random-name-123.netlify.app`.
4. Optional: to rename it, go to **Site configuration → Change site name**, e.g. `wildcast-india.netlify.app`.
5. To update the page later, use **Deploys → drag and drop** with the edited folder.

---

## Things to know about the free hosting

* **Sleeping:** Streamlit Community Cloud puts apps to sleep after a period without visitors. The next visitor sees a **"Yes, get this app back up"** button. Click it, and it starts within about a minute. The Netlify page shows a loading message meanwhile.
* **Storage resets:** the server's storage is temporary. When the app restarts or you redeploy, these are lost:
  * uploads
  * alert acknowledgements
  * scoring-weight changes
  * fetched GBIF/iNaturalist records

  The demonstration data is regenerated identically. For permanent storage you would need an external database, which isn't included.
* **Live data:** the NASA, GBIF and iNaturalist buttons work on the hosted app, because it has internet access. Keys for FIRMS, eBird and IUCN go into the app's **Secrets**.
* **Updating the app:** edit or re-upload files in the GitHub repository. Streamlit Cloud redeploys automatically.
* **"Open full screen ↗"** on the Netlify page opens the app on its own Streamlit address.
