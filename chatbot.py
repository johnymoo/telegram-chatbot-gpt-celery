import os

from openai import OpenAI
from dotenv import load_dotenv
import telebot
from celery import Celery

load_dotenv()
app = Celery('chatbot', broker=os.getenv('CELERY_BROKER_URL'))

    
openapi_key = os.getenv('OPEN_API_KEY')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
client = OpenAI(
    # This is the default and can be omitted
    api_key= openapi_key
)

# Store the last 10 conversations for each user
conversations = {}


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

@bot.message_handler(commands=["start", "help"])
def start(message):
    if message.text.startswith("/help"):
        bot.reply_to(message, "/image to generate image animation\n/create generate image\n/clear - Clears old "
                              "conversations\nsend text to get replay\nsend voice to do voice"
                              "conversation")
    else:
        bot.reply_to(message, "Just start chatting to the AI or enter /help for other commands")



@bot.message_handler(func=lambda message: True)
def echo_message(message):
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
    bot.polling()
