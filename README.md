# :hammer: StonkSmith

*Absolutely no day-trading.*

Forge your financial data into a single source of truth. **StonkSmith** 
scrapes, aggregates, and syncs your investment accounts into a unified 
Google Sheets Dashboard.

---

## :rocket: Overview

StonkSmith is a Python-based tool designed to:

- :eye: Scrape data from multiple investment accounts
- :jigsaw: Aggregate holdings, balances, and performance
- :chart: Sync everything into a single Google Sheets dashboard
- :brain: Provide a centralized view of your net worth

No more bouncing between your squad of applications that are meant for 
specific accounts because there isn't any current app that *just works* for 
all the accounts you own.

**ONE SHEET TO RULE THEM ALL!**

---

## :wrench: Features (Planned)

- [ ] Multi-broker support (Fidelity, Schwab, Vanguard, TSP, Ally, 529, etc.)
- [ ] Automatic data scraping / API integrations
- [ ] Google Sheets sync
- [ ] Net worth tracking over time
- [ ] Asset allocation breakdown
- [ ] CLI commands for automation
- [ ] Scheduling (cron / background jobs)

--- 

## :bricks: Project Structure (Planned)

```text
StonkSmith/
|--- README.md
|--- LICENSE
|--- .gitignore
|--- crawler/
|--- forge/
|--- sync/
|--- cli/
|--- utils/
```

---

## :wheel: Installation (Coming Soon)

```bash
git clone https://github.com/Gerrrt/stonksmith.git
cd stonksmith
pip install -r requirements.txt
```

---

## :pizza: Usage (Future)

```bash
stonksmith forge
stonksmith sync
stonksmith run
```

---

## :key: Module Credential Access

During module execution (`on_login`), credentials are available from both
`context` and `connection`:

- Active authenticated credential:
	- `context.active_username`
	- `context.active_password`
- Raw CLI-provided credential lists:
	- `context.cli_usernames`
	- `context.cli_passwords`
- Backward-compatible connection fields:
	- `connection.username`
	- `connection.password`

Example:

```python
def on_login(self, context, connection):
		user = context.active_username or connection.username
		if not user:
				context.log.fail("No authenticated user found")
				return

		context.log.success(f"Running module for {user}")
```

---

## :lock: Security Note

This project will handle sensitive financial data.

Planned safeguards:
* Environment variable-based credential storage
* No hardcoded secrets
* Optional encryption for stored data

Never commit credentials to source control.

---

## :brain: Vision

Think of StonkSmith as your own personal financial command center.

The goal is to evolve this into a modular, extensible tool that:
* Scales with your life as you gain wealth
* Supports new platforms easily
* Gives you total visibility and control

---

## :handshake: Contributing

This is currently a personal project, but contributions may open up in the 
future.

---

## :newspaper: License

MIT License

Do what you want, just give credit.

---

## :trumpet: Author

Built by someone who got tired of checking five different apps just to 
answer the simple question of:

*"How much money do I actually have?"*

---