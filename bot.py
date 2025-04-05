import os
import json
import logging
import aiohttp
import time
import jwt
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv, set_key
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()

try:
    # Конфигурация
    TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
    YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID')
    AUTHORIZED_KEY_FILE = os.getenv('AUTHORIZED_KEY_FILE')
    
    # Чтение ключа из файла
    with open(AUTHORIZED_KEY_FILE, 'r') as f:
        AUTHORIZED_KEY = json.load(f)
    
    if not all([TELEGRAM_TOKEN, YANDEX_FOLDER_ID, AUTHORIZED_KEY]):
        raise ValueError("Не все необходимые переменные окружения установлены")
        
except Exception as e:
    logger.error(f"Ошибка при загрузке конфигурации: {str(e)}")
    raise

# URL для получения IAM токена
IAM_TOKEN_URL = "https://iam.api.cloud.yandex.net/iam/v1/tokens"

# URL для API YandexGPT
YANDEXGPT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

def save_token_to_env(token: str):
    """Сохранение токена в .env файл"""
    try:
        env_file_path = '.env'
        lines = []
        if os.path.exists(env_file_path):
            with open(env_file_path, 'r') as file:
                lines = file.readlines()
        
        token_found = False
        new_lines = []
        for line in lines:
            if line.strip().startswith("IAM_TOKEN="):
                new_lines.append(f"IAM_TOKEN={token}\n")
                token_found = True
            else:
                new_lines.append(line)
        
        if not token_found:
            new_lines.append(f"IAM_TOKEN={token}\n")
        
        with open(env_file_path, 'w') as file:
            file.writelines(new_lines)
            
        logger.info("IAM токен успешно сохранен в .env файл")
    except Exception as e:
        logger.error(f"Ошибка при сохранении токена в .env: {e}")

def create_jwt_token():
    """Создание JWT токена для авторизации"""
    try:
        now = int(time.time())
        payload = {
            'aud': IAM_TOKEN_URL,
            'iss': AUTHORIZED_KEY['service_account_id'],
            'iat': now,
            'exp': now + 3600
        }
        
        encoded_token = jwt.encode(
            payload,
            AUTHORIZED_KEY['private_key'],
            algorithm='PS256',
            headers={'kid': AUTHORIZED_KEY['id']}
        )
        
        logger.info("JWT токен успешно создан")
        return encoded_token
    except Exception as e:
        logger.error(f"Ошибка при создании JWT токена: {str(e)}")
        raise

async def get_iam_token():
    """Получение IAM токена для авторизации"""
    try:
        # Подготовка данных для запроса
        data = {
            "jwt": create_jwt_token()
        }
        
        # Отправка запроса
        async with aiohttp.ClientSession() as session:
            async with session.post(IAM_TOKEN_URL, json=data) as response:
                response.raise_for_status()
                result = await response.json()
                iam_token = result["iamToken"]
                
                # Сохраняем токен в .env
                save_token_to_env(iam_token)
                
                logger.info("IAM токен успешно получен")
                return iam_token
    except Exception as e:
        logger.error(f"Ошибка при получении IAM токена: {str(e)}")
        raise

async def get_yandexgpt_response(prompt: str) -> str:
    """Получение ответа от YandexGPT"""
    try:
        # Получение IAM токена
        iam_token = await get_iam_token()
        logger.info(f"IAM токен: {iam_token}")
        
        # Подготовка заголовков
        headers = {
            "Authorization": f"Bearer {iam_token}",
            "Content-Type": "application/json"
        }
        
        # Подготовка данных для запроса
        data = {
            "modelUri": f"gpt://{YANDEX_FOLDER_ID}/yandexgpt",
            "completionOptions": {
                "temperature": 0.6,
                "maxTokens": 2000
            },
            "messages": [
                {
                    "role": "user",
                    "text": prompt
                }
            ]
        }
        
        # Отправка запроса
        async with aiohttp.ClientSession() as session:
            async with session.post(YANDEXGPT_URL, headers=headers, json=data) as response:
                response.raise_for_status()
                result = await response.json()
                logger.info("Ответ от YandexGPT успешно получен")
                return result["result"]["alternatives"][0]["message"]["text"]
    except Exception as e:
        logger.error(f"Ошибка при получении ответа от YandexGPT: {str(e)}")
        raise

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    await update.message.reply_text(
        "Привет! Я бот, использующий YandexGPT. "
        "Просто напиши мне сообщение, и я постараюсь на него ответить."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    try:
        # Получение текста сообщения
        user_message = update.message.text
        logger.info(f"Получено сообщение от пользователя: {user_message}")
        
        # Получение ответа от YandexGPT
        response = await get_yandexgpt_response(user_message)
        
        # Отправка ответа пользователю
        await update.message.reply_text(response)
        logger.info("Ответ успешно отправлен пользователю")
    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {str(e)}")
        await update.message.reply_text(
            "Извините, произошла ошибка при обработке вашего запроса. "
            "Пожалуйста, попробуйте позже."
        )

def main():
    """Основная функция"""
    try:
        # Создание приложения
        application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Добавление обработчиков
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        # Запуск бота
        logger.info("Бот запущен")
        application.run_polling()
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {str(e)}")
        raise

if __name__ == "__main__":
    main() 