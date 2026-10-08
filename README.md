# Instagram Request Manager

A Python command-line tool that reads pending follow requests from an Instagram HTML export and cancels them through a visible Playwright browser session.

Built as a practical browser automation project with resumable processing, structured error logs, account validation, and English/Turkish interface matching.

## Features

- Parses and validates usernames using Python's standard-library HTML parser.
- Removes duplicate usernames while preserving input order.
- Previews profile URLs with `--dry-run`, without opening a browser.
- Uses manual login in a persistent Chromium session.
- Saves progress atomically and resumes completed profiles.
- Records per-profile errors as JSON Lines and supports explicit retries.
- Stops on login challenges, security warnings, or HTTP 429 responses.
- Supports configurable delays and batch breaks.

## Requirements and setup

Python 3.10 or newer.

```sh
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Usage

Preview the included synthetic example:

```sh
python cancel_pending_requests.py examples/pending_requests.html --dry-run
```

Expected profile URLs:

```text
https://www.instagram.com/demo_account_one/
https://www.instagram.com/demo_account_two/
```

Use your own exported `pending_follow_requests.html` file:

```sh
python cancel_pending_requests.py "path/to/pending_follow_requests.html" --dry-run
python cancel_pending_requests.py "path/to/pending_follow_requests.html" --delay 5 --batch-size 10 --break-seconds 30
```

The second command opens Chromium. Log in to your own account manually, close notification dialogs, and press Enter in the terminal. This command performs actual cancellations. Ctrl+C stops processing; saved results are reused on the next run. Use `--retry-errors` to retry failed profiles.

| Option | Default | Purpose |
| --- | --- | --- |
| `html` | `pending_follow_requests.html` beside the script | Input HTML export |
| `--dry-run` | Off | Print URLs only |
| `--delay` | 5 | Seconds between profiles; minimum 1 |
| `--batch-size` | 10 | Profiles between batch breaks |
| `--break-seconds` | 30 | Batch break duration; 0 disables the extra break |
| `--retry-errors` | Off | Include previously failed profiles |

## Input format

The parser expects table rows containing exactly two cells: `Username` (or `Kullanıcı adı`) and a username. Other export layouts are not currently supported. The example contains invented usernames, not personal export data.

## Architecture

`UsernameParser` extracts input. `cancel_one` handles profile navigation and cancellation. `guard` detects session restrictions. `process_profile` records results and errors. `save_state` writes progress through a temporary file before replacing the previous state.

Runtime files are stored beside the script: `.instagram_browser/`, `cancel_requests_progress.json`, and `cancel_requests_errors.jsonl`. The progress file is bound to the logged-in account. Keep these files private. Git ignores session files, logs, and personal exports. The diagnostic helper is available in the source but is not called automatically.

## Tests

```sh
python -m unittest discover -s tests -v
```

Tests run offline and cover HTML parsing, username validation, deduplication, resumable selection, state persistence, and error handling. GitHub Actions runs the same suite on Python 3.10 through 3.13. Tests do not verify Instagram's live interface.

## Limitations and responsible use

This is an independent project and is not affiliated with Instagram or Meta. Use only with your own account and in accordance with the platform's rules. Interface changes can break label matching. Profile-state detection currently examines visible page buttons, so suggested accounts can affect classification. Delays do not guarantee protection from platform restrictions. Review the preview before running a live session.

## Portfolio summary

Developed a Python/Playwright CLI for processing Instagram HTML exports, with validated input, resumable state, account-bound sessions, structured error logging, and automated offline tests.

## Türkçe kısa kullanım

Instagram dışa aktarımındaki bekleyen takip isteklerini okuyup görünür tarayıcı üzerinden iptal eder. Önce `--dry-run` ile listeyi kontrol edin. Gerçek çalıştırmada kendi hesabınıza manuel giriş yapın. İlerleme kaydedilir; hatalı profiller `--retry-errors` ile yeniden denenebilir. Kişisel dışa aktarım dosyalarını ve tarayıcı oturumunu GitHub'a yüklemeyin.

