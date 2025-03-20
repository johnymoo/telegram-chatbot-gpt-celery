import os
import time
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
import telebot
from celery import Celery, chain
import requests
from requests.exceptions import RequestException
import humanize
import pytz
from datetime import datetime
import arxiv
from pyzotero import zotero
import requests
import json
import hashlib
import logging  # Import the logging module

load_dotenv()

import logging
import sys

# Configure logging to output to stdout
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# Debug: Print environment variables
#print("Environment variables:")
#print(f"PDF_PATH: {os.getenv('PDF_PATH')}")
#print(f"ZOTERO_LIBRARY_ID: {os.getenv('ZOTERO_LIBRARY_ID')}")
#print(f"ZOTERO_API_KEY: {os.getenv('ZOTERO_API_KEY')}")
#print(f"TIMEZONE: {os.getenv('TIMEZONE')}")

# Initialize Zotero client
try:
    zot = zotero.Zotero(
        library_id=os.getenv('ZOTERO_LIBRARY_ID'),
        library_type='user',
        api_key=os.getenv('ZOTERO_API_KEY')
    )
    logger.info("Successfully initialized Zotero client")
except Exception as e:
    logger.error(f"Error initializing Zotero client: {str(e)}")

app = Celery('chatbot', broker=os.getenv('CELERY_BROKER_URL'))

bandwagon_url = os.getenv('BANDWAGON_URL')
bandwagon_params = {
    'veid': os.getenv('BANDWAGON_VEID'),
    'api_key': os.getenv('BANDWAGON_API_TOKEN')
}

jms_url = os.getenv('JMS_URL')
jms_params = {
    'service': os.getenv('JMS_SERVICE'),
    'id': os.getenv('JMS_ID')
}

def is_running_in_docker():
    """
    Detect if the application is running inside a Docker container.
    Returns True if running in Docker, False otherwise.
    """
    # Method 1: Check for .dockerenv file
    if Path('/.dockerenv').exists():
        return True

pdf_path = Path(os.getenv('PDF_PATH', ''))
if is_running_in_docker():
    pdf_path = Path('/pdf') # for docker use

openapi_key = os.getenv('OPEN_API_KEY')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
client = OpenAI(api_key=openapi_key)

# Store the last 10 conversations for each user
conversations = {}
# dict to store chat model parameters
chat_params = {
    'model': 'gpt-3.5-turbo',
    'temperature': 0.7,
    'max_tokens': 1024,
    'top_p': 1,
    'frequency_penalty': 0,
    'presence_penalty': 0     
}


SYSTEM_PROMPT = os.getenv('SYSTEM_PROMPT')



def conversation_tracking(text_message, user_id):
    """
    Make remember all the conversation
    :param user_id: telegram user id
    :param text_message: text message
    :return: str
    """
    # Get the last 10 conversations and responses for this user
    user_conversations = conversations.get(user_id, {'conversations': [], 'responses': []})
    user_messages = user_conversations['conversations'][-9:] + [text_message]
    user_responses = user_conversations['responses'][-9:]

    # Store the updated conversations and responses for this user
    conversations[user_id] = {'conversations': user_messages, 'responses': user_responses}

    # Construct the full conversation history in the user:assistant, " format
    conversation_history = []

    for i in range(min(len(user_messages), len(user_responses))):
        conversation_history.append({
            "role": "user", "content": user_messages[i]
        })
        conversation_history.append({
            "role": "assistant", "content": user_responses[i]
        })

    # Add last prompt
    conversation_history.append({
        "role": "user", "content": text_message
    })
    # Generate response
    task = generate_response_chat.apply_async(args=[conversation_history])
    response = task.get()

    # Add the response to the user's responses
    user_responses.append(response)

    # Store the updated conversations and responses for this user
    conversations[user_id] = {'conversations': user_messages, 'responses': user_responses}

    return response


@app.task
def generate_image(prompt, number=1):
    response = client.images.generate(
        prompt=prompt,
        n=number,
        model = "dall-e-3",
        size="1024x1024",
        quality="standard"
    )
    image_url = response.data[0].url
    return image_url

@bot.message_handler(commands=["create", "image"])
def handle_image(message):
#    space_markup = '                                                                                  '
#    image_footer = '[Website](https://deadlyai.com)'
    caption = f"Powered by Dall-E" 

    #number = message.text[7:10]
    if message.text.startswith("/image"):
        prompt = message.text.replace("/image", "").strip()
    else:
        prompt = message.text.replace("/create", "").strip()
    logger.info(f"message= {message.text}")
    logger.info(f"prompt = {prompt}")
    numbers = 1 # Dall-E-3 api only support number = 1
    task = generate_image.apply_async(args=[prompt, numbers])
    image_url = task.get()
    if image_url is not None:
        logger.info(f"chat_id= {message.chat.id} \nphoto = {image_url}\n " +
                f"caption = {caption}")
        bot.send_photo(chat_id=message.chat.id, photo=image_url, reply_to_message_id=message.message_id,
                        caption=prompt, parse_mode='Markdown')
    else:
        bot.reply_to(message, "Could not generate image, try again later.")



@app.task
def generate_response_chat(message_list):
    completion = client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": "You are an AI named Javis and you are in a conversation with a human. You can answer questions, "
                "provide information as accurate as possible, and help with a wide variety of tasks." 
            },
        ] + message_list,
        model="gpt-3.5-turbo",
        temperature=0.7,
        max_tokens=1024,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0    
    )
    return completion.choices[0].message.content

@app.task
def get_jms_data_usage(data):
    servicename = 'JMS'
    used_bw = data['bw_counter_b']
    total_bw = data['monthly_bw_limit_b']
    date_next_reset = data['bw_reset_day_of_month']
    date_next_reset_str = f"Date Next Reset: {date_next_reset}"

    used_bw_pct = used_bw / total_bw
    used_bw_pct_str = f"{used_bw_pct:.0%}"

    # convert to human readable format
    used_bw_str = f"{humanize.naturalsize(used_bw)}"
    #print(f"{used_bw_str}")
    total_bw_str = f"{humanize.naturalsize(total_bw)}"
 
    return servicename + "\n" + used_bw_str + "/" + total_bw_str +", " + used_bw_pct_str + "\n" + date_next_reset_str

@app.task
def get_bandwagon_data_usage(data):
    hostname = data['hostname']
    hostname_str = f"{hostname}"
    
    used_bw = data['data_counter']
    total_bw = data['plan_monthly_data'] * data['monthly_data_multiplier']
    date_next_reset = data['data_next_reset']

    used_bw_pct = used_bw / total_bw
    used_bw_pct_str = f"{used_bw_pct:.0%}"

    # convert to human readable format
    used_bw_str = f"{humanize.naturalsize(used_bw, True)}"
    #print(f"{used_bw_str}")
    total_bw_str = f"{humanize.naturalsize(total_bw, True)}"
    #print(f"{total_bw_str}")

    tz = pytz.timezone(os.getenv("TIMEZONE"))
    dt_utc = datetime.utcfromtimestamp(date_next_reset)
    dt_local = dt_utc.replace(tzinfo=pytz.utc).astimezone(tz)
    dt_local_str = f'Date Next Reset: {dt_local.strftime("%d %B, %Y, %H:%M")}'
    
    #print(f'{dt_local_str}')

    return hostname_str + "\n" + used_bw_str + "/" + total_bw_str +", " + used_bw_pct_str + "\n" + dt_local_str

@app.task
def call_rest_api_usage(url, params):
    """helper function to call rest api 

    Args:
        url (str): urlof the rest api
        params (args): parameters for the rest api

    Returns:
        _type_: _description_
    """
    try:
        with requests.get(url, params=params) as response:
            if response.status_code == 200:
                if 'application/json' in response.headers.get('Content-Type'):
                    data = response.json()
                    #print(data)
                else:
                    print(response.text)
                return response.json()
    except RequestException as e:
        logger.error(f"An error occured: {e}")
        response.close()

@app.task
def call_download_arxiv_pdf(paperID, dir):
    """_summary_
    task: download the pdf of the arXiv paper

    Args:
        paperID (str): e.g. 2403.03186
        dir (str): path or Path object for the directory
    """
    try:
        dir_path = Path(dir)
        logger.info(f'Paper ID: {paperID} \n Directory: {dir_path}')
        paper = next(arxiv.Client().results(arxiv.Search(id_list=[paperID])))
        #print(f"Summary: {paper.summary}")
        filename = dir_path / f"{paperID}.pdf"

        # generate summary file
        summary_file = dir_path / f"{paperID}_info.txt"
        info_str = ''
        # skip if the file already exists
        if not summary_file.exists():
            with open(summary_file, 'w', encoding='utf-8') as file:
                info_str += 'title, ' + paper.title + '\n'
                info_str += 'url, ' + paper.pdf_url + '\n'
                # Join authors with commas and add trailing newline
                authors = ', '.join(str(author) for author in paper.authors)
                info_str += 'author, ' + authors + '\n'
                info_str += 'summary, ' + paper.summary
                logger.info(info_str)
                file.write(info_str)

        # start download pdf
        paper.download_pdf(filename=str(filename))
        return f"Paper downloaded: {filename} \n {info_str}"

    except Exception as e:
        result = f"Error downloading arXiv PDF: {e}"
        logger.error(result)
        return result


@bot.message_handler(commands=["start", "help"])
def start(message):
    if message.text.startswith("/help"):
        bot.reply_to(message, "/image to generate image animation\n/create generate image\n/paper {paperID} - Download arXiv paper and upload to Zotero\n/clear - Clears old "
                              "conversations\nsend text to get replay\nsend voice to do voice"
                              "conversation")
    else:
        bot.reply_to(message, "Just start chatting to the AI or enter /help for other commands")


@bot.message_handler(commands=["model", "temperature", "maxtokens"])
def update_model(message):
    """Update model parameters"""
    bot.reply_to(message, "Model update not implemented")

@bot.message_handler(commands=['vps'])
def get_vps_data_usage(message):
    """
    retrieve vps data usage
    """
    #print(f"url = {bandwagon_url}", f"params = {bandwagon_params}")
    bwg_rlt = call_rest_api_usage.delay(bandwagon_url, bandwagon_params) 

    jms_rlt = call_rest_api_usage.delay(jms_url, jms_params)
    
    #print(f"{result.get()}")
    bot.reply_to(message, get_bandwagon_data_usage(bwg_rlt.get()) + '\n\n' +
                 get_jms_data_usage(jms_rlt.get()))

@bot.message_handler(commands=['paper'])
def dl_arxiv(message):
    """
    download pdf from Arxiv by link
    Args:
        message (_type_): _description_
    """
    reply = ""
    if message.text.startswith("/paper"):
        paperID = message.text.replace("/paper", "").strip()
        if len(paperID) == 0:
            bot.reply_to(message, 'Usage: /paper {paperID} (e.g. 2403.03186)')
        print(f"paperID = {paperID}")
        summary_file = pdf_path / f"{paperID}_info.txt"

        info_str = ''
        # skip if the file already exists
        if summary_file.exists():
            print(f"{summary_file} exists")
            with open(summary_file, 'r', encoding='utf-8') as file:
                info_str = file.read()
                print(info_str)
            reply = info_str
        else:
            logger.info(f"start downloading arXiv PDF: {paperID} {pdf_path}")
            rlt = call_download_arxiv_pdf.delay(paperID, dir=str(pdf_path))
            reply = rlt.get()
        
    bot.reply_to(message, reply)
        
    # After successful download, try to upload to Zotero
    # if reply.startswith("Paper downloaded:"):
    #     upload_result = upload_pdf_zotero.delay(paperID)
    #     bot.reply_to(message, upload_result.get())

@app.task
def test_upload_zotero(paper_id):
    pdf_path = Path("/mnt/books/Books/GPT") / "2311.02883.pdf"
    response = zot.attachment_simple([str(pdf_path)], "K93PPGZ7")
    #response = zot.attachment_both([pdffile], "K93PPGZ7")
    logger.info(response)

@app.task
def upload_pdf_zotero(paper_id):
    """Upload a PDF file to Zotero library
    
    Args:
        paper_id (str): arXiv paper ID (e.g. 2403.03186)
    
    Returns:
        str: Success/failure message
    """
    try:
        # Check if PDF exists
        pdf_file = pdf_path / f"{paper_id}.pdf"
        if not pdf_file.exists():
            logger.error(f"Error: PDF file not found at {pdf_file}")
            return f"Error: PDF file not found at {pdf_file}"

        # Get paper metadata from info file
        info_file = pdf_path / f"{paper_id}_info.txt"
        if not info_file.exists():
            return f"Error: Paper info file not found at {info_file}"
            
        # Read and parse metadata
        with open(info_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Parse metadata with fixed order: title, url, author, summary
        lines = content.split('\n')

        # First three lines are title, url, author
        title_key, title_value = lines[0].split(',', 1)
        url_key, url_value = lines[1].split(',', 1)
        author_key, author_value = lines[2].split(',', 1)

        metadata = {
            title_key.strip(): title_value.strip(),
            url_key.strip(): url_value.strip(),
            author_key.strip(): author_value.strip(),
        }

        # Everything after the third line is the summary
        summary_key, summary_first_line = lines[3].split(',', 1)
        metadata[summary_key.strip()] = '\n'.join([summary_first_line] + lines[4:]).strip()

        logger.info("Parsed metadata:")
        for key, value in metadata.items():
            logger.info(f"{key}: {value[:50]}...")

        logger.info("Final metadata:", metadata)

        # Verify required metadata fields
        required_fields = ['title', 'summary', 'url', 'author']
        for field in required_fields:
            if field not in metadata:
                raise Exception(f"Missing required metadata field: {field}")

        # Create Zotero item
        logger.info("Creating Zotero item template")
        template = zot.item_template('journalArticle')
        template['title'] = metadata.get('title', '')
        template['abstractNote'] = metadata.get('summary', '')
        template['url'] = metadata.get('url', '')
        # Parse authors and split into firstName/lastName
        authors = metadata['author'].strip().rstrip(',').split(',')
        template['creators'] = []
        for author in authors:
            if author.strip():
                # Split name into parts
                name_parts = author.strip().split()
                if len(name_parts) > 1:
                    template['creators'].append({
                        'creatorType': 'author',
                        'firstName': ' '.join(name_parts[:-1]),
                        'lastName': name_parts[-1]
                    })
                else:
                    template['creators'].append({
                        'creatorType': 'author',
                        'firstName': '',
                        'lastName': name_parts[0]
                    })
        logger.info(f"Authors parsed: {template['creators']}")

        logger.info("Uploading metadata to Zotero")
       # Upload item metadata first
        item = zot.create_items([template])
        logger.info(item)
        if not item or not item["success"]:
            raise Exception("Failed to create Zotero item")

        item = item["success"]
        logger.info(f"item created: {item['0']}")
        # # Then attach PDF
        #print(f"Attaching PDF: {pdf_file}")
        pdf_files = [pdf_file]
        logger.info(f"Attaching PDF: {pdf_files}")
        # response = zot.attachment_simple(
        #         [str(pdf_file)],
        #         item["0"]
        #     )
        test_pdf_path = Path("/mnt/books/Books/GPT") / "2311.02883.pdf"
        response = zot.attachment_simple([str(test_pdf_path)], "K93PPGZ7")
        # # with open(pdf_file, 'rb') as pdf:
        #     zot.attachment_simple(
        #         pdf,
        #         item,
        #         filename=f"{paper_id}.pdf"
        #     )
        logger.info(response)
        if response and 'successful' in response:
            logger.info("PDF uploaded successfully as a standalone item!")
        else:
            logger.info("Failed to upload PDF:", response)
        #print(f"Successfully uploaded to Zotero: {paper_id}")
        return f"Successfully uploaded {paper_id} to Zotero"

    except Exception as e:
        return f"Error uploading to Zotero: {str(e)}"

def upload_pdf_to_zotero(pdf_path_str, collection_key=None):
    """
    Uploads a PDF file to Zotero using the Zotero API.

    Args:
        pdf_path_str (str): Path to the PDF file.
        collection_key (str, optional): Key of the Zotero collection to upload to. Defaults to None (My Library).

    Returns:
        dict: The response from the Zotero API, or None if an error occurred.
    """
    api_key = os.getenv('ZOTERO_API_KEY')
    user_id = os.getenv('ZOTERO_LIBRARY_ID')
    try:
        pdf_path = Path(pdf_path_str)
        with open(pdf_path, 'rb') as pdf_file:
            pdf_data = pdf_file.read()

        filename = pdf_path.name
        filesize = len(pdf_data)
        filehash = hashlib.sha1(pdf_data).hexdigest()

        headers = {
            'Zotero-API-Key': api_key,
            'Zotero-API-Version': '3',
            'Content-Type': 'application/json',
        }

        url = f'https://api.zotero.org/users/{user_id}/items'

        if collection_key:
            url = f'https://api.zotero.org/collections/{collection_key}/items'

        # First, create an item with file metadata
        item_data = {
            'itemType': 'attachment',
            'linkMode': 'imported_file',
            'filename': filename,
            "contentType": "application/pdf",
        }

        response = requests.post(url, headers=headers, json=[item_data]) #send as a list
        response.raise_for_status()

        response_json = response.json()
        if not response_json:
            print("Error: No JSON response from Zotero API during item creation.")
            return None
        if not isinstance(response_json, list) or not response_json: # check if response is a list and not empty
            print(f"Error: unexpected response structure: {response_json}")
            return None

        upload_url = response_json[0]['data']['url']
        upload_auth = response_json[0]['data']['authorization']

        # Second, upload the file to the provided URL
        upload_headers = {
            'Authorization': upload_auth,
            'Content-Type': 'application/pdf',
            'Content-Disposition': f'attachment; filename="{filename}"',
        }

        upload_response = requests.put(upload_url, headers=upload_headers, data=pdf_data)
        upload_response.raise_for_status()

        # Third, confirm the upload
        confirm_url = f'https://api.zotero.org/users/{user_id}/items/{response_json[0]["data"]["key"]}'
        confirm_headers = {
            'Zotero-API-Key': api_key,
            'Zotero-API-Version': '3',
            'If-Match': response.headers['ETag'],
        }

        confirm_data = {
            "itemType": "attachment",
            "linkMode": "imported_file",
            "filename": filename,
            "filesize": filesize,
            "filehash": filehash,
            "contentType": "application/pdf"

        }

        confirm_response = requests.patch(confirm_url, headers=confirm_headers, json=confirm_data)
        confirm_response.raise_for_status()

        return confirm_response.json()

    except requests.exceptions.RequestException as e:
        print(f"Error uploading PDF: {e}")
        if 'response' in locals() and response is not None:
            print(f"Response Content: {response.content}")
        return None
    except FileNotFoundError:
        print(f"Error: PDF file not found at {pdf_path}")
        return None
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON response from Zotero API. Response: {response.text}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None
        

@bot.message_handler(func=lambda message: True)
def echo_message(message):
    """ echo back the message to the user

    Args:
        message (str): input message from the user
    """
    user_id = message.chat.id

    # Handle /clear command
    if message.text == '/clear':
        conversations[user_id] = {'conversations': [], 'responses': []}
        bot.reply_to(message, "Conversations and responses cleared!")
        return

    response = conversation_tracking(message.text, user_id)

    # Reply to message
    bot.reply_to(message, response)


if __name__ == "__main__":
    while True:
        try:
            logger.info("start polling telegram bot..")
            bot.polling(non_stop=True, interval=1)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received. Exiting...")
            break
        except Exception as e:
            print(e)
            time.sleep(5)
            continue
        finally:
            logger.info("polling exited")
