# Deploy Product Hunter as a Web App

The application is already browser-based. Hosting it gives you one URL that can be opened from a work computer without installing Python.

## Before deploying

You need:

1. A GitHub account.
2. A SerpApi key for Google Shopping, Google Lens, and Google Maps results.
3. An OpenAI API key only if you want local image uploads recognized.
4. A strong app password so other people cannot consume your API keys.

Never commit `.env` or `.streamlit/secrets.toml`. They are ignored by Git in this package.

## Recommended: Streamlit Community Cloud

### 1. Put the project in GitHub

1. Create a new GitHub repository, preferably private.
2. Unzip this package.
3. Upload the files inside the folder so `app.py` is at the repository root.
4. Commit the files.

### 2. Create the hosted app

1. Sign in to Streamlit Community Cloud and choose **Create app**.
2. Select the GitHub repository and branch.
3. Set the entrypoint to `app.py`.
4. Open **Advanced settings** and paste the secrets block below.
5. Replace all placeholder values and deploy.

```toml
SERPAPI_API_KEY = "your-real-serpapi-key"
OPENAI_API_KEY = "your-real-openai-project-key"
APP_PASSWORD = "a-long-private-passphrase"

OPENAI_MODEL = "gpt-4.1-mini"
DEFAULT_LOCATION = "Los Angeles, CA"
COUNTRY_CODE = "us"
LANGUAGE = "en"

ALLOW_USER_API_KEYS = false
ALLOW_PUBLIC_WITH_SERVER_KEYS = false
MAX_UPLOAD_MB = 10
MAX_INPUTS = 12
MAX_SEARCH_JOBS = 24
```

After deployment, Streamlit provides a `streamlit.app` URL. Keep the app private in Streamlit sharing settings when practical, and keep `APP_PASSWORD` configured as an additional safeguard.

## Alternative: Render

The package includes `Dockerfile` and `render.yaml`.

1. Put the project in a GitHub repository.
2. In Render, create a new Blueprint and connect the repository.
3. Render reads `render.yaml` and prompts for the three values marked `sync: false`:
   - `SERPAPI_API_KEY`
   - `OPENAI_API_KEY`
   - `APP_PASSWORD`
4. Complete the deployment and open the assigned `onrender.com` URL.

The included health-check path is `/_stcore/health`. Render can also use a custom domain if your workplace blocks shared hosting domains.

## Security behavior

- Server API keys are never prefilled into browser text boxes.
- When server keys exist, the app uses them only if `APP_PASSWORD` is configured or `ALLOW_PUBLIC_WITH_SERVER_KEYS=true` is explicitly set.
- `ALLOW_USER_API_KEYS=false` prevents users from entering alternate keys in the browser.
- Uploaded images are validated, resized, converted to JPEG, and re-encoded without EXIF metadata before being sent for recognition.
- Excel files are generated in memory, which avoids shared output files between users.
- Text from web results is escaped before Excel export to reduce spreadsheet formula-injection risk.

The built-in password is a practical shared-access gate, not enterprise identity management. For a company-wide deployment, put the app behind your organization's approved authentication or reverse proxy.

## Work-computer considerations

The work computer only needs a modern browser and permission to access the hosted domain. The app sends product images to OpenAI and search requests to SerpApi, so confirm that using those external services is permitted by your employer before uploading company-confidential material.
