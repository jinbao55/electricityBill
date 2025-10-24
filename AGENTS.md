# Repository Guidelines

## Project Structure & Module Organization
- `main.py` holds the Flask app, scheduler, and database helpers; extend routes or jobs here to reuse the shared cache utilities.
- `templates/index.html` contains the H5 page, and `static/dist` serves bundled assets—keep chart JS and CSS in that directory.
- `deploy.sh` and `update.sh` wrap Docker Compose for service control. Copy `env.example` to per-host `.env` files and keep them ignored.

## Build, Test, and Development Commands
- `python3 -m venv .venv && source .venv/bin/activate` prepares an isolated environment; use it before installing packages.
- `pip install -r requirements.txt` aligns Flask, APScheduler, PyMySQL, and requests versions across environments.
- `python main.py` boots the dev server plus fetch job; ensure `.env` defines the database host before running.
- `./deploy.sh start|stop|restart|logs` covers routine Docker tasks, while `docker-compose up -d --build` is handy for local container debugging.

## Coding Style & Naming Conventions
- Follow PEP 8: four-space indentation, `snake_case` for functions, and UPPER_SNAKE_CASE for module constants such as `DB_CONFIG`.
- Add concise docstrings to cache helpers and scheduler jobs so their side effects stay obvious.
- Keep templates lean; favor Jinja conditionals over inline JavaScript and store shared styles in `static/dist`.

## Testing Guidelines
- No automated suite exists yet; hit endpoints manually with `curl "http://localhost:9136/data?device_id=...&period=day"` and confirm results against MySQL.
- After changing SQL or caching, run `python main.py` for one fetch cycle and watch the scheduler logs for failures.
- If you add pytest, keep tests in `tests/`, name them `test_<feature>.py`, and guard network calls behind environment checks.

## Commit & Pull Request Guidelines
- History favors concise, imperative Chinese subjects (e.g., “配置更新”); match that tone or supply a brief English equivalent.
- Group related changes, avoid committing secrets, and point out affected endpoints or scripts in the message body when behavior shifts.
- Pull requests should call out required `.env` updates, attach H5 screenshots for UI tweaks, and reference linked issues where applicable.

## Security & Configuration Tips
- Never commit real database credentials; copy `env.example` to `.env` and rely on `python-dotenv` to load them.
- Rotate `SERVER_CHAN_KEY_*` values if exposed and capture the change in deployment notes.
- Dry-run schema changes against MySQL before merging so the fetch job keeps writing to `electricity_balance` without errors.
