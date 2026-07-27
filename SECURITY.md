# Security notes

## Protected information

Never commit API keys, app passwords, or other credentials. Store them in the hosting provider's secret manager or local environment variables.

## Browser and backend separation

All OpenAI and SerpApi requests originate from the Streamlit server. The application does not intentionally place server API keys in HTML or JavaScript sent to the browser.

## Uploaded images

Local uploads are limited by size, decoded with Pillow, oriented, resized to at most 2048 by 2048 pixels, flattened, converted to JPEG, and saved without EXIF metadata before being sent for product recognition.

## Excel export

Search results and user-supplied text are sanitized before they are written into the workbook so cells beginning with spreadsheet formula characters are treated as text.

## Persistence

The web workflow builds the workbook in memory. The app does not include a database and does not intentionally retain searches or uploaded files after the session ends. Hosting providers may retain infrastructure logs according to their own policies.

## Authentication

`APP_PASSWORD` provides a simple shared gate. It is not a substitute for enterprise identity, audit logs, role-based access controls, or SSO.
