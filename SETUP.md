# GEO Outreach Bot — Setup Guide

## Step 1: GitHub Repository banao
1. github.com pe jaao → New Repository
2. Name: `geo-outreach-bot`
3. Private rakho
4. Saari files upload karo

## Step 2: Google Sheets setup
1. sheets.google.com → New Sheet banao
2. Sheet ka naam: `websites`
3. Column A mein saari website URLs daalo
4. Sheet ID copy karo URL se:
   `https://docs.google.com/spreadsheets/d/[SHEET_ID]/edit`

## Step 3: Google Service Account banao
1. console.cloud.google.com jaao
2. New Project banao
3. APIs & Services → Enable:
   - Google Sheets API
   - Google Drive API
4. Credentials → Service Account banao
5. JSON key download karo
6. Sheet mein service account email ko Editor access do

## Step 4: GitHub Secrets daalo
GitHub repo → Settings → Secrets → New secret:

| Secret Name       | Value                              |
|-------------------|------------------------------------|
| ANTHROPIC_API_KEY | sk-ant-api03-...                   |
| CAPTCHA_API_KEY   | 2captcha.com dashboard se          |
| GOOGLE_SHEET_ID   | Sheet URL se ID                    |
| GOOGLE_CREDS_JSON | Service account JSON (poora paste) |

## Step 5: 2captcha setup
1. 2captcha.com pe signup karo
2. $3-5 add karo balance
3. API key copy karo dashboard se

## Step 6: Run karo
- Automatic: har 4 ghante mein chalega
- Manual: GitHub → Actions → Run Bot → Run workflow

## Bot kya karta hai:
- Google Sheets se pending sites uthata hai
- Claude Vision se form analyze karta hai
- 2captcha se captcha solve karta hai
- Form fill aur submit karta hai
- Google Sheets mein real-time status update karta hai
