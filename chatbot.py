import os
import time
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

load_dotenv()
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

pdf_path = os.getenv('PDF_PATH')

openapi_key = os.getenv('OPEN_API_KEY')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
client = OpenAI(
    # This is the default and can be omitted
    api_key= openapi_key
)

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
    print(f"message= {message.text}")
    print(f"prompt = {prompt}")
    numbers = 1 # Dall-E-3 api only support number = 1
    task = generate_image.apply_async(args=[prompt, numbers])
    image_url = task.get()
    if image_url is not None:
        print(f"chat_id= {message.chat.id} \nphoto = {image_url}\n " +
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
        print(f"An error occured: {e}")
        response.close()

@app.task
def call_download_arxiv_pdf(paperID, dir):
    """_summary_
    task: download the pdf of the arXiv paper

    Args:
        paperID (str): e.g. 2403.03186
        dir (str): path with '/' end
    """
    try:
        print(f'Paper ID: {paperID} \n Directory: {dir}')
        paper = next(arxiv.Client().results(arxiv.Search(id_list=[paperID])))
        #print(f"Summary: {paper.summary}")
        filename = dir + paperID + '.pdf'

        # generate summary file
        summary_file = dir + paperID + '_info.txt'
        info_str = ''
        # skip if the file already exists
        if not os.path.exists(summary_file):
            with open(summary_file, 'w', encoding='utf-8') as file:
                info_str += 'title, '+ paper.title + '\n'
                info_str += ('url, ' + paper.pdf_url) + '\n'
                info_str += 'author, '
                for author in paper.authors:
                    info_str += str(author) + ', '
                info_str += '\n'
                info_str += ('summary, ' + paper.summary)
                print(info_str)
                file.write(info_str)

        # start download pdf
        paper.download_pdf(filename=filename)
        return f"Paper downloaded: {filename} \n {info_str}"

    except Exception as e:
        result = f"Error downloading arXiv PDF: {e}"
        print(result)
        return result



@bot.message_handler(commands=["start", "help"])
def start(message):
    if message.text.startswith("/help"):
        bot.reply_to(message, "/image to generate image animation\n/create generate image\n/clear - Clears old "
                              "conversations\nsend text to get replay\nsend voice to do voice"
                              "conversation")
    else:
        bot.reply_to(message, "Just start chatting to the AI or enter /help for other commands")


@bot.message_handler(commands=["model", "temperature", "maxtokens"])
def update_model(message):
    print()

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
        summary_file = pdf_path + paperID + '_info.txt'

        info_str = ''
        # skip if the file already exists
        if os.path.exists(summary_file):
            print(f"{summary_file} exists")
            with open(summary_file, 'r', encoding='utf-8') as file:
                info_str = file.read()
                print(info_str)
            reply = info_str
        else:
            print(f"start downloading arXiv PDF: {paperID} {pdf_path}")
            rlt = call_download_arxiv_pdf.delay(paperID, dir=pdf_path)
            reply = rlt.get()
        
    bot.reply_to(message, reply)

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
            bot.polling(non_stop=True, interval=0)
        except Exception as e:
            print(e)
            time.sleep(5)
            continue
