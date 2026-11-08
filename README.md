 # FSSAI Label Audit web app

## What goes in the folder
`skills/fssai-label-audit/` holds the skill files (00_SKILL.md to 05_templates.md and 06_reference_data.xlsx). 07_report_builder.py may stay there but the app does not use it. Only this folder and the app code go into the repository. Do not add client label PDFs or any other client folders. Keep the repository PRIVATE.

## Test on your own PC (Windows PowerShell)
```
pip install -r requirements.txt
$env:ANTHROPIC_API_KEY="your_key"
$env:APP_USERS="admin:Test12345"
$env:ADMIN_USERS="admin"
streamlit run app.py
```ssssssssssss
If "streamlit is not recognized", use `python -m streamlit run app.py`. These settings last only for that terminal window. The app does not read a .env file by itself.

## Deploy online (Render)
1. Create a private GitHub repository and push this folder (GitHub Desktop works).
2. On render.com: New > Web Service > select the repository.
3. Build command: `pip install -r requirements.txt`
4. Start command: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true`
5. Under Environment add: `ANTHROPIC_API_KEY`, `APP_USERS`, `ADMIN_USERS`, `PYTHON_VERSION=3.12.4`
6. Deploy. Render gives a link; everyone logs in there.

## Notes
- Never put the API key in the repository or the zip.
- Admin users see the skill file sizes and approximate token count in the sidebar. If the count exceeds the limit, put the large file names in `EXCLUDE_FILES`.
- To change users, edit `APP_USERS` in Render. It redeploys.