# Telegram Chatbot with GPT-3 and Celery
This repository contains an example of a Telegram chatbot integrated with OpenAI's GPT-3 and Celery for task queue management. The chatbot can respond to messages, store the last 10 conversations for each user, and efficiently process messages using Celery.

## Requirements

- Python 3.6 or higher
- Redis
- OpenAI API Key
- Telegram Bot Token

## Usage

- Clone the repository:
   ```
  git clone https://github.com/shamspias/telegram-chatbot-gpt3-celery.git
  ```
- Create a virtual environment and activate it:
    ```
    python3 -m venv env
    source env/bin/activate
    ```
- Install the dependencies:
    ```
    pip install -r requirements.txt
    ```
- Set the following environment variables:
   - `TELEGRAM_BOT_TOKEN`: Your Telegram Bot Token
   - `OPENAI_API_KEY`: Your OpenAI API Key

- Build the Docker image:
    ```
    docker build -t telegram-chatbot-celery .
    ```

- Start the Docker container:
    ```
    docker-compose up -d
    ```

- Start a conversation with your Telegram bot!


## DALL-E-2

- You can generate image now just type
   ```
  /image number your prompt
  example: /image 2 cats walking in space
  ```

## Zotero Integration

The project includes a Zotero client that supports PDF file uploads. To use the Zotero functionality:

1. Get your Zotero API key from https://www.zotero.org/settings/keys
2. Get your userID from https://www.zotero.org/settings/keys (shown at the top of the page)
3. Set the following environment variables:
   - `ZOTERO_API_KEY`: Your Zotero API key
   - `ZOTERO_USER_ID`: Your Zotero user ID

Example usage of the Zotero client:

```python
from zotero_client import ZoteroClient

# Initialize the client
client = ZoteroClient(
    api_key='your_api_key',
    library_type='user',  # or 'group' for group libraries
    library_id='your_user_id'
)

# Upload a PDF file
response = client.upload_pdf('path/to/your/file.pdf')

# Upload a PDF and attach it to an existing Zotero item
response = client.upload_pdf('path/to/your/file.pdf', item_key='existing_item_key')
```

The client handles:
- Getting upload authorization from Zotero
- Uploading the file to Zotero's storage service
- Registering the upload with Zotero

## Contributing

This is just a starting point and there's always room for improvement. If you have any ideas or suggestions, feel free to open an issue or submit a pull request.

## License
This project is licensed under the MIT License. See the LICENSE file for details.
