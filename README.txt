StrokeGPT Handy Controller

Welcome to StrokeGPT! This is a simple guide to help you set up your own private, voice-enabled AI companion for The Handy.

WINDOWS ONLY.

## What Does It Do?

* AI-Controlled Fun: Chat with an AI that controls your Handy's movements in real-time.
* Fully Customizable Persona: Change the AI's name, personality, and even their profile picture to create your perfect partner.
* Interactive Modes: Go beyond simple chat with advanced, interactive modes for Edging, Milking, and Auto-play. You can even influence the AI's patterns mid-session with chat messages!
* It Remembers You: The AI learns your preferences and remembers details from past chats.
* Internet-Connected for Control & Voice: The app requires an internet connection to send commands to The Handy's servers. If you enable voice, it also connects to the ElevenLabs API. Your AI model (Ollama) still runs 100% locally on your computer.
* Hidden Easter Eggs: A few secrets are tucked away.
* Built-in Safety: The app includes safety limiters to ensure movements always stay within your comfortable range.

## How to Get Started (easier than it looks!)

### Step 1: Install Prerequisites

You need two free programs to run the app.

**Python:**
* Download the latest version from the official Python website.
* During installation, you **must check the box** that says "Add Python to PATH."

**Ollama (The AI's "Brain"):**
* Download Ollama from the Ollama website.
* After installing, open a terminal (Command Prompt on Windows) and run the following command **once** to download the AI model:
    ```
    ollama run llama3:8b-instruct-q4_K_M

    ```
* This will take a few minutes because, much like your mum, models are chonky. Once it's finished, you can close the terminal. Make sure the Ollama application is running in the background before you start StrokeGPT.

### Step 2: Download & Install StrokeGPT

* Download the Project: Go to the project's GitHub page and click the green `<> Code` button, then select "Download ZIP".
* Unzip the file into a folder you can easily access, like your Desktop.
* Install Required Libraries:
    * Open a terminal directly in your new project folder:
    * Open the folder, click the address bar at the top, type `cmd`, and press Enter.
    * In the terminal, run this command:
        ```
        pip install -r requirements.txt

        ```

### Step 3: Run the App!

* Start the Server:
    * In the same terminal (still in your project folder), run this command:
        ```
        python app.py

        ```
    * The server is working when you see a message ending in `Running on http://127.0.0.1:5000`[cite: 88]. Keep this terminal window open.
* Open in Browser:
    * Open your web browser and go to the following address:
        http://127.0.0.1:5000
* The splash screen will appear. Press Enter to begin the on-screen setup guide. Enjoy!

### Optional: Share Your Session with Friends

Want to let someone else connect to your StrokeGPT session remotely? Run the
share helper to spin up a temporary ngrok tunnel and generate a public URL:

```
python share.py --port 5000 --pin 1234

```

* `--port` should match the port that the main app is using (default `5000`).
* `--pin` is optional, but recommended.  Everyone who opens the shared URL
  will need to enter the PIN before the interface loads.
* Set the `NGROK_AUTHTOKEN` environment variable if you have an ngrok account
  for more reliable tunnels.

The script prints both your local URL and the public share link.  Share the
public address with your friends and keep the terminal running while you play
together.

### Configuration & Secrets

You do **not** need to create a separate configuration file to run the app.
Defaults live in `config.py`, which pulls settings from environment variables,
an optional `.env` file in the project folder, and (if present) a
platform‑specific secrets file in your user configuration directory. Edit the
environment variables or `.env` entries if you want to change ports, API keys,
or default models—otherwise the included defaults will "just work."

### Development workflow

If you're modifying the project, install the requirements into a virtual
environment and run the automated test suite before pushing changes:

```
pip install -r requirements.txt
pytest
```

Running `pytest` locally ensures configuration helpers still behave as
expected and prevents regressions from slipping into the UI work.

*A Quick Note on Speed

Don't be fooled by the 0-100 scale! The Handy is a powerful device. For many people, a Max Speed setting between 10 and 25 is more than intense enough. It's highly recommended to start low and find what works for you.

* Enjoying StrokeGPT?
This app is a passion project and is completely free. If you're having fun and want to support future development, consider buying me a coffee!

https://ko-fi.com/strokegpt

TEXT-ONLY CONVERSATION FEEDBACK
-------------------------------
The main composer sends text-only chat to /api/conversation using the configured
OLLAMA_URL and OLLAMA_MODEL. It does not use the device-command chat path.
Select "Rate this reply", choose Overall, Clarity, Relevance, Tone, or Helpfulness,
add an optional note (up to 300 characters), and click a score from -5 through +5.
-5 means strongly dislike, 0 means neutral, and +5 means strongly like. No score
selected means unrated. Scores save immediately; clicking again revises that
reply's rating for the selected aspect. Other aspects are preserved.

Recent ratings and quoted replies are supplied as conversational preference
examples to subsequent text-only prompts. This is prompt context, not model
training, and it does not guarantee that every response will match a preference.

History and ratings persist in conversation.sqlite3 (override with CONVERSATION_DB).
The browser receives an HttpOnly, SameSite cookie that identifies its conversation;
keep this cookie to restore history after restarting the server. Clearing cookies
starts a new conversation. Different browsers do not share history. This is a
local browser identity, not an account login or cross-device sync. The database
contains conversation text and feedback; do not commit it to source control.
The UI restores the latest 20 turns; prompts include up to 10 prior turns and
20 recent ratings. The legacy /api/feedback route remains a separate log-only API.

Validation:
  python -m pytest -q
  node --test tests/feedback_ui.test.cjs


AUTOMATIC TEXT DISCUSSION AND CONVERSATION CONTROLS
-------------------------------------------------
Enter a topic and click Start A <-> B. A explores ideas and B questions assumptions;
both use the same configured LLM with distinct speaker instructions. They alternate
one text reply at a time. Set turns to 0 to continue until stopped (the default),
or choose 1 to 200 for a bounded run. There is a two-second pause between automatic
turns. The page must remain open; it does not resume automatically after a reload.
Stop after current reply prevents further requests while letting an in-flight reply
finish. Errors/timeouts pause the discussion without automatically retrying.
Every turn invokes the configured model; this is not two separate model instances.

To join in, type and Send. Up to five messages can wait for the next reply; queued
human messages are handled before another automatic continuation. Unanswered queued
messages are returned to the draft when you stop or a request fails. The draft is
stored locally in this browser, including queued messages, and cleared when sent
or after confirmed conversation deletion. Pause the discussion to rate a reply.

Scores have text labels, visible keyboard focus, and Left/Right/Home/End navigation;
Enter or Space submits the focused score. The rating summary lists saved aspects.
Remove this aspect's rating changes it back to unrated, rather than neutral.
Use my ratings in future replies toggles saved rating examples on or off while
keeping ordinary conversation context. Export downloads all this browser's saved
turns, speaker labels, timestamps, and ratings as versioned JSON. Delete asks for
confirmation, then deletes this browser's saved turns and ratings. Another browser's
history is unaffected, and pending model responses cannot restore deleted history.

Requests have timeouts (200 seconds for generation, 15 seconds for other operations).
A timed-out request may already have saved server-side; reload history before retrying
a send. Closing the page stops future turns, but an in-flight reply may still save.
